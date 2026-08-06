#!/usr/bin/env python3
"""
아파트 실거래 집계 — KPI / 월별 추이 / 지역 랭킹

fetch_apt_trades.py 가 만든 정규화 레코드를 받아 대시보드가 바로 그릴 수 있는
형태로 집계한다. 외부 의존성 없이 표준 라이브러리만 쓴다.

집계 규칙
  - 해제(취소) 거래는 제외한다. 실제로 성사되지 않은 계약이라 가격 통계를 왜곡한다.
  - 단가는 전용면적이 있는 건으로만 계산한다(면적 결측 건은 거래량에는 포함, 단가에는 제외).
  - 대표 단가는 **중위 평당가**를 쓴다. 평균은 초고가 몇 건에 끌려가는데, 실거래가는
    지역별 거래량이 적은 달이 많아 그 영향이 특히 크다.
  - 최근 1~2개월은 신고 지연(계약 후 30일 내 신고)으로 거래량이 과소 집계된다.
    provisional 플래그로 표시해 대시보드에서 구분할 수 있게 한다.

사용법
  python apt_analytics.py live/trades.json live/analytics.json
"""
import json
import sys
from collections import defaultdict
from datetime import date
from statistics import median

from lawd_codes import SIDO_ORDER

# 신고 지연으로 확정되지 않은 것으로 간주할 최근 개월 수
PROVISIONAL_MONTHS = 2

AREA_BUCKETS = [
    ("~60㎡", 0, 60),
    ("60~85㎡", 60, 85),
    ("85~135㎡", 85, 135),
    ("135㎡~", 135, float("inf")),
]


def reference_month(months):
    """비교의 기준이 되는 마지막 '확정월'.

    최신월은 신고 지연으로 거래량이 덜 잡힌 잠정치라, 확정된 전월/전년동월과 맞대면
    실제로 줄지 않았는데도 급감한 것처럼 보인다. 증감률은 전부 이 달을 기준으로 낸다.
    """
    if len(months) > PROVISIONAL_MONTHS:
        return months[-(PROVISIONAL_MONTHS + 1)]
    return months[-1]


def _pct_change(cur, prev):
    """전기 대비 증감률(%). 기준값이 0이거나 없으면 None."""
    if not prev or cur is None:
        return None
    return round((cur - prev) / prev * 100, 1)


