// 1. 통신: 브라우저는 ROS 대신 HTTP로 서버와 대화합니다.
const $ = id => document.getElementById(id);
const session = crypto.randomUUID();
const canvas = $('map');
const statusNames = ['대기', '주행 중', '도착', '실패', '취소됨', '양보 대기', '관제 연결 끊김'];
let runtimeState = null;
let active = false, snapshot = null, draft = null, revision = -1;
let mapImage = null, transform = null, drag = null;
let zoom = 1, pan = [0, 0];
const say = text => $('message').textContent = text;

async function send(action, extra = {}) {
  const response = await fetch('/api/command', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, session, ...extra})
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error);
  return data;
}
async function run(task) {
  try { await task(); } catch (error) { say(error.message); }
}
async function syncDraft() {
  await send('draft', {mission: draft});
}
$('connect').onclick = () => run(async () => {
  await send('claim'); active = true;
  $('connection').textContent = '조작 연결됨'; say('조작 연결됨');
});
$('disconnect').onclick = () => run(async () => {
  await send('release'); active = false;
  $('connection').textContent = '조회 모드'; say('전체 주행 취소 및 연결 해제됨');
});
$('stop').onclick = () => run(async () => {
  await send('cancel_all'); say('전체 주행 취소 명령 발행됨');
});
for (const [id, action] of [['go-all', 'goto_all'], ['init-all', 'initial_all']]) {
  $(id).onclick = () => run(async () => {
    await syncDraft(); await send(action); say('일괄 명령 발행됨. 로봇 상태를 확인하세요.');
  });
}
setInterval(async () => {
  if (!active) return;
  try { await send('pulse'); }
  catch (error) { active = false; $('connection').textContent = '연결 끊김'; say(error.message); }
}, 700);
window.addEventListener('pagehide', () => {
  if (active) fetch('/api/command', {method: 'POST', keepalive: true,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'release', session})}).catch(() => {});
});

// 실행 관리자는 ROS와 독립적으로 살아 있어 종료 후에도 웹 화면은 유지됩니다.
async function runtimeAction(action) {
  const response = await fetch('/api/runtime', {method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action, mode: $('runtime-mode').value})});
  const data = await response.json();
  if (!response.ok) throw Error(data.error);
  if (action !== 'rqt') { active = false; $('connection').textContent = '조회 모드'; }
  if (action === 'start') {
    draft = null; snapshot = null; revision = -1; mapImage = null; transform = null;
    $('cards').replaceChildren(); $('robot').replaceChildren();
  }
  say(action === 'rqt' ? 'rqt 실행 요청됨. 이 PC의 창을 확인하세요.' : '환경 전환 요청됨');
}
for (const action of ['start','stop','rqt']) $('runtime-'+action).onclick = () => run(() => runtimeAction(action));
async function pollRuntime() {
  try {
    const response = await fetch('/api/runtime');
    if (!response.ok) return; // 기존 web_node 단독 실행과도 호환
    const data = await response.json(); runtimeState = data;
    $('runtime-panel').hidden = false;
    const labels = {idle:'종료됨 · 환경 선택 가능',starting:'시작 중',running:'실행 중 · 로봇 준비 상태 확인',stopping:'종료 중'};
    $('runtime-status').textContent = labels[data.phase];
    $('runtime-error').textContent = data.error || '';
    $('runtime-mode').disabled = data.phase !== 'idle';
    for (const id of ['connect', 'go-all', 'init-all', 'stop', 'map-send', 'map-open', 'map-browse', 'map-reload', 'save', 'mission-file']) $(id).disabled = data.phase !== 'running';
    $('runtime-start').disabled = data.phase !== 'idle';
    $('runtime-stop').disabled = !['starting','running'].includes(data.phase);
    $('runtime-rqt').disabled = data.phase !== 'running';
    if (data.phase !== 'running') {
      active = false; $('connection').textContent = '조회 모드';
      say('연습 환경: ' + labels[data.phase]);
    }
  } catch (_) {} finally { setTimeout(pollRuntime, 700); }
}
pollRuntime();

