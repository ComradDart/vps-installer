import pytest
from listeners import unexpected_listeners


def socket(protocol, local, owner='systemd-network'):
    return f'{protocol} UNCONN 0 0 {local} 0.0.0.0:* users:(("{owner}",pid=10700,fd=22))'


@pytest.mark.parametrize('owner', ['systemd-network', 'systemd-networkd'])
def test_interface_bound_networkd_dhcp_is_not_an_unexpected_server(owner):
    assert unexpected_listeners(socket('udp', '192.0.2.10%enp3s0:68', owner), 22) == []


@pytest.mark.parametrize('protocol,local,owner', [
    ('udp', '0.0.0.0:68', 'systemd-network'),
    ('udp', '192.0.2.10:68', 'systemd-network'),
    ('udp', '192.0.2.10%enp3s0:68', 'unknown-server'),
    ('tcp', '192.0.2.10%enp3s0:68', 'systemd-network'),
    ('udp', '192.0.2.10%enp3s0:80', 'systemd-network'),
    ('udp', '192.0.2.10%enp3s0:443', 'systemd-network'),
    ('tcp', '0.0.0.0:2053', 'x-ui'),
    ('tcp', '0.0.0.0:10000', 'xray'),
    ('udp', '192.0.2.10%:68', 'systemd-network'),
])
def test_exception_does_not_allow_other_public_services(protocol, local, owner):
    line = socket(protocol, local, owner)
    assert unexpected_listeners(line, 22) == [line]


def test_dhcp_does_not_hide_an_additional_udp_listener():
    dhcp = socket('udp', '192.0.2.10%enp3s0:68')
    quic = socket('udp', '0.0.0.0:443', 'nginx')
    ssh = socket('tcp', '0.0.0.0:2222', 'sshd')
    panel = socket('tcp', '127.0.0.1:2053', 'x-ui')
    assert unexpected_listeners('\n'.join([dhcp, quic, ssh, panel]), 2222) == [quic]


def test_unowned_dhcp_socket_is_still_reported():
    line = 'udp UNCONN 0 0 192.0.2.10%enp3s0:68 0.0.0.0:*'
    assert unexpected_listeners(line, 22) == [line]
