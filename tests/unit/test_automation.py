import copy,json,uuid
import pytest
from automation import candidate_compose,candidate_tls,GRPC,cloudflare_dns
from managed_inbound import ensure,planned_cache,payload,decoded,relay_template
from transport_profile import parse_peer,client_uri,client_config
from xui_api import SetupError,Api

class FakeApi:
    def __init__(self):self.rows=[];self.writes=[]
    def inbounds(self):return copy.deepcopy(self.rows)
    def clients(self):return []
    def request(self,path,data=None):
        self.writes.append((path,data))
        if path.endswith('getNewX25519Cert'):return {'privateKey':'a'*43,'publicKey':'b'*43}
        row=dict(data,id=len(self.rows)+1,tag='in-'+str(data['port'])+'-tcp');self.rows.append(row);return copy.deepcopy(row)

def parameters(mode='cloudflare-grpc'):
    return {'role':'outbound','domain':'example.test'},dict(schema=1,mode=mode,topology='standalone',active=False)

@pytest.mark.parametrize('mode',['cloudflare-grpc','direct-grpc','direct-reality'])
def test_create_rerun_and_api_recovery(tmp_path,mode):
    api=FakeApi();state,p=parameters(mode);cache=planned_cache(tmp_path,api,state,p)
    uuid.UUID(cache['uuid']);row,created=ensure(api,state,p,cache)
    assert created and row['enable'] and row['listen']=='0.0.0.0'
    assert decoded(row,'settings')['decryption']=='none'
    assert not ensure(api,state,p,cache)[1]
    assert len(api.rows)==1
    assert planned_cache(tmp_path,api,state,p)['uuid']==cache['uuid']
    (tmp_path/'secrets/managed-xray.json').unlink()
    assert planned_cache(tmp_path,api,state,p)['uuid']==cache['uuid']
    if mode=='direct-reality':
        assert decoded(row,'settings')['clients'][0]['flow']=='xtls-rprx-vision'
        assert decoded(row,'streamSettings')['realitySettings']['target']=='nginx:8443'
    else:
        assert decoded(row,'settings')['clients'][0]['flow']==''
        assert decoded(row,'streamSettings')==dict(network='grpc',security='none',grpcSettings=dict(serviceName='vlessgrpc',multiMode=False))
    assert (tmp_path/'secrets/managed-xray.json').stat().st_mode&0o777==0o600

def test_conflicts_preserved(tmp_path):
    api=FakeApi();state,p=parameters();cache=planned_cache(tmp_path,api,state,p)
    row,unused=ensure(api,state,p,cache)
    api.rows[0]['port']=12345
    with pytest.raises(SetupError,match='differs'):ensure(api,state,p,cache)
    api.rows[0]['remark']='user-managed';api.rows[0]['port']=10000
    data=decoded(api.rows[0],'settings');data['clients'][0]['id']=str(uuid.uuid4());api.rows[0]['settings']=json.dumps(data)
    with pytest.raises(SetupError,match='unmanaged'):ensure(api,state,p,cache)
    assert len(api.rows)==1

def test_no_uuid_rotation_for_disabled_client(tmp_path):
    api=FakeApi();state,p=parameters();cache=planned_cache(tmp_path,api,state,p);ensure(api,state,p,cache)
    data=decoded(api.rows[0],'settings');data['clients'][0]['enable']=False;api.rows[0]['settings']=json.dumps(data)
    with pytest.raises(SetupError):ensure(api,state,p,cache)
    assert planned_cache(tmp_path,api,state,p)['uuid']==cache['uuid']

@pytest.mark.parametrize('mode',['cloudflare-grpc','direct-reality'])
def test_compose_port_owner(mode):
    c={'services':{'xui':{'ports':[dict(target=2053,published='2053',host_ip='127.0.0.1'),dict(target=10000,published='10000')]},'nginx':{'ports':[dict(target=8443,published='443'),dict(target=80,published='80')]}}}
    result=candidate_compose(c,mode)
    owners=[name for name,s in result['services'].items() for p in s['ports'] if p['published']=='443']
    assert owners==['xui' if mode=='direct-reality' else 'nginx']
    assert not any(p['target']==10000 for s in result['services'].values() for p in s['ports'])
    assert c['services']['xui']['ports'][1]['published']=='10000'
    c['services']['nginx']['ports'].append(dict(target=443,published='443',protocol='udp'))
    with pytest.raises(SetupError,match='UDP'):candidate_compose(c,mode)

def test_nginx_grpc_configuration():
    original='server {\n server_name example.test;\n location / { try_files $uri =404; }\n}'
    result=candidate_tls(original,'example.test','cloudflare-grpc')
    assert result.count('include /etc/nginx/conf.d/vps-grpc.inc;')==1
    assert candidate_tls(result,'example.test','cloudflare-grpc')==result
    assert 'location = /vlessgrpc/Tun {' in GRPC
    assert 'grpc_pass grpc://xui:10000;' in GRPC
    assert 'location / { try_files' in result
    assert candidate_tls(result,'example.test','direct-reality')==original

