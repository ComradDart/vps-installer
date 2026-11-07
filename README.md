# VPS Installer

Два VPS: входной в РФ и выходной за рубежом.

```text
Клиент → INBOUND :443 (VLESS/REALITY)
       → Cloudflare → OUTBOUND :443 (VLESS/gRPC/TLS)
       → nginx → Xray :10000 → интернет
```

На обоих узлах: SSH по ключам, sudo-пользователь `vpsadmin`, UFW, fail2ban,
обновления безопасности, chrony, Docker, 3x-ui/Xray, nginx, сайт, Let's Encrypt
с продлением и ежедневный backup. Панель — только `127.0.0.1:2053` через SSH.
Образы — **latest**. Опционально: Telegram-прокси telemt/MTProxyL на INBOUND :9443.

## Подготовка

- Debian 12/13 или Ubuntu 24.04/26.04 LTS, systemd, amd64/arm64.
- На каждом VPS: публичный IPv4, рекомендуется от 1 ГиБ RAM; минимум 4 ГиБ свободно в `/opt`.
- INBOUND: домен с A-записью на его IP, **DNS only**, без AAAA.
- OUTBOUND: отдельный домен, Cloudflare **Proxied**, gRPC и HTTP/2 включены,
  SSL/TLS **Full (strict)**. Рабочие настройки менять не требуется.
- У провайдера открыты TCP80/443 и SSH-порт; для telemt дополнительно TCP9443.
  Путь `/.well-known/acme-challenge/` должен проходить без кеша и WAF challenge.
- Сохраните SSH-сессию и доступ к консоли провайдера. Чужие сервисы и данные
  не удаляются; конфликт портов останавливает установку.

## Установка

На VPS выберите **один** вариант. Git и GitHub-токен не нужны.

**curl:**

```bash
setup_file=$(mktemp)
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/ComradDart/vps-installer/main/get.sh -o "$setup_file" && sudo bash "$setup_file"
rm -f "$setup_file"
```

**wget:**

```bash
setup_file=$(mktemp)
wget --https-only -O "$setup_file" https://raw.githubusercontent.com/ComradDart/vps-installer/main/get.sh && sudo bash "$setup_file"
rm -f "$setup_file"
```

Скачивается опубликованная ветка `main`. Установленная копия:
`/opt/vps-installer/app/install.sh`.

1. **Сначала OUTBOUND:** выберите роль `2`. Укажите его домен, origin IPv4,
   SSH-порт, email для сертификата и публичный SSH-ключ. Подтвердите новый SSH-доступ
   из второй сессии по подсказке установщика; старую не закрывайте.
2. Получите ссылку: `sudo /opt/vps-installer/app/install.sh --show-client`.
3. **Затем INBOUND:** запустите тот же установщик, выберите роль `1`, укажите
   параметры этого VPS. В скрытый запрос вставьте ссылку OUTBOUND и задайте
   ожидаемый внешний IPv4 OUTBOUND. Для telemt ответьте `yes`; Enter означает `no`.
4. На обоих узлах: `sudo /opt/vps-installer/app/install.sh --check`.

Inbound, UUID, nginx, gRPC, маршруты и публичные адреса ссылок настраиваются сами.
Между VPS используется **домен OUTBOUND**, а не прямой зарубежный IP.
При отказе выбранного outbound этот трафик не переключается на direct.

## Подключить клиента

На INBOUND выполните `sudo /opt/vps-installer/app/install.sh --show-client`
либо возьмите ссылку/QR клиента в панели. Импортируйте в клиент с поддержкой
VLESS/REALITY/Vision. Через прокси откройте `https://api4.ipify.org`: нужен IP OUTBOUND.
Ссылку OUTBOUND обычным клиентам не выдавайте: она нужна для связи VPS.

## Панель и доступ другим людям

Каждый создаёт **свой ключ на своём компьютере**. Задайте парольную фразу.
Если файл уже существует, выберите другое имя, чтобы не перезаписать его.

Linux/macOS:

```bash
ssh-keygen -t ed25519 -a 64 -f ~/.ssh/3xui_key
cat ~/.ssh/3xui_key.pub
```

Windows PowerShell — нужен компонент «Клиент OpenSSH»:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -a 64 -f "$env:USERPROFILE\.ssh\3xui_key"
Get-Content "$env:USERPROFILE\.ssh\3xui_key.pub"
```

Передайте администратору **только строку из `.pub`**. Приватный файл и его пароль
на VPS не загружайте. Такой же ключ используется для `vpsadmin` при установке.

Администратор на нужном VPS:

```bash
sudo /opt/vps-installer/app/install.sh --panel-users
```

Меню: **1** — добавить `panel_ivan` и его ключ; **2** — удалить; **3** — добавить
или заменить ключи; **4** — список; **5** — команда подключения. Удаление пользователя
или замена всех ключей завершают его открытые туннели. На втором VPS доступ добавляют отдельно.

На своём компьютере подставьте `SSH_PORT` и `SERVER_IP`:

```bash
ssh -N -T -o ExitOnForwardFailure=yes -p SSH_PORT -i ~/.ssh/3xui_key -L 127.0.0.1:2053:127.0.0.1:2053 panel_ivan@SERVER_IP
```

В Windows замените путь ключа на `"$env:USERPROFILE\.ssh\3xui_key"`.
Администратор использует `vpsadmin` и свой ключ. Пока SSH открыт, панель доступна
на **http://127.0.0.1:2053/**. Если порт занят, первое `2053` в `-L` замените
на `12053` и откройте `http://127.0.0.1:12053/`.

