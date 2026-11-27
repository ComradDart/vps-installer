#!/usr/bin/env bash
# menu_command is returned to main via Bash dynamic scope.
# shellcheck disable=SC2034
maintenance_menu() {
    local choice
    printf '\nVPS Installer\n'
    printf '%s\n' '1. Установить или продолжить установку'
    if [[ -f $STATE ]]; then
        load_state
        printf '%s · %s\n' "$ROLE" "$DOMAIN"
        printf '%s\n' '2. Статус' '3. Проверить стек' '4. Проверить VLESS' '5. Создать резервную копию'
        printf '%s\n' '6. Обновить код установщика' '7. Изменить заголовок и текст сайта'
        if [[ $ROLE == inbound ]]; then
            printf '%s\n' '8. Подключить или зарегистрировать Telegram-прокси' '9. Установить или запустить Zapret2 для Telegram-прокси'
        fi
        printf '%s\n' '10. Включить еженедельную перезагрузку' '11. Выключить еженедельную перезагрузку'
    fi
    printf '%s\n' '0. Выход'
    ask choice 'Выберите действие' 0
    if [[ ! -f $STATE && $choice != 0 && $choice != 1 ]]; then
        die 'Сначала выполните установку'
    fi
    case "$choice" in
        1) menu_command=--install;;
        2) menu_command=--status;;
        3) menu_command=--check;;
        4) menu_command=--check-xray;;
        5) menu_command=--backup;;
        6) menu_command=--update;;
        7) menu_command=--reconfigure;;
        8|9)
            [[ $ROLE == inbound ]] || die 'Telegram-прокси доступен только на INBOUND'
            if [[ $choice == 8 ]]; then menu_command=--telemt; else menu_command=--telemt-zapret2; fi;;
        10) menu_command=--reboot-weekly-on;;
        11) menu_command=--reboot-weekly-off;;
        0) menu_command='';;
        *) die 'Выберите номер из меню';;
    esac
}
update_installer() {
    if [[ $APP == "$ROOT/app" ]]; then
        # shellcheck source=get.sh
        source "$APP/get.sh"
        bootstrap_fetch "$TMPDIR_TASK"
        APP="$TMPDIR_TASK/vps-installer-main"
        bash -n "$APP/install.sh"
        # Use the running version to back up the current format before replacing it.
        local new_app=$APP
        APP="$ROOT/app"
        backup_stack
        APP=$new_app
    else
        backup_stack
    fi
    install_app
    log 'Installer code updated. Server configurations and containers were not changed.'
}

readonly WEEKLY_REBOOT_CRON=/etc/cron.d/vps-installer-reboot

enable_weekly_reboot() {
    local pending
    confirm 'Enable weekly reboot every Sunday at 04:00 (VPS local time)? This interrupts VPS traffic'
    if ! command -v cron >/dev/null 2>&1; then
        apt-get update
        NEEDRESTART_MODE=l apt-get install -y --no-install-recommends cron
    fi
    systemctl enable --now cron.service
    pending=$(mktemp /etc/cron.d/.vps-installer-reboot.XXXXXX)
    cron_weekly_reboot >"$pending"
    chmod 644 "$pending"
    mv -Tf -- "$pending" "$WEEKLY_REBOOT_CRON"
    log 'Weekly reboot enabled: Sunday at 04:00 in the VPS time zone.'
}
cron_weekly_reboot() {
    cat <<'EOF'
# Managed by vps-installer. Skip a reboot while installer maintenance is running.
0 4 * * 0 root /usr/bin/flock -n /run/lock/vps-installer.lock /usr/bin/systemctl --no-block reboot
EOF
}
disable_weekly_reboot() {
    rm -f -- "$WEEKLY_REBOOT_CRON"
    log 'Weekly reboot disabled.'
}