def test_peer_uri_and_route_all_managed_traffic():
    peer=dict(mode='grpc',address='exit.example.test',server_name='exit.example.test',port=443,uuid=str(uuid.uuid4()),service='vlessgrpc')
    uri=client_uri(peer,'Example');parsed=parse_peer(uri,'192.0.2.20')
    assert parsed['uuid']==peer['uuid'] and parsed['service']=='vlessgrpc'
    base={'outbounds':[{'tag':'direct','protocol':'freedom'}],'routing':{'rules':[{'type':'field','ip':['geoip:private'],'outboundTag':'blocked'}]}}
    after=relay_template(base,'in-10000-tcp',parsed)
    assert after['routing']['rules'][0]==dict(type='field',inboundTag=['in-10000-tcp'],outboundTag='to-outbound')
    assert relay_template(after,'in-10000-tcp',parsed)==after
    assert len(client_config(parsed)['outbounds'])==1
    assert client_config(parsed)['outbounds'][0]['protocol']=='vless'
    assert not client_config(parsed)['outbounds'][0]['streamSettings']['tlsSettings']['allowInsecure']
    assert base['routing']['rules'][0]['outboundTag']=='blocked'
    with pytest.raises(SetupError):parse_peer(uri.split('#')[0]+'&security=none','192.0.2.20')

def test_cloudflare_proxy_check(monkeypatch):
    import dns
    from conftest import APP
    monkeypatch.setattr(dns,'resolve',lambda host:dict(A={'104.21.1.1'},AAAA={'2606:4700::1'}))
    assert cloudflare_dns('example.test',APP/'config/cloudflare-networks.json')
    monkeypatch.setattr(dns,'resolve',lambda host:dict(A={'192.0.2.10'},AAAA=set()))
    with pytest.raises(SetupError,match='Proxied'):cloudflare_dns('example.test',APP/'config/cloudflare-networks.json')

def test_api_response_never_leaks_secrets():
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b'{"success":false,"msg":"secret-password-uuid"}'
    class Opener:
        def open(self,*args,**kw):return Response()
    api=Api('http://127.0.0.1:2053','secret-token');api.opener=Opener()
    with pytest.raises(SetupError) as exc:api.request('/panel/api/inbounds/add',{'settings':'private'})
    assert 'secret-password' not in str(exc.value)

@pytest.mark.parametrize('version',['3.11.0','3.12.0'])
def test_latest_runtime_contract_guard(version):
    from xui_api import Docker
    docker=Docker();docker.run=lambda *args,**kwargs:version
    if version=='3.11.0':assert docker.version()==version
    else:
        with pytest.raises(SetupError,match='unreviewed API version'):docker.version()

def test_unmanaged_client_not_overwritten(tmp_path):
    api=FakeApi();state,p=parameters();cache=planned_cache(tmp_path,api,state,p)
    api.clients=lambda:[dict(email=cache['email'],uuid=str(uuid.uuid4()))]
    with pytest.raises(SetupError,match='existing client was preserved'):ensure(api,state,p,cache)
    assert api.writes==[]

def test_relay_conflict_not_overwritten():
    state,p=parameters();peer=dict(mode='grpc',address='exit.example.test',server_name='exit.example.test',port=443,uuid=str(uuid.uuid4()),service='vlessgrpc')
    current=dict(outbounds=[],routing=dict(rules=[dict(type='field',inboundTag=['mine'],outboundTag='direct')]))
    before=copy.deepcopy(current)
    with pytest.raises(SetupError,match='Conflicting route'):relay_template(current,'mine',peer)
    assert current==before


def test_relay_rule_is_unconditional_and_preserves_deployed_defaults():
    peer=dict(mode='grpc',address='exit.example.test',server_name='exit.example.test',port=443,uuid=str(uuid.uuid4()),service='vlessgrpc')
    old_out=client_config(peer)['outbounds'][0];old_out['tag']='vps-installer-exit'
    blocked=dict(tag='blocked',protocol='blackhole',settings={})
    template=dict(outbounds=[dict(tag='direct',protocol='freedom'),old_out,blocked],routing=dict(rules=[]))
    planned=relay_template(template,'saved-tag',peer)
    assert planned['outbounds']==template['outbounds']
    assert len(planned['outbounds'])==3
    assert planned['routing']['rules'][0]['outboundTag']=='vps-installer-exit'
    assert planned['routing']['rules'][0]['inboundTag']==['saved-tag']
    assert relay_template(planned,'saved-tag',peer)==planned


def test_new_relay_rejects_a_direct_ip_or_wrong_transport():
    from transport_profile import relay_peer
    peer=dict(mode='grpc',address='exit.example.test',server_name='exit.example.test',port=443,uuid=str(uuid.uuid4()),service='vlessgrpc')
    assert relay_peer(peer)==peer
    for patch in (dict(mode='reality'),dict(port=10000),dict(service='other'),dict(server_name='other.example.test')):
        with pytest.raises(SetupError):relay_peer(dict(peer,**patch))
    with pytest.raises(SetupError):parse_peer('vless://'+peer['uuid']+'@192.0.2.10:443?security=tls&type=grpc&serviceName=vlessgrpc','192.0.2.10')


def test_relay_keeps_native_panel_api_rule_first():
    peer=dict(mode='grpc',address='exit.example.test',server_name='exit.example.test',port=443,uuid=str(uuid.uuid4()),service='vlessgrpc')
    api_rule=dict(type='field',inboundTag=['api'],outboundTag='api')
    template=dict(outbounds=[dict(tag='direct',protocol='freedom')],routing=dict(rules=[api_rule]))
    planned=relay_template(template,'client-in',peer)
    assert planned['routing']['rules'][0]==api_rule
    assert planned['routing']['rules'][1]['outboundTag']=='to-outbound'
    assert relay_template(planned,'client-in',peer)==planned
