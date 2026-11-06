#!/usr/bin/env python3
"""Refuse foreign published Docker listeners, including those without docker-proxy."""
import json, subprocess, sys
try:
    ids=subprocess.check_output(['docker','ps','-q'],text=True).split()
    if not ids: sys.exit(0)
    rows=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))
    for row in rows:
        if row['Config'].get('Labels',{}).get('com.docker.compose.project')=='vps-installer':continue
        for port, bindings in (row['HostConfig'].get('PortBindings') or {}).items():
            if any(b.get('HostPort') in ('80','443','2053','8443') for b in bindings or []):
                raise ValueError('Foreign Docker publication conflicts: '+row['Name']+' '+port)
except (ValueError,subprocess.CalledProcessError) as e:
    print(str(e),file=sys.stderr);sys.exit(1)
