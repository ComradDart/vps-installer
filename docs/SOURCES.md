# Проверенные источники

Исследование: 6 ноября 2026 года. Контейнерные теги в итоговом проекте latest по
последующему прямому требованию пользователя; ссылки на конкретный исходный release
здесь фиксируют изученный код, а не закрепляют Docker image.

- Releases: https://github.com/MHSanaei/3x-ui/releases/latest (в дату исследования v3.11.0).
- Main/CLI: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/main.go
- User service / bcrypt / login epoch: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/service/panel/user.go
- Image layout: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/Dockerfile
- Entrypoint: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/DockerEntrypoint.sh
- Current CSRF/login routes: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/controller/index.go
- Inbound API: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/controller/inbound.go
- Cloudflare gRPC: https://developers.cloudflare.com/network/grpc-connections/
- Docker Debian apt: https://docs.docker.com/engine/install/debian/
- Docker Ubuntu apt: https://docs.docker.com/engine/install/ubuntu/
- Docker firewall: https://docs.docker.com/engine/network/packet-filtering-firewalls/
- Docker port publishing/localhost caveat: https://docs.docker.com/engine/network/port-publishing/
- nginx grpc module: https://nginx.org/en/docs/http/ngx_http_grpc_module.html
- Certbot deploy hooks: https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates

Фактически скачаны upstream main.go, Dockerfile, entrypoint, модели, user/index/inbound/API
и страница Cloudflare. Команды CLI и HTTP login дополнительно проверялись на реальном
образе. Нельзя переносить результаты на любую будущую latest без повторного теста.

Автоматизация API (тот же официальный v3.11.0, не pin образа):

- Bearer middleware/routes: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/controller/api.go
- REALITY keys/restart: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/controller/server.go
- Xray template read/update: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/controller/xray_setting.go
- Модель inbound и JSON fields: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/database/model/model.go
- REALITY schema: https://github.com/MHSanaei/3x-ui/blob/v3.11.0/frontend/src/schemas/protocols/security/reality.ts
- Официальные Cloudflare ranges: https://www.cloudflare.com/ips-v4 и https://www.cloudflare.com/ips-v6

Краткий проверяемый контракт хранится в config/api-contracts/3.11.0.json.
POST /panel/api/xray/update передаёт form xraySetting; inbound add — JSON с
settings/streamSettings как JSON strings. Не используются выдуманные API endpoints.

- Client get/list/delete (проверка ownership при rollback): https://github.com/MHSanaei/3x-ui/blob/v3.11.0/internal/web/controller/client.go
