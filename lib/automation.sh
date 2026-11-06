#!/usr/bin/env bash
transport_select() {
    local mode topology=standalone choice remote_uri remote_ip status
    status=$(python3 "$APP/helpers/automation.py" profile-info "$ROOT")
    [[ $status == missing ]] || return 0
    if [[ $ROLE == inbound ]]; then
        mode=direct-reality
        log 'INBOUND: VLESS/REALITY/Vision on TCP443; nginx self-steal target on internal 8443. Use DNS only for this hostname.'
        printf 'INBOUND topology:\n1. Relay to an existing OUTBOUND\n2. Standalone server\n'
        ask choice Topology 1
        case "$choice" in 1) topology=relay;; 2) topology=standalone;; *) die 'Choose 1 or 2';; esac
    else
        printf 'OUTBOUND transport:\n1. cloudflare-grpc\n2. direct-reality\n'
        ask choice Transport 1
        case "$choice" in 1) mode=cloudflare-grpc;; 2) mode=direct-reality;; *) die 'Choose 1 or 2';; esac
    fi
    if [[ $topology == relay ]]; then
        read -r -s -p 'Paste the OUTBOUND VLESS client URI (hidden): ' remote_uri </dev/tty || die 'Terminal input closed'
        printf '\n' >/dev/tty
        ask remote_ip 'Expected OUTBOUND exit IPv4 (used to reject a direct bypass)'
        printf '%s\n%s\n' "$remote_uri" "$remote_ip" | python3 "$APP/helpers/automation.py" import-peer "$ROOT"
        unset remote_uri
    fi
    python3 "$APP/helpers/automation.py" profile-init "$ROOT" --mode "$mode" --topology "$topology"
}
cloudflare_checkpoint() {
    local mode reply
    # ask writes the named variable.
    # shellcheck disable=SC2034
    reply=
    mode=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["mode"])' "$ROOT/transport.json")
    [[ $mode == cloudflare-grpc ]] || return 0
    log 'Cloudflare Dashboard: DNS -> this hostname -> Proxied (orange cloud). SSL/TLS -> Full (strict). Network -> gRPC On; HTTP/2 enabled. Do not apply challenges/cache to gRPC or ACME paths.'
    if ! python3 "$APP/helpers/automation.py" cf-check "$ROOT" 2>"$TMPDIR_TASK/cloudflare-check.txt"; then
        cat "$TMPDIR_TASK/cloudflare-check.txt" >&2
        ask reply 'Enable the Cloudflare settings above, wait for DNS, then press Enter'
        python3 "$APP/helpers/automation.py" cf-check "$ROOT"
    fi
}
configure_xray() {
    require_docker
    transport_select
    backup_stack
    install_app
    # The SSH checkpoint is already complete; this marks transport verification pending.
    state_set phase ssh-ready
    cloudflare_checkpoint
    python3 "$APP/helpers/automation.py" configure "$ROOT"
    state_set phase ready
    log "Verified client profile: $ROOT/clients/vless.txt (root-only). Use --show-client in an interactive terminal."
}
migrate_inbound_reality() {
    require_docker
    [[ $ROLE == inbound ]] || die 'This command is only for the INBOUND server'
    backup_stack
    install_app
    log 'Migrating the managed INBOUND to REALITY/Vision; existing client UUIDs and OUTBOUND route are preserved. Public TCP443 moves from nginx to Xray.'
    local topology
    topology=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["topology"])' "$ROOT/transport.json")
    if [[ $topology == standalone ]]; then warn 'Saved topology is standalone: direct egress. This conversion does not add an OUTBOUND route.'; fi
    state_set phase ssh-ready
    python3 "$APP/helpers/automation.py" migrate-inbound-reality "$ROOT"
    state_set phase ready
    log 'INBOUND REALITY verified. Import the updated profile from --show-client; existing gRPC device profiles must be updated.'
}
show_client() {
    [[ -s $ROOT/clients/vless.txt ]] || die 'No verified client profile; run --configure-xray'
    [[ -t 1 ]] || die 'Use --show-client in an interactive terminal; client secrets are not written to piped logs'
    printf '\nVerified VLESS profile (keep private):\n' >/dev/tty
    cat "$ROOT/clients/vless.txt" >/dev/tty
}
