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
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from statistics import median, quantiles

from lawd_codes import REGIONS, SIDO_ORDER, region_name

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
    """거래 목록 -> 건수·중위/평균 평당가·사분위·중위 거래금액·평균 전용면적.

    사분위(p25/p75)를 함께 내는 이유: 중위값 하나로는 지역을 설명할 수 없다.
    실측으로 강남구는 25% 7,514 / 중위 10,909 / 75% 14,217 이라 사분위폭이 중위의
    61%다. "강남구 = 10,909만원/평"은 7,500짜리와 14,200짜리를 한 숫자로 뭉갠 값이다.
    밴드를 함께 보면 중위가 오른 것인지 고가 구간만 오른 것인지 갈린다.
    """
    if not records:
        return {"count": 0, "median_ppp": None, "avg_ppp": None,
                "p25_ppp": None, "p75_ppp": None, "iqr_ratio_pct": None,
                "median_amount": None, "avg_area": None}
    ppp = [r["price_per_pyeong"] for r in records if r.get("price_per_pyeong")]
    areas = [r["area_m2"] for r in records if r.get("area_m2")]
    amounts = [r["amount_manwon"] for r in records if r.get("amount_manwon") is not None]

    med = round(median(ppp)) if ppp else None
    p25 = p75 = iqr_ratio = None
    # 사분위는 표본이 최소 4건은 돼야 의미가 있다(statistics.quantiles 요구사항이기도 하다).
    if len(ppp) >= 4:
        q1, _, q3 = quantiles(ppp, n=4)
        p25, p75 = round(q1), round(q3)
        if med:
            iqr_ratio = round((p75 - p25) / med * 100, 1)
    return {
        "count": len(records),
        "median_ppp": med,
        "avg_ppp": round(sum(ppp) / len(ppp)) if ppp else None,
        "p25_ppp": p25,
        "p75_ppp": p75,
        "iqr_ratio_pct": iqr_ratio,
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
        # 외지 중개 비중. 지도의 지표로 바로 쓰려고 랭킹 행에 같이 싣는다.
        # 판단 불가(중개사 소재지 없음·직거래)는 분모에서 뺀다.
        judged = [r for r in group if r.get("is_outside_agent") is not None]
        outside = (round(sum(1 for r in judged if r["is_outside_agent"]) / len(judged) * 100, 1)
                   if len(judged) >= 200 else None)
        rows.append({
            "lawd_cd": code,
            "region": sample["region"],
            "sido": sample["region"].split(" ")[0],
            "count": overall["count"],
            "share_pct": round(overall["count"] / total * 100, 2) if total else 0,
            "median_ppp": overall["median_ppp"],
            "p25_ppp": overall["p25_ppp"],
            "p75_ppp": overall["p75_ppp"],
            "iqr_ratio_pct": overall["iqr_ratio_pct"],
            "median_amount": overall["median_amount"],
            "avg_area": overall["avg_area"],
            "ref_count": cur_s["count"],
            "ref_ppp": cur_s["median_ppp"],
            "mom_count_pct": _pct_change(cur_s["count"], prev_s["count"]),
            "mom_ppp_pct": _pct_change(cur_s["median_ppp"], prev_s["median_ppp"]),
            "outside_pct": outside,
            "outside_judged": len(judged),
        })
    # 중위 평당가 내림차순. 단가가 없는 지역(거래 0건)은 뒤로 보낸다.
    rows.sort(key=lambda r: (r["median_ppp"] is not None, r["median_ppp"] or 0), reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def sido_rollup(records, months):
    anchor = week_anchor(records)
    rows = []
    for sido, group in _group(records, lambda r: r["region"].split(" ")[0]).items():
        rows.append({"sido": sido, **summarize(group),
                     "monthly": monthly_series(group, months),
                     "weekly": weekly_series(group, anchor=anchor)})
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


def complex_histories(records, keys, max_points=40):
    """지정한 (시군구, 단지, 면적타입) 조합의 거래 이력.

    신고가 표는 "+43.3% 갱신" 같은 이벤트만 던져서, 그게 얼마나 이례적인지 판단할
    맥락이 없다. 해당 조합의 거래 궤적을 함께 실어 대시보드에서 펼쳐 볼 수 있게 한다.
    keys 를 받는 이유는 전체 28,488개 조합을 다 실으면 JSON 이 감당이 안 되기 때문이다.
    """
    wanted = set(keys)
    grouped = defaultdict(list)
    for r in records:
        atype = _area_type(r)
        if not atype or not r.get("apt"):
            continue
        key = (r["lawd_cd"], r["apt"], atype)
        if key in wanted:
            grouped[key].append(r)

    out = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda r: r["deal_date"])
        # 오래된 것부터 잘라내 최근 궤적을 남긴다.
        rows = rows[-max_points:]
        out["|".join((key[0], key[1], str(key[2])))] = [
            {"d": r["deal_date"], "amt": r["amount_manwon"],
             "ppp": r["price_per_pyeong"], "fl": r["floor"]}
            for r in rows
        ]
    return out


def complex_shards(records, months):
    """시군구별 단지 x 전용타입 월별 궤적. 관심단지가 필요할 때만 내려받는 조각들.

    전부 페이지에 심으면 안 되는 이유는 재봤다 - 조합이 31,910개고 15개월치를 다 실으면
    2.8MB 가 는다. index.html 이 이미 1.7MB 라 첫 화면이 그만큼 느려진다. 반면 관심단지는
    보통 서너 개고 한두 시군구에 몰려 있어서, 그 시군구 조각만 받아오면 20~30KB 로 끝난다.

    조각을 받지 못해도(오프라인, file:// 로 연 경우) 관심단지 목록 자체는 페이지에 이미
    실린 price_index 요약으로 돌아간다. 궤적 그래프만 빠진다.

    행 형식은 [단지명, 전용타입, [[월인덱스, 중위거래가, 건수], ...]] 다. 키 이름을
    3만 번 반복하지 않으려고 배열로 눕혔다.
    """
    by_region = defaultdict(lambda: defaultdict(list))
    idx = {ym: i for i, ym in enumerate(months)}
    for r in records:
        atype = _area_type(r)
        if not atype or not r.get("apt") or r.get("amount_manwon") is None:
            continue
        if r["deal_ym"] not in idx:
            continue
        by_region[r["lawd_cd"]][(r["apt"], atype)].append(r)

    shards = {}
    for code, groups in by_region.items():
        rows = []
        for (apt, atype), rs in groups.items():
            by_month = defaultdict(list)
            for r in rs:
                by_month[idx[r["deal_ym"]]].append(r["amount_manwon"])
            points = [[mi, round(median(v)), len(v)] for mi, v in sorted(by_month.items())]
            rows.append([apt, atype, points])
        rows.sort(key=lambda x: (x[0], x[1]))
        shards[code] = {
            "lawd_cd": code,
            "region": region_name(code),
            "months": months,
            "columns": ["apt", "area_type", "points"],
            "point_columns": ["month_index", "median_amount", "count"],
            "rows": rows,
        }
    return shards


def floor_premium(records, min_group=6, min_regions=1):
    """층 프리미엄. 반드시 단지 x 면적타입 **안에서** 비교한다.

    전체 평균으로 저층/고층을 비교하면 +12.6% 가 나오는데, 고층 단지가 대체로 신축이라
    건축연차 효과가 섞인 값이다. 같은 단지 같은 타입 안에서 각 거래가 그 조합의 중위값
    대비 몇 % 인지를 구하고, 그 편차를 층 구간별로 모아야 순수 층 효과가 남는다.
    """
    groups = defaultdict(list)
    for r in records:
        atype = _area_type(r)
        if atype and r.get("apt") and r.get("floor") is not None and r.get("price_per_pyeong"):
            groups[(r["lawd_cd"], r["apt"], atype)].append(r)

    buckets = [("1~3층", 1, 3), ("4~9층", 4, 9), ("10~14층", 10, 14),
               ("15~19층", 15, 19), ("20층~", 20, 10**6)]
    devs = {label: [] for label, _, _ in buckets}
    used_groups = 0
    for rows in groups.values():
        if len(rows) < min_group:
            continue
        base = median([r["price_per_pyeong"] for r in rows])
        if not base:
            continue
        used_groups += 1
        for r in rows:
            fl = r["floor"]
            for label, lo, hi in buckets:
                if lo <= fl <= hi:
                    devs[label].append((r["price_per_pyeong"] / base - 1) * 100)
                    break

    rows_out = []
    for label, _, _ in buckets:
        v = devs[label]
        rows_out.append({
            "bucket": label,
            "count": len(v),
            # 같은 단지·타입의 중위값 대비 편차(%). 0이면 그 단지 평균과 같다는 뜻.
            "premium_pct": round(median(v), 1) if v else None,
        })
    return {"buckets": rows_out, "groups_used": used_groups, "min_group": min_group}


def price_index(records, months, min_deals=3, recent_months=9):
    """단지 × 면적타입별 시세 인덱스. "예산 8억으로 어디를 살 수 있나"의 재료다.

    지금 대시보드는 지역 -> 가격 방향이다("강남구는 평당 1억"). 실사용자의 질문은
    반대라서, 가격 -> 지역으로 뒤집으려면 단지 단위 시세표가 필요하다.

    설계에서 정한 것:
      - 거래 min_deals 건 미만은 버린다. 1~2건짜리 시세는 그 거래에 통째로 좌우된다.
      - 최근 recent_months 개월 거래만 쓴다. 15개월 전 가격을 "지금 살 수 있는 값"으로
        내놓으면 안 된다.
      - 대표값은 중위다. 같은 단지·타입 안에서도 층·향 때문에 편차가 있다.
    """
    window = set(months[-recent_months:])
    # 직전 창. "지금 얼마"만으로는 관심단지를 지켜볼 수가 없어서 "그때 대비 얼마"를 같이 낸다.
    # 단지별 15개월 궤적을 통째로 실으면 1.8~2.8MB 라 페이지가 두 배가 되는데, 창 두 개를
    # 비교하는 것으로 줄이면 약 180KB 로 끝난다. 실측으로 15,304개 중 67%가 양쪽 창에
    # 모두 3건 이상이라 변화율이 나온다.
    prior = set(months[:-recent_months])
    groups = defaultdict(list)
    prev_groups = defaultdict(list)
    umd_of = {}
    for r in records:
        atype = _area_type(r)
        if not atype or not r.get("apt") or r.get("amount_manwon") is None:
            continue
        key = (r["lawd_cd"], r["region"], r["apt"], atype)
        if r["deal_ym"] in window:
            groups[key].append(r)
            umd_of.setdefault(key, r.get("umd") or "")
        elif r["deal_ym"] in prior:
            prev_groups[key].append(r)

    # 13,000행에 딕셔너리 키 이름을 매번 싣으면 JSON 이 3MB 를 넘는다(키 이름만
    # 행당 110바이트). 배열로 눕히고 지역명은 코드->이름 표로 한 번만 싣는다.
    # 순서는 아래 COLUMNS 와 정확히 일치해야 한다.
    region_names = {}
    # 법정동 이름도 행마다 문자열로 실으면 15,000행 x 10바이트가 그대로 붙는다.
    # 이름은 1,000개 남짓이라 표로 한 번만 싣고 행에는 번호를 둔다.
    umd_names, umd_idx = [], {}
    rows = []
    for (code, region, apt, atype), rs in groups.items():
        if len(rs) < min_deals:
            continue
        region_names[code] = region
        amts = sorted(r["amount_manwon"] for r in rs)
        ppps = [r["price_per_pyeong"] for r in rs if r.get("price_per_pyeong")]
        umd = umd_of.get((code, region, apt, atype), "")
        if umd not in umd_idx:
            umd_idx[umd] = len(umd_names)
            umd_names.append(umd)
        prev = prev_groups.get((code, region, apt, atype), [])
        # 직전 창도 min_deals 를 넘어야 비교값을 낸다. 한두 건짜리와 견주면
        # "6개월 새 30% 올랐다" 같은 값이 그 한 건 때문에 나온다.
        prev_med = (round(median([r["amount_manwon"] for r in prev]))
                    if len(prev) >= min_deals else None)
        rows.append([
            code, apt, atype,
            round(median(amts)), amts[0], amts[-1],
            len(rs),
            round(median(ppps)) if ppps else None,
            rs[-1].get("build_year"),
            umd_idx[umd],
            prev_med,
            len(prev),
        ])
    rows.sort(key=lambda r: r[3])
    return {
        "columns": ["lawd_cd", "apt", "area_type", "median_amount",
                    "min_amount", "max_amount", "count", "median_ppp", "build_year",
                    "umd", "prev_median", "prev_count"],
        "rows": rows,
        "umd_names": umd_names,
        "prior_window": [months[0], months[-recent_months - 1]] if prior else [],
        "region_names": region_names,
        "window": months[-recent_months:],
        "min_deals": min_deals,
    }


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


def settlement_series(records, months, min_rows=30, days_min_rate=80.0):
    """월별 등기완료율과 계약->등기 소요일. "이 달 수치를 얼마나 믿을 수 있나"의 측정값.

    지금까지 "최근 2개월은 잠정"이라고 규칙으로 선언만 했다. 등기일자를 쓰면 그것을
    관측값으로 바꿀 수 있다. 실측: 계약에서 등기까지 중위 69일이고, 월별 등기완료율은
    2025-12 99.3% -> 2026-07 11.0% 로 최근일수록 급락한다.

    주의 - 이 값은 시장 지표가 아니라 관측 성숙도 지표다. 최근 달의 완료율이 낮은 것은
    등기가 안 될 거래여서가 아니라 아직 등기할 시간이 안 지났기 때문이다. 해제율과
    같은 종류의 관측 편향이라, 시계열로 "등기가 잘 안 된다"고 읽으면 안 된다.
    """
    by = _group(records, lambda r: r["deal_ym"])
    rows = []
    for ym in months:
        group = by.get(ym, [])
        done = [r for r in group if r.get("rgst_date")]
        gaps = [r["days_to_rgst"] for r in done if r.get("days_to_rgst") is not None]
        # 표본이 얇은 달의 비율은 통째로 튄다. 아예 내지 않는다.
        rate = (round(len(done) / len(group) * 100, 1)
                if len(group) >= min_rows else None)
        # 등기가 아직 절반도 안 끝난 달의 "중위 소요일"은 빠른 건만 보고 계산한 값이라
        # 늘 짧게 나온다(실측: 완료율 3.6%인 달이 "중위 2일"). 생존 편향이라 내지 않는다.
        # 이걸 그대로 보이면 "등기는 이틀이면 된다"로 읽힌다.
        biased = rate is None or rate < days_min_rate
        rows.append({
            "ym": ym,
            "total": len(group),
            "registered": len(done),
            "rate_pct": rate,
            "median_days": (None if biased or len(gaps) < min_rows
                            else round(median(gaps))),
            "days_biased": biased,
        })
    allgaps = [r["days_to_rgst"] for r in records
               if r.get("days_to_rgst") is not None and 0 <= r["days_to_rgst"] < 400]
    return {
        "months": rows,
        "min_rows": min_rows,
        "days_min_rate": days_min_rate,
        "overall_median_days": round(median(allgaps)) if allgaps else None,
        "p25_days": round(quantiles(allgaps, n=4)[0]) if len(allgaps) >= 4 else None,
        "p75_days": round(quantiles(allgaps, n=4)[2]) if len(allgaps) >= 4 else None,
        "measured": len(allgaps),
    }


def outside_agent_stats(records, months, min_rows=200):
    """중개사 소재지가 매물 소재지와 다른 거래의 비중 - 원정 매수의 대리 지표.

    "이 동네를 사는 사람이 이 동네 사람인가"에 직접 답하는 필드는 실거래가 API 에 없다.
    중개사 소재지는 그 질문에 가장 가까운 관측값이다. 매수자가 자기 생활권 중개사를
    데려오는 경우가 많기 때문이다.

    한계는 분명하다 - 매수자가 아니라 중개사의 소재지이고, 매도측이 부른 중개사일 수도
    있다. 그래서 "외지인 매수 비율"이라 부르지 않고 "외지 중개 비중"이라고만 한다.
    직거래는 중개사가 없으니 애초에 분모에서 빠진다.

    실측: 수도권 평균 6.6%, 서울 중구 26.0% 부터 고양 덕양구 1.5% 까지 17배 차이.
    """
    def share(group):
        judged = [r for r in group if r.get("is_outside_agent") is not None]
        if len(judged) < min_rows:
            return None, len(judged)
        out = sum(1 for r in judged if r["is_outside_agent"])
        return round(out / len(judged) * 100, 1), len(judged)

    overall, n = share(records)
    regions = []
    for code, group in _group(records, lambda r: r["lawd_cd"]).items():
        pct, judged = share(group)
        if pct is None:
            continue
        regions.append({"lawd_cd": code, "region": group[0]["region"],
                        "outside_pct": pct, "judged": judged})
    regions.sort(key=lambda r: r["outside_pct"], reverse=True)

    by_month = _group(records, lambda r: r["deal_ym"])
    series = []
    for ym in months:
        pct, judged = share(by_month.get(ym, []))
        series.append({"ym": ym, "outside_pct": pct, "judged": judged})
    return {"overall_pct": overall, "judged": n, "min_rows": min_rows,
            "regions": regions, "monthly": series}


def party_stats(records, months, min_rows=200):
    """매도자·매수자 구성(개인/법인/공공기관). 법인 순매도 흐름을 본다.

    실측: 법인 매도 2.25% 대 법인 매수 0.67% 로 법인이 순매도 쪽이다. 월별로는
    2025-06 1.24% -> 2025-12 2.31% -> 2026-06 1.04% 로 움직였다.
    """
    def split(group, key):
        c = Counter(r.get(key) or "미상" for r in group)
        total = sum(c.values()) or 1
        return {k: {"count": v, "pct": round(v / total * 100, 2)}
                for k, v in c.most_common()}

    def corp_pct(group, key):
        if len(group) < min_rows:
            return None
        return round(sum(1 for r in group if r.get(key) == "법인") / len(group) * 100, 2)

    by_month = _group(records, lambda r: r["deal_ym"])
    series = [{"ym": ym,
               "seller_corp_pct": corp_pct(by_month.get(ym, []), "seller"),
               "buyer_corp_pct": corp_pct(by_month.get(ym, []), "buyer"),
               "count": len(by_month.get(ym, []))}
              for ym in months]

    regions = []
    for code, group in _group(records, lambda r: r["lawd_cd"]).items():
        s, b = corp_pct(group, "seller"), corp_pct(group, "buyer")
        if s is None:
            continue
        regions.append({"lawd_cd": code, "region": group[0]["region"], "count": len(group),
                        "seller_corp_pct": s, "buyer_corp_pct": b,
                        "net_corp_sell_pct": round(s - (b or 0), 2)})
    regions.sort(key=lambda r: r["net_corp_sell_pct"], reverse=True)
    return {"seller": split(records, "seller"), "buyer": split(records, "buyer"),
            "monthly": series, "regions": regions, "min_rows": min_rows}


AGE_BUCKETS = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 30), (30, 40), (40, 999)]
REBUILD_AGE = 30          # 재건축 연한. 이 나이부터 "기대"가 값에 실린다고 본다


