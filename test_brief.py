#!/usr/bin/env python3
"""주간 브리핑 생성 테스트. `python test_brief.py` 로 실행."""
import unittest

import json
import os
import tempfile

from weekly_brief import (build, delta_line, fmt_amount, fmt_pct, load_watchlist,
                          watchlist_section)


PRICE_INDEX = {
    "columns": ["lawd_cd", "apt", "area_type", "median_amount", "min_amount",
                "max_amount", "count", "median_ppp", "build_year", "umd",
                "prev_median", "prev_count"],
    "rows": [
        ["11680", "은마", 84, 388000, 370000, 420000, 10, 15202, 1979, 0, 414000, 8],
        ["11680", "은마", 76, 345000, 330000, 380000, 14, 14916, 1979, 0, None, 0],
    ],
    "region_names": {"11680": "서울특별시 강남구"},
    "umd_names": ["대치동"],
    "window": ["2025-12", "2026-08"],
    "min_deals": 3,
}


def analytics(**over):
    base = {
        "meta": {"excluded_canceled": 100, "missing_regions": []},
        "kpi": {"period_from": "2025-06", "period_to": "2026-08", "total_deals": 1000,
                "median_ppp": 2791, "median_amount": 61000, "avg_area": 75.8,
                "ref_month": "2026-06", "latest_month": "2026-08",
                "ref": {"count": 200}, "latest": {"count": 30},
                "mom_count_pct": -17.8, "mom_ppp_pct": -11.0,
                "yoy_ppp_pct": -17.4, "yoy_count_pct": -29.8},
        "regions": [], "record_highs": None, "deal_type": None,
    }
    base.update(over)
    return base


class FormatTest(unittest.TestCase):
    def test_amount(self):
        self.assertEqual(fmt_amount(61000), "6.1억")
        self.assertEqual(fmt_amount(3900), "3,900만")
        self.assertEqual(fmt_amount(None), "–")

    def test_pct_sign(self):
        self.assertEqual(fmt_pct(12.3), "+12.3%")
        self.assertEqual(fmt_pct(-5.0), "-5.0%")
        self.assertEqual(fmt_pct(None), "–")

    def test_delta_without_previous(self):
        self.assertEqual(delta_line("중위", 2791, None, "만원"), "중위 **2,791만원**")

    def test_delta_up_down_and_same(self):
        self.assertIn("▲ 91만원", delta_line("중위", 2791, 2700, "만원"))
        self.assertIn("▼ 9만원", delta_line("중위", 2791, 2800, "만원"))
        self.assertIn("지난 브리핑과 동일", delta_line("중위", 2791, 2791, "만원"))


class BuildTest(unittest.TestCase):
    def test_snapshot_without_previous_state(self):
        text, state = build(analytics(), {})
        self.assertIn("중위 평당가 **2,791만원**", text)
        self.assertNotIn("▲", text)
        self.assertEqual(state["median_ppp"], 2791)

    def test_comparison_with_previous_state(self):
        text, _ = build(analytics(), {"median_ppp": 2700, "date": "2026-08-02"})
        self.assertIn("▲ 91만원", text)

    def test_missing_regions_warned(self):
        a = analytics()
        a["meta"]["missing_regions"] = [{"region": "인천광역시 옹진군"}]
        text, _ = build(a, {})
        self.assertIn("⚠ 거래 0건 시군구 1개", text)
        self.assertIn("옹진군", text)

    def test_jeonse_absence_is_stated(self):
        text, _ = build(analytics(), {})
        self.assertIn("전월세 데이터 미수집", text)

    def test_thin_regions_excluded_from_movers(self):
        # 거래 300건 미만은 전월비 순위에 넣지 않는다. 표본이 적으면 순위가 튄다.
        a = analytics(regions=[
            {"region": "적은동네", "count": 10, "mom_ppp_pct": 99.0},
            {"region": "큰동네", "count": 500, "mom_ppp_pct": 3.0},
        ])
        text, _ = build(a, {})
        self.assertIn("큰동네", text)
        self.assertNotIn("적은동네", text)

    def test_provisional_month_is_flagged(self):
        text, _ = build(analytics(), {})
        self.assertIn("잠정치", text)


class WatchlistTest(unittest.TestCase):
    """저장소에 커밋한 관심단지를 브리핑이 읽는 부분.

    브라우저 localStorage 는 서버에서 보이지 않는다. 화면을 열지 않아도 관심단지
    소식이 오게 하는 유일한 통로라, 조용히 빠지면 기능 자체가 없는 것과 같다.
    """

    def test_missing_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_watchlist(os.path.join(d, "없음.json")), {})

    def test_broken_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "watchlist.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{ 깨진 json")
            self.assertEqual(load_watchlist(p), {})

    def test_reads_items(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "watchlist.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"items": {"11680|은마|84": {"target": 400000}}}, f)
            self.assertIn("11680|은마|84", load_watchlist(p))

    def test_section_lists_watched_complexes(self):
        a = analytics(price_index=PRICE_INDEX)
        out = "\n".join(watchlist_section(a, {"11680|은마|84": {}}))
        self.assertIn("## 관심단지", out)
        self.assertIn("은마", out)
        self.assertIn("38.8억", out)
        self.assertIn("-6.3%", out)          # 414,000 -> 388,000

    def test_target_reached_is_marked(self):
        a = analytics(price_index=PRICE_INDEX)
        hit = "\n".join(watchlist_section(a, {"11680|은마|84": {"target": 400000}}))
        miss = "\n".join(watchlist_section(a, {"11680|은마|84": {"target": 300000}}))
        self.assertIn("✅", hit)
        self.assertNotIn("✅", miss)

    def test_no_prior_window_shows_dash_not_crash(self):
        # prev_median 이 None 인 행(직전 창에 거래가 모자란 경우)
        out = "\n".join(watchlist_section(analytics(price_index=PRICE_INDEX),
                                          {"11680|은마|76": {}}))
        self.assertIn("34.5억", out)

    def test_untraded_complex_is_explained_not_dropped(self):
        # 조용히 빠지면 "내 단지가 안 오르나 보다"로 오해한다
        out = "\n".join(watchlist_section(analytics(price_index=PRICE_INDEX),
                                          {"41135|없는단지|84": {}}))
        self.assertIn("없는단지", out)
        self.assertIn("거래가 없어", out)

    def test_empty_watchlist_adds_nothing(self):
        self.assertEqual(watchlist_section(analytics(price_index=PRICE_INDEX), {}), [])

    def test_build_without_watchlist_is_unchanged(self):
        a = analytics(price_index=PRICE_INDEX)
        text, _ = build(a, {})
        self.assertNotIn("## 관심단지", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
