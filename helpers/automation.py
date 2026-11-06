#!/usr/bin/env python3
"""Transactional API + nginx/Compose deployment; latest image, reviewed runtime API."""
import argparse,copy,hashlib,ipaddress,json,os,re,shutil,signal,subprocess,sys,tempfile,time,urllib.parse
from pathlib import Path
from state import validate
from xui_api import Api,Docker,SetupError,authenticated_api,private_json,private_text,verify_login
from transport_profile import profile,validate_profile,parse_peer,client_config,client_uri
from managed_inbound import SERVICE,decoded,marker,planned_cache,ensure,validate_existing,peer_for_client,relay_template
from xray_probe import probe

GRPC=(Path(__file__).resolve().parents[1]/'templates/grpc.inc').read_text()
INCLUDE='    include /etc/nginx/conf.d/vps-grpc.inc;'

def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def cloudflare_dns(domain,config):
    from dns import resolve
    answers=resolve(domain);addresses=answers['A']|answers['AAAA']
    ranges=[ipaddress.ip_network(x) for x in json.loads(Path(config).read_text())['networks']]
    if not answers['A'] or any(not any(ipaddress.ip_address(a) in n for n in ranges if n.version==ipaddress.ip_address(a).version) for a in addresses):raise SetupError('Cloudflare DNS is not Proxied (public A/AAAA are not all Cloudflare ranges). Enable the orange cloud, Full (strict), Network -> gRPC, and HTTP/2.')
    return True

def candidate_compose(current,mode,public_port=443,bind='0.0.0.0'):
    c=copy.deepcopy(current)
    if not all(k in c.get('services',{}) for k in ('xui','nginx')):raise SetupError('Expected xui and nginx Compose services')
    owner='xui' if mode=='direct-reality' else 'nginx'
    for name in ('xui','nginx'):
        s=c['services'][name];ports=[]
        if s.get('network_mode')=='host' or s.get('privileged') or s.get('cap_add'):raise SetupError('Unsafe existing Docker privileges/network mode')
        for p in s.get('ports',[]):
            if not isinstance(p,dict):raise SetupError('Compose must be normalized with docker compose config')
            protocol=p.get('protocol','tcp');published=str(p.get('published',''));target=int(p['target'])
            if protocol=='udp' and (published in ('80','443') or target in (80,443)):raise SetupError('Unexpected UDP 80/443 publication; existing stack was not modified')
            if protocol=='tcp' and (published==str(public_port) or target==10000):continue
            if name=='xui' and target==2053 and (p.get('host_ip')!='127.0.0.1' or published!='2053'):
                # Nonstandard high loopback panel ports are allowed in isolated tests;
                # every public panel publication is rejected.
                if p.get('host_ip')!='127.0.0.1':raise SetupError('Panel must be published only on loopback')
            ports.append(p)
        s['ports']=ports
    c['services'][owner]['ports'].append({'target':443 if owner=='xui' else 8443,'published':str(public_port),'host_ip':bind,'protocol':'tcp'})
    return c

def candidate_tls(text,domain,mode):
    if mode=='direct-reality':return text.replace(INCLUDE+'\n','')
    if INCLUDE in text:return text
    pattern=r'(^[ \t]*server_name[ \t]+'+re.escape(domain)+r';[ \t]*$)'
    if len(re.findall(pattern,text,re.M))!=1:raise SetupError('Cannot identify exactly one managed TLS server; custom nginx config was preserved')
    return re.sub(pattern,lambda m:m[0]+'\n'+INCLUDE,text,count=1,flags=re.M)

