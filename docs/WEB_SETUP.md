# 팀원용 웹 Fleet 설치·실행 안내

이 문서는 `gigi/web-fleet` 브랜치 기준이다. 기존 PyQt 사용법은 루트 README에 있다.
처음에는 Gazebo로 실행 흐름을 확인한다. 현재는 개발 버전이며 실물 주행 검증은 아직 하지 않았다.

## 1. 준비

- Ubuntu 24.04 데스크톱과 ROS 2 Jazzy를 사용한다.
- ROS 설치가 없다면 [ROS 공식 설치 안내](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)를 먼저 따른다.
- Gazebo/RViz/rqt 창을 표시할 데스크톱 세션과 그래픽 드라이버가 필요하다.
- 설치·소스 다운로드에는 인터넷이 필요하다. 설치 후 로컬 Gazebo 실행에는 인터넷이 필수는 아니다.
- 기존 작업과 섞이지 않도록 새 터미널과 새 워크스페이스를 권장한다.

ROS 저장소 설정까지 완료한 PC에서:

```bash
sudo apt update
sudo apt install git python3-colcon-common-extensions python3-vcstool python3-rosdep python3-pytest
source /opt/ros/jazzy/setup.bash
```

`rosdep`은 package.xml에 적힌 시스템 의존성을 설치하는 도구다. 처음 사용하는 PC에서만
`sudo rosdep init`을 실행하고, 이후 `rosdep update`를 실행한다.

## 2. 소스 받기

`$HOME`은 로그인한 사용자의 홈 폴더다. 아래 `pinky_web_ws`는 원하는 이름으로 바꿔도 된다.
이미 같은 이름의 폴더를 사용 중이라면 새 이름을 사용한다.

```bash
mkdir -p "$HOME/pinky_web_ws/src"
cd "$HOME/pinky_web_ws"
git clone --branch gigi/web-fleet https://github.com/0gpublike/pinky_pro_team11.git src/pinky_pro_team11
vcs import src < src/pinky_pro_team11/web_dependencies.repos
```

두 저장소를 받는다. `pinky_pro_team11`에는 팀 Fleet와 웹 확장이 있고,
`pinky_pro`에는 순정 로봇 모델·내비게이션·Gazebo 패키지가 있다.
`.repos` 파일은 검증한 순정 커밋을 지정하므로 최신 버전 변경에 따른 차이를 줄인다.

## 3. 의존성 설치와 빌드

워크스페이스 루트에서 Bash로 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
mapfile -t web_package_paths < <(colcon list --packages-up-to pinky_fleet_station pinky_fleet_sim --paths-only)
rosdep install --from-paths "${web_package_paths[@]}" --ignore-src --rosdistro jazzy -y
colcon build --symlink-install --packages-up-to pinky_fleet_station pinky_fleet_sim
source install/setup.bash
```

`colcon`은 ROS 패키지를 빌드한다. `--packages-up-to`는 지정한 패키지와 그 소스 의존성을
함께 빌드한다. `source install/setup.bash`는 현재 터미널에 빌드 결과 위치를 알려 준다.
같은 이름의 패키지가 중복 발견되면 기존 Fleet 저장소를 이 워크스페이스에 추가로 넣었는지 확인한다.

## 4. 실행

새 터미널을 열 때마다 다음처럼 환경을 읽는다.

```bash
source /opt/ros/jazzy/setup.bash
source "$HOME/pinky_web_ws/install/setup.bash"
ros2 run pinky_fleet_station web_manager
```

브라우저에서 <http://127.0.0.1:8080/>에 접속한다.

1. **Gazebo**를 선택하고 환경 시작을 누른다. Gazebo, RViz와 로봇 두 대가 실행된다.
2. 맵과 두 로봇의 위치 추정·준비 상태가 정상인지 확인한다. `실행 중`만으로 주행 준비가 끝난 것은 아니다.
3. **조작 연결**을 누른다. 로봇을 선택하고 지도에서 드래그해 목표 위치와 방향을 정한다.
4. 출발 버튼으로 주행한다. 초기 위치 설정은 선택 후 **초기 위치 전송**을 별도로 누른다.
5. 필요할 때 **rqt 열기**를 누른다. rqt는 자동 실행하지 않는다.
6. 다른 모드로 바꾸려면 **연습 환경 종료**가 끝난 뒤 선택한다.

Gazebo/RViz/rqt 창은 서버를 실행한 PC에 뜬다. 현재 서버는 localhost 전용이며
다른 PC에 웹 주소만 보내서 공동 접속하는 기능은 이번 공유 범위에 포함하지 않는다.
브라우저를 닫아도 실행 관리자는 유지된다. 완전히 끝내려면 환경 종료 후 터미널에서 Ctrl+C를 누른다.
기존 PyQt 관제와 웹 관제를 동시에 조작하지 않는다.

## 5. 맵·미션 경로

기본 미션은 사용자 이름과 설치 폴더에 의존하지 않는다.

```yaml
map:
  yaml_path: package://pinky_fleet_sim/map/fleet_arena.yaml
