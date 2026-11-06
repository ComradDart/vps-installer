# VPS Installer

Установка и обслуживание двух VPS с Docker, 3x-ui, nginx и HTTPS-сайтом.
Настройка VLESS выполняется через официальный API панели. Устройства подключаются
к INBOUND; он работает самостоятельно или передаёт трафик на заданный OUTBOUND.

Оба сервера развёрнуты и работают — подтверждено владельцем проекта.
Контейнерные образы всегда **latest**:

```text
ghcr.io/mhsanaei/3x-ui:latest
nginx:latest
```

## Схема

| Сервер | Подключение устройств / транспорт | Публичный TCP/443 |
|---|---|---|
| INBOUND | VLESS + REALITY + Vision; свой домен, DNS only | Xray в 3x-ui |
| OUTBOUND | VLESS + gRPC + TLS через Cloudflare | nginx |

Типичный маршрут: **устройство → INBOUND REALITY → Cloudflare → OUTBOUND gRPC → Интернет**.
INBOUND также поддерживает standalone. OUTBOUND можно установить в direct-reality.
Для relay нужны готовая VLESS-ссылка OUTBOUND и его выходной IPv4.

На INBOUND nginx обслуживает сайт внутри Docker на `8443` и служит REALITY
self-steal target (`nginx:8443`). На OUTBOUND сайт работает на `/`, а
`/vlessgrpc/Tun` проксируется к `xui:10000`. Панель на обоих серверах доступна
только через **127.0.0.1:2053 хоста и SSH-туннель**.

## Требования

- Debian 12/13 или Ubuntu 24.04/26.04 LTS, systemd, amd64/arm64.
- Доступ root/sudo, минимум 4 GiB свободного места, консоль провайдера для восстановления.
- Свой публичный домен для каждой VPS; свободные TCP 80/443 и выбранный SSH-порт.
- A-запись на IPv4 origin. Для прямого INBOUND — без origin AAAA и без Cloudflare Proxy.

Первый сертификат Let's Encrypt выпускается через HTTP-01 на TCP/80.
Cloudflare должен пропускать ACME-путь без challenge/кэша. При проблемах первого
выпуска временно используйте **DNS only**.

Для OUTBOUND/cloudflare-grpc после выпуска сертификата включите в Cloudflare:
**DNS → Proxied**, **SSL/TLS → Full (strict)**, **Network → gRPC On**, HTTP/2.
Не применяйте challenge или разрушающие POST редиректы к `/vlessgrpc/*`.

## Получение и установка

