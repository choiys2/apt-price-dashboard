#!/usr/bin/env python3
"""
주간 브리핑 자동 생성 — 대시보드를 열지 않아도 읽히는 요약

대시보드는 능동적으로 열어야 보인다. 안 열면 없는 것과 같아서, 매주 "지금 수도권에서
일어나는 일"을 30초 안에 읽히는 텍스트로 뽑아 저장소에 남긴다. LLM 을 쓰지 않고
규칙으로만 계산한다.

직전 브리핑과 비교하기 위해 핵심 수치를 reports/_state.json 에 남긴다. 첫 실행에는
비교 대상이 없어 스냅샷만 나오고, 두 번째부터 "지난 브리핑 대비"가 붙는다.

사용법:
  python weekly_brief.py live/analytics.json reports/
"""
import json
import os
import sys
from collections import Counter
from datetime import date

STATE_FILE = "_state.json"


def fmt_amount(manwon):
    if manwon is None:
        return "–"
    if manwon >= 10000:
        return f"{manwon/10000:.1f}억"
    return f"{manwon:,}만"


def fmt_pct(v, plus=True):
    if v is None:
        return "–"
    sign = "+" if (plus and v > 0) else ""
    return f"{sign}{v}%"


def delta_line(label, cur, prev, unit="", pct=False):
    """직전 브리핑 대비 변화. 비교 대상이 없으면 현재값만 낸다."""
    if cur is None:
        return f"{label} –"
    now = f"{cur:,}{unit}" if not pct else f"{cur}{unit}"
    if prev is None:
        return f"{label} **{now}**"
    diff = cur - prev
    if diff == 0:
        return f"{label} **{now}** (지난 브리핑과 동일)"
    arrow = "▲" if diff > 0 else "▼"
    return f"{label} **{now}** ({arrow} {abs(diff):,}{unit})"


