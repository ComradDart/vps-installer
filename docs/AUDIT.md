# Аудит исходного vps_setup.sh

Первичный аудит относился к VPS + Docker nginx/site/3x-ui. Последующее обязательное
требование добавило автоматическую настройку VLESS через API; она описана в
ARCHITECTURE.md и TEST-REPORT.md. Все развёртываемые контейнеры остаются latest.

Проверен весь оригинал, присланный в сообщении после ТЗ: общая часть, OUTBOUND,
INBOUND, reset/uninstall, ACME, HTML/CSS/JS, counter и refresh-tg-ranges.
Оригинал не включён в поставку, чтобы не путать старую и новую точку запуска.

## Что сохранено

Интерактивный выбор роли; отдельный sudo-пользователь; поддержка уже имеющегося ключа
и согласованного копирования plain root keys; checkpoint SSH; persistent Docker БД;
HTTP-only nginx до выпуска сертификата; проверка точного webroot; локальные ресурсы
сайта и неоновая стилистика; сохранение ответов между запусками.

## Проблемы и изменения

| Исходный участок | Риск / дефект | Реализация |
|---|---|---|
| `docker ... x-ui setting` / `--entrypoint x-ui` | Путь ищется через PATH; в официальном образе `/usr/bin/x-ui` — shell wrapper, бинарник `/app/x-ui` | Используется абсолютный бинарный путь |
| `setting` + `setting -show` | Наличие non-default account не доказывает правильность выбранной пары; CLI может вернуть 0 после сообщения об ошибке | Проверяется фактический bcrypt первого пользователя, затем реальный login в интеграционном тесте |
| CLI `-password` в Docker argv | Секрет в Docker command metadata, shell history при ручном повторении, process list | Вход helper через stdin; пароль не попадает в Docker argv/env, log driver none; остаточная видимость в argv самого upstream бинарника честно описана |
| `.panel_admin.env`, console output, log recovery | Открытый пароль на диске и в журналируемом stdout; парсинг логов ненадёжен | Нет сохранения пароля; одноразовый вывод generated password только в tty; нет log fallback |
| Повторное применение credentials | Может показываться неработающая пара, нет доказательства сохранности клиентов при reset | Reset отдельно: backup, остановка xui, hash verify, сравнение остальных таблиц, rollback |
| Cookie secret link на публичном nginx | Панель остаётся публичным приложением; bearer URL/cookie становится дополнительным секретом | Публичный маршрут к панели удалён, только host 127.0.0.1 + SSH |
| `latest` при каждом запуске | Изменение поведения upstream без фиксации версии | **По последующему уточнению заказчика latest сохранён для всех контейнеров**; backup перед обновлением, текущий образ испытывается фактически |
| Docker convenience script `curl | sh` | Выполнение динамического внешнего скрипта | Официальный apt repo с проверкой fingerprint signing key |
| `usermod -aG docker` | Обычный пользователь сразу получает эквивалент root | В группу Docker не добавляется |
| NET_ADMIN/NET_RAW и встроенный fail2ban | Лишние полномочия для обычного VLESS; защита host SSH этим не обеспечивается | cap_drop ALL; host fail2ban только SSH |
| UFW vs Docker | Публикации Docker могут обходить обычный INPUT UFW | Только необходимые IPv4 PortBindings, закрытая панель, DOCKER-USER guard по собственной subnet; проверка реальных bindings/listeners |
| SSH Port и ранний reload | Старый порт может закрыться до проверки нового; `sshd -t` не доказывает effective values | Сохранение старых портов на staging, UFW до reload, sshd -T для admin и root, две отдельные проверки key login |
| SSH ошибки / Match / socket activation | Нет таймера отката; конфигурация может остаться неправильной на диске | Rollback drop-in, transient systemd timer; обработка ssh.socket; неуспешные effective settings приводят к остановке |
| PasswordAuthentication no без KbdInteractiveAuthentication no | Через PAM может остаться keyboard-interactive auth | Оба метода запрещаются после proof key login; PAM не отключается |
| `apt-get upgrade -y` и бессрочные kernel blacklist | Неуправляемое обновление всего ОС плюс накопление непатченных ядер | Только unattended security origins; без kernel hold и автоматического reboot |
| ip_forward/unprivileged ports/rp_filter/src_valid_mark | Хостовые параметры AWG применяются независимо от роли | Только обоснованный baseline; forwarding мостов управляет Docker; low-port sysctl ограничен netns контейнера |
| Установка Ubuntu focal PPA на Debian, `apt-key`, незакреплённый MTProxyL bootstrap | Несовместимые пакеты и удалённое исполнение | Весь AWG/MTProxyL/telemt install/routing код исключён |
| Автоостановка старого telemt | Изменяет существующий сервис без отдельного подтверждения | Конфликт порта останавливает установку, не сервис |
| `uninstall` широкими `rm -rf`, чужие контейнеры и UFW правила | Удаление данных и разделяемых ресурсов без строгого ownership boundary | Удаление только compose stack/units после backup + YES, все данные и host security остаются |
| HTML перезаписывается при каждом запуске | Теряется пользовательский сайт | Существующий сайт сохраняется; замена только через явный --reconfigure |
| Счётчик root Python / host networking | Лишний сервис и root процесс, порт 8099 | Счётчик исключён; полноценный статический сайт без дополнительных listeners |
| TLS renewal | Нет надёжной полной связки certbot renewal → nginx config test → reload | Отдельный timer, scoped certbot directories, проверка сертификата и ключа, nginx -t перед reload |
| `source` shell state | Формат выполняет код при чтении, особенно опасен при небезопасных родительских каталогах/symlinks | Root-only JSON со строгой схемой; source применяется только к модулям программы |

`|| true` в исходнике неоднократно превращает неуспешную операцию в видимый успех.
В новом установщике ошибки существенных операций завершают работу; rollback/диагностика
используют явные исключения. Strict mode сам по себе не заменяет проверку поведения
функций, вызванных в if/!; этот случай учитывается для reset и восстановления.

Это аудит текста и поведения доступного upstream образа, не воспроизведение всех
ошибок исходника на рабочей VPS. Полная миграция существующих AWG-серверов не выполнялась.
