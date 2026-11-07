import copy,json,subprocess
import pytest
from conftest import APP,bash
from managed_inbound import check_relay,relay_template
from state import validate,write
from render import render
from telemt import native_config,socks_compose,socks_route,socks_inbound,existing_native
from transport_profile import outbound
from xui_api import SetupError
from listeners import unexpected_listeners

def deployed():
    # Same route structure/tags as the supplied working VPS; no real credentials.
    peer=dict(mode='grpc',address='exit.example.test',server_name='exit.example.test',port=443,uuid='11111111-1111-4111-8111-111111111111',service='vlessgrpc',expected_ip='192.0.2.20')
    api=dict(type='field',inboundTag=['api'],outboundTag='api')
    primary=dict(type='field',inboundTag=['in-443-tcp'],outboundTag='vps-installer-exit')
    template=dict(outbounds=[dict(tag='direct',protocol='freedom',settings={}),dict(tag='blocked',protocol='blackhole',settings={}),outbound(peer,'vps-installer-exit')],routing=dict(domainStrategy='AsIs',rules=[api,primary,dict(type='field',ip=['geoip:private'],outboundTag='blocked'),dict(type='field',protocol=['bittorrent'],outboundTag='blocked'),dict(type='field',ip=['ext:geoip_RU.dat:ru'],outboundTag='direct')]))
    return peer,template

def config_native():
    return dict(general=dict(use_middle_proxy=False,links=dict(public_host='entry.example.test')),server=dict(port=9443,metrics_listen='127.0.0.1:9090',api=dict(enabled=True,listen='127.0.0.1:9091')),censorship=dict(mask=True,tls_domain='entry.example.test',mask_host='127.0.0.1',mask_port=8443,tls_fetch_scope='local-mask'),access=dict(users=dict(example='not-a-real-secret')),upstreams=[dict(type='socks5',address='127.0.0.1:1080',weight=10),dict(type='direct',weight=1,scopes='local-mask')])

def test_existing_pair_route_preserved_and_idempotent():
    peer,current=deployed();before=copy.deepcopy(current)
    planned=socks_route(current,'in-443-tcp','in-1080-tcp',peer)
    assert current==before
    assert planned['outbounds']==current['outbounds']
    assert planned['routing']['rules'][0:2]==current['routing']['rules'][0:2]
    assert planned['routing']['rules'][3:]==current['routing']['rules'][2:]
    assert planned['routing']['rules'][2]['outboundTag']=='vps-installer-exit'
    assert socks_route(planned,'in-443-tcp','in-1080-tcp',peer)==planned
    # Core repeat-run must retain SOCKS rule and existing peer identity as well.
    repeated=relay_template(planned,'in-443-tcp',peer)
    assert repeated['routing']==planned['routing']
    assert next(o for o in repeated['outbounds'] if o['protocol']=='vless')==current['outbounds'][2]
    check_relay(planned,'in-443-tcp',peer)

@pytest.mark.parametrize('change',['ip','tls','uuid','route','precedence','missing'])
def test_relay_mismatch_stops_without_changes(change):
    peer,t=deployed()
    if change=='ip':t['outbounds'][2]['settings']['vnext'][0]['address']='192.0.2.20'
    if change=='tls':t['outbounds'][2]['streamSettings']['tlsSettings']['allowInsecure']=True
    if change=='uuid':t['outbounds'][2]['settings']['vnext'][0]['users'][0]['id']='other'
    if change=='route':t['routing']['rules'][1]['outboundTag']='direct'
    if change=='precedence':t['routing']['rules'].insert(0,dict(type='field',network='tcp',outboundTag='direct'))
    if change=='missing':t['outbounds'].pop()
    before=copy.deepcopy(t)
    with pytest.raises(SetupError):socks_route(t,'in-443-tcp','in-1080-tcp',peer)
    assert t==before

def test_socks_route_cannot_keep_direct_bypass():
    peer,t=deployed()
    t['routing']['rules'].append(dict(type='field',inboundTag=['in-1080-tcp'],outboundTag='direct'))
    with pytest.raises(SetupError,match='Conflicting'):socks_route(t,'in-443-tcp','in-1080-tcp',peer)

