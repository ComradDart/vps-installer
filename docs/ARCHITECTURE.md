# Архитектура

Все образы остаются `latest`. Общая настройка VPS одинакова; транспорт применяется
после готовности панели и HTTPS. Пароль создаётся через официальный CLI и проверяется
реальным login. Для дальнейшего API используется root-only Bearer token, без сброса пароля.

```text
cloudflare-grpc / direct-grpc:
  client -> [Cloudflare, если выбран] -> host TCP443 -> nginx:8443 TLS + HTTP/2
    /                  -> static site
    /vlessgrpc/Tun     -> grpc://xui:10000 -> VLESS -> Internet или заданный OUTBOUND

direct-reality (отдельный режим, без Cloudflare Proxy):
  client -> host TCP443 -> xui:443 REALITY / Vision -> Internet или заданный OUTBOUND
                            target nginx:8443 -> HTTPS static site

host TCP80           -> nginx:80 ACME + redirect
host 127.0.0.1:2053   -> xui:2053, панель только через SSH-туннель
host 127.0.0.1:8443   -> nginx:8443, локальная диагностика
```

Никогда не публикуются TCP/10000, UDP/80 и UDP/443. Общий IPv4 Docker bridge
позволяет nginx обращаться к `xui`, Xray — к `nginx`. Host networking и дополнительные
capabilities не используются. nginx — UID101, read-only rootfs, tmpfs; xui — штатный
container root с cap_drop ALL. Low-port sysctl ограничен netns контейнера.

`state.json` содержит общую identity, `transport.json` — выбранные mode/topology/active.
Секреты: `secrets/xui-api.token`, `secrets/managed-xray.json`, optional `secrets/relay.json`;
профили: `clients/`. Все они mode600 под root-only каталогом. Общий state не исполняется.

API-контракт изучен по официальному release 3.11.0 и проверен на работающем `latest`.
Версия будущего образа проверяется до API mutations: неизвестная версия останавливает
автоматизацию. Файл контракта не закрепляет Docker tag или digest.

Перед записью читаются существующие inbound. Владение проверяется по сохранённому
inbound id и UUID служебного клиента. Remark — изменяемое имя: переименование не
ломает проверку и не приводит к созданию дубля. Если id ещё не сохранён, нужен
единственный inbound с известным UUID; перенесённая на другой id identity или
неоднозначность не угадываются. При утрате всего cache первоначальное восстановление
использует исходную программную метку; чужой занятый порт не перезаписывается.
Дополнительные клиенты сохраняются; существующие UUID/REALITY keys не генерируются заново.

Panel shareAddrStrategy/custom и shareAddr задаются отдельно от listen. Для
INBOUND/REALITY штатные Hosts задают публичный Address/443, а REALITY-параметры
наследуются от действующего inbound. subURI/subJsonURI и nginx обеспечивают
публичные подписки. webDomain не меняется; localhost SSH-туннеля в VLESS Address
не используется. PUBLIC_DOMAIN хранится в защищённом state.json INBOUND.
У существующего owned inbound адрес экспорта корректируется с приватным journal;
при ошибке возвращается прежнее значение, пользовательское имя/клиенты не меняются.

Перед применением нормализованный Compose и кандидат nginx проходят реальные проверки.
Приватный `.transport-transaction/journal.json` хранит старые файлы, API template и id.
При ошибке удаляется только созданный этой транзакцией inbound, возвращаются изменённые
файлы и template. Hash guards не дают затереть параллельные изменения администратора:
в таком случае journal сохраняется и требуется review. Pending UUID остаётся для повторения.

REALITY target проверяется из Xray с SNI и TLS, затем настоящим клиентом, до передачи
публичного 443 от nginx к Xray. Проверяется единственный владелец публичного порта.
Оба режима требуют реального VLESS data transfer через отдельный Xray client с одним
proxy outbound и без direct fallback. Проверяется полученный выходной IPv4.

Для relay профиль OUTBOUND должен пройти настоящий клиентский тест до локальных
маршрутных изменений. Первое правило полного inboundTag направляет весь его трафик
в явно заданный VLESS outbound; правила по отдельным доменам/IP не придумываются.

UFW защищает host; DOCKER-USER guard ограничивает forwarded входящий трафик своей subnet
по original destination TCP80/443. Native nftables backend Docker не поддерживается;
iptables-nft frontend с Docker iptables backend допустим. Проверяются реальные
PortBindings и listeners, Engine >=28. Внешний scan и host lifecycle требуют VPS.

## INBOUND и миграция gRPC → REALITY

Новый INBOUND имеет клиентский REALITY/Vision; gRPC выбирается на OUTBOUND либо
используется в переданном OUTBOUND-профиле relay. Public TCP443 у Xray, target
`nginx:8443`; собственный домен INBOUND должен быть DNS-only A на origin.

`--migrate-inbound-reality` обновляет существующий managed inbound через официальный
update API. Сохраняются id, UUID всех клиентов и исходный routing tag. Upstream
при смене порта автоматически меняет auto tag: миграция проходит через зарезервированный
временный custom tag, затем возвращает исходный tag с новым портом. Обе операции
пользуются штатной синхронизацией ссылок в routing, без ручного патчинга БД.

API updateInbound в 3.11.0 сохраняет stored clients и игнорирует переданные изменения
flow. Поэтому Vision выставляется через clients/update с inboundIds-фильтром.
Общие metadata/лимиты читаются свежими из clients/get, чтобы не сбросить их вместе
с flow. Снимок исходного inbound/profile/cache включён в приватный journal до записи.
Rollback возвращает original transport/tag/flow и портовые привязки; пользовательские
изменения квот сохраняются. Смена identity/неожиданного транспорта блокирует rollback
с сохранением journal. Недостающие OUTBOUND-параметры не придумываются.
