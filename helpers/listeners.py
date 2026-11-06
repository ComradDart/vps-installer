#!/usr/bin/env python3
"""Host socket inventory; a port whitelist alone cannot prove remote reachability."""
import re, subprocess, sys
allowed={int(sys.argv[1]),80,443}
text=subprocess.check_output(['ss','-H','-lntup'],text=True)
extra=[]
for line in text.splitlines():
    parts=line.split()
    if len(parts)<5:continue
    local=parts[4];host,sep,port=local.rpartition(':');host=host.strip('[]')
    if host in ('127.0.0.1','::1') or host.startswith('127.'):continue
    if port.isdigit() and (parts[0]=='udp' or int(port) not in allowed):extra.append(line)
if extra:
    print('Unexpected non-loopback host listeners; review UFW and cloud firewall:',file=sys.stderr)
    print('\n'.join(extra),file=sys.stderr);sys.exit(1)
print('Host listener inventory: OK (also inspect Docker publications and scan externally)')
