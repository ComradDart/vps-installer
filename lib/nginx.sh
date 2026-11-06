#!/usr/bin/env bash
wait_healthy() {
    local container=$1 status i
    for ((i=0;i<60;i++)); do
        status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")
        [[ $status == healthy ]] && return 0
        [[ $(docker inspect -f '{{.State.Running}}' "$container") == true ]] || die "$container stopped during readiness check"
        sleep 2
    done
    die "$container failed readiness check"
}
nginx_validate_reload() {
    docker exec vps-nginx nginx -t
    docker exec vps-nginx nginx -s reload
}
nginx_tls() {
    local prior="$TMPDIR_TASK/tls-before.conf"
    [[ ! -f $ROOT/conf.d/tls.conf ]] || cp -a "$ROOT/conf.d/tls.conf" "$prior"
    python3 "$APP/helpers/render.py" tls "$STATE" "$ROOT" "$APP/templates"
    if ! docker exec vps-nginx nginx -t; then
        if [[ -f $prior ]]; then cp -a "$prior" "$ROOT/conf.d/tls.conf"; else rm -f "$ROOT/conf.d/tls.conf"; fi
        die 'TLS config invalid; previous config restored, nginx not reloaded'
    fi
    docker exec vps-nginx nginx -s reload
}