def test_compose_only_adds_loopback_socks():
    current=dict(services=dict(xui=dict(image='ghcr.io/mhsanaei/3x-ui:latest',ports=[dict(target=2053,published='2053',host_ip='127.0.0.1',protocol='tcp'),dict(target=443,published='443',host_ip='0.0.0.0',protocol='tcp')]),nginx=dict(ports=[dict(target=80,published='80')],volumes=['kept'])))
    before=copy.deepcopy(current);new=socks_compose(current)
    assert current==before and new['services']['nginx']==current['services']['nginx']
    assert new['services']['xui']['ports'][:-1]==current['services']['xui']['ports']
    assert new['services']['xui']['ports'][-1]==dict(target=1080,published='1080',host_ip='127.0.0.1',protocol='tcp')
    assert socks_compose(new)==new
    for port in (dict(target=9443,published='9443'),dict(target=1080,published='1080',host_ip='0.0.0.0')):
        broken=copy.deepcopy(current);broken['services']['xui']['ports'].append(port)
        with pytest.raises(SetupError):socks_compose(broken)

@pytest.mark.parametrize('role,enabled',[('inbound',False),('outbound',False),('inbound',True)])
def test_optional_render_and_state_compatibility(tmp_path,config,role,enabled):
    config['role']=role
    validate(config) # Old state without optional key remains valid.
    config['telemt']=enabled;path=tmp_path/'state.json';write(path,config)
    render(path,tmp_path/'stack',APP/'templates');first=(tmp_path/'stack/compose.yml').read_bytes()
    assert ('127.0.0.1:1080:1080/tcp' in first.decode())==enabled
    assert '9443' not in first.decode() and '/udp' not in first.decode()
    render(path,tmp_path/'stack',APP/'templates');assert first==(tmp_path/'stack/compose.yml').read_bytes()
    config['role']='outbound';config['telemt']=True
    with pytest.raises(AssertionError):validate(config)

def test_default_no_and_outbound_do_not_install(tmp_path,config):
    config['role']='inbound';state=tmp_path/'state.json';write(state,config)
    module=(APP/'lib/telemt.sh').read_text()
    # Simpler shell doubles exercise the opt-out boundary; they never run installers.
    r=bash('source "$APP/lib/telemt.sh"; ROLE=outbound; ask(){ exit 55; }; telemt_offer; setup_telemt')
    assert r.returncode==0
    r=bash('source "$APP/lib/telemt.sh"; TELEMT=no; python3(){ exit 55; }; setup_telemt')
    assert r.returncode==0
    script='set -Eeuo pipefail\nSTATE=$1; ROLE=inbound; TELEMT=no\n'+module+'''
ask(){ printf -v "$1" no; }
state_set(){ test "$1:$2" = telemt:no; printf 'DECLINED\\n'; }
telemt_offer
setup_telemt
'''
    r=subprocess.run(['bash','-c',script,'test',str(state)],text=True,capture_output=True)
    assert r.returncode==0 and r.stdout.strip()=='DECLINED'

def test_native_adoption_reads_but_never_rotates_secrets(tmp_path,monkeypatch):
    import telemt
    manager=tmp_path/'mtproxyl';(manager/'mtproxy').mkdir(parents=True)
    (manager/'mtproxy/telemt.toml').write_text('''[general]
use_middle_proxy = false
[general.links]
public_host = "entry.example.test"
[server]
port = 9443
metrics_listen = "127.0.0.1:9090"
[server.api]
listen = "127.0.0.1:9091"
[censorship]
mask = true
tls_domain = "entry.example.test"
mask_host = "127.0.0.1"
mask_port = 8443
tls_fetch_scope = "local-mask"
[access.users]
example = "not-a-real-secret"
[[upstreams]]
type = "socks5"
address = "127.0.0.1:1080"
[[upstreams]]
type = "direct"
scopes = "local-mask"
''')
    (manager/'settings.conf').write_text("ENGINE_BACKEND='binary'\nENGINE_SERVICE_NAMING='standard'\n")
    monkeypatch.setattr(telemt,'MANAGER',manager)
    unit=tmp_path/'telemt.service';monkeypatch.setattr(telemt,'UNIT',unit)
    unit.write_text('ExecStart=/opt/mtproxyl/engine/mtproxyl-telemt run /opt/mtproxyl/mtproxy/telemt.toml\n')
    before={p:p.read_bytes() for p in (unit,manager/'mtproxy/telemt.toml',manager/'settings.conf')}
    assert existing_native(dict(domain='entry.example.test')) is True
    assert all(p.read_bytes()==data for p,data in before.items())

