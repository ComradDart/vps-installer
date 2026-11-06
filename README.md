# Первоначальная настройка VPS + nginx + сайт + 3x-ui

Установщик настраивает VPS, создаёт sudo-пользователя и доступ по SSH-ключу,
устанавливает UFW, fail2ban для SSH, chrony, безопасные автообновления, Docker,
**3x-ui и nginx в Docker**, локальный сайт и настоящий сертификат Let's Encrypt.

По вашему уточнению все образы — **latest**, без закрепления версии/digest:

```text
ghcr.io/mhsanaei/3x-ui:latest
nginx:latest
```

**Xray inbound, клиенты, транспорт и межсерверные маршруты не создаются.**
Панель остаётся для вашей самостоятельной настройки. Выбор INBOUND/OUTBOUND —
метка сервера; первоначальная инфраструктура обеих ролей одинаковая.

Полная установка на VPS пока не проверена. Контейнерные проверки и точные ограничения
перечислены в [отчёте](docs/TEST-REPORT.md). Сначала используйте тестовую VPS.

## 1. Подготовка

Целевые ОС: Debian 12 / Debian 13 / Ubuntu 24.04 / 26.04 LTS с systemd, amd64/arm64.
Реальная контейнерная проверка выполнена на amd64. Нужны root/sudo, консоль провайдера,
минимум 4 GiB свободного места, собственный домен и свободные TCP 80/443/2053/8443.

- Сделайте snapshot у провайдера и проверьте serial/VNC-консоль.
- Создайте **A-запись домена на IPv4 этой VPS**. Поддомен необязателен.
- Для первого выпуска сертификата используйте DNS only в Cloudflare, без Proxy.
- Удалите AAAA этого origin: базовое развёртывание IPv4-only.
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

- Метку INBOUND или OUTBOUND.
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

Первую сессию держите открытой до окончания. Если вход не подтверждён или настройка
неверна, скрипт возвращает предыдущий SSH drop-in; при обрыве процесса работает таймер.
Из консоли провайдера доступен `/opt/vps-installer/ssh-rollback.sh`.
Если ваш образ ОС не пишет нужные события в journal, проверка остановится с откатом.
Старые UFW-правила SSH сохраняются до вашего ручного аудита; --check отмечает лишние правила.

## 4. Сайт и панель

Сайт: `https://ВАШ_ДОМЕН/`. HTML/CSS/JS локальные, внешних CDN и счётчика-сервиса нет.
Данные: `/opt/vps-installer/site`. Изменения сайта сохраняются при обычном повторном запуске.

Панель публикуется **только на 127.0.0.1:2053 хоста**. Доступ с вашего компьютера:

```bash
ssh -N -L 2053:127.0.0.1:2053 -p PORT USER@VPS_IP
```

Откройте локально `http://127.0.0.1:2053/`. HTTP панели идёт внутри защищённого SSH-туннеля.
На хосте 2053 не открывается в Интернет. Внутри контейнера панель слушает `0.0.0.0:2053` —
это необходимо для Docker bridge и не означает публичную публикацию.
Subscription-порты и Xray-порты не публикуются. Дальнейшие inbound/clients/порты настраиваете вы.

Контейнеры: `vps-xui`, `vps-nginx`; bridge-сеть: `vps-installer-proxy`.
Публичные порты: выбранный SSH/TCP, 80/TCP для ACME, 443/TCP для сайта.
127.0.0.1:8443 — локальная диагностика nginx TLS. UDP 80/443 и AWG не открываются.

## 5. Проверка и обслуживание

```bash
sudo /opt/vps-installer/app/install.sh --status
sudo /opt/vps-installer/app/install.sh --check
sudo /opt/vps-installer/app/install.sh --backup
sudo /opt/vps-installer/app/install.sh --reset-3xui-password
sudo /opt/vps-installer/app/install.sh --reconfigure
```

- `--status`: состояние, контейнеры, sockets, firewall, timers.
- `--check`: реальная публикация Docker ports, health, nginx, БД, SSH effective config,
  UFW+DOCKER-USER, fail2ban SSH, время, сертификат, origin TLS/HTTP2, timers.
- `--reset-3xui-password`: backup, краткая остановка только xui, официальный CLI,
  bcrypt verify, сравнение остальных таблиц. Весь стек не пересоздаётся, 2FA не сбрасывается.
- `--reconfigure`: только title/текст сайта, с backup и согласием на замену index/style/app.
  Роль, домен и SSH-порт этой командой не меняются.

Обычный повторный запуск `sudo .../install.sh` сохраняет учётную запись, БД и сайт,
делает backup, выполняет `docker compose pull` для **latest** и повторяет инфраструктурные проверки.
Фонового обновления контейнеров нет. Будущая latest может изменить CLI/схему БД;
проверяйте обновления сначала на тестовой VPS.

После вашей ручной настройки Xray/новых публикаций baseline --check может сообщать
о дополнительных портах. Автоматическое применение ваших inbound/transport правил в scope
этого установщика не входит. Compose/nginx файлы генерируются программой; после их
самостоятельной переработки не запускайте повторное развёртывание вслепую.

TLS выпускается только после DNS и точной проверки HTTP-01 webroot. Конфигурация с
несуществующим сертификатом не создаётся. Отдельный systemd timer обновляет сертификат,
проверяет его и выполняет nginx -t перед reload; при установке запускается renew --dry-run.

После запуска fail2ban установщик ждёт до 30 секунд готовности сокета и jail sshd. При ошибке выводит журнал службы.

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
