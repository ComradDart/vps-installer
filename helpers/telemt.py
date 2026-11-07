#!/usr/bin/env python3
"""Optional native telemt: reuse the existing relay, never configure the peer."""
import copy,json,re,socket,subprocess,sys,time,tomllib
from pathlib import Path
from managed_inbound import decoded,owned_inbound
from state import validate,domain
from transport_profile import profile,relay_peer
from xui_api import Docker,SetupError,authenticated_api,private_json

MANAGER=Path('/opt/mtproxyl')
SERVICE='mtproxyl-telemt.service'
UNIT=Path('/etc/systemd/system')/SERVICE
REMARK='IN · telemt SOCKS'

def require(ok,message):
    if not ok:raise SetupError(message)

def native_config(d,domain):
    general=d.get('general',{});server=d.get('server',{});mask=d.get('censorship',{})
    require(general.get('use_middle_proxy') is False,'telemt Middle-End must be disabled')
    links=general.get('links',{})
    require(links.get('public_host')==domain and links.get('public_port',9443)==9443,'Unexpected public telemt endpoint')
    require(server.get('port')==9443 and not server.get('proxy_protocol',False),'Unexpected telemt listener')
    require(mask.get('mask') is True and mask.get('tls_domain')==domain and mask.get('mask_host')=='127.0.0.1' and mask.get('mask_port')==8443 and mask.get('tls_fetch_scope')=='local-mask','telemt must use the existing local nginx for masking')
    require(server.get('metrics_listen','').startswith('127.0.0.1:') and server.get('api',{}).get('listen','').startswith('127.0.0.1:'),'telemt management endpoints must stay on loopback')
    upstreams=d.get('upstreams',[])
    require(len(upstreams)==2,'Expected SOCKS upstream plus scoped local-mask only')
    common=[u for u in upstreams if not u.get('scopes')]
    local=[u for u in upstreams if u.get('scopes')=='local-mask']
    require(len(common)==1 and common[0].get('type')=='socks5' and common[0].get('address')=='127.0.0.1:1080' and not any(common[0].get(k) for k in ('username','password','interface')),'telemt payload must use only the local Xray SOCKS upstream')
    require(len(local)==1 and local[0].get('type')=='direct' and not local[0].get('interface'),'Direct upstream is permitted only for local-mask')
    require(bool(d.get('access',{}).get('users')),'telemt has no configured users; secrets were not regenerated')

def existing_native(state):
    cfg=MANAGER/'mtproxy/telemt.toml'
    if not MANAGER.exists():
        require(not UNIT.exists(),'Unrecognized existing telemt unit')
        return False
    require(cfg.is_file() and not cfg.is_symlink(),'Existing /opt/mtproxyl is incomplete; refusing to overwrite it')
    native_config(tomllib.loads(cfg.read_text()),state['domain'])
    settings=(MANAGER/'settings.conf').read_text()
    require(re.search(r"^ENGINE_BACKEND=['\"]binary['\"]$",settings,re.M) and re.search(r"^ENGINE_SERVICE_NAMING=['\"]standard['\"]$",settings,re.M),'Only the existing standard native MTProxyL service can be adopted')
    require(UNIT.is_file() and not UNIT.is_symlink() and 'ExecStart=/opt/mtproxyl/engine/mtproxyl-telemt run /opt/mtproxyl/mtproxy/telemt.toml' in UNIT.read_text(),'Unexpected native telemt service; no files were changed')
    return True

def context(root):
    state=json.loads((root/'state.json').read_text());validate(state)
    p=profile(root)
    require(state['role']=='inbound' and state['ssh_port'] not in ('1080','9443'),'telemt requires INBOUND and free TCP1080/9443')
    require(p and p['active'] and p['topology']=='relay','Configure and verify the existing INBOUND relay first')
    peer=relay_peer(json.loads((root/'secrets/relay.json').read_text()))
    require(domain(peer['address']) and peer['expected_ip']!=state['public_ip'],'Relay must use a public OUTBOUND domain and a different exit IP')
    return state,p,peer

