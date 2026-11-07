#!/usr/bin/env python3
"""Host socket inventory; a port whitelist alone cannot prove remote reachability."""
import ipaddress
import re
import subprocess
import sys


def networkd_dhcp_client(parts, line):
    """Recognize an interface-bound DHCPv4 client, not every UDP/68 socket."""
    if parts[0] != 'udp':
        return False
    host, separator, port = parts[4].rpartition(':')
    if not separator or port != '68' or '%' not in host:
        return False
    address, interface = host.rsplit('%', 1)
    if not interface:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.version != 4 or ip.is_unspecified or ip.is_multicast or ip.is_loopback:
        return False
    # ss comm can truncate systemd-networkd to 15 characters, as on Ubuntu.
    owners = re.findall(r'\("([^"\n]+)",pid=\d+,fd=\d+\)', line)
    return bool(owners) and all(
        owner in ('systemd-network', 'systemd-networkd') for owner in owners
    )


def unexpected_listeners(text, ssh_port, telemt=False):
    allowed = {int(ssh_port), 80, 443}
    if telemt:allowed.add(9443)
    extra = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        host, _, port = parts[4].rpartition(':')
        address = host.strip('[]').split('%', 1)[0]
        if address == '::1' or address.startswith('127.'):
            continue
        if networkd_dhcp_client(parts, line):
            continue
        if port.isdigit() and (parts[0] == 'udp' or int(port) not in allowed):
            extra.append(line)
    return extra


def main():
    text = subprocess.check_output(['ss', '-H', '-lntup'], text=True)
    extra = unexpected_listeners(text, sys.argv[1], '--telemt' in sys.argv[2:])
    if extra:
        print('Unexpected non-loopback host listeners; review UFW and cloud firewall:', file=sys.stderr)
        print('\n'.join(extra), file=sys.stderr)
        return 1
    print('Host listener inventory: OK (interface-bound networkd DHCP client recognized; '
          'also inspect Docker publications and scan externally)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
