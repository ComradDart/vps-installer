#!/usr/bin/env bash
status_stack() {
    printf 'Role: %s | domain: %s | phase: %s\n' "$ROLE" "$DOMAIN" "$(state_get phase)"
    if command -v docker >/dev/null 2>&1; then compose ps; else warn 'Docker missing'; fi
    ss -lntup
    ufw status verbose
    systemctl list-timers 'vps-installer-*' --no-pager
}
check_stack() {
    require_docker
    compose config --quiet
    python3 "$APP/helpers/publications.py"
    python3 "$APP/helpers/db.py" integrity "$ROOT/db/x-ui.db"
    docker exec vps-nginx nginx -t
    ssh_effective
    /usr/sbin/sshd -t
    ufw status | rg -q '^Status: active$' || die 'UFW is not active'
    ufw status verbose | rg -q 'Default: deny \(incoming\), allow \(outgoing\)' || die 'Unexpected UFW defaults'
    python3 "$APP/helpers/ufw_rules.py" "$SSH_PORT"
    iptables -C DOCKER-USER -d "$SUBNET" ! -s "$SUBNET" -j VPS-INSTALLER
    iptables -C VPS-INSTALLER -j DROP
    fail2ban-client status sshd
    chronyc waitsync 5 0.5 0 2
    chronyc tracking
    validate_certificate
    curl --noproxy '*' --fail --silent --show-error --max-time 10 --http2 \
        --resolve "$DOMAIN:8443:127.0.0.1" "https://$DOMAIN:8443/" -o /dev/null \
        -w '%{http_version}\n' | rg -qx 2 || die 'Origin HTTP/2 HTTPS check failed'
    python3 "$APP/helpers/listeners.py" "$SSH_PORT"
    systemctl is-active --quiet vps-installer-renew.timer vps-installer-backup.timer
    # Evaluate effective unattended-upgrades configuration without upgrading packages.
    unattended-upgrade --dry-run >/dev/null
    warn 'MANUAL: external scan of SSH/HTTPS and closed panel ports; actual VPS restore and renewal test.'
}

access_instructions() {
    log "HTTPS site: https://$DOMAIN/"
    log "Panel: ssh -N -L 2053:127.0.0.1:2053 -p $SSH_PORT $ADMIN@$PUBLIC_IP"
    log 'Then browse http://127.0.0.1:2053/ . Configure any Xray inbounds yourself.'
}
