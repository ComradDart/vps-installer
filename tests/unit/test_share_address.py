import copy,json,uuid
from managed_inbound import payload,share_address_patch,peer_for_client
from transport_profile import client_uri
import pytest

@pytest.mark.parametrize('mode',['cloudflare-grpc','direct-grpc','direct-reality'])
def test_generated_panel_links_have_an_explicit_public_domain(mode):
    state=dict(role='inbound',domain='entry.example.test')
    profile=dict(mode=mode)
    cache=dict(uuid=str(uuid.uuid4()),email='test',private_key='a'*43,public_key='b'*43,short_id='1234567890abcdef')
    row=payload(state,profile,cache)
    assert row['shareAddrStrategy']=='custom' and row['shareAddr']=='entry.example.test'
    assert row['listen']=='0.0.0.0'
    uri=client_uri(peer_for_client(state,profile,cache),'device')
    assert '@entry.example.test:443?' in uri and 'sni=entry.example.test' in uri
    assert 'localhost' not in uri


def test_panel_address_repair_does_not_change_listener_or_clients():
    state=dict(domain='entry.example.test')
    row=dict(id=1,tag='existing',listen='0.0.0.0',port=443,shareAddrStrategy='node',shareAddr='',settings=json.dumps(dict(clients=[dict(id=str(uuid.uuid4()),flow='xtls-rprx-vision')])) )
    old=copy.deepcopy(row);fixed=share_address_patch(row,state)
    assert row==old
    assert fixed==dict(old,shareAddrStrategy='custom',shareAddr='entry.example.test')
    assert share_address_patch(fixed,state) is None


def test_existing_panel_export_address_is_repaired_idempotently(tmp_path,config):
    from test_reality_migration import transaction_engine
    engine,api,cache=transaction_engine(tmp_path,config)
    api.row.update(shareAddrStrategy='node',shareAddr='localhost')
    original=copy.deepcopy(api.row)
    engine.provision(public=False)
    assert api.row['shareAddrStrategy']=='custom' and api.row['shareAddr']==config['domain']
    for key in ('id','tag','listen','port','settings','streamSettings'):assert api.row[key]==original[key]
    writes=len(api.writes)
    engine.provision(public=False)
    assert len(api.writes)==writes


def test_failed_check_rolls_back_panel_export_address(tmp_path,config):
    from test_reality_migration import transaction_engine
    from xui_api import SetupError
    engine,api,cache=transaction_engine(tmp_path,config)
    api.row.update(shareAddrStrategy='node',shareAddr='localhost')
    original=copy.deepcopy(api.row)
    def reject():raise SetupError('Injected post-share failure')
    engine.actual_bindings=reject
    with pytest.raises(SetupError,match='Injected post-share'):engine.provision(public=False)
    assert api.row==original
    assert not (tmp_path/'.transport-transaction').exists()
