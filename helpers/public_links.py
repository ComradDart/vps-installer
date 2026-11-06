"""Native 3x-ui 3.11 Hosts API: external endpoint metadata, never the listener."""
import copy,json,re,urllib.parse
from pathlib import Path
from managed_inbound import decoded
from client_tools import public_key
from xui_api import SetupError,private_json


def host_payload(row,state):
    domain=state.get('PUBLIC_DOMAIN',state['domain'])
    stream=decoded(row,'streamSettings')
    result=dict(inboundIds=[row['id']],hosts=[domain+':443'],port=443,
                remark='vps-installer:public:'+str(row['id']),security='same')
    if stream.get('security')=='reality' and stream.get('network') in ('tcp','raw'):
        if row['port']!=443:raise SetupError('Managed REALITY port differs; preserved')
        reality=stream['realitySettings']
        if not reality.get('serverNames') or not reality.get('shortIds'):
            raise SetupError('Existing REALITY serverNames/shortIds missing; nothing regenerated')
        public_key(reality.get('privateKey','')) # Verify derivation before any write.
    else:raise SetupError('Unsupported managed transport; public links not guessed')
    return result


def export_patch(row,state):
    result=copy.deepcopy(row)
    result.update(shareAddrStrategy='custom',shareAddr=state.get('PUBLIC_DOMAIN',state['domain']))
    stream=decoded(result,'streamSettings')
    if stream.get('security')=='reality':
        reality=stream['realitySettings']
        reality.setdefault('settings',{})['publicKey']=public_key(reality.get('privateKey',''))
        result['streamSettings']=json.dumps(stream)
    return result


def validate_uri(uri,row,client,state):
    link=urllib.parse.urlsplit(uri);q=urllib.parse.parse_qs(link.query,keep_blank_values=True)
    domain=state.get('PUBLIC_DOMAIN',state['domain'])
    if link.scheme!='vless' or link.hostname!=domain or link.port!=443 or link.username!=client['id']:
        raise SetupError('Panel-generated VLESS address/port/identity is incorrect (link omitted)')
    def value(key):return q.get(key,[''])[0]
    stream=decoded(row,'streamSettings')
    if value('encryption') not in ('','none'):raise SetupError('Unexpected VLESS encryption in panel export')
    reality=stream['realitySettings'];names=reality['serverNames'];shorts=reality['shortIds']
    expected={'security':'reality','flow':client.get('flow',''),'pbk':public_key(reality['privateKey'])}
    if value('type') not in ('tcp','raw') or value('sni') not in names or value('sid') not in shorts:
        raise SetupError('Panel-generated REALITY transport/SNI/short ID differs from server')
    if any(value(k)!=v for k,v in expected.items()):
        raise SetupError('Panel-generated VLESS TLS/transport/key/flow is incorrect (link omitted)')


def verify(api,row,state):
    count=0
    for client in decoded(row,'settings').get('clients',[]):
        if not client.get('enable',True):continue
        sub_id=client.get('subId')
        path='/panel/api/clients/subLinks/'+urllib.parse.quote(sub_id,safe='') if sub_id else '/panel/api/inbounds/allLinks'
        links=api.request(path)
        if not isinstance(links,list):raise SetupError('Unexpected panel subscription-links response')
        owned=[uri for uri in links if isinstance(uri,str) and urllib.parse.urlsplit(uri).username==client['id']
               and urllib.parse.urlsplit(uri).hostname==state.get('PUBLIC_DOMAIN',state['domain'])]
        if not owned:raise SetupError('Panel did not export the managed public endpoint')
        for uri in owned:validate_uri(uri,row,client,state)
        count+=1
    return count


def subscription_plan(api,root,state):
    settings=api.request('/panel/api/setting/all',{})
    if settings.get('subCertFile') or settings.get('subKeyFile'):
        raise SetupError('Existing subscription TLS configuration requires review; preserved')
    after=copy.deepcopy(settings);locations=[]
    port=int(settings['subPort'])
    if port<1 or port>65535:raise SetupError('Invalid existing subscription port')
    for enable,path_key,uri_key in [('subEnable','subPath','subURI'),('subJsonEnable','subJsonPath','subJsonURI'),('subClashEnable','subClashPath','subClashURI')]:
        if not settings.get(enable):continue
        path=settings[path_key]
        if not re.fullmatch(r'/[A-Za-z0-9/_-]+/',path) or path in ('/','/panel/'):
            raise SetupError('Custom subscription path requires review; preserved')
        after[uri_key]='https://'+state.get('PUBLIC_DOMAIN',state['domain'])+path
        locations.append(f'    location ^~ {path} {{\n        proxy_pass http://xui:{port};\n        proxy_set_header Host {state["domain"]};\n        proxy_set_header X-Forwarded-Proto https;\n    }}\n')
    tls=root/'conf.d/tls.conf';include='    include /etc/nginx/conf.d/vps-subscriptions.inc;'
    before=tls.read_text();text=before
    if include not in text:
        pattern=r'(^[ \t]*server_name[ \t]+'+re.escape(state['domain'])+r';[ \t]*$)'
        if len(re.findall(pattern,text,re.M))!=1:raise SetupError('Cannot identify managed nginx site for subscription paths')
        text=re.sub(pattern,lambda m:m[0]+'\n'+include,text,count=1,flags=re.M)
    snippet=root/'conf.d/vps-subscriptions.inc'
    return dict(before_settings=settings,after_settings=after,
                files=[dict(path=str(tls),before=before,after=text),
                       dict(path=str(snippet),before=snippet.read_text() if snippet.exists() else None,after=''.join(locations))])


