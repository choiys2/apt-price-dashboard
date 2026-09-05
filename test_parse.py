#!/usr/bin/env python3
"""
파서·정규화 단위 테스트 (외부 네트워크 없이 실행).

실제 API 호출은 GitHub Actions 의 probe 워크플로에서 확인하고, 여기서는 응답 형태별
파싱 규칙이 깨지지 않는지만 고정한다. 표준 라이브러리만 쓰며 `python test_parse.py` 로 실행.
"""
import gzip
import json
import os
import tempfile
import unittest

import fetch_apt_trades as fetch
import lawd_codes
from fetch_apt_trades import ApiError, load_cache, normalize, parse_response, save_cache, month_range

OK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
  <body>
    <items>
      <item>
        <aptDong>101동</aptDong>
        <aptNm>래미안퍼스티지</aptNm>
        <buildYear>2009</buildYear>
        <buyerGbn>개인</buyerGbn>
        <cdealDay> </cdealDay>
        <cdealType> </cdealType>
        <dealAmount>   350,000</dealAmount>
        <dealDay>15</dealDay>
        <dealMonth>6</dealMonth>
        <dealYear>2026</dealYear>
        <dealingGbn>중개거래</dealingGbn>
        <excluUseAr>84.93</excluUseAr>
        <floor>10</floor>
        <jibun>1330</jibun>
        <sggCd>11650</sggCd>
        <slerGbn>개인</slerGbn>
        <umdNm>반포동</umdNm>
      </item>
      <item>
        <aptNm>해제된단지</aptNm>
        <cdealType>O</cdealType>
        <cdealDay>26.07.01</cdealDay>
        <dealAmount>120,000</dealAmount>
        <dealDay>3</dealDay>
        <dealMonth>5</dealMonth>
        <dealYear>2026</dealYear>
        <excluUseAr>59.98</excluUseAr>
        <floor>-1</floor>
        <sggCd>11650</sggCd>
        <umdNm>잠원동</umdNm>
      </item>
    </items>
    <numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount>
  </body>
</response>"""

EMPTY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
  <body><items/><numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>0</totalCount></body>
</response>"""

GATEWAY_ERR_XML = """<OpenAPI_ServiceResponse>
  <cmmMsgHeader>
    <returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>
    <returnReasonCode>30</returnReasonCode>
  </cmmMsgHeader>
</OpenAPI_ServiceResponse>"""

SERVICE_ERR_XML = """<response>
  <header><resultCode>99</resultCode><resultMsg>INVALID REQUEST PARAMETER ERROR</resultMsg></header>
</response>"""


class ParseTest(unittest.TestCase):
    def test_normal_response(self):
        items, total = parse_response(OK_XML)
        self.assertEqual(total, 2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["aptNm"], "래미안퍼스티지")

    def test_empty_items(self):
        items, total = parse_response(EMPTY_XML)
        self.assertEqual((items, total), ([], 0))

    def test_gateway_error(self):
        with self.assertRaises(ApiError) as ctx:
            parse_response(GATEWAY_ERR_XML)
        self.assertIn("SERVICE_KEY_IS_NOT_REGISTERED_ERROR", str(ctx.exception))

    def test_service_error(self):
        with self.assertRaises(ApiError):
            parse_response(SERVICE_ERR_XML)

    def test_non_xml(self):
        with self.assertRaises(ApiError):
            parse_response("<html>502 Bad Gateway</html>")


class NormalizeTest(unittest.TestCase):
    def setUp(self):
        self.items, _ = parse_response(OK_XML)

    def test_amount_and_area(self):
        rec = normalize(self.items[0], "11650")
        self.assertEqual(rec["amount_manwon"], 350000)   # "   350,000" -> 350000
        self.assertAlmostEqual(rec["area_m2"], 84.93)
        self.assertEqual(rec["deal_date"], "2026-06-15")
        self.assertEqual(rec["deal_ym"], "2026-06")
        self.assertEqual(rec["region"], "서울특별시 서초구")

    def test_unit_prices(self):
        rec = normalize(self.items[0], "11650")
        # 350,000만원 / 84.93㎡ = 4,120.x 만원/㎡
        self.assertAlmostEqual(rec["price_per_m2"], 4121.04, places=1)
        # 84.93㎡ = 25.69평 -> 약 13,623만원/평
        self.assertEqual(rec["price_per_pyeong"], 13623)

    def test_canceled_flag_and_negative_floor(self):
        rec = normalize(self.items[1], "11650")
        self.assertTrue(rec["canceled"])
        self.assertEqual(rec["cancel_day"], "26.07.01")
        self.assertEqual(rec["floor"], -1)   # 지하층은 음수로 들어온다

    def test_missing_required_field_returns_none(self):
        self.assertIsNone(normalize({"aptNm": "이름만있음"}, "11650"))


