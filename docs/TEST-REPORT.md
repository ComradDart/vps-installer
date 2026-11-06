# Отчёт о тестировании

Дата: 6 ноября 2026. Scope: VPS baseline + Docker nginx/site/3x-ui и автоматическая
настройка VLESS через официальный API, включая gRPC/TLS, отдельный REALITY/Vision
и INBOUND relay с явно заданным OUTBOUND.

Образы остаются **latest**, без pin версии/digest. Во время испытаний:
3x-ui 3.11.0, Xray 26.10.21, nginx 1.31.8, rootless Docker 29.9.2 / Compose 2.40.3,
amd64. Это наблюдавшиеся версии, а не закрепление контейнеров.

## Статус

- **PASSED:** Bash syntax, ShellCheck и 156 unit/negative тестов.
- **PASSED:** настоящий gRPC/TLS → nginx → Xray data transfer; API creation,
  повторный запуск без дубликатов и сохранение UUID, проверка port owner/10000.
- **PASSED:** реальный отказ клиентской передачи → откат файлов/inbound/созданного
  клиента → успешная повторная попытка с тем же UUID.
- **PASSED (ранний отдельный прогон):** REALITY/Vision, проверка nginx target и
  настоящий клиент, повторный запуск. Полный финальный повтор не завершён.
- **PASSED (предыдущая серия baseline):** 3 Docker-теста инфраструктуры, TLS/HTTP2,
  reset/SQLite snapshot и Compose для обеих ролей; host lifecycle ими не покрыт.
- **FAILED — ограничение среды:** финальные повторные Docker-прогоны прекращены
  с `no space left on device` при пересоздании контейнеров, в том числе при откате.
  Это не PASSED и не подтверждение полной установки. Приватный transaction journal
  сохраняется для восстановления после освобождения места.
- **NOT RUN до конца:** положительный relay/fail-closed сценарий. Его начальная
  проверка недоступного OUTBOUND выполнялась без локальных API изменений, но
  дальнейшее создание контейнеров прерывалось из-за диска. Автотест добавлен;
  полный результат требует среды с достаточным диском.
- **Cloudflare E2E: NOT RUN.**

На момент коммита нет единого полностью прошедшего финального Docker-прогона.
Нельзя считать REALITY/relay и всю VPS установку полностью проверенными.

## Что проверяют автоматические тесты

- Официальный CLI инициализирует администратора до запуска; bcrypt и настоящий HTTP
  login с CSRF подтверждают credentials. Reset проверяется отдельно; остальные
  таблицы и настройки сохраняются. API-токен проверяется реальным запросом.
- Через работающий API создаётся VLESS gRPC inbound: 10000, 0.0.0.0, enable,
  security none, decryption none, пустой flow, serviceName vlessgrpc.
- Реальный nginx принимает TLS с доверенной одноразовой CA, ALPN h2, обслуживает
  сайт и передаёт /vlessgrpc/Tun в grpc://xui:10000. Отдельный настоящий Xray-клиент
  передаёт HTTP-данные через VLESS; HTTP 200 сайта не используется как доказательство.
- REALITY: официальная генерация X25519 keys, собственный serverName, Vision,
  проверка nginx self-steal target из Xray и настоящий клиентский обмен.
- Повторный запуск сохраняет inbound id и UUID, не создаёт дубликатов. Unit-тест
  проверяет восстановление UUID из API при потере локального cache и отказ при
  конфликтующем/изменённом inbound или чужом клиенте.
- Actual Docker PortBindings: единственный владелец публичного тестового TLS-порта,
  отсутствие публикации TCP/10000, закрытая панель; UDP/80 и UDP/443 запрещены.
- Кандидаты Compose и nginx проходят реальные проверки до применения.
- Ошибка настоящего клиентского transfer откатывает файлы, созданный inbound и
  принадлежащего транзакции непривязанного клиента. Повторная попытка использует тот же UUID.
- Relay сначала проверяет заданный OUTBOUND настоящим клиентом. Недоступный peer не
  меняет local inbound/template. Рабочий peer выдаёт отличимый выходной ответ;
  после его остановки передача прекращается, direct fallback отсутствует.
