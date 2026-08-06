#!/usr/bin/env python3
"""
합성 샘플 거래 데이터 생성기 — **실거래가 아니다.**

실제 API 호출 없이 대시보드 레이아웃·차트·정렬을 검증하기 위한 가짜 데이터를 만든다.
지역별 가격대와 거래량 규모만 현실과 비슷하게 잡아두었고, 개별 거래는 전부 무작위다.
생성물의 meta.synthetic = true 이며 대시보드 상단에 경고 배너가 뜬다.

사용법:
  python make_sample_data.py live/trades_sample.json
"""
import json
import os
import random
import sys
from datetime import date

from fetch_apt_trades import PYEONG_PER_M2, month_range
from lawd_codes import REGIONS, region_name

SEED = 20260806

# 시군구별 기준 평당가(만원). 여기 없는 지역은 시도 기본값을 쓴다.
BASE_PPP = {
    "11680": 9500, "11650": 9200, "11710": 7800, "11170": 7400, "11200": 6900,
    "11440": 6200, "11215": 6100, "11590": 5300, "11740": 5200, "11110": 5000,
    "11140": 4900, "11470": 4700, "11620": 4300, "11290": 4600, "11560": 4500,
    "11410": 4400, "11230": 4200, "11350": 4100, "11380": 4100, "11500": 4000,
    "11530": 3700, "11320": 3600, "11305": 3600, "11260": 3500, "11545": 3800,
    "41135": 5400, "41290": 5800, "41465": 3600, "41463": 3200, "41117": 3400,
    "41285": 3000, "41287": 2800, "41281": 2600, "41210": 3900, "41450": 3500,
    "41131": 3800, "41430": 3100, "41410": 2700, "41173": 3400, "41171": 2700,
    "41190": 2400, "41390": 2200, "41570": 2100, "41480": 2000, "41360": 2400,
    "41150": 2300, "41590": 2500, "41271": 2400, "41273": 2300, "41111": 2600,
    "41113": 2500, "41115": 2600, "41133": 2900, "41310": 2500, "41220": 1900,
    "41370": 2000, "41500": 1700, "41550": 1500, "41610": 1900, "41630": 1700,
    "41650": 1300, "41670": 1400, "41461": 1900, "41250": 1400, "41800": 900,
    "41820": 1200, "41830": 1500,
    "28185": 3100, "28237": 2500, "28200": 2400, "28245": 2200, "28260": 2300,
    "28177": 2000, "28110": 1800, "28140": 1500, "28710": 1100, "28720": 800,
}
SIDO_DEFAULT_PPP = {"서울특별시": 4200, "인천광역시": 2200, "경기도": 2200}

# 시군구당 월평균 거래건수 규모(대략). 소규모 군 지역은 한 자릿수로 떨어진다.
BASE_VOLUME = {"서울특별시": 90, "인천광역시": 130, "경기도": 110}
SMALL_REGIONS = {"41800", "41820", "41830", "28710", "28720", "41250", "41670", "41650"}

AREAS = [39.6, 49.8, 59.9, 74.5, 84.9, 99.8, 114.7, 134.8, 154.2]
UMD_SUFFIX = ["1동", "2동", "3동", "동", "읍", "리"]
APT_PREFIX = ["래미안", "자이", "푸르지오", "e편한세상", "힐스테이트", "아이파크",
              "롯데캐슬", "더샵", "센트럴", "한신", "청구", "삼성", "우성", "현대"]
APT_SUFFIX = ["1차", "2차", "3차", "파크", "리버뷰", "스카이", "포레", "타워", ""]


def make_records(rng, months):
    records = []
    for code, sido, sgg in REGIONS:
        base_ppp = BASE_PPP.get(code, SIDO_DEFAULT_PPP[sido])
        base_vol = BASE_VOLUME[sido] * (0.12 if code in SMALL_REGIONS else 1.0)
        umds = [f"{sgg.split()[-1][:2]}{s}" for s in UMD_SUFFIX[:rng.randint(3, 6)]]
        apts = [f"{rng.choice(APT_PREFIX)}{rng.choice(APT_SUFFIX)}" for _ in range(rng.randint(8, 20))]

        for i, ym in enumerate(months):
            # 완만한 우상향 추세 + 계절성 + 월별 노이즈
            trend = 1 + 0.004 * i
            season = 1 + 0.05 * (1 if ym[5:7] in ("03", "04", "09", "10") else -1)
            vol = max(1, int(rng.gauss(base_vol * season * trend, base_vol * 0.25)))
            # 최근 2개월은 신고 지연으로 실제보다 적게 잡힌다(실데이터의 특성을 재현)
            if i >= len(months) - 2:
                vol = int(vol * (0.55 if i == len(months) - 1 else 0.85))

            for _ in range(vol):
                area = rng.choice(AREAS)
                # 대형일수록 평당가가 조금 낮고, 지은 지 오래됐으면 더 낮다
                build_year = rng.randint(1985, 2024)
                age_factor = 1 - min(0.25, (2026 - build_year) * 0.006)
                size_factor = 1 - max(0.0, (area - 85) * 0.0012)
                ppp = rng.gauss(base_ppp * trend * age_factor * size_factor, base_ppp * 0.13)
                ppp = max(300, ppp)
                amount = round(ppp * (area / PYEONG_PER_M2) / 100) * 100  # 백만원 단위 반올림
                y, m = int(ym[:4]), int(ym[4:6])
                day = rng.randint(1, 28)
                records.append({
                    "lawd_cd": code, "sgg_cd": code, "region": region_name(code),
                    "umd": rng.choice(umds), "apt": rng.choice(apts),
                    "jibun": str(rng.randint(1, 900)),
                    "area_m2": area, "amount_manwon": int(amount),
                    "deal_ym": f"{y:04d}-{m:02d}",
                    "deal_date": f"{y:04d}-{m:02d}-{day:02d}",
                    "floor": rng.randint(1, 25), "build_year": build_year,
                    "deal_gbn": rng.choice(["중개거래"] * 9 + ["직거래"]),
                    "seller": "개인", "buyer": "개인",
                    # 실제로도 1% 안팎이 해제된다
                    "canceled": rng.random() < 0.012, "cancel_day": "",
                    "price_per_m2": round(amount / area, 2),
                    "price_per_pyeong": round(amount / (area / PYEONG_PER_M2)),
                })
    return records


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "live/trades_sample.json"
    months = month_range(12)
    rng = random.Random(SEED)
    records = make_records(rng, months)

    payload = {
        "meta": {
            "synthetic": True,
            "경고": "합성 데이터다. 실제 실거래가가 아니므로 어떤 판단 근거로도 쓰면 안 된다.",
            "generated_at": date.today().isoformat(),
            "months": months,
            "regions": len(REGIONS),
            "api_calls": 0,
            "cache_hits": 0,
            "record_count": len(records),
            "canceled_count": sum(1 for r in records if r["canceled"]),
            "failures": [],
        },
        "records": records,
    }
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"합성 데이터 생성 -> {out}")
    print(f"  {len(records):,}건 / {len(REGIONS)}개 시군구 / {months[0]}~{months[-1]}")


if __name__ == "__main__":
    main()