// 2. 편집 모델: 목표(goal)와 초기 위치(initial_pose)를 서로 따로 보관합니다.
function inputField(parent, title, value, onChange) {
  const label = document.createElement('label'); label.textContent = title;
  const input = document.createElement('input');
  input.type = 'number'; input.step = '0.01'; input.value = value;
  input.oninput = () => { onChange(input.value === '' ? NaN : Number(input.value)); draw(); };
  label.append(input); parent.append(label); return input;
}
function button(parent, text, action) {
  const element = document.createElement('button'); element.textContent = text;
  element.onclick = () => run(action); parent.append(element);
}
function buildCards() {
  const previous = $('robot').value;
  $('cards').replaceChildren(); $('robot').replaceChildren();
  for (const spec of draft.robots) {
    const option = document.createElement('option'); option.value = spec.name;
    option.textContent = spec.name; $('robot').append(option);
    const card = document.createElement('article');
    card.style.setProperty('--robot-color', spec.color);
    const title = document.createElement('h2'); title.textContent = spec.name; card.append(title);
    for (const field of ['state', 'problem']) {
      const p = document.createElement('p'); p.id = field + '-' + spec.name;
      if (field === 'problem') p.className = 'warn'; card.append(p);
    }
    for (const [field, caption, action] of [
      ['goal', '목표 위치 · 실선 화살표', 'goto'],
      ['initial_pose', '초기 위치 · 점선 화살표', 'initial']
    ]) {
      const group = document.createElement('fieldset');
      const legend = document.createElement('legend'); legend.textContent = caption; group.append(legend);
      for (const [key, label] of [['x', 'X (m)'], ['y', 'Y (m)'], ['yaw', '방향 (rad)']]) {
        const input = inputField(group, label, spec[field][key], value => spec[field][key] = value);
        input.id = `${spec.name}-${field}-${key}`;
      }
      button(group, '지도에서 선택', async () => {
        $('robot').value = spec.name; $('mode').value = field;
        say(`${spec.name} ${caption}: 지도에서 드래그하세요.`);
      });
      button(group, action === 'goto' ? '목표로 출발' : '초기 위치 전송', async () => {
        await syncDraft(); await send(action, {robot: spec.name, ...spec[field]});
        say(`${spec.name} 명령 발행됨. 완료 여부는 로봇 상태를 확인하세요.`);
      });
      card.append(group);
    }
    for (const [key, label] of [['max_linear_vel', '직진 (m/s)'], ['max_angular_vel', '회전 (rad/s)']]) {
      inputField(card, label, spec[key], value => spec[key] = value);
    }
    button(card, '속도 적용', async () => {
      await syncDraft(); await send('speed', {robot: spec.name,
        max_linear_vel: spec.max_linear_vel, max_angular_vel: spec.max_angular_vel});
      say(`${spec.name} 속도 명령 발행됨`);
    });
    button(card, '주행 취소', async () => { await send('cancel', {robot: spec.name}); say('주행 취소 명령 발행됨'); });
    $('cards').append(card);
  }
  if (draft.robots.some(r => r.name === previous)) $('robot').value = previous;
}