@pytest.mark.parametrize('broken',['middle','direct','mask','api','domain','empty'])
def test_unsafe_native_config_is_rejected(broken):
    c=config_native();native_config(c,'entry.example.test')
    if broken=='middle':c['general']['use_middle_proxy']=True
    if broken=='direct':c['upstreams'].append(dict(type='direct'))
    if broken=='mask':c['censorship']['mask_host']='external.example.test'
    if broken=='api':c['server']['api']['listen']='0.0.0.0:9091'
    if broken=='domain':c['general']['links']['public_host']='localhost'
    if broken=='empty':c['access']['users']={}
    with pytest.raises(SetupError):native_config(c,'entry.example.test')

def test_only_optional_tcp9443_is_allowed():
    text='tcp LISTEN 0 128 0.0.0.0:9443 0.0.0.0:*\nudp UNCONN 0 0 0.0.0.0:9443 0.0.0.0:*\ntcp LISTEN 0 128 0.0.0.0:1080 0.0.0.0:*'
    assert len(unexpected_listeners(text,22))==3
    extra=unexpected_listeners(text,22,True)
    assert len(extra)==2 and extra[0].startswith('udp') and ':1080' in extra[1]

@pytest.mark.parametrize('failed',[False,True])
def test_optional_api_addition_is_idempotent_or_rolled_back(tmp_path,config,monkeypatch,failed):
    import telemt
    peer,original=deployed();config['role']='inbound';config['domain']='entry.example.test'
    write(tmp_path/'state.json',config)
    (tmp_path/'transport.json').write_text(json.dumps(dict(schema=1,mode='direct-reality',topology='relay',active=True)))
    secrets=tmp_path/'secrets';secrets.mkdir()
    (secrets/'relay.json').write_text(json.dumps(peer))
    (secrets/'managed-xray.json').write_text(json.dumps(dict(uuid=peer['uuid'],inbound_id=1)))
    main=dict(id=1,port=443,tag='in-443-tcp',settings=json.dumps(dict(clients=[dict(id=peer['uuid'],email='kept-client')])))
    baseline=copy.deepcopy(main)
    class Api:
        def __init__(self):self.rows=[main];self.tpl=copy.deepcopy(original);self.adds=0;self.sets=0
        def inbounds(self):return copy.deepcopy(self.rows)
        def template(self):return copy.deepcopy(self.tpl)
        def set_template(self,t):self.tpl=copy.deepcopy(t);self.sets+=1
        def restart(self):pass
        def request(self,path,data):
            if path.endswith('/add'):
                self.adds+=1;row=dict(data,id=2);self.rows.append(row);return copy.deepcopy(row)
            assert path.endswith('/del/2');self.rows=[main]
    api=Api()
    compose=socks_compose(dict(services=dict(xui=dict(ports=[]),nginx=dict(ports=[]))))
    (tmp_path/'compose.yml').write_text(json.dumps(compose));before=(tmp_path/'compose.yml').read_bytes()
    class Docker:
        container='fixture'
        def inspect(self,name):return dict(Config=dict(Labels={'com.docker.compose.project':'fixture'}),HostConfig=dict(PortBindings={'1080/tcp':[dict(HostIp='127.0.0.1',HostPort='1080')]}))
        def run(self,*args):
            assert args[-3:]==('config','--format','json')
            return json.dumps(compose)
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def sendall(self,data):pass
        def recv(self,n):return b'\x05\x00'
    monkeypatch.setattr(telemt,'Docker',Docker)
    monkeypatch.setattr(telemt,'authenticated_api',lambda *a:(api,'3.11.0'))
    monkeypatch.setattr(telemt.socket,'create_connection',lambda *a,**kw:Socket())
    def transfer(*args):
        if failed:raise SetupError('Expected OUTBOUND exit mismatch')
    monkeypatch.setattr(telemt,'transfer',transfer)
    if failed:
        with pytest.raises(SetupError,match='mismatch'):telemt.configure(tmp_path)
        assert api.rows==[baseline] and api.tpl==original
        assert not (secrets/'telemt.json').exists()
    else:
        telemt.configure(tmp_path);telemt.configure(tmp_path);telemt.configure(tmp_path,check=True)
        assert api.adds==1 and api.sets==1 and len(api.rows)==2
        assert api.tpl['outbounds']==original['outbounds']
    assert api.rows[0]==baseline and (tmp_path/'compose.yml').read_bytes()==before