class Engine:
    def __init__(self,root,api,docker,version='3.11.0',compose_path=None,project=None,public_port=443,bind='0.0.0.0',test_url=None,ca_file=None):
        self.root=Path(root);self.api=api;self.docker=docker;self.version=version
        self.state=json.loads((self.root/'state.json').read_text());validate(self.state)
        self.profile=profile(self.root)
        if not self.profile:raise SetupError('Select a transport first')
        self.compose_path=Path(compose_path or self.root/'compose.yml')
        info=docker.inspect(docker.container);self.project=project or info['Config']['Labels']['com.docker.compose.project']
        self.public_port=public_port;self.bind=bind;self.test_url=test_url or 'https://api4.ipify.org?format=json';self.ca_file=ca_file
        self.transaction=self.root/'.transport-transaction';self.changed=False
    def compose(self,*args,file=None):return self.docker.run('compose','-p',self.project,'--project-directory',self.root,'-f',file or self.compose_path,*args)
    def current_compose(self):return json.loads(self.compose('config','--format','json'))
    def nginx_test(self,conf):
        image=self.docker.inspect(self.docker.nginx)['Config']['Image']
        return self.docker.run('run','--rm','--network',self.docker.network,'--user','101:101','--cap-drop','ALL','--security-opt','no-new-privileges:true','--sysctl','net.ipv4.ip_unprivileged_port_start=0',
            '-v',str(self.root/'nginx.conf')+':/etc/nginx/nginx.conf:ro','-v',str(conf)+':/etc/nginx/conf.d:ro','-v',str(self.root/'tls')+':/etc/nginx/tls:ro',
            '--tmpfs','/tmp:uid=101,gid=101,mode=0700','--tmpfs','/var/cache/nginx:uid=101,gid=101,mode=0700','--entrypoint','nginx',image,'-t')
    def prepare(self,original_profile=None):
        if self.transaction.exists():raise SetupError('Interrupted transport transaction found; recovery must finish first')
        self.transaction.mkdir(mode=0o700)
        try:
            current=self.current_compose();proposed=candidate_compose(current,self.profile['mode'],self.public_port,self.bind)
            stage=self.transaction/'candidate';stage.mkdir(mode=0o700)
            shutil.copytree(self.root/'conf.d',stage/'conf.d')
            tls=stage/'conf.d/tls.conf'
            tls.write_text(candidate_tls(tls.read_text(),self.state['domain'],self.profile['mode']));tls.chmod(0o644)
            if self.profile['mode']!='direct-reality':(stage/'conf.d/vps-grpc.inc').write_text(GRPC);(stage/'conf.d/vps-grpc.inc').chmod(0o644)
            private_json(stage/'compose.json',proposed)
            self.compose('config','--quiet',file=stage/'compose.json');self.nginx_test(stage/'conf.d')
            # The journal contains secrets from Xray settings; it is always root-only.
            journal={'status':'prepared','original_template':None,'applied_template_hash':None,'attempted_create':False,'created_id':None,'files':{},'had_profile':True,'original_profile':original_profile or self.profile,'owner_changed':self.profile['mode']=='direct-reality' and not self.profile['active']}
            for label,path in [('compose',self.compose_path),('tls',self.root/'conf.d/tls.conf'),('include',self.root/'conf.d/vps-grpc.inc')]:
                journal['files'][label]={'path':str(path),'text':path.read_text() if path.exists() else None,'applied_hash':None}
            private_json(self.transaction/'journal.json',journal)
            return journal,stage
        except BaseException:
            shutil.rmtree(self.transaction,ignore_errors=True);raise
    def save_journal(self,journal):private_json(self.transaction/'journal.json',journal)
    def apply_files(self,journal,stage):
        files={'compose':stage/'compose.json','tls':stage/'conf.d/tls.conf'}
        if self.profile['mode']!='direct-reality':files['include']=stage/'conf.d/vps-grpc.inc'
        for label,source in files.items():
            data=source.read_text();path=Path(journal['files'][label]['path'])
            journal['files'][label]['applied_hash']=hashlib.sha256(data.encode()).hexdigest();self.save_journal(journal)
            # Config directories are mounted as directories, so atomic replacement is visible.
            from render import atomic
            atomic(path,data,0o600 if label=='compose' else 0o644)
        journal['status']='files-applied';self.save_journal(journal)
        if journal['owner_changed']:self.compose('stop','nginx')
        self.compose('up','-d','--pull','never')
        self.docker.run('exec',self.docker.nginx,'nginx','-t');self.docker.run('exec',self.docker.nginx,'nginx','-s','reload')
    def wait_healthy(self):
        deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            rows=[self.docker.inspect(name) for name in (self.docker.container,self.docker.nginx)]
            if all(r['State'].get('Health',{}).get('Status')=='healthy' for r in rows):return
            if any(not r['State']['Running'] or r['State'].get('Health',{}).get('Status')=='unhealthy' for r in rows):raise SetupError('Transport containers failed their health checks')
            time.sleep(1)
        raise SetupError('Transport container health readiness timed out')
    def actual_bindings(self):
        owners=[]
        for name in (self.docker.container,self.docker.nginx):
            row=self.docker.inspect(name)
            for target,bindings in (row['HostConfig'].get('PortBindings') or {}).items():
                for binding in bindings or []:
                    if target=='10000/tcp':raise SetupError('Internal gRPC port is unexpectedly published')
                    if target.endswith('/udp') and binding['HostPort'] in ('80','443'):raise SetupError('Unexpected UDP publication')
                    if target=='2053/tcp' and binding['HostIp']!='127.0.0.1':raise SetupError('Panel is not loopback-only')
                    if binding['HostPort']==str(self.public_port) and target.endswith('/tcp'):owners.append(name)
        wanted=self.docker.container if self.profile['mode']=='direct-reality' else self.docker.nginx
        if owners!=[wanted]:raise SetupError('Public TLS port is not owned exclusively by the selected service')
    def verify_internal(self,cache):
        direct=self.profile['mode']=='direct-reality'
        peer=peer_for_client(self.state,self.profile,cache,'xui' if direct else 'nginx',443 if direct else 8443)
        expected=self.state['public_ip']
        if self.profile['topology']=='relay':expected=json.loads((self.root/'secrets/relay.json').read_text())['expected_ip']
        return probe(self.docker,self.root,peer,expected,self.test_url,self.ca_file)
    def verify_public(self,cache):
        if self.profile['mode']=='cloudflare-grpc':cloudflare_dns(self.state['domain'],Path(__file__).resolve().parents[1]/'config/cloudflare-networks.json')
        peer=peer_for_client(self.state,self.profile,cache,port=self.public_port)
        expected=self.state['public_ip'] if self.profile['topology']=='standalone' else json.loads((self.root/'secrets/relay.json').read_text())['expected_ip']
        return probe(self.docker,self.root,peer,expected,self.test_url,self.ca_file)
    def recover(self):
        path=self.transaction/'journal.json'
        if not path.exists():
            if self.transaction.exists():shutil.rmtree(self.transaction)
            return
        journal=json.loads(path.read_text());cache_path=self.root/'secrets/managed-xray.json'
        cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
        if journal.get('migration'):
            from reality_migration import restore
            restore(self.api,journal['migration'])
            private_json(cache_path,journal['migration']['original_cache'])
        # Restore routing first: inbound deletion itself removes tag references upstream.
        original=journal.get('original_template')
        if original is not None and journal.get('applied_template_hash'):
            current=self.api.template()
            if fingerprint(current)==journal['applied_template_hash']:self.api.set_template(original)
            elif fingerprint(current)!=fingerprint(original):raise SetupError('Concurrent Xray template edit detected; recovery journal preserved for manual review')
        if journal.get('attempted_create') and cache.get('uuid'):
            old_ids=journal.get('original_ids',[])
            for row in self.api.inbounds():
                if row['id'] not in old_ids and row.get('remark')==marker(self.state,self.profile) and any(c.get('id')==cache['uuid'] for c in decoded(row,'settings').get('clients',[])):
                    self.api.request('/panel/api/inbounds/del/'+str(row['id']),{})
            # 3.11.0 detaches, rather than deletes, a client when its inbound is removed.
            # Remove only our newly created, now unattached identity, never an old/shared client.
            if cache.get('email') not in journal.get('original_client_emails',[]):
                candidates=[c for c in self.api.clients() if c['email']==cache.get('email') and c['uuid']==cache['uuid']]
                if len(candidates)==1:
                    escaped=urllib.parse.quote(cache['email'],safe='')
                    details=self.api.request('/panel/api/clients/get/'+escaped)
                    if details.get('client',{}).get('uuid')==cache['uuid'] and not details.get('inboundIds'):
                        self.api.request('/panel/api/clients/del/'+escaped,{})
        for data in journal.get('files',{}).values():
            target=Path(data['path']);applied=data.get('applied_hash')
            if not applied:continue
            if applied and target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=applied:
                original_bytes=(data['text'] or '').encode()
                if hashlib.sha256(target.read_bytes()).hexdigest()!=hashlib.sha256(original_bytes).hexdigest():raise SetupError('Concurrent nginx/Compose edit detected; recovery journal retained')
            if data['text'] is None:target.unlink(missing_ok=True)
            else:
                from render import atomic
                atomic(target,data['text'],0o600 if target==self.compose_path else 0o644)
        private_json(self.root/'transport.json',journal['original_profile'])
        if journal.get('owner_changed'):self.docker.run('stop',self.docker.container)
        self.compose('up','-d','--pull','never')
        self.docker.run('exec',self.docker.nginx,'nginx','-t');self.docker.run('exec',self.docker.nginx,'nginx','-s','reload')
        shutil.rmtree(self.transaction)
    def provision(self,public=True,migrate=False):
        self.recover()
        self.profile=profile(self.root)
        cache=planned_cache(self.root,self.api,self.state,self.profile)
        migration=None
        if migrate:
            from reality_migration import plan
            migration=plan(self.root,self.api,self.state,self.profile,cache)
            if migration:
                self.profile=migration['profile'];cache=migration['cache']
        if self.profile['mode']=='direct-reality' and not self.ca_file:
            from dns import resolve,check_answers
            try:check_answers(self.state['public_ip'],resolve(self.state['domain']))
            except ValueError:raise SetupError('REALITY requires DNS-only A pointing at this VPS, without origin AAAA. Cloudflare Proxy must be off for the INBOUND hostname.') from None
        if self.profile['topology']=='relay':
            remote=json.loads((self.root/'secrets/relay.json').read_text())
            if remote['expected_ip']==self.state['public_ip']:raise SetupError('OUTBOUND exit IPv4 must differ from this node to verify the relay route')
            # Complete authenticated data transfer is required BEFORE local routing writes.
            probe(self.docker,self.root,remote,remote['expected_ip'],self.test_url,self.ca_file)
        journal,stage=self.prepare(original_profile=migration['original_profile'] if migration else None)
        try:
            journal['original_ids']=[r['id'] for r in self.api.inbounds()]
            journal['original_client_emails']=[c['email'] for c in self.api.clients()]
            journal['attempted_create']=not any(r.get('remark')==marker(self.state,self.profile) for r in self.api.inbounds());self.save_journal(journal)
            if migration:
                journal['original_profile']=migration['original_profile']
                journal['migration']=migration
                journal['attempted_create']=False
                self.save_journal(journal)
                from reality_migration import apply
                row=apply(self.api,migration);created=False
                validate_existing(row,self.state,self.profile,cache)
            else:row,created=ensure(self.api,self.state,self.profile,cache)
            journal['created_id']=row['id'] if created else None;self.save_journal(journal)
            cache['inbound_id']=row['id'];private_json(self.root/'secrets/managed-xray.json',cache)
            changed=created or migration is not None
            if self.profile['topology']=='relay':
                before=self.api.template();after=relay_template(before,row['tag'],remote)
                journal['original_template']=before
                if fingerprint(before)!=fingerprint(after):
                    journal['applied_template_hash']=fingerprint(after);self.save_journal(journal)
                    self.api.set_template(after);changed=True
            if changed:self.api.restart()
            # REALITY's target is checked through the Docker network, with SNI/TLS verification.
            if self.profile['mode']=='direct-reality':
                command=['exec',self.docker.container,'curl','--noproxy','*','--fail','--silent','--show-error','--http2','--max-time','10','--connect-to',self.state['domain']+':8443:nginx:8443']
                if self.ca_file:command+=['--cacert','/test-ca.pem']
                self.docker.run(*command,'https://'+self.state['domain']+':8443/')
                # The internal listener works before public 443 moves away from nginx.
                self.verify_internal(cache)
            self.apply_files(journal,stage)
            self.wait_healthy();self.actual_bindings();self.verify_internal(cache)
            if public:self.verify_public(cache)
            validate_existing(next(r for r in self.api.inbounds() if r['id']==row['id']),self.state,self.profile,cache)
            active=dict(self.profile,active=True);private_json(self.root/'transport.json',active);self.profile=active
            exported=peer_for_client(self.state,active,cache,port=self.public_port)
            private_text(self.root/'clients/vless.txt',client_uri(exported,self.state['role']+'-'+self.state['domain'])+'\n')
            private_json(self.root/'clients/xray-client.json',client_config(exported,10808))
            private_json(self.root/'automation-report.json',{'status':'PASSED' if public else 'ORIGIN_PASSED','api_version':self.version,'inbound_id':row['id'],'mode':active['mode'],'topology':active['topology'],'origin_client':'PASSED','external_client':'PASSED' if public else 'NOT RUN','cloudflare_e2e':'PASSED' if public and active['mode']=='cloudflare-grpc' else 'NOT RUN','verified_at':int(time.time())})
            shutil.rmtree(self.transaction)
            return {'inbound_id':row['id'],'created':created,'origin_client':'PASSED','external_client':'PASSED' if public else 'NOT RUN'}
        except BaseException as error:
            try:self.recover()
            except Exception as recovery_error:
                reason=str(error) if isinstance(error,SetupError) else type(error).__name__
                recovery=str(recovery_error) if isinstance(recovery_error,SetupError) else type(recovery_error).__name__
                raise SetupError('Transport setup failed: '+reason+'. Rollback needs review: '+recovery+'. Recovery journal retained at '+str(self.transaction)) from None
            raise error


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('configure','check','recover','profile-init','import-peer','login-check','version-check','cf-check','profile-info','migrate-inbound-reality'))
    parser.add_argument('root');parser.add_argument('--mode');parser.add_argument('--topology',default='standalone');parser.add_argument('--base',default='http://127.0.0.1:2053');args=parser.parse_args();root=Path(args.root)
    if args.command=='profile-info':
        value=profile(root);print('active' if value and value['active'] else 'pending' if value else 'missing');return
    if args.command=='profile-init':
        value=validate_profile({'schema':1,'mode':args.mode,'topology':args.topology,'active':False})
        if (root/'transport.json').exists():raise SetupError('Transport profile already exists; not overwritten')
        private_json(root/'transport.json',value);return
    if args.command=='import-peer':
        uri,expected=sys.stdin.read().splitlines();private_json(root/'secrets/relay.json',parse_peer(uri,expected));return
    if args.command=='login-check':
        user,password=sys.stdin.read().splitlines();verify_login(args.base,user,password);return
    if args.command=='cf-check':
        state=json.loads((root/'state.json').read_text());cloudflare_dns(state['domain'],Path(__file__).resolve().parents[1]/'config/cloudflare-networks.json');return
    docker=Docker()
    if args.command=='version-check':docker.version();return
    api,version=authenticated_api(root,docker,args.base);engine=Engine(root,api,docker,version)
    if args.command=='recover':engine.recover();return
    if args.command=='check':
        cache_path=root/'secrets/managed-xray.json'
        if not cache_path.exists():raise SetupError('Managed client identity is missing; run --configure-xray to recover it through the API')
        cache=json.loads(cache_path.read_text())
        rows=api.inbounds();row=next((r for r in rows if r.get('remark')==marker(engine.state,engine.profile)),None)
        if row is None:raise SetupError('Managed inbound is missing')
        validate_existing(row,engine.state,engine.profile,cache);engine.actual_bindings();engine.verify_internal(cache);engine.verify_public(cache)
        print('Xray API, inbound, Docker publication and real authenticated client transfer: PASSED');return
    result=engine.provision(public=True,migrate=args.command=='migrate-inbound-reality');print('Automatic Xray configuration verified; inbound id '+str(result['inbound_id'])+'. Client secrets saved under '+str(root/'clients'))

if __name__=='__main__':
    def interrupted(signum,frame):raise SetupError('Transport configuration interrupted')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    try:main()
    except Exception as error:
        # Never print request bodies, credentials, UUIDs or raw upstream error output.
        message=str(error) if isinstance(error,SetupError) else type(error).__name__+' (details suppressed to protect client credentials)'
        print('Xray automation failed: '+message,file=sys.stderr);sys.exit(1)
