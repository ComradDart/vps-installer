# VPS + nginx + сайт + автоматическая настройка 3x-ui / VLESS

Установщик настраивает VPS, создаёт sudo-пользователя и доступ по SSH-ключу,
устанавливает UFW, fail2ban для SSH, chrony, безопасные автообновления, Docker,
**3x-ui и nginx в Docker**, локальный сайт и настоящий сертификат Let's Encrypt.

По вашему уточнению все образы — **latest**, без закрепления версии/digest:

```text
ghcr.io/mhsanaei/3x-ui:latest
nginx:latest
```

После установки панель автоматически получает рабочий VLESS-inbound и тестового
клиента через официальный API. Ручное создание inbound, редактирование nginx и
публикация внутренних портов не требуются. UUID, пароль и существующие клиенты
сохраняются при повторном запуске.

**Для Cloudflare выбирайте `cloudflare-grpc`: VLESS + gRPC + обычный TLS, без REALITY.**
`direct-reality` — отдельный необязательный режим прямого доступа к VPS; Cloudflare
Proxy перед ним использовать нельзя. INBOUND поддерживает самостоятельный сервер
или relay с явно предоставленным профилем OUTBOUND.

Полная установка на VPS пока не проверена. Контейнерные проверки и точные ограничения
перечислены в [отчёте](docs/TEST-REPORT.md). Сначала используйте тестовую VPS.

## 1. Подготовка

Целевые ОС: Debian 12 / Debian 13 / Ubuntu 24.04 / 26.04 LTS с systemd, amd64/arm64.
Реальная контейнерная проверка выполнена на amd64. Нужны root/sudo, консоль провайдера,
минимум 4 GiB свободного места, собственный домен и свободные TCP 80/443/2053/8443.

- Сделайте snapshot у провайдера и проверьте serial/VNC-консоль.
- Создайте **A-запись домена на IPv4 этой VPS**. Поддомен необязателен.
- Самый простой первый выпуск сертификата: временно DNS only в Cloudflare.
  Proxy также допустим, если `/.well-known/acme-challenge/*` проходит до origin
  без challenge/кэша; принудительный HTTPS к origin без сертификата сорвёт проверку.
- Для прямого origin удалите AAAA: базовое развёртывание IPv4-only. IPv6-адреса
  Cloudflare edge допустимы: origin за ним остаётся IPv4.
- В firewall провайдера разрешите выбранный SSH/TCP, 80/TCP и 443/TCP.
- Для существующего сервера прочитайте [миграцию](docs/MIGRATION.md): старые сервисы
  и данные автоматически не удаляются и не останавливаются.

Только при прямом запуске `install.sh` на минимальном образе ОС (bootstrap `get.sh` установит это сам):

```bash
sudo apt-get update
sudo apt-get install -y python3 util-linux
```

## 2. Установка

### Рекомендуется: без Git, через curl или wget

Сохраните bootstrap-скрипт из этого репозитория и запустите его:

```bash
curl -fL https://raw.githubusercontent.com/ComradDart/vps-installer/main/get.sh -o vps-bootstrap.sh
sudo bash vps-bootstrap.sh
```

Если вместо curl установлен wget:

```bash
wget -O vps-bootstrap.sh https://raw.githubusercontent.com/ComradDart/vps-installer/main/get.sh
sudo bash vps-bootstrap.sh
```

Git не требуется. Bootstrap проверяет ОС, при необходимости ставит Python 3,
util-linux, curl и CA-сертификаты, скачивает текущий main по HTTPS во временную
папку, проверяет пути архива, запускает install.sh и удаляет временные файлы.
Ваш текущий каталог и существующий Git checkout не перезаписываются. Для root
можно запускать `bash vps-bootstrap.sh` без sudo.

Ubuntu 26.04 LTS добавлена в поддерживаемые цели. Наличие официального Docker
репозитория resolute проверено; полный host hardening/SSH/UFW на этой ОС требует
проверки на VPS. Будущая ошибка ОС показывает обнаруженные ID и VERSION_ID.

