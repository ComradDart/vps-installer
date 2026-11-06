import importlib.util,json,os,subprocess,sys
from pathlib import Path
import pytest
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP/'helpers'))
import state
@pytest.fixture
def config():
    versions=json.loads((APP/'config/images.json').read_text())
    return dict(schema='1',role='outbound',domain='example.com',admin='vpsadmin',
                ssh_port='22',public_ip='192.0.2.10',email='admin@example.com',subnet='172.30.53.0/24',
                xui_image=versions['xui_image'],nginx_image=versions['nginx_image'],title='HAHA BENIS',text='Digital studio',
                phase='configured')
@pytest.fixture
def statefile(tmp_path,config):
    p=tmp_path/'state.json';state.write(p,config);return p

def bash(code,*args,env=None):
    prefix='set -Eeuo pipefail; APP=$1; shift; source "$APP/lib/common.sh"; '
    return subprocess.run(['bash','-c',prefix+code,'test',str(APP),*map(str,args)],text=True,capture_output=True,env=env)
