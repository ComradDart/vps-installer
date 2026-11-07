#!/usr/bin/env bash
# State flags are consumed by common.sh cleanup across module boundaries.
# shellcheck disable=SC2034
panel_credentials() {
    ask PANEL_USER '3x-ui admin username (3–32 ASCII letters/digits/._-)' operator
    valid_panel_user "$PANEL_USER" || die 'Invalid panel username'
    local manual
    ask manual 'Generate a password with OpenSSL? (yes/no)' yes
    if [[ $manual == yes ]]; then
        PANEL_PASSWORD=$(generate_password)
        # /dev/tty is deliberately separate from stdout/stderr and installer logs.
        printf '\nStore in a password manager now:\nUsername: %s\nPassword: %s\n\n' "$PANEL_USER" "$PANEL_PASSWORD" >/dev/tty
        confirm 'I have saved the credentials'
    else secret PANEL_PASSWORD '3x-ui password (16–72 printable ASCII bytes, no colon)'; fi
}
xui_cli_credentials() {
    local initial=$1
    # Official CLI has no stdin/password-file option in v3.11.0. Transport to the
    # helper is stdin, not Docker metadata. /app/x-ui temporarily has password in
    # its own argv: visible to host root/process inspectors. See README.md.
    printf '%s\n%s\n' "$PANEL_USER" "$PANEL_PASSWORD" | docker run --rm -i --network none \
        --log-driver none --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges:true \
        -v "$ROOT/db:/etc/x-ui" --entrypoint /bin/sh "$XUI_IMAGE" -c '
            IFS= read -r account
            IFS= read -r credential
            if [ "$1" = initial ]; then
                /app/x-ui setting -username "$account" -password "$credential" -port 2053 -listenIP 0.0.0.0 -webBasePath / >/dev/null 2>&1
            else
                /app/x-ui setting -username "$account" -password "$credential" >/dev/null 2>&1
            fi
        ' sh "$initial" >/dev/null || return 1
    # CLI's exit status alone is insufficient: upstream can print an update error
    # and still return 0. Verify the actual first-user bcrypt hash in the same DB.
    printf '%s\n%s\n' "$PANEL_USER" "$PANEL_PASSWORD" | python3 "$APP/helpers/db.py" verify "$ROOT/db/x-ui.db"
}
check_xui_image_contract() {
    local version
    version=$(docker run --rm --network none --log-driver none --entrypoint /app/x-ui "$XUI_IMAGE" -v)
    [[ $version == 3.11.0 || $version == v3.11.0 ]] || die 'latest 3x-ui has an unreviewed API contract. Running inbound configuration was not changed.'
}
setup_xui() {
    check_xui_image_contract
    local fresh=no
    if [[ -s $ROOT/db/x-ui.db ]]; then
        python3 "$APP/helpers/db.py" integrity "$ROOT/db/x-ui.db"
    fi
    if [[ ! -s $ROOT/db/x-ui.db ]] || ! python3 "$APP/helpers/db.py" has-user "$ROOT/db/x-ui.db" >/dev/null 2>&1; then
        panel_credentials
        # Fail closed: never start the normal server after unsuccessful initialization.
        xui_cli_credentials initial
        fresh=yes
    else
        python3 "$APP/helpers/db.py" integrity "$ROOT/db/x-ui.db"
        python3 "$APP/helpers/db.py" single-user "$ROOT/db/x-ui.db" || die 'Expected one panel administrator; existing accounts were preserved for manual review'
        log 'Existing 3x-ui database preserved; credentials are not changed'
    fi
    compose up -d xui
    wait_healthy vps-xui
    if [[ $fresh == yes ]]; then
        printf '%s\n%s\n' "$PANEL_USER" "$PANEL_PASSWORD" | python3 "$APP/helpers/automation.py" login-check "$ROOT"
        unset PANEL_PASSWORD PANEL_USER
    fi
}
reset_xui() {
    require_docker
    [[ -s $ROOT/db/x-ui.db ]] || die 'Existing SQLite panel database required'
    python3 "$APP/helpers/db.py" single-user "$ROOT/db/x-ui.db" || die 'Password reset requires exactly one existing administrator'
    panel_credentials
    backup_stack
    RESET_PENDING=yes
    compose stop xui
    python3 "$APP/helpers/db.py" snapshot "$ROOT/db/x-ui.db" "$TMPDIR_TASK/xui-before.db"
    local before after
    before=$(python3 "$APP/helpers/db.py" fingerprint "$ROOT/db/x-ui.db")
    if ! xui_cli_credentials reset; then
        restore_db_after_failed_reset
        die 'Credential change failed; previous database restored'
    fi
    after=$(python3 "$APP/helpers/db.py" fingerprint "$ROOT/db/x-ui.db")
    if [[ $before != "$after" ]]; then
        restore_db_after_failed_reset
        die 'Unexpected non-user DB modification; previous database restored'
    fi
    unset PANEL_PASSWORD PANEL_USER
    compose start xui
    wait_healthy vps-xui
    RESET_PENDING=no
    log 'Admin credentials changed and bcrypt verified. Inbounds/clients/settings preserved; 2FA remains unchanged.'
}
restore_db_after_failed_reset() {
    compose stop xui || return 1
    rm -f "$ROOT/db/x-ui.db-wal" "$ROOT/db/x-ui.db-shm"
    install -m 600 "$TMPDIR_TASK/xui-before.db" "$ROOT/db/x-ui.db" || return 1
    compose start xui || return 1
    RESET_PENDING=no
}
