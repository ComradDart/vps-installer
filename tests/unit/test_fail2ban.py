import pytest
from conftest import bash


def test_waits_for_delayed_socket():
    r=bash("""source "$APP/lib/hardening.sh"
pings=0
fail2ban-client(){
 if [[ $1 == ping ]]; then pings=$((pings+1)); ((pings >= 3)); else printf 'JAIL_READY\\n'; fi
}
systemctl(){ return 1; }
sleep(){ :; }
wait_fail2ban 2
[[ $pings == 3 ]]
""")
    assert r.returncode==0 and 'JAIL_READY' in r.stdout


def test_socket_without_sshd_jail_is_not_ready():
    r=bash("""source "$APP/lib/hardening.sh"
jails=0
fail2ban-client(){
 if [[ $1 == ping ]]; then return 0; fi
 jails=$((jails+1)); if ((jails < 3)); then return 1; fi
 printf 'JAIL_READY\\n'
}
systemctl(){ return 1; }
sleep(){ :; }
wait_fail2ban 2
((jails >= 3))
""")
    assert r.returncode==0 and 'JAIL_READY' in r.stdout


def test_failed_service_stops_and_prints_diagnostics():
    r=bash("""source "$APP/lib/hardening.sh"
fail2ban-client(){ printf 'socket unavailable' >&2; return 255; }
systemctl(){ if [[ $1 == is-failed ]]; then return 0; fi; printf 'SERVICE_DIAGNOSTIC\\n'; }
journalctl(){ printf 'JOURNAL_DIAGNOSTIC\\n'; }
wait_fail2ban 2
printf 'UNSAFE_CONTINUE'
""")
    assert r.returncode!=0 and 'UNSAFE_CONTINUE' not in r.stdout
    assert 'SERVICE_DIAGNOSTIC' in r.stderr and 'JOURNAL_DIAGNOSTIC' in r.stderr
    assert 'socket unavailable' not in r.stderr


def test_readiness_timeout_is_fatal():
    r=bash("""source "$APP/lib/hardening.sh"
fail2ban-client(){ return 255; }
systemctl(){ printf 'SERVICE_DIAGNOSTIC\\n'; return 1; }
journalctl(){ printf 'JOURNAL_DIAGNOSTIC\\n'; }
wait_fail2ban 0
printf 'UNSAFE_CONTINUE'
""")
    assert r.returncode!=0 and 'UNSAFE_CONTINUE' not in r.stdout
    assert 'within 0s' in r.stderr and 'JOURNAL_DIAGNOSTIC' in r.stderr
