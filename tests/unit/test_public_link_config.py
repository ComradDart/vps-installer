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


def test_repair_refuses_outbound_before_any_api_call(tmp_path,config):
    class NoApi:
        def __getattr__(self,key):raise AssertionError('OUTBOUND API must not be used')
    with pytest.raises(Exception,match='only for INBOUND'):
        repair(NoApi(),tmp_path,config,dict(mode='cloudflare-grpc'))


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