// 3. 파일: YAML 다운로드는 현재 편집값을 서버에 검증·반영한 뒤 실행합니다.
$('save').onclick = () => run(async () => {
  await syncDraft();
  const response = await fetch('/api/mission.yaml');
  if (!response.ok) throw Error('미션 다운로드 실패');
  const anchor = document.createElement('a'); anchor.href = '/api/mission.yaml'; anchor.download = 'mission_web.yaml';
  document.body.append(anchor); anchor.click(); anchor.remove();
  say('미션 YAML 다운로드를 요청했습니다. 브라우저 다운로드 목록을 확인하세요.');
});
$('mission-file').onchange = () => run(async () => {
  const file = $('mission-file').files[0]; if (!file) return;
  $('mission-file').value = ''; // 실패 후 같은 파일을 다시 선택할 수 있게 초기화
  if (file.size > 200000) throw Error('미션 파일은 200KB 이하로 선택하세요.');
  await send('mission_load', {text: await file.text()});
  const response = await fetch('/api/state'); const data = await response.json();
  draft = structuredClone(data.mission); buildCards();
  $('map-path').value = draft.map.yaml_path;
  $('file-status').textContent = '불러온 미션: ' + file.name;
  say('미션 불러옴. 로봇에는 아직 명령을 보내지 않았습니다.');
  $('mission-file').value = '';
});
for (const [id, action] of [['map-open', 'map_open'], ['map-reload', 'map_reload']]) {
  $(id).onclick = () => run(async () => {
    await send(action, {path: $('map-path').value});
    const response = await fetch('/api/state'); const data = await response.json();
    draft.map = data.mission.map; $('map-path').value = draft.map.yaml_path;
    say('화면의 맵을 불러왔습니다. 필요하면 로봇에 맵 이름을 전송하세요.');
  });
}
// 브라우저 파일 업로드는 원래 절대경로를 주지 않으므로 PC 폴더 목록에서 선택합니다.
let browseParent = '';
async function browse(path) {
  $('browse-error').textContent = '';
  try {
    const response = await fetch('/api/files?path=' + encodeURIComponent(path));
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    browseParent = data.parent; $('browse-path').textContent = data.path;
    $('browse-list').replaceChildren();
    for (const entry of data.entries) {
      const row = document.createElement('button');
      row.textContent = (entry.directory ? '📁 ' : '📄 ') + entry.name;
      row.onclick = async () => {
        if (entry.directory) return browse(entry.path);
        try {
          await send('map_open', {path: entry.path});
          const response = await fetch('/api/state'); const data = await response.json();
          draft.map = data.mission.map; $('map-path').value = draft.map.yaml_path;
          $('file-browser').close(); zoom = 1; pan = [0, 0];
          say('맵 열기 완료: ' + entry.name);
        } catch (error) { $('browse-error').textContent = error.message; }
      };
      $('browse-list').append(row);
    }
  } catch (error) { $('browse-error').textContent = error.message; }
}
$('map-browse').onclick = () => {
  $('file-browser').showModal();
  const path = $('map-path').value;
  browse(path.startsWith('package://') ? '~' : (path.slice(0, path.lastIndexOf('/')) || '~'));
};
$('browse-up').onclick = () => browse(browseParent);
$('browse-close').onclick = () => $('file-browser').close();
$('map-send').onclick = () => run(async () => {
  await send('map_send'); say('전체 주행 취소 후 맵 이름 전송됨. 로봇 상태 확인 후 초기 위치를 다시 지정하세요.');
});

