# Состояние проверки

Обновлено 7 ноября 2026 года (Москва). Старые промежуточные отчёты доступны в Git history.

## Работающие VPS

Владелец подтвердил, что **оба VPS работают**: INBOUND/REALITY и OUTBOUND.
Это результат пользовательского развёртывания; прямого административного доступа
к этим VPS у среды разработки не было.

## Выполненные автоматические проверки

| Проверка | Результат |
|---|---|
| Unit/negative, Bash syntax, ShellCheck после SSH tunnel users | 175 тестов прошли |
| Реальный OpenSSH: разрешённый туннель, запрет exec/shell/SFTP/SCP/другого target/reverse | Пройдено в одноразовом Alpine-контейнере с отдельными Linux UID |
| Замена ключа, отзыв активного туннеля, сохранение primary admin SSH | Пройдено на настоящем sshd |
| Откат ошибочного SSH-конфига и перекрывающего Match | Пройдено; расписание systemd timer отдельно не проверено |
| Публичные ссылки INBOUND: точечный прогон | 10 тестов прошли за 12.40 секунд |
| Настоящие 3x-ui API links и raw/base64 subscription | Address/443, SNI, REALITY pbk/sid/flow совпали с конфигурацией |
| QR из штатного React UI 3x-ui | Декодирован ZXing; совпал с API-ссылкой при входе через localhost и 127.0.0.1 |
| Независимость API links от Host | Совпали для localhost, loopback, Docker-IP и внешнего hostname |
| Повтор ремонта экспорта | Один Host group; UUID/subId/ключи/Short IDs/клиенты сохранены |

Экспорт проверялся официальным release-бинарником 3x-ui **3.11.0** с отдельной
временной БД. UI и API настоящие; прямых SQL-правок нет. Xray в этом прогоне не
запускался. Nginx validation/reload в export fixture заменены заглушкой.
Это проверка экспорта и QR, а не передачи VPN-трафика через публичный origin.

Ранние контейнерные проверки подтверждали отдельные startup/login/TLS/gRPC/REALITY
сценарии. Полный последующий migration/relay E2E в песочнице прерывался из-за ENOSPC
в Docker VFS; эти прогоны не считаются успешными. Подробная история сохранена в Git.

## Не проверено средой разработки

- Полный lifecycle Debian/Ubuntu VPS с PAM, UFW и systemd rollback timers.
- Внешний Cloudflare E2E с настоящей зоной и сертификатом.
- Новая публичная подписка через nginx и REALITY self-steal в одном E2E-прогоне.
- Каждая будущая версия образов latest.

## Воспроизведение

- `bash tests/run.sh` — unit, Bash syntax, ShellCheck.
- `bash scripts/test_panel_ssh.sh` — настоящий sshd в одноразовом Alpine-контейнере.
- `RUN_DOCKER_INTEGRATION=1 bash tests/run.sh` — контейнерные сценарии; нужен Docker и свободный диск.
- `XUI_EXPORT_BINARY=/absolute/path/to/official/x-ui python3 -m pytest tests/integration/test_public_links.py -q`
  — экспорт и QR. Нужны Chromium, playwright, Pillow, zxing-cpp; бинарник 3.11.0.

Без необходимых opt-in переменных интеграционные проверки явно SKIPPED/NOT RUN.
Ручной порядок: [MANUAL-TEST.md](MANUAL-TEST.md).

При уборке репозитория проверены ShellCheck и 17 bootstrap-тестов (0.57 секунды),
включая корневой каталог архива из GitHub API для приватного репозитория.
VPN/SSH E2E повторно не запускались; работающие VPS не изменялись.
