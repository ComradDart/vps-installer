#!/usr/bin/env python3
"""Run as root in a disposable Alpine container; uses real sshd and Linux UIDs."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'helpers'))
from panel_users import Manager, run


def wait_for(check, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.1)
    raise AssertionError('Condition timed out')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    assert os.geteuid() == 0, 'Disposable container root required'
    base = Path(tempfile.mkdtemp(prefix='panel-ssh-', dir='/var/lib'))
    os.chmod(base, 0o755)
    state = base / 'state'; state.mkdir(mode=0o700)
    sshdir = base / 'ssh'; sshdir.mkdir(mode=0o755)
    port = free_port()
    (state / 'state.json').write_text(json.dumps(dict(admin='primaryadmin', ssh_port=str(port), public_ip='127.0.0.1')))
    for name in ('host', 'admin', 'guest', 'replacement'):
        run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(base / name)])
    hashed = run(['openssl', 'passwd', '-6', '-stdin'], input='disposable-test-only-password\n')
    run(['useradd', '-M', '-U', '-d', '/nonexistent', '-s', '/bin/sh', '-p', hashed, 'primaryadmin'])
    admin_key = base / 'admin.pub'; os.chmod(admin_key, 0o644)
    config = sshdir / 'sshd_config'
    config.write_text(f'''Port {port}
ListenAddress 127.0.0.1
HostKey {base / 'host'}
PidFile {base / 'sshd.pid'}
AuthorizedKeysFile {admin_key}
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
StrictModes yes
PerSourcePenalties no
PermitRootLogin no
LogLevel VERBOSE
''')
    log = (base / 'server.log').open('w+')
    server = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', str(config)], stderr=log)
    panel = subprocess.Popen([sys.executable, '-m', 'http.server', '2053', '--bind', '127.0.0.1', '--directory', str(sshdir)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    denied = subprocess.Popen([sys.executable, '-m', 'http.server', '2054', '--bind', '127.0.0.1'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    clients = []

    class TestManager(Manager):
        def reload(self):
            server.send_signal(signal.SIGHUP)
            time.sleep(.15)

        def watchdog(self, nonce):
            pass  # No systemd in this container; rollback body is exercised below.

        def stop_watchdog(self, nonce):
            pass

    manager = TestManager(state, sshdir)

    def ssh(user, key, *arguments):
        return ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3',
                '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'IdentitiesOnly=yes', '-i', str(base / key), '-p', str(port),
                *arguments, user + '@127.0.0.1']

    def execute(user, key, *arguments, command='true'):
        return subprocess.run(ssh(user, key, *arguments) + [command], capture_output=True, text=True, timeout=8)

    def tunnel(user='panel_friend', key='guest', destination=2053):
        local = free_port()
        process = subprocess.Popen(ssh(user, key, '-N', '-T', '-o', 'ExitOnForwardFailure=yes',
                                       '-L', f'{local}:127.0.0.1:{destination}'),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clients.append(process)
        wait_for(lambda: process.poll() is not None or listening(local))
        assert process.poll() is None, 'SSH tunnel startup failed'
        return process, local

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(local):
        return opener.open(f'http://127.0.0.1:{local}/sshd_config', timeout=3).read()

    def works(local):
        try:
            return b'PermitRootLogin no' in get(local)
        except OSError:
            return False

    try:
        wait_for(lambda: listening(port) and listening(2053) and listening(2054))
        assert execute('primaryadmin', 'admin', command='printf PRIMARY_OK').stdout == 'PRIMARY_OK'
        before = manager.baseline()
        manager.add('panel_friend', (base / 'guest.pub').read_text())
        first, local = tunnel()
        wait_for(lambda: works(local))
        print('PASS: publickey login and permitted tunnel transfer HTTP bytes from loopback panel')
        for flags, command in [((), 'id'), (('-tt',), '/bin/sh'), (('-s',), 'sftp')]:
            result = execute('panel_friend', 'guest', *flags, command=command)
            assert result.returncode != 0 and 'uid=' not in result.stdout, result
        result = execute('panel_friend', 'guest', command='scp -t /tmp/forbidden')
        assert result.returncode != 0
        print('PASS: command, PTY shell, SFTP and SCP denied')
        bad, other = tunnel(destination=2054)
        assert not works(other)
        # A direct-tcpip request reports the reason rather than just an HTTP timeout.
        result = execute('panel_friend', 'guest', '-W', '127.0.0.1:2054')
        assert result.returncode != 0 and 'administratively prohibited' in result.stderr, result.stderr
        result = execute('panel_friend', 'guest', '-W', 'localhost:2053')
        assert result.returncode != 0 and 'administratively prohibited' in result.stderr
        result = subprocess.run(ssh('panel_friend', 'guest', '-N', '-T', '-o', 'ExitOnForwardFailure=yes',
                                    '-R', '0:127.0.0.1:2053'), capture_output=True, text=True, timeout=8)
        assert result.returncode != 0 and 'remote port forwarding failed' in result.stderr, result.stderr
        print('PASS: other port, alternate hostname and reverse forwarding denied')
        manager.change_key('panel_friend', (base / 'replacement.pub').read_text(), replace=True)
        wait_for(lambda: first.poll() is not None)
        result = execute('panel_friend', 'guest')
        assert result.returncode != 0 and 'Permission denied' in result.stderr
        active, fresh = tunnel(key='replacement')
        wait_for(lambda: works(fresh))
        print('PASS: key replacement rejects old key and closes its active tunnel; new key works')
        # Inject an invalid SSH policy and prove rollback recovers working access.
        saved_render = manager.render
        def broken_render():
            saved_render()
            with manager.policy.open('a') as stream:
                stream.write('ThisDirectiveDoesNotExist yes\n')
        manager.render = broken_render
        try:
            manager.change_key('panel_friend', (base / 'guest.pub').read_text())
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError('Invalid policy was accepted')
        manager.render = saved_render
        assert works(fresh)
        assert manager.records['panel_friend']['keys'] == [(base / 'replacement.pub').read_text().strip().rsplit(' ', 1)[0]]
        print('PASS: invalid sshd configuration rolled back; working key/tunnel retained')
        # A provider Match block overriding a safety option must also roll back.
        original_main = config.read_text()
        config.write_text(original_main + '\nMatch User panel_friend\n    PermitTTY yes\n')
        try:
            manager.change_key('panel_friend', (base / 'guest.pub').read_text())
        except ValueError as error:
            assert 'restriction overridden' in str(error)
        else:
            raise AssertionError('Provider override accepted')
        config.write_text(original_main); manager.reload()
        print('PASS: effective-policy override detected and transaction rolled back')
        manager.revoke('panel_friend')
        wait_for(lambda: active.poll() is not None)
        result = execute('panel_friend', 'replacement')
        assert result.returncode != 0 and 'Permission denied' in result.stderr
        assert not works(fresh)
        assert subprocess.run(['id', 'panel_friend'], capture_output=True).returncode != 0
        print('PASS: revoked account removed, active forwarding terminated and new connections denied')
        assert execute('primaryadmin', 'admin', command='printf PRIMARY_OK').stdout == 'PRIMARY_OK'
        assert manager.baseline() == before
        print('PASS: primary administrator real SSH command and effective settings preserved')
        print('NOT RUN: systemd rollback timer scheduling (container has no systemd); rollback body tested')
    finally:
        for process in clients + [server, panel, denied]:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.2):
            return True
    except OSError:
        return False


if __name__ == '__main__':
    main()