### Другие способы

Из GitHub: откройте **Code → Download ZIP**, распакуйте архив и в каталоге
`vps-installer-main` выполните `sudo ./install.sh`. Через Git:

```bash
git clone https://github.com/ComradDart/vps-installer.git vps-installer
cd vps-installer
sudo ./install.sh
```

Все модули должны оставаться
рядом с install.sh. Если нужен один файл, скачайте `download/vps_setup.sh`
(кнопка Download raw file в GitHub) и выполните команду из раздела ниже.


Из архива:

```bash
tar -xzf vps-installer.tar.gz
cd vps-installer
sudo ./install.sh
```

Если передан один самораспаковывающийся файл `vps_setup.sh`:

```bash
bash vps_setup.sh
cd vps-installer
sudo ./install.sh
```

Либо одной командой с распаковкой и запуском:

```bash
sudo bash vps_setup.sh --install
```

Самораспаковка не скачивает код из Интернета и не перезаписывает уже существующий
каталог. Для повторного распаковывания укажите новый каталог после `--install`
или без этого флага. Внутри проекта `vps_setup.sh` — совместимый вход в `install.sh`.

Установщик запросит:

- Роль INBOUND или OUTBOUND, затем транспорт и (для INBOUND) самостоятельный/relay режим.
- Имя sudo-пользователя, SSH-порт и публичный SSH-ключ. Root keys переносятся только
  при явном выборе; ключи с options требуют отдельного ручного review.
- Пароль для sudo, если у пользователя ещё нет рабочего пароля.
- Реальный домен, публичный IPv4 VPS и email для Let's Encrypt.
- Свободную приватную /24 для Docker; обычно достаточно предложенного значения.
- Title/текст сайта и учётные данные панели.

Пароль панели можно ввести вручную или получить от OpenSSL. Генерируемый пароль
показывается однократно в терминале: сохраните его в менеджере паролей.
Пароли **не сохраняются в state или .env**. Пользователь не добавляется в Docker group.

## 3. Две проверки SSH — обязательны

Сначала открываются новый и действующие SSH-порты, ставится таймер отката на 10 минут.
Root/password SSH ещё не отключены. Установщик напечатает команду входа через ключ:

```bash
ssh -o ControlMaster=no -o ControlPath=none -o PreferredAuthentications=publickey -o PasswordAuthentication=no -p PORT USER@VPS_IP
```

В **новой сессии** выполните напечатанную команду вида:

```bash
sudo /opt/vps-installer/app/install.sh --confirm-ssh TOKEN "$SSH_CONNECTION"
```

Она сверяет свежий `Accepted publickey` в journal ssh.service и sudo-пользователя.
Вернитесь в первую сессию и введите VERIFIED. После этого отключаются root/password/
keyboard-interactive SSH и запрашивается ещё одна новая сессия для окончательной проверки.

Управляемый файл SSH называется `/etc/ssh/sshd_config.d/00-00-vps-installer.conf`: он
читается раньше типичного провайдерского `00-custom-root.conf`. OpenSSH использует
первое значение; провайдерские файлы не удаляются. Проверяются действующие настройки
отдельно для admin и root, включая влияние Match.

Первую сессию держите открытой до окончания. Если вход не подтверждён или настройка
неверна, скрипт возвращает предыдущий SSH drop-in; при обрыве процесса работает таймер.
Из консоли провайдера доступен `/opt/vps-installer/ssh-rollback.sh`.
Если ваш образ ОС не пишет нужные события в journal, проверка остановится с откатом.
Старые UFW-правила SSH сохраняются до вашего ручного аудита; --check отмечает лишние правила.

## 4. Сайт и панель

