import copy,json,uuid
import pytest
from managed_inbound import owned_inbound,ensure,decoded
from reality_migration import plan,apply
from xui_api import SetupError
from test_reality_migration import transaction_engine


def test_rename_does_not_break_ownership_or_create_a_duplicate(tmp_path,config):
    engine,api,cache=transaction_engine(tmp_path,config)
    api.row['remark']='My renamed inbound'
    original=copy.deepcopy(api.row)
    row,created=ensure(api,engine.state,engine.profile,cache)
    assert not created and row['id']==cache['inbound_id']
    assert owned_inbound(api.inbounds(),engine.state,engine.profile,cache)['remark']=='My renamed inbound'
    engine.provision(public=False)
    assert api.row['remark']=='IN · Client VLESS'
    for key in ('id','tag','port','settings','streamSettings'):assert api.row[key]==original[key]
    writes=len(api.writes);engine.provision(public=False)
    assert len(api.writes)==writes


def test_migration_preserves_a_user_supplied_display_name(tmp_path,config):
    engine,api,cache=transaction_engine(tmp_path,config)
    api.row['remark']='Entry for router'
    value=plan(tmp_path,api,engine.state,engine.profile,cache)
    row=apply(api,value)
    assert row['remark']=='Entry for router' and row['id']==cache['inbound_id']
    assert decoded(row,'settings')['clients'][0]['id']==cache['uuid']


def test_id_alone_cannot_adopt_an_unrelated_client(tmp_path,config):
    engine,api,cache=transaction_engine(tmp_path,config)
    api.row['remark']='Another inbound'
    data=decoded(api.row,'settings');data['clients'][0]['id']=str(uuid.uuid4());api.row['settings']=json.dumps(data)
    assert owned_inbound(api.inbounds(),engine.state,engine.profile,cache) is None
    with pytest.raises(SetupError,match='unmanaged'):ensure(api,engine.state,engine.profile,cache)
    assert api.writes==[]


def test_saved_uuid_moved_to_another_id_is_not_guessed(tmp_path,config):
    engine,api,cache=transaction_engine(tmp_path,config)
    api.row['id']=99;api.row['remark']='Renamed'
    with pytest.raises(SetupError,match='different inbound ID'):owned_inbound(api.inbounds(),engine.state,engine.profile,cache)
    assert api.writes==[]


def test_xray_only_check_does_not_run_host_configuration():
    import subprocess
    from conftest import APP
    script=r'''set -Eeuo pipefail
source "$1/install.sh"
init_runtime(){ :; }
load_state(){ :; }
require_docker(){ :; }
check_stack(){ printf 'HOST_CHECK_SHOULD_NOT_RUN\n'; return 9; }
python3(){
    [[ $1 == "$APP/helpers/automation.py" && $2 == check && $3 == "$ROOT" ]] || return 8
    printf 'XRAY_CHECK_ROUTED\n'
}
main --check-xray
'''
    result=subprocess.run(['bash','-c',script,'test',str(APP)],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'XRAY_CHECK_ROUTED' in result.stdout and 'HOST_CHECK_SHOULD_NOT_RUN' not in result.stdout
