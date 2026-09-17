"""웹 입구는 유지하고 선택한 연습 환경의 ROS 프로세스만 시작/종료한다.

ROS_DOMAIN_ID는 실행 전에 정해진다. 그래서 모드 전환은 환경변수만 바꾸는
동작이 아니라 기존 프로세스를 종료한 뒤 새 도메인으로 다시 실행하는 동작이다.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from ament_index_python.packages import get_package_share_directory
from .mission_io import load_mission


class Runtime:
    def __init__(self, sim_mission, real_mission, backend_port):
        self.missions = {'sim': sim_mission, 'real': real_mission}
        self.backend_port = backend_port
        self.mode = None
        self.phase = 'idle'
        self.error = ''
        self.processes = {}
        self.log_dir = Path(tempfile.mkdtemp(prefix='pinky-web-runtime-'))
        self.deadline = 0
        self.stop_stage = 0

    def spawn(self, name, args):
        env = os.environ.copy()
        env['ROS_DOMAIN_ID'] = '77' if self.mode == 'sim' else '0'
        # launch가 자식들을 생성해도 같은 프로세스 그룹으로 함께 종료할 수 있다.
        with (self.log_dir / (name + '.log')).open('ab') as log:
            process = subprocess.Popen(args, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        self.processes[name] = process

    def start(self, mode):
        if self.phase != 'idle':
            raise ValueError('현재 환경을 종료한 뒤 모드를 선택하세요.')
        if mode not in self.missions:
            raise ValueError('지원하지 않는 모드입니다.')
        required = ['pinky_fleet_station', 'domain_bridge'] if mode == 'real' else ['pinky_fleet_station', 'pinky_fleet_sim', 'pinky_fleet_agent', 'pinky_navigation', 'pinky_description', 'pinky_gz_sim', 'ros_gz_bridge', 'ros_gz_sim', 'rviz2']
        for package in required:
            try:
                get_package_share_directory(package)
            except LookupError as exc:
                raise ValueError(f'{package} 패키지를 빌드/설치한 뒤 웹 관리자를 재시작하세요.') from exc
        mission = self.missions[mode]
        load_mission(mission)  # 누락된 설정은 프로세스를 띄우기 전에 검출
        if mode == 'sim' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            raise ValueError('Gazebo/RViz를 표시할 데스크톱 세션이 없습니다.')
        self.mode, self.phase, self.error = mode, 'starting', ''
        self.deadline = time.monotonic() + 120
        try:
            self.spawn('station', ['ros2', 'launch', 'pinky_fleet_station', 'web_fleet.launch.xml',
                       'fake:=False', f'use_bridge:={"True" if mode == "real" else "False"}',
                       f'mission:={mission}', f'port:={self.backend_port}'])
            if mode == 'sim':
                self.spawn('gazebo', ['ros2', 'launch', 'pinky_fleet_station', 'web_gz_fleet.launch.xml'])
                self.spawn('rviz_tf', ['ros2', 'run', 'pinky_fleet_station', 'rviz_tf'])
                config = Path(get_package_share_directory('pinky_fleet_station')) / 'config' / 'fleet_web.rviz'
                self.spawn('rviz', ['ros2', 'run', 'rviz2', 'rviz2', '-d', str(config),
                                    '--ros-args', '-p', 'use_sim_time:=true', '-r', '/tf:=/fleet_view/tf', '-r', '/tf_static:=/fleet_view/tf_static'])
        except Exception as exc:
            self.error = str(exc)
            self.stop()
            raise ValueError(str(exc)) from exc

    def open_rqt(self):
        if self.phase != 'running':
            raise ValueError('먼저 연습 환경을 시작하세요.')
        if 'rqt' in self.processes and self.processes['rqt'].poll() is None:
            return
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            raise ValueError('rqt를 표시할 데스크톱 세션이 없습니다.')
        self.spawn('rqt', ['ros2', 'run', 'rqt_gui', 'rqt_gui'])

    def signal_all(self, sig):
        for process in self.processes.values():
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass

    def stop(self):
        if self.phase == 'idle':
            return
        self.phase, self.stop_stage = 'stopping', 0
        self.signal_all(signal.SIGINT)
        self.deadline = time.monotonic() + 8

    def groups_alive(self):
        alive = False
        for process in self.processes.values():
            process.poll()  # 종료된 직접 자식 회수
            try:
                os.killpg(process.pid, 0)
                alive = True
            except ProcessLookupError:
                pass
        return alive

    def tick(self):
        now = time.monotonic()
        if self.phase == 'stopping':
            if not self.groups_alive():
                self.processes.clear()
                self.phase, self.mode = 'idle', None
            elif now > self.deadline:
                self.signal_all(signal.SIGTERM if self.stop_stage == 0 else signal.SIGKILL)
                self.stop_stage += 1
                self.deadline = now + 3
        elif self.phase in ('starting', 'running'):
            for name in ('station', 'gazebo'):
                process = self.processes.get(name)
                if process and process.poll() is not None:
                    self.error = f'{name} 종료. 로그: {self.log_dir / (name + ".log")}'
                    self.stop()
                    return
            if self.phase == 'starting':
                try:
                    with urlopen(f'http://127.0.0.1:{self.backend_port}/api/state', timeout=.15):
                        self.phase = 'running'
                except (OSError, URLError):
                    if now > self.deadline:
                        self.error = '웹 관제 연결 시간 초과. 로그를 확인하세요.'
                        self.stop()

    def status(self):
        self.tick()
        return dict(mode=self.mode, phase=self.phase, error=self.error,
                    log_dir=str(self.log_dir), missions=self.missions,
                    processes={name: p.poll() for name, p in self.processes.items()})


def make_handler(runtime, port):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(1)

        def log_message(self, *_):
            pass

        def reply(self, status, body, mime='application/json', attachment=None):
            if mime == 'application/json' and not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            if attachment:
                self.send_header('Content-Disposition', attachment)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                return self.reply(403, {'error': '잘못된 Host'})
            if self.path == '/api/runtime':
                return self.reply(200, runtime.status())
            if self.path in ('/', '/web.js', '/web.css'):
                filename = 'web.html' if self.path == '/' else self.path[1:]
                mime = {'web.html': 'text/html; charset=utf-8', 'web.js': 'text/javascript', 'web.css': 'text/css'}[filename]
                return self.reply(200, Path(__file__).with_name(filename).read_bytes(), mime)
            self.proxy()

        def do_POST(self):
            host = self.headers.get('Host')
            if (host not in (f'127.0.0.1:{port}', f'localhost:{port}') or
                    self.headers.get('Origin') != f'http://{host}' or
                    self.headers.get('Content-Type') != 'application/json'):
                return self.reply(403, {'error': '같은 주소에서 요청하세요.'})
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 262144:
                    raise ValueError('요청 크기를 확인하세요.')
                body = self.rfile.read(size)
                if self.path == '/api/runtime':
                    data = json.loads(body)
                    if data.get('action') == 'start':
                        runtime.start(data.get('mode'))
                    elif data.get('action') == 'stop':
                        runtime.stop()
                    elif data.get('action') == 'rqt':
                        runtime.open_rqt()
                    else:
                        raise ValueError('알 수 없는 실행 요청')
                    return self.reply(200, runtime.status())
                self.proxy(body)
            except (ValueError, OSError, TypeError, AttributeError) as exc:
                self.reply(400, {'error': str(exc)})

        def proxy(self, body=None):
            if runtime.phase != 'running':
                return self.reply(503, {'error': '연습 환경을 먼저 시작하세요.'})
            base = f'http://127.0.0.1:{runtime.backend_port}'
            request = Request(base + self.path, data=body,
                              headers={'Origin': base, 'Content-Type': 'application/json'})
            try:
                response = urlopen(request, timeout=2)
            except HTTPError as exc:
                response = exc
            except OSError:
                return self.reply(503, {'error': '관제 연결을 기다리는 중입니다.'})
            with response:
                self.reply(response.status, response.read(), response.headers.get('Content-Type'),
                           response.headers.get('Content-Disposition'))
    return Handler


def main():
    share = Path(get_package_share_directory('pinky_fleet_station'))
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--backend-port', type=int, default=8082)
    parser.add_argument('--sim-mission', default=str(share / 'config/mission_web.yaml'))
    parser.add_argument('--real-mission', default=str(share / 'config/mission_real_web.yaml'))
    args = parser.parse_args()
    runtime = Runtime(args.sim_mission, args.real_mission, args.backend_port)
    server = HTTPServer(('127.0.0.1', args.port), make_handler(runtime, args.port))
    server.timeout = .2
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        print(f'통합 웹 관제 http://127.0.0.1:{args.port}', flush=True)
        while True:
            runtime.tick()
            server.handle_request()
    except KeyboardInterrupt:
        runtime.stop()
        until = time.monotonic() + 16
        while runtime.phase != 'idle' and time.monotonic() < until:
            runtime.tick()
            time.sleep(.1)
        runtime.signal_all(signal.SIGKILL)
    finally:
        server.server_close()
