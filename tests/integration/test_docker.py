"""Real Docker test. Never invokes host installer/sshd/UFW/ACME.

Uses isolated names, networks, high loopback ports and an ephemeral test CA.
This module tests the initial infrastructure. test_automation.py separately
creates VLESS inbounds and verifies real authenticated client transfers.
This is not a Cloudflare or VPS E2E test.
"""
import copy,hashlib,http.cookiejar,json,os,secrets,shutil,socket,sqlite3,subprocess,sys,time,urllib.parse,urllib.request,uuid
from pathlib import Path
import pytest
from conftest import APP
from state import write
from render import render,tls
from db import fingerprint

pytestmark=pytest.mark.skipif(os.environ.get('RUN_DOCKER_INTEGRATION')!='1',reason='Explicit opt-in required')


def run(args,**kw):
    p=subprocess.run(list(map(str,args)),text=True,capture_output=True,**kw)
    if p.returncode:
        # Docker commands used here never have the panel password in argv.
        raise RuntimeError('Command failed: '+str(args[0:3])+'\n'+p.stdout+p.stderr)
    return p.stdout

def docker(*args,**kw):return run(['docker',*args],**kw)

def freeport():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

@pytest.fixture(scope='module')
def live():
    docker('info')
    base=APP.parent/'integration-work'/uuid.uuid4().hex;base.mkdir(parents=True)
    root=base/'stack';root.mkdir();versions=json.loads((APP/'config/images.json').read_text())
    ident='vps-it-'+uuid.uuid4().hex[:10];ports=dict(http=freeport(),tls=freeport(),panel=freeport())
    d=dict(schema='1',role='outbound',domain='example.test',admin='vpsadmin',ssh_port='22',
           public_ip='192.0.2.10',email='test@example.test',subnet='172.29.163.0/24',
           title='Integration test site',text='No real certificate or public service',phase='configured',
           xui_image=versions['xui_image'],nginx_image=versions['nginx_image'])
    state=root/'state.json';write(state,d);render(state,root,APP/'templates')
    ca=base/'ca.pem';ca_key=base/'ca.key';key=root/'tls/privkey.pem';csr=base/'server.csr';cert=root/'tls/fullchain.pem'
    run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',ca_key,'-out',ca,'-days','1','-subj','/CN=Ephemeral integration CA'])
    run(['openssl','req','-newkey','rsa:2048','-nodes','-keyout',key,'-out',csr,'-subj','/CN=example.test'])
    ext=base/'extensions';ext.write_text('subjectAltName=DNS:example.test,DNS:exit.example.test\nextendedKeyUsage=serverAuth\n')
    run(['openssl','x509','-req','-in',csr,'-CA',ca,'-CAkey',ca_key,'-CAcreateserial','-out',cert,'-days','1','-extfile',ext])
    # Test key only. In production export_certificate installs root:101 mode 640.
    key.chmod(0o644);cert.chmod(0o644);tls(state,root,APP/'templates')
    generated=json.loads(docker('compose','--project-directory',root,'-f',root/'compose.yml','config','--format','json'))
    for service in generated['services'].values():
        service['container_name']=ident+'-'+service['container_name']
        service['healthcheck'].update(interval='1s',start_period='5s')
    # Managed test environment maps container root outside our host UID range.
    # Use the task UID and provide the one writable runtime config file explicitly.
    # Production VPS runs xui with its normal container root and cap_drop ALL.
    generated['services']['xui']['user']=str(os.getuid())+':'+str(os.getgid())
    # Current 3x-ui atomically writes a temporary config beside config.json,
    # so the entire runtime directory must be writable, not just the file.
    init=ident+'-init'
    docker('create','--name',init,'--network','none','--entrypoint','/bin/true',versions['xui_image'])
    try:docker('cp',init+':/app/bin',base/'bin')
    finally:docker('rm','-v',init)
    generated['services']['xui']['volumes'].append(dict(type='bind',source=str(base/'bin'),target='/app/bin'))
    generated['services']['xui']['ports']=[dict(target=2053,published=str(ports['panel']),host_ip='127.0.0.1',protocol='tcp')]
    generated['services']['nginx']['ports']=[dict(target=80,published=str(ports['http']),host_ip='127.0.0.1',protocol='tcp'),dict(target=8443,published=str(ports['tls']),host_ip='127.0.0.1',protocol='tcp')]
    generated['networks']['proxy']['name']=ident+'-network'
    # Let Docker choose an unused subnet in tests; production checks its explicit subnet.
    generated['networks']['proxy'].pop('ipam',None)
    compose=base/'compose.json';compose.write_text(json.dumps(generated))
    def dc(*args):return docker('compose','-p',ident,'--project-directory',root,'-f',compose,*args)
    ctx=dict(base=base,root=root,state=state,config=d,ident=ident,ports=ports,dc=dc,ca=ca,versions=versions,
             xui=generated['services']['xui']['container_name'],nginx=generated['services']['nginx']['container_name'],
             net=ident+'-network',password=secrets.token_hex(24),user='operator',checkpoints=[])
    ctx['compose_path']=compose
    try:yield ctx
    finally:
        debug=[]
        for name in (ctx['xui'],ctx['nginx'],ident+'-client',ident+'-target'):
            result=subprocess.run(['docker','logs','--tail','35',name],capture_output=True,text=True)
            text=result.stdout+result.stderr
            for value in (ctx.get('password',''),ctx.get('oldpassword','')):
                if value:text=text.replace(value,'<redacted>')
            debug.append(name+'\n'+text)
        results=APP/'test-results';results.mkdir(exist_ok=True)
        (results/'integration-debug.log').write_text('\n'.join(debug))
        for name in (ident+'-client',ident+'-curl',ident+'-target'):
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:dc('down','--remove-orphans','--timeout','1','--volumes')
        finally:
            report=results/'integration-results.json';report.write_text(json.dumps(ctx['checkpoints'],indent=2))
            shutil.rmtree(base)