def build(analytics, prev_state):
    k = analytics["kpi"]
    m = analytics["meta"]
    rh = analytics.get("record_highs") or {}
    dt = analytics.get("deal_type") or {}
    regions = analytics.get("regions") or []
    today = date.today().isoformat()

    L = []
    L.append(f"# 수도권 아파트 실거래 주간 브리핑 ({today})")
    L.append("")
    L.append(f"집계 기간 {k['period_from']} ~ {k['period_to']} · "
             f"시군구 {len(regions)}개 · 거래 {k['total_deals']:,}건")
    L.append("")

    # --- 1. 한눈에 ---
    L.append("## 한눈에")
    L.append("")
    L.append("- " + delta_line("중위 평당가", k["median_ppp"], prev_state.get("median_ppp"), "만원"))
    L.append(f"- 중위 거래가 **{fmt_amount(k['median_amount'])}** · 평균 전용 {k['avg_area']}㎡")
    L.append(f"- 기준월 {k['ref_month']}(확정) 거래 {k['ref']['count']:,}건 · "
             f"전월비 거래량 {fmt_pct(k['mom_count_pct'])} / 평당가 {fmt_pct(k['mom_ppp_pct'])}")
    if k.get("yoy_ppp_pct") is not None:
        L.append(f"- 전년 동월 대비 평당가 {fmt_pct(k['yoy_ppp_pct'])} / "
                 f"거래량 {fmt_pct(k['yoy_count_pct'])}")
    L.append(f"- 최신월 {k['latest_month']}은 신고 지연으로 과소 집계된 잠정치다 "
             f"({k['latest']['count']:,}건).")
    L.append("")

    # --- 2. 오른 곳 / 내린 곳 ---
    moved = [r for r in regions if r.get("mom_ppp_pct") is not None and r["count"] >= 300]
    if moved:
        up = sorted(moved, key=lambda r: r["mom_ppp_pct"], reverse=True)[:5]
        down = sorted(moved, key=lambda r: r["mom_ppp_pct"])[:5]
        L.append(f"## 전월비 평당가 (거래 300건 이상 {len(moved)}개 시군구)")
        L.append("")
        L.append("| 오른 곳 | | 내린 곳 | |")
        L.append("| --- | ---: | --- | ---: |")
        for a, b in zip(up, down):
            L.append(f"| {a['region']} | {fmt_pct(a['mom_ppp_pct'])} | "
                     f"{b['region']} | {fmt_pct(b['mom_ppp_pct'])} |")
        L.append("")

    # --- 3. 신고가 / 신저가 ---
    if rh.get("highs") or rh.get("lows"):
        w = rh.get("window") or []
        span = f"{w[0]}~{w[-1]}" if w else ""
        L.append(f"## 신고가 · 신저가 ({span} 계약분)")
        L.append("")
        L.append("- " + delta_line("신고가", rh.get("high_count"), prev_state.get("high_count"), "건"))
        L.append("- " + delta_line("신저가", rh.get("low_count"), prev_state.get("low_count"), "건"))
        by_region = Counter(r["region"] for r in rh.get("highs", []))
        if by_region:
            top = ", ".join(f"{reg}({n})" for reg, n in by_region.most_common(5))
            L.append(f"- 신고가가 많은 지역: {top}")
        L.append("")
        for label, key in (("갱신폭 큰 신고가", "highs"), ("낙폭 큰 신저가", "lows")):
            rows = (rh.get(key) or [])[:5]
            if not rows:
                continue
            L.append(f"**{label}**")
            L.append("")
            L.append("| 지역 | 단지 | 전용 | 거래가 | 직전 기록 | 갱신폭 |")
            L.append("| --- | --- | ---: | ---: | ---: | ---: |")
            for r in rows:
                L.append(f"| {r['region']} {r['umd']} | {r['apt']} | {r['area_type']}㎡ | "
                         f"{fmt_amount(r['amount_manwon'])} | {fmt_amount(r['prev'])} | "
                         f"{fmt_pct(r['gap_pct'])} |")
            L.append("")

    # --- 4. 시장 구성 ---
    if dt:
        L.append("## 거래 구성")
        L.append("")
        L.append(f"- 직거래 {dt['direct']['count']:,}건({dt['direct_share_pct']}%) · "
                 f"중개거래 대비 중위 평당가 {fmt_pct(dt['direct_vs_broker_pct'])}")
        L.append("  (직거래는 가족 간 증여성 거래가 섞여 시세보다 낮게 신고되는 경우가 많다)")
        fp = analytics.get("floor_premium")
        if fp:
            lo = next((b for b in fp["buckets"] if b["bucket"] == "1~3층"), None)
            hi = next((b for b in fp["buckets"] if b["bucket"] == "20층~"), None)
            if lo and hi and lo["premium_pct"] is not None and hi["premium_pct"] is not None:
                L.append(f"- 층 프리미엄: 저층 {fmt_pct(lo['premium_pct'])} vs "
                         f"20층~ {fmt_pct(hi['premium_pct'])} "
                         f"(같은 단지·타입 안에서 비교)")
        L.append("")

    # --- 4b. 원본에만 있던 신호들 (등기일자·중개사 소재지·매도자 구분) ---
    st, oa, pt, an = (analytics.get(k) for k in
                      ("settlement", "outside_agent", "party", "anomalies"))
    if any((st, oa, pt, an)):
        L.append("## 신호")
        L.append("")
    if st and st.get("overall_median_days"):
        settled = [x for x in st["months"] if x.get("rate_pct") is not None]
        newest = settled[-1] if settled else None
        L.append(f"- 등기까지 중위 **{st['overall_median_days']}일** "
                 f"({st['p25_days']}~{st['p75_days']}일)"
                 + (f" · 최신월 {newest['ym']} 등기완료율 **{newest['rate_pct']}%**"
                    if newest else ""))
        L.append("  (완료율이 낮은 달은 시장이 나빠서가 아니라 아직 등기할 시간이 "
                 "안 지난 것이다. 시계열로 비교하면 안 된다)")
    if oa and oa.get("overall_pct") is not None:
        top = ", ".join(f"{x['region'].split()[-1]} {x['outside_pct']}%"
                        for x in oa["regions"][:3])
        L.append(f"- 외지 중개 비중 **{oa['overall_pct']}%** · 높은 곳: {top}")
        L.append("  (매물 소재지와 중개사 소재지가 다른 거래. 원정 매수의 대리 지표일 뿐 "
                 "매수자 주소가 아니다)")
    if pt and pt.get("seller"):
        s, b = pt["seller"].get("법인"), pt["buyer"].get("법인")
        if s and b:
            L.append(f"- 법인 매도 **{s['pct']}%** vs 매수 **{b['pct']}%** "
                     f"(순매도 {round(s['pct'] - b['pct'], 2)}%p)")
    if an and an.get("total"):
        combos = " · ".join(f"{k} {v:,}건" for k, v in
                            list(an.get("combo_counts", {}).items())[:3])
        L.append(f"- 확인이 필요한 거래 **{an['total']:,}건** "
                 f"({an['window'][0]}~{an['window'][-1]}): {combos}")
        L.append("  (위법의 증거가 아니다. 신축 저층·특약·가족 간 거래·신고 오류가 "
                 "모두 같은 신호를 낸다)")
    if any((st, oa, pt, an)):
        L.append("")

    # --- 5. 데이터 상태 ---
    L.append("## 데이터 상태")
    L.append("")
    L.append(f"- 해제(취소) 거래 {m['excluded_canceled']:,}건 제외")
    pi = analytics.get("price_index")
    if pi:
        L.append(f"- 시세 인덱스 {len(pi['rows']):,}개 단지×전용타입 "
                 f"({pi['window'][0]}~{pi['window'][-1]})")
    if analytics.get("jeonse"):
        j = analytics["jeonse"]
        L.append(f"- 전세가율 중위 {j['overall_pct']}% ({j['matched_pairs']:,}쌍 매칭)")
    else:
        L.append("- 전세가율: 전월세 데이터 미수집")
    missing = m.get("missing_regions") or []
    if missing:
        L.append(f"- ⚠ 거래 0건 시군구 {len(missing)}개: "
                 + ", ".join(x["region"] for x in missing))
    L.append("")
    L.append("---")
    L.append("")
    L.append("출처: 국토교통부 아파트 매매 실거래가 (data.go.kr). "
             "규칙 기반 자동 생성이며 LLM 을 쓰지 않는다. "
             "실거래가는 계약일 기준 신고분이라 최근 2개월은 잠정치다.")

    state = {
        "date": today,
        "median_ppp": k["median_ppp"],
        "total_deals": k["total_deals"],
        "high_count": rh.get("high_count"),
        "low_count": rh.get("low_count"),
    }
    return "\n".join(L), state


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    src = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "reports"
    os.makedirs(out_dir, exist_ok=True)

    with open(src, encoding="utf-8") as f:
        analytics = json.load(f)

    state_path = os.path.join(out_dir, STATE_FILE)
    prev_state = {}
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                prev_state = json.load(f)
        except json.JSONDecodeError:
            prev_state = {}

    text, state = build(analytics, prev_state)

    today = date.today()
    name = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}.md"
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(os.path.join(out_dir, "latest.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"브리핑 생성 -> {path} ({len(text):,}자)")
    if prev_state:
        print(f"  직전 브리핑({prev_state.get('date')}) 대비 비교 포함")
    else:
        print("  직전 브리핑이 없어 스냅샷만 담았다")


if __name__ == "__main__":
    main()
