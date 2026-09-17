# Pinky 웹 관제 첫 버전

## 실행 (가짜 로봇으로 연습)

```bash
cd $HOME/pinky_web_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select pinky_fleet_station --symlink-install
source install/setup.bash
# 실제 로봇과 분리된 연습용 도메인. 같은 도메인의 다른 노드가 없는지 확인하세요.
export ROS_DOMAIN_ID=77
ros2 launch pinky_fleet_station web_fleet.launch.xml
```

브라우저에서 http://127.0.0.1:8080 을 연다. 기본 실행은 가짜 로봇 2대와
coordinator, 웹 서버를 띄운다. Gazebo 물리 시뮬레이션은 아니다.
`mission_web.yaml`은 package:// 주소로 설치된 fleet_arena 맵을 찾는다.

1. **조작 연결**: 이 브라우저가 조작권을 얻는다. 다른 탭은 조회만 가능하다.
2. 지도 위에서 로봇을 선택하고 누른 채 드래그한다. 시작점은 위치, 방향은 yaw다.
3. 오른쪽 **목표로 출발** 또는 **초기 위치 전송**으로 실제 명령을 보낸다.
4. **주행 취소**는 기존 GUI의 정지와 같은 CMD_CANCEL이다. 하드웨어 비상정지가 아니다.
5. **연결 해제**는 전체 주행을 취소하고 조작권을 반환한다.

좌표 단위는 m, 방향은 rad다. 0 rad는 맵의 +X 방향, 약 1.57 rad는 +Y 방향이다.
직진 속도는 m/s, 회전 속도는 rad/s다. 웹에서 설정할 수 있는 속도 상한은
mission 파일의 각 로봇 설정값이다.

## 코드 읽는 순서

- `pinky_fleet_station/web.html`: 화면 구조. `web.js`의 `poll()`은 250ms마다 상태를 요청한다.
  `command()`는 버튼 입력을 JSON으로 보낸다. `worldToPixel()`과 `pixelToWorld()`는
  로봇의 미터 좌표와 화면 픽셀 좌표를 변환한다. 지도 원점 회전도 반영한다.
- `pinky_fleet_station/web_node.py`: 서버와 ROS 사이의 어댑터.
  `on_state()`는 로봇 상태를 저장하고 `snapshot()`은 웹에 보낼 데이터를 만든다.
  `validate_command()`는 입력값을 검사하고 `publish()`는 기존 FleetCommand를 발행한다.
- 기존 `mission_io.py`: 미션 YAML을 읽는 공통 코드. 새 서버도 공유하며, 다른 PC에서 맵을 찾기 위한 package:// 경로 해석이 추가되었다.
- 기존 `coordinator_node.py`: 로봇 간 교착 제어. 웹으로 옮겨도 이 노드가 계속 담당한다.

예를 들어 출발 버튼을 누르면 다음 순서다.

브라우저 → POST /api/command → 입력·연결·맵 검사 → CMD_GOTO 발행 →
domain_bridge(실기) → agent → Nav2. 응답의 '명령 발행됨'은 도착을 뜻하지 않는다.
도착 여부는 로봇이 보내는 nav_status로 확인한다.

HTTP 요청과 ROS 콜백은 한 스레드에서 번갈아 처리하므로 공유 데이터의 동시 수정이 없다.
현재는 단일 PC용 Python 표준 HTTP 서버다. 외부 공개용 서버는 아니다.

## 연결과 정지

브라우저는 0.7초마다 조작 세션을 갱신한다. 3초 동안 갱신이 없으면 서버가
전체 CANCEL을 발행하고 조작권을 해제한다. 재접속 시 자동 출발하지 않는다.
백그라운드 탭 절전도 연결 끊김으로 판단할 수 있다.

**서버 프로세스 강제 종료·PC 전원 차단 시에는 서버가 CANCEL을 보낼 수 없다.**
기존 robot agent의 데드맨이 동작하려면 coordinator를 포함한 모든 하트비트가
끊겨야 한다. coordinator만 살아 있는 서버 장애까지 정지를 보장하려면 기존
하트비트 구조도 추가 변경해야 한다. 정상 Ctrl+C/SIGTERM에서는 취소를 발행한다.
웹 관제와 기존 PyQt 관제를 동시에 조작하지 않는다(조작권은 웹 클라이언트끼리만 적용).

## 실기 연결

가짜 로봇 연습을 종료한 뒤 실제 로봇과 같은 맵을 가리키는 별도 미션 YAML을 만든다.
기존 mission.yaml에는 다른 PC 경로가 있으므로 그대로 사용하지 않는다.

```bash
export ROS_DOMAIN_ID=0
ros2 launch pinky_fleet_station web_fleet.launch.xml \
  fake:=False use_bridge:=True mission:=/절대경로/실기미션.yaml
```

