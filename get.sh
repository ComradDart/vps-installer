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
import shutil,sys,tarfile
archive,root=sys.argv[1:];root=Path(root)
with tarfile.open(archive,'r:gz') as tar:
    members=tar.getmembers();seen=set();total=0
    for member in members:
        parts=PurePosixPath(member.name).parts
        if not parts or parts[0]!='vps-installer-main' or '..' in parts or PurePosixPath(member.name).is_absolute():
            raise SystemExit('Unsafe archive path')
        if member.name in seen or not (member.isdir() or member.isfile()):raise SystemExit('Unsafe archive entry')
        seen.add(member.name);total+=member.size
    if total>64*1024*1024:raise SystemExit('Unexpected archive size')
    for member in members:
        dest=root/member.name
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
        printf 'Usage: sudo bash get.sh [installer arguments]\nDownloads the current official ComradDart/vps-installer source into a temporary directory.\nNo Git required. Targets: Debian 12/13, Ubuntu 24.04/26.04 LTS.\n'
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
    local package command missing=no
    for command in python3 flock; do command -v "$command" >/dev/null 2>&1 || missing=yes; done
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then missing=yes; fi
    if [[ ! -s /etc/ssl/certs/ca-certificates.crt ]]; then missing=yes; fi
    if [[ $missing == yes ]]; then
        export DEBIAN_FRONTEND=noninteractive
        printf '[+] Installing bootstrap prerequisites (no Git)\n'
        apt-get update
        apt-get install -y --no-install-recommends ca-certificates curl python3 util-linux
    fi
    package="$BOOTSTRAP_TEMP/source.tar.gz"
    local url=https://codeload.github.com/ComradDart/vps-installer/tar.gz/refs/heads/main
    printf '[+] Downloading ComradDart/vps-installer from GitHub over HTTPS\n'
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
            --connect-timeout 20 --max-time 180 --retry 2 "$url" -o "$package"
    else
        wget --https-only --timeout=30 --tries=3 -O "$package" "$url"
    fi
    bootstrap_extract "$package" "$BOOTSTRAP_TEMP"
    # Keep the parent process for guaranteed temporary-directory cleanup.
    bash "$BOOTSTRAP_TEMP/vps-installer-main/install.sh" "$@"
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then bootstrap_main "$@"; fi
