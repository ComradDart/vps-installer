#!/usr/bin/env python3
"""Report TCP per resolved address; ICMP and HTTPS don't prove VLESS or double-hop."""
import ipaddress,json,re,socket,sys,time
try:
    host,port=sys.argv[1:];assert re.fullmatch(r'[A-Za-z0-9_.:\[\]-]{1,253}',host)
    assert port.isdigit() and 1<=int(port)<=65535
    addresses=socket.getaddrinfo(host.strip('[]'),int(port),type=socket.SOCK_STREAM)
    seen=set();ok=False
    for family,kind,proto,canon,addr in addresses:
        if addr in seen:continue
        seen.add(addr);start=time.monotonic()
        with socket.socket(family,kind,proto) as s:
            s.settimeout(5)
            try:s.connect(addr);status='connected';ok=True
            except OSError as e:status=type(e).__name__
        print(json.dumps(dict(address=addr[0],port=int(port),tcp=status,seconds=round(time.monotonic()-start,3))))
    print('TCP probe only; protocol authentication/data transfer must be tested separately.')
    sys.exit(0 if ok else 1)
except (ValueError,AssertionError,OSError) as e:
    print('Probe failed: '+str(e),file=sys.stderr);sys.exit(1)