기존 방식대로 로봇의 agent/Nav2가 먼저 실행되어 있어야 한다.
실기 모드에서는 상태 2초 초과 미수신, 맵 정보 없음, 맵 이름/규격 불일치 시
주행 관련 명령을 거부한다. 가짜 노드는 맵 규격을 제공하지 않아 fake 모드에서만
그 검사를 생략한다. 실기에서 fake:=True로 실행하지 않는다.

## 추가된 웹 기능

- 목표와 초기 위치 각각의 좌표·방향 입력란, 드래그 중 노란 방향 화살표와 각도 표시.
- 드래그 완료 후 목표는 실선, 초기 위치는 점선 화살표로 유지. 단순 클릭은 기존 방향을 유지한다.
- 초기 위치 선택 후에는 **초기 위치 전송**을 눌러 적용한다. 기존 PyQt의 자동 전송과 다르다.
- 동시 출발, 초기 위치 일괄 전송, 배터리, 현재 실행 중인 목표 표시.
- 휠/버튼 확대·축소, 지도 이동 모드에서 드래그, 화면에 맞추기.
- 맵 경로를 입력해 열기/다시 읽기. 로봇 전송은 별도 버튼이며 파일 업로드가 아니라 맵 이름 전송이다.
- 미션 YAML 불러오기와 다운로드. 다운로드는 현재 편집 중인 목표·초기 위치·속도를 포함한다.

미션 파일의 로봇 구성·도메인·토픽·coordinator 설정 변경은 실행 중에 적용하지 않는다.
해당 설정을 바꾸려면 새 YAML을 지정해 launch를 재시작한다.
속도 상한은 서버 시작 시 미션 값으로 고정된다. 미션 다운로드는 브라우저의 다운로드 폴더에
새 파일을 저장하며 기존 파일을 덮어쓰는 서버 API는 제공하지 않는다.

## 방향 화살표 코드 설명

화면 코드를 읽기 쉽도록 `web.html`(구조), `web.css`(색·배치), `web.js`(동작)로 나눴다.
`web.js`의 `draft`는 사용자가 편집 중인 미션이다.
각 로봇의 `goal`과 `initial_pose`가 따로 있어 초기 위치 변경이 목표를 덮어쓰지 않는다.

`onpointerdown`이 드래그 시작 좌표를 기억하고 `onpointermove`가
`Math.atan2(끝Y - 시작Y, 끝X - 시작X)`로 yaw를 계산한다.
`arrow()`는 그 yaw로 화살표 끝점을 계산해 캔버스에 그린다.
`onpointerup`은 선택한 좌표와 방향을 draft에 저장한다. 이 단계에서는 로봇이 움직이지 않는다.

`syncDraft()`는 편집값을 서버의 `apply_draft()`에 보내 검증한다.
검증이 성공해야 출발/초기 위치 전송이 이어진다. `goto_all`은 모든 로봇의 상태를
먼저 확인하므로 한 로봇이라도 준비되지 않으면 전송을 시작하지 않는다.

## 이번 업데이트 검증

초기 웹 기능 검증에서는 자동 테스트 28개가 통과했다. 브라우저에서 두 로봇 동시 출발/취소, 목표 방향 40.6도,
초기 위치 방향 -143.1도 분리 및 초기 위치 전송을 확인했다.
실행 중인 테스트 서버에 YAML 저장·불러오기 왕복, 없는 맵 열기 실패 시 기존 맵 유지,
맵 재로드/이름 전송 및 일괄 명령 API를 확인했다. 실제 로봇 검증은 아직 하지 않았다.

## 파일 작업 오류 수정

미션 불러오기·다운로드와 맵 열기는 조작 연결 없이 사용할 수 있다.
단, 다른 브라우저가 조작 중이면 공유 설정 변경을 막는다. 로봇 명령은 계속 조작 연결이 필요하다.
맵 파일 선택 버튼은 관제 PC의 폴더 목록을 열고 YAML을 선택하면 대응하는 이미지도 읽는다.
다운로드는 서버가 Content-Disposition: attachment로 응답한다.
미션 불러오기가 완료되면 파일 이름이 화면에 남는다.

## 실물 / Gazebo 통합 실행 화면

처음 설치하는 팀원은 먼저 [팀원용 설치 안내](../docs/WEB_SETUP.md)를 따른다.
아래 경로는 예시 워크스페이스이며 다른 위치를 사용해도 된다.

```bash
source /opt/ros/jazzy/setup.bash
source $HOME/pinky_web_ws/install/setup.bash
ros2 run pinky_fleet_station web_manager
```

http://127.0.0.1:8080 에서 연습 환경을 선택하고 시작한다.
Gazebo 모드는 도메인 77에서 가상 로봇 두 대, Nav2, 관제, Gazebo GUI, RViz를 실행한다.
실물 모드는 도메인 0의 관제와 도메인 10/11 브리지만 실행한다. 로봇의 bringup/Nav2/agent는
로봇에서 먼저 실행해야 한다. 실물 모드를 시작하는 것만으로 출발 명령은 보내지 않는다.

