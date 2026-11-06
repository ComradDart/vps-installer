#!/usr/bin/env bash
base_packages() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates curl gnupg openssl sudo ufw fail2ban \
        unattended-upgrades chrony python3-systemd jq nftables iptables openssh-server dnsutils python3 python3-bcrypt \
        sqlite3 rsync ripgrep certbot
    # No blanket apt upgrade, dist-upgrade, kernel hold, or scheduled reboot.
}
wait_fail2ban() {
    local timeout=${1:-30} deadline
    deadline=$((SECONDS + timeout))
    log 'Waiting for fail2ban socket and sshd jail readiness'
    while ((SECONDS < deadline)); do
        if fail2ban-client ping >/dev/null 2>&1 && fail2ban-client status sshd >/dev/null 2>&1; then
            fail2ban-client status sshd
            return 0
        fi
        if systemctl is-failed --quiet fail2ban.service; then break; fi
        sleep 1
    done
    warn "fail2ban did not become ready within ${timeout}s; service diagnostics follow"
    systemctl status fail2ban.service --no-pager -l >&2 || true
    journalctl -u fail2ban.service -n 50 --no-pager >&2 || true
    if [[ -r /var/log/fail2ban.log ]]; then tail -n 50 /var/log/fail2ban.log >&2 || true; fi
    die 'fail2ban socket/sshd jail unavailable. Installation stopped; inspect the diagnostics above.'
}
hardening() {
    cat >/etc/sysctl.d/99-vps-installer.conf <<'EOF'
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
EOF
    if modprobe tcp_bbr 2>/dev/null && sysctl -n net.ipv4.tcp_available_congestion_control | rg -qw bbr; then
        printf 'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr\n' >>/etc/sysctl.d/99-vps-installer.conf
    else warn 'BBR unavailable; retaining kernel congestion control'; fi
    sysctl -p /etc/sysctl.d/99-vps-installer.conf
    # Xray is an application proxy. Installer does not enable host forwarding;
    # Docker itself manages forwarding needed by its bridge networks.
    systemctl enable --now chrony
    cat >/etc/apt/apt.conf.d/52vps-installer <<'EOF'
#clear Unattended-Upgrade::Allowed-Origins;
#clear Unattended-Upgrade::Origins-Pattern;
Unattended-Upgrade::Origins-Pattern {
    "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
    "origin=Ubuntu,archive=${distro_codename}-security";
    "origin=UbuntuESMApps,archive=${distro_codename}-apps-security";
    "origin=UbuntuESM,archive=${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
EOF
    cat >/etc/apt/apt.conf.d/20vps-installer-auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
    systemctl enable --now unattended-upgrades
    cat >/etc/fail2ban/jail.d/vps-installer.local <<EOF
[sshd]
enabled = true
backend = systemd
port = $SSH_PORT
maxretry = 3
findtime = 10m
bantime = 1h
banaction = ufw
EOF
    fail2ban-client -t
    systemctl enable fail2ban
    systemctl restart fail2ban
    wait_fail2ban
}
