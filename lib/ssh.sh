#!/usr/bin/env bash
# State flags are consumed by common.sh cleanup across module boundaries.
# shellcheck disable=SC2034
setup_user() {
    local home group password input keyfile
    if ! id "$ADMIN" >/dev/null 2>&1; then
        adduser --disabled-password --gecos '' "$ADMIN"
    fi
    (( $(id -u "$ADMIN") >= 1000 )) || die 'Refusing an existing system account'
    usermod -aG sudo "$ADMIN"
    home=$(getent passwd "$ADMIN" | cut -d: -f6); group=$(id -gn "$ADMIN")
    [[ $home == /home/* && ! -L $home && ! -L $home/.ssh && ! -L $home/.ssh/authorized_keys ]] || die 'Unsafe admin home/SSH path'
    if [[ $(passwd -S "$ADMIN" | awk '{print $2}') != P ]]; then
        secret password "Set sudo password for $ADMIN"
        printf '%s:%s\n' "$ADMIN" "$password" | chpasswd
        unset password
    fi
    install -d -m 700 -o "$ADMIN" -g "$group" "$home/.ssh"
    keyfile="$home/.ssh/authorized_keys"
    if [[ ! -s $keyfile ]]; then
        ask input 'Copy plain root public keys? Options-prefixed keys require manual review' no
        if [[ $input == yes ]]; then
            valid_key_file /root/.ssh/authorized_keys || die 'Root keys contain options/invalid lines. Supply a reviewed public key instead.'
            install -m 600 -o "$ADMIN" -g "$group" /root/.ssh/authorized_keys "$keyfile"
        else
            ask input 'Paste one public SSH key (not a private key)'
            printf '%s\n' "$input" >"$TMPDIR_TASK/new-key"
            valid_key_file "$TMPDIR_TASK/new-key" || die 'Invalid SSH public key'
            install -m 600 -o "$ADMIN" -g "$group" "$TMPDIR_TASK/new-key" "$keyfile"
        fi
    else
        ssh-keygen -l -f "$keyfile" >/dev/null || die 'Existing authorized_keys is invalid'
        chmod 600 "$keyfile"; chown "$ADMIN:$group" "$keyfile"
    fi
}
reload_ssh() {
    /usr/sbin/sshd -t
    systemctl daemon-reload
    if systemctl is-active --quiet ssh.socket; then
        systemctl restart ssh.socket
    fi
    systemctl reload-or-restart ssh.service
}
ssh_effective() {
    local effective key value client
    client=${SSH_CONNECTION:-127.0.0.1}; client=${client%% *}
    effective=$(/usr/sbin/sshd -T -C "user=$ADMIN,host=$DOMAIN,addr=$client")
    for key in permitrootlogin:no passwordauthentication:no pubkeyauthentication:yes kbdinteractiveauthentication:no x11forwarding:no maxauthtries:3; do
        value=${key#*:}; key=${key%%:*}
        rg -q "^$key $value$" <<<"$effective" || die "Effective SSH setting differs: $key. Inspect main config, earlier drop-ins and Match blocks."
    done
    rg -q "^port $SSH_PORT$" <<<"$effective" || die 'Selected SSH port missing from effective configuration'
    effective=$(/usr/sbin/sshd -T -C "user=root,host=$DOMAIN,addr=$client")
    rg -q '^permitrootlogin no$' <<<"$effective" || die 'A Match block still permits root SSH'
}
ssh_gate() {
    local token reply
    token=$(openssl rand -hex 16)
    python3 "$APP/helpers/ssh_gate.py" create "$ROOT" "$token" "$ADMIN" "$SSH_PORT"
    cat <<EOF
Open a NEW terminal; keep this session open. Force key authentication:
  ssh -o ControlMaster=no -o ControlPath=none -o PreferredAuthentications=publickey -o PasswordAuthentication=no -p $SSH_PORT $ADMIN@$PUBLIC_IP
In that NEW session execute (also verifies sudo):
  sudo $ROOT/app/install.sh --confirm-ssh $token "\$SSH_CONNECTION"
EOF
    ask reply 'After the confirmation command succeeds, type VERIFIED'
    [[ $reply == VERIFIED && -f $ROOT/ssh-gate.ack ]] || die 'New SSH key login has not been verified'
    rm -f "$ROOT/ssh-gate.json" "$ROOT/ssh-gate.ack"
}
setup_ssh() {
    install -d -m 755 /run/sshd /etc/ssh/sshd_config.d
    if [[ $(state_get phase) != configured ]]; then ssh_effective; return 0; fi
    local oldports
    oldports=$(/usr/sbin/sshd -T | awk '$1=="port" {print $2}')
    # Entire SSH tree backed up; rollback touches only this installer's drop-in.
    if [[ -f /etc/ssh/sshd_config.d/00-vps-installer.conf ]]; then
        cp -a /etc/ssh/sshd_config.d/00-vps-installer.conf "$ROOT/ssh-before.conf"
    else rm -f "$ROOT/ssh-before.conf"; fi
    cat >"$ROOT/ssh-rollback.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ -f /opt/vps-installer/ssh-before.conf ]]; then
    cp -a /opt/vps-installer/ssh-before.conf /etc/ssh/sshd_config.d/00-vps-installer.conf
else rm -f /etc/ssh/sshd_config.d/00-vps-installer.conf; fi
/usr/sbin/sshd -t
systemctl daemon-reload
if systemctl is-active --quiet ssh.socket; then systemctl restart ssh.socket; fi
systemctl reload-or-restart ssh.service
EOF
    chmod 700 "$ROOT/ssh-rollback.sh"
    systemd-run --unit=vps-installer-ssh-rollback --on-active=10m "$ROOT/ssh-rollback.sh"
    SSH_PENDING=yes
    {
        printf '# Installer staging: existing authentication is retained\n'
        printf 'Port %s\n' "$SSH_PORT"
        while read -r p; do [[ $p == "$SSH_PORT" ]] || printf 'Port %s\n' "$p"; done <<<"$oldports"
        printf 'PubkeyAuthentication yes\n'
    } >/etc/ssh/sshd_config.d/00-vps-installer.conf
    reload_ssh
    ssh_gate
    cat >/etc/ssh/sshd_config.d/00-vps-installer.conf <<EOF
Port $SSH_PORT
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
X11Forwarding no
MaxAuthTries 3
LoginGraceTime 30
EOF
    /usr/sbin/sshd -t
    ssh_effective
    reload_ssh
    # A second connection proves that restrictions did not break key login.
    ssh_gate
    systemctl is-active --quiet vps-installer-ssh-rollback.timer || die 'SSH rollback timer expired; rerun from the retained session'
    ssh_effective
    systemctl stop vps-installer-ssh-rollback.timer
    SSH_PENDING=no
    state_set phase ssh-ready
    warn 'Old SSH firewall rules retained for recovery. Audit/remove obsolete rules manually.'
}
