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


if __name__ == "__main__":
    unittest.main(verbosity=2)
