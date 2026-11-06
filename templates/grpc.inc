# Managed VLESS/gRPC; panel 2053 is deliberately not proxied.
location = /vlessgrpc/Tun {
    grpc_pass grpc://xui:10000;
    grpc_set_header Host $host;
    grpc_connect_timeout 5s;
    grpc_read_timeout 300s;
    grpc_send_timeout 300s;
    client_max_body_size 0;
}
location = /vlessgrpc/TunMulti {
    grpc_pass grpc://xui:10000;
    grpc_set_header Host $host;
    grpc_connect_timeout 5s;
    grpc_read_timeout 300s;
    grpc_send_timeout 300s;
    client_max_body_size 0;
}
