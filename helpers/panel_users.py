#!/usr/bin/env python3
"""Individual SSH keys for a shared, loopback-only panel. No panel API calls."""
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time


BEGIN = '# BEGIN vps-installer panel tunnel users'
END = '# END vps-installer panel tunnel users'
TYPES = {'ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256',
         'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521',
         'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com'}
POLICY = {
    'authenticationmethods': 'publickey', 'pubkeyauthentication': 'yes',
    'passwordauthentication': 'no', 'kbdinteractiveauthentication': 'no',
    'authorizedkeyscommand': 'none', 'disableforwarding': 'no',
    'allowtcpforwarding': 'local', 'allowstreamlocalforwarding': 'no',
    'permitopen': '127.0.0.1:2053', 'permitlisten': 'none',
    'gatewayports': 'no', 'allowagentforwarding': 'no', 'x11forwarding': 'no',
    'permittty': 'no', 'permittunnel': 'no', 'permituserrc': 'no',
    'maxsessions': '0', 'forcecommand': '/bin/false',
}


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kwargs).stdout.strip()


def atomic(path, data, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'Refusing symlink: {path}')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def public_key(text):
    parts = text.strip().split()
    if '\n' in text.strip() or len(parts) < 2 or parts[0] not in TYPES:
        raise ValueError('Paste one plain public key, without options; never a private key')
    try:
        raw = base64.b64decode(parts[1], validate=True)
        size = int.from_bytes(raw[:4], 'big')
        if raw[4:4 + size].decode() != parts[0]:
            raise ValueError('Key type does not match its encoding')
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid public key') from exc
    key = ' '.join(parts[:2])
    with tempfile.NamedTemporaryFile(mode='w') as stream:
        stream.write(key + '\n'); stream.flush()
        run(['ssh-keygen', '-l', '-f', stream.name])
    return key


def fingerprint(key):
    raw = base64.b64decode(key.split()[1])
    return 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')