def relay_route(template,main_tag,peer):
    rules=template.get('routing',{}).get('rules',[])
    matches=[(i,r) for i,r in enumerate(rules) if main_tag in r.get('inboundTag',[])]
    require(len(matches)==1,'Existing VLESS route is missing or ambiguous; no relay changes allowed')
    index,rule=matches[0];tag=rule.get('outboundTag')
    require(rule=={'type':'field','inboundTag':[main_tag],'outboundTag':tag},'Existing VLESS route must be unconditional')
    require(all(r.get('inboundTag')==['api'] and r.get('outboundTag')=='api' for r in rules[:index]),'A preceding route may bypass the existing relay')
    exits=[o for o in template.get('outbounds',[]) if o.get('tag')==tag]
    require(len(exits)==1 and exits[0].get('protocol')=='vless','Existing relay is not a single VLESS outbound')
    out=exits[0];stream=out.get('streamSettings',{});tls=stream.get('tlsSettings',{})
    nodes=out.get('settings',{}).get('vnext',[])
    require(len(nodes)==1 and nodes[0].get('address')==peer['address'] and nodes[0].get('port')==443,'Existing relay must use the saved OUTBOUND domain on TCP443')
    users=nodes[0].get('users',[])
    require(len(users)==1 and users[0].get('id')==peer['uuid'] and not users[0].get('flow') and users[0].get('encryption','none')=='none','Existing relay identity differs from saved peer; it was not overwritten')
    require(stream.get('network')=='grpc' and stream.get('security')=='tls' and stream.get('grpcSettings',{}).get('serviceName')=='vlessgrpc' and not stream.get('grpcSettings',{}).get('multiMode',False) and tls.get('serverName')==peer['address'] and tls.get('allowInsecure',False) is False and 'h2' in tls.get('alpn',[]),'Existing Cloudflare TLS/gRPC settings differ; no relay changes allowed')
    return index,tag

def socks_route(template,main_tag,socks_tag,peer):
    index,tag=relay_route(template,main_tag,peer)
    result=copy.deepcopy(template);rules=result['routing']['rules']
    wanted={'type':'field','inboundTag':[socks_tag],'outboundTag':tag}
    require(all(r==wanted for r in rules if socks_tag in r.get('inboundTag',[])),'Conflicting SOCKS route; existing configuration was preserved')
    rules[:]=[r for r in rules if r!=wanted]
    rules.insert(index+1,wanted)
    return result

def socks_inbound(rows,cache=None):
    rows=[r for r in rows if int(r['port'])==1080]
    require(len(rows)<=1,'Multiple inbounds use TCP1080')
    if not rows:return None
    row=rows[0];settings=decoded(row,'settings');stream=decoded(row,'streamSettings')
    require(row['protocol']=='mixed' and row['listen']=='0.0.0.0' and row['enable'] is True and settings.get('auth')=='noauth' and settings.get('udp') is False and not settings.get('accounts') and stream.get('security','none')=='none' and stream.get('network','tcp') in ('tcp','raw'),'TCP1080 belongs to a different inbound; it was not overwritten')
    if cache:require(row['id']==cache['inbound_id'] and row['tag']==cache['tag'],'Saved SOCKS identity changed; no inbound was overwritten')
    return row

def socks_compose(current):
    result=copy.deepcopy(current)
    require('xui' in result.get('services',{}),'Missing xui Compose service')
    for name,service in result['services'].items():
        for p in service.get('ports',[]):
            require(isinstance(p,dict),'Compose must be normalized before editing')
            require(str(p.get('published'))!='9443','TCP9443 must be owned by native telemt, not Docker; remove the old publication explicitly')
            if str(p.get('published'))=='1080' or p['target']==1080:
                require(name=='xui' and p.get('host_ip')=='127.0.0.1' and str(p.get('published'))=='1080' and p['target']==1080 and p.get('protocol','tcp')=='tcp','SOCKS must be published only as 127.0.0.1:1080:1080/tcp')
    ports=result['services']['xui'].setdefault('ports',[])
    if not any(p['target']==1080 for p in ports):ports.append(dict(target=1080,published='1080',host_ip='127.0.0.1',protocol='tcp'))
    return result

def free_port(address,port):
    with socket.socket() as s:
        try:s.bind((address,port))
        except OSError:raise SetupError('TCP'+str(port)+' is already occupied; nothing was replaced') from None

def transfer(peer,domain):
    # --noproxy '' is essential: '*' would silently bypass the SOCKS proxy.
    args=['curl','--fail','--silent','--show-error','--max-time','15','--noproxy','','--proxy','socks5h://127.0.0.1:1080','https://api4.ipify.org?format=json']
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=20)
        require(p.returncode==0 and json.loads(p.stdout).get('ip')==peer['expected_ip'],'SOCKS exit does not match OUTBOUND; telemt was not exposed')
        p=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','10','--noproxy','*','--resolve',domain+':8443:127.0.0.1','https://'+domain+':8443/','-o','/dev/null'],capture_output=True,timeout=15)
        require(p.returncode==0,'Existing nginx origin TLS check failed; no nginx settings were changed')
    except (ValueError,subprocess.TimeoutExpired):raise SetupError('Optional telemt transfer/TLS check failed; raw output suppressed') from None