def repair(api,root,state,profile,docker=None):
    if state['role']!='inbound' or profile['mode']!='direct-reality':
        raise SetupError('Public-link repair is only for INBOUND REALITY; OUTBOUND preserved')
    root=Path(root);journal=root/'public-links-transaction.json'
    # Recover only native export metadata; no direct DB changes or Xray restart.
    def restore(data):
        subscriptions=data.get('subscriptions')
        if subscriptions:
            from render import atomic
            for file in subscriptions['files']:
                if file['before'] is None:Path(file['path']).unlink(missing_ok=True)
                else:atomic(Path(file['path']),file['before'],0o644)
            api.request('/panel/api/setting/update',subscriptions['before_settings'])
            docker.run('exec',docker.nginx,'nginx','-t');docker.run('exec',docker.nginx,'nginx','-s','reload')
        for change in reversed(data['changes']):
            group=change['group']
            if change['before_host'] is None:
                if any(h.get('groupId')==group for h in api.request('/panel/api/hosts/list')):
                    api.request('/panel/api/hosts/del/'+group,{})
            else:api.request('/panel/api/hosts/update/'+group,change['before_host'])
            api.request('/panel/api/inbounds/update/'+str(change['before_row']['id']),change['before_row'])
        journal.unlink(missing_ok=True)
    if journal.exists():restore(json.loads(journal.read_text()))
    cache_path=root/'secrets/managed-xray.json'
    if not cache_path.exists():raise SetupError('Managed inbound identity missing; no arbitrary inbound modified')
    cache=json.loads(cache_path.read_text());rows=api.inbounds()
    owned=[r for r in rows if r['id']==cache.get('inbound_id')]
    if not owned:owned=[r for r in rows if r.get('remark')=='vps-installer:'+state['role']+':'+profile['mode']]
    if len(owned)!=1 or owned[0]['protocol']!='vless':raise SetupError('Expected one managed VLESS inbound; nothing guessed')
    row=owned[0];desired=host_payload(row,state);tag=desired['remark']
    hosts=api.request('/panel/api/hosts/list')
    if not isinstance(hosts,list):raise SetupError('Unexpected native Hosts API response')
    group='vpspublic'+str(row['id'])
    own=[h for h in hosts if h.get('groupId')==group]
    if len(own)>1:raise SetupError('Ambiguous managed public Host group')
    if own and (own[0].get('inboundIds')!=[row['id']] or own[0].get('remark')!=tag):
        raise SetupError('Managed Host group was changed by hand; preserved')
    if any(row['id'] in h.get('inboundIds',[]) and h.get('groupId')!=group and not h.get('isDisabled') for h in hosts):
        raise SetupError('Custom Host rules already exist on this inbound; preserved, no extra endpoint added')
    desired['groupId']=group
    after=export_patch(row,state)
    host_changed=not own or any(own[0].get(k)!=v for k,v in desired.items())
    row_changed=(after['shareAddrStrategy'],after['shareAddr'],decoded(after,'streamSettings'),decoded(after,'settings'))!=(row.get('shareAddrStrategy'),row.get('shareAddr'),decoded(row,'streamSettings'),decoded(row,'settings'))
    subscriptions=subscription_plan(api,root,state) if docker else None
    subscription_changed=subscriptions and (subscriptions['before_settings']!=subscriptions['after_settings'] or any(f['before']!=f['after'] for f in subscriptions['files']))
    if not row_changed and not host_changed and not subscription_changed:
        return verify(api,row,state)
    data={'changes':[dict(group=group,before_host=own[0] if own else None,before_row=row)]}
    if subscription_changed:data['subscriptions']=subscriptions
    private_json(journal,data)
    # Retain a root-only reviewable snapshot after successful repair too.
    private_json(root/'secrets/public-links-before.json',data)
    try:
        if row_changed:api.request('/panel/api/inbounds/update/'+str(row['id']),after)
        if host_changed:api.request('/panel/api/hosts/'+('update/'+group if own else 'add'),desired)
        if subscription_changed:
            from render import atomic
            for file in subscriptions['files']:atomic(Path(file['path']),file['after'],0o644)
            docker.run('exec',docker.nginx,'nginx','-t')
            api.request('/panel/api/setting/update',subscriptions['after_settings'])
            docker.run('exec',docker.nginx,'nginx','-s','reload')
        actual=next(r for r in api.inbounds() if r['id']==row['id'])
        count=verify(api,actual,state)
        journal.unlink()
        return count
    except BaseException:
        restore(data)
        raise