- Секреты отсутствуют в обычных Docker logs; API errors не раскрывают тела ответов.
- Baseline: TLS/HTTP2 сайта, точные ACME bytes через HTTP и HTTPS, persistent DB/site,
  reset credentials и восстановление настоящего SQLite snapshot.
- Bash syntax / ShellCheck; schema validation, DNS/proxy, SSH proof parsing,
  fail2ban readiness, безопасная распаковка и отрицательные сценарии.

## Условия и ограничения

Это **контейнерные интеграционные тесты, не две полноценные VM**. Имена/сети изолированы,
порты высокие и loopback. Host SSH/UFW/systemd/apt не меняются. Тестовая CA проверяется
нормальным способом, без curl -k. Для частного HTTP fixture добавляется точечное
исключение из private-IP guard только внутри теста; production template не ослабляется.

В rootless песочнице xui запускается под UID тестера с writable копией bin. Для
отдельного тестового OUTBOUND и reference client официальный Xray-бинарник запускается в лёгком
nginx:latest контейнере с отдельным конфигом: это экономит VFS-диск. Production
xui использует штатный container root с cap_drop ALL, без таких fixture-модификаций.

Разработка обнаружила и устранила оставшуюся после удаления inbound запись клиента
в 3.11.0. Параллельные, а затем и последовательные повторные Docker-прогоны завершались
ошибкой нехватки диска VFS; они не учитываются как PASSED. После освобождения
места требуется повторить полный набор в более вместительной среде.
Ранее apt simulation Ubuntu 26.04 не прошла из-за TLS trust прокси среды: успешная
установка пакетов на этой ОС этим не доказана.

## NOT RUN / MANUAL

- **Внешний Cloudflare E2E: NOT RUN.** Нет предоставленной зоны/публичного origin
  и настоящего сертификата для этого теста. В pytest задан явный skip с этой причиной;
  origin PASSED не подменяет внешний E2E. На VPS установка требует и origin, и
  настоящий публичный VLESS-сеанс перед объявлением готовности.
- Полная установка с нуля на Debian 12/13, Ubuntu 24.04/26.04 LTS, arm64.
- Реальные внешние SSH-сессии, ssh.socket, UFW/DOCKER-USER/fail2ban, сканирование
  портов, reboot и chrony/unattended upgrades на VPS.
- Публичный Let's Encrypt HTTP-01 и renew --dry-run.
- Полный архивный --restore, legacy migration и --uninstall на VPS.

Порядок ручной проверки: [MANUAL-TEST.md](MANUAL-TEST.md).

## Воспроизведение

```bash
./tests/run.sh
RUN_DOCKER_INTEGRATION=1 ./tests/run.sh
```

Зависимости перечислены в tests/requirements.txt; ShellCheck также нужен.
Тесты создают только свои Docker-ресурсы и удаляют их при завершении.
Для VFS нужен достаточный свободный диск; одновременные прогоны не рекомендуются.

## Исправление SSH precedence (6 ноября 2026)

В конфигурации пользователя `00-custom-root.conf` задавал PermitRootLogin yes и
PasswordAuthentication yes раньше прежнего `00-vps-installer.conf`. OpenSSH брал
первое значение, и установка правильно останавливалась до reload lockdown.

- Managed drop-in переименован в `00-00-vps-installer.conf`, раньше provider файла.
  Снимок, staging, финальная запись и rollback используют один и тот же новый путь.
- Provider/cloud-image файлы сохраняются. Проверка PermitRootLogin выполняется для
  root; ошибки показывают фактическое и ожидаемое значение.
- **PASSED:** 107 unit/negative тестов, Bash syntax и ShellCheck.
- 4 новых тестовых случая используют настоящий OpenSSH 10.0p2 Debian-7+deb13u4
  в режиме разбора временного конфига: воспроизведение прежнего конфликта,
  исправленный приоритет, обнаружение Match override и два варианта реального
  восстановления файлов rollback (с прежним managed файлом / без него).
  Служба SSH песочницы не запускалась и не перезагружалась.
- Внешние SSH-сессии и systemd timer на VPS остаются MANUAL; Docker/Cloudflare
  повторно для этого изменения не проверялись. Их ограничения выше сохраняются.

## Исправление инвентаризации DHCP (6 ноября 2026)

