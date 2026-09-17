"""웹 관제: HTTP 요청과 ROS 콜백을 한 스레드에서 순서대로 처리한다.

브라우저 → JSON 요청 → FleetCommand → 기존 domain_bridge → 로봇 agent.
추가 웹 프레임워크 없이 Python 표준 라이브러리를 사용한다.
"""
import os
import io
import json
import math
from pathlib import Path
import time
import signal
from urllib.parse import urlsplit, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image
import yaml
import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from nav_msgs.msg import Path as RosPath
from std_msgs.msg import String
from pinky_fleet_msgs.msg import FleetCommand, RobotState
from .mission_io import load_mission, Mission, resolve_map_path


def validate_command(data, spec):
    """허용한 명령과 유한한 숫자만 ROS에 전달한다. STOP/RESUME은 coordinator 전용."""
    action = data.get('action')
    fields = {'goto': ('x', 'y', 'yaw'), 'initial': ('x', 'y', 'yaw'),
              'cancel': (), 'speed': ('max_linear_vel', 'max_angular_vel')}
    if action not in fields:
        raise ValueError('지원하지 않는 명령입니다.')
    values = {}
    for key in fields[action]:
        raw = data.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f'{key}: 숫자가 필요합니다.')
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError('유한한 숫자만 입력하세요.')
        if action == 'speed' and not 0 < value <= spec[key]:
            raise ValueError(f'{key}: 0 초과, 미션 설정값 {spec[key]} 이하로 입력하세요.')
        values[key] = value
    return action, values