```

`package://`는 인터넷 주소가 아니다. ROS가 해당 패키지의 설치 폴더를 찾아 준다.
실물 기본 맵은 `package://pinky_navigation/map/pinklab.yaml`이다.
일반 절대 경로, `~/maps/example.yaml`, `$HOME/maps/example.yaml`도 사용할 수 있다.
직접 만든 맵은 YAML과 YAML의 `image`가 가리키는 이미지 파일을 함께 전달해야 한다.
기본 패키지 맵은 미션을 다운로드해도 `package://` 주소가 유지된다.
사용자가 직접 연 로컬 맵은 파일 경로가 저장되므로 다른 PC에 맞게 바꿔야 한다.

별도 미션을 쓰려면:

```bash
ros2 run pinky_fleet_station web_manager \
  --sim-mission "$HOME/missions/sim.yaml" \
  --real-mission "$HOME/missions/real.yaml"
```

현재 Gazebo 월드·스폰 위치·Nav2 초기 위치는 기본 아레나에 맞춰져 있다.
`--sim-mission`만 바꾸어도 Gazebo 월드나 스폰 위치가 자동 변경되는 것은 아니다.
월드 변경은 Gazebo 월드, web_gz_fleet launch, web_nav2 설정과 미션을 함께 맞춰야 한다.

## 6. 실물 모드

실물 모드 시작은 관제와 domain_bridge만 실행한다. 로봇의 모터·라이다·Nav2·agent는
기존 [팀 README](../README.md)의 로봇 실행 절차로 먼저 시작해야 한다.
관제 PC와 로봇이 통신 가능한 네트워크에 있고 같은 맵을 사용하는지 확인한다.

| 환경 | 실제 ROS_DOMAIN_ID | 분리 방법 |
|---|---|---|
| 실물 관제 PC | 0 | domain_bridge가 로봇 10/11과 연결 |
| 실물 pinky1 / pinky2 | 10 / 11 | 로봇별 도메인 |
| Gazebo 전체 | 77 | pinky1 / pinky2 네임스페이스 |

시뮬레이터 미션의 `domain_id: 10/11`은 메시지 메타데이터와 coordinator 우선순위다.
Gazebo 노드가 실제로 서로 다른 도메인에 있다는 뜻은 아니다.
기본 실물 맵은 예시이므로 현재 로봇에 올라간 맵과 초기 위치를 맞춘 뒤 사용한다.

## 7. 검증과 알려진 문제

```bash
cd "$HOME/pinky_web_ws/src/pinky_pro_team11/pinky_fleet_station"
python3 -m pytest test/test_web_node.py test/test_mission_io.py test/test_web_manager.py test/test_map_paths.py -q
```

- 웹 기능·실행 관리·경로 호환성 테스트 50개가 통과했다.
- 기존 워크스페이스와 다른 임시 설치 위치에서 8개 패키지 빌드, 기본 맵 두 개 읽기, 웹 관리자와 정적 파일 응답을 확인했다.
- Gazebo 두 대의 위치 추정과 이동, pinky1의 목표 도착을 확인했다.
- pinky2 교차 주행 중 Nav2 `compute_path_to_pose` 응답 시간 초과가 발생했다. 전체 교차 미션 성공은 미검증이다.
- RViz 셰이더 오류 기록이 있어 그래픽 표시 정상 여부를 각 PC에서 확인해야 한다.
- 실물 주행과 시뮬레이터 로봇별 도메인 분리는 아직 검증/구현하지 않았다.
- 깨끗한 OS에서 모든 의존성을 새로 설치하는 과정은 아직 검증하지 않았다.

`패키지를 찾을 수 없습니다`는 빌드 및 source 여부를 확인한다.
8080 포트 사용 중이면 기존 web_manager를 종료하거나 `--port 8090 --backend-port 8092`로 실행한다.
실행 오류의 로그 폴더는 `/api/runtime` 응답의 `log_dir`에서 확인할 수 있다.

## 8. 팀원과 변경 공유

이 사본의 개발 브랜치는 `gigi/web-fleet`이다. `build/`, `install/`, `log/`는 Git에 넣지 않는다.
업데이트를 받기 전 로컬 수정 내용을 커밋하고, 실행 중인 환경을 종료한 다음:

```bash
cd "$HOME/pinky_web_ws/src/pinky_pro_team11"
git pull --ff-only origin gigi/web-fleet
cd "$HOME/pinky_web_ws"
colcon build --symlink-install --packages-up-to pinky_fleet_station pinky_fleet_sim
source install/setup.bash
```

원본 팀 저장소에 합치는 PR은 팀원 검토 후 별도로 진행한다.
코드 변경 범위는 [원본과 웹 버전 비교](WEB_CHANGES.md), 화면 상세 사용법은
[WEB_GUIDE](../pinky_fleet_station/WEB_GUIDE.md)를 참고한다.
