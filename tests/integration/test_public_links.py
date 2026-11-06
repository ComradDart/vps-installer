"""Focused INBOUND real-panel export check, including decoding the UI QR image.

XUI_EXPORT_BINARY=/absolute/path/to/official/x-ui enables this test. The binary
must be the reviewed 3.11.0 release (same API contract as deployed latest).
No Xray transfer or Cloudflare E2E is implied by this export-only fixture.
"""
import base64,copy,io,json,os,re,secrets,socket,subprocess,time,urllib.request,uuid
from pathlib import Path

import pytest
from managed_inbound import decoded,payload
from public_links import repair,validate_uri
from client_tools import public_key
from xui_api import Api

pytestmark=pytest.mark.skipif(not os.environ.get('XUI_EXPORT_BINARY'),reason='NOT RUN: official 3x-ui export binary not supplied')


@pytest.fixture(scope='module')
def panel(tmp_path_factory):
    root=tmp_path_factory.mktemp('real-public-links');binary=Path(os.environ['XUI_EXPORT_BINARY'])
    assert subprocess.check_output([str(binary),'-v'],text=True).strip()=='3.11.0'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=dict(os.environ,XUI_DB_FOLDER=str(root/'db'));password=secrets.token_urlsafe(24)
    command=[str(binary),'setting','-username','exportadmin','-password',password,'-port',str(port),'-listenIP','127.0.0.1','-webBasePath','/']
    subprocess.run(command,env=env,capture_output=True,check=True)
    log=(root/'panel.log').open('w')
    process=subprocess.Popen([str(binary)],env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT)
    try:
        base='http://127.0.0.1:'+str(port)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            try:opener.open(base+'/csrf-token',timeout=1);break
            except OSError:time.sleep(.1)
        output=subprocess.run([str(binary),'setting','-getApiToken','-tokenName','exports','-tokenScope','admin'],env=env,capture_output=True,text=True,check=True).stdout
        token=re.findall(r'^apiToken:\s*(\S+)\s*$',output,re.M)[0]
        yield root,Api(base,token),base,password,opener
    finally:
        process.terminate();process.wait(timeout=10);log.close()


def test_native_links_subscription_and_qr(panel):
    mode='direct-reality'
    root,api,base,password,opener=panel
    state=dict(role='outbound' if mode=='cloudflare-grpc' else 'inbound',domain='entry.example.test',PUBLIC_DOMAIN='entry.example.test')
    profile=dict(mode=mode);cache=dict(mode=mode,uuid=str(uuid.uuid4()),email='export-'+mode)
    if mode=='direct-reality':
        private=secrets.token_urlsafe(32)
        cache.update(private_key=private,public_key=public_key(private),short_id=secrets.token_hex(8))
    row=api.request('/panel/api/inbounds/add',payload(state,profile,cache));cache['inbound_id']=row['id']
    (root/'secrets').mkdir(exist_ok=True);(root/'secrets/managed-xray.json').write_text(json.dumps(cache))
    (root/'conf.d').mkdir(exist_ok=True)
    (root/'conf.d/tls.conf').write_text('server {\n    server_name entry.example.test;\n}\n')
    class NginxFixture:
        nginx='fixture'
        def run(self,*args):pass # Export-only fixture: public nginx/REALITY transfer is NOT RUN.
    nginx=NginxFixture()
    before=copy.deepcopy(row)
    assert repair(api,root,state,profile,nginx)==1
    after=next(r for r in api.inbounds() if r['id']==row['id'])
    assert decoded(after,'settings')==decoded(before,'settings')
    for field in ('listen','port','tag'):assert after[field]==before[field]
    if mode=='direct-reality':
        old=decoded(before,'streamSettings')['realitySettings'];new=decoded(after,'streamSettings')['realitySettings']
        assert (old['privateKey'],old['shortIds'])==(new['privateKey'],new['shortIds'])
    client=decoded(after,'settings')['clients'][0];subid=client['subId']
    url='/panel/api/clients/subLinks/'+subid
    reference=api.request(url)
    for host in ('localhost:2053','127.0.0.1:2053','172.30.53.2:2053','admin.example.test'):
        request=urllib.request.Request(base+url,headers={'Authorization':'Bearer '+api.token,'Host':host})
        links=json.load(opener.open(request))['obj']
        assert links==reference
        for link in links:validate_uri(link,after,client,state)
    settings=api.request('/panel/api/setting/all',{})
    assert settings['subURI']=='https://entry.example.test'+settings['subPath']
    assert settings['webDomain']==''
    raw=opener.open('http://127.0.0.1:2096'+settings['subPath']+subid).read().decode()
    if not raw.startswith('vless://'):raw=base64.b64decode(raw).decode()
    for link in raw.splitlines():validate_uri(link,after,client,state)
    assert set(raw.splitlines())==set(reference)
    assert repair(api,root,state,profile,nginx)==1
    assert len([h for h in api.request('/panel/api/hosts/list') if row['id'] in h['inboundIds']])==1
    assert decoded(next(r for r in api.inbounds() if r['id']==row['id']),'settings')==decoded(after,'settings')
    # Decode an actual QR from the shipped React UI, rather than creating our own.
    from playwright.sync_api import sync_playwright
    import zxingcpp
    from PIL import Image
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        try:
            for hostname in ('127.0.0.1','localhost'):
                ui=base.replace('127.0.0.1',hostname);context=browser.new_context()
                csrf=context.request.get(ui+'/csrf-token').json()['obj']
                assert context.request.post(ui+'/login',data=dict(username='exportadmin',password=password),headers={'X-CSRF-Token':csrf}).json()['success']
                page=context.new_page();page.goto(ui+'/panel/clients')
                item=page.locator('tr').filter(has_text=cache['email'])
                item.locator('button').filter(has=page.locator('[aria-label="qrcode"]')).first.click(timeout=15000)
                page.locator('.ant-collapse-header').filter(has_text='VLESS').click(timeout=10000)
                qr=page.locator('.qr-panel-canvas svg').last
                qr.wait_for(state='attached')
                markup=qr.evaluate('(element) => element.outerHTML')
                picture=context.new_page()
                picture.set_content('<body style="margin:0;background:white">'+markup+'</body>')
                picture.locator('svg').evaluate('(element) => { element.setAttribute("width","512");element.setAttribute("height","512"); }')
                result=zxingcpp.read_barcode(Image.open(io.BytesIO(picture.locator('svg').screenshot())))
                assert result and result.text in reference
                validate_uri(result.text,after,client,state)
                context.close()
        finally:browser.close()
