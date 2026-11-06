"""In-place conversion of an installer-owned INBOUND to REALITY/Vision."""
import copy,json,re,secrets,urllib.parse
from managed_inbound import decoded,marker,payload,validate_existing
from xui_api import SetupError,private_json


def select_row(api,state,profile,cache):
    rows=[r for r in api.inbounds() if r.get('remark')==marker(state,profile)]
    if len(rows)!=1:raise SetupError('Expected one managed INBOUND for migration; nothing overwritten')
    row=validate_existing(rows[0],state,profile,cache)
    if cache.get('inbound_id',row['id'])!=row['id']:raise SetupError('Managed inbound identity changed; migration refused')
    return row


def plan(root,api,state,profile,cache):
    if state['role']!='inbound':raise SetupError('REALITY migration is only for the INBOUND server; OUTBOUND was not modified')
    if profile['mode']=='direct-reality':return None
    if profile['mode']!='direct-grpc':raise SetupError('Only a managed direct-grpc INBOUND can be migrated')
    original=select_row(api,state,profile,cache)
    temporary_tag='vps-installer-migration-'+str(original['id'])
    if any(r['id']!=original['id'] and r.get('tag')==temporary_tag for r in api.inbounds()):raise SetupError('Temporary migration tag is already in use')
    if any(r['id']!=original['id'] and int(r['port'])==443 for r in api.inbounds()):raise SetupError('Port 443 belongs to another inbound; migration refused')
    keyfile=root/'secrets/reality-migration.json'
    if keyfile.exists():keys=json.loads(keyfile.read_text())
    else:
        pair=api.request('/panel/api/server/getNewX25519Cert')
        keys=dict(uuid=cache['uuid'],private_key=pair.get('privateKey',''),public_key=pair.get('publicKey',''),short_id=secrets.token_hex(8))
        if any(not re.fullmatch(r'[A-Za-z0-9_-]{43}',keys[k]) for k in ('private_key','public_key')):raise SetupError('Unexpected official REALITY key response')
        private_json(keyfile,keys)
    if keys.get('uuid')!=cache['uuid']:raise SetupError('Pending REALITY keys belong to a different client; migration refused')
    target=dict(profile,mode='direct-reality',active=False)
    newcache=dict(cache,mode='direct-reality',**{k:keys[k] for k in ('private_key','public_key','short_id')})
    settings=decoded(original,'settings')
    desired=copy.deepcopy(original)
    spec=payload(state,target,newcache)
    for key in ('port','listen','protocol','remark','streamSettings'):desired[key]=spec[key]
    desired['disableFlow']=False
    # Client updates use the official clients API: 3.11.0 ignores clients in updateInbound.
    # Keep settings/IDs/limits and the tag exactly as read; the tag owns the relay rule.
    if not settings.get('clients'):raise SetupError('Managed inbound has no clients')
    return dict(original=original,desired=desired,temporary_tag=temporary_tag,original_cache=cache,cache=newcache,original_profile=profile,profile=target)


def compatible(current,migration):
    """Allow only the known intermediate states; never overwrite concurrent user edits."""
    before=migration['original'];after=migration['desired']
    if current.get('tag') not in (before['tag'],migration['temporary_tag']):return False
    for key in ('port','listen','protocol','remark','enable','expiryTime'):
        if current.get(key) not in (before.get(key),after.get(key)):return False
    for key in ('streamSettings','sniffing'):
        if decoded(current,key) not in (decoded(before,key),decoded(after,key)):return False
    left=copy.deepcopy(decoded(before,'settings'));right=copy.deepcopy(decoded(current,'settings'))
    originals={c['id']:c for c in left.pop('clients',[])}
    clients=right.pop('clients',[])
    if left!=right or len(clients)!=len(originals):return False
    seen=set()
    for client in clients:
        prior=originals.get(client.get('id'))
        if not prior or client.get('id') in seen or client.get('email')!=prior.get('email'):return False
        if client.get('flow','') not in (prior.get('flow',''),'xtls-rprx-vision'):return False
        seen.add(client['id'])
    # Limits/comments/shared metadata are read fresh for each flow update, including
    # rollback. updateInbound itself retains stored clients, so do not overwrite them.
    return True


def read(api,identity):
    matches=[r for r in api.inbounds() if r['id']==identity]
    if len(matches)!=1:raise SetupError('Migration inbound disappeared; recovery journal retained')
    return matches[0]


def set_flow(api,identity,email,flow):
    current=read(api,identity)
    clients=[c for c in decoded(current,'settings')['clients'] if c['email']==email]
    if len(clients)!=1:raise SetupError('Client membership changed during migration')
    escaped=urllib.parse.quote(email,safe='')
    record=api.request('/panel/api/clients/get/'+escaped)['client']
    if record.get('uuid',clients[0]['id'])!=clients[0]['id']:raise SetupError('Client UUID changed during migration; not overwritten')
    updated=dict(clients[0],flow=flow,limitHwid=record.get('limitHwid',0))
    for key in ('security','email','limitIp','totalGB','expiryTime','enable','tgId','subId','group','comment','reset','resetDay','resetWeekday','resetMax','trafficReset','trafficResetDay','clientHostRuleIds'):
        if key in record:updated[key]=record[key]
    if record.get('reverse'):updated['reverse']=json.loads(record['reverse'])
    api.request('/panel/api/clients/update/'+escaped+'?inboundIds='+str(identity),updated)


def apply(api,migration):
    identity=migration['original']['id']
    if not compatible(read(api,identity),migration):raise SetupError('Concurrent inbound edit detected before migration')
    # Upstream regenerates auto tags when a port changes, even if tag is supplied.
    # Move through a reserved custom tag, then restore the original tag with the new port.
    # Upstream rewrites its routing references on each rename; final relay tag stays stable.
    bridge=dict(migration['original'],tag=migration['temporary_tag'])
    api.request('/panel/api/inbounds/update/'+str(identity),bridge)
    api.request('/panel/api/inbounds/update/'+str(identity),migration['desired'])
    current=read(api,identity)
    if current.get('tag')!=migration['original']['tag']:raise SetupError('API changed the relay tag; migration will be rolled back')
    for client in decoded(migration['original'],'settings')['clients']:
        set_flow(api,identity,client['email'],'xtls-rprx-vision')
    return read(api,identity)


def restore(api,migration):
    identity=migration['original']['id'];current=read(api,identity)
    if not compatible(current,migration):raise SetupError('Concurrent inbound/client edit detected; migration journal retained')
    api.request('/panel/api/inbounds/update/'+str(identity),migration['original'])
    for client in decoded(migration['original'],'settings')['clients']:
        set_flow(api,identity,client['email'],client.get('flow',''))
    api.restart()
