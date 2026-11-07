"""Parse fixtures with the real OpenSSH daemon binary; never run/reload a daemon."""
import shutil,subprocess,shlex
from pathlib import Path
import pytest
from conftest import APP

@pytest.fixture
def ssh_fixture(tmp_path):
    binary=shutil.which('sshd')
    if not binary:pytest.skip('Real sshd binary required for configuration parsing')
    key=tmp_path/'hostkey'
    subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
    snippets=tmp_path/'sshd_config.d';snippets.mkdir()
    vendor=snippets/'00-custom-root.conf';vendor.write_text('PermitRootLogin yes\nPasswordAuthentication yes\n')
    (snippets/'60-cloudimg-settings.conf').write_text('PasswordAuthentication no\n')
    main=tmp_path/'sshd_config'
    main.write_text('HostKey '+str(key)+'\nInclude '+str(snippets)+'/*.conf\nUsePAM no\n')
    def effective(user):
        result=subprocess.run([binary,'-T','-f',str(main),'-C',f'user={user},host=localhost,addr=127.0.0.1'],text=True,capture_output=True)
        assert result.returncode==0,result.stderr
        return dict(line.split(' ',1) for line in result.stdout.splitlines())
    return snippets,vendor,main,effective


def managed_config(port=22):
    # Exercise the exact here-doc used by setup_ssh, rather than duplicating settings.
    source=(APP/'lib/ssh.sh').read_text()
    section=source.split('cat >/etc/ssh/sshd_config.d/00-00-vps-installer.conf <<EOF\n',1)[1].split('\nEOF',1)[0]
    return section.replace('$SSH_PORT',str(port))+'\n'


def test_provider_first_value_reproduced_then_hardened(ssh_fixture):
    snippets,vendor,main,effective=ssh_fixture;original=vendor.read_bytes()
    old=snippets/'00-vps-installer.conf';old.write_text(managed_config())
    assert effective('root')['permitrootlogin']=='yes'
    assert effective('vpsadmin')['passwordauthentication']=='yes'
    old.unlink()
    managed=snippets/'00-00-vps-installer.conf';managed.write_text(managed_config())
    assert effective('root')['permitrootlogin']=='no'
    admin=effective('vpsadmin')
    for key,value in dict(passwordauthentication='no',pubkeyauthentication='yes',kbdinteractiveauthentication='no',x11forwarding='no',maxauthtries='3').items():assert admin[key]==value
    assert vendor.read_bytes()==original
    # Rollback removes only the managed file and restores the provider's original policy.
    managed.unlink()
    assert effective('root')['permitrootlogin']=='yes'
    assert effective('vpsadmin')['passwordauthentication']=='yes'


def test_match_override_still_detectable(ssh_fixture):
    snippets,vendor,main,effective=ssh_fixture
    (snippets/'00-00-vps-installer.conf').write_text(managed_config())
    with main.open('a') as f:f.write('Match User root\n    PermitRootLogin yes\n')
    assert effective('root')['permitrootlogin']=='yes'
    # setup_ssh still checks the actual root context and refuses this configuration.
    source=(APP/'lib/ssh.sh').read_text()
    assert 'user=root,host=' in source and '[[ $actual == no ]]' in source


@pytest.mark.parametrize('had_managed',[False,True])
def test_real_rollback_preserves_provider_and_prior_managed_config(ssh_fixture,tmp_path,had_managed):
    snippets,vendor,main,effective=ssh_fixture
    original_vendor=vendor.read_bytes();managed=snippets/'00-00-vps-installer.conf'
    stack=tmp_path/'stack';stack.mkdir()
    previous='PermitRootLogin no\nPasswordAuthentication no\nMaxAuthTries 4\n'
    if had_managed:(stack/'ssh-before.conf').write_text(previous)
    managed.write_text(managed_config())
    source=(APP/'lib/ssh.sh').read_text()
    rollback=source.split('cat >"$ROOT/ssh-rollback.sh" <<\'EOF\'\n',1)[1].split('\nEOF',1)[0]
    rollback=rollback.replace('/opt/vps-installer',str(stack)).replace('/etc/ssh/sshd_config.d',str(snippets))
    rollback=rollback.replace('/usr/sbin/sshd -t',shlex.quote(shutil.which('sshd'))+' -t -f '+shlex.quote(str(main)))
    # Real file restoration and sshd parsing, without starting/reloading any system unit.
    result=subprocess.run(['bash','-c','systemctl(){ :; };\n'+rollback],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert vendor.read_bytes()==original_vendor
    if had_managed:
        assert managed.read_text()==previous
        assert effective('root')['permitrootlogin']=='no'
    else:
        assert not managed.exists()
        assert effective('root')['permitrootlogin']=='yes'


def test_staging_preserves_existing_root_password_login(ssh_fixture):
    snippets,vendor,main,effective=ssh_fixture
    managed=snippets/'00-00-vps-installer.conf'
    vendor.unlink()
    managed.write_text('PermitRootLogin yes\nPasswordAuthentication yes\nPort 22\n')
    staging=snippets/'00-00-00-vps-staging.conf'
    staging.write_text('Port 2222\nPort 22\nPubkeyAuthentication yes\n')
    assert effective('root')['permitrootlogin']=='yes'
    assert effective('root')['passwordauthentication']=='yes'
    staging.unlink();managed.write_text(managed_config(2222))
    assert effective('root')['permitrootlogin']=='no'
    assert effective('vpsadmin')['passwordauthentication']=='no'
