#!/usr/bin/env python3
import os,re,subprocess,sys
allowed={p+'/tcp' for p in (sys.argv[1],'80','443')}
if '--telemt' in sys.argv[2:]:allowed.add('9443/tcp')
text=subprocess.check_output(['ufw','status'],text=True,env={**os.environ,'LC_ALL':'C'})
assert 'Status: active' in text,'UFW not active'
extra=[]
for line in text.splitlines():
    if not re.search(r'\b(ALLOW|LIMIT)\b',line):continue
    destination=re.split(r'\s{2,}',line.strip())[0].replace(' (v6)','')
    if destination not in allowed:extra.append(line)
if extra:
    print('Extra UFW openings preserved; review before continuing:',file=sys.stderr)
    print('\n'.join(extra),file=sys.stderr);sys.exit(1)
print('UFW allow/limit rules match SSH/HTTP/HTTPS TCP whitelist')
