#!/usr/bin/env python3
import json, os, re, secrets, subprocess, sys, time
from pathlib import Path
op,root=sys.argv[1:3];root=Path(root);gate=root/'ssh-gate.json';ack=root/'ssh-gate.ack'
try:
    if op=='create':
        ack.unlink(missing_ok=True)
        gate.write_text(json.dumps(dict(token=sys.argv[3],user=sys.argv[4],port=sys.argv[5],since=int(time.time()))))
        gate.chmod(0o600)
    elif op=='confirm':
        d=json.loads(gate.read_text());connection=sys.argv[4].split()
        assert os.geteuid()==0 and os.environ.get('SUDO_USER')==d['user'], 'Run sudo from the new admin SSH session'
        assert secrets.compare_digest(d['token'],sys.argv[3]) and time.time()-d['since']<600, 'Gate expired or wrong token'
        assert len(connection)==4 and connection[3]==d['port'], 'Wrong SSH destination port'
        client,port=connection[:2]
        text=subprocess.check_output(['journalctl','--since','@'+str(d['since']),'-u','ssh.service','--no-pager','-o','cat'],text=True)
        assert re.search(r'Accepted publickey for '+re.escape(d['user'])+r' from '+re.escape(client)+r' port '+re.escape(port)+r'\b',text), 'No matching fresh Accepted publickey entry in ssh.service journal'
        ack.touch(mode=0o600);print('SSH public-key login and sudo verified')
    else: raise ValueError('Unknown operation')
except (OSError,ValueError,AssertionError,subprocess.CalledProcessError) as e:
    print('SSH confirmation failed: '+str(e),file=sys.stderr);sys.exit(1)