def credentials(c,initial):
    # Execute production function with an isolated test ROOT. Password only in stdin.
    script='''set -Eeuo pipefail
ROOT=$1; APP=$2; XUI_IMAGE=$3; source "$APP/lib/xui.sh"
IFS= read -r PANEL_USER
IFS= read -r PANEL_PASSWORD
xui_cli_credentials "$4"
'''
    p=subprocess.run(['bash','-c',script,'test',str(c['root']),str(APP),c['versions']['xui_image'],initial],input=c['user']+'\n'+c['password']+'\n',text=True,capture_output=True)
    assert p.returncode==0, 'Real CLI bootstrap/reset failed: '+p.stdout+p.stderr
    assert c['password'] not in p.stdout+p.stderr

def wait(c):
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        rows=json.loads(docker('inspect',c['xui'],c['nginx']))
        if all(x['State'].get('Health',{}).get('Status')=='healthy' for x in rows):return
        if any(not x['State']['Running'] for x in rows):raise AssertionError('Container stopped during startup')
        time.sleep(2)
    raise AssertionError('Readiness timed out; inspect isolated test containers')

def api(c):
    jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    base='http://127.0.0.1:'+str(c['ports']['panel'])
    def request(path,data=None):
        headers={}
        if data is not None:headers={'Content-Type':'application/json','X-CSRF-Token':token}
        req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        return json.load(opener.open(req,timeout=15))
    token=request('/csrf-token')['obj']
    result=request('/login',dict(username=c['user'],password=c['password']))
    assert result['success'], 'Panel login failed (credentials suppressed)'
    token=request('/csrf-token')['obj']
    return request

