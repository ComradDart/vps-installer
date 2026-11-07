import io,subprocess,tarfile
from pathlib import Path
import pytest
from conftest import APP,bash

@pytest.mark.parametrize('distro,version,ok',[
    ('debian','12',True),('debian','13',True),('ubuntu','24.04',True),('ubuntu','26.04',True),
    ('ubuntu','22.04',False),('ubuntu','26.10',False),('debian','11',False),('alpine','3.23',False)])
def test_os_policy_matches_bootstrap(distro,version,ok):
    assert (bash('supported_os "$1" "$2"',distro,version).returncode==0)==ok
    r=bash('source "$APP/get.sh"; bootstrap_supported_os "$1" "$2"',distro,version)
    assert (r.returncode==0)==ok

def test_unsupported_os_diagnostic_identifies_actual_version():
    r=bash('require_supported_os ubuntu 22.04 "Ubuntu 22.04 LTS"')
    assert r.returncode!=0 and 'ID=ubuntu VERSION_ID=22.04' in r.stderr and '26.04' in r.stderr

def archive(path,name,kind=None):
    with tarfile.open(path,'w:gz') as tar:
        m=tarfile.TarInfo(name);data=b'#!/bin/sh\nexit 0\n';m.size=len(data);m.mode=0o755
        if kind:m.type=kind;m.linkname='/etc/passwd';m.size=0
        tar.addfile(m,io.BytesIO(data) if not kind else None)

def test_bootstrap_extracts_real_bundle_without_git(tmp_path):
    package=tmp_path/'source.tar.gz';target=tmp_path/'extract';target.mkdir()
    archive(package,'vps-installer-main/install.sh')
    r=bash('source "$APP/get.sh"; bootstrap_extract "$1" "$2"',package,target)
    assert r.returncode==0 and (target/'vps-installer-main/install.sh').read_text().startswith('#!/bin/sh')

@pytest.mark.parametrize('name,kind',[
    ('vps-installer-main/../../escape',None),('/absolute',None),
    ('another-repo/install.sh',None),('vps-installer-main/link',tarfile.SYMTYPE),
    ('vps-installer-main/link',tarfile.LNKTYPE)])
def test_bootstrap_rejects_unsafe_archive(tmp_path,name,kind):
    package=tmp_path/'source.tar.gz';target=tmp_path/'extract';target.mkdir();archive(package,name,kind)
    r=bash('source "$APP/get.sh"; bootstrap_extract "$1" "$2"',package,target)
    assert r.returncode!=0 and not list(target.iterdir())

def test_bootstrap_cleanup_on_failure(tmp_path):
    temp=tmp_path/'temporary';temp.mkdir()
    r=bash('source "$APP/get.sh"; BOOTSTRAP_TEMP=$1; trap bootstrap_cleanup EXIT; false',temp)
    assert r.returncode!=0 and not temp.exists()
