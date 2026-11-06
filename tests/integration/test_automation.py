"""Actual API + authenticated VLESS transfer. Cloudflare E2E is NOT RUN here."""
import json,time,os
import pytest
from test_docker import live,credentials,wait,docker
from xui_api import Docker,authenticated_api,private_json,SetupError
from automation import Engine
from managed_inbound import decoded

pytestmark=pytest.mark.skipif(os.environ.get("RUN_DOCKER_INTEGRATION")!="1",reason="Explicit opt-in required")

@pytest.fixture
def transport_stack():
    generator=live.__wrapped__();c=next(generator)
    try:
        config=json.loads(c['compose_path'].read_text())
        config['services']['xui']['volumes'].append(dict(type='bind',source=str(c['ca']),target='/test-ca.pem',read_only=True))
        c['compose_path'].write_text(json.dumps(config))
        credentials(c,'initial');c['dc']('up','-d');wait(c)
        adapter=Docker(c['xui'],c['nginx'],c['net'])
        api,version=authenticated_api(c['root'],adapter,'http://127.0.0.1:'+str(c['ports']['panel']))
        # Controlled private destination; test-only exception to the panel's private-IP guard.
        targetconf=c['base']/'target.conf'
        targetconf.write_text('server { listen 8080; location /ip { default_type application/json; return 200 \'{"ip":"192.0.2.10"}\'; } }')
        docker('run','-d','--name',c['ident']+'-target','--network',c['net'],'--network-alias','target','-v',str(targetconf)+':/etc/nginx/conf.d/default.conf:ro','nginx:latest')
        target=json.loads(docker('inspect',c['ident']+'-target'))[0]
        ip=target['NetworkSettings']['Networks'][c['net']]['IPAddress']
        template=api.template()
        template['routing']['rules'].insert(0,{'type':'field','domain':['full:target'],'outboundTag':'direct'})
        freedom=next(o for o in template['outbounds'] if o['protocol']=='freedom')
        freedom.setdefault('settings',{}).setdefault('finalRules',[]).insert(0,{'ip':[ip+'/32'],'action':'allow'})
        api.set_template(template);api.restart();time.sleep(2)
        # VFS copies whole image layers on every run. Keep the production probe flow,
        # using the same official Xray binary in the smaller latest nginx filesystem.
        original_run=adapter.run
        def limited_disk_run(*args,**kwargs):
            args=list(args)
            if args and args[0]=='run' and '--entrypoint' in args and args[args.index('--entrypoint')+1].startswith('/app/bin/xray-'):
                index=args.index(c['versions']['xui_image'])
                args[index]=c['versions']['nginx_image']
                args[1:1]=['-v',str(c['base']/'bin')+':/app/bin:ro']
            return original_run(*args,**kwargs)
        adapter.run=limited_disk_run
        c.update(adapter=adapter,api=api,version=version)
        yield c
    finally:
        try:next(generator)
        except StopIteration:pass

def engine(c,mode):
    if not (c['root']/'transport.json').exists():private_json(c['root']/'transport.json',dict(schema=1,mode=mode,topology='standalone',active=False))
    return Engine(c['root'],c['api'],c['adapter'],c['version'],compose_path=c['compose_path'],project=c['ident'],public_port=c['ports']['tls'],bind='127.0.0.1',test_url='http://target:8080/ip',ca_file=c['ca'])

@pytest.mark.parametrize('mode',['direct-grpc','direct-reality'])
def test_real_api_client_and_idempotency(transport_stack,mode):
    c=transport_stack;e=engine(c,mode)
    result=e.provision(public=False)
    assert result['origin_client']=='PASSED'
    first=json.loads((c['root']/'secrets/managed-xray.json').read_text())
    rows=c['api'].inbounds();assert len(rows)==1
    row=rows[0];assert row['enable'] and row['protocol']=='vless'
    if mode=='direct-grpc':
        assert row['port']==10000
        assert decoded(row,'streamSettings')['grpcSettings']['serviceName']=='vlessgrpc'
        assert 'grpc_pass grpc://xui:10000;' in (c['root']/'conf.d/vps-grpc.inc').read_text()
    else:
        assert row['port']==443
        assert decoded(row,'settings')['clients'][0]['flow']=='xtls-rprx-vision'
    again=engine(c,mode).provision(public=False)
    assert not again['created']
    assert first==json.loads((c['root']/'secrets/managed-xray.json').read_text())
    assert [r['id'] for r in c['api'].inbounds()]==[row['id']]
    e.actual_bindings()
    assert json.loads((c['root']/'automation-report.json').read_text())['cloudflare_e2e']=='NOT RUN'
    assert c['password'] not in docker('logs',c['xui'])
    token=(c['root']/'secrets/xui-api.token').read_text().strip()
    assert token not in docker('logs',c['xui'])
    c['checkpoints'].append(dict(check=mode+' authenticated client transfer, stable UUID/id, exclusive port owner, no public 10000',status='PASSED'))

