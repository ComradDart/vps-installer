#!/usr/bin/env python3
import ipaddress, subprocess, sys
try:
    domain,expected=sys.argv[1:]
    ipaddress.IPv4Address(expected)
    answers={}
    for kind in ('A','AAAA'):
        raw=subprocess.check_output(['dig','+time=5','+tries=1','+short',domain,kind],text=True).splitlines()
        values=[]
        for v in raw:
            try:values.append(str(ipaddress.ip_address(v)))
            except ValueError:pass # CNAME owner names are not address records.
        answers[kind]=set(values)
    assert answers['A']=={expected}, 'A records must match origin IPv4 exactly; initially use DNS-only in Cloudflare'
    assert not answers['AAAA'], 'Base deployment is IPv4-only; remove origin AAAA before issuance'
except (AssertionError,ValueError,subprocess.CalledProcessError) as e:
    print('DNS check failed: '+str(e),file=sys.stderr);sys.exit(1)