Системный UDP/68 listener `systemd-network` на IPv4 с `%interface` ошибочно считался
публичным сервером. Теперь он распознаётся как DHCPv4-клиент systemd-networkd.
Исключение требует UDP/68, конкретный IPv4, интерфейс и известное имя процесса
из ss (включая усечённое до 15 символов). Wildcard bind, неизвестный владелец,
TCP/68 и другие UDP-порты по-прежнему отмечаются как неожиданные. Проверка остаётся
инвентаризацией, а не доказательством внешней доступности или подлинности процесса.

- **PASSED:** 120 unit/negative тестов, Bash syntax и ShellCheck.
- 13 новых случаев: реальный формат DHCP из сообщения пользователя, оба варианта
  имени networkd, отсутствие владельца, неизвестный процесс, неправильный bind,
  публичные 2053/10000, UDP/80/443 и смешанный список DHCP с посторонним listener.
- Конфигурация firewall и Docker не менялась; повторный Docker/Cloudflare E2E для
  этого исправления не запускался. Проверка на VPS остаётся ручной.

## Вывод проверки автообновлений (6 ноября 2026)

`unattended-upgrade --dry-run` раньше запускался с подавлением только stdout.
В stderr попадали печатаемые APT команды dpkg и Python DeprecationWarning о fork.
Сама проверка оставалась симуляцией, но вывод выглядел как реальная установка.
Теперь оба потока записываются в root-only unattended-upgrade-check.log (600).
Перед запуском явно показано, что это dry-run; после — краткий результат. Ненулевой
exit status выводит последние 30 строк и останавливает установку, не маскируясь успехом.
Политика security-only и само поведение пакетного менеджера не изменялись.

- **PASSED:** 123 unit/negative теста, Bash syntax, ShellCheck.
- Три новых теста со stub пакетного менеджера проверяют захват обоих потоков,
  остановку/диагностику при отказе и права/замену предыдущего лога. Это тесты
  обработки вывода, не реальный apt/unattended-upgrade прогон на Ubuntu.
- Реальный dry-run на VPS и повторный Docker/Cloudflare E2E для этого изменения
  не запускались; предыдущие ограничения отчёта остаются в силе.

## INBOUND REALITY и миграция (6 ноября 2026)

Новый INBOUND использует REALITY/Vision с target nginx:8443; relay — первый вариант
выбора topology. gRPC остаётся режимом OUTBOUND/его клиентского профиля. Добавлена
явная команда --migrate-inbound-reality для старого managed INBOUND gRPC.

- **PASSED:** 135 unit/negative тестов, Bash syntax и ShellCheck.
- Проверены сохранение inbound id/tag и UUID всех клиентов, Vision, сохранение
  metadata/квот, повтор без регенерации ключей, отказ при изменённой identity,
  отказ для OUTBOUND и выбор правильного транспорта для каждой роли.
- Файловая модель транзакции проверяет отказ после смены владельца 443, восстановление
  Compose/profile/cache/API и успешную повторную попытку с теми же UUID/ключами.
  Docker и передача данных в этом unit-сценарии — stubs, не E2E.
- Настоящий API-прогон на официальных бинарниках 3x-ui/Xray выявил автопереименование
  tag при смене порта. Исправлено переходом через временный custom tag с возвратом
  прежнего tag; следующее выполнение дошло до применения Compose после изменения
  транспорта и flow через API.
- **FAILED / BLOCKED окружением:** Docker-переход портов оборвался на ENOSPC
  (заполнен VFS-диск песочницы). Повтор с облегчённым тестовым filesystem также
  остановился при подготовке из-за отсутствия места. Возврат после полного
  Docker-handoff, обычный HTTPS через REALITY self-steal и полный повтор миграции
  в текущей версии **не подтверждены реальным E2E**. Тест для них добавлен в
  tests/integration/test_reality_migration.py; нужен повтор в среде с диском.
- **NOT RUN:** внешний Cloudflare E2E и миграция на настоящей VPS. Предыдущие
  результаты обычного gRPC/REALITY не заменяют эту проверку миграции.

В production Compose остаются только официальные latest образы. Test fixture
может запускать те же официальные бинарники и musl loader в уменьшенном filesystem
через VPS_TEST_RUNTIME; это не эквивалент полноценной VM и не развёртываемый образ.

