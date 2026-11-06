"""Read-only diagnostics/export for an explicitly selected existing VLESS client."""
import base64,json,re,subprocess
from managed_inbound import decoded
from transport_profile import client_uri
from xui_api import SetupError
from xray_probe import probe


def public_key(private):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',private):raise SetupError('Invalid REALITY private-key encoding in the API; key not changed')
    raw=base64.urlsafe_b64decode(private+'=')
    der=bytes.fromhex('302e020100300506032b656e04220420')+raw
    result=subprocess.run(['openssl','pkey','-inform','DER','-pubout','-outform','DER'],input=der,capture_output=True)
    prefix=bytes.fromhex('302a300506032b656e032100')
    if result.returncode or not result.stdout.startswith(prefix) or len(result.stdout)!=44:raise SetupError('Could not derive the existing REALITY public key; keys not changed')
    return base64.urlsafe_b64encode(result.stdout[len(prefix):]).decode().rstrip('=')


def select_client(api,state,email):
    matches=[]
    for row in api.inbounds():
        if row['protocol']!='vless':continue
        for client in decoded(row,'settings').get('clients',[]):
            if client.get('email')==email:matches.append((row,client))
    if len(matches)!=1:raise SetupError('Expected exactly one VLESS inbound/client for this email; no configuration was guessed')
    row,client=matches[0];stream=decoded(row,'streamSettings')
    if row.get('enable') is not True or client.get('enable') is not True:raise SetupError('Selected inbound or client is disabled')
    peer=dict(address=state['domain'],port=443,server_name=state['domain'],uuid=client['id'])
    metadata_matches=True
    if stream.get('security')=='reality' and stream.get('network') in ('tcp','raw'):
        if row['port']!=443:raise SetupError('Selected REALITY listener is not on internal TCP443')
        settings=stream.get('realitySettings',{});names=settings.get('serverNames',[]);shorts=settings.get('shortIds',[])
        if not names or not shorts:raise SetupError('REALITY serverNames or shortIds is empty')
        preferred=settings.get('settings',{}).get('serverName')
        server_name=preferred if preferred in names else names[0]
        derived=public_key(settings.get('privateKey',''))
        metadata_matches=settings.get('settings',{}).get('publicKey')==derived
        flow=client.get('flow','')
        if flow not in ('','xtls-rprx-vision'):raise SetupError('Selected client uses an unsupported VLESS flow')
        peer.update(mode='reality',server_name=server_name,public_key=derived,short_id=shorts[0],fingerprint='chrome',flow=flow)
    elif stream.get('network')=='grpc' and stream.get('security')=='none':
        service=stream.get('grpcSettings',{}).get('serviceName','')
        if not service:raise SetupError('Selected gRPC inbound has no serviceName')
        peer.update(mode='grpc',service=service)
    else:raise SetupError('Selected VLESS transport is not a supported REALITY or nginx gRPC setup')
    return row,peer,metadata_matches


def check_selected(engine,email):
    row,peer,metadata_matches=select_client(engine.api,engine.state,email)
    # Use actual API settings, not a removed managed test client's cache.
    engine.profile=dict(engine.profile,mode='direct-reality' if peer['mode']=='reality' else 'direct-grpc')
    engine.actual_bindings()
    print('Selected existing client: enabled; '+peer['mode']+'; flow='+str(peer.get('flow','none') or 'none'),flush=True)
    if not metadata_matches:print('Panel public-key metadata differs from the existing server key; this diagnostic uses the correctly derived public key.',flush=True)
    expected=engine.state['public_ip']
    if engine.profile['topology']=='relay':
        remote=json.loads((engine.root/'secrets/relay.json').read_text());expected=remote['expected_ip']
        print('Checking INBOUND -> OUTBOUND transfer...',flush=True)
        probe(engine.docker,engine.root,remote,expected,engine.test_url,engine.ca_file)
        print('OUTBOUND transfer: PASSED',flush=True)
    internal=dict(peer,address='xui' if peer['mode']=='reality' else 'nginx',port=443 if peer['mode']=='reality' else 8443)
    print('Checking selected client through internal INBOUND...',flush=True)
    probe(engine.docker,engine.root,internal,expected,engine.test_url,engine.ca_file)
    print('Internal INBOUND transfer: PASSED',flush=True)
    print('Checking selected client through public INBOUND...',flush=True)
    result=probe(engine.docker,engine.root,peer,expected,engine.test_url,engine.ca_file)
    print('Public INBOUND transfer: PASSED',flush=True)
    return result


def show_selected(engine,email):
    row,peer,metadata_matches=select_client(engine.api,engine.state,email)
    # No stdout: a client URI is a credential, not diagnostic output.
    try:
        with open('/dev/tty','w') as terminal:
            terminal.write('\nExisting client profile (keep private):\n'+client_uri(peer,email)+'\n')
    except OSError:raise SetupError('Showing client credentials requires an interactive terminal') from None