class CacheTest(unittest.TestCase):
    def test_gzip_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            save_cache(d, "11650", "202606", [{"aptNm": "테스트"}], 1)
            got = load_cache(d, "11650", "202606")
            self.assertEqual(got["items"], [{"aptNm": "테스트"}])
            self.assertEqual(got["total_count"], 1)

    def test_missing_cache_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(load_cache(d, "11650", "202601"))

    def test_corrupt_cache_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "11650", "202606.json.gz")
            os.makedirs(os.path.dirname(path))
            with open(path, "wb") as f:
                f.write(b"not gzip at all")
            self.assertIsNone(load_cache(d, "11650", "202606"))

    def test_stable_bytes_for_same_content(self):
        # mtime=0 고정이 안 되면 같은 내용도 매번 다른 바이트가 돼 git diff 가 계속 생긴다.
        with tempfile.TemporaryDirectory() as d:
            save_cache(d, "11650", "202606", [{"a": "1"}], 1)
            with open(os.path.join(d, "11650", "202606.json.gz"), "rb") as f:
                first = f.read()
            save_cache(d, "11650", "202606", [{"a": "1"}], 1)
            with open(os.path.join(d, "11650", "202606.json.gz"), "rb") as f:
                second = f.read()
            self.assertEqual(first, second)


class MonthRangeTest(unittest.TestCase):
    def test_crosses_year_boundary(self):
        import datetime
        got = month_range(4, end=datetime.date(2026, 2, 10))
        self.assertEqual(got, ["202511", "202512", "202601", "202602"])

    def test_length_and_order(self):
        got = month_range(12)
        self.assertEqual(len(got), 12)
        self.assertEqual(got, sorted(got))


class CircuitBreakerTest(unittest.TestCase):
    """러너가 통째로 막혔을 때 남은 수천 건을 계속 시도하지 않고 멈추는지 고정한다."""

    def setUp(self):
        self.cfg = {"service_key": "x", "request_interval_sec": 0,
                    "bulk_timeout_sec": 1, "bulk_retries": 0}
        self.calls = 0

    def _always_fail(self, cfg, code, ymd):
        self.calls += 1
        raise fetch.ApiError("timed out")

    def test_aborts_after_consecutive_failures(self):
        with tempfile.TemporaryDirectory() as d:
            orig = fetch.fetch_month_raw
            fetch.fetch_month_raw = self._always_fail
            try:
                out = fetch.collect(self.cfg, months=15, cache_dir=d, verbose=False,
                                    max_consecutive_failures=5)
            finally:
                fetch.fetch_month_raw = orig
        self.assertTrue(out["meta"]["aborted_early"])
        self.assertEqual(self.calls, 5)                     # 1155회를 다 돌지 않는다
        self.assertEqual(len(out["meta"]["failures"]), 5)

    def test_recovery_resets_the_counter(self):
        # 실패가 흩어져 있으면(중간에 성공이 끼면) 중단하지 않고 끝까지 간다
        seq = []

        def flaky(cfg, code, ymd):
            seq.append(1)
            if len(seq) % 3:
                raise fetch.ApiError("timed out")
            return [], 0

        with tempfile.TemporaryDirectory() as d:
            orig = fetch.fetch_month_raw
            fetch.fetch_month_raw = flaky
            try:
                out = fetch.collect(self.cfg, months=2, sido="인천광역시",
                                    cache_dir=d, verbose=False,
                                    max_consecutive_failures=5)
            finally:
                fetch.fetch_month_raw = orig
        self.assertFalse(out["meta"]["aborted_early"])
        # 시군구 수는 행정구역 개편으로 바뀌므로 테이블에서 가져온다
        expected = len(lawd_codes.regions("인천광역시")) * 2
        self.assertEqual(len(seq), expected)


class RgstDateTest(unittest.TestCase):
    """등기일자 파싱. 빈 값이 "아직 등기 안 됨"으로 읽히므로 파싱 실패를 미등기로 세면
    확정도를 실제보다 낮게 보고하게 된다."""

    def test_two_digit_year_expands(self):
        self.assertEqual(fetch._rgst_date("26.02.03"), "2026-02-03")
        self.assertEqual(fetch._rgst_date("25.12.23"), "2025-12-23")

    def test_blank_and_garbage_are_none(self):
        for bad in ("", "   ", None, "2026-02-03", "26.2.3", "26.13.01", "26.02.32"):
            self.assertIsNone(fetch._rgst_date(bad), f"{bad!r} 을 통과시켰다")

    def test_whitespace_tolerated(self):
        self.assertEqual(fetch._rgst_date("  26.02.03  "), "2026-02-03")