def rebuild_premium(records, months, this_year=None, min_deals=3, min_complexes=8,
                    min_base=3, top_n=60):
    """재건축 기대 분해 - 낡았는데 비싼 단지를 같은 동네 안에서 골라낸다.

    아파트값은 보통 나이가 들수록 내려간다. 실측으로 수도권 중위 평당가는 0~5년
    2,762만원에서 25~30년 2,232만원까지 계속 떨어진다. 그런데 40년 이상에서 4,109만원
    으로 되튄다. 이 반등이 건물값일 리는 없으니 재건축 기대가 값에 실린 것으로 본다.

    측정 방법:
      같은 법정동 안에서 30년 미만 단지들의 중위 평당가를 기준선으로 잡고, 30년 이상
      단지가 그 기준선보다 얼마나 비싼지를 잰다. 동 단위로 비교하는 것이 핵심이다.
      시군구로 묶으면 강남구 도곡동과 개포동이 한 기준선에 들어가, 재건축 기대가 아니라
      동네 차이를 재게 된다.

    한계 - 대지지분 데이터가 실거래가 API 에 없다. 재건축 기대의 크기는 결국 대지지분이
    좌우하는데 그걸 못 보고 값의 잔차로만 추정한다. 그래서 이 값은 "재건축 가치"가 아니라
    "같은 동네 새 아파트 대비 웃돈"이다. 학군·역세권처럼 나이와 무관한 이유로 비싼 노후
    단지도 같이 올라온다.
    """
    year = this_year or date.today().year
    window = set(months)
    groups = defaultdict(list)
    for r in records:
        atype = _area_type(r)
        if (not atype or not r.get("apt") or not r.get("build_year")
                or not r.get("price_per_pyeong") or r["deal_ym"] not in window):
            continue
        groups[(r["lawd_cd"], r.get("umd") or "", r["apt"], atype)].append(r)

    units = []
    for (code, umd, apt, atype), rs in groups.items():
        if len(rs) < min_deals:
            continue
        units.append({
            "lawd_cd": code, "region": rs[0]["region"], "umd": umd, "apt": apt,
            "area_type": atype, "age": year - rs[-1]["build_year"],
            "build_year": rs[-1]["build_year"], "count": len(rs),
            "median_ppp": round(median([r["price_per_pyeong"] for r in rs])),
            "median_amount": round(median([r["amount_manwon"] for r in rs])),
        })

    # 수도권 전체 연식대 곡선. U자 반등을 화면에서 그대로 보여주려고 같이 낸다.
    curve = []
    for lo, hi in AGE_BUCKETS:
        vals = [u["median_ppp"] for u in units if lo <= u["age"] < hi]
        curve.append({"bucket": f"{lo}~{hi}년" if hi < 999 else f"{lo}년~",
                      "lo": lo, "count": len(vals),
                      "median_ppp": round(median(vals)) if vals else None})

    by_umd = defaultdict(list)
    for u in units:
        by_umd[(u["lawd_cd"], u["umd"])].append(u)

    rows, no_base = [], 0
    for key, items in by_umd.items():
        if len(items) < min_complexes:
            continue
        young = [u["median_ppp"] for u in items if u["age"] < REBUILD_AGE]
        # 동 전체가 노후 단지면 기준선이 없다. 지어내지 않고 건너뛴다.
        if len(young) < min_base:
            no_base += 1
            continue
        base = median(young)
        if not base:
            continue
        for u in items:
            if u["age"] < REBUILD_AGE:
                continue
            rows.append({**u, "base_ppp": round(base),
                         "premium_pct": round((u["median_ppp"] - base) / base * 100, 1)})
    rows.sort(key=lambda r: r["premium_pct"], reverse=True)
    prems = [r["premium_pct"] for r in rows]
    return {
        "curve": curve,
        "rows": rows[:top_n],
        "total": len(rows),
        "median_pct": round(median(prems), 1) if prems else None,
        "p25_pct": round(quantiles(prems, n=4)[0], 1) if len(prems) >= 4 else None,
        "p75_pct": round(quantiles(prems, n=4)[2], 1) if len(prems) >= 4 else None,
        "over30_count": sum(1 for p in prems if p > 30),
        "rebuild_age": REBUILD_AGE, "min_complexes": min_complexes,
        "min_deals": min_deals, "skipped_no_base": no_base, "this_year": year,
    }


