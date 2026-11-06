# Архитектура первоначальной установки

Обе метки роли устанавливают одинаковую инфраструктуру. По последнему уточнению
заказчика транспорта, Xray inbound/clients и double-hop в поставке нет.

```text
Internet TCP 80  -> nginx:80   -> HTTP-01 webroot / HTTPS redirect
Internet TCP 443 -> nginx:8443 -> TLS + HTTP/2 -> static site
Host 127.0.0.1:2053 -> xui:2053 (панель по SSH-туннелю)
Host 127.0.0.1:8443 -> nginx:8443 (локальная проверка TLS)
```

| Порт | Назначение | Доступ |
|---|---|---|
| выбранный SSH/TCP | host sshd | внешний, public-key auth после двух gate |
| 80/TCP | nginx / ACME | внешний IPv4 |
| 443/TCP | nginx / HTTPS-сайт | внешний IPv4 |
| 2053/TCP | 3x-ui | только 127.0.0.1 хоста |
| 8443/TCP | nginx TLS diagnostics | только 127.0.0.1 хоста |
| Xray / subscription / UDP | не публикуются | пользователь настраивает отдельно |

Сеть: отдельный Docker bridge IPv4 /24, без host networking. Она не internal:
приложению может требоваться исходящий Интернет. nginx — UID/GID 101, read-only rootfs,
cap_drop ALL, tmpfs cache/pid; xui — root контейнера без capabilities. Низкие порты
разрешаются sysctl только внутри netns контейнера, не глобально на VPS.

Оба образа latest по требованию пользователя. Обычный install повторно pull-ит их
после backup, остальные команды не обновляют образы.

UFW защищает host; DOCKER-USER guard ограничивает forwarded входящий трафик к своей
subnet по original destination port 80/443. Native nftables backend Docker не поддержан:
если DOCKER-USER отсутствует, установка прекращается. iptables-nft frontend с обычным
Docker iptables backend допустим. Скрипт не flush-ит чужие цепочки и не выключает firewall.

Публикации проверяются через docker inspect, а host listeners через ss. Из-за известных
проблем старых Docker с loopback publication требуется Engine >=28. Проверка извне VPS
остаётся обязательной. Старые UFW rules сохраняются и могут быть отмечены --check.