Сайт: `https://ВАШ_ДОМЕН/`. HTML/CSS/JS локальные, внешних CDN и счётчика-сервиса нет.
Данные: `/opt/vps-installer/site`. Изменения сайта сохраняются при обычном повторном запуске.
Новая заглушка: CRT scanlines, canvas-сигнал, глитчи, орбиты, выдуманный терминал,
рандомайзер и кнопки WARP/«не нажимать». Телеметрия декоративная; счётчик тыков
локальный для браузера. FX можно остановить; учитываются настройки уменьшения движения.

Для обновления уже созданного сайта с сохранением БД/пароля панели:

```bash
curl -fL https://raw.githubusercontent.com/ComradDart/vps-installer/main/get.sh -o vps-bootstrap.sh
sudo bash vps-bootstrap.sh --reconfigure
```

Подтвердите замену трёх управляемых файлов сайта. Заголовок и текст можно оставить
прежними нажатием Enter. Установщик предварительно делает backup.


Панель публикуется **только на 127.0.0.1:2053 хоста**. Доступ с вашего компьютера:

```bash
ssh -N -L 2053:127.0.0.1:2053 -p PORT USER@VPS_IP
```

Откройте локально `http://127.0.0.1:2053/`. HTTP панели идёт внутри защищённого SSH-туннеля.
На хосте 2053 не открывается в Интернет. Внутри контейнера панель слушает `0.0.0.0:2053` —
это необходимо для Docker bridge и не означает публичную публикацию.
Subscription-порты не публикуются. gRPC-порт Xray 10000 доступен только в Docker bridge.
В отдельном режиме REALITY публичный TCP/443 принадлежит Xray; nginx остаётся его self-steal target.

Контейнеры: `vps-xui`, `vps-nginx`; bridge-сеть: `vps-installer-proxy`.
Публичные порты: выбранный SSH/TCP, 80/TCP для ACME, 443/TCP для сайта и выбранного VLESS-транспорта.

### Если ключ находится в Termius

Windows OpenSSH/PowerShell не получает ключи из хранилища Termius автоматически.
Для доступа без экспорта ключа выберите в Termius тот же SSH-хост и ключ,
пользователя `netadmin` (или выбранное при установке имя), затем создайте
**Port Forwarding → Local**: local port `2053`, destination `127.0.0.1`,
destination port `2053`. Запустите правило и откройте `http://127.0.0.1:2053/`.
Обычный `ssh -N -L ...` выше подходит, когда ключ действительно доступен OpenSSH.


127.0.0.1:8443 — локальная диагностика nginx TLS. UDP 80/443 и AWG не открываются.

## Автоматические режимы

| Режим | Публичный TCP/443 | Настройка |
|---|---|---|
| `cloudflare-grpc` (OUTBOUND) | nginx TLS/HTTP2 | `/vlessgrpc/Tun` → `grpc://xui:10000`; сайт на `/`; Cloudflare Proxied |
| `direct-grpc` (самостоятельный INBOUND) | nginx TLS/HTTP2 | тот же транспорт без обязательного Cloudflare |
| `direct-reality` | Xray REALITY / Vision | собственный домен в serverNames, target `nginx:8443`; сайт через self-steal |

Во всех режимах панель остаётся на host `127.0.0.1:2053`. Публикаций TCP/10000,
UDP/80 и UDP/443 нет. Для REALITY выбирайте DNS only; nginx и Xray не делят публичный 443.

Для `cloudflare-grpc` после первичного выпуска сертификата включите:

1. **Cloudflare Dashboard → DNS → Records → нужное имя → Proxy status: Proxied** (оранжевое облако).
2. **SSL/TLS → Overview → Full (strict)**.
3. **Network → gRPC → On**. В зоне должен быть включён HTTP/2.
4. Не применяйте challenge, cache или redirect, разрушающий gRPC POST, к
   `/vlessgrpc/*`; ACME webroot должен доходить до origin.

