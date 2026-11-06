#!/usr/bin/env python3
"""DNS is an early hint; an exact public ACME challenge proves the origin route."""
import argparse,ipaddress,shutil,socket,subprocess,sys

def resolve(domain):
    answers={'A':set(),'AAAA':set()}
    if shutil.which('dig'):
        for kind in answers:
            raw=subprocess.check_output(['dig','+time=5','+tries=1','+short',domain,kind],text=True).splitlines()
            for value in raw:
                try:address=ipaddress.ip_address(value)
                except ValueError:continue
                if (kind=='A')==(address.version==4):answers[kind].add(str(address))
    else:
        try:
            for family,_,_,_,address in socket.getaddrinfo(domain,80,type=socket.SOCK_STREAM):
                if family in (socket.AF_INET,socket.AF_INET6):answers['A' if family==socket.AF_INET else 'AAAA'].add(address[0])
        except socket.gaierror as error:raise ValueError('Domain does not resolve; configure DNS before installation') from error
    return answers

def check_answers(expected,answers,allow_proxy=False):
    ipaddress.IPv4Address(expected)
    if not answers['A']:raise ValueError('No A records found; configure DNS before installation')
    if answers['A']=={expected}:
        if answers['AAAA']:raise ValueError('Direct origin is IPv4-only; remove its AAAA record before issuance')
        return 'direct'
    if not allow_proxy:raise ValueError('A records differ from origin; use --allow-proxy for a proxy with a verified HTTP-01 route')
    return 'proxy-or-other-host'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('domain');parser.add_argument('origin_ipv4');parser.add_argument('--allow-proxy',action='store_true')
    args=parser.parse_args();answers=resolve(args.domain);mode=check_answers(args.origin_ipv4,answers,args.allow_proxy)
    print('[+] DNS '+args.domain+': A='+','.join(sorted(answers['A']))+' AAAA='+(','.join(sorted(answers['AAAA'])) or 'none'))
    if mode!='direct':
        print('[!] DNS uses proxy/other addresses, not the origin IPv4. Exact public ACME-file verification is required.',file=sys.stderr)
        print('[!] Cloudflare: allow /.well-known/acme-challenge/* on port 80 without challenges/cache. For first issuance, avoid forced HTTPS to an origin without a valid certificate; DNS only is the simplest fallback.',file=sys.stderr)
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print('DNS check failed: '+str(error),file=sys.stderr);sys.exit(1)
