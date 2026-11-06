#!/usr/bin/env python3
"""3x-ui API adapter: reviewed 3.11.0 contract, selected by the running latest image."""
import http.cookiejar,json,os,re,subprocess,tempfile,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path

class SetupError(RuntimeError):pass

def private_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.parent.chmod(0o700)
    fd,tmp=tempfile.mkstemp(prefix='.private-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def private_text(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.parent.chmod(0o700)
    fd,tmp=tempfile.mkstemp(prefix='.private-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

class Docker:
    def __init__(self,container='vps-xui',nginx='vps-nginx',network='vps-installer-proxy'):
        self.container=container;self.nginx=nginx;self.network=network
    def run(self,*args,input=None,timeout=120):
        p=subprocess.run(['docker',*map(str,args)],input=input,text=True,capture_output=True,timeout=timeout)
        if p.returncode:
            hint=': no space left on device' if 'no space left on device' in p.stderr.lower() else ': port already allocated' if 'port is already allocated' in p.stderr.lower() else ''
            raise SetupError('Docker '+str(args[0])+' failed (exit '+str(p.returncode)+')'+hint+'; raw output suppressed to protect secrets')
        return p.stdout
    def inspect(self,name):return json.loads(self.run('inspect',name))[0]
    def version(self):
        text=self.run('exec',self.container,'/app/x-ui','-v').strip()
        match=re.fullmatch(r'v?(\d+\.\d+\.\d+)',text)
        if not match or match[1]!='3.11.0':raise SetupError('Running latest 3x-ui has an unreviewed API version; no inbound changes were made. Expected reviewed contract 3.11.0.')
        return match[1]
    def binary(self):
        machine=self.run('exec',self.container,'uname','-m').strip()
        if machine not in ('x86_64','aarch64'):raise SetupError('Unsupported Xray architecture')
        return '/app/bin/xray-linux-'+('amd64' if machine=='x86_64' else 'arm64')

class Api:
    def __init__(self,base,token=''):
        parsed=urllib.parse.urlsplit(base)
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','::1','localhost') or parsed.username:raise SetupError('Panel API must use a loopback HTTP endpoint')
        self.base=base.rstrip('/');self.token=token
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(self,path,data=None,form=False):
        headers={'Authorization':'Bearer '+self.token} if self.token else {}
        body=None
        if data is not None:
            headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
            body=(urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
        req=urllib.request.Request(self.base+path,data=body,headers=headers)
        try:
            with self.opener.open(req,timeout=20) as response:payload=json.load(response)
        except urllib.error.HTTPError as e:raise SetupError('3x-ui API '+path.split('?')[0]+' HTTP '+str(e.code)) from None
        except (OSError,ValueError,urllib.error.URLError):raise SetupError('3x-ui API unreachable or returned invalid JSON') from None
        if not isinstance(payload,dict) or payload.get('success') is not True:raise SetupError('3x-ui API rejected '+path.split('?')[0]+' (response omitted to protect credentials)')
        return payload.get('obj')
    def inbounds(self):
        rows=self.request('/panel/api/inbounds/list')
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not all(k in r for k in ('id','port','protocol','settings','streamSettings','tag')) for r in rows):raise SetupError('Unexpected inbound-list API schema; no writes allowed')
        return rows
    def clients(self):
        rows=self.request('/panel/api/clients/list')
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not all(k in r for k in ('email','uuid')) for r in rows):raise SetupError('Unexpected client-list API schema; no writes allowed')
        return rows
    def restart(self):self.request('/panel/api/server/restartXrayService',{})
    def template(self):
        obj=self.request('/panel/api/xray/',{})
        if isinstance(obj,str):obj=json.loads(obj)
        if not isinstance(obj,dict) or not isinstance(obj.get('xraySetting'),dict):raise SetupError('Unexpected Xray template API schema')
        return obj['xraySetting']
    def set_template(self,template):
        self.request('/panel/api/xray/update',{'xraySetting':json.dumps(template),'outboundTestUrl':'https://www.google.com/generate_204'},form=True)


def authenticated_api(root,docker,base='http://127.0.0.1:2053'):
    version=docker.version();path=Path(root)/'secrets/xui-api.token';api=Api(base)
    if path.exists():
        api.token=path.read_text().strip()
        try:api.inbounds();return api,version
        except SetupError as e:
            if not ('HTTP 401' in str(e) or 'HTTP 403' in str(e)):raise
    # This documented CLI prints a named token once; it does not reset the user.
    output=docker.run('exec',docker.container,'/app/x-ui','setting','-getApiToken','-tokenName','vps-installer','-tokenScope','admin')
    tokens=re.findall(r'^apiToken:\s*(\S+)\s*$',output,re.M)
    if len(tokens)!=1:raise SetupError('Official CLI did not return exactly one API token; panel password was not changed')
    api.token=tokens[0];api.inbounds();private_text(path,api.token+'\n')
    return api,version


def verify_login(base,username,password):
    jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    try:
        obj=json.load(opener.open(base.rstrip('/')+'/csrf-token',timeout=10));token=obj['obj']
        req=urllib.request.Request(base.rstrip('/')+'/login',data=json.dumps({'username':username,'password':password}).encode(),headers={'Content-Type':'application/json','X-CSRF-Token':token})
        result=json.load(opener.open(req,timeout=10))
        if result.get('success') is not True:raise SetupError('Chosen panel credentials failed a real HTTP login')
    except (OSError,ValueError,KeyError,urllib.error.URLError):raise SetupError('Panel login/CSRF verification failed (credentials omitted)') from None
