#!/usr/bin/env python3
import json, subprocess, sys

def check(rows,reality=False,telemt=False):
    expected={'vps-xui':{'2053/tcp':{('127.0.0.1','2053')}},
              'vps-nginx':{'80/tcp':{('0.0.0.0','80')},'8443/tcp':{('127.0.0.1','8443')}}}
    if reality:expected['vps-xui']['443/tcp']={('0.0.0.0','443')}
    else:expected['vps-nginx']['8443/tcp'].add(('0.0.0.0','443'))
    if telemt:expected['vps-xui']['1080/tcp']={('127.0.0.1','1080')}
    assert len(rows)==2
    for row in rows:
        name=row['Name'].lstrip('/')
        assert name in expected and row['State']['Running'], 'Unexpected or stopped container'
        actual={k:{(b['HostIp'],b['HostPort']) for b in v} for k,v in (row['HostConfig'].get('PortBindings') or {}).items() if v}
        assert actual==expected[name], 'Unexpected Docker PortBindings for '+name
        networks=row['NetworkSettings']['Networks']
        assert set(networks)=={'vps-installer-proxy'}, 'Unexpected Docker networks'
        assert not row['HostConfig'].get('Privileged') and not row['HostConfig'].get('CapAdd'), 'Unexpected privileges'
        assert row['HostConfig']['NetworkMode']!='host', 'Host networking forbidden'
        assert 'ALL' in row['HostConfig']['CapDrop'], 'Capabilities not dropped'
        assert row['State'].get('Health',{}).get('Status')=='healthy', 'Container is not healthy'
if __name__=='__main__':
    try:
        rows=json.loads(subprocess.check_output(['docker','inspect','vps-xui','vps-nginx'],text=True));check(rows,len(sys.argv)>1 and sys.argv[1]=='direct-reality','--telemt' in sys.argv[2:])
        print('Docker publications/networks/health/privileges: OK')
    except (AssertionError,subprocess.CalledProcessError,KeyError) as e:
        print('Docker exposure check failed: '+str(e),file=sys.stderr);sys.exit(1)
