#!/usr/bin/env bash
firewall_base() {
    local old
    # Keep EVERY currently configured SSH port while opening the new one.
    while read -r old; do
        valid_port "$old" || die 'Unexpected effective SSH port'
        ufw allow "$old/tcp" comment 'vps-installer SSH recovery'
    done < <(/usr/sbin/sshd -T | awk '$1=="port" {print $2}')
    ufw allow "$SSH_PORT/tcp" comment 'vps-installer SSH'
    ufw allow 80/tcp comment 'vps-installer ACME'
    ufw allow 443/tcp comment 'vps-installer HTTPS'
    ufw default deny incoming
    ufw default allow outgoing
    ufw --force enable
    # Existing rules are preserved. --check reports extra legacy openings.
}
docker_guard() {
    # Scope to our destination subnet; never flush Docker/UFW/foreign rules.
    iptables -S DOCKER-USER >/dev/null 2>&1 || die 'DOCKER-USER unavailable. Use Docker iptables backend; native nftables backend is not supported by this guard.'
    if ! iptables -S VPS-INSTALLER >/dev/null 2>&1; then iptables -N VPS-INSTALLER; fi
    # Build the chain before attaching it, and do not replace it on re-runs.
    if ! iptables -C VPS-INSTALLER -j DROP 2>/dev/null; then
        iptables -A VPS-INSTALLER -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
        iptables -A VPS-INSTALLER -p tcp -m conntrack --ctorigdstport 80 -j RETURN
        iptables -A VPS-INSTALLER -p tcp -m conntrack --ctorigdstport 443 -j RETURN
        iptables -A VPS-INSTALLER -j DROP
    fi
    iptables -C DOCKER-USER -d "$SUBNET" ! -s "$SUBNET" -j VPS-INSTALLER 2>/dev/null || \
        iptables -I DOCKER-USER 1 -d "$SUBNET" ! -s "$SUBNET" -j VPS-INSTALLER
}
install_guard_service() {
    cat >/etc/systemd/system/vps-installer-firewall.service <<EOF
[Unit]
Description=Guard vps-installer Docker publications
Requires=docker.service
After=docker.service ufw.service
PartOf=docker.service
[Service]
Type=oneshot
ExecStart=$ROOT/app/install.sh --apply-docker-firewall
RemainAfterExit=yes
[Install]
WantedBy=docker.service
EOF
    systemctl daemon-reload
    systemctl enable vps-installer-firewall.service
    docker_guard
}
