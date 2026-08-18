#!/usr/bin/env python3
"""집계 로직 단위 테스트. `python test_analytics.py` 로 실행."""
import unittest

from apt_analytics import (
    PROVISIONAL_MONTHS, _area_type, _is_broker, _pct_change, _prev_ym,
    _same_month_last_year, analyze, area_distribution, build_kpi, cancel_rate_series,
    deal_type_stats, missing_regions, monthly_series, record_highs, reference_month,
    anomaly_flags, complex_histories, floor_premium, jeonse_ratio, outside_agent_stats,
    party_stats, region_monthly, region_ranking, settlement_series, summarize,
    umd_ranking, week_anchor, weekly_series,
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


class FallbackTest(unittest.TestCase):
    """예전 trades.json 에 없는 필드를 원본에서 유도하는지. 없으면 조용히 틀린 값이 된다."""

    def test_is_broker_derived_when_missing(self):
        self.assertTrue(_is_broker({"deal_gbn": "중개거래"}))
        self.assertFalse(_is_broker({"deal_gbn": "직거래"}))
        self.assertFalse(_is_broker({"deal_gbn": "중개거래", "is_broker": False}))

    def test_area_type_derived_when_missing(self):
        self.assertEqual(_area_type({"area_m2": 84.97}), 84)   # 내림
        self.assertEqual(_area_type({"area_m2": 83.99}), 83)   # 84형과 섞지 않는다
        self.assertEqual(_area_type({"area_m2": 84.1, "area_type": 84}), 84)
        self.assertIsNone(_area_type({"area_m2": None}))


PYEONG = 3.305785


def deal(ym, amount, apt="가나아파트", area=84.9, gbn="중개거래", code="11680"):
    # 평당가는 금액에서 계산해야 한다. 고정값을 넣으면 금액 차이가 통계에 안 나타나
    # 테스트가 통과해도 아무것도 검증하지 못한다.
    ppp = round(amount / (area / PYEONG))
    return {**rec(ym, ppp, amount=amount, area=area, code=code),
            "apt": apt, "deal_gbn": gbn, "area_type": int(area),
            "is_broker": gbn != "직거래", "deal_date": f"{ym}-15"}


class RecordHighTest(unittest.TestCase):
    MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

    def test_detects_new_high_with_gap(self):
        rows = [deal("2026-01", 100000), deal("2026-02", 105000),
                deal("2026-03", 102000), deal("2026-04", 110000),
                deal("2026-05", 120000)]
        out = record_highs(rows, self.MONTHS, recent_months=3, min_history=3)
        self.assertEqual(out["high_count"], 2)                 # 04, 05
        top = out["highs"][0]
        self.assertEqual(top["amount_manwon"], 120000)
        self.assertEqual(top["prev"], 110000)
        self.assertAlmostEqual(top["gap_pct"], 9.1, places=1)

    def test_short_history_excluded(self):
        rows = [deal("2026-05", 100000), deal("2026-06", 200000)]
        out = record_highs(rows, self.MONTHS, min_history=3)
        self.assertEqual(out["high_count"], 0)                 # 표본 2건은 "최고가"가 아니다

    def test_area_types_are_not_mixed(self):
        # 같은 단지라도 59㎡ 와 84㎡ 는 가격대가 달라 섞으면 전부 신고가로 잡힌다
        rows = ([deal(m, 60000, area=59.9) for m in self.MONTHS[:4]]
                + [deal("2026-05", 100000, area=84.9)])
        out = record_highs(rows, self.MONTHS, min_history=3)
        self.assertEqual(out["high_count"], 0)

    def test_only_recent_window_reported(self):
        rows = [deal(m, 100000 + i * 1000) for i, m in enumerate(self.MONTHS)]
        out = record_highs(rows, self.MONTHS, recent_months=2, min_history=3)
        self.assertEqual(out["window"], ["2026-05", "2026-06"])
        self.assertEqual(out["high_count"], 2)


class DealTypeTest(unittest.TestCase):
    def test_direct_share_and_gap(self):
        rows = ([deal("2026-06", 100000) for _ in range(9)]
                + [deal("2026-06", 50000, gbn="직거래")])
        out = deal_type_stats(rows)
        self.assertEqual(out["direct"]["count"], 1)
        self.assertEqual(out["direct_share_pct"], 10.0)
        self.assertEqual(out["direct_vs_broker_pct"], -50.0)

    def test_no_direct_deals(self):
        out = deal_type_stats([deal("2026-06", 100000)])
        self.assertEqual(out["direct"]["count"], 0)
        self.assertIsNone(out["direct_vs_broker_pct"])


class MissingRegionTest(unittest.TestCase):
    def test_lists_regions_with_no_records(self):
        expected = [("11680", "서울특별시", "강남구"), ("41597", "경기도", "화성시 동탄구")]
        out = missing_regions([deal("2026-06", 100000, code="11680")], expected)
        self.assertEqual([m["lawd_cd"] for m in out], ["41597"])
        self.assertEqual(out[0]["region"], "경기도 화성시 동탄구")


class CancelRateTest(unittest.TestCase):
    def test_rate_per_month_and_empty_month(self):
        rows = [rec("2026-01", 1000), {**rec("2026-01", 1000), "canceled": True},
                rec("2026-03", 1000)]
        out = cancel_rate_series(rows, ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(out[0]["rate_pct"], 50.0)
        self.assertIsNone(out[1]["rate_pct"])      # 거래 0건인 달은 비율이 없다
        self.assertEqual(out[2]["rate_pct"], 0.0)


class BrokerViewTest(unittest.TestCase):
    def test_analyze_exposes_broker_only_view(self):
        payload = {"meta": {}, "records": (
            [deal("2026-06", 100000) for _ in range(5)]
            + [deal("2026-06", 40000, gbn="직거래") for _ in range(5)])}
        out = analyze(payload)
        self.assertEqual(out["kpi"]["total_deals"], 10)
        self.assertEqual(out["broker"]["kpi"]["total_deals"], 5)
        # 직거래를 빼면 중위 거래가가 올라간다
        self.assertGreater(out["broker"]["kpi"]["median_amount"], out["kpi"]["median_amount"])


def rent(ym, deposit, apt="가나아파트", area=84.9, monthly=0, code="11680"):
    return {"lawd_cd": code, "apt": apt, "area_m2": area, "area_type": int(area),
            "deposit_manwon": deposit, "monthly_manwon": monthly,
            "is_jeonse": monthly == 0, "deal_ym": ym, "deal_date": f"{ym}-15"}


class JeonseRatioTest(unittest.TestCase):
    """전세가율은 같은 단지 x 같은 타입끼리 짝지어야 한다."""

    def test_matched_pair_ratio(self):
        sales = [deal("2026-05", 100000), deal("2026-06", 100000)]
        rents = [rent("2026-05", 60000), rent("2026-06", 60000)]
        out = jeonse_ratio(sales, rents, min_pairs=2, min_region_samples=1)
        self.assertEqual(out["matched_pairs"], 1)
        self.assertEqual(out["overall_pct"], 60.0)
        self.assertEqual(out["regions"][0]["jeonse_ratio_pct"], 60.0)

    def test_monthly_rent_excluded(self):
        # 월세 계약의 보증금을 전세금으로 쓰면 전세가율이 터무니없이 낮아진다
        sales = [deal("2026-05", 100000), deal("2026-06", 100000)]
        rents = [rent("2026-05", 5000, monthly=100), rent("2026-06", 5000, monthly=100)]
        out = jeonse_ratio(sales, rents, min_pairs=2, min_region_samples=1)
        self.assertEqual(out["matched_pairs"], 0)
        self.assertIsNone(out["overall_pct"])

    def test_area_types_are_not_crossed(self):
        # 84㎡ 매매와 59㎡ 전세를 짝지으면 전세가율이 실제보다 낮게 나온다
        sales = [deal("2026-05", 100000, area=84.9), deal("2026-06", 100000, area=84.9)]
        rents = [rent("2026-05", 60000, area=59.9), rent("2026-06", 60000, area=59.9)]
        out = jeonse_ratio(sales, rents, min_pairs=2, min_region_samples=1)
        self.assertEqual(out["matched_pairs"], 0)

    def test_thin_samples_dropped(self):
        sales = [deal("2026-05", 100000)]              # 매매 1건뿐
        rents = [rent("2026-05", 60000), rent("2026-06", 60000)]
        out = jeonse_ratio(sales, rents, min_pairs=2, min_region_samples=1)
        self.assertEqual(out["matched_pairs"], 0)

    def test_region_needs_enough_complexes(self):
        sales = [deal("2026-05", 100000), deal("2026-06", 100000)]
        rents = [rent("2026-05", 60000), rent("2026-06", 60000)]
        out = jeonse_ratio(sales, rents, min_pairs=2, min_region_samples=5)
        self.assertEqual(out["matched_pairs"], 1)      # 짝은 지어졌지만
        self.assertEqual(out["regions"], [])           # 지역 대표값으로는 못 올린다

    def test_analyze_attaches_jeonse_when_rent_given(self):
        payload = {"meta": {}, "records": [deal("2026-05", 100000), deal("2026-06", 100000)]}
        rp = {"records": [rent("2026-05", 60000), rent("2026-06", 60000)]}
        out = analyze(payload, rent_payload=rp)
        self.assertIn("jeonse", out)
        self.assertEqual(out["meta"]["jeonse_record_count"], 2)

    def test_analyze_without_rent_has_no_jeonse(self):
        payload = {"meta": {}, "records": [deal("2026-05", 100000)]}
        self.assertNotIn("jeonse", analyze(payload))


class QuartileTest(unittest.TestCase):
    def test_quartiles_and_spread(self):
        rows = [rec("2026-06", p) for p in (1000, 2000, 3000, 4000, 5000)]
        s = summarize(rows)
        self.assertEqual(s["median_ppp"], 3000)
        self.assertEqual((s["p25_ppp"], s["p75_ppp"]), (1500, 4500))
        self.assertEqual(s["iqr_ratio_pct"], 100.0)     # (4500-1500)/3000

    def test_too_few_samples_have_no_quartiles(self):
        s = summarize([rec("2026-06", 1000), rec("2026-06", 2000)])
        self.assertIsNone(s["p25_ppp"])
        self.assertIsNone(s["iqr_ratio_pct"])
        self.assertEqual(s["median_ppp"], 1500)          # 중위값은 그대로 낸다


def fdeal(ym, amount, floor, apt="가나아파트", area=84.9, code="11680"):
    d = deal(ym, amount, apt=apt, area=area, code=code)
    d["floor"] = floor
    return d


class FloorPremiumTest(unittest.TestCase):
    """층 효과는 단지 x 타입 안에서 재야 한다. 전체 평균으로 재면 건축연차가 섞인다."""

    def test_deviation_measured_within_group(self):
        # 한 단지 안에서 저층만 싸다
        rows = ([fdeal("2026-06", 90000, f) for f in (1, 2, 3)]
                + [fdeal("2026-06", 100000, f) for f in (5, 6, 12)])
        out = floor_premium(rows, min_group=6)
        by = {b["bucket"]: b["premium_pct"] for b in out["buckets"]}
        self.assertEqual(out["groups_used"], 1)
        self.assertLess(by["1~3층"], 0)                  # 단지 중위 대비 저평가
        self.assertGreater(by["4~9층"], 0)

    def test_cheap_old_complex_does_not_create_fake_premium(self):
        # 저층만 있는 싼 단지 + 고층만 있는 비싼 단지. 전체로 보면 "고층이 비싸다"가
        # 되지만, 단지 안에서는 편차가 0이라 프리미엄이 잡히면 안 된다.
        rows = ([fdeal("2026-06", 50000, f, apt="싼단지") for f in (1, 2, 3, 1, 2, 3)]
                + [fdeal("2026-06", 200000, f, apt="비싼단지") for f in (20, 21, 22, 20, 21, 22)])
        out = floor_premium(rows, min_group=6)
        by = {b["bucket"]: b["premium_pct"] for b in out["buckets"]}
        self.assertEqual(by["1~3층"], 0.0)
        self.assertEqual(by["20층~"], 0.0)

    def test_thin_groups_skipped(self):
        rows = [fdeal("2026-06", 100000, 5), fdeal("2026-06", 100000, 6)]
        out = floor_premium(rows, min_group=6)
        self.assertEqual(out["groups_used"], 0)


class ComplexHistoryTest(unittest.TestCase):
    def test_only_requested_keys_returned_and_sorted(self):
        rows = ([deal("2026-06", 100000, apt="가", area=84.9)]
                + [deal("2026-05", 90000, apt="가", area=84.9)]
                + [deal("2026-06", 70000, apt="나", area=59.9)])
        out = complex_histories(rows, {("11680", "가", 84)})
        self.assertEqual(list(out), ["11680|가|84"])
        self.assertEqual([x["d"] for x in out["11680|가|84"]],
                         ["2026-05-15", "2026-06-15"])   # 오래된 것부터

    def test_truncates_to_recent_points(self):
        rows = [deal(f"2026-{m:02d}", 100000 + m, apt="가") for m in range(1, 13)]
        out = complex_histories(rows, {("11680", "가", 84)}, max_points=5)
        hist = out["11680|가|84"]
        self.assertEqual(len(hist), 5)
        self.assertEqual(hist[-1]["d"], "2026-12-15")    # 최근이 남는다


class RegionMonthlyTest(unittest.TestCase):
    """입체 지도의 시간 재생이 읽는 표. 월 순서에 맞춘 배열이 계약 조건이다."""

    def test_arrays_align_with_month_order_and_fill_gaps(self):
        months = ["2026-04", "2026-05", "2026-06"]
        rows = [rec("2026-04", 100), rec("2026-06", 200), rec("2026-06", 300)]
        out = region_monthly(rows, months, min_samples=1)
        self.assertEqual(out["months"], months)
        e = out["regions"]["11680"]
        self.assertEqual(e["count"], [1, 0, 2])          # 거래 없는 달도 자리를 지킨다
        self.assertEqual(e["ppp"], [100, None, 250])

    def test_thin_month_leaves_price_blank_but_keeps_count(self):
        # 두세 건짜리 중위값으로 지도 기둥이 솟으면 근거 없는 변동을 시장 변화처럼
        # 보여주게 된다. 건수는 남기되 단가만 비운다.
        months = ["2026-06"]
        out = region_monthly([rec("2026-06", 100), rec("2026-06", 900)], months,
                             min_samples=5)
        e = out["regions"]["11680"]
        self.assertEqual(e["count"], [2])
        self.assertIsNone(e["ppp"][0])

    def test_months_outside_window_are_ignored(self):
        out = region_monthly([rec("2025-01", 100), rec("2026-06", 200)],
                             ["2026-06"], min_samples=1)
        self.assertEqual(out["regions"]["11680"]["count"], [1])

    def test_each_region_gets_its_own_row(self):
        rows = [rec("2026-06", 100), rec("2026-06", 300, code="41135")]
        out = region_monthly(rows, ["2026-06"], min_samples=1)
        self.assertEqual(set(out["regions"]), {"11680", "41135"})

    def test_both_views_carry_their_own_series(self):
        # 지도에서 "중개거래만"을 켜도 재생이 같은 기준으로 돌아야 한다.
        rows = [dict(rec("2026-06", 100), deal_gbn="중개거래") for _ in range(3)]
        rows += [dict(rec("2026-06", 900), deal_gbn="직거래")]
        out = analyze({"meta": {}, "records": rows})
        self.assertIn("region_monthly", out)
        self.assertIn("region_monthly", out["broker"])
        self.assertEqual(out["region_monthly"]["regions"]["11680"]["count"], [4])
        self.assertEqual(out["broker"]["region_monthly"]["regions"]["11680"]["count"], [3])


class SettlementTest(unittest.TestCase):
    """등기완료율 - "최근 달은 잠정"을 규칙이 아니라 관측값으로 말하는 부분."""

    def _rows(self, ym, n, registered, days=70):
        out = []
        for i in range(n):
            r = rec(ym, 100)
            if i < registered:
                r["rgst_date"] = "2026-08-01"
                r["days_to_rgst"] = days
            out.append(r)
        return out

    def test_rate_is_share_of_registered(self):
        out = settlement_series(self._rows("2026-06", 100, 40), ["2026-06"], min_rows=10)
        m = out["months"][0]
        self.assertEqual((m["total"], m["registered"], m["rate_pct"]), (100, 40, 40.0))

    def test_thin_month_reports_no_rate(self):
        out = settlement_series(self._rows("2026-06", 5, 5), ["2026-06"], min_rows=30)
        self.assertIsNone(out["months"][0]["rate_pct"])

    def test_median_days_withheld_while_month_is_immature(self):
        # 완료율이 낮은 달의 소요일은 빨리 끝난 건만 보고 잰 값이라 늘 짧게 나온다.
        # 실측으로 완료율 3.6%인 달이 "중위 2일"이었다. 그대로 내면 오독을 부른다.
        out = settlement_series(self._rows("2026-08", 100, 4, days=2), ["2026-08"],
                                min_rows=1, days_min_rate=80.0)
        m = out["months"][0]
        self.assertEqual(m["rate_pct"], 4.0)
        self.assertTrue(m["days_biased"])
        self.assertIsNone(m["median_days"])

    def test_median_days_reported_once_month_is_settled(self):
        out = settlement_series(self._rows("2026-01", 100, 95, days=70), ["2026-01"],
                                min_rows=1)
        m = out["months"][0]
        self.assertFalse(m["days_biased"])
        self.assertEqual(m["median_days"], 70)

    def test_month_with_no_deals_is_still_a_row(self):
        out = settlement_series([], ["2026-05", "2026-06"], min_rows=1)
        self.assertEqual([m["ym"] for m in out["months"]], ["2026-05", "2026-06"])
        self.assertEqual(out["months"][0]["total"], 0)


class OutsideAgentTest(unittest.TestCase):
    """외지 중개 비중 - 원정 매수의 대리 지표."""

    def _rows(self, n, outside, code="11680"):
        out = []
        for i in range(n):
            r = rec("2026-06", 100, code=code)
            r["is_outside_agent"] = i < outside
            out.append(r)
        return out

    def test_share_counts_only_judged_rows(self):
        rows = self._rows(100, 20)
        # 중개사 소재지가 없는 건(직거래 포함)은 분모에서 빠져야 한다.
        for r in self._rows(100, 0):
            r["is_outside_agent"] = None
            rows.append(r)
        out = outside_agent_stats(rows, ["2026-06"], min_rows=10)
        self.assertEqual(out["overall_pct"], 20.0)
        self.assertEqual(out["judged"], 100)

    def test_thin_region_is_omitted_not_zeroed(self):
        # 판정 가능 건이 적으면 비율을 내지 않는다. 0% 로 두면 "외지가 없는 동네"로 읽힌다.
        out = outside_agent_stats(self._rows(5, 0), ["2026-06"], min_rows=200)
        self.assertIsNone(out["overall_pct"])
        self.assertEqual(out["regions"], [])

    def test_regions_sorted_high_first(self):
        rows = self._rows(100, 40) + self._rows(100, 5, code="41135")
        out = outside_agent_stats(rows, ["2026-06"], min_rows=10)
        self.assertEqual([r["outside_pct"] for r in out["regions"]], [40.0, 5.0])


class PartyTest(unittest.TestCase):
    def _rows(self, n, corp_sell=0, corp_buy=0):
        out = []
        for i in range(n):
            r = rec("2026-06", 100)
            r["seller"] = "법인" if i < corp_sell else "개인"
            r["buyer"] = "법인" if i < corp_buy else "개인"
            out.append(r)
        return out

    def test_seller_and_buyer_shares(self):
        out = party_stats(self._rows(100, corp_sell=3, corp_buy=1), ["2026-06"], min_rows=10)
        self.assertEqual(out["seller"]["법인"]["pct"], 3.0)
        self.assertEqual(out["buyer"]["법인"]["pct"], 1.0)

    def test_net_corp_sell_is_seller_minus_buyer(self):
        out = party_stats(self._rows(100, corp_sell=5, corp_buy=2), ["2026-06"], min_rows=10)
        self.assertEqual(out["regions"][0]["net_corp_sell_pct"], 3.0)

    def test_thin_month_reports_none(self):
        out = party_stats(self._rows(5, corp_sell=5), ["2026-06"], min_rows=200)
        self.assertIsNone(out["monthly"][0]["seller_corp_pct"])

    def test_missing_party_labelled_not_dropped(self):
        rows = self._rows(2)
        rows[0]["seller"] = None
        out = party_stats(rows, ["2026-06"], min_rows=1)
        self.assertIn("미상", out["seller"])


class WeeklyTest(unittest.TestCase):
    def test_groups_by_monday_of_contract_week(self):
        # 2026-06-03 은 수요일 -> 그 주 월요일은 2026-06-01
        rows = [deal("2026-06", 100000), deal("2026-06", 100000)]
        for r in rows:
            r["deal_date"] = "2026-06-03"
        out = weekly_series(rows, weeks=2)
        last = out["weeks"][-1]
        self.assertEqual(last["week"], "2026-06-01")
        self.assertEqual(last["count"], 2)

    def test_last_weeks_marked_provisional(self):
        rows = [dict(deal("2026-06", 100000), deal_date="2026-06-03")]
        out = weekly_series(rows, weeks=10)
        self.assertEqual(sum(1 for w in out["weeks"] if w["provisional"]), 5)
        self.assertTrue(out["weeks"][-1]["provisional"])
        self.assertFalse(out["weeks"][0]["provisional"])

    def test_anchor_aligns_axes_across_groups(self):
        # 시도별 시계열의 x축이 어긋나면 필터를 바꿀 때마다 축이 밀린다.
        early = [dict(deal("2026-05", 100000), deal_date="2026-05-06")]
        late = [dict(deal("2026-06", 100000), deal_date="2026-06-03")]
        anchor = week_anchor(early + late)
        a = weekly_series(early, weeks=8, anchor=anchor)
        b = weekly_series(late, weeks=8, anchor=anchor)
        self.assertEqual([w["week"] for w in a["weeks"]], [w["week"] for w in b["weeks"]])

    def test_empty_input_is_safe(self):
        self.assertEqual(weekly_series([], weeks=4)["weeks"], [])
        self.assertIsNone(week_anchor([]))


class AnomalyTest(unittest.TestCase):
    def _peer(self, ym, n, amount, apt="가"):
        return [deal(ym, amount, apt=apt) for _ in range(n)]

    def test_needs_a_rare_anchor_signal(self):
        # 직거래+법인매도만 겹친 건은 흔해서(실측 2,350건) 목록에 올리지 않는다.
        rows = self._peer("2026-06", 6, 100000)
        odd = deal("2026-06", 100000, apt="가", gbn="직거래")
        odd["seller"] = "법인"
        out = anomaly_flags(rows + [odd], ["2026-06"], min_peers=5)
        self.assertEqual(out["total"], 0)

    def test_deep_discount_with_direct_deal_is_listed(self):
        rows = self._peer("2026-06", 6, 100000)
        cheap = deal("2026-06", 50000, apt="가", gbn="직거래")   # 중위 대비 -50%
        out = anomaly_flags(rows + [cheap], ["2026-06"], min_peers=5)
        self.assertEqual(out["total"], 1)
        self.assertEqual(sorted(out["rows"][0]["flags"]), ["시세괴리", "직거래"])
        self.assertEqual(out["rows"][0]["gap_pct"], -50.0)

    def test_small_discount_not_flagged(self):
        rows = self._peer("2026-06", 6, 100000)
        mild = deal("2026-06", 85000, apt="가", gbn="직거래")    # -15%, 문턱 30% 미만
        self.assertEqual(anomaly_flags(rows + [mild], ["2026-06"], min_peers=5)["total"], 0)

    def test_peer_median_needs_enough_neighbours(self):
        # 이웃이 적으면 기준 자체가 그 몇 건에 좌우된다. 판정하지 않는다.
        rows = self._peer("2026-06", 2, 100000)
        cheap = deal("2026-06", 30000, apt="가", gbn="직거래")
        self.assertEqual(anomaly_flags(rows + [cheap], ["2026-06"], min_peers=5)["total"], 0)

    def test_old_deal_gets_no_price_verdict(self):
        """시세 기준 창(6개월) 밖의 거래는 괴리를 판정하지 않는다.

        그 사이 시장이 움직인 만큼이 통째로 "싸게 팔렸다"로 잡히기 때문이다.
        """
        months = [f"2025-{m:02d}" for m in range(7, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]
        rows = self._peer("2026-06", 6, 100000)
        old = dict(deal("2025-07", 50000, apt="가", gbn="직거래"), seller="법인")
        out = anomaly_flags(rows + [old], months, recent_months=6, scan_months=12,
                            min_peers=5)
        listed = [r for r in out["rows"] if r["deal_date"].startswith("2025-07")]
        self.assertTrue(all(r["gap_pct"] is None for r in listed))

    def test_flag_counts_split_all_versus_shown(self):
        rows = self._peer("2026-06", 6, 100000)
        for i in range(3):
            rows.append(deal("2026-06", 40000, apt="가", gbn="직거래"))
        out = anomaly_flags(rows, ["2026-06"], min_peers=5, top_n=1)
        self.assertEqual(out["total"], 3)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["flag_counts"]["시세괴리"], 3)
        self.assertEqual(out["shown_flag_counts"]["시세괴리"], 1)


class NewFieldsInAnalyzeTest(unittest.TestCase):
    def test_analyze_carries_every_new_section(self):
        rows = [rec("2026-06", 100 + i) for i in range(40)]
        out = analyze({"meta": {}, "records": rows})
        for key in ("settlement", "outside_agent", "party", "weekly", "anomalies"):
            self.assertIn(key, out, f"{key} 가 빠졌다")
        self.assertIn("weekly", out["sido"][0], "시도별 주간 시계열이 빠졌다")

    def test_region_rows_carry_outside_share(self):
        rows = []
        for i in range(300):
            r = rec("2026-06", 100)
            r["is_outside_agent"] = i < 30
            rows.append(r)
        out = analyze({"meta": {}, "records": rows})
        row = out["regions"][0]
        self.assertEqual(row["outside_pct"], 10.0)
        self.assertEqual(row["outside_judged"], 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