// 4. 지도 좌표 변환: 이미지 Y축은 아래로, ROS Y축은 위로 증가합니다.
function worldToPixel(x, y) {
  const m = snapshot.map, c = Math.cos(m.origin[2]), s = Math.sin(m.origin[2]);
  const dx = x - m.origin[0], dy = y - m.origin[1];
  return [transform.x + (c * dx + s * dy) / m.resolution * transform.scale,
    transform.y + (m.height - (-s * dx + c * dy) / m.resolution) * transform.scale];
}
function pixelToWorld(x, y) {
  const m = snapshot.map, c = Math.cos(m.origin[2]), s = Math.sin(m.origin[2]);
  const lx = (x - transform.x) / transform.scale * m.resolution;
  const ly = (m.height - (y - transform.y) / transform.scale) * m.resolution;
  return [m.origin[0] + c * lx - s * ly, m.origin[1] + s * lx + c * ly];
}
function arrow(ctx, pose, color, label, dashed = false, length = 38) {
  if (![pose.x, pose.y, pose.yaw].every(Number.isFinite)) return;
  const [x, y] = worldToPixel(pose.x, pose.y);
  const angle = pose.yaw - snapshot.map.origin[2];
  const ex = x + Math.cos(angle) * length, ey = y - Math.sin(angle) * length;
  ctx.save(); ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 3;
  ctx.setLineDash(dashed ? [6, 4] : []);
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(ex, ey); ctx.stroke();
  ctx.setLineDash([]); ctx.beginPath(); ctx.moveTo(ex, ey);
  for (const offset of [-0.48, 0.48]) ctx.lineTo(ex - 12 * Math.cos(angle + offset), ey + 12 * Math.sin(angle + offset));
  ctx.closePath(); ctx.fill(); ctx.strokeRect(x - 4, y - 4, 8, 8);
  ctx.font = 'bold 12px system-ui'; ctx.lineWidth = 3; ctx.strokeStyle = '#0b1220';
  const text = `${label} ${(pose.yaw * 180 / Math.PI).toFixed(0)}°`;
  ctx.strokeText(text, x + 9, y - 12); ctx.fillText(text, x + 9, y - 12); ctx.restore();
}
function draw() {
  const ctx = canvas.getContext('2d');
  canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight;
  if (!snapshot?.map || !mapImage || !draft) return;
  const m = snapshot.map;
  const scale = Math.min(canvas.width / m.width, canvas.height / m.height) * .90 * zoom;
  transform = {scale, x: (canvas.width - m.width * scale) / 2 + pan[0], y: (canvas.height - m.height * scale) / 2 + pan[1]};
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(mapImage, transform.x, transform.y, m.width * scale, m.height * scale);
  for (const {spec, state, path, problem} of snapshot.robots) {
    ctx.strokeStyle = spec.color; ctx.lineWidth = 2; ctx.beginPath();
    path.forEach(([x, y], index) => { const p = worldToPixel(x, y); index ? ctx.lineTo(...p) : ctx.moveTo(...p); }); ctx.stroke();
    const edited = draft.robots.find(r => r.name === spec.name);
    if (edited) {
      arrow(ctx, edited.initial_pose, spec.color, `${spec.name} 초기`, true);
      arrow(ctx, edited.goal, spec.color, `${spec.name} 목표`);
    }
    if (state?.localized) {
      const p = worldToPixel(state.x, state.y);
      ctx.fillStyle = problem ? '#64748b' : spec.color;
      ctx.beginPath(); ctx.arc(...p, 9, 0, Math.PI * 2); ctx.fill();
      arrow(ctx, state, problem ? '#94a3b8' : spec.color, `${spec.name} 현재`, false, 24);
    }
    if (state?.goal_valid) arrow(ctx, {x: state.goal_x, y: state.goal_y, yaw: state.goal_yaw}, '#ffffff', `${spec.name} 실행`, true, 28);
  }
  if (drag?.pose) arrow(ctx, drag.pose, '#facc15', '선택 중', drag.mode === 'initial_pose', 55);
}
function position(event) { const box = canvas.getBoundingClientRect(); return [event.clientX - box.left, event.clientY - box.top]; }
canvas.onpointerdown = event => {
  if (!transform) return;
  const point = position(event), [x, y] = pixelToWorld(...point);
  const mode = $('mode').value;
  if (mode !== 'pan') {
    const m = snapshot.map;
    if (point[0] < transform.x || point[1] < transform.y || point[0] > transform.x + m.width * transform.scale || point[1] > transform.y + m.height * transform.scale) return;
  }
  const spec = draft.robots.find(r => r.name === $('robot').value);
  drag = {point, pan: [...pan], mode, robot: spec.name,
    pose: mode === 'pan' ? null : {x, y, yaw: spec[mode].yaw}};
  canvas.setPointerCapture(event.pointerId); draw();
};
canvas.onpointermove = event => {
  if (!transform) return;
  const point = position(event), [x, y] = pixelToWorld(...point);
  $('coordinates').textContent = `X ${x.toFixed(3)} m · Y ${y.toFixed(3)} m`;
  if (!drag) return;
  if (drag.mode === 'pan') pan = [drag.pan[0] + point[0] - drag.point[0], drag.pan[1] + point[1] - drag.point[1]];
  else if (Math.hypot(point[0] - drag.point[0], point[1] - drag.point[1]) > 3) {
    drag.pose.yaw = Math.atan2(y - drag.pose.y, x - drag.pose.x);
    $('coordinates').textContent += ` · 방향 ${(drag.pose.yaw * 180 / Math.PI).toFixed(1)}°`;
  }
  draw();
};
canvas.onpointerup = () => {
  if (drag?.pose) {
    const spec = draft.robots.find(r => r.name === drag.robot);
    spec[drag.mode] = {...drag.pose};
    for (const key of ['x', 'y', 'yaw']) $(`${spec.name}-${drag.mode}-${key}`).value = drag.pose[key].toFixed(3);
    say(`${spec.name} ${drag.mode === 'goal' ? '목표' : '초기 위치'} 선택됨 · ${(drag.pose.yaw * 180 / Math.PI).toFixed(1)}°. 전송 버튼을 누르세요.`);
  }
  drag = null; draw();
};
canvas.onpointercancel = () => { drag = null; draw(); };
function magnify(factor) { zoom = Math.min(10, Math.max(.3, zoom * factor)); draw(); }
canvas.addEventListener('wheel', event => { event.preventDefault(); magnify(event.deltaY < 0 ? 1.1 : 1 / 1.1); }, {passive: false});
$('zoom-in').onclick = () => magnify(1.25); $('zoom-out').onclick = () => magnify(.8);
$('fit').onclick = () => { zoom = 1; pan = [0, 0]; draw(); };
window.onresize = draw;

