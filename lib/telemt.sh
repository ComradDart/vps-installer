#!/usr/bin/env bash
# No actions at source time. OUTBOUND and the default "no" path do not install anything.
telemt_offer() {
    [[ ${ROLE:-} == inbound ]] || return 0
    if python3 -c 'import json,sys;sys.exit(0 if "telemt" in json.load(open(sys.argv[1])) else 1)' "$STATE"; then return 0; fi
    local reply
    ask reply 'Установить telemt/MTProxyL на TCP9443 через существующий OUTBOUND? yes/no' no
    case "${reply,,}" in
        yes|y|да) TELEMT=yes;;
        no|n|нет) TELEMT=no;;
        *) die 'Choose yes or no';;
    esac
    state_set telemt "$TELEMT"
}
telemt_manager() {
    if ! /usr/local/bin/mtproxyl "$@" >>"$ROOT/telemt-install.log" 2>&1; then
        die "MTProxyL step failed. Private details: $ROOT/telemt-install.log. Existing VPS relay was not reconfigured."
    fi
}
setup_telemt() {
    [[ $TELEMT == yes ]] || return 0
    [[ $ROLE == inbound ]] || die 'telemt is supported only on INBOUND'
    local kind
    local -a packages=()
    kind=$(python3 "$APP/helpers/telemt.py" preflight "$ROOT")
    log 'telemt: preserving the existing VPS relay. Adding local SOCKS may briefly restart xui; nginx, SSH and OUTBOUND stay as configured.'
    python3 "$APP/helpers/telemt.py" configure "$ROOT"
    if [[ $kind == fresh ]]; then
        # Dependencies are exclusive to the opted-in native manager.
        if ! command -v jq >/dev/null 2>&1; then packages+=(jq); fi
        if ! command -v nano >/dev/null 2>&1 && ! command -v vim >/dev/null 2>&1; then packages+=(nano); fi
        if ((${#packages[@]})); then
            NEEDRESTART_MODE=l apt-get install -y "${packages[@]}"
        fi
        install -m 600 /dev/null "$ROOT/telemt-install.log"
        curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
            --max-time 60 https://raw.githubusercontent.com/Liafanx/MTProxyL/main/install.sh -o "$TMPDIR_TASK/mtproxyl-install.sh"
        bash -n "$TMPDIR_TASK/mtproxyl-install.sh"
        # Upstream uses a fixed /tmp log. Refuse symlinks/foreign files before
        # executing it as root; the sticky directory protects our root-owned file.
        python3 - <<'PY'
import os,stat
fd=os.open('/tmp/mtproxyl-install.log',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
try:
    s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_nlink!=1:
        raise SystemExit('Unsafe /tmp/mtproxyl-install.log; bootstrap stopped')
    os.fchmod(fd,0o600)
finally:os.close(fd)
PY
        # Bootstrap the latest CLI only; --help prevents its interactive installer.
        if ! env -u MTPROXYL_VERSION -u MTPROXYL_BRANCH bash "$TMPDIR_TASK/mtproxyl-install.sh" -- --help >>"$ROOT/telemt-install.log" 2>&1; then
            die "MTProxyL bootstrap failed; private log: $ROOT/telemt-install.log"
        fi
        need /usr/local/bin/mtproxyl
        telemt_manager expert set general use_middle_proxy false --no-apply
        telemt_manager expert set censorship mask_host 127.0.0.1 --no-apply
        telemt_manager expert set censorship mask_port 8443 --no-apply
        telemt_manager expert set censorship tls_fetch_scope local-mask --no-apply
        telemt_manager upstream add xray socks5 127.0.0.1:1080
        telemt_manager upstream disable direct
        telemt_manager upstream add local-mask direct '' '' '' 1 '' local-mask
        TELEMT_NEW=yes
        telemt_manager install --mode manager --engine binary --service-name standard \
            --proxy-mode mtproto --port 9443 --host "$DOMAIN" --sni "$DOMAIN" \
            --zapret2 no --syn-limiter off --meko no --web no --api no
    fi
    python3 "$APP/helpers/telemt.py" check "$ROOT"
    # Native host INPUT traffic: do not open 9443 in Docker's forwarding guard.
    ufw allow 9443/tcp comment 'vps-installer telemt'
    state_set telemt yes
    TELEMT_NEW=no
    log 'telemt ready on TCP9443. Client links: sudo mtproxyl secret link (contains secrets).'
}
