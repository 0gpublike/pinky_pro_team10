from types import SimpleNamespace
import pytest
from pinky_fleet_station.web_manager import Runtime


def test_reject_mode_change_while_running():
    runtime = SimpleNamespace(phase='running')
    with pytest.raises(ValueError, match='종료'):
        Runtime.start(runtime, 'real')


def test_rqt_requires_environment():
    with pytest.raises(ValueError, match='시작'):
        Runtime.open_rqt(SimpleNamespace(phase='idle'))


def test_rqt_not_duplicated():
    runtime = SimpleNamespace(phase='running', processes={'rqt':SimpleNamespace(poll=lambda:None)})
    Runtime.open_rqt(runtime)


def test_stop_does_not_block():
    signals = []
    runtime = SimpleNamespace(phase='running', signal_all=signals.append)
    Runtime.stop(runtime)
    assert runtime.phase == 'stopping'
    assert len(signals)==1


def test_stop_waits_for_children():
    runtime = SimpleNamespace(phase='stopping', groups_alive=lambda:False,
                              processes={'station':object()}, mode='sim')
    Runtime.tick(runtime)
    assert runtime.phase=='idle' and runtime.mode is None
    assert runtime.processes=={}


def test_simulation_namespaces_keep_distinct_configuration():
    from pathlib import Path
    import yaml
    import xml.etree.ElementTree as ET
    root = Path(__file__).resolve().parents[1]
    fleet = ET.parse(root/'launch/web_gz_fleet.launch.xml').getroot()
    groups = fleet.find('timer').findall('group')
    assert len(groups) == 2 and all(g.get('scoped') == 'true' for g in groups)
    for name in ('pinky1','pinky2'):
        params = yaml.safe_load((root/f'config/web_nav2_{name}.yaml').read_text())
        assert list(params) == [name]
        controller = params[name]['controller_server']['ros__parameters']
        assert controller['FollowPath']['plugin'] == 'nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController'


def test_agent_does_not_relay_plan_to_itself():
    from pathlib import Path
    import xml.etree.ElementTree as ET
    root = ET.parse(Path(__file__).resolve().parents[1]/'launch/web_gz_robot.launch.xml').getroot()
    assert root.find(".//arg[@name='plan_in_topic']").get('value') == 'nav_plan'
    assert len(root.findall(".//set_remap[@from='/tf']")) == 1