class AgentLocalityTest(unittest.TestCase):
    """중개사 소재지 비교. 한쪽만 접두로 보면 신설 구가 통째로 외지로 잡힌다."""

    def test_same_district_is_local(self):
        self.assertFalse(fetch._agent_is_outside("서울 강남구", "서울특별시 강남구"))
        self.assertFalse(fetch._agent_is_outside("경기 성남시 분당구", "경기도 성남시 분당구"))

    def test_different_district_is_outside(self):
        self.assertTrue(fetch._agent_is_outside("서울 송파구", "서울특별시 강남구"))
        self.assertTrue(fetch._agent_is_outside("경기 수원시 팔달구", "서울특별시 중구"))

    def test_new_district_matched_by_old_city_name(self):
        # 2026 신설 구는 중개사 소재지가 아직 "경기 화성시" 로만 찍힌다. 한쪽 방향만
        # 접두로 보면 같은 동네인데 외지로 잡혀, 실측 비중이 6.6% 대신 8.0% 로 부풀었다.
        self.assertFalse(fetch._agent_is_outside("경기 화성시", "경기도 화성시 만세구"))
        self.assertFalse(fetch._agent_is_outside("경기 수원시", "경기도 수원시 팔달구"))

    def test_unknown_agent_is_not_judged(self):
        # 모르는 것을 "같은 동네"로 세면 외지 비중이 실제보다 낮아진다.
        self.assertIsNone(fetch._agent_is_outside("", "서울특별시 강남구"))
        self.assertIsNone(fetch._agent_is_outside(None, "서울특별시 강남구"))
        self.assertIsNone(fetch._agent_is_outside("서울 강남구", ""))


class NewFieldsNormalizeTest(unittest.TestCase):
    ROW = {
        "sggCd": "11680", "umdNm": "대치동", "aptNm": "테스트", "jibun": "910-5",
        "excluUseAr": "83.65", "dealAmount": "132,000",
        "dealYear": "2026", "dealMonth": "5", "dealDay": "4",
        "floor": "2", "buildYear": "2003", "dealingGbn": "중개거래",
        "slerGbn": "법인", "buyerGbn": "개인",
        "estateAgentSggNm": "서울 강남구", "rgstDate": "26.07.20",
    }

    def test_carries_new_fields(self):
        r = normalize(self.ROW, "11680")
        self.assertEqual(r["deal_day"], 4)
        self.assertEqual(r["agent_sgg"], "서울 강남구")
        self.assertEqual(r["rgst_date"], "2026-07-20")
        self.assertEqual(r["seller"], "법인")
        self.assertFalse(r["is_outside_agent"])

    def test_days_to_registration(self):
        r = normalize(self.ROW, "11680")
        self.assertEqual(r["days_to_rgst"], 77)      # 2026-05-04 -> 2026-07-20

    def test_unregistered_leaves_none_not_zero(self):
        # 0 으로 두면 "계약 당일 등기"가 되어 소요일 통계가 통째로 망가진다.
        r = normalize({**self.ROW, "rgstDate": ""}, "11680")
        self.assertIsNone(r["rgst_date"])
        self.assertIsNone(r["days_to_rgst"])

    def test_outside_agent_detected(self):
        r = normalize({**self.ROW, "estateAgentSggNm": "경기 성남시 분당구"}, "11680")
        self.assertTrue(r["is_outside_agent"])

    def test_cancel_date_and_days(self):
        r = normalize({**self.ROW, "cdealType": "O", "cdealDay": "26.05.20"}, "11680")
        self.assertTrue(r["canceled"])
        self.assertEqual(r["cancel_date"], "2026-05-20")
        self.assertEqual(r["days_to_cancel"], 16)     # 2026-05-04 -> 05-20

    def test_uncanceled_has_no_cancel_date(self):
        # 0 으로 두면 "계약 당일 해제"가 되어 소요일 통계가 망가진다.
        r = normalize(self.ROW, "11680")
        self.assertFalse(r["canceled"])
        self.assertIsNone(r["cancel_date"])
        self.assertIsNone(r["days_to_cancel"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
