# 원본과 웹 버전의 차이

비교 기준: 팀 저장소 `mini_project_1`의 커밋 `8e2aa588964301ef6a6c3a6e6d41ec3851e70de9`.
순정 Pinky 소스 기준은 `web_dependencies.repos`에 기록했다.

웹뷰만 교체한 버전은 아니다. 로봇 제어의 핵심은 그대로 재사용하고, 웹 서버와 실행 관리 계층을
추가했다. 특히 Gazebo 연결 문제를 해결하기 위해 웹 전용 launch와 설정이 추가되었다.

| 구성 | 변경 여부 | 담당 역할 |
|---|---|---|
| pinky_fleet_agent | 기존 소스 유지 | FleetCommand를 Nav2 명령으로 전달, 상태·데드맨 관리 |
| pinky_fleet_msgs | 기존 소스 유지 | 로봇과 관제 사이 메시지 규격 |
| coordinator_node.py | 기존 소스 유지 | 교착 판단과 양보·재출발 제어 |
| gui_node.py / map_canvas.py | 기존 소스 유지 | 원래 PyQt 화면 |
| pinky_fleet_sim | 기존 소스 유지 | 기존 아레나·맵·시뮬 파일 |
| 순정 pinky_pro | 추적 파일 수정 없음 | 로봇 모델과 Nav2 launch 등 |
| mission_io.py | 작은 기능 추가 | package:// 맵 경로 해석과 저장 시 원래 주소 보존 |
| web.html / web.css / web.js | 추가 | 브라우저 화면, 방향 드래그, 버튼, 파일 작업 |
| web_node.py | 추가 | HTTP API, 조작 세션, 입력 검사, 기존 ROS 메시지 발행·수신 |
| web_manager.py | 추가 | 환경 시작·종료, 모드별 도메인 지정, rqt 실행 |
| web_* launch / web_nav2_* 설정 | 추가 | Gazebo 두 대의 네임스페이스·TF·센서·Nav2 연결 보정 |
| rviz_tf.py / fleet_web.rviz | 추가 | RViz에서 두 로봇의 TF와 상태 표시 |
| setup.py / package.xml | 설치 정보 확장 | 새 실행 명령·파일·의존성 등록 |

## 명령이 흐르는 순서

```text
기존: PyQt 화면 ──────────→ FleetCommand → agent → Nav2
웹:   브라우저 → web_node → FleetCommand → agent → Nav2
                                 ↑
                        기존 coordinator도 사용
```

실물에서는 관제와 agent 사이에 기존 domain_bridge가 들어간다.
웹 화면은 ROS 메시지를 직접 보내지 않으므로 web_node가 중간에서 변환해야 한다.
web_node의 입력 검사·조작권 관리 코드는 새로 작성된 백엔드 로직이다.
따라서 “백엔드 전체가 동일하다”는 표현은 정확하지 않다.

## Gazebo 실행 방식에서 달라진 점

- 로봇별 launch 인자 범위를 분리해 첫 로봇 설정이 두 번째 로봇에 적용되는 문제를 막았다.
- Nav2를 독립 노드로 실행하고 로봇별 네임스페이스 아래에 파라미터를 배치했다.
- 원본 URDF 파일을 편집하는 대신 스폰 시 Gazebo 센서의 링크 참조를 보정했다.
- agent의 TF 입력을 해당 로봇 토픽에 연결했다.
- Nav2 경로 입력을 nav_plan으로 분리해 agent의 경로 재발행 토픽과 겹치지 않게 했다.
- AMCL 초기 위치를 가상 로봇 스폰 위치에 맞췄다.

이는 단순한 UI 변경을 넘어 실행 동작에 영향을 주는 변경이다. 기존 컨트롤러 플러그인은
유지했지만, Gazebo 경로 전체는 별도 검증 대상이다. 현재 교차 주행 실패와 RViz 그래픽 오류가
남아 있으므로 완성된 실물 주행 버전으로 취급하지 않는다.

## 직접 비교하기

저장소 루트에서:

```bash
git diff 8e2aa588964301ef6a6c3a6e6d41ec3851e70de9 --stat
git diff 8e2aa588964301ef6a6c3a6e6d41ec3851e70de9 -- pinky_fleet_agent pinky_fleet_msgs pinky_fleet_sim pinky_fleet_station/pinky_fleet_station/coordinator_node.py
```

두 번째 명령은 위 핵심 소스에 변경이 없으면 아무것도 출력하지 않는다.
이 브랜치는 기존 PyQt 실행 파일을 삭제하거나 대체하지 않는다.
