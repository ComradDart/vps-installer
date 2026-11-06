import copy,json,urllib.parse,uuid
import pytest
from managed_inbound import decoded,payload,validate_existing
from reality_migration import plan,apply,restore,compatible
from xui_api import SetupError

class Panel:
    def __init__(self,state,profile,cache):
        self.row=dict(payload(state,profile,cache),id=7,tag='in-10000-tcp')
        settings=decoded(self.row,'settings')
        settings['clients'].append(dict(id=str(uuid.uuid4()),email='device-two',flow='',enable=False,totalGB=123456,expiryTime=987654,comment='preserve me'))
        self.row['settings']=json.dumps(settings);self.writes=[];self.keys=0
    def inbounds(self):return [copy.deepcopy(self.row)]
    def restart(self):pass
    def clients(self):return [dict(email=c['email'],uuid=c['id']) for c in decoded(self.row,'settings')['clients']]
    def request(self,path,data=None):
        if path.endswith('getNewX25519Cert'):
            self.keys+=1;return dict(privateKey='p'*43,publicKey='q'*43)
        if '/clients/get/' in path:return dict(client=dict(limitHwid=7))
        self.writes.append((path,copy.deepcopy(data)))
        if '/inbounds/update/' in path:
            old=decoded(self.row,'settings')['clients']
            previous_tag=self.row['tag'];previous_port=self.row['port']
            self.row=copy.deepcopy(data)
            if previous_tag=='in-'+str(previous_port)+'-tcp' and self.row['tag']==previous_tag:
                self.row['tag']='in-'+str(self.row['port'])+'-tcp'
            settings=decoded(self.row,'settings');settings['clients']=old;self.row['settings']=json.dumps(settings)
            return copy.deepcopy(self.row)
        if '/clients/update/' in path:
            assert path.endswith('?inboundIds=7')
            email=urllib.parse.unquote(path.split('/clients/update/')[1].split('?')[0])
            assert data['limitHwid']==7
            settings=decoded(self.row,'settings')
            for client in settings['clients']:
                if client['email']==email:client['flow']=data['flow']
            self.row['settings']=json.dumps(settings);return None
        raise AssertionError('Unexpected API call')

@pytest.fixture
def migration(tmp_path):
    state=dict(role='inbound',domain='entry.example.test')
    profile=dict(schema=1,mode='direct-grpc',topology='relay',active=True)
    cache=dict(mode='direct-grpc',uuid=str(uuid.uuid4()),email='vps-installer-test',inbound_id=7)
    api=Panel(state,profile,cache)
    value=plan(tmp_path,api,state,profile,cache)
    return tmp_path,state,profile,cache,api,value


def test_migration_keeps_uuid_tag_clients_and_relay(migration):
    root,state,profile,cache,api,value=migration
    before=copy.deepcopy(api.row)
    result=apply(api,value)
    assert result['id']==7 and result['tag']==before['tag']
    assert result['port']==443
    assert value['profile']['topology']=='relay'
    assert value['cache']['uuid']==cache['uuid']
    validate_existing(result,state,value['profile'],value['cache'])
    old=decoded(before,'settings')['clients'];new=decoded(result,'settings')['clients']
    for left,right in zip(old,new):assert dict(left,flow='xtls-rprx-vision')==right
    assert decoded(result,'streamSettings')['realitySettings']['target']=='nginx:8443'
    assert not any('/add' in path or '/del' in path for path,data in api.writes)
    assert profile['mode']=='direct-grpc' and cache['mode']=='direct-grpc'


def test_retry_reuses_pending_keys(migration):
    root,state,profile,cache,api,value=migration
    second=plan(root,api,state,profile,cache)
    assert value['cache']==second['cache'] and api.keys==1


def test_partial_flow_change_can_be_rolled_back(migration):
    root,state,profile,cache,api,value=migration
    before=copy.deepcopy(api.row)
    api.request('/panel/api/inbounds/update/7',dict(value['original'],tag=value['temporary_tag']))
    api.request('/panel/api/inbounds/update/7',value['desired'])
    from reality_migration import set_flow
    set_flow(api,7,'vps-installer-test','xtls-rprx-vision')
    restore(api,value)
    assert decoded(api.row,'settings')==decoded(before,'settings')
    assert decoded(api.row,'streamSettings')==decoded(before,'streamSettings')
    assert api.row['tag']==before['tag'] and api.row['port']==10000


def test_concurrent_client_edit_is_not_overwritten(migration):
    root,state,profile,cache,api,value=migration
    apply(api,value)
    settings=decoded(api.row,'settings');settings['clients'][0]['totalGB']=76543
    api.row['settings']=json.dumps(settings)
    restore(api,value)
    assert decoded(api.row,'settings')['clients'][0]['totalGB']==76543
    assert decoded(api.row,'settings')['clients'][0].get('flow','')==''


def test_outbound_cannot_be_migrated(migration):
    root,state,profile,cache,api,value=migration
    with pytest.raises(SetupError,match='only for the INBOUND'):plan(root,api,dict(state,role='outbound'),profile,cache)


def test_already_reality_does_not_generate_new_keys(migration):
    root,state,profile,cache,api,value=migration
    assert plan(root,api,state,dict(profile,mode='direct-reality'),value['cache']) is None
    assert api.keys==1