Репозиторий приватный: анонимные `raw.githubusercontent.com` и `codeload` ссылки
не работают. Авторизуйтесь на [GitHub](https://github.com/ComradDart/vps-installer).

**Без Git на VPS:** нажмите **Code → Download ZIP**, загрузите архив на сервер
через SFTP/Termius и распакуйте. В каталоге с `install.sh` выполните:

```bash
sudo apt-get update
sudo apt-get install -y python3 util-linux
sudo bash ./install.sh
```

Выберите роль и следуйте мастеру. Для relay сначала подготовьте OUTBOUND и его
клиентскую ссылку. Не закрывайте исходную SSH-сессию до завершения проверки входа
нового sudo-пользователя в отдельном окне.

Если Git и GitHub CLI уже настроены, можно получить исходники командой:

```bash
gh repo clone ComradDart/vps-installer
cd vps-installer
sudo bash ./install.sh
```

### Bootstrap без Git с авторизацией

Сохранённый из приватного репозитория `get.sh` умеет скачивать актуальный main
через GitHub API. Нужен токен с **Contents: Read-only** только для этого репозитория:

```bash
read -rsp 'GitHub token: ' GH_TOKEN; printf '\n'
export GH_TOKEN
sudo --preserve-env=GH_TOKEN bash ./get.sh
unset GH_TOKEN
```

Токен не записывается в аргументы curl и не передаётся установщику. Временный
root-only файл авторизации удаляется. Любую служебную команду можно передать после
`get.sh`, например `--panel-users` или `--repair-client-links`.

## Доступ к панели

На компьютере с вашим SSH-ключом:

```bash
ssh -N -T -o ExitOnForwardFailure=yes \
  -p SSH_PORT -i ~/.ssh/your_key \
  -L 2053:127.0.0.1:2053 ADMIN@SERVER_IP
```

Откройте **http://127.0.0.1:2053** и войдите под существующей учётной записью 3x-ui.
Если ключ хранится в Termius, создайте там **Port Forwarding → Local** с тем же
хостом/ключом: local port `2053`, destination `127.0.0.1`, destination port `2053`.
Ключи Termius не появляются в Windows OpenSSH автоматически.

Для приглашённых администраторов:

```bash
sudo /opt/vps-installer/app/install.sh --panel-users
```

Меню управляет отдельными Linux-пользователями и публичными SSH-ключами. Им доступен
только туннель к панели: без shell, команд, SFTP, sudo, Docker и других forwarding.
В 3x-ui остаётся **одна общая административная учётная запись**. Отзыв доступа
закрывает активные туннели. [Подробная инструкция](docs/PANEL-USERS.md).

## Ссылки и QR на INBOUND

Установщик сохраняет публичный домен как `PUBLIC_DOMAIN` и через штатные
**Custom share address + Hosts** задаёт внешний Address, независимо от localhost,
по которому открыта панель. REALITY SNI, `pbk`, `sid` и flow берутся из действующей
конфигурации. Публичные URL подписок используют HTTPS-домен и nginx.

Если на существующем INBOUND в ссылках остался localhost, выполните из актуальных
исходников:

```bash
sudo bash ./install.sh --repair-client-links
```

Обновите страницу и заново откройте QR. UUID, ключи REALITY, Short IDs, существующие
subId и пароль панели сохраняются. Эта команда предназначена только для INBOUND.

Для ручной правки откройте **Hosts → vps-installer:public:…**: Address — домен без
схемы, Port — `443`, Security — `Same`. В inbound: **Share address strategy → Custom**,
**Custom share address → домен**. SNI настраивается отдельно в REALITY Server Names.
`webDomain` для исправления ссылок менять не нужно. Повтор repair вернёт сохранённый
домен установщика; пути подписок должны совпадать с nginx.

## Обслуживание

Установленная копия: `/opt/vps-installer/app/install.sh`.

| Команда | Назначение |
|---|---|
| `--status` | Состояние контейнеров, портов и таймеров |
| `--check` | Полная проверка инфраструктуры и передачи VLESS |
| `--check-xray` | API, привязки портов и реальная передача VLESS |
| `--check-xray-client EMAIL` | Проверить существующего клиента по email из панели |
| `--show-client` | Показать сохранённую служебную VLESS-ссылку в терминале |
| `--show-client-for EMAIL` | Показать актуальную ссылку выбранного клиента |
| `--panel-users` | Управлять SSH-доступом к панели |
| `--repair-client-links` | Исправить экспорт ссылок и QR INBOUND/REALITY |
| `--backup` | Создать локальную резервную копию |
| `--restore /absolute/backup.tar.gz` | Восстановить эту же конфигурацию из архива |
| `--reset-3xui-password` | Явно сменить пароль существующего администратора |
| `--reconfigure` | Изменить заголовок/текст управляемого сайта |
| `--configure-xray` | Настроить или проверить сохранённый транспорт |
| `--migrate-inbound-reality` | Перевести старый managed INBOUND с gRPC на REALITY |
| `--uninstall` | Остановить стек, сохранив данные и защиту хоста |

Пример: `sudo /opt/vps-installer/app/install.sh --status`.
Если служебный клиент удалён вручную, используйте `--check-xray-client EMAIL`.
Для обновления инструментов получите свежие исходники приватного репозитория и
запускайте нужную команду из нового каталога. Простой повтор установки может
обновить latest-образы; для обычного доступа к панели он не требуется.

## Данные и резервные копии

В `/opt/vps-installer` находятся `state.json`, `transport.json`, `compose.yml`,
БД панели, сайт, сертификаты, root-only каталоги `secrets/` и `clients/`.
Архивы сохраняются в `/var/backups/vps-installer`; настроен ежедневный backup.
Они содержат ключи и учётные данные: храните внешние копии с шифрованием.

Повтор установки сохраняет существующие UUID и пароль панели. При несовместимой
версии API, конфликте identity или порта автоматизация останавливается. Теги
образов latest не закрепляются; текущий проверенный API-контракт — 3.11.0.

## Документация и проверки

- [Архитектура](docs/ARCHITECTURE.md) и [безопасность](docs/SECURITY.md).
- [SSH-пользователи панели](docs/PANEL-USERS.md), [миграция](docs/MIGRATION.md).
- [Результаты проверок](docs/TEST-REPORT.md), [ручная проверка](docs/MANUAL-TEST.md).
- [Официальные источники](docs/SOURCES.md).

Исходники: `helpers/`, `lib/`, `templates/`, `config/`. Проверки: `tests/`.
Для локальных unit/syntax-проверок установите ShellCheck и зависимости из
`tests/requirements.txt`, затем выполните `bash tests/run.sh`.
Контейнерные и browser-проверки запускаются отдельно по инструкциям в тестах.