## Восстановление после ручного удаления (7 ноября 2026, Москва)

Пользователь удалил старый gRPC inbound и клиента в панели. Раньше команда
--migrate-inbound-reality требовала существующий inbound и останавливалась.
Теперь при отсутствии обоих она создаёт новый REALITY/Vision с UUID из сохранённого
cache, без изменения OUTBOUND-профиля. Конфликт порта, занятый UUID или оставшийся
старый клиент не приводят к удалению/перезаписи чужих данных.

- **PASSED:** 138 unit/negative тестов, Bash syntax и ShellCheck.
- Три новых unit-сценария: создание после удаления, отказ с сохранением оставшегося
  клиента, откат создания с первоначальным профилем gRPC (как после перезапуска).
  Проверены удаление только созданного inbound/непривязанного клиента, возврат
  Compose/cache/profile и сохранение UUID. Docker/client transfer в модели — stubs.
- Ownership при recovery берётся из приватного journal: новый REALITY inbound
  находится даже когда на диске пока сохранён старый gRPC profile.
- Полный Docker/VPS/Cloudflare E2E этой ветки **NOT RUN**: заполненный диск среды
  остаётся ограничением. Результаты предыдущих отдельных проверок его не заменяют.

## Адрес экспорта и переименование (7 ноября 2026, Москва)

- **PASSED:** 149 unit/negative тестов, Bash syntax и ShellCheck.
- Создаваемые и мигрируемые inbound явно задают custom share address = домену
  state. Listen остаётся 0.0.0.0. Проверены оба экспорта (panel metadata и VLESS URI),
  идемпотентный ремонт metadata, сохранение клиентов/порта и откат share address.
- Ownership больше не зависит от remark: сохранённые id/UUID подтверждают renamed
  inbound. Проверены отсутствие дубля, сохранение пользовательского имени при
  миграции, отказ при чужом UUID/перенесённом id и отдельный путь --check-xray.
- --check-xray показывает этапы API/publications, internal transfer и public transfer.
  Подмена этих шагов host hardening/apt-проверками исключена unit-сценарием.
- Это unit-проверки и файловая модель API, не новый Docker/VPS/Cloudflare E2E.
  Полный E2E этой версии **NOT RUN** из-за прежнего ограничения диска среды.

## Диагностика выбранного клиента (7 ноября 2026, Москва)

- **PASSED:** 156 unit/negative тестов, Bash syntax и ShellCheck.
- --check-xray-client EMAIL не зависит от удалённого служебного UUID: выбирает
  единственную текущую VLESS-привязку email через API, сохраняет реальные enable/flow
  и использует текущие serverNames/shortIds. UUID/серверные параметры не изменяются.
- Этапы проверки: заданный OUTBOUND (для relay), internal INBOUND, public INBOUND.
  При отличии выходного IP ошибка явно сообщает, что данные были переданы, но
  выбранный маршрут не соответствует ожидаемому.
- --show-client-for EMAIL пишет актуальный профиль только в tty. X25519 public key
  детерминированно выводится из существующего private key через OpenSSL DER/stdin;
  серверный private key не попадает в argv, environment, stdout или URI.
- Семь unit-сценариев: RFC7748 вектор, устаревшая public-key metadata, отсутствие
  test-client cache, фактический пустой flow, неоднозначность/disabled client,
  отсутствие API mutations/утечек stdout и вывод URI только в терминал.
- Эти тесты не являются новым сетевым E2E. Docker/VPS/Cloudflare E2E новой команды
  в песочнице **NOT RUN**; пользовательская проверка на VPS ожидается отдельно.


## SSH-доступ к общей панели (7 ноября 2026, Москва)

- **PASSED:** 175 unit/negative тестов, Bash syntax и ShellCheck.
- **PASSED, реальный сетевой интеграционный тест:** Alpine latest, OpenSSH
  10.3_p1, отдельные Linux UID для основного администратора и tunnel-пользователя.
  Разрешённый publickey-туннель реально передаёт HTTP-данные с 127.0.0.1:2053.
- **PASSED:** запрет exec, PTY shell, SFTP/SCP; отказ direct-tcpip к другому порту
  и к localhost вместо разрешённого литерала; отказ reverse-forwarding.