У приглашённых — только этот туннель, без shell, sudo, Docker, SFTP/SCP и других
перенаправлений. В 3x-ui одна общая учётная запись; её пароль выдаёт администратор.
Отзыв SSH-ключа не отзывает известный пароль панели и API-токены.

## Telegram-прокси — по желанию

Согласитесь при установке INBOUND или подключите позднее:

```bash
sudo /opt/vps-installer/app/install.sh --telemt
sudo mtproxyl secret link
```

Схема: **telemt :9443 → SOCKS 127.0.0.1:1080 → существующий VLESS outbound → OUTBOUND**.
Маскировка — существующий сайт `127.0.0.1:8443`; direct разрешён только для `local-mask`.
В ссылке — домен INBOUND и порт 9443. Порт 443 остаётся за VLESS/REALITY.

`--telemt` сохраняет UUID, ключи, межсерверный outbound, nginx и настройки OUTBOUND.
При добавлении Docker binding возможен короткий перезапуск только xui. Совместимый
нативный MTProxyL принимается без переустановки и смены секретов. Конфликтующий
Docker binding 9443 или другая установка вызывают ошибку, без удаления чужих данных.

При новой установке скачиваются актуальные MTProxyL и нативный движок.
WEB/Selfmask, Zapret2, Meko, WARP и дополнительные контейнеры не включаются.
На VPS с малой RAM менеджер может создать swap. Приватный журнал:
`/opt/vps-installer/telemt-install.log`. На OUTBOUND telemt не нужен.
Ответ `no` не добавляет пакеты и порты; SOCKS, панель, API и метрики остаются локальными.

## Обновление и backup

**Обновить только скрипт**, сохранив конфиги, маршруты и контейнеры:

```bash
setup_file=$(mktemp)
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/ComradDart/vps-installer/main/get.sh -o "$setup_file" && sudo bash "$setup_file" --update
rm -f "$setup_file"
```

Для wget используйте строку из установки, добавив `--update` после `sudo bash "$setup_file"`.
Для Git: `cd ~/vps-installer && git pull --ff-only && sudo bash ./install.sh --update`.
Если telemt уже настроен вручную, после обновления выполните `--telemt` на INBOUND,
чтобы проверить и зарегистрировать его. Основную установку повторять не нужно.

**Обновить контейнеры latest** в окно обслуживания:

```bash
sudo /opt/vps-installer/app/install.sh --backup
sudo docker compose -p vps-installer -f /opt/vps-installer/compose.yml pull
sudo docker compose -p vps-installer -f /opt/vps-installer/compose.yml up -d
sudo /opt/vps-installer/app/install.sh --check
```

API проверен для 3x-ui 3.11.0. При изменении контракта latest автоматизация
остановится до правки inbound; проверку версии не обходите вслепую.

Backup: `/var/backups/vps-installer`. Данные: `/opt/vps-installer`, MTProxyL — `/opt/mtproxyl`.
Архивы содержат секреты: копируйте их за пределы VPS с шифрованием. Повторная установка
сохраняет пароль, клиентов, UUID, сертификаты и сайт. Восстановление той же роли,
домена, IP, SSH-порта и режима telemt:

```bash
sudo /opt/vps-installer/app/install.sh --restore /var/backups/vps-installer/ARCHIVE.tar.gz
```

Архив и `.sha256` — root-owned, mode 600. При сбое запуска возвращается предыдущий стек.
SSH/UFW и native MTProxyL восстанавливаются вручную; их основные конфиги сохранены
в `system.tar.gz` внутри backup. Для MTProxyL также доступен `sudo mtproxyl backup`.

## Полезные команды

Аргументы ниже: `sudo /opt/vps-installer/app/install.sh АРГУМЕНТ`.

| Аргумент | Действие |
|---|---|
| `--status` / `--check` | Статус / проверка стека, SSH, HTTPS, firewall и передачи VLESS |
| `--check-xray` / `--check-xray-client EMAIL` | Проверить VLESS / выбранного клиента |
| `--show-client-for EMAIL` | Показать ссылку выбранного клиента |
| `--repair-client-links` | Исправить localhost в штатных ссылках/QR |
| `--reset-3xui-password` | Сменить пароль панели, сохранив клиентов; краткая остановка xui |
| `--backup` / `--help` | Создать backup / показать все команды |

Логи: `sudo docker logs --tail 100 vps-xui` или `vps-nginx`.
Диагностика: `sudo docker exec vps-nginx nginx -t`, `sudo ufw status verbose`,
`sudo fail2ban-client status sshd`; для telemt — `sudo systemctl status mtproxyl-telemt`.

## Если не работает

- **HTTPS/сертификат:** DNS, TCP80/443, HTTP-01 без WAF, `nginx -t`, логи nginx.
- **Cloudflare/gRPC:** Proxied, Full (strict), HTTP/2, gRPC, SNI домена OUTBOUND,
  `serviceName=vlessgrpc`; внутренний TCP10000 не публикуется.
- **VLESS/связь VPS:** `--check-xray` на обоих узлах, UUID, лимиты клиента,
  домен и ожидаемый IP OUTBOUND. Не добавляйте direct для обхода сбоя.
- **Панель/туннель:** SSH-порт, свой приватный ключ, имя пользователя, свободный
  локальный порт. Не открывайте 2053 в firewall.
- **Telegram:** TCP9443 у провайдера/UFW, служба telemt, локальный SOCKS1080,
  `sudo mtproxyl secret link`. Его параметры не настраиваются в панели 3x-ui.

Перед production проверьте SSH из второй сессии, внешний scan портов, IP клиента,
отказ OUTBOUND без выхода через РФ, продление TLS и restore. Локальные тесты
не заменяют реальное развёртывание. Разработка: `tests/requirements.txt` и `bash tests/run.sh`.
