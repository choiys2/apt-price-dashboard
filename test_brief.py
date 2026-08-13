#!/usr/bin/env python3
"""주간 브리핑 생성 테스트. `python test_brief.py` 로 실행."""
import unittest

from weekly_brief import build, delta_line, fmt_amount, fmt_pct


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
