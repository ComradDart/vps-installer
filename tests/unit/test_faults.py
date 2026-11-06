import json,os,subprocess,sys,tarfile
from pathlib import Path
import pytest
from conftest import APP,bash

def test_dns_not_updated(tmp_path):
    # Stub dig only; this is a negative unit test, not a real DNS/E2E check.
    bindir=tmp_path/'bin';bindir.mkdir();dig=bindir/'dig';dig.write_text('#!/bin/sh\ncase "$*" in *AAAA*) exit 0;; *) echo 192.0.2.99;; esac\n');dig.chmod(0o755)
    r=subprocess.run([sys.executable,str(APP/'helpers/dns.py'),'example.com','192.0.2.10'],env={**os.environ,'PATH':str(bindir)+':'+os.environ['PATH']},capture_output=True,text=True)
    assert r.returncode!=0 and 'A records' in r.stderr

def test_registry_pull_failure():
    r=bash('source "$APP/lib/docker.sh"; docker(){ return 7; }; compose pull')
    assert r.returncode!=0

def test_daemon_unavailable():
    r=bash('source "$APP/lib/docker.sh"; docker(){ return 7; }; need(){ :; }; require_docker')
    assert r.returncode!=0 and 'daemon unavailable' in r.stderr

def test_password_hash_verification_failure_is_redacted(tmp_path):
    import sqlite3,bcrypt
    path=tmp_path/'x-ui.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE users(id INTEGER,username TEXT,password TEXT)')
        c.execute('INSERT INTO users VALUES (1,?,?)',('operator',bcrypt.hashpw(b'previous-test-password',bcrypt.gensalt()).decode()))
    r=subprocess.run([sys.executable,str(APP/'helpers/db.py'),'verify',str(path)],input='operator\nSENTINEL-SECRET-VALUE\n',capture_output=True,text=True)
    assert r.returncode!=0 and 'SENTINEL' not in r.stderr+r.stdout

def test_archive_untrusted_ownership_rejected(tmp_path):
    # Real extractor rejects user-owned/unchecksummed archives before mutation.
    path=tmp_path/'bad.tar.gz';path.write_bytes(b'invalid');Path(str(path)+'.sha256').write_text('0'*64)
    r=subprocess.run([sys.executable,str(APP/'helpers/backup.py'),'extract',str(path),str(tmp_path/'target')],capture_output=True,text=True)
    assert r.returncode!=0 and not (tmp_path/'target').exists()
