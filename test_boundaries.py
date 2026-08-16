#!/usr/bin/env python3
"""경계 준비 로직 단위 테스트. `python test_boundaries.py` 로 실행.

여기서 잡고 싶은 것은 "조용히 빠지는" 부류의 결함이다. 실제로 겪은 것들:
  - 고정 허용오차로 단순화했더니 작은 구 6개가 점 부족으로 통째로 사라졌는데
    결과 파일만 봐서는 알 수 없었다.
  - 원본 다운로드가 끊기면 해상도가 10분의 1인 판으로 조용히 내려앉았다.
"""
import json
import unittest

from fetch_boundaries import MERGED_CELLS, build, ring_area, rings_of, simplify


def square(cx, cy, r, n=40):
    """정사각형 근처를 촘촘히 도는 링. 단순화 대상이 있게 점을 많이 둔다."""
    pts = []
    for i in range(n):
        t = i / n * 4
        side = int(t)
        f = t - side
        if side == 0:   pts.append((cx-r + 2*r*f, cy-r))
        elif side == 1: pts.append((cx+r, cy-r + 2*r*f))
        elif side == 2: pts.append((cx+r - 2*r*f, cy+r))
        else:           pts.append((cx-r, cy+r - 2*r*f))
    return pts


def feature(code, name, rings):
    return {"properties": {"code": code, "name": name},
            "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in rings]]}}


class SimplifyTest(unittest.TestCase):
    def test_keeps_corners(self):
        pts = square(127.0, 37.5, 0.1)
        out = simplify(pts, 0.001)
        # 네 꼭짓점은 어떤 허용오차에서도 남아야 한다
        self.assertGreaterEqual(len(out), 4)
        self.assertLess(len(out), len(pts))

    def test_short_ring_untouched(self):
        pts = [(0, 0), (1, 0)]
        self.assertEqual(simplify(pts, 0.5), pts)

    def test_deep_ring_does_not_blow_stack(self):
        # 재귀형이던 시절 이런 링(단조 증가 = 최악의 분할)에서 스택이 터졌다.
        pts = [(i * 0.001, i * i * 1e-7) for i in range(20000)]
        out = simplify(pts, 1e-6)
        self.assertGreater(len(out), 2)
        self.assertEqual(out[0], pts[0])
        self.assertEqual(out[-1], pts[-1])

    def test_tighter_tolerance_keeps_more(self):
        pts = square(127.0, 37.5, 0.1)
        self.assertGreaterEqual(len(simplify(pts, 0.0001)), len(simplify(pts, 0.01)))


class RingAreaTest(unittest.TestCase):
    def test_sign_marks_winding(self):
        ccw = [(0, 0), (1, 0), (1, 1), (0, 1)]
        self.assertAlmostEqual(ring_area(ccw), 1.0)
        self.assertAlmostEqual(ring_area(list(reversed(ccw))), -1.0)

    def test_rings_of_multipolygon_takes_outer_only(self):
        geom = {"type": "MultiPolygon", "coordinates": [
            [[[0, 0], [1, 0], [1, 1]], [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3]]],   # 외곽 + 구멍
            [[[5, 5], [6, 5], [6, 6]]],
        ]}
        rings = rings_of(geom)
        self.assertEqual(len(rings), 2)         # 구멍은 빠진다
        self.assertEqual(rings[1][0], [5, 5])


class BuildTest(unittest.TestCase):
    """build() 는 우리 83개 시군구를 2013 경계 셀에 대응시킨다."""

    def _geo(self, feats):
        return {"type": "FeatureCollection", "features": feats}

    def test_small_region_survives_default_tolerance(self):
        # 서울 중구는 반경 0.02도(약 2km)로, 기본 허용오차 0.002 로 한 번에 밀면
        # 점이 다 사라진다. 허용오차를 낮춰가며 형태를 남기는 것이 이 테스트의 요지다.
        geo = self._geo([feature("11020", "중구", square(126.99, 37.56, 0.02))])
        cells, cell_of, labels, missing = build(geo, tol=0.002)
        self.assertIn("11140", cell_of, f"서울 중구가 빠졌다. 누락: {missing}")
        self.assertGreaterEqual(len(cells["11140"][0]), 4)

    def test_merged_cell_absorbs_new_districts(self):
        # 옛 중구 + 동구 -> 제물포구(28125) + 영종구(28155) 한 칸
        geo = self._geo([
            feature("23010", "중구", square(126.4, 37.45, 0.08)),
            feature("23020", "동구", square(126.5, 37.48, 0.05)),
        ])
        cells, cell_of, labels, _ = build(geo, tol=0.002)
        cell = MERGED_CELLS["인천_옛중구동구"]
        for m in cell["members"]:
            self.assertEqual(cell_of[m], "인천_옛중구동구")
        self.assertEqual(labels["인천_옛중구동구"], cell["label"])
        # 두 원본 피처가 한 셀 안에 링 두 개로 들어간다
        self.assertEqual(len(cells["인천_옛중구동구"]), 2)

    def test_missing_source_feature_is_reported_not_silent(self):
        cells, cell_of, _, missing = build(self._geo([]), tol=0.002)
        self.assertEqual(cells, {})
        self.assertEqual(cell_of, {})
        self.assertTrue(missing)

    def test_tiny_islands_are_dropped(self):
        # 본토 옆에 면적이 0.01% 인 섬. 전부 세우면 입체 지도가 점으로 뒤덮인다.
        big = square(126.5, 37.5, 0.2)
        tiny = square(125.0, 37.2, 0.002)
        geo = self._geo([{"properties": {"code": "23080", "name": "서구"},
                          "geometry": {"type": "MultiPolygon", "coordinates": [
                              [[list(p) for p in big]], [[list(p) for p in tiny]]]}}])
        cells, _, _, _ = build(geo, tol=0.002)
        self.assertEqual(len(cells["인천_옛서구"]), 1)

    def test_name_alias_maps_michuhol_to_old_name(self):
        # 2013 원본에는 미추홀구가 개칭 전 이름 "남구"로 실려 있다.
        geo = self._geo([feature("23030", "남구", square(126.65, 37.46, 0.05))])
        _, cell_of, labels, _ = build(geo, tol=0.002)
        self.assertIn("28177", cell_of)
        self.assertEqual(labels["28177"], "인천광역시 미추홀구")

    def test_gyeonggi_names_have_no_space_in_source(self):
        # 원본은 "수원시장안구" 처럼 붙여 쓴다. 우리 표는 "수원시 장안구"다.
        geo = self._geo([feature("31011", "수원시장안구", square(127.0, 37.3, 0.05))])
        _, cell_of, _, _ = build(geo, tol=0.002)
        self.assertIn("41111", cell_of)

    def test_output_is_json_serializable(self):
        geo = self._geo([feature("11010", "종로구", square(126.98, 37.59, 0.04))])
        cells, cell_of, labels, _ = build(geo, tol=0.002)
        payload = {"cells": {k: [[list(p) for p in r] for r in v] for k, v in cells.items()},
                   "cell_of": cell_of, "labels": labels}
        self.assertIn("11110", json.loads(json.dumps(payload))["cells"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