class WebNode(Node):
    def __init__(self):
        super().__init__('fleet_web')
        self.declare_parameter('mission', '')
        self.declare_parameter('port', 8080)
        self.declare_parameter('fake', False)
        self.mission = load_mission(self.get_parameter('mission').value)
        self.states, self.paths, self.pubs = {}, {}, {}
        self.owner, self.deadline = None, 0
        self.coordinator = None
        self.map_info, self.map_png, self.map_error = None, b'', ''
        self.revision = 0
        self.speed_limits = {r['name']: dict(r) for r in self.mission.robots}
        try:
            self.load_map(self.mission.map_yaml_path)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.map_error = f'맵 로드 실패: {exc}'
        for spec in self.mission.robots:
            name = spec['name']
            self.pubs[name] = self.create_publisher(FleetCommand, spec['command_topic'], 10)
            self.create_subscription(RobotState, spec['state_topic'],
                                     lambda msg, n=name: self.on_state(n, msg), 10)
            self.create_subscription(RosPath, spec['plan_topic'],
                                     lambda msg, n=name: self.paths.__setitem__(n, [
                                         [p.pose.position.x, p.pose.position.y] for p in msg.poses]), 10)
        self.create_subscription(String, '/fleet/coordinator_status', self.on_coordinator, 10)
        self.create_timer(0.2, self.watch_session)
        self.create_timer(1.0, self.heartbeat)

    def read_map(self, filename):
        """검증에 성공한 뒤에만 현재 맵을 교체하도록 임시 결과를 반환한다."""
        path = Path(resolve_map_path(filename)).resolve()
        meta = yaml.safe_load(path.read_text())
        if not isinstance(meta, dict):
            raise ValueError('맵 YAML은 매핑이어야 합니다.')
        resolution = float(meta['resolution'])
        origin = list(map(float, meta['origin']))
        if len(origin) != 3 or resolution <= 0 or not all(math.isfinite(v) for v in [resolution, *origin]):
            raise ValueError('맵 resolution/origin을 확인하세요.')
        with Image.open(path.parent / meta['image']) as source:
            img = source.convert('RGB')
        output = io.BytesIO()
        img.save(output, format='PNG')
        return (dict(name=path.stem, width=img.width, height=img.height,
                     resolution=resolution, origin=origin), output.getvalue(), str(path))

    def load_map(self, filename):
        info, png, path = self.read_map(filename)
        self.map_info, self.map_png, self.map_error = info, png, ''
        self.mission.map_yaml_path = path
        self.paths.clear()
        self.revision += 1

    def apply_draft(self, data):
        """편집값만 저장한다. 이 함수는 로봇을 움직이지 않는다."""
        candidate = Mission(data)
        current = self.mission.to_dict()
        incoming = candidate.to_dict()
        # 실행 중인 coordinator와 bridge의 설정은 웹 편집으로 바꿀 수 없다.
        for key in ('defaults', 'coordinator'):
            if incoming[key] != current[key]:
                raise ValueError(f'{key} 변경은 launch 재시작이 필요합니다.')
        if [r['name'] for r in candidate.robots] != [r['name'] for r in self.mission.robots]:
            raise ValueError('로봇 구성 변경은 launch 재시작이 필요합니다.')
        for r in candidate.robots:
            old = self.mission.robot(r['name'])
            for key in ('domain_id', 'state_topic', 'command_topic', 'plan_topic'):
                if r[key] != old[key]:
                    raise ValueError('도메인/토픽 변경은 launch 재시작이 필요합니다.')
            for field in ('goal', 'initial_pose'):
                validate_command(dict(action='goto', **r[field]), old)
            validate_command(dict(action='speed', **{k: r[k] for k in
                             ('max_linear_vel', 'max_angular_vel')}), self.speed_limits[r['name']])
        prepared = self.read_map(candidate.map_yaml_path)
        self.mission = candidate
        self.map_info, self.map_png, self.mission.map_yaml_path = prepared
        self.map_error = ''
        self.paths.clear()
        self.revision += 1

    def require_ready(self, name, action):
        problem = self.problem(name)
        if problem:
            raise ValueError(f'{name}: {problem}')
        if action == 'goto' and not self.states[name][0]['localized']:
            raise ValueError(f'{name}: 초기 위치를 지정하고 위치 추정을 기다리세요.')

    def on_state(self, name, msg):
        data = {key: getattr(msg, key) for key in msg.get_fields_and_field_types() if key != 'header'}
        # 실제 agent는 배터리 미지원 시 NaN을 보낸다. JSON에는 NaN이 없어 null로 표현한다.
        if not math.isfinite(data['battery_percent']):
            data['battery_percent'] = None
        self.states[name] = (data, time.monotonic())

    def on_coordinator(self, msg):
        try:
            self.coordinator = json.loads(msg.data)
        except ValueError:
            self.coordinator = None

    def publish(self, name, command, **fields):
        msg = FleetCommand()
        msg.command = command
        for key, value in fields.items():
            setattr(msg, key, value)
        self.pubs[name].publish(msg)

    def cancel_all(self):
        for name in self.pubs:
            self.publish(name, FleetCommand.CMD_CANCEL)

    def watch_session(self):
        # coordinator도 하트비트를 보내므로, 브라우저 소실 시 CANCEL을 직접 보낸다.
        if self.owner and time.monotonic() >= self.deadline:
            self.cancel_all()
            self.owner = None

    def heartbeat(self):
        if self.owner and time.monotonic() < self.deadline:
            for name in self.pubs:
                self.publish(name, FleetCommand.CMD_HEARTBEAT)

    def problem(self, name):
        pair = self.states.get(name)
        if not pair or time.monotonic() - pair[1] > 2:
            return '로봇 상태 수신이 끊겼습니다.'
        if not self.map_info:
            return self.map_error
        s, m = pair[0], self.map_info
        if self.get_parameter('fake').value:
            return ''  # 명시적 테스트 실행에만 적용: 가짜 노드는 맵 규격을 발행하지 않는다.
        if not s['map_known']:
            return '로봇의 맵 정보를 기다리는 중입니다.'
        if s['map_name'] and s['map_name'] != m['name']:
            return '맵 이름 불일치'
        expected = {'map_width': m['width'], 'map_height': m['height'],
                    'map_resolution': m['resolution'], 'map_origin_x': m['origin'][0],
                    'map_origin_y': m['origin'][1]}
        if any(not math.isclose(s[k], v, abs_tol=1e-5) for k, v in expected.items()):
            return '맵 규격 불일치'
        return ''

    def snapshot(self):
        return dict(robots=[dict(spec=s, state=self.states.get(s['name'], (None,))[0],
                                problem=self.problem(s['name']), path=self.paths.get(s['name'], []))
                            for s in self.mission.robots], map=self.map_info,
                    map_error=self.map_error, coordinator=self.coordinator,
                    mission=self.mission.to_dict(), revision=self.revision,
                    simulated=self.get_parameter('fake').value or 'fake_state_pub' in self.get_node_names())

    def command(self, data):
        self.watch_session()
        session = data.get('session')
        if not isinstance(session, str) or not 16 <= len(session) <= 100:
            raise ValueError('유효한 조작 세션이 필요합니다.')
        if data.get('action') == 'claim':
            if self.owner and self.owner != session:
                raise ValueError('다른 브라우저가 조작 중입니다.')
            self.owner, self.deadline = session, time.monotonic() + 3
            return
        editing = data.get('action') in ('draft', 'mission_load', 'map_open', 'map_reload')
        if editing and self.owner and self.owner != session:
            raise ValueError('다른 브라우저가 조작 중입니다. 파일 변경은 조작 해제 후 가능합니다.')
        if not editing and self.owner != session:
            raise ValueError('먼저 조작 연결 버튼을 누르세요.')
        if data.get('action') == 'pulse':
            self.deadline = time.monotonic() + 3
            return
        if data.get('action') == 'release':
            self.cancel_all()
            self.owner = None
            return
        if data.get('action') == 'cancel_all':
            self.cancel_all()
            return
        action = data.get('action')
        if action in ('draft', 'mission_load'):
            content = data.get('mission')
            if action == 'mission_load':
                content = yaml.safe_load(data.get('text', ''))
            if not isinstance(content, dict):
                raise ValueError('미션 YAML은 매핑이어야 합니다.')
            self.apply_draft(content)
            return
        if action in ('map_open', 'map_reload'):
            self.load_map(data.get('path') if action == 'map_open' else self.mission.map_yaml_path)
            return
        if action == 'map_send':
            if not self.map_info:
                raise ValueError('먼저 맵을 여세요.')
            self.cancel_all()
            for name in self.pubs:
                self.publish(name, FleetCommand.CMD_SET_MAP, map_name=self.map_info['name'])
            return
        if action in ('goto_all', 'initial_all'):
            kind = 'goto' if action == 'goto_all' else 'initial'
            # 하나라도 검증에 실패하면 아무 로봇에도 전송하지 않는다.
            commands = []
            for spec in self.mission.by_priority():
                self.require_ready(spec['name'], kind)
                pose = spec['goal' if kind == 'goto' else 'initial_pose']
                _, fields = validate_command(dict(action=kind, **pose), spec)
                commands.append((spec['name'], fields))
            for name, fields in commands:
                self.publish(name, FleetCommand.CMD_GOTO if kind == 'goto' else
                             FleetCommand.CMD_SET_INITIAL_POSE, **fields)
            return
        name = data.get('robot')
        if name not in self.pubs:
            raise ValueError('등록되지 않은 로봇입니다.')
        action, fields = validate_command(data, self.speed_limits[name])
        if action != 'cancel':
            self.require_ready(name, action)
        codes = dict(goto=FleetCommand.CMD_GOTO, initial=FleetCommand.CMD_SET_INITIAL_POSE,
                     cancel=FleetCommand.CMD_CANCEL, speed=FleetCommand.CMD_SET_SPEED)
        self.publish(name, codes[action], **fields)


