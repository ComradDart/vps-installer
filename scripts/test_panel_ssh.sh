#!/usr/bin/env bash
# Disposable real Linux users + real OpenSSH; never run scenario.py on a VPS.
set -Eeuo pipefail
APP=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH
export DOCKER_HOST=unix:///var/run/docker.sock
mounts=(--mount "type=bind,src=$APP,dst=/src,readonly")
if [[ -n ${CODEX_PROXY_CERT:-} ]]; then
    mounts+=(--mount "type=bind,src=/etc/ssl/certs/ca-certificates.crt,dst=/run/outer-ca.pem,readonly" -e SSL_CERT_FILE=/run/outer-ca.pem)
fi
docker run --rm "${mounts[@]}" alpine:latest sh -ec '
    apk add --no-cache openssh python3 shadow sudo openssl procps
    exec python3 /src/tests/integration/panel_ssh_scenario.py
'
