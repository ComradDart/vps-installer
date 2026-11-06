import hashlib,importlib,json,os,signal,sqlite3,subprocess,sys,tarfile,time
from pathlib import Path
import pytest
from conftest import APP,bash
from state import domain,validate,write
from render import render,tls
import publications

@pytest.mark.parametrize('name',['example.com','inbound.example.com','xn--e1afmkfd.xn--p1ai','a.co'])
def test_domain_good(name):assert domain(name)
@pytest.mark.parametrize('name',['','localhost','https://example.com','a..com','-bad.com','bad-.com','a.com;id','a.com\n','127.0.0.1','*.example.com','a'*64+'.com','a.com.'])
def test_domain_bad(name):assert not domain(name)
@pytest.mark.parametrize('port',['1','22','65535'])
def test_ports_good(port):assert bash('valid_port "$1"',port).returncode==0
@pytest.mark.parametrize('port',['0','65536','-1','22/tcp','22;id','00022','abc',''])
def test_ports_bad(port):assert bash('valid_port "$1"',port).returncode!=0
@pytest.mark.parametrize('value',['a'*16,'Z!@#$%^&*() '+('a'*20),'f'*72])
def test_password_valid(value):assert bash('valid_password "$1"',value).returncode==0
@pytest.mark.parametrize('value',['short','a'*73,'a'*15+'\n','пароль'*8,'a'*16+':'])
def test_password_invalid(value):assert bash('valid_password "$1"',value).returncode!=0

def test_password_generator_is_random():
    r=bash('for i in {1..100}; do generate_password; done');assert r.returncode==0
    vals=r.stdout.splitlines();assert len(vals)==len(set(vals))==100
    assert all(len(x)==48 and all(c in '0123456789abcdef' for c in x) for x in vals)

def test_key_validation_and_cleanup(tmp_path):
    key=tmp_path/'key'
    subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
    r=bash('TMPDIR_TASK=$1; valid_key_file "$2"',tmp_path,key.with_suffix('.pub'));assert r.returncode==0
    assert not list(tmp_path.glob('key.*??????'))
    invalid=tmp_path/'bad';invalid.write_text('ssh-ed25519 invalid-data\n')
    assert bash('TMPDIR_TASK=$1; valid_key_file "$2"',tmp_path,invalid).returncode!=0
    assert bash('TMPDIR_TASK=$1; valid_key_file "$2"',tmp_path,key).returncode!=0
    invalid.write_text('command="/bin/false" '+key.with_suffix('.pub').read_text())
    assert bash('TMPDIR_TASK=$1; valid_key_file "$2"',tmp_path,invalid).returncode!=0
    assert not list(tmp_path.glob('key.??????'))

def test_all_key_lines_must_be_valid(tmp_path):
    key=tmp_path/'ed';subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
    pub=key.with_suffix('.pub');pub.write_text(pub.read_text()+'ssh-ed25519 broken\n')
    assert bash('TMPDIR_TASK=$1; valid_key_file "$2"',tmp_path,pub).returncode!=0

def test_state_atomic_no_execution(tmp_path,config):
    p=tmp_path/'state.json';config['title']='$(touch /tmp/not-an-actual-command)';write(p,config)
    assert p.stat().st_mode&0o777==0o600
    for i in range(5):write(p,config)
    assert json.loads(p.read_text())==config and not list(tmp_path.glob('.state-*'))
    config['ssh_port']='$(id)'
    with pytest.raises(AssertionError):write(p,config)
    assert json.loads(p.read_text())['ssh_port']=='22'

def test_unknown_secret_fields_rejected(config):
    config['password']='secret'
    with pytest.raises(AssertionError):validate(config)

@pytest.mark.parametrize('role',['inbound','outbound'])
def test_render_and_rerun_preserve_data(tmp_path,config,role):
    config['role']=role
    p=tmp_path/'state.json';write(p,config);root=tmp_path/'stack'
    render(p,root,APP/'templates');site=root/'site/index.html';site.write_text('Custom site')
    db=root/'db/x-ui.db';db.write_bytes(b'kept database bytes')
    first=(root/'compose.yml').read_bytes();render(p,root,APP/'templates')
    assert site.read_text()=='Custom site' and db.read_bytes()==b'kept database bytes'
    assert first==(root/'compose.yml').read_bytes()
    assert '2053:2053/tcp' in first.decode() and '/udp' not in first.decode()
    assert 'host' not in first.decode().replace('hostname','')
    assert not (root/'conf.d/tls.conf').exists()
    with pytest.raises(AssertionError):tls(p,root,APP/'templates')
    assert not list(root.rglob('.render-*'))

def test_site_html_escaping(tmp_path,config):
    config['title']='<script>bad()</script>';p=tmp_path/'state.json';write(p,config)
    render(p,tmp_path/'stack',APP/'templates')
    text=(tmp_path/'stack/site/index.html').read_text();assert '<script>bad' not in text and '&lt;script&gt;' in text

