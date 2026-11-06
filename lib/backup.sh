#!/usr/bin/env bash
# Transaction flags are consumed by common.sh cleanup.
# shellcheck disable=SC2034
backup_stack() {
    log 'Creating root-only local backup (includes credentials, keys and certificates)'
    python3 "$APP/helpers/backup.py" create "$ROOT" "$BACKUPS"
    warn 'Backups contain secrets. Copy them off-server with encryption; no automatic pruning.'
}
restore_stack() {
    local archive=$1 stage old
    [[ $archive == /* && -f $archive ]] || die 'Use an absolute backup archive path'
    stage=$(mktemp -d /opt/.vps-installer-restore.XXXXXX)
    RESTORE_STAGE=$stage
    if ! python3 "$APP/helpers/backup.py" extract "$archive" "$stage"; then
        rm -rf -- "$stage"; die 'Restore validation failed before changing the live stack'
    fi
    # Restoring another identity/role/network could break SSH and firewall.
    if ! python3 - "$STATE" "$stage/stack/state.json" <<'EOF'
import json,sys
old,new=(json.load(open(p)) for p in sys.argv[1:])
for key in ('role','domain','ssh_port','admin','public_ip','subnet'):
    assert old[key]==new[key], 'Identity change requires a manual recovery plan: '+key
EOF
    then rm -rf -- "$stage"; die 'Backup belongs to a different stack identity'; fi
    confirm 'Restore stack DB/site/certs/config/code from this backup? System SSH/UFW and legacy services are left as they are'
    backup_stack
    compose down
    old="$ROOT.before-restore.$(date -u +%Y%m%dT%H%M%SZ).$$"
    RESTORE_OLD=$old
    mv -- "$ROOT" "$old"
    mv -- "$stage/stack" "$ROOT"
    if ! (load_state && compose config --quiet && compose up -d && wait_healthy vps-xui && wait_healthy vps-nginx && docker exec vps-nginx nginx -t); then
        compose down || true
        mv -- "$ROOT" "$stage/failed-stack"
        mv -- "$old" "$ROOT"
        RESTORE_OLD=''
        RESTORE_STAGE=''
        compose up -d
        warn "Failed restore retained at $stage"
        die 'Restore failed; previous stack restored'
    fi
    RESTORE_OLD=''
    rm -rf -- "$stage"
    RESTORE_STAGE=''
    log "Restored. Previous tree retained at $old; SSH and firewall not restored automatically."
}
install_backup_timer() {
    cat >/etc/systemd/system/vps-installer-backup.service <<EOF
[Unit]
Description=Snapshot vps-installer data
[Service]
Type=oneshot
ExecStart=$ROOT/app/install.sh --backup
UMask=0077
EOF
    cat >/etc/systemd/system/vps-installer-backup.timer <<'EOF'
[Unit]
Description=Daily local stack backup
[Timer]
OnCalendar=daily
RandomizedDelaySec=30m
Persistent=true
[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now vps-installer-backup.timer
}
uninstall_stack() {
    printf 'Remove ONLY: vps-xui, vps-nginx, their Compose network, managed renewal/backup/firewall units.\n'
    printf 'KEEP: %s (DB, site, certificates, code), %s, SSH, users, UFW rules, Docker and legacy services.\n' "$ROOT" "$BACKUPS"
    confirm 'Stop and uninstall this managed stack? Data are preserved; deletion must be performed separately by the administrator'
    backup_stack
    systemctl disable --now vps-installer-renew.timer vps-installer-backup.timer vps-installer-firewall.service
    compose down
    # The detached subnet is no longer used. Do not flush or delete a shared chain.
    if iptables -C DOCKER-USER -d "$SUBNET" ! -s "$SUBNET" -j VPS-INSTALLER 2>/dev/null; then
        iptables -D DOCKER-USER -d "$SUBNET" ! -s "$SUBNET" -j VPS-INSTALLER
    fi
    rm -f /etc/systemd/system/vps-installer-renew.{service,timer} \
        /etc/systemd/system/vps-installer-backup.{service,timer} /etc/systemd/system/vps-installer-firewall.service
    systemctl daemon-reload
    log 'Stack stopped/uninstalled; data, host security and all legacy services retained'
}