def configure(root,check=False):
    state,p,peer=context(root);docker=Docker();api,_=authenticated_api(root,docker)
    cache=json.loads((root/'secrets/managed-xray.json').read_text())
    rows=api.inbounds();main=owned_inbound(rows,state,p,cache)
    require(main is not None,'Managed VLESS inbound not found; no new VLESS inbound was created')
    before=api.template();relay_route(before,main['tag'],peer)
    path=root/'secrets/telemt.json';saved=json.loads(path.read_text()) if path.exists() else None
    row=socks_inbound(rows,saved)
    project=docker.inspect(docker.container)['Config']['Labels']['com.docker.compose.project']
    def compose(*args,file=None):return docker.run('compose','-p',project,'--project-directory',root,'-f',file or root/'compose.yml',*args)
    current=json.loads(compose('config','--format','json'));candidate=socks_compose(current)
    if check:
        require(row is not None and candidate==current,'Missing loopback SOCKS inbound/publication')
        require(socks_route(before,main['tag'],row['tag'],peer)==before,'SOCKS route is missing or not first after the client relay rule')
    else:
        if candidate!=current:free_port('127.0.0.1',1080)
        if row is not None and saved is None:
            wanted={'type':'field','inboundTag':[row['tag']],'outboundTag':relay_route(before,main['tag'],peer)[1]}
            require(row.get('remark') in (REMARK,'IN telemt SOCKS') or wanted in before['routing']['rules'],'Existing TCP1080 is not recognized as telemt SOCKS')
        created=None;applied=None;changed=False;old=(root/'compose.yml').read_text()
        try:
            if row is None:
                row=api.request('/panel/api/inbounds/add',dict(remark=REMARK,tag='telemt-socks',enable=True,listen='0.0.0.0',port=1080,protocol='mixed',settings=json.dumps(dict(auth='noauth',udp=False)),streamSettings=json.dumps(dict(network='tcp',security='none')),sniffing=json.dumps(dict(enabled=False))))
                created=row['id'];socks_inbound([row])
            applied=socks_route(before,main['tag'],row['tag'],peer)
            if applied!=before:api.set_template(applied);api.restart()
            if candidate!=current:
                from render import atomic
                stage=root/'.telemt-compose.json';private_json(stage,candidate)
                try:
                    compose('config','--quiet',file=stage)
                    atomic(root/'compose.yml',stage.read_text(),0o600);changed=True
                    compose('up','-d','--no-deps','--pull','never','xui')
                finally:stage.unlink(missing_ok=True)
            deadline=time.monotonic()+20
            while True:
                try:
                    with socket.create_connection(('127.0.0.1',1080),timeout=1) as s:
                        s.sendall(b'\x05\x01\x00');require(s.recv(2)==b'\x05\x00','SOCKS5 handshake failed')
                    break
                except (OSError,SetupError):
                    if time.monotonic()>=deadline:raise SetupError('Local SOCKS did not become ready') from None
                    time.sleep(.5)
            transfer(peer,state['domain'])
            private_json(path,dict(inbound_id=row['id'],tag=row['tag']))
        except BaseException:
            try:
                if changed:
                    from render import atomic
                    atomic(root/'compose.yml',old,0o600);compose('up','-d','--no-deps','--pull','never','xui')
                if applied!=before and applied is not None:
                    require(api.template()==applied,'Concurrent routing edit; automatic rollback refused')
                    api.set_template(before)
                if created is not None:api.request('/panel/api/inbounds/del/'+str(created),{})
                if created is not None or applied!=before:api.restart()
            except Exception:print('Optional SOCKS rollback incomplete; use the backup. Existing VLESS identities were not edited.',file=sys.stderr)
            raise
    bindings=docker.inspect(docker.container)['HostConfig']['PortBindings']
    require(bindings.get('1080/tcp')==[dict(HostIp='127.0.0.1',HostPort='1080')],'Actual SOCKS Docker publication is not loopback-only')
    if check:transfer(peer,state['domain'])

def main():
    op,root=sys.argv[1],Path(sys.argv[2]);state=json.loads((root/'state.json').read_text());validate(state)
    if op=='preflight':
        context(root)
        docker=Docker();ids=docker.run('ps','-q').split()
        if ids:
            for row in json.loads(docker.run('inspect',*ids)):
                require(not any(b.get('HostPort')=='9443' for bindings in (row['HostConfig'].get('PortBindings') or {}).values() for b in bindings or []),'A Docker container already publishes 9443; it was not changed')
        exists=existing_native(state)
        if not exists:free_port('0.0.0.0',9443)
        print('existing' if exists else 'fresh')
    elif op=='configure':configure(root)
    elif op=='check':
        require(existing_native(state),'Native telemt config missing')
        require(subprocess.run(['systemctl','is-active','--quiet',SERVICE]).returncode==0,'Native telemt service is not active')
        configure(root,check=True);print('telemt: local SOCKS -> existing Cloudflare relay -> expected OUTBOUND IP; local origin TLS: OK')
    else:raise SetupError('Unknown telemt operation')

if __name__=='__main__':
    try:main()
    except (SetupError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as e:
        print('telemt: '+(str(e) if isinstance(e,SetupError) else 'Validation/operation failed; raw configuration suppressed to protect secrets'),file=sys.stderr);sys.exit(1)
