#!/usr/bin/env bash
certbot_stack() {
    certbot --config-dir "$ROOT/letsencrypt" --work-dir "$ROOT/certbot-work" --logs-dir "$ROOT/certbot-logs" "$@"
}
check_dns() {
    python3 "$APP/helpers/dns.py" "$DOMAIN" "$PUBLIC_IP" --allow-proxy
}
acme_probe() {
    local token expected actual
    token="vps-$(openssl rand -hex 12)"; expected=$(openssl rand -hex 24)
    printf '%s' "$expected" >"$ROOT/acme/.well-known/acme-challenge/$token"
    chmod 644 "$ROOT/acme/.well-known/acme-challenge/$token"
    # Fetch exact bytes, not just HTTP 200. The public check also works via CF.
    actual=$(curl --noproxy '*' -fsS --max-time 20 -H "Host: $DOMAIN" "http://127.0.0.1/.well-known/acme-challenge/$token") || {
        rm -f "$ROOT/acme/.well-known/acme-challenge/$token"; die 'Local ACME webroot inaccessible';
    }
    [[ $actual == "$expected" ]] || { rm -f "$ROOT/acme/.well-known/acme-challenge/$token"; die 'Wrong local ACME response'; }
    actual=$(curl --noproxy '*' -fsS --location --max-redirs 5 --proto '=http,https' --proto-redir '=http,https' --max-time 30 "http://$DOMAIN/.well-known/acme-challenge/$token") || {
        rm -f "$ROOT/acme/.well-known/acme-challenge/$token"; die 'Public ACME challenge failed. Cloudflare: remove challenges/cache/forced HTTPS for the ACME path, or temporarily use DNS only. HTTP nginx retained.';
    }
    rm -f "$ROOT/acme/.well-known/acme-challenge/$token"
    [[ $actual == "$expected" ]] || die 'Wrong public ACME response'
}
validate_certificate() {
    local dir="$ROOT/letsencrypt/live/$DOMAIN" certpub keypub
    openssl x509 -in "$dir/fullchain.pem" -noout -checkhost "$DOMAIN" >/dev/null
    openssl x509 -in "$dir/fullchain.pem" -noout -checkend 0 >/dev/null
    openssl verify -CApath /etc/ssl/certs -untrusted "$dir/chain.pem" "$dir/cert.pem" >/dev/null
    certpub=$(openssl x509 -in "$dir/fullchain.pem" -pubkey -noout)
    keypub=$(openssl pkey -in "$dir/privkey.pem" -pubout)
    [[ $certpub == "$keypub" ]] || die 'Certificate/private-key mismatch'
}
export_certificate() {
    validate_certificate
    install -d -m 750 -o root -g 101 "$ROOT/tls"
    install -m 644 "$ROOT/letsencrypt/live/$DOMAIN/fullchain.pem" "$ROOT/tls/fullchain.pem"
    install -m 640 -o root -g 101 "$ROOT/letsencrypt/live/$DOMAIN/privkey.pem" "$ROOT/tls/privkey.pem"
}
setup_certificates() {
    if [[ ! -s $ROOT/letsencrypt/live/$DOMAIN/fullchain.pem ]]; then
        check_dns
        acme_probe
        certbot_stack certonly --webroot -w "$ROOT/acme" -d "$DOMAIN" --cert-name "$DOMAIN" \
            --email "$EMAIL" --agree-tos --no-eff-email --non-interactive || \
            die 'Certificate issuance failed; HTTP-only nginx retained. Correct DNS/ACME and rerun.'
    elif ! openssl x509 -in "$ROOT/letsencrypt/live/$DOMAIN/fullchain.pem" -noout -checkend 2592000 >/dev/null; then
        acme_probe
        certbot_stack renew --cert-name "$DOMAIN" --non-interactive
    fi
    export_certificate
    nginx_tls
    certbot_stack renew --cert-name "$DOMAIN" --dry-run --non-interactive
    install_cert_timer
}
install_cert_timer() {
    cat >/etc/systemd/system/vps-installer-renew.service <<EOF
[Unit]
Description=Renew this stack's Let's Encrypt certificate and safely reload nginx
After=docker.service network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=$ROOT/app/install.sh --renew
UMask=0077
EOF
    cat >/etc/systemd/system/vps-installer-renew.timer <<'EOF'
[Unit]
Description=Twice-daily certificate renewal
[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=1h
Persistent=true
[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now vps-installer-renew.timer
}
renew_certificate() {
    certbot_stack renew --cert-name "$DOMAIN" --non-interactive
    # If renewal fails, no export or nginx reload occurs.
    export_certificate
    nginx_validate_reload
}
