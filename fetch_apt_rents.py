#!/usr/bin/env python3
"""
국토교통부 아파트 전월세 실거래가 수집기 (data.go.kr / RTMSDataSvcAptRent)

매매 수집기(fetch_apt_trades.py)와 호출 방식·캐시 구조가 같아서 그쪽 함수를 그대로
재사용한다. 엔드포인트와 정규화 규칙만 다르다.

엔드포인트: https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent
전세 판별 : 월세(monthlyRent)가 0 이면 전세, 그 외는 월세

사용법
  python fetch_apt_rents.py probe --lawd 11680 --ymd 202606
  python fetch_apt_rents.py fetch --months 15 --out live/rents.json
"""
import argparse
import json
import os
import sys

import fetch_apt_trades as trades
from fetch_apt_trades import (
    ApiError, PYEONG_PER_M2, _first, _to_float, _to_int, month_range, parse_response,
)
from lawd_codes import region_name, regions

CONFIG_PATH = "apt_config.json"
CACHE_DIR = "data/rent"
BASE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent"
OPERATION = "getRTMSDataSvcAptRent"


def load_config(path=CONFIG_PATH):
    """매매용 설정을 읽고 엔드포인트만 전월세로 갈아끼운다."""
    cfg = trades.load_config(path)
    cfg = dict(cfg)
    cfg["base_url"] = BASE_URL
    cfg["operation"] = OPERATION
    return cfg


def normalize(row, lawd_cd):
    """전월세 원본 -> 집계용 레코드. 보증금·월세가 없으면 None."""
    deposit = _to_int(_first(row, "deposit", "보증금액"))
    monthly = _to_int(_first(row, "monthlyRent", "월세금액")) or 0
    area = _to_float(_first(row, "excluUseAr", "전용면적"))
    year = _to_int(_first(row, "dealYear", "년"))
    month = _to_int(_first(row, "dealMonth", "월"))
    day = _to_int(_first(row, "dealDay", "일")) or 1
    if deposit is None or not year or not month:
        return None

    rec = {
        "lawd_cd": lawd_cd,
        "region": region_name(lawd_cd),
        "umd": _first(row, "umdNm", "법정동"),
        "apt": _first(row, "aptNm", "아파트"),
        "area_m2": area,
        "area_type": int(area) if area else None,
        "deposit_manwon": deposit,
        "monthly_manwon": monthly,
        # 월세가 0이면 전세다. 전세가율은 전세 계약만으로 계산해야 한다.
        "is_jeonse": monthly == 0,
        "deal_ym": f"{year:04d}-{month:02d}",
        "deal_date": f"{year:04d}-{month:02d}-{day:02d}",
        "floor": _to_int(_first(row, "floor", "층")),
        "build_year": _to_int(_first(row, "buildYear", "건축년도")),
        "contract_type": _first(row, "contractType"),   # 신규 / 갱신
        "contract_term": _first(row, "contractTerm"),
    }
    if area and monthly == 0:
        rec["deposit_per_pyeong"] = round(deposit / (area / PYEONG_PER_M2))
    else:
        rec["deposit_per_pyeong"] = None
    return rec


def collect(cfg, months=15, sido=None, cache_dir=CACHE_DIR, refresh_months=3, verbose=True,
            max_consecutive_failures=trades.MAX_CONSECUTIVE_FAILURES):
    """매매 수집과 같은 구조. 캐시 디렉터리와 정규화만 전월세용이다."""
    targets = regions(sido)
    ymds = month_range(months)
    refresh_set = set(ymds[-refresh_months:]) if refresh_months > 0 else set()

    records, failures = [], []
    api_calls = cache_hits = done = consecutive = 0
    total_jobs = len(targets) * len(ymds)
    aborted = False

    for code, _sido, _sgg in targets:
        if aborted:
            break
        for ymd in ymds:
            done += 1
            cached = None if ymd in refresh_set else trades.load_cache(cache_dir, code, ymd)
            if cached is not None:
                cache_hits += 1
                items = cached["items"]
            else:
                try:
                    items, total = trades.fetch_month_raw(cfg, code, ymd)
                except ApiError as e:
                    failures.append({"lawd_cd": code, "deal_ymd": ymd, "error": str(e)})
                    consecutive += 1
                    if verbose:
                        print(f"  ! {code} {ymd} 실패({consecutive}연속): {e}", file=sys.stderr)
                    if consecutive >= max_consecutive_failures:
                        print(f"\n[중단] {consecutive}회 연속 실패. 받아둔 캐시는 저장됐다.",
                              file=sys.stderr)
                        aborted = True
                        break
                    continue
                consecutive = 0
                api_calls += 1
                trades.save_cache(cache_dir, code, ymd, items, total)

            for row in items:
                rec = normalize(row, code)
                if rec:
                    records.append(rec)

        if verbose:
            print(f"  [{done}/{total_jobs}] {region_name(code)} 누적 {len(records):,}건")

    jeonse = sum(1 for r in records if r["is_jeonse"])
    return {
        "meta": {
            "aborted_early": aborted, "months": ymds, "regions": len(targets),
            "api_calls": api_calls, "cache_hits": cache_hits,
            "record_count": len(records), "jeonse_count": jeonse,
            "failures": failures,
        },
        "records": records,
    }


def main():
    ap = argparse.ArgumentParser(description="국토부 아파트 전월세 실거래가 수집기")
    ap.add_argument("--config", default=CONFIG_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="단일 시군구·월 호출해 필드명 확인")
    p.add_argument("--lawd", default="11680")
    p.add_argument("--ymd", default=month_range(4)[0])
    p.add_argument("--timeout", type=int, default=30)
    p.set_defaults(cmd="probe")

    p = sub.add_parser("fetch", help="범위 전체 수집")
    p.add_argument("--months", type=int, default=15)
    p.add_argument("--sido", default=None)
    p.add_argument("--out", default="live/rents.json")
    p.add_argument("--cache-dir", default=CACHE_DIR)
    p.add_argument("--refresh-months", type=int, default=3)
    p.set_defaults(cmd="fetch")

    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.cmd == "probe":
        url = trades.build_url(cfg, args.lawd, args.ymd, 1, num_of_rows=5)
        body, elapsed = trades.request_once(url, args.timeout)
        items, total = parse_response(body)
        print(f"응답 {elapsed:.1f}초 / totalCount={total} / 이번 페이지 {len(items)}건")
        if items:
            print("필드명:", ", ".join(sorted(items[0].keys())))
            print("\n원본 1건:", json.dumps(items[0], ensure_ascii=False, indent=2))
            print("\n정규화 1건:",
                  json.dumps(normalize(items[0], args.lawd), ensure_ascii=False, indent=2))
        return

    result = collect(cfg, months=args.months, sido=args.sido,
                     cache_dir=args.cache_dir, refresh_months=args.refresh_months)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    m = result["meta"]
    print(f"\n완료 -> {args.out}")
    print(f"  전월세 {m['record_count']:,}건 (전세 {m['jeonse_count']:,}건) / "
          f"API {m['api_calls']}회 / 캐시 {m['cache_hits']}회 / 실패 {len(m['failures'])}건")


if __name__ == "__main__":
    main()
