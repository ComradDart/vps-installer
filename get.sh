#!/usr/bin/env bash
# Download this file first, then run it; no curl|bash, Git or source-directory overwrite.
set +x
set -Eeuo pipefail
umask 077
bootstrap_supported_os() {
    case "$1:$2" in
        debian:12|debian:13|ubuntu:24.04|ubuntu:26.04) return 0;;
        *) return 1;;
    esac
}
bootstrap_cleanup() {
    local code=$?
    trap - EXIT INT TERM HUP
    if [[ -n ${BOOTSTRAP_TEMP:-} && -d $BOOTSTRAP_TEMP ]]; then rm -rf -- "$BOOTSTRAP_TEMP"; fi
    exit "$code"
}
bootstrap_extract() {
    python3 - "$1" "$2" <<'PY'
from pathlib import Path,PurePosixPath
import re,shutil,sys,tarfile
archive,root=sys.argv[1:];root=Path(root)
with tarfile.open(archive,'r:gz') as tar:
    members=tar.getmembers();seen=set();total=0;source=None
    for member in members:
        parts=PurePosixPath(member.name).parts
        if not parts or '..' in parts or PurePosixPath(member.name).is_absolute():
            raise SystemExit('Unsafe archive path')
        if parts[0]!='vps-installer-main' and not re.fullmatch(r'ComradDart-vps-installer-[0-9a-f]{7,40}',parts[0],re.I):raise SystemExit('Unexpected repository archive')
        if source is not None and source!=parts[0]:raise SystemExit('Multiple archive roots')
        source=parts[0]
        if member.name in seen or not (member.isdir() or member.isfile()):raise SystemExit('Unsafe archive entry')
        seen.add(member.name);total+=member.size
    if total>64*1024*1024:raise SystemExit('Unexpected archive size')
    for member in members:
        dest=root/'vps-installer-main'/Path(*PurePosixPath(member.name).parts[1:])
        if member.isdir():dest.mkdir(parents=True,exist_ok=True,mode=0o700)
        else:
            dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with tar.extractfile(member) as src,dest.open('xb') as dst:shutil.copyfileobj(src,dst)
            dest.chmod(member.mode&0o755)
if not (root/'vps-installer-main/install.sh').is_file():raise SystemExit('Installer missing in archive')
PY
}
bootstrap_main() {
    if [[ ${1:-} == --help || ${1:-} == -h ]]; then
        printf 'Usage: sudo bash get.sh [installer arguments]\nDownloads ComradDart/vps-installer main into a temporary directory; no Git required.\nPrivate repository: supply GH_TOKEN (or GITHUB_TOKEN) with Contents: read access.\nTargets: Debian 12/13, Ubuntu 24.04/26.04 LTS.\n'
        return 0
    fi
    [[ $EUID == 0 ]] || { printf 'Run with sudo: sudo bash get.sh\n' >&2; return 1; }
    # shellcheck disable=SC1091
    . /etc/os-release
    if ! bootstrap_supported_os "${ID:-unknown}" "${VERSION_ID:-unknown}"; then
        printf 'Detected %s (ID=%s VERSION_ID=%s). Supported: Debian 12/13, Ubuntu 24.04/26.04 LTS.\n' \
            "${PRETTY_NAME:-Linux}" "${ID:-unknown}" "${VERSION_ID:-unknown}" >&2
        return 1
    fi
    printf '[+] Detected %s\n' "${PRETTY_NAME:-Linux}"
    printf '[!] TLS needs HTTP-01 on port 80. Cloudflare Proxy must allow the ACME path; use DNS only for first issuance if redirects or challenges interfere.\n'
    BOOTSTRAP_TEMP=$(mktemp -d /tmp/vps-bootstrap.XXXXXX)
    trap bootstrap_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM HUP
    local package command missing=no token=${GH_TOKEN:-${GITHUB_TOKEN:-}} auth_config=''
    unset GH_TOKEN GITHUB_TOKEN
    [[ -z $token || $token =~ ^[A-Za-z0-9_]+$ ]] || { printf 'Invalid GitHub token format\n' >&2; return 1; }
    for command in python3 flock; do command -v "$command" >/dev/null 2>&1 || missing=yes; done
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then missing=yes; fi
    if [[ -n $token ]] && ! command -v curl >/dev/null 2>&1; then missing=yes; fi
    if [[ ! -s /etc/ssl/certs/ca-certificates.crt ]]; then missing=yes; fi
    if [[ $missing == yes ]]; then
        export DEBIAN_FRONTEND=noninteractive
        printf '[+] Installing bootstrap prerequisites (no Git)\n'
        apt-get update
        apt-get install -y --no-install-recommends ca-certificates curl python3 util-linux
    fi
    package="$BOOTSTRAP_TEMP/source.tar.gz"
    local url=https://codeload.github.com/ComradDart/vps-installer/tar.gz/refs/heads/main
    local -a auth_args=()
    if [[ -n $token ]]; then
        url=https://api.github.com/repos/ComradDart/vps-installer/tarball/main
        auth_config="$BOOTSTRAP_TEMP/github-curl.conf"
        printf 'header = "Authorization: Bearer %s"\n' "$token" >"$auth_config"
        chmod 600 "$auth_config"
        auth_args=(--config "$auth_config")
    fi
    unset token
    printf '[+] Downloading ComradDart/vps-installer from GitHub over HTTPS\n'
    if command -v curl >/dev/null 2>&1; then
        if ! curl "${auth_args[@]}" --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
            --connect-timeout 20 --max-time 180 --retry 2 "$url" -o "$package"; then
            printf 'Download failed. A private repository requires GH_TOKEN with Contents: read, or download its ZIP while signed into GitHub.\n' >&2
            return 1
        fi
    else
        wget --https-only --timeout=30 --tries=3 -O "$package" "$url"
    fi
    [[ -z $auth_config ]] || rm -f -- "$auth_config"
    bootstrap_extract "$package" "$BOOTSTRAP_TEMP"
    # Keep the parent process for guaranteed temporary-directory cleanup.
    bash "$BOOTSTRAP_TEMP/vps-installer-main/install.sh" "$@"
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then bootstrap_main "$@"; fi
