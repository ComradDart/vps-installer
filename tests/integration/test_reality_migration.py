"""Official panel/Xray binaries; real migration, client, self-steal and rollback."""
import json,os,shutil,time
import pytest
from test_docker import live,credentials,wait,docker
from state import write
from xui_api import Docker,authenticated_api,private_json,SetupError
from automation import Engine
from managed_inbound import decoded

pytestmark=pytest.mark.skipif(os.environ.get('RUN_DOCKER_INTEGRATION')!='1',reason='Explicit opt-in required')

@pytest.fixture
def small_stack():
    generator=live.__wrapped__();c=next(generator)
    try:
        root=c['root'];base=c['base'];init=c['ident']+'-extract'
        docker('create','--name',init,'--network','none','--entrypoint','/bin/true',c['versions']['xui_image'])
        try:
            docker('cp',init+':/app/x-ui',base/'x-ui')
            docker('cp','-L',init+':/lib/ld-musl-x86_64.so.1',base/'musl.so')
            docker('cp',init+':/app/internal',base/'internal')
        finally:docker('rm','-v',init)
        # Only test fixtures use a smaller filesystem, with unchanged official binaries.
        for item in (base/'bin').iterdir():
            if item.name not in ('xray-linux-amd64','geoip.dat','geosite.dat','config.json'):
                if item.is_dir():shutil.rmtree(item)
                else:item.unlink()
        c['config']['role']='inbound';write(c['state'],c['config'])
        config=json.loads(c['compose_path'].read_text());service=config['services']['xui']
        runtime=os.environ.get('VPS_TEST_RUNTIME',c['versions']['nginx_image'])
        service['image']=runtime;service['working_dir']='/app'
        config['services']['nginx']['image']=runtime
        service['volumes'] += [dict(type='bind',source=str(source),target=target,read_only=True) for source,target in (
            (base/'x-ui','/app/x-ui'),(base/'musl.so','/lib/ld-musl-x86_64.so.1'),
            (base/'musl.so','/lib/libc.musl-x86_64.so.1'),(base/'internal','/app/internal'),(c['ca'],'/test-ca.pem'))]
        service['healthcheck']['test']=['CMD','curl','-fsS','-o','/dev/null','http://127.0.0.1:2053/']
        c['compose_path'].write_text(json.dumps(config))
        # Keep production bootstrap on the official full image.
        credentials(c,'initial');c['dc']('up','-d');wait(c)
        adapter=Docker(c['xui'],c['nginx'],c['net']);original=adapter.run
        def run(*args,**kwargs):
            args=list(args)
            if args and args[0]=='run' and '--entrypoint' in args and args[args.index('--entrypoint')+1].startswith('/app/bin/xray-'):
                args[1:1]=['-v',str(base/'bin')+':/app/bin:ro']
            return original(*args,**kwargs)
        adapter.run=run
        api,version=authenticated_api(root,adapter,'http://127.0.0.1:'+str(c['ports']['panel']))
        # Test-only IP fixture on the existing nginx, without another VFS container.
        http=root/'conf.d/http.conf';text=http.read_text()
        text=text.rsplit('}',1)[0]+' location = /fixture-ip { default_type application/json; return 200 \'{"ip":"192.0.2.10"}\'; }\n}\n'
        http.write_text(text);docker('exec',c['nginx'],'nginx','-s','reload')
        subnet=json.loads(docker('network','inspect',c['net']))[0]['IPAM']['Config'][0]['Subnet']
        template=api.template()
        template['routing']['rules'].insert(0,dict(type='field',domain=['full:nginx'],outboundTag='direct'))
        freedom=next(o for o in template['outbounds'] if o['protocol']=='freedom')
        freedom.setdefault('settings',{}).setdefault('finalRules',[]).insert(0,dict(ip=[subnet],action='allow'))
        api.set_template(template);api.restart();time.sleep(1)
        private_json(root/'transport.json',dict(schema=1,mode='direct-grpc',topology='standalone',active=False))
        c.update(adapter=adapter,api=api,version=version)
        yield c
    finally:
        try:next(generator)
        except StopIteration:pass


def engine(c):
    return Engine(c['root'],c['api'],c['adapter'],c['version'],compose_path=c['compose_path'],project=c['ident'],public_port=c['ports']['tls'],bind='127.0.0.1',test_url='http://nginx/fixture-ip',ca_file=c['ca'])


def test_real_migration_rollback_and_self_steal(small_stack):
    c=small_stack;root=c['root'];api=c['api']
    engine(c).provision(public=False)
    before=api.inbounds()[0];identity=decoded(before,'settings')['clients'][0]['id']
    template=api.template()
    template['routing']['rules'].insert(0,dict(type='field',inboundTag=[before['tag']],outboundTag='direct'))
    api.set_template(template);api.restart()
    original_template=api.template()
    before_compose=c['compose_path'].read_bytes();before_cache=(root/'secrets/managed-xray.json').read_bytes()
    e=engine(c)
    def reject_binding():raise SetupError('Injected post-handoff failure')
    e.actual_bindings=reject_binding
    with pytest.raises(SetupError,match='Injected post-handoff'):e.provision(public=False,migrate=True)
    restored=api.inbounds()[0]
    assert restored['id']==before['id'] and restored['port']==10000
    assert api.template()==original_template
    assert decoded(restored,'settings')['clients'][0]['id']==identity
    assert decoded(restored,'settings')['clients'][0].get('flow','')==''
    assert (root/'secrets/managed-xray.json').read_bytes()==before_cache
    assert c['compose_path'].read_bytes()==before_compose
    engine(c).verify_internal(json.loads(before_cache))
    engine(c).provision(public=False,migrate=True)
    row=api.inbounds()[0];client=decoded(row,'settings')['clients'][0]
    assert row['id']==before['id'] and row['tag']==before['tag'] and row['port']==443
    assert client['id']==identity and client['flow']=='xtls-rprx-vision'
    assert api.template()==original_template
    result=c['adapter'].run('exec',c['xui'],'curl','--noproxy','*','--fail','--silent','--show-error','--max-time','10','--cacert','/test-ca.pem','--connect-to','example.test:443:xui:443','https://example.test/')
    assert 'Integration test site' in result
    snapshot=(root/'secrets/managed-xray.json').read_bytes()
    engine(c).provision(public=False,migrate=True)
    assert (root/'secrets/managed-xray.json').read_bytes()==snapshot
    assert len(api.inbounds())==1
    engine(c).actual_bindings()
    c['checkpoints'].append(dict(status='PASSED',check='Real gRPC -> REALITY migration; same id/tag/UUID; post-handoff rollback; real VLESS client and HTTPS self-steal; repeat without key rotation'))
