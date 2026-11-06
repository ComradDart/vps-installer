import subprocess
from conftest import APP


def simulate(tmp_path, failure=False):
    script = r'''set -Eeuo pipefail
ROOT=$1; source "$2/lib/checks.sh"
SIMULATED_RESULT=$3
log(){ printf '[+] %s\n' "$*"; }
warn(){ printf '[!] %s\n' "$*" >&2; }
die(){ warn "$*"; exit 1; }
unattended-upgrade(){
    [[ $# == 1 && $1 == --dry-run ]] || return 99
    printf 'simulation plan stdout\n'
    printf '/usr/bin/dpkg --unpack simulated.deb\nDeprecationWarning: simulated warning\n' >&2
    return "$SIMULATED_RESULT"
}
'''
    # No package manager is executed: the stub reproduces its two output streams.
    script += '\ncheck_security_updates\nprintf "CONTINUED\\n"\n'
    return subprocess.run(['bash', '-c', script, 'test', str(tmp_path), str(APP), '7' if failure else '0'],
                          text=True, capture_output=True)


def test_successful_simulation_captures_both_streams_privately(tmp_path):
    result = simulate(tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'dry-run simulation' in result.stdout and 'simulation: OK' in result.stdout
    assert 'CONTINUED' in result.stdout
    assert 'dpkg --unpack' not in result.stdout + result.stderr
    assert 'DeprecationWarning' not in result.stdout + result.stderr
    report = tmp_path / 'unattended-upgrade-check.log'
    assert 'simulation plan stdout' in report.read_text()
    assert 'dpkg --unpack' in report.read_text() and 'DeprecationWarning' in report.read_text()
    assert report.stat().st_mode & 0o777 == 0o600


def test_failed_simulation_stops_and_shows_diagnostics(tmp_path):
    result = simulate(tmp_path, failure=True)
    assert result.returncode != 0
    assert 'failed (exit 7)' in result.stderr
    assert 'dpkg --unpack' in result.stderr and 'DeprecationWarning' in result.stderr
    assert 'simulation: OK' not in result.stdout
    assert 'CONTINUED' not in result.stdout


def test_previous_log_permissions_are_restricted(tmp_path):
    report = tmp_path / 'unattended-upgrade-check.log'
    report.write_text('old output');report.chmod(0o644)
    assert simulate(tmp_path).returncode == 0
    assert report.stat().st_mode & 0o777 == 0o600
    assert 'old output' not in report.read_text()