def week_anchor(records):
    """전체 거래에서 가장 최근 계약이 속한 주(월요일).

    시도별 주간 시계열의 x축을 맞추려면 기준 주가 하나여야 한다. 각자 자기 최신 주를
    끝으로 잡으면 서울과 인천의 같은 자리가 다른 주가 되어 필터를 바꿀 때마다 축이 밀린다.
    """
    from datetime import date as _date, timedelta
    last = None
    for r in records:
        try:
            d = _date(*map(int, r["deal_date"].split("-")))
        except (ValueError, TypeError):
            continue
        if last is None or d > last:
            last = d
    return None if last is None else last - timedelta(days=last.weekday())


def weekly_series(records, weeks=26, min_rows=1, anchor=None):
    """계약일 기준 주간 시계열.

    월별 차트는 최신 달이 아직 열흘밖에 안 지났어도 반토막으로 보인다. 주 단위로 끊으면
    그 착시가 없다. 다만 신고 지연(계약 후 30일)은 그대로라 마지막 4~5주는 여전히
    차오르는 중이고, 그 구간은 provisional 로 표시해 화면에서 구분한다.
    """
    from datetime import date as _date, timedelta

    def monday(d):
        return d - timedelta(days=d.weekday())

    by = defaultdict(list)
    for r in records:
        try:
            d = _date(*map(int, r["deal_date"].split("-")))
        except (ValueError, TypeError):
            continue
        by[monday(d)].append(r)
    last = anchor or (max(by) if by else None)
    if last is None:
        return {"weeks": [], "provisional_weeks": 0}

    keys = [last - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    # 신고 지연이 30일이므로 마지막 5주는 아직 차오르는 중이다.
    prov = set(keys[-5:])
    rows = []
    for k in keys:
        group = by.get(k, [])
        ppp = [r["price_per_pyeong"] for r in group if r.get("price_per_pyeong")]
        rows.append({"week": k.isoformat(), "count": len(group),
                     "median_ppp": round(median(ppp)) if len(ppp) >= min_rows else None,
                     "provisional": k in prov})
    return {"weeks": rows, "provisional_weeks": 5,
            "note": "계약일 기준 주(월요일 시작). 마지막 5주는 신고 지연으로 아직 차오르는 중이다."}


def anomaly_flags(records, months, recent_months=6, scan_months=12, discount_pct=30,
                  stale_days=180, min_peers=5, top_n=200):
    """눈여겨볼 거래를 규칙으로 뽑는다. "이상"이 아니라 "확인이 필요한" 것들이다.

    네 가지 신호를 각각 독립적으로 붙인다. 하나만으로는 아무 뜻도 아니고, 겹칠수록
    설명이 필요해지는 것들이다.
      - 시세 괴리: 같은 단지 x 같은 전용타입의 중위가 대비 discount_pct% 이상 싸다.
        단지 안에서 비교하므로 지역·평형 차이는 이미 통제돼 있다.
      - 직거래: 중개사 없이 이뤄진 거래. 실측으로 중개거래보다 중위 평당가가 28.5% 낮은데,
        가족 간 증여성 거래가 섞이기 때문으로 알려져 있다.
      - 법인 매도: 매도자가 법인.
      - 등기 지연: 계약 후 stale_days 가 지나도록 등기가 없다.

    쓰지 말아야 할 방식을 분명히 해둔다 - 이 목록은 위법의 증거가 아니다. 신축 저층,
    특약이 붙은 매매, 단순 신고 오류 모두 같은 신호를 낸다. 판단 재료이지 판단이 아니다.

    창이 두 개인 이유:
      - 훑는 범위는 scan_months(12개월). 등기 지연은 계약 후 stale_days(180일)가
        지나야 판정되는데, 6개월만 훑으면 그 조건에 닿는 거래가 아예 없어 신호가
        구조적으로 죽는다(실제로 처음엔 한 건도 안 걸렸다).
      - 시세 기준은 recent_months(6개월) 안에서만 잡는다. 기준을 12개월로 넓히면
        그 사이 오르내린 만큼이 통째로 "싸게 팔렸다"로 잡힌다. 그래서 6개월 밖의
        거래는 시세 괴리를 아예 판정하지 않고, 시점과 무관한 신호(직거래·법인매도·
        등기지연)로만 걸린다.
    """
    from datetime import date as _date

    peer_window = set(months[-recent_months:])
    scan_window = set(months[-scan_months:])
    # 시세 기준은 최근 거래분으로만 잡는다. 오래된 값을 기준 삼으면 시장이 움직인 만큼
    # 과거 거래가 통째로 "싸게 팔린 것"으로 잡힌다.
    peers = defaultdict(list)
    for r in records:
        atype = _area_type(r)
        if (atype and r.get("apt") and r.get("amount_manwon") is not None
                and r["deal_ym"] in peer_window):
            peers[(r["lawd_cd"], r["apt"], atype)].append(r["amount_manwon"])
    med = {k: median(v) for k, v in peers.items() if len(v) >= min_peers}

    today = date.today()
    rows = []
    for r in records:
        if r["deal_ym"] not in scan_window:
            continue
        atype = _area_type(r)
        key = (r["lawd_cd"], r.get("apt"), atype)
        # 6개월 밖의 거래에는 기준이 없다(위 주석 참고). gap 이 None 으로 남는다.
        base = med.get(key) if r["deal_ym"] in peer_window else None
        flags, gap = [], None
        if base and r.get("amount_manwon") is not None:
            gap = round((r["amount_manwon"] - base) / base * 100, 1)
            if gap <= -discount_pct:
                flags.append("시세괴리")
        if not _is_broker(r):
            flags.append("직거래")
        if r.get("seller") == "법인":
            flags.append("법인매도")
        if not r.get("rgst_date"):
            try:
                age = (today - _date(*map(int, r["deal_date"].split("-")))).days
            except (ValueError, TypeError):
                age = 0
            if age >= stale_days:
                flags.append("등기지연")
        # 올릴 조건: 드문 신호(시세괴리·등기지연)가 하나 이상 있고, 신호가 둘 이상 겹칠 것.
        #
        # 처음엔 "둘 이상"만 걸었는데 목록의 82%가 직거래+법인매도로 채워졌다(2,350건).
        # 법인이 중개사 없이 파는 것은 흔한 일이라 그 조합만으로는 확인할 거리가 못 된다.
        # 반면 시세 괴리와 등기 지연은 각각 369건·150건뿐이고 둘 다 "왜?"가 붙는 신호다.
        # 그래서 이 둘을 닻으로 삼고, 직거래·법인매도는 정황을 더하는 역할만 하게 했다.
        if len(flags) >= 2 and ("시세괴리" in flags or "등기지연" in flags):
            rows.append({
                "deal_date": r["deal_date"], "region": r["region"], "umd": r.get("umd"),
                "apt": r.get("apt"), "area_type": atype, "floor": r.get("floor"),
                "amount_manwon": r.get("amount_manwon"),
                "peer_median": round(base) if base else None,
                "gap_pct": gap, "flags": flags, "seller": r.get("seller"),
                "buyer": r.get("buyer"), "registered": bool(r.get("rgst_date")),
            })
    # 겹친 신호가 많은 순, 같으면 괴리가 큰 순
    rows.sort(key=lambda x: (len(x["flags"]), -(x["gap_pct"] or 0)), reverse=True)
    shown = rows[:top_n]
    counts = Counter(f for x in rows for f in x["flags"])
    # 화면의 탭은 실제로 보여줄 수 있는 건수를 달아야 한다. 전체 집계 수를 달면
    # "등기지연 150"을 눌렀는데 10건만 나오는 일이 생긴다.
    shown_counts = Counter(f for x in shown for f in x["flags"])
    combos = Counter("+".join(x["flags"]) for x in rows)
    return {"rows": shown, "total": len(rows),
            "shown_flag_counts": dict(shown_counts),
            "window": months[-scan_months:], "peer_window": months[-recent_months:],
            "flag_counts": dict(counts), "combo_counts": dict(combos.most_common()),
            "discount_pct": discount_pct, "stale_days": stale_days,
            "min_peers": min_peers}


def region_monthly(records, months, min_samples=5):
    """시군구 × 월 요약. 입체 지도의 시간 재생(월을 넘기며 높이가 변하는 화면)에 쓴다.

    행마다 키 이름을 싣지 않고 월 순서에 맞춘 배열로 눕힌다. 83개 시군구 × 15개월에
    {"ym":..,"count":..,"median_ppp":..} 를 다 실으면 60KB 가 넘는데, 배열이면 6KB다.
    표본이 min_samples 미만인 달은 중위 평당가를 비운다. 2~3건짜리 중위값으로 지도
    기둥이 솟으면 근거 없는 변동을 시장 변화처럼 보여주게 된다.
    """
    idx = {ym: i for i, ym in enumerate(months)}
    out = {}
    for code, group in _group(records, lambda r: r["lawd_cd"]).items():
        counts = [0] * len(months)
        ppps = [None] * len(months)
        for ym, rs in _group(group, lambda r: r["deal_ym"]).items():
            i = idx.get(ym)
            if i is None:
                continue
            counts[i] = len(rs)
            vals = [r["price_per_pyeong"] for r in rs if r.get("price_per_pyeong")]
            if len(vals) >= min_samples:
                ppps[i] = round(median(vals))
        out[code] = {"count": counts, "ppp": ppps}
    return {"months": months, "min_samples": min_samples, "regions": out}


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


def jeonse_ratio(sale_records, rent_records, min_pairs=2, min_region_samples=5):
    """전세가율 = 전세보증금 / 매매가.

    지역 단위로 중위 전세금 / 중위 매매가를 나누면 안 된다. 두 모집단의 단지·평형
    구성이 달라서(전세는 신축 대단지에, 매매는 재건축 노후단지에 몰리는 식) 비율이
    실제와 크게 어긋난다. 그래서 **같은 단지 x 같은 면적타입**끼리 먼저 짝을 짓고,
    그 비율들의 중위값을 지역값으로 올린다.

    한쪽이라도 표본이 min_pairs 미만인 조합은 버린다. 단지-타입 표본이 1건이면
    비율이 그 한 건에 통째로 좌우된다.
    """
    sale = defaultdict(list)
    for r in sale_records:
        atype = _area_type(r)
        if atype and r.get("apt") and r.get("amount_manwon"):
            sale[(r["lawd_cd"], r["apt"], atype)].append(r["amount_manwon"])

    rent = defaultdict(list)
    for r in rent_records:
        if r.get("is_jeonse") and r.get("area_type") and r.get("apt") and r.get("deposit_manwon"):
            rent[(r["lawd_cd"], r["apt"], r["area_type"])].append(r["deposit_manwon"])

    per_region = defaultdict(list)
    pairs = 0
    for key, sale_amounts in sale.items():
        deposits = rent.get(key)
        if not deposits or len(sale_amounts) < min_pairs or len(deposits) < min_pairs:
            continue
        ratio = median(deposits) / median(sale_amounts) * 100
        per_region[key[0]].append(ratio)
        pairs += 1

    rows = []
    for code, ratios in per_region.items():
        if len(ratios) < min_region_samples:
            continue
        rows.append({"lawd_cd": code, "region": region_name(code),
                     "jeonse_ratio_pct": round(median(ratios), 1),
                     "matched_complexes": len(ratios)})
    rows.sort(key=lambda r: r["jeonse_ratio_pct"], reverse=True)

    overall = median([r for rs in per_region.values() for r in rs]) if per_region else None
    return {
        "regions": rows,
        "overall_pct": round(overall, 1) if overall is not None else None,
        "matched_pairs": pairs,
        "min_pairs": min_pairs,
        "min_region_samples": min_region_samples,
    }


def _views(records, months):
    """한 벌의 거래 목록으로 KPI/추이/랭킹을 만든다. 전체본과 중개거래본에 같이 쓴다."""
    return {
        "kpi": build_kpi(records, months),
        "monthly": monthly_series(records, months),
        "sido": sido_rollup(records, months),
        "regions": region_ranking(records, months),
        "weekly": weekly_series(records, anchor=week_anchor(records)),
        # 입체 지도의 시간 재생용. 전체본/중개거래본이 각자 갖고 있어야 지도에서
        # 직거래를 빼도 재생이 같은 기준으로 돈다.
        "region_monthly": region_monthly(records, months),
    }


def analyze(payload, include_canceled=False, expected_regions=None, rent_payload=None):
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
        "record_highs": None,   # 아래에서 채운다
        "cancel_rate": cancel_rate_series(raw, months),
        # 등기일자·중개사 소재지·매도자 구분은 원본에 늘 있었는데 쓰지 않고 있었다.
        # 채움률은 각각 74.8% / 95.1% / 100% 다.
        "settlement": settlement_series(records, months),
        "outside_agent": outside_agent_stats(records, months),
        "party": party_stats(records, months),
        "anomalies": anomaly_flags(records, months),
        # 재건축 기대는 직거래를 빼고 본다. 시세보다 28.5% 낮게 신고되는 건들이 섞이면
        # 노후 단지의 웃돈이 실제보다 작게 나온다.
        "rebuild": rebuild_premium(broker or records, months),
    }
    rh = record_highs(records, months)
    result["record_highs"] = rh
    # 표에 실제로 뜨는 행의 조합만 이력을 싣는다. 전체 28,488개를 다 넣으면 JSON 이
    # 감당이 안 되고, 화면에서 펼쳐 보는 것도 이 행들뿐이다.
    keys = {(r["region"], r["apt"], r["area_type"]) for r in rh["highs"] + rh["lows"]}
    code_by_region = {}
    for r in records:
        code_by_region.setdefault(r["region"], r["lawd_cd"])
    keys = {(code_by_region.get(reg), apt, at) for reg, apt, at in keys if code_by_region.get(reg)}
    result["complex_history"] = complex_histories(records, keys)
    result["floor_premium"] = floor_premium(records)
    # 예산 역질의용 시세 인덱스. 직거래는 시세보다 28.5% 낮게 신고되는 경우가 많아
    # "이 값이면 살 수 있다"는 표에 섞으면 안 된다.
    result["price_index"] = price_index(broker or records, months)
    # 관심단지 궤적은 시군구별 조각으로 따로 나간다. 여기에는 어느 시군구 조각이
    # 있는지와 어디서 받아오는지만 싣는다.
    result["history_index"] = {
        "path": "history/{lawd_cd}.json",
        "months": months,
        "regions": sorted({r["lawd_cd"] for r in records}),
    }

    if rent_payload:
        rr = rent_payload.get("records", [])
        result["jeonse"] = jeonse_ratio(records, rr)
        result["meta"]["rent_record_count"] = len(rr)
        result["meta"]["jeonse_record_count"] = sum(1 for r in rr if r.get("is_jeonse"))
    return result


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "live/analytics.json"

    with open(src, encoding="utf-8") as f:
        payload = json.load(f)

    rent_payload = None
    rent_path = sys.argv[3] if len(sys.argv) > 3 else None
    if rent_path and os.path.exists(rent_path):
        with open(rent_path, encoding="utf-8") as f:
            rent_payload = json.load(f)

    result = analyze(payload, rent_payload=rent_payload)
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
    if result.get("jeonse"):
        j = result["jeonse"]
        print(f"  전세가율 중위 {j['overall_pct']}% "
              f"(단지x타입 {j['matched_pairs']:,}쌍 매칭, 시군구 {len(j['regions'])}개)")
    pi = result["price_index"]
    print(f"  시세 인덱스 {len(pi['rows']):,}개 단지x타입 "
          f"({pi['window'][0]}~{pi['window'][-1]}, {pi['min_deals']}건 이상)")
    missing = result["meta"]["missing_regions"]
    if missing:
        print(f"  ! 거래 0건 시군구 {len(missing)}개: "
              + ", ".join(m["region"] for m in missing), file=sys.stderr)


if __name__ == "__main__":
    main()
