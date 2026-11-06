#!/usr/bin/env python3
"""Real authenticated Xray client; no published SOCKS port, no direct fallback."""
import copy,ipaddress,json,os,secrets,shutil,tempfile,time
from pathlib import Path
from xui_api import SetupError,private_json
from transport_profile import client_config

def probe(docker,root,peer,expected_ip,url='https://api4.ipify.org?format=json',ca_file=None,image=None):
    root=Path(root);temporary=Path(tempfile.mkdtemp(prefix='.xray-probe-',dir=root));name='vps-probe-'+secrets.token_hex(6)
    config=client_config(peer)
    mounts=[]
    if ca_file:
        # Test CA is only used for the controlled origin in isolated integration tests.
        ca_file=Path(ca_file).resolve();mounts=['-v',str(ca_file)+':/probe-ca.pem:ro']
        if peer['mode']=='grpc':config['outbounds'][0]['streamSettings']['tlsSettings']['certificates']=[{'certificateFile':'/probe-ca.pem','usage':'verify'}]
    path=temporary/'client.json';private_json(path,config)
    try:
        image=image or docker.inspect(docker.container)['Config']['Image']
        docker.run('run','-d','--name',name,'--network',docker.network,'--log-driver','none','--user',str(os.getuid())+':'+str(os.getgid()),'--cap-drop','ALL','--security-opt','no-new-privileges:true','-v',str(path)+':/client.json:ro',*mounts,'--entrypoint',docker.binary(),image,'run','-config','/client.json')
        for _ in range(20):
            try:docker.run('exec',name,'timeout','2','bash','-c','exec 3<>/dev/tcp/127.0.0.1/1080',timeout=5);break
            except SetupError:time.sleep(.2)
        else:raise SetupError('Reference Xray client did not become ready')
        args=['exec',name,'curl','--noproxy','','--fail','--silent','--show-error','--max-time','25','--proxy','socks5h://127.0.0.1:1080']
        if ca_file:args+=['--cacert','/probe-ca.pem']
        response=docker.run(*args,url,timeout=35)
        try:actual=json.loads(response)['ip'];ipaddress.ip_address(actual)
        except (ValueError,KeyError,TypeError):raise SetupError('Real client transferred an unexpected diagnostic response') from None
        if ipaddress.ip_address(actual)!=ipaddress.ip_address(expected_ip):raise SetupError('Real client exit address differs from the selected OUTBOUND; direct bypass or wrong route')
        return {'transport':'PASSED','exit_address':'PASSED'}
    finally:
        try:docker.run('rm','-f',name,timeout=15)
        except SetupError:pass
        shutil.rmtree(temporary)
