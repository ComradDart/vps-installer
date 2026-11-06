#!/usr/bin/env python3
import html, json, os, sys, tempfile
from pathlib import Path
from state import validate
from transport_profile import profile

def atomic(path,text,mode=0o644):
    fd,tmp=tempfile.mkstemp(prefix='.render-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f: f.write(text)
        os.chmod(tmp,mode);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def render(state,root,templates):
    d=json.loads(Path(state).read_text());validate(d);root=Path(root);templates=Path(templates)
    # Compose single-quoted bind paths must not contain quotes/newlines or substitutions.
    if any(c in str(root) for c in "'\n\r$:"):raise ValueError('Unsafe project path')
    for name in ('db','xray-logs','conf.d','site','acme','.well-known','tls','letsencrypt','certbot-work','certbot-logs'):
        p=root/name;p.mkdir(parents=True,exist_ok=True)
        p.chmod(0o700 if name in ('db','xray-logs','letsencrypt','certbot-work','certbot-logs') else 0o755)
    (root/'acme/.well-known/acme-challenge').mkdir(parents=True,exist_ok=True)
    for p in (root/'acme',root/'acme/.well-known',root/'acme/.well-known/acme-challenge'):p.chmod(0o755)
    # Parent /opt/vps-installer remains 0700; bind-mounted paths have their own access.
    managed=profile(root);reality=bool(managed and managed['active'] and managed['mode']=='direct-reality')
    tokens={'XUI_PUBLIC_TLS':"      - '0.0.0.0:443:443/tcp'" if reality else '',
            'NGINX_PUBLIC_TLS':'' if reality else "      - '0.0.0.0:443:8443/tcp'",'ROOT':str(root),'DOMAIN':d['domain'],'SUBNET':d['subnet'],
            'XUI_IMAGE':d['xui_image'],'NGINX_IMAGE':d['nginx_image'],
            'TITLE':html.escape(d['title']), 'TEXT':html.escape(d['text'])}
    def subst(text):
        for k,v in tokens.items():text=text.replace('@@'+k+'@@',v)
        if '@@' in text:raise ValueError('Unresolved template tokens')
        return text
    for src,dest in [('compose.yml','compose.yml'),('nginx.conf','nginx.conf'),('http.conf','conf.d/http.conf')]:
        atomic(root/dest,subst((templates/src).read_text()))
    # Existing HTTPS configuration stays in place until explicitly replaced after cert validation.
    # Never overwrite the administrator's site during an ordinary render/re-run.
    for src in (templates/'site').iterdir():
        dest=root/'site'/src.name
        if not dest.exists():atomic(dest,subst(src.read_text()))

def site(state,root,templates):
    """Explicit site update: never rewrite Compose or nginx configuration."""
    d=json.loads(Path(state).read_text());validate(d);root=Path(root);templates=Path(templates)
    target=root/'site';target.mkdir(parents=True,exist_ok=True);target.chmod(0o755)
    for name in ('index.html','style.css','app.js'):
        text=(templates/'site'/name).read_text()
        text=text.replace('@@TITLE@@',html.escape(d['title'])).replace('@@TEXT@@',html.escape(d['text']))
        atomic(target/name,text)

def tls(state,root,templates):
    d=json.loads(Path(state).read_text());validate(d);root=Path(root);templates=Path(templates)
    assert (root/'tls/fullchain.pem').is_file() and (root/'tls/privkey.pem').is_file(), 'TLS files missing'
    text=(templates/'tls.conf').read_text()
    text=text.replace('@@DOMAIN@@',d['domain'])
    managed=profile(root)
    if managed and managed['active'] and managed['mode']!='direct-reality':
        atomic(root/'conf.d/vps-grpc.inc',(templates/'grpc.inc').read_text())
        text=text.replace('server_name '+d['domain']+';', 'server_name '+d['domain']+';\n    include /etc/nginx/conf.d/vps-grpc.inc;')
    atomic(root/'conf.d/tls.conf',text)
if __name__=='__main__':
    try:
        if sys.argv[1]=='tls':tls(*sys.argv[2:])
        elif sys.argv[1]=='site':site(*sys.argv[2:])
        else:render(*sys.argv[1:])
    except (OSError,ValueError,AssertionError) as e:print('Render failed: '+str(e),file=sys.stderr);sys.exit(1)