def test_tls_template_site_only(tmp_path,statefile):
    root=tmp_path/'stack';render(statefile,root,APP/'templates')
    for name in ('fullchain.pem','privkey.pem'):(root/'tls'/name).touch()
    tls(statefile,root,APP/'templates');text=(root/'conf.d/tls.conf').read_text()
    assert 'grpc_pass' not in text and 'proxy_pass' not in text
    assert 'http2 on' in text and '127.0.0.1:10000' not in text

def test_missing_docker_fails_cleanly(tmp_path):
    # Function-level fault injection; no daemon is invoked by this test.
    r=bash('source "$APP/lib/docker.sh"; need() { echo "missing Docker" >&2; exit 9; }; require_docker')
    assert r.returncode==9 and 'missing Docker' in r.stderr

def test_certbot_failure_does_not_publish_tls():
    r=bash(r'''source "$APP/lib/certificates.sh"; DOMAIN=not-issued.invalid; EMAIL=admin@example.com
ROOT_SHADOW='unused'
check_dns(){ :; }; acme_probe(){ :; }; certbot_stack(){ return 42; }
export_certificate(){ echo 'UNSAFE-EXPORT'; }; nginx_tls(){ echo 'UNSAFE-TLS'; }
setup_certificates''')
    assert r.returncode!=0 and 'issuance failed' in r.stderr and 'UNSAFE' not in r.stdout

def test_error_cleanup_and_no_secret_in_log(tmp_path):
    # An ERR command containing a secret must not be echoed in cleanup output.
    temp=tmp_path/'ephemeral';temp.mkdir();(temp/'secret').write_text('hidden')
    r=bash(r'''TMPDIR_TASK=$1; trap cleanup EXIT; trap 'warn "Operation failed at line $LINENO"' ERR
false 'SENTINEL-DO-NOT-LOG' ''',temp)
    assert r.returncode!=0 and not temp.exists()
    assert 'SENTINEL' not in r.stdout+r.stderr

def test_sigterm_cleanup(tmp_path):
    temp=tmp_path/'temp';temp.mkdir()
    proc=subprocess.Popen(['bash','-c','set -Eeuo pipefail; source "$1/lib/common.sh"; TMPDIR_TASK=$2; trap cleanup EXIT; trap "exit 143" TERM; kill -TERM $$','test',str(APP),str(temp)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    out,err=proc.communicate(timeout=5);assert proc.returncode==143 and not temp.exists()

def test_publication_check_rejects_public_panel():
    rows=[]
    for name,ports in [('vps-xui',{'2053/tcp':[dict(HostIp='0.0.0.0',HostPort='2053')]}),('vps-nginx',{})]:
        rows.append(dict(Name='/'+name,State=dict(Running=True,Health=dict(Status='healthy')),Config={},HostConfig=dict(PortBindings=ports,CapAdd=None,CapDrop=['ALL'],NetworkMode='test'),NetworkSettings=dict(Networks={'vps-installer-proxy':{}})))
    with pytest.raises(AssertionError,match='PortBindings'):publications.check(rows)

def test_offline_sqlite_snapshot(tmp_path):
    import db
    path=tmp_path/'x-ui.db'
    with sqlite3.connect(path) as c:c.execute('CREATE TABLE inbounds(id INTEGER,settings TEXT)');c.execute('INSERT INTO inbounds VALUES (1,?)',('{"clients":[1]}',))
    output=tmp_path/'snapshot.db'
    subprocess.run([sys.executable,str(APP/'helpers/db.py'),'snapshot',str(path),str(output)],check=True)
    assert db.fingerprint(path)==db.fingerprint(output)

def test_probe_closed_port():
    import socket
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    r=subprocess.run([sys.executable,str(APP/'helpers/probe.py'),'127.0.0.1',str(port)],capture_output=True,text=True)
    assert r.returncode!=0 and 'TCP probe only' in r.stdout

def test_cli_help_and_unknown_argument():
    r=subprocess.run([str(APP/'install.sh'),'--help'],capture_output=True,text=True)
    assert r.returncode==0 and '--reset-3xui-password' in r.stdout
    r=subprocess.run([str(APP/'install.sh'),'--wrong'],capture_output=True,text=True)
    assert r.returncode!=0 and 'Unknown command' in r.stderr

def test_partial_db_without_user_never_counts_as_initialized(tmp_path):
    path=tmp_path/'x-ui.db'
    with sqlite3.connect(path) as c:c.execute('CREATE TABLE users(id INTEGER,username TEXT,password TEXT)')
    r=subprocess.run([sys.executable,str(APP/'helpers/db.py'),'has-user',str(path)],capture_output=True,text=True)
    assert r.returncode!=0
    with sqlite3.connect(path) as c:c.execute("INSERT INTO users VALUES(1,'operator','hash')")
    r=subprocess.run([sys.executable,str(APP/'helpers/db.py'),'has-user',str(path)],capture_output=True,text=True)
    assert r.returncode==0

@pytest.mark.parametrize('subnet',['127.0.0.0/24','169.254.1.0/24','224.0.0.0/24','8.8.8.0/24'])
def test_subnet_must_be_rfc1918(config,subnet):
    config['subnet']=subnet
    with pytest.raises(AssertionError):validate(config)
