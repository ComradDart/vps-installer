import copy,json
import pytest
from public_links import export_patch,host_payload,repair
from state import write,validate
from client_tools import public_key


def test_public_domain_migrates_inbound_only(tmp_path,config):
    config['role']='inbound';target=tmp_path/'state.json';write(target,config)
    assert json.loads(target.read_text())['PUBLIC_DOMAIN']==config['domain']
    assert target.stat().st_mode&0o777==0o600
    config['PUBLIC_DOMAIN']='localhost'
    with pytest.raises(AssertionError):validate(config)


def test_reality_export_patch_preserves_client_and_server_identity(config):
    private='dwdtCnMYpX08FsFyUbJmRd9ML4frwJkqsXf7pR25LCo'
    stream=dict(network='tcp',security='reality',realitySettings=dict(privateKey=private,shortIds=['1234567890abcdef'],serverNames=['sni.example.test'],settings=dict(publicKey='')))
    row=dict(id=3,port=443,listen='0.0.0.0',settings=json.dumps(dict(clients=[dict(id='existing-uuid',subId='existing-sub-id',flow='xtls-rprx-vision')])),streamSettings=json.dumps(stream))
    old=copy.deepcopy(row);fixed=export_patch(row,config)
    assert row==old and fixed['settings']==row['settings']
    settings=json.loads(fixed['streamSettings'])['realitySettings']
    assert settings['privateKey']==private and settings['shortIds']==stream['realitySettings']['shortIds']
    assert settings['settings']['publicKey']==public_key(private)
    host=host_payload(row,config)
    assert host['hosts']==[config['domain']+':443'] and host['security']=='same'
    assert 'sni' not in host # inherit the actual REALITY serverNames, not Address


def test_grpc_native_host_and_export_have_public_tls(config):
    import uuid,urllib.parse
    from public_links import validate_uri
    from xui_api import SetupError
    identity=str(uuid.uuid4());client=dict(id=identity,enable=True,flow='')
    row=dict(id=8,port=10000,settings=json.dumps(dict(clients=[client])),
             streamSettings=json.dumps(dict(network='grpc',security='none',grpcSettings=dict(serviceName='vlessgrpc'))))
    before=copy.deepcopy(row);host=host_payload(row,config)
    assert host['security']=='tls' and host['port']==443 and host['alpn']==['h2']
    assert host['sni']==config['domain'] and row==before
    query=dict(security='tls',type='grpc',serviceName='vlessgrpc',sni=config['domain'],alpn='h2',encryption='none')
    def uri(q,port=443):return 'vless://'+identity+'@'+config['domain']+':'+str(port)+'?'+urllib.parse.urlencode(q)
    validate_uri(uri(query),row,client,config)
    for patch in (dict(security='none'),dict(sni='localhost'),dict(serviceName=''),dict(flow='xtls-rprx-vision')):
        with pytest.raises(SetupError):validate_uri(uri(dict(query,**patch)),row,client,config)
    with pytest.raises(SetupError):validate_uri(uri(query,10000),row,client,config)
