#!/usr/bin/env bash
# shellcheck disable=SC2034
readonly ROOT=/opt/vps-installer
readonly STATE="$ROOT/state.json"
readonly BACKUPS=/var/backups/vps-installer
TMPDIR_TASK=''
SSH_PENDING=no
RESET_PENDING=no
RESTORE_STAGE=''
RESTORE_OLD=''
log() { printf '[+] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
die() { warn "$*"; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Required command missing: $1"; }
ask() {
    local _answer
    read -r -p "$2${3:+ [$3]}: " _answer </dev/tty || die 'Terminal input closed'
    printf -v "$1" '%s' "${_answer:-${3:-}}"
}
confirm() { local reply; ask reply "$1 (type YES)"; [[ $reply == YES ]] || die 'Cancelled'; }
secret() {
    local one two
    read -r -s -p "$2: " one </dev/tty || die 'Terminal input closed'; printf '\n' >/dev/tty
    read -r -s -p 'Repeat: ' two </dev/tty || die 'Terminal input closed'; printf '\n' >/dev/tty
    [[ $one == "$two" ]] || die 'Passwords differ'
    valid_password "$one" || die 'Use 16–72 printable ASCII bytes, without colon'
    printf -v "$1" '%s' "$one"
}
valid_domain() { python3 "$APP/helpers/state.py" domain "$1"; }
valid_port() { [[ $1 =~ ^[1-9][0-9]{0,4}$ ]] && ((10#$1 <= 65535)); }
valid_user() { [[ $1 =~ ^[a-z][a-z0-9_-]{0,30}$ && $1 != root ]]; }
valid_panel_user() { [[ $1 =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]{2,31}$ ]]; }
valid_password() { local LC_ALL=C; [[ $1 =~ ^[\ -~]{16,72}$ && $1 != *:* ]]; }
generate_password() { openssl rand -hex 24; }
valid_key_file() {
    local key line count=0
    [[ -s $1 ]] || return 1
    while IFS= read -r line || [[ -n $line ]]; do
        [[ -z $line || $line == \#* ]] && continue
        # An options-prefixed root key is never silently turned into an unrestricted key.
        [[ $line =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com)\  ]] || return 1
        key=$(mktemp "$TMPDIR_TASK/key.XXXXXX")
        printf '%s\n' "$line" >"$key"
        if ! ssh-keygen -l -f "$key" >/dev/null 2>&1; then rm -f -- "$key"; return 1; fi
        rm -f -- "$key"; count=$((count + 1))
    done <"$1"
    ((count > 0))
}
state_get() { python3 "$APP/helpers/state.py" get "$STATE" "$1"; }
state_set() { python3 "$APP/helpers/state.py" set "$STATE" "$1" "$2"; }
load_state() {
    [[ -f $STATE && ! -L $STATE ]] || die "Missing or symlink state: $STATE"
    [[ $(stat -c %u "$STATE") == 0 && $(stat -c %a "$STATE") == 600 ]] || die 'State must be root-owned, mode 600'
    python3 "$APP/helpers/state.py" validate "$STATE"
    ROLE=$(state_get role); DOMAIN=$(state_get domain)
    ADMIN=$(state_get admin); SSH_PORT=$(state_get ssh_port); PUBLIC_IP=$(state_get public_ip)
    EMAIL=$(state_get email); SUBNET=$(state_get subnet)
    XUI_IMAGE=$(state_get xui_image); NGINX_IMAGE=$(state_get nginx_image)
}
cleanup() {
    local code=$?
    trap - EXIT INT TERM HUP ERR
    if [[ -n $RESTORE_OLD && -d $RESTORE_OLD ]]; then
        if [[ -d $ROOT ]]; then
            compose down || true
            mv -- "$ROOT" "$RESTORE_STAGE/interrupted-stack"
        fi
        mv -- "$RESTORE_OLD" "$ROOT"
        compose up -d || warn 'Interrupted restore rollback requires manual recovery'
        RESTORE_STAGE=''
    fi
    if [[ -n $RESTORE_STAGE && -d $RESTORE_STAGE ]]; then rm -rf -- "$RESTORE_STAGE"; fi
    if [[ $RESET_PENDING == yes ]]; then
        if [[ -s $TMPDIR_TASK/xui-before.db ]]; then
            restore_db_after_failed_reset || warn 'Reset rollback failed; use the latest backup'
        else compose start xui || true; fi
    fi
    if [[ $SSH_PENDING == yes && -x $ROOT/ssh-rollback.sh ]]; then
        "$ROOT/ssh-rollback.sh" || warn "SSH rollback failed; use provider console: $ROOT/ssh-rollback.sh"
        systemctl stop vps-installer-ssh-rollback.timer || true
    fi
    if [[ -n $TMPDIR_TASK && -d $TMPDIR_TASK ]]; then rm -rf -- "$TMPDIR_TASK"; fi
    ((code == 0)) || warn "Stopped (exit $code). Existing data retained. Inspect --status and backups in $BACKUPS."
    exit "$code"
}
init_runtime() {
    [[ $EUID == 0 ]] || die 'Run with sudo on the target VPS'
    need python3; need flock
    install -d -m 700 "$ROOT" "$BACKUPS"
    exec 9>/run/lock/vps-installer.lock
    flock -n 9 || die 'Another operation is running'
    TMPDIR_TASK=$(mktemp -d /run/vps-installer.XXXXXX)
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    trap 'warn "Operation failed at line $LINENO (command arguments are not logged)"' ERR
}
supported_os() {
    case "$1:$2" in
        debian:12|debian:13|ubuntu:24.04|ubuntu:26.04) return 0;;
        *) return 1;;
    esac
}
require_supported_os() {
    supported_os "$1" "$2" || die "Detected ${3:-Linux} (ID=$1 VERSION_ID=$2). Supported targets: Debian 12/13, Ubuntu 24.04/26.04 LTS."
}
preflight() {
    # os-release is supplied by the OS, never by a user state file.
    # shellcheck disable=SC1091
    . /etc/os-release
    require_supported_os "${ID:-unknown}" "${VERSION_ID:-unknown}" "${PRETTY_NAME:-Linux}"
    [[ $(dpkg --print-architecture) == amd64 || $(dpkg --print-architecture) == arm64 ]] || die 'Only amd64 and arm64 supported'
    [[ -d /run/systemd/system ]] || die 'A systemd VPS is required; containers are for tests only'
    (( $(df -Pm /opt | awk 'NR==2 {print $4}') >= 4096 )) || die 'Need at least 4 GiB free in /opt'
    [[ -z ${SUDO_USER:-} || ${SUDO_USER} == root ]] || log 'Keep this session open until SSH verification finishes'
}
install_app() {
    [[ $APP == "$ROOT/app" ]] && return 0
    install -d -m 700 "$ROOT/app"
    cp -a "$APP/." "$ROOT/app/"
    chown -R root:root "$ROOT/app"
    chmod 700 "$ROOT/app/install.sh" "$ROOT/app/vps_setup.sh"
    APP="$ROOT/app"
}
