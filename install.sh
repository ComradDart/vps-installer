#!/usr/bin/env bash
# Never inherit tracing into credential handling, even with bash -x.
set +x
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
# This installer always targets the local VPS daemon, preserving registry auth config.
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH
export DOCKER_HOST=unix:///var/run/docker.sock
APP=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=lib/common.sh
source "$APP/lib/common.sh"
for module in hardening ssh firewall docker xui nginx certificates backup checks automation; do
    # shellcheck source=/dev/null
    source "$APP/lib/$module.sh"
done
usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [command]
  (none)                   Install or resume same saved role/identity
  --help                   Show help (no root/mutations needed)
  --status                 Show saved state, containers, sockets, timers
  --check                  Verify infrastructure and real authenticated VLESS transfer
  --check-xray             Verify Xray API, ports and real VLESS transfer only
  --check-xray-client EMAIL Test an existing client selected by its panel email
  --show-client-for EMAIL   Show that existing client profile on an interactive terminal
  --reconfigure            Explicitly update site title/text; other identity stays fixed
  --reset-3xui-password     Change only existing panel admin credentials (brief xui stop)
  --configure-xray         Automatically configure and verify the selected Xray transport
  --migrate-inbound-reality Convert the managed INBOUND to REALITY/Vision, retaining UUIDs
  --show-client            Show verified VLESS URI only on an interactive terminal
  --backup                 Consistent SQLite/local configuration backup
  --restore /absolute/file.tar.gz
                           Restore same stack identity, preserving current host SSH/UFW
  --uninstall              Stop/remove managed containers/units; preserve all data/security
  --probe-route HOST PORT   Test a particular TCP destination; no routing changes
Internal: --confirm-ssh TOKEN "$SSH_CONNECTION", --apply-docker-firewall, --renew
Targets: systemd Debian 12/13, Ubuntu 24.04/26.04 LTS; IPv4-only base, Engine >=28.
No automatic migration/import/deletion of legacy services. Read README.md first.
EOF
}
collect_state() {
    local choice title text xui_ref nginx_ref
    printf 'Select server role:\n1. INBOUND — Russian VPS\n2. OUTBOUND — Foreign VPS\n'
    ask choice Role
    case "$choice" in 1) ROLE=inbound;; 2) ROLE=outbound;; *) die 'Choose 1 or 2';; esac
    log 'Both roles install the VPS stack, then automatically configure the selected VLESS transport.'
    ask ADMIN 'Sudo username' vpsadmin; valid_user "$ADMIN" || die 'Invalid sudo username'
    ask SSH_PORT 'SSH TCP port (existing port is retained during verification)' 22
    valid_port "$SSH_PORT" || die 'Invalid SSH port'
    case "$SSH_PORT" in 80|443|2053|8443) die 'SSH port conflicts with the managed stack';; esac
    ask DOMAIN 'Own domain (ASCII/punycode, no URL prefix; apex allowed)'
    DOMAIN=${DOMAIN,,}; valid_domain "$DOMAIN" || die 'Invalid domain'
    ask PUBLIC_IP 'Origin IPv4 of this VPS (Cloudflare Proxy may return different public DNS addresses)'
    ask EMAIL "Let's Encrypt email"
    ask SUBNET 'Unused private Docker /24 subnet' 172.30.53.0/24
    ask title 'Site title' 'HAHA BENIS'
    ask text 'Site text' 'Independent digital studio. Exploring light, form and the web.'
    printf 'Role=%s Domain=%s SSH=%s User=%s\n' "$ROLE" "$DOMAIN" "$SSH_PORT" "$ADMIN"
    confirm 'Apply this configuration? Existing services/data will not be removed'
    # User policy: all containers use latest; backup precedes pulls and updates.
    xui_ref=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["xui_image"])' "$APP/config/images.json")
    nginx_ref=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["nginx_image"])' "$APP/config/images.json")
    python3 - "$STATE" "$ROLE" "$DOMAIN" "$ADMIN" "$SSH_PORT" "$PUBLIC_IP" "$EMAIL" "$SUBNET" "$xui_ref" "$nginx_ref" "$title" "$text" "$APP/helpers" <<'EOF'
