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

from lawd_codes import REGIONS, SIDO_ORDER

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


# 예전에 만들어둔 trades.json 에는 is_broker / area_type 이 없다. 없으면 원본 필드에서
# 유도한다. 이게 없으면 "직거래 100%" 같은 조용히 틀린 값이 그대로 집계된다.
def _is_broker(rec):
    v = rec.get("is_broker")
    return (rec.get("deal_gbn") != "직거래") if v is None else v


def _area_type(rec):
    v = rec.get("area_type")
    if v is None and rec.get("area_m2"):
        return int(rec["area_m2"])
    return v


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


def record_highs(records, months, recent_months=3, min_history=3, top_n=60):
    """단지 x 면적타입 단위로 신고가·신저가 갱신 거래를 찾는다.

    같은 단지라도 타입이 다르면 가격대가 완전히 달라 함께 비교하면 의미가 없다.
    전용면적을 내림해 묶은 area_type 을 키에 넣는 이유다(84.97/84.93 -> 84).
    직전 거래가 min_history 건 미만이면 "최고가"라는 말 자체가 성립하지 않으므로 뺀다.
    """
    watch = set(months[-recent_months:])
    groups = defaultdict(list)
    for r in records:
        atype = _area_type(r)
        if atype and r.get("amount_manwon") is not None and r.get("apt"):
            groups[(r["lawd_cd"], r["apt"], atype)].append(r)

    highs, lows = [], []
    for (code, apt, atype), rows in groups.items():
        rows.sort(key=lambda r: r["deal_date"])
        if len(rows) <= min_history:
            continue
        hi = lo = rows[0]["amount_manwon"]
        for r in rows[1:]:
            amt = r["amount_manwon"]
            prev_hi, prev_lo = hi, lo
            hi, lo = max(hi, amt), min(lo, amt)
            if r["deal_ym"] not in watch:
                continue
            entry = {
                "region": r["region"], "umd": r["umd"], "apt": apt,
                "area_type": atype, "deal_date": r["deal_date"],
                "amount_manwon": amt, "floor": r["floor"],
                "price_per_pyeong": r["price_per_pyeong"],
                "history_count": len(rows),
            }
            if amt > prev_hi:
                highs.append({**entry, "prev": prev_hi,
                              "gap_pct": round((amt - prev_hi) / prev_hi * 100, 1)})
            elif amt < prev_lo:
                lows.append({**entry, "prev": prev_lo,
                             "gap_pct": round((amt - prev_lo) / prev_lo * 100, 1)})

    highs.sort(key=lambda x: x["gap_pct"], reverse=True)
    lows.sort(key=lambda x: x["gap_pct"])
    return {"window": months[-recent_months:], "highs": highs[:top_n], "lows": lows[:top_n],
            "high_count": len(highs), "low_count": len(lows)}


def deal_type_stats(records):
    """중개거래와 직거래를 갈라서 비교한다.

    직거래는 실측에서 중개거래보다 중위 평당가가 28.5% 낮았다. 가족 간 증여성
    거래가 섞여 있다는 신호라, 섞어서 집계하면 시세가 아래로 끌린다.
    """
    broker = [r for r in records if _is_broker(r)]
    direct = [r for r in records if not _is_broker(r)]
    b, d = summarize(broker), summarize(direct)
    gap = None
    if b["median_ppp"] and d["median_ppp"]:
        gap = round((d["median_ppp"] / b["median_ppp"] - 1) * 100, 1)
    return {
        "broker": b, "direct": d,
        "direct_share_pct": round(len(direct) / len(records) * 100, 2) if records else 0,
        "direct_vs_broker_pct": gap,
    }


def missing_regions(records, expected):
    """수집 대상인데 거래가 한 건도 없는 시군구.

    행정구역 개편으로 코드가 폐지되면 API 는 오류 없이 totalCount=0 을 돌려준다.
    실패로 잡히지 않아 지역이 통째로 조용히 빠지므로, 여기서 따로 드러낸다.
    """
    seen = {r["lawd_cd"] for r in records}
    return [{"lawd_cd": c, "region": f"{sido} {sgg}"}
            for c, sido, sgg in expected if c not in seen]


def cancel_rate_series(raw_records, months):
    """월별 해제율. 시계열로 비교하면 안 되는 지표라 경고와 함께 쓴다.

    오래된 거래일수록 해제가 반영될 시간이 길었기 때문에 과거로 갈수록 높게 나온다
    (실측: 2025-06 9.5% -> 2026-08 0.6%). 시장 변화가 아니라 관측 편향이다.
    뒤집으면 최근 달에는 앞으로 해제로 빠질 거래가 더 남아 있다는 뜻이다.
    """
    total, canceled = defaultdict(int), defaultdict(int)
    for r in raw_records:
        total[r["deal_ym"]] += 1
        if r.get("canceled"):
            canceled[r["deal_ym"]] += 1
    return [{"ym": m, "total": total.get(m, 0), "canceled": canceled.get(m, 0),
             "rate_pct": round(canceled.get(m, 0) / total[m] * 100, 1) if total.get(m) else None}
            for m in months]


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


def _views(records, months):
    """한 벌의 거래 목록으로 KPI/추이/랭킹을 만든다. 전체본과 중개거래본에 같이 쓴다."""
    return {
        "kpi": build_kpi(records, months),
        "monthly": monthly_series(records, months),
        "sido": sido_rollup(records, months),
        "regions": region_ranking(records, months),
    }


def analyze(payload, include_canceled=False, expected_regions=None):
    raw = payload["records"]
    records = raw if include_canceled else [r for r in raw if not r.get("canceled")]
    if not records:
        raise SystemExit("집계할 거래가 없다. 수집 결과(trades.json)를 먼저 확인할 것.")

    months = sorted({r["deal_ym"] for r in records})
    broker = [r for r in records if _is_broker(r)]
    expected = expected_regions if expected_regions is not None else REGIONS

    result = {
        "meta": {
            **payload.get("meta", {}),
            "analyzed_at": date.today().isoformat(),
            "excluded_canceled": len(raw) - len(records),
            "months": months,
            "provisional_months": months[-PROVISIONAL_MONTHS:] if PROVISIONAL_MONTHS else [],
            "ref_month": reference_month(months),
            "missing_regions": missing_regions(records, expected),
        },
        **_views(records, months),
        # 직거래를 뺀 시세 기준. 대시보드에서 토글로 전환한다.
        "broker": _views(broker, months) if broker else None,
        "umd_top": umd_ranking(records),
        "area_distribution": area_distribution(records),
        "deal_type": deal_type_stats(records),
        "record_highs": record_highs(records, months),
        "cancel_rate": cancel_rate_series(raw, months),
    }
    return result


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
    dt = result["deal_type"]
    print(f"  직거래 {dt['direct']['count']:,}건({dt['direct_share_pct']}%), "
          f"중개거래 대비 평당가 {dt['direct_vs_broker_pct']}%")
    rh = result["record_highs"]
    print(f"  최근 {len(rh['window'])}개월 신고가 {rh['high_count']:,}건 / 신저가 {rh['low_count']:,}건")
    missing = result["meta"]["missing_regions"]
    if missing:
        print(f"  ! 거래 0건 시군구 {len(missing)}개: "
              + ", ".join(m["region"] for m in missing), file=sys.stderr)


if __name__ == "__main__":
    main()