Установщик показывает этот checkpoint, проверяет публичные A/AAAA по официальным
Cloudflare networks и выполняет настоящий VLESS/gRPC-сеанс через публичный домен.
Сам факт HTTP 200 сайта или адрес Cloudflare успехом VLESS не считается. Если маршрут
не работает, установка завершается ошибкой с откатом; успех не объявляется.
Токен Cloudflare не нужен: переключатель gRPC включаете в dashboard.

Для INBOUND relay требуется готовая VLESS-ссылка OUTBOUND (gRPC/TLS или REALITY/Vision)
и **его выходной IPv4**, отличающийся от IP INBOUND. До изменения маршрутизации
выполняется реальная передача через этот профиль. Только после неё создаётся
полное правило inboundTag → заданный VLESS outbound; при падении OUTBOUND этот
трафик не переключается на direct. Управление VPS и прочие inbound не перенаправляются.
Без параметров OUTBOUND произвольная межсерверная схема не создаётся.

## 5. Проверка и обслуживание

```bash
sudo /opt/vps-installer/app/install.sh --show-client
sudo /opt/vps-installer/app/install.sh --status
sudo /opt/vps-installer/app/install.sh --check
sudo /opt/vps-installer/app/install.sh --backup
sudo /opt/vps-installer/app/install.sh --reset-3xui-password
sudo /opt/vps-installer/app/install.sh --reconfigure
```

- `--status`: состояние, контейнеры, sockets, firewall, timers.
- `--check`: реальная публикация Docker ports, health, nginx, БД, SSH effective config,
  UFW+DOCKER-USER, fail2ban SSH, время, сертификат, origin TLS/HTTP2, timers, API и
  настоящий VLESS-сеанс с проверкой выходного IP (через Cloudflare в соответствующем режиме).
- `--reset-3xui-password`: backup, краткая остановка только xui, официальный CLI,
  bcrypt verify, сравнение остальных таблиц. Весь стек не пересоздаётся, 2FA не сбрасывается.
- `--reconfigure`: только title/текст сайта, с backup и согласием на замену index/style/app.
  Роль, домен и SSH-порт этой командой не меняются.

Для уже установленного сервера обновите код и запустите автонастройку:

```bash
curl -fL https://raw.githubusercontent.com/ComradDart/vps-installer/main/get.sh -o vps-bootstrap.sh
sudo bash vps-bootstrap.sh --configure-xray
sudo /opt/vps-installer/app/install.sh --show-client
```

В терминале Termius команду `--show-client` можно выполнить в обычной SSH-сессии.
Она выводит готовую VLESS-ссылку; импортируйте её в клиент. Ссылка также хранится
root-only в `/opt/vps-installer/clients/vless.txt`, JSON для Xray — рядом.
Для дополнительных устройств создавайте отдельных клиентов в панели: серверный
inbound и nginx уже настроены. Секретные файлы не присылайте в отчёт об ошибке.

Обычный повторный запуск после успешной автонастройки сохраняет инфраструктуру,
пароль и UUID, делает backup и проверяет существующий inbound через API. Дубли не
создаются; самостоятельно изменённый или конфликтующий inbound не перезаписывается.
Активный транспорт не переключается автоматически. При незавершённой транзакции
сначала восстанавливается предыдущая конфигурация. `--configure-xray` не обновляет
образы: используется работающий `latest`. Фонового обновления контейнеров нет.

На новой установке образы скачиваются как `latest`, без версии/digest. API-адаптер
проверен на 3x-ui **3.11.0**: ссылка на этот release фиксирует изученный контракт,
а не тег контейнера. Если будущий `latest` меняет версию, автоматизация останавливается
до записи inbound, пока контракт не будет проверен и адаптер обновлён.

