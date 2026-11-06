#!/usr/bin/env python3
import ipaddress,json,re,secrets,urllib.parse,uuid
from pathlib import Path
from state import domain
from xui_api import SetupError,private_json

MODES=('cloudflare-grpc','direct-grpc','direct-reality')
def validate_profile(p):
    if set(p)!={'schema','mode','topology','active'} or p['schema']!=1 or p['mode'] not in MODES or p['topology'] not in ('standalone','relay') or not isinstance(p['active'],bool):raise SetupError('Invalid transport profile')
    return p

def profile(root):
    path=Path(root)/'transport.json'
    return validate_profile(json.loads(path.read_text())) if path.exists() else None

def parse_peer(uri,expected_ip):
    parsed=urllib.parse.urlsplit(uri.strip())
    if parsed.scheme!='vless' or parsed.password or not parsed.username or not parsed.hostname:raise SetupError('Expected a VLESS client URI')
    try:client_id=str(uuid.UUID(parsed.username));ipaddress.IPv4Address(expected_ip)
    except ValueError:raise SetupError('Invalid peer UUID or expected OUTBOUND IPv4') from None
    if not domain(parsed.hostname):raise SetupError('Use the OUTBOUND domain, not an unverified single foreign IP')
    pairs=urllib.parse.parse_qsl(parsed.query,keep_blank_values=True);q=dict(pairs)
    if len(q)!=len(pairs):raise SetupError('Duplicate VLESS URI parameters')
    peer={'address':parsed.hostname,'port':parsed.port or 443,'uuid':client_id,'server_name':q.get('sni',parsed.hostname),'expected_ip':expected_ip}
    if not domain(peer['server_name']) or not 1<=peer['port']<=65535:raise SetupError('Invalid peer endpoint')
    if q.get('security')=='tls' and q.get('type')=='grpc' and not q.get('flow'):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{2,47}',q.get('serviceName','')):raise SetupError('Invalid gRPC serviceName')
        peer.update(mode='grpc',service=q['serviceName'])
    elif q.get('security')=='reality' and q.get('type') in ('tcp','raw') and q.get('flow')=='xtls-rprx-vision':
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',q.get('pbk','')) or not re.fullmatch(r'(?:[a-fA-F0-9]{2}){1,8}',q.get('sid','')):raise SetupError('Invalid REALITY peer key/shortId')
        peer.update(mode='reality',public_key=q['pbk'],short_id=q['sid'],fingerprint=q.get('fp','chrome'))
        if peer['fingerprint'] not in ('chrome','firefox','safari','edge','randomized'):raise SetupError('Unsupported REALITY fingerprint')
    else:raise SetupError('Supported peer URI types: VLESS gRPC/TLS or VLESS REALITY/Vision')
    return peer

def outbound(peer,tag='proxy'):
    user={'id':peer['uuid'],'encryption':'none'}
    if peer['mode']=='grpc':stream={'network':'grpc','security':'tls','tlsSettings':{'serverName':peer['server_name'],'allowInsecure':False,'alpn':['h2']},'grpcSettings':{'serviceName':peer['service'],'multiMode':False}}
    else:
        user['flow']=peer.get('flow','xtls-rprx-vision')
        stream={'network':'tcp','security':'reality','realitySettings':{'serverName':peer['server_name'],'fingerprint':peer.get('fingerprint','chrome'),'publicKey':peer['public_key'],'shortId':peer['short_id'],'spiderX':'/'}}
    return {'tag':tag,'protocol':'vless','settings':{'vnext':[{'address':peer['address'],'port':peer['port'],'users':[user]}]},'streamSettings':stream}

def client_config(peer,port=1080):
    return {'log':{'loglevel':'warning'},'inbounds':[{'listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth','udp':False}}],'outbounds':[outbound(peer)],'routing':{'domainStrategy':'AsIs','rules':[]}}

def client_uri(peer,title):
    q={'encryption':'none','security':'tls' if peer['mode']=='grpc' else 'reality','type':'grpc' if peer['mode']=='grpc' else 'tcp','sni':peer['server_name']}
    if peer['mode']=='grpc':q.update(serviceName=peer['service'],alpn='h2')
    else:
        q.update(pbk=peer['public_key'],sid=peer['short_id'],fp=peer.get('fingerprint','chrome'))
        if peer.get('flow','xtls-rprx-vision'):q['flow']=peer.get('flow','xtls-rprx-vision')
    return 'vless://'+peer['uuid']+'@'+peer['address']+':'+str(peer['port'])+'?'+urllib.parse.urlencode(q)+'#'+urllib.parse.quote(title,safe='')