rqt는 **rqt 열기** 버튼으로 실행한다. 이미 열려 있으면 중복 실행하지 않는다.
rqt에서 Plugins 메뉴의 Configuration / Dynamic Reconfigure 도구 등으로 노드 파라미터를
확인할 수 있다(설치된 플러그인에 따라 메뉴가 다를 수 있다).
Gazebo/RViz/rqt 창은 웹 서버가 실행되는 PC의 데스크톱에 뜬다.

**연습 환경 종료**는 이 관리자가 시작한 프로세스 그룹만 종료한다. 종료 중에는 다른 환경을
시작할 수 없다. 실물 로봇 자체의 프로세스를 원격 종료하지 않는다.
브라우저를 닫아도 환경 관리자는 계속 실행되며, 기존 조작 세션의 연결 만료 정책은 유지된다.

`web_manager.py`는 ROS와 독립적인 실행 관리자다. 8080으로 들어온 관제 요청을 현재
환경의 8082 웹 노드에 전달한다. ROS 도메인은 프로세스를 만들 때 정해지므로 모드 전환은
기존 프로세스 종료 후 새 도메인으로 재실행한다.
`web_gz_robot.launch.xml`은 기존 Gazebo 스폰/agent 구성을 재사용하면서 Nav2를
독립 노드로 실행한다. `rviz_tf.py`는 두 로봇의 TF를 RViz 전용 토픽으로 모은다.

실물/시뮬 미션은 각각 mission_real_web.yaml / mission_web.yaml이다.
관리자 옵션 `--real-mission /경로/미션.yaml`, `--sim-mission /경로/미션.yaml`으로 변경할 수 있다.
현재 Gazebo 월드는 fleet_arena 고정이다. 다른 맵으로 실제 시뮬레이션 환경까지 바꾸려면
Gazebo 월드와 로봇 Nav2 설정도 함께 맞춰야 한다. 웹의 맵 열기만으로 Gazebo 벽이 바뀌지는 않는다.
Gazebo의 로봇별 ROS 도메인 분리는 아직 적용하지 않았으며 네임스페이스로 분리한다.

### Gazebo 연결에서 보완한 부분

웹 전용 launch는 각 로봇 설정의 범위를 group으로 분리한다. 그렇지 않으면 첫 로봇의
브리지·Nav2 파일 경로가 두 번째 로봇에 재사용될 수 있다.
`web_nav2_pinky1.yaml`, `web_nav2_pinky2.yaml`은 기존 Nav2 설정을 각 네임스페이스 아래에
배치한 파일이다. 원래 튜닝을 바꾸면 이 파일도 함께 갱신해야 한다.
`web_spawn.launch.py`는 URDF 링크 이름과 Gazebo 센서 reference의 불일치를 보정한다.
라이다가 생성되지 않으면 AMCL이 위치를 추정할 수 없어 주행도 시작할 수 없다.

### 통합 실행 검증 (2026-09-17)

ROS 환경을 source한 상태에서 웹 노드·미션·실행 관리자 테스트 41개가 통과했다.
Gazebo에서 두 로봇의 라이다, 위치 추정, 웹 상태 수신과 이동을 확인했고 pinky1은 목표에 도달했다.
pinky2는 교차 주행 중 `compute_path_to_pose` 목표 수신 응답 시간 초과로 Nav2가 주행을
중단했다. 따라서 두 로봇의 전체 교차 미션 성공까지 검증된 상태는 아니다.
충돌 방지 설정은 유지했으며, 이 실패는 Nav2 실행 지연과 경로 계획 로그를 추가 분석해야 한다.

Gazebo·RViz·rqt 프로세스 실행과 환경 종료를 확인했다. RViz 로그에 그래픽 셰이더 오류가
있어 네이티브 창의 완전한 렌더링 정상 여부는 별도 확인이 필요하다.
실물 로봇 연결·주행과 시뮬레이터의 로봇별 도메인 분리는 아직 검증/구현하지 않았다.

테스트를 다시 실행하려면 패키지 폴더에서 다음 명령을 사용한다. `source`는 현재 터미널에
ROS와 직접 빌드한 패키지의 위치를 알려 주는 단계다.

```bash
source /opt/ros/jazzy/setup.bash
source $HOME/pinky_web_ws/install/setup.bash
python3 -m pytest test/test_web_node.py test/test_mission_io.py test/test_web_manager.py -q
```

## 팀 공유용 경로 검증

기본 미션은 package:// 주소를 사용하며, 미션 다운로드에도 해당 주소를 보존한다.
사용자 지정 맵 경로는 기존 방식대로 지원한다. 경로 호환성 테스트를 포함한 50개 테스트가
통과했고 별도 설치 위치에서 8개 패키지 빌드와 맵·웹 관리자 실행을 확인했다.
