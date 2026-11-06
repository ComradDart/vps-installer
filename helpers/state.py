#!/usr/bin/env python3
"""Non-executable, validated JSON state. No eval/source or password fields."""
import ipaddress, json, os, re, sys, tempfile
from pathlib import Path
FIELDS = {'schema','role','domain','admin','ssh_port','public_ip','email','subnet',
          'xui_image','nginx_image','title','text','phase'}
def domain(s):
    return bool(len(s)<=253 and '.' in s and not re.fullmatch(r'[0-9.]+',s) and
                all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in s.split('.')))
def validate(d):
    assert set(d)==FIELDS, 'Unknown or missing state fields'
    assert d['schema']=='1'
    assert d['role'] in ('inbound','outbound')
    assert domain(d['domain'])
    assert re.fullmatch(r'[a-z][a-z0-9_-]{0,30}',d['admin']) and d['admin']!='root'
    assert re.fullmatch(r'[1-9][0-9]{0,4}',d['ssh_port']) and int(d['ssh_port'])<=65535
    assert int(d['ssh_port']) not in (80,443,2053,8443)
    assert isinstance(ipaddress.ip_address(d['public_ip']),ipaddress.IPv4Address)
    assert re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',d['email'])
    n=ipaddress.ip_network(d['subnet']);assert n.version==4 and n.prefixlen==24 and any(n.subnet_of(ipaddress.ip_network(r)) for r in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
    assert d['xui_image']=='ghcr.io/mhsanaei/3x-ui:latest'
    assert d['nginx_image']=='nginx:latest'
    for k in ('title','text'): assert 1<=len(d[k])<=1000 and not any(ord(c)<32 for c in d[k])
    assert d['phase'] in ('configured','ssh-ready','ready')
def write(path,d):
    validate(d);path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix='.state-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(d,f,indent=2,ensure_ascii=False);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
        fd=os.open(path.parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def main():
    op=sys.argv[1]
    if op=='domain': return 0 if domain(sys.argv[2]) else 1
    path=sys.argv[2]
    if op=='create':
        d=json.load(sys.stdin);write(path,d);return 0
    d=json.loads(Path(path).read_text());validate(d)
    if op=='get': print(d[sys.argv[3]])
    elif op=='set': d[sys.argv[3]]=sys.argv[4];write(path,d)
    elif op!='validate': raise ValueError('Invalid operation')
    return 0
if __name__=='__main__':
    try: sys.exit(main())
    except (ValueError,AssertionError,KeyError,OSError,json.JSONDecodeError) as e:
        print('State/validation error: '+str(e),file=sys.stderr);sys.exit(1)
