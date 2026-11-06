#!/usr/bin/env python3
import copy,json,re,secrets,uuid
from xui_api import SetupError,private_json

SERVICE='vlessgrpc'
def decoded(row,key):
    value=row.get(key)
    if isinstance(value,str):
        try:value=json.loads(value)
        except ValueError:raise SetupError('Malformed '+key+' in existing inbound') from None
    if not isinstance(value,dict):raise SetupError('Unexpected '+key+' schema')
    return value

def marker(state,profile):return 'vps-installer:'+state['role']+':'+profile['mode']

def planned_cache(root,api,state,profile):
    path=root/'secrets/managed-xray.json'
    if path.exists():
        cache=json.loads(path.read_text())
        if cache.get('mode')!=profile['mode']:raise SetupError('Changing an existing managed transport requires a separate migration; active UUIDs have not been changed')
        uuid.UUID(cache['uuid']);return cache
    # Recover identity from the API before generating anything.
    matches=[r for r in api.inbounds() if r.get('remark')==marker(state,profile)]
    if len(matches)>1:raise SetupError('Multiple managed inbounds found; refusing to guess or delete one')
    if matches:
        row=matches[0];clients=decoded(row,'settings').get('clients',[])
        selected=[c for c in clients if c.get('email')=='vps-installer-test' and c.get('enable') is True]
        if len(selected)!=1:raise SetupError('Managed test client missing or ambiguous; UUID not regenerated')
        cache={'mode':profile['mode'],'uuid':selected[0]['id'],'email':'vps-installer-test','inbound_id':row['id']}
        if profile['mode']=='direct-reality':
            reality=decoded(row,'streamSettings')['realitySettings'];public=reality.get('settings',{}).get('publicKey')
            if not public:raise SetupError('Existing REALITY public key is unavailable; private key and UUID have not been changed')
            cache.update(private_key=reality['privateKey'],public_key=public,short_id=reality['shortIds'][0])
    else:
        cache={'mode':profile['mode'],'uuid':str(uuid.uuid4()),'email':'vps-installer-test'}
        if profile['mode']=='direct-reality':
            keys=api.request('/panel/api/server/getNewX25519Cert')
            if not isinstance(keys,dict) or any(not re.fullmatch(r'[A-Za-z0-9_-]{43}',keys.get(k,'')) for k in ('privateKey','publicKey')):raise SetupError('Unexpected official REALITY key-generation response')
            cache.update(private_key=keys['privateKey'],public_key=keys['publicKey'],short_id=secrets.token_hex(8))
    private_json(path,cache);return cache

def payload(state,profile,cache):
    reality=profile['mode']=='direct-reality'
    client={'id':cache['uuid'],'flow':'xtls-rprx-vision' if reality else '', 'email':cache['email'],'enable':True,'limitIp':0,'totalGB':0,'expiryTime':0}
    if reality:
        stream={'network':'tcp','security':'reality','realitySettings':{'show':False,'target':'nginx:8443','xver':0,'serverNames':[state['domain']],'privateKey':cache['private_key'],'shortIds':[cache['short_id']],'settings':{'publicKey':cache['public_key'],'fingerprint':'chrome','serverName':state['domain'],'spiderX':'/'}}}
    else:stream={'network':'grpc','security':'none','grpcSettings':{'serviceName':SERVICE,'multiMode':False}}
    return {'up':0,'down':0,'total':0,'remark':marker(state,profile),'enable':True,'expiryTime':0,'listen':'0.0.0.0','port':443 if reality else 10000,'protocol':'vless',
            'shareAddrStrategy':'custom','shareAddr':state['domain'],
            'settings':json.dumps({'clients':[client],'decryption':'none'}),'streamSettings':json.dumps(stream),'sniffing':json.dumps({'enabled':False,'destOverride':['http','tls']})}

