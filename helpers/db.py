#!/usr/bin/env python3
"""Read/verify/snapshot SQLite, never write 3x-ui's schema or credentials."""
import hashlib, json, sqlite3, sys
from pathlib import Path

def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=30)
def fingerprint(path):
    with connect(path) as c:
        out={}
        for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if name=='users':continue
            quote='"'+name.replace('"','""')+'"'
            rows=c.execute('SELECT * FROM '+quote).fetchall()
            out[name]=hashlib.sha256(repr(sorted(rows,key=repr)).encode()).hexdigest()
        return out

def main():
    op,path=sys.argv[1:3]
    if op=='verify':
        import bcrypt
        user,password=sys.stdin.read().splitlines()
        with connect(path) as c:
            row=c.execute('SELECT username,password FROM users ORDER BY id LIMIT 1').fetchone()
            assert row and row[0]==user and bcrypt.checkpw(password.encode(),row[1].encode()), 'Credential verification failed'
    elif op=='has-user':
        with connect(path) as c:assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0]>0
    elif op=='snapshot':
        with connect(path) as src,sqlite3.connect(sys.argv[3]) as dst:src.backup(dst)
        with connect(sys.argv[3]) as c:assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        Path(sys.argv[3]).chmod(0o600)
    elif op=='fingerprint':print(json.dumps(fingerprint(path),sort_keys=True))
    elif op=='integrity':
        with connect(path) as c:assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    else:raise ValueError('Unknown DB operation')
if __name__=='__main__':
    try:main()
    except Exception:
        print('Database operation failed (secrets suppressed)',file=sys.stderr);sys.exit(1)
