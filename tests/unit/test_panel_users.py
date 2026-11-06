import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import panel_users as panel


@pytest.fixture
def manager(tmp_path, config):
    root = tmp_path / 'root'; root.mkdir()
    ssh = tmp_path / 'ssh'; ssh.mkdir()
    (root / 'state.json').write_text(json.dumps(config))
    (ssh / 'sshd_config').write_text('Port 22\n')
    return panel.Manager(root, ssh)


@pytest.fixture(scope='module')
def key(tmp_path_factory):
    path = tmp_path_factory.mktemp('panel-key') / 'key'
    panel.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(path)])
    return Path(str(path) + '.pub').read_text()


def test_public_key_canonicalization_and_fingerprint(key):
    canonical = panel.public_key(key)
    assert len(canonical.split()) == 2
    assert panel.public_key(canonical + ' arbitrary comment') == canonical
    assert panel.fingerprint(canonical).startswith('SHA256:')


@pytest.mark.parametrize('bad', [
    '-----BEGIN OPENSSH PRIVATE KEY-----', 'ssh-ed25519 invalid',
    'command="id" ssh-ed25519 AAAA', 'ssh-ed25519-cert-v01@openssh.com AAAA',
    'ssh-ed25519 AAAA\nssh-ed25519 AAAA', 'ssh-rsa AAAA',
])
def test_private_cert_option_multiline_and_invalid_keys_rejected(bad):
    with pytest.raises(ValueError):
        panel.public_key(bad)


@pytest.mark.parametrize('user', ['root', 'vpsadmin', 'other', 'panel_a;id', 'panel_*', 'panel_' + 'a' * 27])
def test_no_arbitrary_account_adoption(manager, user, key):
    with patch.object(panel, 'run') as command, pytest.raises(ValueError):
        manager.add(user, key)
    command.assert_not_called()


def test_changed_uid_cannot_be_revoked(manager):
    manager.records['panel_friend'] = {'uid': 2001, 'keys': [], 'status': 'active'}
    with patch.object(panel.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=2002)):
        with patch.object(panel, 'run') as command, pytest.raises(ValueError, match='UID changed'):
            manager.revoke('panel_friend')
        command.assert_not_called()


def test_primary_admin_uid_cannot_be_revoked(manager):
    manager.records['panel_friend'] = {'uid': 2001, 'keys': [], 'status': 'active'}
    with patch.object(panel.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=2001)):
        with pytest.raises(ValueError, match='UID changed'):
            manager.revoke('panel_friend')


@pytest.mark.parametrize('role', ['inbound', 'outbound'])
def test_policy_and_root_key_files_for_both_roles(manager, key, role):
    manager.state['role'] = role
    manager.records['panel_friend'] = {'uid': 2001, 'keys': [panel.public_key(key)], 'status': 'active'}
    manager.render()
    text = manager.policy.read_text()
    assert 'Match User panel_friend\n' in text
    assert 'allowtcpforwarding local' in text and 'permitopen 127.0.0.1:2053' in text
    assert 'maxsessions 0' in text and 'forcecommand /bin/false' in text
    assert 'allowstreamlocalforwarding no' in text and 'permitlisten none' in text
    assert (manager.keys / 'panel_friend').stat().st_mode & 0o777 == 0o644
    assert manager.keys.stat().st_mode & 0o777 == 0o755
    assert manager.main.read_text().endswith(panel.END + '\n')
    original = manager.main.read_text()
    manager.render()
    assert manager.main.read_text() == original
    assert '-cert-' not in text


def test_stale_rollback_timer_cannot_revert_later_transaction(manager):
    manager.journal.write_text(json.dumps({'nonce': 'new'}))
    with patch.object(panel, 'run') as command:
        manager.rollback('old')
    command.assert_not_called()
    assert manager.journal.exists()


def test_add_key_is_idempotent_and_preserves_other_key(manager, key):
    existing = 'ssh-ed25519 other-key-fixture'
    manager.records['panel_friend'] = {'uid': 2001, 'keys': [existing], 'status': 'active'}
    import contextlib
    with patch.object(manager, 'owned'), patch.object(manager, 'transaction', contextlib.nullcontext):
        manager.change_key('panel_friend', key)
        manager.change_key('panel_friend', key)
    assert manager.records['panel_friend']['keys'] == [existing, panel.public_key(key)]