def test_real_stack_tls_reset_backup_rerun(live):
    c=live;dc=c['dc'];root=c['root']
    def passed(name):c['checkpoints'].append(dict(status='PASSED',check=name))
    credentials(c,'initial');passed('Official CLI bootstrap before server start; bcrypt verification')
    dc('config','--quiet');dc('up','-d');wait(c);passed('Real 3x-ui and nginx startup and health checks')
    request=api(c);passed('HTTP login with chosen credentials and current CSRF mechanism')
    docker('exec',c['nginx'],'nginx','-t');passed('nginx configuration accepted by actual image')
    text=run(['curl','--noproxy','*','--fail','--silent','--show-error','--http2','--cacert',c['ca'],'--resolve','example.test:'+str(c['ports']['tls'])+':127.0.0.1','https://example.test:'+str(c['ports']['tls'])+'/', '-w','\n%{http_version}\n'])
    assert 'Integration test site' in text and text.rstrip().endswith('2');passed('CA-verified TLS, domain validation, ALPN and HTTP/2 site GET')
    # Real ACME webroot bytes, with no call to public ACME servers.
    probe=root/'acme/.well-known/acme-challenge/test';probe.write_text('acme-exact-bytes');probe.chmod(0o644)
    text=run(['curl','--noproxy','*','-fsS','http://127.0.0.1:'+str(c['ports']['http'])+'/.well-known/acme-challenge/test'])
    assert text=='acme-exact-bytes'
    secure=run(['curl','--noproxy','*','-fsS','--cacert',c['ca'],'--resolve','example.test:'+str(c['ports']['tls'])+':127.0.0.1','https://example.test:'+str(c['ports']['tls'])+'/.well-known/acme-challenge/test'])
    assert secure=='acme-exact-bytes';probe.unlink();passed('Real HTTP and CA-verified HTTPS ACME webroot serving; no certificate issuance claimed')
    dc('stop','xui')
    before=fingerprint(root/'db/x-ui.db');oldpass=c['password'];c['oldpassword']=oldpass;c['password']=secrets.token_hex(24)
    credentials(c,'reset');assert fingerprint(root/'db/x-ui.db')==before
    dc('start','xui');wait(c);api(c);passed('Official CLI credential reset, new HTTP login, unchanged non-user tables')
    c['password'],newpass=oldpass,c['password']
    with pytest.raises(AssertionError,match='Panel login failed'):api(c)
    c['password']=newpass;passed('Previous password rejected after reset')
    # Rerender and restart must retain custom site and panel clients.
    site=root/'site/index.html';site.write_text('Custom preserved site');render(c['state'],root,APP/'templates')
    assert site.read_text()=='Custom preserved site'
    dc('up','-d');wait(c);assert api(c)('/panel/api/inbounds/list')['obj']==[]
    passed('Repeated rendering/up preserves custom site, credentials and empty initial inbound list')
    # Production snapshot operation, then restore snapshot into another DB and compare.
    snapshot=c['base']/'snapshot.db'
    run([sys.executable,APP/'helpers/db.py','snapshot',root/'db/x-ui.db',snapshot]);dc('stop','xui')
    snapfinger=fingerprint(snapshot)
    with sqlite3.connect(root/'db/x-ui.db') as db:db.execute("INSERT INTO settings(key,value) VALUES ('integrationTemporary','temporary modification')")
    db.close()
    for name in ('x-ui.db-wal','x-ui.db-shm'):(root/'db'/name).unlink(missing_ok=True)
    shutil.copyfile(snapshot,root/'db/x-ui.db');assert fingerprint(root/'db/x-ui.db')==snapfinger
    dc('start','xui');wait(c);assert api(c)('/panel/api/inbounds/list')['obj']==[]
    passed('Consistent SQLite snapshot and recovery verified with live panel settings')
    for container in (c['xui'],c['nginx']):
        logs=docker('logs',container)
        assert oldpass not in logs and newpass not in logs
    passed('Chosen old/new passwords absent from normal Docker logs')
    rows=json.loads(docker('inspect',c['xui'],c['nginx']))
    panel=next(r for r in rows if r['Name'].lstrip('/')==c['xui'])
    assert panel['HostConfig']['PortBindings']['2053/tcp'][0]['HostIp']=='127.0.0.1'
    assert all('10000/tcp' not in r['HostConfig']['PortBindings'] for r in rows)
    assert not any(r['HostConfig']['Privileged'] or r['HostConfig']['CapAdd'] for r in rows)
    passed('Actual PortBindings: loopback panel, no public gRPC port, no added capabilities')

@pytest.mark.parametrize('role',['inbound','outbound'])
def test_compose_config_both_roles(tmp_path,config,role):
    config['role']=role
    p=tmp_path/'state.json';write(p,config);render(p,tmp_path/'stack',APP/'templates')
    docker('compose','--project-directory',tmp_path/'stack','-f',tmp_path/'stack/compose.yml','config','--quiet')
