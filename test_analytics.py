#!/usr/bin/env python3
"""집계 로직 단위 테스트. `python test_analytics.py` 로 실행."""
import unittest

from apt_analytics import (
    PROVISIONAL_MONTHS, _pct_change, _prev_ym, _same_month_last_year, analyze,
    area_distribution, build_kpi, monthly_series, reference_month, region_ranking,
    summarize, umd_ranking,
)


def rec(ym, ppp, amount=100000, area=84.0, code="11680", umd="역삼동", canceled=False):
    return {
        "lawd_cd": code, "region": "서울특별시 강남구" if code == "11680" else "경기도 성남시 분당구",
        "umd": umd, "apt": "테스트단지", "area_m2": area, "amount_manwon": amount,
        "deal_ym": ym, "deal_date": f"{ym}-15", "price_per_pyeong": ppp,
        "price_per_m2": round(amount / area, 2), "canceled": canceled, "floor": 5,
    }


class HelperTest(unittest.TestCase):
    def test_prev_ym_crosses_year(self):
        self.assertEqual(_prev_ym("2026-01"), "2025-12")
        self.assertEqual(_prev_ym("2026-07"), "2026-06")

    def test_same_month_last_year(self):
        self.assertEqual(_same_month_last_year("2026-01"), "2025-01")

    def test_pct_change(self):
        self.assertEqual(_pct_change(120, 100), 20.0)
        self.assertEqual(_pct_change(80, 100), -20.0)

    def test_pct_change_guards_zero_and_none(self):
        # 거래 0건인 달을 기준으로 증감률을 내면 ZeroDivisionError 가 난다.
        self.assertIsNone(_pct_change(10, 0))
        self.assertIsNone(_pct_change(10, None))
        self.assertIsNone(_pct_change(None, 100))


class SummarizeTest(unittest.TestCase):
    def test_empty(self):
        s = summarize([])
        self.assertEqual(s["count"], 0)
        self.assertIsNone(s["median_ppp"])

    def test_median_resists_outlier(self):
        rows = [rec("2026-01", p) for p in (1000, 1100, 1200, 1300, 90000)]
        s = summarize(rows)
        self.assertEqual(s["median_ppp"], 1200)      # 중위값은 초고가 1건에 안 끌림
        self.assertGreater(s["avg_ppp"], 18000)      # 평균은 끌려감

    def test_missing_area_counted_but_not_priced(self):
        rows = [rec("2026-01", 1000), {**rec("2026-01", None), "area_m2": None}]
        s = summarize(rows)
        self.assertEqual(s["count"], 2)              # 거래량에는 포함
        self.assertEqual(s["median_ppp"], 1000)      # 단가 계산에는 제외


class MonthlyTest(unittest.TestCase):
    def test_fills_empty_months(self):
        months = ["2026-01", "2026-02", "2026-03"]
        series = monthly_series([rec("2026-01", 1000), rec("2026-03", 1200)], months)
        self.assertEqual([s["ym"] for s in series], months)
        self.assertEqual(series[1]["count"], 0)      # 거래 없는 달도 x축에 남는다
        self.assertIsNone(series[1]["median_ppp"])

    def test_provisional_flag_on_recent_months(self):
        months = ["2026-01", "2026-02", "2026-03", "2026-04"]
        series = monthly_series([rec(m, 1000) for m in months], months)
        self.assertEqual([s["provisional"] for s in series], [False, False, True, True])


class ReferenceMonthTest(unittest.TestCase):
    def test_skips_provisional_tail(self):
        months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
        # 최근 2개월(04,05)은 잠정 -> 기준월은 03
        self.assertEqual(reference_month(months), months[-(PROVISIONAL_MONTHS + 1)])
        self.assertEqual(reference_month(months), "2026-03")

    def test_falls_back_when_too_few_months(self):
        # 수집 개월이 잠정 구간보다 짧으면 기준월을 뺄 수 없으니 최신월을 그대로 쓴다
        self.assertEqual(reference_month(["2026-05", "2026-06"]), "2026-06")
        self.assertEqual(reference_month(["2026-06"]), "2026-06")


class RankingTest(unittest.TestCase):
    def setUp(self):
        # 2개월뿐이라 기준월 = 최신월(2026-06)로 폴백된다
        self.months = ["2026-05", "2026-06"]
        self.records = (
            [rec("2026-05", 5000, code="11680") for _ in range(4)]
            + [rec("2026-06", 6000, code="11680") for _ in range(6)]
            + [rec("2026-05", 3000, code="41135") for _ in range(2)]
            + [rec("2026-06", 3000, code="41135") for _ in range(2)]
        )

    def test_sorted_by_median_ppp(self):
        rows = region_ranking(self.records, self.months)
        self.assertEqual(rows[0]["lawd_cd"], "11680")
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[1]["lawd_cd"], "41135")

    def test_mom_and_share(self):
        rows = {r["lawd_cd"]: r for r in region_ranking(self.records, self.months)}
        gangnam = rows["11680"]
        self.assertEqual(gangnam["mom_count_pct"], 50.0)    # 4건 -> 6건
        self.assertEqual(gangnam["mom_ppp_pct"], 20.0)      # 5000 -> 6000
        self.assertEqual(gangnam["share_pct"], 71.43)       # 10/14
        self.assertEqual(rows["41135"]["mom_ppp_pct"], 0.0)  # 변동 없음은 None 이 아니라 0%

    def test_region_with_no_latest_month_does_not_crash(self):
        records = [rec("2026-05", 5000, code="11680")]      # 최신월 거래 없음
        rows = region_ranking(records, self.months)
        self.assertEqual(rows[0]["ref_count"], 0)
        self.assertEqual(rows[0]["mom_count_pct"], -100.0)  # 1건 -> 0건
        self.assertIsNone(rows[0]["mom_ppp_pct"])           # 단가는 산출 불가


