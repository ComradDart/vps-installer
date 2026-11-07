#!/usr/bin/env bash
status_stack() {
    printf 'Role: %s | domain: %s | phase: %s\n' "$ROLE" "$DOMAIN" "$(state_get phase)"
    if command -v docker >/dev/null 2>&1; then compose ps; else warn 'Docker missing'; fi
    ss -lntup
    ufw status verbose
    systemctl list-timers 'vps-installer-*' --no-pager
    if [[ $TELEMT == yes ]]; then systemctl --no-pager --full status mtproxyl-telemt.service; fi
}
check_security_updates() {
    local report="$ROOT/unattended-upgrade-check.log" code
    log "Checking automatic security updates (dry-run simulation; details: $report)"
    install -m 600 /dev/null "$report"
    if unattended-upgrade --dry-run >"$report" 2>&1; then
        log 'Automatic security-update simulation: OK (no packages installed by this check)'
    else
        code=$?
        warn "Automatic security-update simulation failed (exit $code). Last log lines:"
        tail -n 30 -- "$report" >&2
        die "Inspect $report for the full simulation output"
    fi
}
check_stack() {
    require_docker
    compose config --quiet
    [[ -s $ROOT/transport.json ]] || die 'No managed transport selected; run --configure-xray first'
    local mode
    local -a extra=()
    if [[ $TELEMT == yes ]]; then extra=(--telemt); fi
    mode=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["mode"])' "$ROOT/transport.json")
    python3 "$APP/helpers/publications.py" "$mode" "${extra[@]}"
    python3 "$APP/helpers/db.py" integrity "$ROOT/db/x-ui.db"
    python3 "$APP/helpers/db.py" single-user "$ROOT/db/x-ui.db"
    docker exec vps-nginx nginx -t
    ssh_effective
    /usr/sbin/sshd -t
    ufw status | rg -q '^Status: active$' || die 'UFW is not active'
    ufw status verbose | rg -q 'Default: deny \(incoming\), allow \(outgoing\)' || die 'Unexpected UFW defaults'
    python3 "$APP/helpers/ufw_rules.py" "$SSH_PORT" "${extra[@]}"
    iptables -C DOCKER-USER -d "$SUBNET" ! -s "$SUBNET" -j VPS-INSTALLER
    iptables -C VPS-INSTALLER -j DROP
    fail2ban-client status sshd
    chronyc waitsync 5 0.5 0 2
    chronyc tracking
    validate_certificate
    curl --noproxy '*' --fail --silent --show-error --max-time 10 --http2 \
        --resolve "$DOMAIN:8443:127.0.0.1" "https://$DOMAIN:8443/" -o /dev/null \
        -w '%{http_version}\n' | rg -qx 2 || die 'Origin HTTP/2 HTTPS check failed'
    python3 "$APP/helpers/listeners.py" "$SSH_PORT" "${extra[@]}"
    systemctl is-active --quiet vps-installer-renew.timer vps-installer-backup.timer
    python3 "$APP/helpers/automation.py" check "$ROOT"
    if [[ $TELEMT == yes ]]; then python3 "$APP/helpers/telemt.py" check "$ROOT"; fi
    # Evaluate effective unattended-upgrades configuration without upgrading packages.
    check_security_updates
    warn 'MANUAL: external scan of SSH/HTTPS and closed panel ports; actual VPS restore and renewal test.'
}

access_instructions() {
    log "HTTPS site: https://$DOMAIN/"
    log "Panel: ssh -N -L 2053:127.0.0.1:2053 -p $SSH_PORT $ADMIN@$PUBLIC_IP"
    log 'Then browse http://127.0.0.1:2053/ . Verified device URI: use --show-client.'
}
