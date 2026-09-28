"""이미지 전처리·디버그 오버레이 (ROS-free).

새 세그 모델은 학습 때 이미지 상위 30 % 를 **잘라내고**(crop) 학습했다 → 추론 입력도 똑같이 자른다.
검출 좌표는 잘린 이미지 기준이므로 원본 좌표로 되돌린다(y += 잘린 행 수). lane_target·오버레이는 원본 좌표로 동작한다.
오버레이는 **자르지 않은 원본** 위에 그린다 (모델이 본 영역의 위 경계는 회색 점선).
"""

from .lane_target import Instance

import numpy as np

try:
    import cv2
except ImportError:              # pragma: no cover
    cv2 = None

# 클래스별 오버레이 색 (BGR)
CLASS_COLORS = {
    'lane': (0, 255, 0),
    'crosswalk': (0, 220, 255),
    'cone': (0, 140, 255),
    'traffic_light': (0, 140, 255),
    'barricade': (0, 140, 255),
}
DEFAULT_COLOR = (200, 200, 200)
TARGET_COLOR = (0, 0, 255)
POINT_COLOR = (0, 255, 0)
CROP_LINE_COLOR = (128, 128, 128)


def crop_top_rows(height, frac):
    """잘라내는 행 수 = int(frac·H). frac 는 [0, 1) 로 클램프 (최소 1 행은 남긴다)."""
    frac = min(1.0, max(0.0, float(frac)))
    return min(int(frac * int(height)), max(0, int(height) - 1))


def crop_top(img, frac=0.30):
    """상위 frac 비율의 행을 잘라낸 이미지(뷰)와 잘린 행 수를 돌려준다. 원본은 바꾸지 않는다."""
    n = crop_top_rows(img.shape[0], frac)
    return img[n:], n


def shift_instances(instances, dy):
    """잘린 이미지 좌표의 검출을 원본 좌표로 (y += dy). 새 Instance 목록."""
    if dy == 0:
        return list(instances)
    out = []
    for inst in instances:
        x0, y0, x1, y1 = inst.bbox
        out.append(Instance(inst.cls, inst.conf, [(x, y + dy) for x, y in inst.polygon],
                            bbox=(x0, y0 + dy, x1, y1 + dy)))
    return out


def draw_debug(img_original, instances, result, crop_frac=0.30, infer_ms=0.0,
               stop_row_frac=0.80, draw_polygons=False):
    """원본 이미지 위에 검출 bbox(원본 좌표)·차선 중심점·샘플 행·crop 경계를 그린 새 이미지."""
    if cv2 is None:
        raise RuntimeError('python3-opencv 가 필요합니다')
    dbg = np.array(img_original, copy=True)
    H, W = dbg.shape[:2]

    if draw_polygons:
        overlay = dbg.copy()
        for inst in instances:
            pts = np.array(inst.polygon, dtype=np.int32).reshape(-1, 1, 2)
            if len(pts) >= 3:
                cv2.fillPoly(overlay, [pts], CLASS_COLORS.get(inst.cls, DEFAULT_COLOR))
        cv2.addWeighted(overlay, 0.3, dbg, 0.7, 0, dbg)

    for inst in instances:
        color = CLASS_COLORS.get(inst.cls, DEFAULT_COLOR)
        x0, y0, x1, y1 = (int(round(v)) for v in inst.bbox)
        cv2.rectangle(dbg, (x0, y0), (x1, y1), color, 2)
        cv2.putText(dbg, f'{inst.cls} {inst.conf:.2f}', (x0, max(14, y0 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    n_crop = crop_top_rows(H, crop_frac)
    if n_crop > 0:
        for x in range(0, W, 16):                                   # 회색 점선 = 모델이 본 영역의 위 경계
            cv2.line(dbg, (x, n_crop), (min(W - 1, x + 8), n_crop), CROP_LINE_COLOR, 1)

    y = int(result.target_y)
    stop_row = int(stop_row_frac * H)
    cv2.line(dbg, (0, y), (W, y), (255, 255, 0), 1)                 # 샘플 행
    cv2.line(dbg, (0, stop_row), (W, stop_row), (0, 200, 255), 1)   # 횡단보도 정지 행
    cv2.line(dbg, (W // 2, 0), (W // 2, H), (255, 0, 0), 1)         # 화면 중앙선
    if result.left_seen:
        cv2.circle(dbg, (int(result.left_x), y), 5, POINT_COLOR, -1)
    if result.right_seen:
        cv2.circle(dbg, (int(result.right_x), y), 5, POINT_COLOR, -1)
    if result.quality_name not in ('LOST', 'STALE'):
        cv2.circle(dbg, (int(result.target_x), y), 7, TARGET_COLOR, -1)   # 차선 중심점
    cv2.putText(dbg, f'{result.quality_name} e={result.error_x:+.2f} cw={int(result.crosswalk_detected)} '
                     f'half={result.half_lane_px:.0f}px {infer_ms:.0f}ms',
                (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, TARGET_COLOR, 2)
    return dbg
