#!/usr/bin/env python3
import ipaddress,json,subprocess,sys
try:
    desired=ipaddress.ip_network(sys.argv[1]);ids=subprocess.check_output(['docker','network','ls','-q'],text=True).split()
    rows=json.loads(subprocess.check_output(['docker','network','inspect',*ids],text=True)) if ids else []
    managed=any(r['Name']=='vps-installer-proxy' for r in rows)
    for row in rows:
        for cfg in row.get('IPAM',{}).get('Config',[]) or []:
            if cfg.get('Subnet'):
                subnet=ipaddress.ip_network(cfg['Subnet'])
                if subnet.version!=desired.version:continue
                if row['Name']=='vps-installer-proxy':assert subnet==desired,'Managed network changed'
                else:assert not subnet.overlaps(desired),'Overlaps Docker network '+row['Name']
    # Also avoid collision with host LAN/VPN routes (default route is not a collision).
    routes=json.loads(subprocess.check_output(['ip','-j','-4','route','show'],text=True))
    for route in routes:
        if route.get('dst','default')=='default':continue
        if managed and ipaddress.ip_network(route['dst'])==desired and route.get('dev','').startswith('br-'):continue
        assert not ipaddress.ip_network(route['dst']).overlaps(desired),'Overlaps host route '+route['dst']
except (ValueError,AssertionError,subprocess.CalledProcessError) as e:
    print('Network check failed: '+str(e),file=sys.stderr);sys.exit(1)