def validate_existing(row,state,profile,cache):
    expected=payload(state,profile,cache)
    if any(row.get(k)!=expected[k] for k in ('protocol','port','listen','enable')):raise SetupError('Existing managed inbound differs from the selected transport; not overwritten')
    settings=decoded(row,'settings');stream=decoded(row,'streamSettings')
    clients=[c for c in settings.get('clients',[]) if c.get('id')==cache['uuid']]
    if len(clients)!=1 or clients[0].get('enable') is not True or clients[0].get('flow','')!=('xtls-rprx-vision' if profile['mode']=='direct-reality' else '') or settings.get('decryption')!='none':raise SetupError('Existing managed VLESS client settings differ; UUID and clients were preserved')
    if profile['mode']=='direct-reality':
        r=stream.get('realitySettings',{})
        if stream.get('network') not in ('tcp','raw') or stream.get('security')!='reality' or r.get('target',r.get('dest'))!='nginx:8443' or state['domain'] not in r.get('serverNames',[]) or r.get('privateKey')!=cache['private_key'] or cache['short_id'] not in r.get('shortIds',[]):raise SetupError('Existing REALITY settings differ; no keys regenerated')
    elif stream.get('network')!='grpc' or stream.get('security')!='none' or stream.get('grpcSettings',{}).get('serviceName')!=SERVICE or stream.get('grpcSettings',{}).get('multiMode',False) is not False:raise SetupError('Existing gRPC service/transport differs; no inbound overwritten')
    if not row.get('tag'):raise SetupError('API did not return an inbound tag')
    return row

def owned_inbound(rows,state,profile,cache):
    """Remark is a mutable display name; ownership uses the saved ID and client UUID."""
    def contains(row):return any(c.get('id')==cache['uuid'] for c in decoded(row,'settings').get('clients',[]))
    identified=[r for r in rows if contains(r)]
    saved=cache.get('inbound_id')
    if saved is not None:
        matches=[r for r in identified if r['id']==saved]
        if len(matches)==1:return matches[0]
        if identified:raise SetupError('Saved UUID belongs to a different inbound ID; no configuration was guessed')
    else:
        if len(identified)==1:return identified[0]
        if len(identified)>1:raise SetupError('Saved UUID occurs in multiple inbounds; saved inbound ID is required')
    if any(r.get('remark')==marker(state,profile) for r in rows):raise SetupError('Managed name exists but its saved client UUID is missing; clients were preserved')
    return None

def ensure(api,state,profile,cache):
    rows=api.inbounds();owned=owned_inbound(rows,state,profile,cache)
    if owned:return validate_existing(owned,state,profile,cache),False
    port=443 if profile['mode']=='direct-reality' else 10000
    if any(int(r['port'])==port for r in rows):raise SetupError('Port '+str(port)+' already belongs to an unmanaged inbound. Existing configuration was preserved.')
    if any(c['email']==cache['email'] for c in api.clients()):raise SetupError('Managed test-client email already exists outside this inbound; existing client was preserved')
    row=api.request('/panel/api/inbounds/add',payload(state,profile,cache))
    if not isinstance(row,dict) or not row.get('id'):raise SetupError('Inbound creation returned an unexpected schema')
    return validate_existing(row,state,profile,cache),True

def peer_for_client(state,profile,cache,address=None,port=443):
    peer={'address':address or state['domain'],'server_name':state['domain'],'port':port,'uuid':cache['uuid']}
    if profile['mode']=='direct-reality':peer.update(mode='reality',public_key=cache['public_key'],short_id=cache['short_id'],fingerprint='chrome')
    else:peer.update(mode='grpc',service=SERVICE)
    return peer

def relay_template(template,inbound_tag,peer):
    from transport_profile import outbound
    result=copy.deepcopy(template);tag='vps-installer-exit'
    matches=[o for o in result.get('outbounds',[]) if o.get('tag')==tag]
    candidate=outbound(peer,tag)
    if matches and (len(matches)!=1 or matches[0]!=candidate):raise SetupError('Existing managed OUTBOUND differs; no routing overwritten')
    if not matches:result.setdefault('outbounds',[]).append(candidate)
    rules=result.setdefault('routing',{}).setdefault('rules',[])
    expected={'type':'field','inboundTag':[inbound_tag],'outboundTag':tag}
    conflicts=[r for r in rules if inbound_tag in r.get('inboundTag',[]) and r!=expected]
    if conflicts:raise SetupError('Conflicting route for the managed inbound; direct fallback not applied')
    result['routing']['rules']=[expected]+[r for r in rules if r!=expected]
    return result


def share_address_patch(row,state):
    """Make panel-generated device links independent of the SSH-tunnel Host header."""
    if row.get('shareAddrStrategy')=='custom' and row.get('shareAddr')==state['domain']:return None
    result=copy.deepcopy(row)
    result.update(shareAddrStrategy='custom',shareAddr=state['domain'])
    return result
