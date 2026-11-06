#!/usr/bin/env python3
"""Root-only local backups, online SQLite snapshots, confined restore extraction."""
import hashlib, json, os, shutil, sqlite3, sys, tarfile, tempfile, time
from pathlib import Path, PurePosixPath
from db import connect
from state import validate

def stream_digest(f):
    h=hashlib.sha256()
    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def snapshot_tree(src,dst):
    # Directory must be installer-owned, never arbitrary input from JSON.
    shutil.copytree(src,dst,symlinks=True,ignore=shutil.ignore_patterns('*.db-wal','*.db-shm'))
    for db in Path(src).rglob('*.db'):
        if db.is_symlink():continue
        with db.open('rb') as f:magic=f.read(16)
        if magic!=b'SQLite format 3\x00':continue
        target=dst/db.relative_to(src)
        target.unlink(missing_ok=True)
        with connect(db) as c,sqlite3.connect(target) as out:c.backup(out)
        target.chmod(0o600)

def create(root,backups):
    root=Path(root);backups=Path(backups);backups.mkdir(mode=0o700,parents=True,exist_ok=True)
    name='vps-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+os.urandom(3).hex()+'.tar.gz'
    result=backups/name
    with tempfile.TemporaryDirectory(prefix='.backup-',dir=backups) as temp:
        temp=Path(temp)
        if root.exists():snapshot_tree(root,temp/'stack')
        with tarfile.open(temp/'system.tar.gz','w:gz',dereference=False) as tar:
            for name in ('/etc/ssh','/etc/ufw','/etc/fail2ban','/etc/apt/apt.conf.d','/etc/sysctl.d','/etc/vps-setup.conf'):
                if Path(name).exists():tar.add(name,arcname=name.lstrip('/'))
        # Legacy data are only read, never stopped/deleted/imported. SQLite files
        # are backed up via sqlite3.backup; this is not a distributed snapshot.
        for index,legacy in enumerate(('/opt/3x-ui','/opt/nginx-panel','/opt/telemt','/opt/mtproxyl','/etc/amnezia')):
            if Path(legacy).is_dir():snapshot_tree(Path(legacy),temp/('legacy-'+str(index)))
        pending=temp/'archive.tmp'
        with tarfile.open(pending,'w:gz',dereference=False) as tar:
            for child in temp.iterdir():
                if child!=pending:tar.add(child,arcname=child.name)
        pending.chmod(0o600);os.replace(pending,result)
    with result.open('rb') as f:sha=stream_digest(f)
    sidecar=Path(str(result)+'.sha256');sidecar.write_text(sha+'\n');sidecar.chmod(0o600)
    print(result)

def extract(archive,target):
    archive=Path(archive);target=Path(target).resolve();side=Path(str(archive)+'.sha256')
    for p in (archive,side):
        st=p.lstat();assert p.is_file() and not p.is_symlink() and st.st_uid==0 and st.st_mode&0o077==0, 'Backup and checksum must be root-owned mode 600'
    # Stream the digest; avoid reading large backups into RAM.
    with archive.open('rb') as f:actual=stream_digest(f)
    assert actual==side.read_text().strip(), 'Backup checksum mismatch'
    target.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tarfile.open(archive,'r:gz') as tar:
        all_members=tar.getmembers();members=[];total=0;seen=set()
        for m in all_members:
            p=PurePosixPath(m.name)
            assert not p.is_absolute() and '..' not in p.parts and m.name not in seen, 'Unsafe archive path'
            assert p.parts and (p.parts[0]=='stack' or p.parts[0]=='system.tar.gz' or p.parts[0].startswith('legacy-')), 'Unexpected archive root'
            seen.add(m.name)
            assert m.isdir() or m.isfile() or m.issym(), 'Special files/hard links are forbidden'
            # Legacy and system snapshots are retained in the backup for manual
            # recovery only; never materialize their links during stack restore.
            if p.parts[0]!='stack':continue
            members.append(m)
            if m.issym():
                assert not PurePosixPath(m.linkname).is_absolute(), 'Absolute symlink forbidden'
                linked=(target/p.parent/m.linkname).resolve()
                assert linked.is_relative_to(target/'stack'), 'Symlink leaves stack'
            total+=m.size
        assert total < shutil.disk_usage(target).free*0.8, 'Insufficient restore disk space'
        # Extract directories and regular files first. A symlink can never be an
        # ancestor of a written member: reject the entire archive if it is.
        links={PurePosixPath(m.name) for m in members if m.issym()}
        for m in members:
            p=PurePosixPath(m.name)
            assert not any(a in links for a in p.parents), 'Symlink ancestor forbidden'
        for m in members:
            dest=target/m.name
            if m.isdir():dest.mkdir(mode=0o700,parents=True,exist_ok=True)
            elif m.isfile():
                dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                with tar.extractfile(m) as src,dest.open('xb') as out:shutil.copyfileobj(src,out)
                dest.chmod(m.mode&0o777&~0o002);os.chown(dest,0,m.gid if m.gid in (0,101) else 0)
        for m in members:
            if m.issym():
                dest=target/m.name;dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True);dest.symlink_to(m.linkname)
        for m in reversed(members):
            if m.isdir():
                dest=target/m.name;dest.chmod(m.mode&0o777&~0o002);os.chown(dest,0,m.gid if m.gid in (0,101) else 0)
    d=json.loads((target/'stack/state.json').read_text());validate(d)
    assert (target/'stack/db/x-ui.db').is_file(), 'Backup has no panel DB'

if __name__=='__main__':
    try:
        if sys.argv[1]=='create':create(*sys.argv[2:])
        elif sys.argv[1]=='extract':extract(*sys.argv[2:])
        else:raise ValueError('Unknown backup operation')
    except Exception as e:
        print('Backup/restore failed: '+str(e),file=sys.stderr);sys.exit(1)
