#!/usr/bin/env bash
install_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        local distro codename arch fingerprint
        # shellcheck disable=SC1091
        . /etc/os-release
        distro=$ID; codename=$VERSION_CODENAME; arch=$(dpkg --print-architecture)
        install -d -m 755 /etc/apt/keyrings
        curl -fsS --proto '=https' --tlsv1.2 "https://download.docker.com/linux/$distro/gpg" -o "$TMPDIR_TASK/docker.asc"
        fingerprint=$(gpg --show-keys --with-colons "$TMPDIR_TASK/docker.asc" | awk -F: '$1=="fpr" {print $10; exit}')
        [[ $fingerprint == 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ]] || die 'Docker signing-key fingerprint mismatch'
        install -m 644 "$TMPDIR_TASK/docker.asc" /etc/apt/keyrings/docker.asc
        printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
            "$arch" "$distro" "$codename" >/etc/apt/sources.list.d/vps-installer-docker.list
        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    fi
    systemctl enable --now docker
    docker info >/dev/null || die 'Docker daemon unavailable'
    docker compose version >/dev/null || die 'Docker Compose v2 plugin required'
    # Docker <28 has a known remote-access issue with localhost-published ports.
    local major
    major=$(docker version --format '{{.Server.Version}}'); major=${major%%.*}
    if [[ ! $major =~ ^[0-9]+$ ]] || ((major < 28)); then die 'Docker Engine >=28 required for safe loopback port publication'; fi
    log 'No account is added to the Docker group (membership is equivalent to root)'
}
require_docker() { need docker; docker info >/dev/null || die 'Docker daemon unavailable'; docker compose version >/dev/null; }
compose() { docker compose --project-name vps-installer --project-directory "$ROOT" -f "$ROOT/compose.yml" "$@"; }
render() { python3 "$APP/helpers/render.py" "$STATE" "$ROOT" "$APP/templates"; }
check_ports() {
    python3 "$APP/helpers/check_ports.py"
    local p
    for p in 80 443 2053 8443; do
        if ss -H -lnt "sport = :$p" | rg -q .; then
            die "TCP port $p is busy. Stop/migrate its owner explicitly; no existing service has been stopped."
        fi
    done
}