class Manager:
    def __init__(self, root, ssh_dir='/etc/ssh'):
        self.root = Path(root)
        self.ssh = Path(ssh_dir)
        self.main = self.ssh / 'sshd_config'
        self.policy = self.ssh / 'vps-panel-users.conf'
        self.keys = self.ssh / 'vps-panel-keys'
        self.registry = self.root / 'panel-users.json'
        self.journal = self.root / 'panel-users-transaction.json'
        self.state = json.loads((self.root / 'state.json').read_text())
        self.admin = self.state['admin']
        self.sshd = shutil.which('sshd') or '/usr/sbin/sshd'
        self.records = json.loads(self.registry.read_text()) if self.registry.exists() else {}
        self.keys.mkdir(mode=0o755, exist_ok=True)
        if self.keys.is_symlink():
            raise ValueError('Refusing symlink key directory')
        os.chmod(self.keys, 0o755)

    def save(self):
        atomic(self.registry, json.dumps(self.records, indent=2) + '\n')

    def owned(self, user):
        if not re.fullmatch(r'panel_[a-z0-9_]{1,26}', user) or user == self.admin:
            raise ValueError('Use panel_NAME (lowercase letters/digits/underscore, max 32 chars)')
        record = self.records.get(user)
        if record is None:
            raise ValueError('This account is not managed by --panel-users')
        account = pwd.getpwnam(user)
        if account.pw_uid != record['uid'] or account.pw_uid in (0, pwd.getpwnam(self.admin).pw_uid):
            raise ValueError('Account UID changed; refusing to modify or terminate it')
        return account

    def context(self, user, address):
        return f'user={user},host=panel-check.invalid,addr={address},laddr={self.state["public_ip"]},lport={self.state["ssh_port"]}'

    def addresses(self):
        client = os.environ.get('SSH_CONNECTION', '').split()
        return list(dict.fromkeys(['127.0.0.1', '198.51.100.17'] + client[:1]))

    def effective(self, user, address):
        output = run([self.sshd, '-T', '-f', str(self.main), '-C', self.context(user, address)])
        return dict(line.split(' ', 1) for line in output.splitlines())

    def baseline(self):
        run([self.sshd, '-t', '-f', str(self.main)])
        return {(u, a): self.effective(u, a) for u in {self.admin, 'root'} for a in self.addresses()}

    def validate(self, baseline):
        run([self.sshd, '-t', '-f', str(self.main)])
        for (user, address), before in baseline.items():
            if self.effective(user, address) != before:
                raise ValueError(f'Primary administrator/root SSH settings changed for {address}')
        for user, record in self.records.items():
            if record['status'] != 'active':
                continue
            self.owned(user)
            for address in self.addresses():
                actual = self.effective(user, address)
                expected = dict(POLICY, authorizedkeysfile=str(self.keys / '%u'),
                                pubkeyacceptedalgorithms=self.algorithms(record))
                for option, value in expected.items():
                    if actual.get(option) != value:
                        raise ValueError(f'SSH restriction overridden for {user}: {option}; no change applied')
                if any(actual.get(k) for k in ('allowusers', 'allowgroups', 'denyusers', 'denygroups')):
                    raise ValueError('Existing Allow/DenyUsers/Groups policy requires manual review; preserved')

    @staticmethod
    def algorithms(record):
        kinds = {k.split()[0] for k in record['keys']}
        if 'ssh-rsa' in kinds:
            kinds.remove('ssh-rsa'); kinds.update(('rsa-sha2-512', 'rsa-sha2-256'))
        # Exclude SSH certificates: global TrustedUserCAKeys must not bypass our key list.
        return ','.join(sorted(kinds)) or 'ssh-ed25519'

    def render(self):
        text = self.main.read_text()
        if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
            raise ValueError('Malformed managed SSH block; refusing to rewrite main config')
        text = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.S)
        lines = ['# Managed tunnel users; public keys are root-controlled.']
        for user, record in sorted(self.records.items()):
            lines.append(f'Match User {user}')
            for key, value in dict(POLICY, authorizedkeysfile=str(self.keys / '%u'),
                                   pubkeyacceptedalgorithms=self.algorithms(record)).items():
                lines.append(f'    {key} {value}')
        lines.append('Match all')
        atomic(self.policy, '\n'.join(lines) + '\n', 0o600)
        # EOF avoids placing Match blocks inside the early global drop-in Include.
        atomic(self.main, text.rstrip() + f'\n\n{BEGIN}\nMatch all\nInclude {self.policy}\n{END}\n',
               self.main.stat().st_mode & 0o777)
        for user, record in self.records.items():
            values = record['keys'] if record['status'] == 'active' else []
            atomic(self.keys / user, ''.join(
                'restrict,port-forwarding,permitopen="127.0.0.1:2053" ' + key + '\n'
                for key in values), 0o644)
        self.save()

    def reload(self):
        for service in ('ssh.service', 'sshd.service'):
            try:
                run(['systemctl', 'reload', service]); return
            except subprocess.CalledProcessError:
                pass
        raise ValueError('Could not reload ssh/sshd service')

    def watchdog(self, nonce):
        run(['systemd-run', '--quiet', '--unit=vps-panel-users-' + nonce,
             '--on-active=120s', '/usr/bin/python3', str(Path(__file__).resolve()),
             'rollback', str(self.root), nonce])

    def stop_watchdog(self, nonce):
        subprocess.run(['systemctl', 'stop', 'vps-panel-users-' + nonce + '.timer'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    @contextlib.contextmanager
    def transaction(self):
        if self.journal.exists():
            raise ValueError('Unfinished SSH transaction; run the printed rollback command first')
        before = self.baseline()
        nonce = secrets.token_hex(8)
        backup = self.root / 'panel-users-backups' / nonce
        backup.mkdir(parents=True, mode=0o700)
        files = [self.main, self.policy, self.registry, *self.keys.iterdir()]
        snapshot = {}
        for index, path in enumerate(files):
            if path.is_symlink():
                raise ValueError('Refusing symlink in managed SSH files')
            saved = backup / str(index)
            snapshot[str(path)] = {'saved': str(saved), 'exists': path.exists(),
                                   'mode': (path.stat().st_mode & 0o777) if path.exists() else 0o600}
            if path.exists():
                shutil.copyfile(path, saved); os.chmod(saved, 0o600)
        journal = {'nonce': nonce, 'files': snapshot, 'created': None}
        atomic(backup / 'manifest.json', json.dumps(journal, indent=2))
        atomic(self.journal, json.dumps(journal))
        print(f'SSH backup: {backup}\nRollback: sudo python3 {Path(__file__).resolve()} rollback {self.root} {nonce}')
        try:
            self.watchdog(nonce)
            yield journal
            self.render(); self.validate(before); self.reload()
            if journal['created']:
                # Activate only while the rollback journal/watchdog still exist.
                run(['usermod', '--expiredate', '', journal['created'][0]])
        except BaseException:
            self.rollback(nonce)
            raise
        else:
            self.journal.unlink()
        finally:
            self.stop_watchdog(nonce)

    def rollback(self, nonce):
        if not self.journal.exists():
            return
        journal = json.loads(self.journal.read_text())
        if journal['nonce'] != nonce:
            return
        created = journal.get('created')
        if created:
            user, uid = created
            try:
                if pwd.getpwnam(user).pw_uid == uid:
                    run(['usermod', '--expiredate', '1970-01-02', user])
                    self.terminate(uid)
                    run(['userdel', user])
            except KeyError:
                pass
        for path, entry in journal['files'].items():
            if entry['exists']:
                atomic(path, Path(entry['saved']).read_text(), entry['mode'])
            else:
                Path(path).unlink(missing_ok=True)
        if created:
            (self.keys / created[0]).unlink(missing_ok=True)
        run([self.sshd, '-t', '-f', str(self.main)])
        self.reload()
        self.journal.unlink()
        self.records = json.loads(self.registry.read_text()) if self.registry.exists() else {}

    @staticmethod
    def terminate(uid):
        if uid == 0:
            raise ValueError('Refusing to terminate root')
        for sig in ('TERM', 'KILL'):
            result = subprocess.run(['pkill', '-' + sig, '-u', str(uid)], check=False,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode not in (0, 1):
                raise ValueError('Could not terminate guest SSH sessions')
            for _ in range(20):
                result = subprocess.run(['pgrep', '-u', str(uid)], check=False,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.returncode == 1:
                    return
                if result.returncode != 0:
                    raise ValueError('Could not verify session termination')
                time.sleep(0.1)
        raise ValueError('Guest processes still exist; account remains revoked')

    def add(self, user, key):
        if not re.fullmatch(r'panel_[a-z0-9_]{1,26}', user) or user == self.admin:
            raise ValueError('Use panel_NAME, max 32 lowercase letters/digits/underscore')
        try:
            pwd.getpwnam(user)
        except KeyError:
            pass
        else:
            raise ValueError('Linux account already exists; it will not be adopted')
        if user in self.records:
            raise ValueError('Account has a pending revocation; complete removal first')
        key = public_key(key)
        shell = shutil.which('nologin')
        if not shell:
            raise ValueError('nologin is required')
        # Discard a random password immediately. A valid hash permits publickey
        # on systems without PAM; PasswordAuthentication remains forbidden.
        hashed = run(['openssl', 'passwd', '-6', '-stdin'], input=secrets.token_urlsafe(48) + '\n')
        with self.transaction() as journal:
            run(['useradd', '--no-create-home', '--user-group', '--home-dir', '/nonexistent',
                 '--shell', shell, '--expiredate', '1970-01-02', '--password', hashed, user])
            account = pwd.getpwnam(user)
            journal['created'] = [user, account.pw_uid]
            atomic(self.journal, json.dumps(journal))
            self.records[user] = {'uid': account.pw_uid, 'keys': [key], 'status': 'active'}
            groups = set(os.getgrouplist(user, account.pw_gid))
            sudo = subprocess.run(['sudo', '-n', '-l', '-U', user], check=False,
                                  capture_output=True, text=True, env=dict(os.environ, LC_ALL='C'))
            # sudo versions differ: some return 0 even when -l prints denial.
            denied = re.fullmatch(r'User ' + re.escape(user) + r' is not allowed to run sudo on \S+\.',
                                  (sudo.stdout + sudo.stderr).strip())
            if groups != {account.pw_gid} or sudo.returncode not in (0, 1) or not denied:
                raise ValueError('New guest has unexpected group/sudo privileges')
        self.command(user)

    def change_key(self, user, key, replace=False):
        self.owned(user)
        if self.records[user]['status'] != 'active':
            raise ValueError('Account is revoked; finish removing it')
        key = public_key(key)
        with self.transaction():
            keys = [] if replace else self.records[user]['keys'][:]
            if key not in keys:
                keys.append(key)
            self.records[user]['keys'] = keys
        if replace:
            self.terminate(self.owned(user).pw_uid)

    def revoke(self, user):
        account = self.owned(user)
        # Monotonic revocation: rollback never restores a revoked key/account.
        run(['usermod', '--expiredate', '1970-01-02', user])
        atomic(self.keys / user, '', 0o644)
        self.records[user]['status'] = 'revoked'; self.save()
        self.terminate(account.pw_uid)
        with self.transaction():
            # Remove OS account only after SSH config has been safely applied.
            pass
        run(['userdel', user])
        # Retain its restrictive Match block until the next successful edit.
        del self.records[user]; self.save()
        (self.keys / user).unlink(missing_ok=True)
        print(f'{user}: account removed; existing SSH sessions terminated')

    def listing(self):
        for user, record in sorted(self.records.items()):
            print(f'{user} ({record["status"]})')
            for key in record['keys']:
                print('  ' + fingerprint(key))
        if not self.records:
            print('No invited SSH tunnel users')

    def command(self, user):
        self.owned(user)
        print('ssh -N -T -o ExitOnForwardFailure=yes '
              f'-p {self.state["ssh_port"]} -i ~/.ssh/3xui_key '
              f'-L 127.0.0.1:2053:127.0.0.1:2053 {user}@{self.state["public_ip"]}')
        print('Open http://127.0.0.1:2053 and use the EXISTING 3x-ui admin login/password.')
        print('If local port 2053 is busy, use -L 12053:127.0.0.1:2053 and open http://127.0.0.1:12053.')

    def menu(self):
        if self.journal.exists():
            nonce = json.loads(self.journal.read_text())['nonce']
            raise ValueError(f'Pending rollback: sudo python3 {Path(__file__).resolve()} rollback {self.root} {nonce}')
        while True:
            print('\nSSH-доступ к общей панели 3x-ui\n1. Добавить пользователя SSH-туннеля\n'
                  '2. Удалить пользователя и отозвать доступ\n3. Добавить или заменить публичный ключ\n'
                  '4. Показать пользователей и отпечатки ключей\n5. Команда подключения\n0. Выход')
            choice = input('Выбор: ').strip()
            try:
                if choice == '0':
                    return
                if choice == '4':
                    self.listing(); continue
                if choice not in {'1', '2', '3', '5'}:
                    continue
                user = input('Linux-пользователь (panel_NAME): ').strip()
                if choice == '1':
                    print('Ключ генерирует пользователь НА СВОЁМ устройстве. Нужен только публичный .pub.')
                    self.add(user, input('Публичный SSH-ключ: '))
                elif choice == '2':
                    if input('Активные туннели будут завершены. Для удаления введите имя ещё раз: ') == user:
                        self.revoke(user)
                elif choice == '3':
                    mode = input('1 — добавить ключ; 2 — заменить ВСЕ ключи и завершить туннели: ')
                    if mode not in {'1', '2'}:
                        continue
                    self.change_key(user, input('Публичный SSH-ключ: '), mode == '2')
                else:
                    self.command(user)
            except (ValueError, KeyError, subprocess.CalledProcessError) as exc:
                print('Operation failed: ' + (str(exc) if not isinstance(exc, subprocess.CalledProcessError)
                                             else 'OS/SSH command failed; SSH rollback attempted'), file=sys.stderr)
                if self.journal.exists():
                    raise ValueError('SSH rollback is pending; keep the admin session open') from exc


def main():
    if os.geteuid() != 0:
        raise ValueError('Run with sudo')
    os.umask(0o077)
    action, root = sys.argv[1:3]
    manager = Manager(root)
    if action == 'rollback':
        manager.rollback(sys.argv[3])
    elif action == 'menu' and sys.stdin.isatty():
        for command in ('useradd', 'usermod', 'userdel', 'pkill', 'pgrep', 'sudo',
                        'openssl', 'ssh-keygen', 'sshd', 'systemctl', 'systemd-run'):
            if not shutil.which(command):
                raise ValueError(f'Missing {command}; install openssh-server passwd procps sudo openssl')
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *_: sys.exit(1))
        manager.menu()
    else:
        raise ValueError('Interactive terminal required')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, subprocess.CalledProcessError, EOFError) as error:
        print('Panel SSH management stopped: ' + (str(error) if not isinstance(error, subprocess.CalledProcessError)
                                                 else 'system command failed; inspect SSH configuration'), file=sys.stderr)
        sys.exit(1)
