import pytest
from dns import check_answers

def test_direct_origin():assert check_answers('192.0.2.10',{'A':{'192.0.2.10'},'AAAA':set()},True)=='direct'
def test_proxy_ipv4_ipv6_can_reach_ipv4_origin():
    answers={'A':{'104.21.1.1','172.67.1.1'},'AAAA':{'2606:4700::1'}}
    assert check_answers('192.0.2.10',answers,True)=='proxy-or-other-host'
    with pytest.raises(ValueError,match='A records'):check_answers('192.0.2.10',answers)
def test_missing_dns_still_fails():
    with pytest.raises(ValueError,match='No A records'):check_answers('192.0.2.10',{'A':set(),'AAAA':set()},True)
def test_direct_ipv6_requires_real_support():
    with pytest.raises(ValueError,match='IPv4-only'):check_answers('192.0.2.10',{'A':{'192.0.2.10'},'AAAA':{'2001:db8::1'}},True)


def test_dns_failure_precedes_system_mutations():
    import subprocess
    from conftest import APP
    code=r"""set -Eeuo pipefail
source "$1/install.sh"
preflight(){ :; }
load_state(){ :; }
backup_stack(){ :; }
collect_state(){ :; }
confirm(){ :; }
check_dns(){ printf 'DNS_CHECK\n'; return 1; }
base_packages(){ printf 'UNSAFE_PACKAGES\n'; }
install_main
"""
    r=subprocess.run(['bash','-c',code,'test',str(APP)],text=True,capture_output=True)
    assert r.returncode!=0 and 'DNS_CHECK' in r.stdout and 'UNSAFE_PACKAGES' not in r.stdout


def test_site_update_preserves_compose_nginx_database(tmp_path,statefile):
    from conftest import APP
    from render import site
    for name in ('compose.yml','nginx.conf','db/x-ui.db','conf.d/tls.conf','site/custom.txt'):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('DO NOT CHANGE')
    site(statefile,tmp_path,APP/'templates')
    for name in ('compose.yml','nginx.conf','db/x-ui.db','conf.d/tls.conf','site/custom.txt'):
        assert (tmp_path/name).read_text()=='DO NOT CHANGE'
    assert 'HAHA BENIS' in (tmp_path/'site/index.html').read_text()
    assert 'warpBtn' in (tmp_path/'site/app.js').read_text()