// 5. 상태 갱신은 사용자가 편집 중인 입력값을 덮어쓰지 않습니다.
async function poll() {
  try {
    if (runtimeState && runtimeState.phase !== 'running') return;
    const response = await fetch('/api/state');
    if (!response.ok) throw Error('서버 응답 오류');
    const data = await response.json(); snapshot = data;
    if (!draft) {
      draft = structuredClone(data.mission); buildCards();
      $('map-path').value = draft.map.yaml_path; say('준비됨. 조작 연결 후 사용할 수 있습니다.');
    }
    if (revision !== data.revision) {
      revision = data.revision;
      const version = revision, image = new Image();
      image.onload = () => { if (revision === version) { mapImage = image; draw(); } };
      image.src = '/map.png?v=' + revision;
    }
    $('simulation').textContent = runtimeState ? (runtimeState.mode === 'sim' ? 'Gazebo · ROS 도메인 77' : '실제 로봇 · 관제 도메인 0') : (data.simulated ? '가짜 로봇 테스트 모드' : '실기 / 외부 ROS 연결');
    $('mapstatus').textContent = data.map_error || '맵: ' + data.map.name;
    $('coordinator').textContent = JSON.stringify(data.coordinator, null, 2);
    for (const {spec, state, problem} of data.robots) {
      const battery = state && Number.isFinite(state.battery_percent) && state.battery_percent >= 0 ? state.battery_percent.toFixed(0) + '%' : '알 수 없음';
      $('state-' + spec.name).textContent = state ? `${statusNames[state.nav_status] ?? '알 수 없음'} · (${state.x.toFixed(2)}, ${state.y.toFixed(2)}) m · ${state.linear_velocity.toFixed(2)} m/s · 배터리 ${battery}` : '상태 대기 중';
      $('problem-' + spec.name).textContent = problem;
    }
    draw();
  } catch (error) { say('상태 연결 실패: ' + error.message); }
  finally { setTimeout(poll, 250); }
}
poll();
