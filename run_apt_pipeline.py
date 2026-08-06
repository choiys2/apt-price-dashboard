#!/usr/bin/env python3
"""
수집 -> 집계 -> 대시보드 한 번에 실행.

건전성 체크가 붙어 있다. data.go.kr 이 응답하지 않거나 인증키가 만료되면 수집 결과가
0건에 가까워지는데, 그대로 배포하면 어제까지 멀쩡하던 사이트가 통째로 비어버린다.
수집량이 임계치 미만이면 exit code 2 로 끝내고, 워크플로가 배포 단계를 건너뛰어
이미 떠 있는 이전 버전을 그대로 두게 한다(= 배포를 안 하는 것이 곧 롤백이다).

사용법:
  python run_apt_pipeline.py                       # 수도권 15개월
  python run_apt_pipeline.py --sido 서울특별시 --out-dir live
  python run_apt_pipeline.py --sample              # API 없이 합성 데이터로 화면만 확인
"""
import argparse
import json
import os
import sys

from apt_analytics import analyze
from build_apt_dashboard import render
from fetch_apt_trades import CACHE_DIR, collect, load_config
from lawd_codes import regions


def main():
    ap = argparse.ArgumentParser(description="아파트 실거래가 대시보드 파이프라인")
    ap.add_argument("--months", type=int, default=15,
                    help="최근 N개월. 기본 15 — 전년 동월 대비를 내려면 "
                         "기준월(최신월-2)의 12개월 전까지 있어야 해서 15개월이 필요하다")
    ap.add_argument("--sido", default=None, help="시도명으로 한정 (예: 서울특별시)")
    ap.add_argument("--out-dir", default="live")
    ap.add_argument("--cache-dir", default=CACHE_DIR)
    ap.add_argument("--config", default="apt_config.json")
    ap.add_argument("--refresh-months", type=int, default=3,
                    help="최근 N개월은 캐시를 무시하고 재수집 (기본 3)")
    ap.add_argument("--min-records", type=int, default=None,
                    help="이 건수 미만이면 비정상으로 보고 exit 2. "
                         "기본값은 시군구 수 x 개월 x 5")
    ap.add_argument("--sample", action="store_true",
                    help="API 대신 합성 데이터를 써서 화면만 확인한다")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    n_regions = len(regions(args.sido))
    trades_path = os.path.join(args.out_dir, "trades.json")
    analytics_path = os.path.join(args.out_dir, "analytics.json")
    html_path = os.path.join(args.out_dir, "index.html")

    print(f"[1/3] 수집 ({args.months}개월 x {n_regions}개 시군구)")
    if args.sample:
        from make_sample_data import make_records, SEED
        import random
        from datetime import date
        from fetch_apt_trades import month_range
        months = month_range(args.months)
        records = make_records(random.Random(SEED), months)
        full = {"meta": {"synthetic": True, "generated_at": date.today().isoformat(),
                         "months": months, "regions": n_regions, "api_calls": 0,
                         "cache_hits": 0, "record_count": len(records),
                         "canceled_count": sum(1 for r in records if r["canceled"]),
                         "failures": []},
                "records": records}
        print("  합성 데이터 사용 — 실거래가가 아니다")
    else:
        cfg = load_config(args.config)
        full = collect(cfg, months=args.months, sido=args.sido,
                       cache_dir=args.cache_dir, refresh_months=args.refresh_months)

    with open(trades_path, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, separators=(",", ":"))
    m = full["meta"]
    print(f"  -> {trades_path}: 거래 {m['record_count']:,}건, "
          f"API 호출 {m['api_calls']}회, 실패 {len(m['failures'])}건")

    # 건전성 체크: 시군구당 월 5건은 가장 한산한 군 지역 기준으로도 밑도는 수치다.
    threshold = args.min_records if args.min_records is not None else n_regions * args.months * 5
    if m["record_count"] < threshold:
        print(f"\n[중단] 수집량 {m['record_count']:,}건이 임계치 {threshold:,}건 미만이다. "
              f"API 장애나 인증키 문제일 가능성이 높아 배포하지 않는다.", file=sys.stderr)
        if m["failures"]:
            print(f"  실패 예시: {m['failures'][0]}", file=sys.stderr)
        raise SystemExit(2)

    print("[2/3] 집계")
    analytics = analyze(full)
    with open(analytics_path, "w", encoding="utf-8") as f:
        json.dump(analytics, f, ensure_ascii=False, separators=(",", ":"))
    k = analytics["kpi"]
    print(f"  -> {analytics_path}: {k['period_from']}~{k['period_to']}, "
          f"중위 평당가 {k['median_ppp']:,}만원")

    print("[3/3] 대시보드 생성")
    render(analytics, html_path)
    print(f"  -> {html_path} ({os.path.getsize(html_path)/1024:.0f}KB)")
    print(f"\n완료. {html_path} 를 브라우저로 열어 확인할 것.")


if __name__ == "__main__":
    main()
