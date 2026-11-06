# Отчёт о проверках

Дата: 6 ноября 2026. Итоговый scope: первичная настройка VPS, nginx + локальный сайт + 3x-ui в Docker. Никаких Xray inbound/clients/транспортов установщик не создаёт.

Все контейнеры используют latest по требованию заказчика. В момент проверки latest содержал 3x-ui 3.11.0 / Xray 26.10.21 и nginx 1.31.8. Это сведения о проведённом испытании, не закрепление версий.

## PASSED

- Bash syntax для всех Bash файлов.
- ShellCheck 0.11.0 для entrypoints, lib и test runner, exit 0. Исключения SC2034 документируют межмодульные state flags; SC1090/source обоснованы локальными модулями.
- 62 unit/negative теста, pytest. DNS/GHCR/daemon/ACME failure здесь инъекции отказа, не реальные внешние проверки.
- 3 настоящих Docker integration теста, 66.69 секунды: полный последовательный сценарий инфраструктуры и Compose config для обеих ролей.

- Official CLI bootstrap before server start; bcrypt verification
- Real 3x-ui and nginx startup and health checks
- HTTP login with chosen credentials and current CSRF mechanism
- nginx configuration accepted by actual image
- CA-verified TLS, domain validation, ALPN and HTTP/2 site GET
- Real HTTP ACME webroot serving; no certificate issuance claimed
- Official CLI credential reset, new HTTP login, unchanged non-user tables
- Previous password rejected after reset
- Repeated rendering/up preserves custom site, credentials and empty initial inbound list
- Consistent SQLite snapshot and recovery verified with live panel settings
- Chosen old/new passwords absent from normal Docker logs
- Actual PortBindings: loopback panel, no public gRPC port, no added capabilities

## FAILED

В финальном сокращённом наборе отсутствуют. До уточнения scope разрабатывался отдельный gRPC E2E; он не был завершён и исключён вместе с транспортными модулями. Работа gRPC/REALITY не заявляется и не входит в итоговый установщик.

## NOT RUN

- Полная root установка на настоящих Debian 12, Debian 13, Ubuntu 24.04 LTS.
- Реальная конфигурация SSH/Ubuntu ssh.socket, проверка новых внешних сессий и таймера rollback.
- Host UFW/fail2ban/DOCKER-USER, external IPv4/IPv6 port scan.
- Настоящий DNS/Let's Encrypt HTTP-01/renew --dry-run и публичная цепочка.
- Полный архивный --restore, миграция legacy-сервисов и --uninstall на VPS.
- Full OS reboot, unattended upgrades и chrony на VPS.
- arm64.

## MANUAL

Последовательность дана в MANUAL-TEST.md. Требуется отдельная тестовая VPS с snapshot и консолью провайдера. Это тестовый кандидат; production readiness не заявляется.

## Условия контейнерного теста

Rootless Docker 29.9.2 / Compose 2.40.3, Debian 13 managed environment, amd64. Использовались отдельные имена/сеть и высокие loopback порты. Host firewall/sshd не менялись. В rootless среде xui запускался под UID тестера с writable копией /app/bin; production Compose запускает его под штатным container root без capabilities. Приватный ключ одноразового тестового CA был доступен только внутри тестовой папки; реальные deploy права TLS проверяются вручную.

TLS проверялся через временный доверенный CA и hostname, без curl -k. Наличие выбранных паролей в normal Docker logs отдельно проверено; секреты в state/.env не писались. Snapshot SQLite был реально восстановлен и прочитан работающей панелью. Это не доказательство полного архивного --restore.

Архивный backup/restore защищён owner/mode/sha256/path checks и имеет негативный unit test недоверенного архива, но полный root lifecycle требует VPS. Не выдавайте mocks за E2E.

## Обновление: Ubuntu 26.04 и установка без Git

- Добавлен Ubuntu 26.04 LTS (включая образ 26.04.1 с VERSION_ID=26.04).
- Проверены официальная документация Docker и доступность Release для resolute.
- 78 unit/negative тестов проходят: добавлены матрица ОС, диагностика версии,
  безопасная распаковка bootstrap и cleanup при отказе.
- get.sh скачивает main по HTTPS через curl/wget без Git, проверяет структуру архива,
  ставит только отсутствующие bootstrap prerequisites и запускает текущий install.sh.
- Для fail2ban backend=systemd явно добавлен python3-systemd (recommends не устанавливаются).
- Standalone download/vps_setup.sh пересобран с текущим кодом и проверен распаковкой.
- Полная установка SSH/UFW/ACME на Ubuntu 26.04 остаётся MANUAL; прежняя серия
  трёх Docker integration тестов относится к инфраструктуре, а не полной ОС.
- FAILED (ограничение тестовой среды): apt simulation в контейнере Ubuntu 26.04.1
  не завершилась из-за доверия к TLS-сертификату прокси песочницы. Это не успешная
  проверка установки пакетов; реальное развёртывание на Ubuntu 26.04 остаётся MANUAL.

## Обновление: readiness fail2ban

- Вместо мгновенного status sshd после restart проверяются socket ping и готовность
  jail с ожиданием до 30 секунд. Служба запускается одним restart после enable.
- При failed state или timeout выводятся systemctl status, journal и fail2ban.log;
  ошибка не игнорируется и установка не продолжается без SSH jail.
- 4 новых unit-теста: задержка сокета, задержка jail, падение службы и timeout.
  Итого 82 unit-теста. Реальная служба на VPS требует повторной проверки.