- **PASSED:** замена ключа закрывает старый активный туннель, старый ключ отвергается,
  новый работает; удаление аккаунта закрывает активный туннель и запрещает новые входы.
- **PASSED:** синтаксически ошибочная политика и перекрывающий PermitTTY более ранний
  Match вызывают откат; рабочий ключ сохраняется. Основной администратор реально
  выполняет SSH-команду до и после; его эффективная конфигурация и настройки root
  не изменились. Agent/X11/Unix-socket/tun запрещены проверкой эффективных параметров.
- **NOT RUN:** запуск systemd rollback timer, Debian/Ubuntu host SSH с PAM.
  В контейнере методы reload/watchdog адаптированы: настоящий sshd получает SIGHUP,
  планировщика systemd нет. Тело отката проверено; работа timer на VPS не заявляется.
- Общие Docker/Xray/Cloudflare E2E заново не запускались: эта функция их не меняет.
  После просьбы пользователя дополнительные тестовые прогоны остановлены.
- Воспроизведение: `bash scripts/test_panel_ssh.sh`; реализация сценария —
  `tests/integration/panel_ssh_scenario.py`. Не запускать этот сценарий напрямую на VPS: 
  он создаёт тестовые Linux-учётные записи.


## Публичные ссылки INBOUND / REALITY (7 ноября 2026, Москва)

Область по последнему уточнению: только INBOUND. OUTBOUND и gRPC не изменялись.
Latest сохранён; API-адаптер проверяет совместимость с контрактом 3.11.0.

- **PASSED:** 10 точечных тестов за 12.40 секунд: один сетевой/browser сценарий
  настоящей панели, три проверки конфигурации и шесть существующих проверок
  share-address. Полный набор тестов заново не запускался.
- Настоящий официальный release-бинарник 3x-ui 3.11.0 запускался с отдельной
  временной БД. База изменялась только официальными API; SQL-правок нет.
- Получены настоящие `/panel/api/clients/subLinks/:subId` и raw/base64 subscription
  с фактическим случайным subPath. Проверены Address=PUBLIC_DOMAIN, порт443,
  security=reality, flow клиента, существующие SNI/Short ID и выведенный из
  текущего private key корректный непустой pbk.
- Ответы API одинаковы с Host localhost, 127.0.0.1, Docker-IP и внешним hostname.
  В Chromium выполнен настоящий login через localhost и 127.0.0.1. Штатный QR
  VLESS из React UI декодирован ZXing и совпадает с ответом panel API. Для чтения
  используется точный SVG панели, перерисованный без анимации; собственный QR
  тест не генерирует.
- Повтор сохраняет один Host group, UUID/subId, flow, private key, Short IDs и
  внутренние listener/tag/port. Проверены PUBLIC_DOMAIN/root-only state и отказ
  от работы с OUTBOUND до вызова его API.
- Через настоящее Settings API подтверждены публичные subURI и неизменный
  webDomain. nginx-файлы в этой export-only fixture моделируются; вызовы nginx
  validation/reload заменены заглушкой. В production они выполняются до/при
  применении; ошибка запускает откат API metadata/settings и nginx-файлов.
- **NOT RUN:** публичная подписка через nginx и REALITY self-steal, реальная
  передача пользовательского трафика в этой новой проверке, deployment на VPS.
  Xray не запускался: тест проверяет настоящий экспорт/UI панели, а не VPN E2E.
  Docker-образ в этом прогоне не запускался из-за ограничения диска среды.

Воспроизведение (Python pytest/playwright/Pillow/zxing-cpp и Chromium):
`XUI_EXPORT_BINARY=/absolute/path/to/official/x-ui python3 -m pytest tests/integration/test_public_links.py -q`.
Без переменной интеграционная проверка явно SKIPPED/NOT RUN.

Официальные источники контракта v3.11.0: internal/web/controller/host.go,
internal/web/entity/entity.go (HostGroup), internal/sub/host_sub.go,
internal/web/controller/setting.go, internal/web/service/setting.go,
frontend/src/pages/clients/ClientQrModal.tsx и pages/inbounds/qr/QrPanel.tsx
в https://github.com/MHSanaei/3x-ui/tree/v3.11.0 .