import sys
sys.path.insert(0,sys.argv[-1]);from state import write
keys=['role','domain','admin','ssh_port','public_ip','email','subnet','xui_image','nginx_image','title','text']
d=dict(zip(keys,sys.argv[2:-1]));d.update(schema='1',phase='configured');write(sys.argv[1],d)
EOF
}
install_main() {
    warn 'Before setup: TLS uses HTTP-01 on port 80. Cloudflare Proxy must pass the ACME path; otherwise use DNS only until the first certificate is issued.'
    preflight
    if [[ -f $STATE ]]; then
        load_state
        backup_stack
    else
        # Includes original config/legacy data BEFORE apt, SSH, firewall or Docker changes.
        backup_stack
        if [[ -e /etc/vps-setup.conf || -d /opt/3x-ui || -d /opt/mtproxyl || -d /etc/amnezia ]]; then
            warn 'Legacy install detected; backup created. No legacy service or data will be stopped/deleted/imported.'
            confirm 'Proceed with infrastructure preparation? Conflicting listeners will cause a safe stop; follow docs/MIGRATION.md'
        fi
        collect_state
        load_state
    fi
    transport_select
    if [[ $(python3 "$APP/helpers/automation.py" profile-info "$ROOT") == active || -d $ROOT/.transport-transaction ]]; then
        configure_xray
        check_stack
        access_instructions
        return
    fi
    # Resolve and warn before package, user, SSH, UFW or Docker changes.
    check_dns
    base_packages
    install_app
    setup_user
    install_docker
    if [[ ! -f $ROOT/compose.yml ]]; then check_ports; fi
    # Check selected subnet against every existing Docker network before creating it.
    python3 "$APP/helpers/network.py" "$SUBNET"
    firewall_base
    setup_ssh
    hardening
    render
    compose config --quiet
    compose pull
    setup_xui
    compose up -d nginx
    wait_healthy vps-nginx
    install_guard_service
    setup_certificates
    install_backup_timer
    configure_xray
    check_stack
    state_set phase ready
    access_instructions
}
reconfigure_site() {
    local title text
    backup_stack
    ask title 'Site title' "$(state_get title)"
    ask text 'Site text' "$(state_get text)"
    confirm 'Replace managed index.html/style.css/app.js with the updated site? Other site files are preserved'
    # Validate both values before making any change.
    cp -a "$STATE" "$TMPDIR_TASK/site-state.json"
    python3 "$APP/helpers/state.py" set "$TMPDIR_TASK/site-state.json" title "$title"
    python3 "$APP/helpers/state.py" set "$TMPDIR_TASK/site-state.json" text "$text"
    install_app
    python3 "$APP/helpers/render.py" site "$TMPDIR_TASK/site-state.json" "$ROOT" "$APP/templates"
    install -m 600 "$TMPDIR_TASK/site-state.json" "$STATE"
    nginx_validate_reload
}
main() {
    case "${1:-}" in --help|-h) [[ $# == 1 ]] || die 'Unexpected arguments'; usage; return;; esac
    case "${1:-}" in
        --confirm-ssh)
            [[ $EUID == 0 && $# == 3 ]] || die 'SSH confirmation requires sudo, a token, and the SSH_CONNECTION value'
            # Deliberately bypass the installer's operation lock to permit a second session.
            exec python3 "$APP/helpers/ssh_gate.py" confirm "$ROOT" "$2" "$3";;
        --probe-route)
            [[ $# == 3 ]] || die 'Use --probe-route HOST PORT'
            exec python3 "$APP/helpers/probe.py" "$2" "$3";;
        --restore) [[ $# == 2 ]] || die 'Use --restore /absolute/backup.tar.gz';;
        --check-xray-client|--show-client-for) [[ $# == 2 && -n $2 ]] || die 'Specify the client email shown in the panel';;
        ''|--status|--check|--check-xray|--configure-xray|--migrate-inbound-reality|--show-client|--reconfigure|--reset-3xui-password|--reset-3xui-credentials|--backup|--uninstall|--apply-docker-firewall|--renew)
            (( $# <= 1 )) || die 'Unexpected arguments';;
        *) die 'Unknown command; see --help';;
    esac
    init_runtime
    if [[ ${1:-} == '' ]]; then install_main; return; fi
    load_state
    case "$1" in
        --status) status_stack;;
        --configure-xray) configure_xray;;
        --migrate-inbound-reality) migrate_inbound_reality;;
        --show-client) show_client;;
        --check) check_stack;;
        --check-xray) require_docker; python3 "$APP/helpers/automation.py" check "$ROOT";;
        --check-xray-client) require_docker; python3 "$APP/helpers/automation.py" check-client "$ROOT" --client-email "$2";;
        --show-client-for) require_docker; python3 "$APP/helpers/automation.py" show-client-for "$ROOT" --client-email "$2";;
        --reconfigure) reconfigure_site;;
        --reset-3xui-password|--reset-3xui-credentials) reset_xui;;
        --backup) backup_stack;;
        --restore) require_docker; restore_stack "$2";;
        --uninstall) require_docker; uninstall_stack;;
        --apply-docker-firewall) docker_guard;;
        --renew) require_docker; renew_certificate;;
    esac
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
