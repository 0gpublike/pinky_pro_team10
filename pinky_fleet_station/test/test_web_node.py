"""웹 경계 입력과 연결 소실 정책을 실제 ROS 통신 없이 검사한다."""
import time
from types import SimpleNamespace
import pytest
from pinky_fleet_station.web_node import WebNode, validate_command

SPEC = {'max_linear_vel': .2, 'max_angular_vel': 1.5}

@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, '1', None])
def test_invalid_pose(value):
    with pytest.raises(ValueError):
        validate_command(dict(action='goto', x=value, y=0, yaw=0), SPEC)

@pytest.mark.parametrize('value', [0, -.1, .21])
def test_speed_limit(value):
    with pytest.raises(ValueError):
        validate_command(dict(action='speed', max_linear_vel=value, max_angular_vel=1), SPEC)

def test_cancel_needs_no_coordinates():
    assert validate_command({'action': 'cancel'}, SPEC) == ('cancel', {})

def test_disconnect_cancels_once():
    calls = []
    node = SimpleNamespace(owner='browser', deadline=time.monotonic()-1,
                           cancel_all=lambda: calls.append('cancel'))
    WebNode.watch_session(node)
    WebNode.watch_session(node)
    assert calls == ['cancel']
    assert node.owner is None

def test_session_is_exclusive():
    node = SimpleNamespace(owner='a'*16, deadline=time.monotonic()+3, watch_session=lambda: None)
    with pytest.raises(ValueError, match='다른 브라우저'):
        WebNode.command(node, {'action': 'claim', 'session': 'b'*16})

def test_expired_session_cannot_send():
    node = SimpleNamespace(owner=None, watch_session=lambda: None)
    with pytest.raises(ValueError, match='먼저'):
        WebNode.command(node, {'action': 'goto', 'session': 'a'*16})


def test_batch_failure_publishes_nothing():
    calls = []
    specs = [dict(name=n, goal=dict(x=0, y=0, yaw=0)) for n in ['a', 'b']]
    def ready(name, action):
        if name == 'b':
            raise ValueError('offline')
    node = SimpleNamespace(owner='a'*16, watch_session=lambda: None,
                           mission=SimpleNamespace(by_priority=lambda: specs),
                           require_ready=ready, publish=lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match='offline'):
        WebNode.command(node, dict(action='goto_all', session='a'*16))
    assert calls == []


def test_failed_map_load_preserves_current_map(tmp_path):
    node = SimpleNamespace(read_map=lambda path: WebNode.read_map(None, path),
                           map_info={'name': 'original'}, map_png=b'old')
    with pytest.raises(OSError):
        WebNode.load_map(node, str(tmp_path / 'missing.yaml'))
    assert node.map_info == {'name': 'original'}
    assert node.map_png == b'old'


def test_mission_draft_rejects_changed_topic_without_mutation():
    from pinky_fleet_station.mission_io import Mission
    mission = Mission({'robots': [{'name': 'a', 'domain_id': 1}, {'name': 'b', 'domain_id': 2}]})
    incoming = mission.to_dict()
    incoming['robots'][0]['command_topic'] = '/unexpected'
    node = SimpleNamespace(mission=mission)
    with pytest.raises(ValueError, match='토픽'):
        WebNode.apply_draft(node, incoming)
    assert node.mission.robot('a')['command_topic'] == '/a/command'


@pytest.mark.parametrize('action', ['draft', 'mission_load', 'map_open', 'map_reload'])
def test_file_edit_without_control_session(action):
    calls = []
    node = SimpleNamespace(owner=None, watch_session=lambda: None,
                           mission=SimpleNamespace(map_yaml_path='/map.yaml'),
                           apply_draft=lambda data: calls.append(data),
                           load_map=lambda path: calls.append(path))
    WebNode.command(node, dict(action=action, session='browser-session-123',
                              mission={}, text='{}', path='/map.yaml'))
    assert len(calls) == 1
    assert node.owner is None


def test_file_edit_cannot_override_another_operator():
    node = SimpleNamespace(owner='another-operator', watch_session=lambda: None)
    with pytest.raises(ValueError, match='다른 브라우저'):
        WebNode.command(node, dict(action='map_open', session='browser-session-123'))


def test_unknown_battery_is_json_null():
    import json
    msg = SimpleNamespace(battery_percent=float('nan'),
                          get_fields_and_field_types=lambda: {'battery_percent':'float'})
    node = SimpleNamespace(states={})
    WebNode.on_state(node, 'pinky1', msg)
    assert json.dumps(node.states['pinky1'][0], allow_nan=False) == '{"battery_percent": null}'
