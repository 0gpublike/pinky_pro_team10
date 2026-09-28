"""pipeline_image: 상위 crop + 좌표 복원 + 원본 위 오버레이 — ROS 불필요."""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pinky_lane_station.detectors import create_detector  # noqa: E402
from pinky_lane_station.lane_target import Instance, LaneTargetEstimator, TargetResult  # noqa: E402
from pinky_lane_station.pipeline_image import (CLASS_COLORS, TARGET_COLOR, crop_top,  # noqa: E402
                                               crop_top_rows, draw_debug, shift_instances)
from pinky_lane_station.synthetic_camera import render_lane_frame  # noqa: E402

cv2 = pytest.importorskip('cv2')


def _frame(**kw):
    return render_lane_frame(noise=0, **kw)


def test_crop_top_removes_exactly_top_rows_and_keeps_original():
    img = _frame()
    before = img.copy()
    out, dy = crop_top(img, 0.30)
    assert dy == crop_top_rows(480, 0.30) == 144
    assert out.shape == (480 - 144, 640, 3)
    assert np.array_equal(out, img[144:])
    assert np.array_equal(img, before)                       # 원본 보존


def test_crop_top_edges():
    img = _frame()
    out, dy = crop_top(img, 0.0)
    assert dy == 0 and np.array_equal(out, img)
    out, dy = crop_top(img, -1.0)
    assert dy == 0                                           # 클램프
    out, dy = crop_top(img, 1.0)
    assert dy == 479 and out.shape[0] == 1                   # 최소 1 행은 남긴다


def test_shift_instances_restores_original_coordinates():
    inst = [Instance('lane', 0.9, [(10, 0), (20, 0), (20, 50), (10, 50)]),
            Instance('cone', 0.5, [(100, 10), (120, 10), (110, 30)])]
    out = shift_instances(inst, 144)
    assert [i.cls for i in out] == ['lane', 'cone'] and out[0].conf == 0.9
    assert out[0].polygon == [(10.0, 144.0), (20.0, 144.0), (20.0, 194.0), (10.0, 194.0)]
    assert out[0].bbox == (10.0, 144.0, 20.0, 194.0)
    assert out[1].bbox == (100.0, 154.0, 120.0, 174.0)
    assert inst[0].polygon[0] == (10.0, 0.0)                 # 입력 불변
    assert shift_instances(inst, 0)[0].polygon == inst[0].polygon


@pytest.mark.parametrize('lateral, sign', [(0.0, 0), (0.03, +1), (-0.03, -1)])
def test_crop_then_shift_matches_full_frame_target(lateral, sign):
    """crop 추론 + 좌표 복원 결과가 전체 프레임 추론과 같은 차선 중앙을 준다."""
    det = create_detector('classic')
    img = _frame(lateral=lateral)
    cropped, dy = crop_top(img, 0.30)
    inst = shift_instances(det.infer(cropped), dy)
    r = LaneTargetEstimator().update(inst, img.shape[1], img.shape[0])
    r_full = LaneTargetEstimator().update(det.infer(img), img.shape[1], img.shape[0])
    assert r.quality_name == 'BOTH'
    assert r.target_y == r_full.target_y == round(0.72 * 480)
    assert abs(r.error_x - r_full.error_x) < 0.03
    if sign:
        assert r.error_x * sign > 0.1
    else:
        assert abs(r.error_x) < 0.05


def test_crop_then_shift_keeps_crosswalk_bottom_in_original_coords():
    det = create_detector('classic')
    img = _frame(crosswalk_ahead=0.10)
    cropped, dy = crop_top(img, 0.30)
    r = LaneTargetEstimator().update(shift_instances(det.infer(cropped), dy), 640, 480)
    r_full = LaneTargetEstimator().update(det.infer(img), 640, 480)
    assert r.crosswalk_raw and r_full.crosswalk_raw
    assert abs(r.crosswalk_bottom_y - r_full.crosswalk_bottom_y) <= 2


def test_shifted_instances_never_start_above_crop_line():
    det = create_detector('classic')
    cropped, dy = crop_top(_frame(), 0.30)
    for inst in shift_instances(det.infer(cropped), dy):
        assert inst.bbox[1] >= dy, inst.bbox


def test_draw_debug_draws_on_original_not_cropped():
    img = _frame()
    cropped, dy = crop_top(img, 0.30)
    r = LaneTargetEstimator().update(shift_instances(create_detector('classic').infer(cropped), dy), 640, 480)
    dbg = draw_debug(img, [], r, crop_frac=0.30)
    assert dbg.shape == img.shape and dbg is not img        # 원본 크기 (잘린 크기가 아님)
    assert dbg[:100].mean() > 50                            # 위쪽 영역이 원본 배경
    assert np.array_equal(img, _frame())                     # 원본 그대로


def test_draw_debug_bbox_per_instance_and_target_point():
    img = np.full((480, 640, 3), 120, dtype=np.uint8)
    insts = [Instance('lane', 0.9, [(100, 300), (140, 300), (140, 460), (100, 460)]),
             Instance('lane', 0.8, [(500, 300), (540, 300), (540, 460), (500, 460)]),
             Instance('crosswalk', 0.7, [(200, 400), (440, 400), (440, 440), (200, 440)]),
             Instance('cone', 0.6, [(300, 200), (340, 200), (340, 260), (300, 260)])]
    r = LaneTargetEstimator().update(insts, 640, 480)
    assert r.quality_name == 'BOTH'
    dbg = draw_debug(img, insts, r, crop_frac=0.30, infer_ms=12.0)
    for inst in insts:                                       # bbox 테두리 색이 각 인스턴스에 존재
        x0, y0, x1, y1 = (int(v) for v in inst.bbox)
        color = np.array(CLASS_COLORS[inst.cls])
        edge = dbg[y0:y1 + 1, x0:x0 + 2]
        assert (np.abs(edge.astype(int) - color).sum(axis=2) < 30).any(), inst.cls
    ty, tx = int(r.target_y), int(r.target_x)
    assert tuple(dbg[ty, tx]) == TARGET_COLOR                # 차선 중심점
    assert (dbg[144] == 128).all(axis=1).any()               # crop 경계 점선
    assert (img == 120).all()                                # 원본 보존


def test_draw_debug_lost_has_no_target_point():
    img = np.full((480, 640, 3), 120, dtype=np.uint8)
    r = TargetResult()
    dbg = draw_debug(img, [], r, crop_frac=0.0)
    assert not (dbg[int(r.target_y)] == np.array(TARGET_COLOR)).all(axis=1).any()
    assert not (dbg == 128).all(axis=2).any()                # crop 0 → 경계선 없음
