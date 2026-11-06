import base64,copy,json,uuid
import pytest
from client_tools import public_key,select_client,check_selected,show_selected
from transport_profile import client_uri,client_config
from xui_api import SetupError

PRIVATE=base64.urlsafe_b64encode(bytes.fromhex('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a')).decode().rstrip('=')
PUBLIC=base64.urlsafe_b64encode(bytes.fromhex('8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a')).decode().rstrip('=')

class Panel:
    def __init__(self,flow='xtls-rprx-vision'):
        self.identity=str(uuid.uuid4());self.writes=[]
        self.rows=[dict(id=1,remark='Renamed by user',protocol='vless',port=443,enable=True,
            settings=json.dumps(dict(clients=[dict(id=self.identity,email='router-device',enable=True,flow=flow)])),
            streamSettings=json.dumps(dict(network='tcp',security='reality',realitySettings=dict(privateKey=PRIVATE,serverNames=['cover.example.test'],shortIds=['1234567890abcdef'],settings=dict(publicKey='wrong-stale-metadata',serverName='cover.example.test')))))]
    def inbounds(self):return copy.deepcopy(self.rows)
    def request(self,*args,**kwargs):raise AssertionError('Diagnostic must not mutate the panel')


def test_rfc7748_public_key_is_derived_without_regenerating_keys():
    assert public_key(PRIVATE)==PUBLIC


def test_existing_client_is_selected_without_a_test_client_cache():
    api=Panel();before=copy.deepcopy(api.rows)
    row,peer,metadata=select_client(api,dict(domain='entry.example.test'),'router-device')
    assert row['id']==1 and peer['uuid']==api.identity
    assert peer['address']=='entry.example.test' and peer['server_name']=='cover.example.test'
    assert peer['public_key']==PUBLIC and not metadata
    assert api.rows==before and api.writes==[]


def test_actual_empty_flow_is_preserved_in_client_export():
    api=Panel(flow='');row,peer,metadata=select_client(api,dict(domain='entry.example.test'),'router-device')
    assert client_config(peer)['outbounds'][0]['settings']['vnext'][0]['users'][0]['flow']==''
    assert 'flow=' not in client_uri(peer,'device')
    assert 'pbk='+PUBLIC in client_uri(peer,'device')


def test_ambiguous_client_is_not_guessed():
    api=Panel();api.rows.append(copy.deepcopy(api.rows[0]))
    with pytest.raises(SetupError,match='exactly one'):select_client(api,dict(domain='entry.example.test'),'router-device')


def test_disabled_client_is_reported():
    api=Panel();settings=json.loads(api.rows[0]['settings']);settings['clients'][0]['enable']=False
    api.rows[0]['settings']=json.dumps(settings)
    with pytest.raises(SetupError,match='disabled'):select_client(api,dict(domain='entry.example.test'),'router-device')


def test_selected_diagnostic_is_read_only_and_does_not_print_credentials(tmp_path,monkeypatch,capsys):
    from types import SimpleNamespace
    api=Panel();before=copy.deepcopy(api.rows);calls=[]
    engine=SimpleNamespace(api=api,state=dict(domain='entry.example.test',public_ip='192.0.2.10'),profile=dict(mode='direct-reality',topology='standalone'),root=tmp_path,docker=object(),test_url='https://example.test/ip',ca_file=None,actual_bindings=lambda:None)
    def fake_probe(docker,root,peer,expected,url,ca):calls.append(peer);return dict(transport='PASSED')
    monkeypatch.setattr('client_tools.probe',fake_probe)
    check_selected(engine,'router-device')
    text=capsys.readouterr().out
    assert len(calls)==2 and calls[0]['address']=='xui' and calls[1]['address']=='entry.example.test'
    assert api.identity not in text and PRIVATE not in text and PUBLIC not in text
    assert 'metadata differs' in text and api.rows==before


def test_export_uses_terminal_not_stdout(monkeypatch,capsys):
    from types import SimpleNamespace
    api=Panel();written=[]
    class Terminal:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def write(self,text):written.append(text)
    monkeypatch.setattr('client_tools.open',lambda *args:Terminal(),raising=False)
    show_selected(SimpleNamespace(api=api,state=dict(domain='entry.example.test')),'router-device')
    assert capsys.readouterr().out==''
    assert api.identity in written[0] and 'pbk='+PUBLIC in written[0]
    assert PRIVATE not in written[0]
