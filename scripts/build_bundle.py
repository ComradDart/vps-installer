from pathlib import Path
import base64,hashlib,io,tarfile,textwrap
P=Path(__file__).resolve().parents[1];OUT=P/'download'
OUT.mkdir(exist_ok=True)
buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode='w:gz') as tar:
 for p in sorted(P.rglob('*')):
  if not p.is_file() or any(x in ('__pycache__','.pytest_cache','.venv','.git','download') for x in p.parts) or p.suffix=='.pyc':continue
  info=tar.gettarinfo(str(p),arcname='vps-installer/'+str(p.relative_to(P)))
  info.uid=info.gid=0;info.uname=info.gname='root';info.mode=0o755 if p.suffix=='.sh' else 0o644
  with p.open('rb') as f:tar.addfile(info,f)
payload=buf.getvalue();digest=hashlib.sha256(payload).hexdigest()
encoded='\n'.join(textwrap.wrap(base64.b64encode(payload).decode(),76))
header=r'''#!/usr/bin/env bash
# Self-contained delivery. Default: extract only. --install: extract and start installer.
set +x
set -Eeuo pipefail
umask 077
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf 'Usage: bash vps_setup.sh [--install] [new-directory]\nDefault: extract ./vps-installer; never overwrite existing files.\n'
    exit 0
fi
INSTALL_NOW=no
if [[ ${1:-} == --install ]]; then INSTALL_NOW=yes; shift; fi
(( $# <= 1 )) || { printf 'Too many arguments\n' >&2; exit 2; }
command -v python3 >/dev/null || { printf 'Install prerequisites: sudo apt-get install python3 util-linux\n' >&2; exit 1; }
DESTINATION=${1:-./vps-installer}
python3 - "$DESTINATION" <<'VPS_INSTALLER_BUNDLE'
import base64,hashlib,io,os,shutil,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath
payload=base64.b64decode(
'''
# Build as concatenated strings to avoid shell interpolation of Python content.
script=header+'"""\n'+encoded+'\n""")\n'+f"assert hashlib.sha256(payload).hexdigest()=={digest!r}, 'Archive checksum mismatch'\n"+r'''
target=Path(sys.argv[1]).expanduser().absolute()
if target.exists() or target.is_symlink():raise SystemExit('Destination exists; choose another new directory: '+str(target))
target.parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='.vps-unpack-',dir=target.parent) as staging:
    staging=Path(staging)
    with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as tar:
        for member in tar.getmembers():
            parts=PurePosixPath(member.name).parts
            assert parts and parts[0]=='vps-installer' and '..' not in parts
            assert member.isfile(), 'Unexpected non-file archive entry'
            destination=staging.joinpath(*parts)
            destination.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
            with tar.extractfile(member) as source,destination.open('xb') as output:shutil.copyfileobj(source,output)
            destination.chmod(member.mode&0o755)
    os.rename(staging/'vps-installer',target)
print('Extracted to: '+str(target))
print('Read README.md, then run: sudo '+str(target/'install.sh'))
VPS_INSTALLER_BUNDLE
if [[ $INSTALL_NOW == yes ]]; then
    exec "$DESTINATION/install.sh"
fi
'''
(OUT/'vps_setup.sh').write_text(script);(OUT/'vps_setup.sh').chmod(0o755)
(OUT/'vps_setup.sh.sha256').write_text(hashlib.sha256((OUT/'vps_setup.sh').read_bytes()).hexdigest()+'  vps_setup.sh\n')
print('Archive:',len(payload),'bytes; self-extractor:',len(script.encode()),'bytes')