def _prev_ym(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def _same_month_last_year(ym):
    return f"{int(ym[:4]) - 1:04d}-{ym[5:7]}"


def summarize(records):
    """거래 목록 -> {건수, 중위/평균 평당가, 중위 거래금액, 평균 전용면적}."""
    if not records:
        return {"count": 0, "median_ppp": None, "avg_ppp": None,
                "median_amount": None, "avg_area": None}
    ppp = [r["price_per_pyeong"] for r in records if r.get("price_per_pyeong")]
    areas = [r["area_m2"] for r in records if r.get("area_m2")]
    amounts = [r["amount_manwon"] for r in records if r.get("amount_manwon") is not None]
    return {
        "count": len(records),
        "median_ppp": round(median(ppp)) if ppp else None,
        "avg_ppp": round(sum(ppp) / len(ppp)) if ppp else None,
        "median_amount": round(median(amounts)) if amounts else None,
        "avg_area": round(sum(areas) / len(areas), 1) if areas else None,
    }


def _group(records, key):
    out = defaultdict(list)
    for r in records:
        out[key(r)].append(r)
    return out


def monthly_series(records, months):
    """월별 시계열. 거래가 없는 달도 0으로 채워 차트 x축이 끊기지 않게 한다."""
    by_month = _group(records, lambda r: r["deal_ym"])
    provisional = set(months[-PROVISIONAL_MONTHS:]) if PROVISIONAL_MONTHS else set()
    series = []
    for ym in months:
        row = {"ym": ym, **summarize(by_month.get(ym, []))}
        row["provisional"] = ym in provisional
        series.append(row)
    return series


def region_ranking(records, months):
    """시군구별 랭킹. 증감률은 마지막 확정월(reference_month) 기준으로 낸다."""
    ref = reference_month(months)
    prev = _prev_ym(ref)
    total = len(records)

    rows = []
    for code, group in _group(records, lambda r: r["lawd_cd"]).items():
        overall = summarize(group)
        by_month = _group(group, lambda r: r["deal_ym"])
        cur_s = summarize(by_month.get(ref, []))
        prev_s = summarize(by_month.get(prev, []))
        sample = group[0]
        rows.append({
            "lawd_cd": code,
            "region": sample["region"],
            "sido": sample["region"].split(" ")[0],
            "count": overall["count"],
            "share_pct": round(overall["count"] / total * 100, 2) if total else 0,
            "median_ppp": overall["median_ppp"],
            "median_amount": overall["median_amount"],
            "avg_area": overall["avg_area"],
            "ref_count": cur_s["count"],
            "ref_ppp": cur_s["median_ppp"],
            "mom_count_pct": _pct_change(cur_s["count"], prev_s["count"]),
            "mom_ppp_pct": _pct_change(cur_s["median_ppp"], prev_s["median_ppp"]),
        })
    # 중위 평당가 내림차순. 단가가 없는 지역(거래 0건)은 뒤로 보낸다.
    rows.sort(key=lambda r: (r["median_ppp"] is not None, r["median_ppp"] or 0), reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def sido_rollup(records, months):
    rows = []
    for sido, group in _group(records, lambda r: r["region"].split(" ")[0]).items():
        rows.append({"sido": sido, **summarize(group),
                     "monthly": monthly_series(group, months)})
    # 거래량순이 아니라 행정구역 통념 순서(서울-인천-경기)로 둔다. 필터 버튼 순서가 된다.
    rows.sort(key=lambda r: SIDO_ORDER.index(r["sido"]) if r["sido"] in SIDO_ORDER else 99)
    return rows


def umd_ranking(records, top_n=100):
    """법정동 단위 랭킹. 표본이 너무 적으면 중위값이 튀므로 10건 미만은 제외한다."""
    rows = []
    for (code, umd), group in _group(records, lambda r: (r["lawd_cd"], r["umd"])).items():
        if len(group) < 10 or not umd:
            continue
        rows.append({"lawd_cd": code, "region": group[0]["region"], "umd": umd,
                     **summarize(group)})
    rows.sort(key=lambda r: r["median_ppp"] or 0, reverse=True)
    return rows[:top_n]


def area_distribution(records):
    rows = []
    for label, lo, hi in AREA_BUCKETS:
        group = [r for r in records if r.get("area_m2") and lo <= r["area_m2"] < hi]
        rows.append({"bucket": label, **summarize(group)})
    return rows


def build_kpi(records, months):
    ref = reference_month(months)
    prev = _prev_ym(ref)
    last_year = _same_month_last_year(ref)
    by_month = _group(records, lambda r: r["deal_ym"])

    cur = summarize(by_month.get(ref, []))
    prv = summarize(by_month.get(prev, []))
    yoy = summarize(by_month.get(last_year, []))
    overall = summarize(records)

    return {
        "period_from": months[0],
        "period_to": months[-1],
        "total_deals": overall["count"],
        "median_ppp": overall["median_ppp"],
        "avg_ppp": overall["avg_ppp"],
        "median_amount": overall["median_amount"],
        "avg_area": overall["avg_area"],
        "latest_month": months[-1],           # 화면에 잠정치로 함께 보여주는 달
        "ref_month": ref,                     # 모든 증감률의 기준이 되는 확정월
        "latest": summarize(by_month.get(months[-1], [])),
        "ref": cur,
        "prev": prv,
        "mom_count_pct": _pct_change(cur["count"], prv["count"]),
        "mom_ppp_pct": _pct_change(cur["median_ppp"], prv["median_ppp"]),
        "yoy_count_pct": _pct_change(cur["count"], yoy["count"]) if yoy["count"] else None,
        "yoy_ppp_pct": _pct_change(cur["median_ppp"], yoy["median_ppp"]),
    }


def analyze(payload, include_canceled=False):
    raw = payload["records"]
    records = raw if include_canceled else [r for r in raw if not r.get("canceled")]
    if not records:
        raise SystemExit("집계할 거래가 없다. 수집 결과(trades.json)를 먼저 확인할 것.")

    months = sorted({r["deal_ym"] for r in records})

    return {
        "meta": {
            **payload.get("meta", {}),
            "analyzed_at": date.today().isoformat(),
            "excluded_canceled": len(raw) - len(records),
            "months": months,
            "provisional_months": months[-PROVISIONAL_MONTHS:] if PROVISIONAL_MONTHS else [],
            "ref_month": reference_month(months),
        },
        "kpi": build_kpi(records, months),
        "monthly": monthly_series(records, months),
        "sido": sido_rollup(records, months),
        "regions": region_ranking(records, months),
        "umd_top": umd_ranking(records),
        "area_distribution": area_distribution(records),
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "live/analytics.json"

    with open(src, encoding="utf-8") as f:
        payload = json.load(f)

    result = analyze(payload)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    k = result["kpi"]
    print(f"집계 완료 -> {dst}")
    print(f"  기간 {k['period_from']} ~ {k['period_to']} / 거래 {k['total_deals']:,}건 "
          f"(해제거래 {result['meta']['excluded_canceled']:,}건 제외)")
    print(f"  중위 평당가 {k['median_ppp']:,}만원 / 중위 거래가 {k['median_amount']:,}만원")
    print(f"  기준월(확정) {k['ref_month']}: {k['ref']['count']:,}건, "
          f"전월비 거래량 {k['mom_count_pct']}% / 평당가 {k['mom_ppp_pct']}%")
    print(f"  최신월(잠정) {k['latest_month']}: {k['latest']['count']:,}건 — 신고 지연으로 과소 집계")
    print(f"  시군구 {len(result['regions'])}개, 상위: "
          + ", ".join(f"{r['region']}({r['median_ppp']:,})" for r in result["regions"][:3]))


if __name__ == "__main__":
    main()