@pytest.mark.parametrize('role,choice,mode,topology',[
    ('inbound','2','direct-reality','standalone'),
    ('outbound','1','cloudflare-grpc','standalone'),
])
def test_role_transport_selection(tmp_path,role,choice,mode,topology):
    import subprocess
    from conftest import APP
    script=r'''set -Eeuo pipefail
ROOT=$1; APP=$2; ROLE=$3; CHOICE=$4
source "$APP/lib/automation.sh"
log(){ :; }
ask(){ printf -v "$1" '%s' "$CHOICE"; }
transport_select
'''
    result=subprocess.run(['bash','-c',script,'test',str(tmp_path),str(APP),role,choice],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    profile=json.loads((tmp_path/'transport.json').read_text())
    assert profile['mode']==mode and profile['topology']==topology


def test_interrupted_temporary_tag_restores_original_route_tag(migration):
    root,state,profile,cache,api,value=migration
    original=copy.deepcopy(api.row)
    bridge=dict(value['original'],tag=value['temporary_tag'])
    api.request('/panel/api/inbounds/update/7',bridge)
    restore(api,value)
    assert api.row['tag']==original['tag'] and api.row['port']==original['port']


def test_changed_client_identity_blocks_rollback(migration):
    root,state,profile,cache,api,value=migration
    apply(api,value)
    settings=decoded(api.row,'settings');settings['clients'][0]['id']=str(uuid.uuid4())
    api.row['settings']=json.dumps(settings)
    assert not compatible(api.row,value)
    with pytest.raises(SetupError,match='Concurrent'):restore(api,value)

class MemoryDocker:
    container='vps-xui';nginx='vps-nginx';network='vps-installer-proxy'
    def inspect(self,name):return dict(Config=dict(Labels={'com.docker.compose.project':'test'},Image='nginx:latest'))
    def run(self,*args,**kwargs):return ''


def transaction_engine(tmp_path,config):
    from automation import Engine
    from state import write
    from xui_api import private_json
    config=dict(config,role='inbound');write(tmp_path/'state.json',config)
    profile=dict(schema=1,mode='direct-grpc',topology='standalone',active=True)
    cache=dict(mode='direct-grpc',uuid=str(uuid.uuid4()),email='vps-installer-test',inbound_id=7)
    api=Panel(config,profile,cache)
    private_json(tmp_path/'transport.json',profile);private_json(tmp_path/'secrets/managed-xray.json',cache)
    compose=dict(services=dict(xui=dict(ports=[dict(target=2053,published='2053',host_ip='127.0.0.1')]),nginx=dict(ports=[dict(target=8443,published='443',host_ip='0.0.0.0')])) )
    private_json(tmp_path/'compose.yml',compose)
    conf=tmp_path/'conf.d';conf.mkdir();(conf/'tls.conf').write_text('server {\nserver_name '+config['domain']+';\n    include /etc/nginx/conf.d/vps-grpc.inc;\n}\n')
    (conf/'vps-grpc.inc').write_text('old grpc include')
    class Harness(Engine):
        """Transaction unit harness: filesystem is real; Docker/client operations are stubs."""
        def compose(self,*args,file=None):
            path=file or self.compose_path
            if args[0]=='config':return path.read_text()
            if args[0]=='up':
                rows=json.loads(path.read_text())['services']
                self.port_owner=next(name for name,s in rows.items() for p in s['ports'] if p['published']=='443')
            return ''
        def nginx_test(self,conf):pass
        def wait_healthy(self):pass
        def actual_bindings(self):
            assert self.port_owner==('xui' if self.profile['mode']=='direct-reality' else 'nginx')
        def verify_internal(self,cache):
            validate_existing(api.inbounds()[0],self.state,self.profile,cache)
        def verify_public(self,cache):raise AssertionError('External E2E must not run in a unit test')
    return Harness(tmp_path,api,MemoryDocker(),ca_file=tmp_path/'test-ca'),api,cache


def test_transaction_rolls_back_after_port_handoff_and_retry_keeps_uuid(tmp_path,config):
    from xui_api import private_json
    engine,api,cache=transaction_engine(tmp_path,config)
    original_compose=(tmp_path/'compose.yml').read_bytes()
    original_profile=(tmp_path/'transport.json').read_bytes()
    original_cache=(tmp_path/'secrets/managed-xray.json').read_bytes()
    def reject():raise SetupError('Post-handoff injected failure')
    check=engine.actual_bindings;engine.actual_bindings=reject
    with pytest.raises(SetupError,match='Post-handoff'):engine.provision(public=False,migrate=True)
    assert engine.port_owner=='nginx' and api.row['port']==10000
    assert (tmp_path/'compose.yml').read_bytes()==original_compose
    assert (tmp_path/'transport.json').read_bytes()==original_profile
    assert (tmp_path/'secrets/managed-xray.json').read_bytes()==original_cache
    assert not (tmp_path/'.transport-transaction').exists()
    engine.actual_bindings=check
    engine.provision(public=False,migrate=True)
    assert engine.port_owner=='xui' and api.row['port']==443
    assert decoded(api.row,'settings')['clients'][0]['id']==cache['uuid']
    assert json.loads((tmp_path/'secrets/managed-xray.json').read_text())['uuid']==cache['uuid']
    assert 'security=reality' in (tmp_path/'clients/vless.txt').read_text()
    assert api.keys==1
    first=(tmp_path/'secrets/managed-xray.json').read_bytes()
    engine.provision(public=False,migrate=True)
    assert (tmp_path/'secrets/managed-xray.json').read_bytes()==first and api.keys==1


def test_changed_shared_record_uuid_is_not_reset(migration):
    from reality_migration import set_flow
    root,state,profile,cache,api,value=migration
    original=api.request
    def request(path,data=None):
        if '/clients/get/' in path:return dict(client=dict(uuid=str(uuid.uuid4()),limitHwid=7))
        return original(path,data)
    api.request=request
    with pytest.raises(SetupError,match='UUID changed'):set_flow(api,7,cache['email'],'xtls-rprx-vision')
    assert decoded(api.row,'settings')['clients'][0]['id']==cache['uuid']
    assert api.writes==[]