def handler_for(node):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(0.25)

        def log_message(self, *_):
            pass

        def reply(self, code, data, mime='application/json'):
            body = json.dumps(data, ensure_ascii=False).encode() if mime == 'application/json' else data
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            if mime.startswith('application/yaml'):
                self.send_header('Content-Disposition', 'attachment; filename=mission_web.yaml')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',
                                                f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {'error': '잘못된 Host'})
            if self.path.startswith('/api/files?'):
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    directory = Path(os.path.expandvars(os.path.expanduser(query.get('path', [str(Path.home())])[0]))).resolve()
                    entries = []
                    for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                        if item.name.startswith('.'):
                            continue
                        if item.is_dir() or item.suffix.lower() in ('.yaml', '.yml'):
                            entries.append(dict(name=item.name, path=str(item), directory=item.is_dir()))
                        if len(entries) >= 1000:
                            break
                    return self.reply(200, dict(path=str(directory), parent=str(directory.parent), entries=entries))
                except OSError as exc:
                    return self.reply(400, {'error': str(exc)})
            if self.path == '/':
                return self.reply(200, Path(__file__).with_name('web.html').read_bytes(), 'text/html; charset=utf-8')
            if self.path == '/api/mission.yaml':
                return self.reply(200, yaml.safe_dump(node.mission.to_dict(), allow_unicode=True, sort_keys=False).encode(), 'application/yaml; charset=utf-8')
            if self.path in ('/web.js', '/web.css'):
                mime = 'text/javascript' if self.path.endswith('.js') else 'text/css'
                return self.reply(200, Path(__file__).with_name(self.path[1:]).read_bytes(), mime)
            if self.path == '/api/state':
                return self.reply(200, node.snapshot())
            if self.path.split('?')[0] == '/map.png' and node.map_png:
                return self.reply(200, node.map_png, 'image/png')
            self.reply(404, {'error': '없는 경로'})

        def do_POST(self):
            if (not self.valid_host() or self.headers.get('Origin') != 'http://' + self.headers.get('Host', '')
                    or self.headers.get('Content-Type') != 'application/json'):
                return self.reply(403, {'error': '같은 주소의 관제 화면에서 요청하세요.'})
            if self.path != '/api/command':
                return self.reply(404, {'error': '없는 경로'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 262144:
                    raise ValueError('요청 크기 초과')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('JSON 객체가 필요합니다.')
                node.command(data)
                self.reply(200, {'ok': True, 'message': '명령 발행됨 (완료 여부는 로봇 상태 확인)'})
            except (ValueError, TypeError, OSError, KeyError, yaml.YAMLError) as exc:
                self.reply(400, {'error': str(exc)})
    return Handler


def main(args=None):
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    node = WebNode()
    server = HTTPServer(('127.0.0.1', node.get_parameter('port').value), handler_for(node))
    server.timeout = 0.01
    print(f'웹 관제: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.01)
            node.watch_session()
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.cancel_all()
        server.server_close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