DNS проверяется до основных этапов настройки: пакетов установщика, создания пользователя, SSH/UFW и Docker.
Адреса прокси не обязаны совпадать с IPv4 origin: для них заранее выводится предупреждение,
а перед certbot обязательно проверяется точное содержимое случайного ACME-файла
через публичный домен. При ошибке выпуска nginx остаётся доступен по HTTP.
TLS выпускается только после DNS и точной проверки HTTP-01 webroot. Конфигурация с
несуществующим сертификатом не создаётся. Отдельный systemd timer обновляет сертификат,
проверяет его и выполняет nginx -t перед reload; при установке запускается renew --dry-run.

После запуска fail2ban установщик ждёт до 30 секунд готовности сокета и jail sshd. При ошибке выводит журнал службы.

Проверка listeners распознаёт системный DHCPv4-клиент `systemd-networkd`: UDP/68
на конкретном IPv4 с привязкой к интерфейсу не считается лишним сервером.
Посторонние UDP-порты и публичные 2053/10000 продолжают вызывать ошибку.

Fail2ban защищает **SSH**. Защита панели через fail2ban не заявляется. AWG, MTProxyL,
telemt не устанавливаются. Их старые сервисы сохраняются до вашего отдельного решения.

## 6. Backup / restore / uninstall

```bash
sudo /opt/vps-installer/app/install.sh --backup
sudo /opt/vps-installer/app/install.sh --restore /var/backups/vps-installer/FILE.tar.gz
sudo /opt/vps-installer/app/install.sh --uninstall
```

Daily backup хранится в `/var/backups/vps-installer`, root-only. SQLite снимается через
online backup API; отдельно сохраняются системные настройки и найденные legacy-каталоги.
Это не единая распределённая транзакция всех сервисов. Архив содержит секреты и ключи:
делайте зашифрованную offsite-копию. Автоматического удаления/ротации нет.

Restore проверяет checksum/права/пути архива/state/совпадение identity. Восстанавливается
только stack; SSH/UFW и legacy не откатываются автоматически. Предыдущее дерево сохраняется.
Данные старой БД могут быть несовместимы с новой latest — полный snapshot VPS остаётся
надёжным вариантом отката несовместимого обновления.

Uninstall требует YES, делает backup, убирает только managed контейнеры/сеть/systemd units.
БД, сайт, сертификаты, backups, SSH, пользователь, Docker и старые сервисы **сохраняются**.

## 7. Диагностика для передачи ошибки

```bash
sudo docker compose -p vps-installer --project-directory /opt/vps-installer -f /opt/vps-installer/compose.yml ps
sudo docker inspect vps-xui vps-nginx --format '{{.Name}} {{json .HostConfig.PortBindings}}'
sudo ss -lntup
sudo ufw status verbose
sudo iptables -S DOCKER-USER
sudo iptables -S VPS-INSTALLER
sudo fail2ban-client status sshd
sudo /usr/sbin/sshd -t
sudo /usr/sbin/sshd -T
sudo systemctl list-timers 'vps-installer-*'
sudo journalctl -u vps-installer-renew.service --since today
```

Пришлите ОС, текст ошибки и вывод --status без паролей/private keys/БД.
Дальнейшую ручную проверку смотрите в [MANUAL-TEST.md](docs/MANUAL-TEST.md).

## Разработка

Bash управляет apt/systemd/Docker; Python helpers валидируют JSON, атомарно пишут файлы
и безопасно работают с SQLite/архивами. State никогда не исполняется через source/eval.
Bind volumes разделяют данные БД, сайта, ACME и TLS. Пароль в upstream CLI кратко виден
host root в argv самого бинарника: точное ограничение описано в [SECURITY.md](docs/SECURITY.md).

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r tests/requirements.txt shellcheck-py==0.11.0.1
./tests/run.sh
RUN_DOCKER_INTEGRATION=1 ./tests/run.sh
```

Docker-тест использует локальный daemon, изолированные имена/сеть и высокие loopback-порты.
Host SSH/UFW/certbot не запускаются. CA одноразовый тестовый, не Let's Encrypt.
В rootless песочнице xui запускается под UID тестера с копией writable runtime bin;
production compose использует root контейнера с cap_drop ALL.
