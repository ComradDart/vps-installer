# Границы безопасности

- State не содержит паролей и не исполняется. Parent `/opt/vps-installer` root-only 700.
  Локальные модули/скрипты принадлежат root; обычный пользователь не может подменить
  код systemd timer или программу подтверждения SSH.
- Официальный CLI 3x-ui, исследованный в текущем latest, не имеет password-stdin/file.
  Helper получает username/password через stdin; в `docker inspect`, Docker environment,
  normal stdout/logs и `.env` пароля нет. Одноразовый helper имеет network none,
  log driver none, cap_drop ALL. **Сам `/app/x-ui setting` кратковременно содержит
  пароль в argv своего процесса.** Устранить это без изменения upstream/обхода его
  поддержанного CLI здесь нельзя. Host root и средства process tracing могут его увидеть.
  Не запускайте установщик под `strace`, process recorder или terminal recorder.
  Если это неприемлемо, на уже работающей панели меняйте пароль через UI внутри
  SSH-туннеля с текущей авторизацией. Проверен login/UI-механизм текущей версии;
  автоматический password-recovery по неизвестному API не придуман.
- CLI запускается как текущий UID/GID (на целевой VPS это root), без передачи секретов
  через Docker ENV или аргументы Docker command. Значения shell read quoted, не eval.
- Reset использует поддержанный CLI, а Python лишь читает bcrypt/SQLite и делает
  snapshots. Прямого патчинга схемы/хешей базы нет. 2FA не отключается.
- Built-in fail2ban контейнера и лишние network capabilities исключены.
  Host fail2ban проверяется для SSH. Защита панели fail2ban не заявляется.
- Пользователь не добавляется в docker group. Обычное sudo остаётся с паролем.
- nginx работает как UID/GID 101, read-only root filesystem, tmpfs для cache/pid,
  приватный ключ читается через root:101 640 внутри отдельного bind volume.
  Публичные HTML/CSS/JS имеют права чтения; `umask 077` не делает сайт нечитаемым.
- Официальный образ 3x-ui сам может включать upstream-бинарники для иных протоколов.
  Установщик не запускает и не настраивает MTProxyL/telemt/AWG, не ставит host-пакеты
  AWG, не загружает его модули и не открывает его UDP-порты.
- Базовая IPv4-only сеть не является глобальной блокировкой IPv6 на хосте. Старые
  IPv6 listeners/rules нужно проверить. Не публикуйте origin AAAA до отдельной IPv6 реализации.
- Local backups не являются шифрованным offsite backup. Архив содержит секреты;
  checksum определяет целостность, но не заменяет аутентификацию источника.
- Docker Engine >=28 нужен из-за исправлений loopback publications. DOCKER-USER
  поддерживается только с iptables backend; существующий firewall никогда не выключается.
- latest применяется по прямому требованию заказчика. Воспроизводимость контейнерного
  кода между датами не гарантируется; повторный запуск может обновить приложения.

## API и транспорт

Bearер-токен официального API и VLESS/REALITY секреты сохраняются только в root-only
secrets/clients и backup. HTTP API доступен через loopback; тела ответов/запросов,
UUID, ключи и URI не печатаются в системные журналы. Reference client запускается с
log driver none; профиль передаётся через приватный файл, не Docker argv/env.
`--show-client` выводит URI только в интерактивный tty, не в redirected stdout.
Копии профилей на устройствах тоже являются секретами.

Смена пароля отдельной командой не отзывает Bearer token; для его отзыва используйте
управление API tokens панели. Не добавляйте публичный маршрут nginx к panel API.
Возможности сторонних плагинов/терминальных записывающих программ не контролируются.

Режим relay не добавляет direct fallback для управляемого inbound. Standalone
сохраняет штатные защитные правила 3x-ui для приватных адресов. Интеграционные тесты
используют точечное исключение для своего Docker fixture; оно не попадает на VPS.