class UmdTest(unittest.TestCase):
    def test_small_sample_excluded(self):
        records = ([rec("2026-06", 5000, umd="역삼동") for _ in range(12)]
                   + [rec("2026-06", 9000, umd="표본적은동") for _ in range(3)])
        rows = umd_ranking(records)
        self.assertEqual([r["umd"] for r in rows], ["역삼동"])


class AreaDistTest(unittest.TestCase):
    def test_bucket_boundaries(self):
        records = [rec("2026-06", 5000, area=a) for a in (59.9, 60.0, 84.9, 85.0, 134.9, 135.0)]
        rows = {r["bucket"]: r["count"] for r in area_distribution(records)}
        self.assertEqual(rows["~60㎡"], 1)
        self.assertEqual(rows["60~85㎡"], 2)      # 60.0, 84.9
        self.assertEqual(rows["85~135㎡"], 2)     # 85.0, 134.9
        self.assertEqual(rows["135㎡~"], 1)


class AnalyzeTest(unittest.TestCase):
    def test_canceled_excluded_by_default(self):
        payload = {"meta": {}, "records": [
            rec("2026-06", 5000),
            rec("2026-06", 99000, canceled=True),
        ]}
        result = analyze(payload)
        self.assertEqual(result["kpi"]["total_deals"], 1)
        self.assertEqual(result["meta"]["excluded_canceled"], 1)
        self.assertEqual(result["kpi"]["median_ppp"], 5000)   # 해제건이 통계를 안 흔든다

    def test_include_canceled_option(self):
        payload = {"meta": {}, "records": [rec("2026-06", 5000), rec("2026-06", 9000, canceled=True)]}
        self.assertEqual(analyze(payload, include_canceled=True)["kpi"]["total_deals"], 2)

    def test_all_canceled_raises(self):
        payload = {"meta": {}, "records": [rec("2026-06", 5000, canceled=True)]}
        with self.assertRaises(SystemExit):
            analyze(payload)

    def test_kpi_yoy_absent_when_no_prior_year(self):
        payload = {"meta": {}, "records": [rec("2026-06", 5000)]}
        self.assertIsNone(analyze(payload)["kpi"]["yoy_count_pct"])

    def test_structure_keys(self):
        payload = {"meta": {"api_calls": 3}, "records": [rec("2026-06", 5000)]}
        result = analyze(payload)
        for key in ("meta", "kpi", "monthly", "sido", "regions", "umd_top", "area_distribution"):
            self.assertIn(key, result)
        self.assertEqual(result["meta"]["api_calls"], 3)   # 수집 메타가 보존된다


class ReferenceMonthKpiTest(unittest.TestCase):
    """증감률이 잠정치인 최신월이 아니라 마지막 확정월을 기준으로 나오는지 고정한다."""

    def _payload(self):
        months = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]
        recs = []
        # 01~03 은 월 10건, 04~05(잠정)는 신고 지연으로 2건씩만 들어온 상황
        for ym, n, ppp in [("2026-01", 10, 1000), ("2026-02", 10, 1100),
                           ("2026-03", 10, 1200), ("2026-04", 2, 1210),
                           ("2026-05", 2, 1220)]:
            recs += [rec(ym, ppp) for _ in range(n)]
        return {"meta": {}, "records": recs}, months

    def test_kpi_uses_last_confirmed_month(self):
        payload, _ = self._payload()
        k = analyze(payload)["kpi"]
        self.assertEqual(k["ref_month"], "2026-03")
        self.assertEqual(k["latest_month"], "2026-05")
        self.assertEqual(k["ref"]["count"], 10)
        self.assertEqual(k["latest"]["count"], 2)
        # 03(10건) vs 02(10건) = 0%. 최신월 기준이었다면 2 vs 2 였을 것이다.
        self.assertEqual(k["mom_count_pct"], 0.0)
        self.assertAlmostEqual(k["mom_ppp_pct"], 9.1, places=1)

    def test_ranking_uses_last_confirmed_month(self):
        payload, months = self._payload()
        rows = region_ranking(payload["records"], months)
        self.assertEqual(rows[0]["ref_count"], 10)     # 잠정월의 2건이 아니다
        self.assertEqual(rows[0]["mom_count_pct"], 0.0)

    def test_meta_exposes_ref_month(self):
        payload, _ = self._payload()
        result = analyze(payload)
        self.assertEqual(result["meta"]["ref_month"], "2026-03")
        self.assertEqual(result["meta"]["provisional_months"], ["2026-04", "2026-05"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