def test_failed_transfer_rolls_back(transport_stack):
    c=transport_stack;e=engine(c,'direct-grpc');before=c['compose_path'].read_bytes()
    e.test_url='http://target:8080/nonexistent'
    with pytest.raises(SetupError):e.provision(public=False)
    assert c['api'].inbounds()==[]
    assert c['compose_path'].read_bytes()==before
    assert not json.loads((c['root']/'transport.json').read_text())['active']
    identity=json.loads((c['root']/'secrets/managed-xray.json').read_text())['uuid']
    engine(c,'direct-grpc').provision(public=False)
    assert json.loads((c['root']/'secrets/managed-xray.json').read_text())['uuid']==identity

def test_relay_verified_before_routing_and_no_direct_fallback(transport_stack):
    import uuid
    from transport_profile import parse_peer,client_uri
    from xray_probe import probe
    c=transport_stack;root=c['root'];adapter=c['adapter'];names=[]
    keys=c['api'].request('/panel/api/server/getNewX25519Cert')
    peer=dict(mode='reality',address='exit.example.test',port=2443,server_name='example.test',uuid=str(uuid.uuid4()),public_key=keys['publicKey'],short_id='1234567890abcdef',fingerprint='chrome')
    remote=parse_peer(client_uri(peer,'Independent test OUTBOUND'),'192.0.2.20')
    e=engine(c,'direct-grpc')
    e.profile['topology']='relay';private_json(root/'transport.json',e.profile);private_json(root/'secrets/relay.json',remote)
    # A nonexistent OUTBOUND must cause no local inbound or routing mutation.
    original=c['api'].template()
    with pytest.raises(SetupError):e.provision(public=False)
    assert c['api'].inbounds()==[] and c['api'].template()==original
    try:
        # Reuse the HTTP fixture on a second port to fit the sandbox's VFS disk budget.
        targetconf=c['base']/'target.conf'
        with targetconf.open('a') as f:f.write('\nserver { listen 8081; location / { default_type application/json; return 200 \'{"ip":"192.0.2.20"}\'; } }')
        docker('exec',c['ident']+'-target','nginx','-s','reload')
        server={'log':{'loglevel':'warning'},'inbounds':[{'listen':'0.0.0.0','port':2443,'protocol':'vless','settings':{'clients':[{'id':peer['uuid'],'flow':'xtls-rprx-vision'}],'decryption':'none'},'streamSettings':{'network':'tcp','security':'reality','realitySettings':{'show':False,'target':'nginx:8443','serverNames':['example.test'],'privateKey':keys['privateKey'],'shortIds':[peer['short_id']]}}}], 'outbounds':[{'protocol':'freedom','settings':{'redirect':'target:8081'}}]}
        path=c['base']/'exit.json';private_json(path,server)
        name=c['ident']+'-exit';names.append(name)
        docker('run','-d','--name',name,'--network',c['net'],'--network-alias','exit.example.test','--user',str(os.getuid())+':'+str(os.getgid()),'--log-driver','none','--cap-drop','ALL','-v',str(path)+':/exit.json:ro','-v',str(c['base']/'bin')+':/xray-bin:ro','--entrypoint','/xray-bin/'+adapter.binary().rsplit('/',1)[1],c['versions']['nginx_image'],'run','-config','/exit.json')
        time.sleep(2)
        e.provision(public=False)
        row=c['api'].inbounds()[0]
        assert c['api'].template()['routing']['rules'][0]==dict(type='field',inboundTag=[row['tag']],outboundTag='vps-installer-exit')
        # The destination's direct response is .10; only the independent OUTBOUND returns .20.
        cache=json.loads((root/'secrets/managed-xray.json').read_text());e.verify_internal(cache)
        docker('stop',name)
        with pytest.raises(SetupError):e.verify_internal(cache)
        assert len(c['api'].inbounds())==1
        c['checkpoints'].append(dict(check='Provided OUTBOUND preverified; real relay exits through peer; peer shutdown fails closed',status='PASSED'))
    finally:
        for name in reversed(names):docker('rm','-f',name)

@pytest.mark.skip(reason='NOT RUN: no external Cloudflare zone/origin or real public certificate configured in this environment')
def test_external_cloudflare_e2e():
    """The origin tests above must never be reported as Cloudflare E2E."""
