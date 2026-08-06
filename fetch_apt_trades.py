#!/usr/bin/env python3
"""
국토교통부 아파트 매매 실거래가 수집기 (data.go.kr / RTMSDataSvcAptTrade)

엔드포인트: https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade
호출 단위 : LAWD_CD(시군구 5자리) × DEAL_YMD(계약연월 YYYYMM) 1회 = 그 지역 그 달 전체 거래
응답 포맷 : XML

설계 메모
  - 응답 <item>의 자식 태그를 이름 그대로 전부 담아 원본(raw)으로 캐시한다. 국토부가
    필드를 추가/개명해도 캐시는 살아 있고, 정규화 규칙만 고치면 재수집 없이 반영된다.
  - 과거 월의 거래 내역은 사실상 확정값이라 캐시 히트면 재호출하지 않는다. 다만 신고
    지연·해제(취소) 반영이 있으므로 최근 N개월은 --refresh-months 로 강제 갱신한다.
  - 인증키는 코드/설정파일에 커밋하지 않는다. 로컬은 apt_config.json(gitignore),
    CI는 환경변수 MOLIT_SERVICE_KEY 로 주입한다.

사용법
  python fetch_apt_trades.py probe --lawd 11680 --ymd 202606
      -> 원본 XML과 파싱된 필드명을 그대로 출력 (API 스펙 실측 확인용)
  python fetch_apt_trades.py fetch --months 15 --out live/trades.json
      -> 수도권 전체 시군구 × 최근 15개월 수집 후 정규화 결과 저장
  python fetch_apt_trades.py fetch --months 15 --sido 서울특별시
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from lawd_codes import REGIONS, region_name, regions

CONFIG_PATH = "apt_config.json"
CACHE_DIR = "data/raw"
PYEONG_PER_M2 = 3.305785  # 1평 = 3.305785㎡


# --------------------------------------------------------------------------
# 설정
# --------------------------------------------------------------------------
def load_config(path=CONFIG_PATH):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        # 설정 파일이 없어도 환경변수만으로 동작하게 한다(CI 기본 경로).
        cfg = {}
    env_key = os.environ.get("MOLIT_SERVICE_KEY")
    if env_key:
        cfg["service_key"] = env_key
    cfg.setdefault("base_url", "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade")
    cfg.setdefault("operation", "getRTMSDataSvcAptTrade")
    cfg.setdefault("num_of_rows", 1000)
    cfg.setdefault("request_interval_sec", 0.12)
    cfg.setdefault("timeout_sec", 20)
    cfg.setdefault("retries", 2)
    if not cfg.get("service_key") or cfg["service_key"].startswith("YOUR_"):
        raise SystemExit(
            "서비스키가 없다. apt_config.json 의 service_key 를 채우거나 "
            "환경변수 MOLIT_SERVICE_KEY 를 설정할 것."
        )
    return cfg


# --------------------------------------------------------------------------
# API 호출 / 파싱
# --------------------------------------------------------------------------
class ApiError(RuntimeError):
    pass


def call_api(cfg, lawd_cd, deal_ymd, page_no=1):
    params = {
        "serviceKey": cfg["service_key"],
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "pageNo": page_no,
        "numOfRows": cfg["num_of_rows"],
    }
    url = f"{cfg['base_url']}/{cfg['operation']}?{urlencode(params)}"
    last_err = None
    for attempt in range(cfg["retries"] + 1):
        try:
            with urlopen(url, timeout=cfg["timeout_sec"]) as resp:
                return resp.read().decode("utf-8")
        except (URLError, HTTPError) as e:
            last_err = e
            # 429(요청 과다)는 짧은 재시도로 안 풀리는 경우가 많아 더 오래 쉰다.
            time.sleep(5 if getattr(e, "code", None) == 429 else 1.5 * (attempt + 1))
    raise ApiError(f"네트워크 오류: {last_err} (LAWD_CD={lawd_cd}, DEAL_YMD={deal_ymd})")


def _mask_key(text, cfg):
    key = cfg.get("service_key", "")
    return text.replace(key, "***SERVICE_KEY***") if key else text


def parse_response(xml_text):
    """(items, total_count) 반환. items 는 <item> 자식 태그를 그대로 담은 dict 목록."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise ApiError(f"XML 파싱 실패(응답이 XML이 아님): {xml_text[:300]}")

    # data.go.kr 게이트웨이 단계 오류는 <OpenAPI_ServiceResponse> 로 내려온다.
    if root.tag.endswith("OpenAPI_ServiceResponse"):
        msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or ""
        code = root.findtext(".//returnReasonCode") or ""
        raise ApiError(f"게이트웨이 오류 [{code}] {msg}")

    # 프록시/WAF가 끼어들면 HTML 오류 페이지가 내려오는데, 그것도 XML로는 멀쩡히 파싱된다.
    # 그대로 두면 "거래 0건"으로 조용히 넘어가 빈 대시보드가 배포되므로 여기서 끊는다.
    has_result = root.find(".//resultCode") is not None
    has_items = root.find(".//items") is not None
    if root.tag != "response" and not (has_result or has_items):
        raise ApiError(f"예상치 못한 응답 루트 <{root.tag}>: {xml_text[:300]}")

    result_code = (root.findtext(".//resultCode") or "").strip()
    result_msg = (root.findtext(".//resultMsg") or "").strip()
    # 정상 코드는 서비스에 따라 "00" 또는 "000" 으로 내려온다.
    if result_code and result_code not in ("00", "000"):
        raise ApiError(f"API 오류 [{result_code}] {result_msg}")

    items = []
    for item in root.iter("item"):
        row = {}
        for child in item:
            row[child.tag] = (child.text or "").strip()
        if row:
            items.append(row)

    total_raw = root.findtext(".//totalCount")
    try:
        total = int((total_raw or "0").strip())
    except ValueError:
        total = len(items)
    return items, total


def fetch_month_raw(cfg, lawd_cd, deal_ymd):
    """한 시군구·한 달의 전체 거래를 페이지네이션으로 모두 받아 raw dict 목록으로 반환."""
    items, total = parse_response(call_api(cfg, lawd_cd, deal_ymd, page_no=1))
    page = 1
    while len(items) < total:
        page += 1
        time.sleep(cfg["request_interval_sec"])
        more, _ = parse_response(call_api(cfg, lawd_cd, deal_ymd, page_no=page))
        if not more:
            break
        items.extend(more)
    return items, total


# --------------------------------------------------------------------------
# 캐시
# --------------------------------------------------------------------------
# 캐시는 gzip 으로 저장한다. 수도권 15개월치 원본은 비압축이면 100MB를 넘어 git 에
# 올리기 어렵지만, 반복이 많은 JSON이라 gzip 하면 1/8 수준으로 줄어 저장소에 누적 가능하다.
def cache_path(cache_dir, lawd_cd, deal_ymd):
    return os.path.join(cache_dir, lawd_cd, f"{deal_ymd}.json.gz")


def load_cache(cache_dir, lawd_cd, deal_ymd):
    path = cache_path(cache_dir, lawd_cd, deal_ymd)
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, EOFError):
        return None


def save_cache(cache_dir, lawd_cd, deal_ymd, items, total):
    path = cache_path(cache_dir, lawd_cd, deal_ymd)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "lawd_cd": lawd_cd,
        "deal_ymd": deal_ymd,
        "total_count": total,
        "fetched_at": date.today().isoformat(),
        "items": items,
    }
    # mtime 을 0으로 고정해야 내용이 같을 때 바이트가 동일해져 불필요한 git diff 가 안 생긴다.
    with gzip.GzipFile(path, "wb", mtime=0) as gz:
        gz.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# --------------------------------------------------------------------------
# 정규화
# --------------------------------------------------------------------------
def _first(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    return ""


def _to_int(text):
    digits = re.sub(r"[^\d-]", "", text or "")
    if digits in ("", "-"):
        return None
    return int(digits)


def _to_float(text):
    try:
        return float(re.sub(r"[^\d.\-]", "", text or ""))
    except ValueError:
        return None


def normalize(row, lawd_cd):
    """API 원본 dict -> 대시보드 집계용 레코드. 필수값이 없으면 None."""
    amount = _to_int(_first(row, "dealAmount", "거래금액"))          # 만원 단위
    area = _to_float(_first(row, "excluUseAr", "전용면적"))          # ㎡
    year = _to_int(_first(row, "dealYear", "년"))
    month = _to_int(_first(row, "dealMonth", "월"))
    day = _to_int(_first(row, "dealDay", "일"))
    if amount is None or not year or not month:
        return None

    day = day or 1
    sgg_cd = _first(row, "sggCd", "지역코드") or lawd_cd
    cdeal = _first(row, "cdealType", "해제여부").upper()

    rec = {
        "lawd_cd": lawd_cd,
        "sgg_cd": sgg_cd,
        "region": region_name(lawd_cd),
        "umd": _first(row, "umdNm", "법정동"),
        "apt": _first(row, "aptNm", "아파트"),
        "jibun": _first(row, "jibun", "지번"),
        "area_m2": area,
        "amount_manwon": amount,
        "deal_ym": f"{year:04d}-{month:02d}",
        "deal_date": f"{year:04d}-{month:02d}-{day:02d}",
        "floor": _to_int(_first(row, "floor", "층")),
        "build_year": _to_int(_first(row, "buildYear", "건축년도")),
        "deal_gbn": _first(row, "dealingGbn"),        # 중개거래 / 직거래
        "seller": _first(row, "slerGbn"),             # 개인 / 법인 / 공공기관
        "buyer": _first(row, "buyerGbn"),
        "canceled": cdeal in ("O", "Y"),              # 해제(취소)된 거래
        "cancel_day": _first(row, "cdealDay"),
    }
    if area:
        rec["price_per_m2"] = round(amount / area, 2)                      # 만원/㎡
        rec["price_per_pyeong"] = round(amount / (area / PYEONG_PER_M2))   # 만원/평
    else:
        rec["price_per_m2"] = None
        rec["price_per_pyeong"] = None
    return rec


# --------------------------------------------------------------------------
# 수집 오케스트레이션
# --------------------------------------------------------------------------
def month_range(months, end=None):
    """최근 N개월의 YYYYMM 목록(오름차순). end 미지정 시 이번 달까지."""
    end = end or date.today()
    y, m = end.year, end.month
    out = []
    for _ in range(months):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def collect(cfg, months=15, sido=None, cache_dir=CACHE_DIR, refresh_months=3, verbose=True):
    targets = regions(sido)
    ymds = month_range(months)
    refresh_set = set(ymds[-refresh_months:]) if refresh_months > 0 else set()

    records, failures = [], []
    api_calls = cache_hits = 0
    total_jobs = len(targets) * len(ymds)
    done = 0

    for code, _sido, sgg in targets:
        for ymd in ymds:
            done += 1
            cached = None if ymd in refresh_set else load_cache(cache_dir, code, ymd)
            if cached is not None:
                cache_hits += 1
                items = cached["items"]
            else:
                try:
                    items, total = fetch_month_raw(cfg, code, ymd)
                except ApiError as e:
                    failures.append({"lawd_cd": code, "deal_ymd": ymd, "error": str(e)})
                    if verbose:
                        print(f"  ! {code} {ymd} 실패: {e}", file=sys.stderr)
                    time.sleep(cfg["request_interval_sec"])
                    continue
                api_calls += 1
                save_cache(cache_dir, code, ymd, items, total)
                time.sleep(cfg["request_interval_sec"])

            for row in items:
                rec = normalize(row, code)
                if rec:
                    records.append(rec)

        if verbose:
            print(f"  [{done}/{total_jobs}] {region_name(code)} 누적 {len(records):,}건")

    meta = {
        "generated_at": date.today().isoformat(),
        "months": ymds,
        "regions": len(targets),
        "api_calls": api_calls,
        "cache_hits": cache_hits,
        "record_count": len(records),
        "canceled_count": sum(1 for r in records if r["canceled"]),
        "failures": failures,
    }
    return {"meta": meta, "records": records}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def cmd_probe(args):
    cfg = load_config(args.config)
    xml_text = call_api(cfg, args.lawd, args.ymd, page_no=1)
    print("=" * 70)
    print(f"RAW XML (앞 1500자) — LAWD_CD={args.lawd} DEAL_YMD={args.ymd}")
    print("=" * 70)
    print(_mask_key(xml_text[:1500], cfg))

    items, total = parse_response(xml_text)
    print("\n" + "=" * 70)
    print(f"파싱 결과: totalCount={total}, 이번 페이지 {len(items)}건")
    print("=" * 70)
    if items:
        print("필드명 목록:", ", ".join(sorted(items[0].keys())))
        print("\n원본 1건:")
        print(json.dumps(items[0], ensure_ascii=False, indent=2))
        print("\n정규화 1건:")
        print(json.dumps(normalize(items[0], args.lawd), ensure_ascii=False, indent=2))
    else:
        print("거래 0건 (해당 지역·월에 신고된 매매가 없거나 파라미터 확인 필요)")


def cmd_fetch(args):
    cfg = load_config(args.config)
    print(f"수집 시작: {args.months}개월 × {len(regions(args.sido))}개 시군구 "
          f"(최근 {args.refresh_months}개월은 캐시 무시하고 재수집)")
    result = collect(
        cfg,
        months=args.months,
        sido=args.sido,
        cache_dir=args.cache_dir,
        refresh_months=args.refresh_months,
    )
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    m = result["meta"]
    print(f"\n완료 -> {args.out}")
    print(f"  거래 {m['record_count']:,}건 (해제거래 {m['canceled_count']:,}건 포함)")
    print(f"  API 호출 {m['api_calls']}회 / 캐시 히트 {m['cache_hits']}회 / 실패 {len(m['failures'])}건")


def main():
    ap = argparse.ArgumentParser(description="국토부 아파트 매매 실거래가 수집기")
    ap.add_argument("--config", default=CONFIG_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="단일 시군구·월 호출해 원본 XML과 필드명 확인")
    p.add_argument("--lawd", default="11680", help="시군구 법정동코드 5자리 (기본: 강남구)")
    p.add_argument("--ymd", default=month_range(2)[0], help="계약연월 YYYYMM (기본: 지난달)")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("fetch", help="범위 전체 수집")
    p.add_argument("--months", type=int, default=15,
                   help="최근 N개월 (기본 15)")
    p.add_argument("--sido", default=None, help="시도명으로 한정 (예: 서울특별시)")
    p.add_argument("--out", default="live/trades.json",
                   help="정규화 결과(파생물). 캐시에서 언제든 재생성되므로 커밋하지 않는다")
    p.add_argument("--cache-dir", default=CACHE_DIR)
    p.add_argument("--refresh-months", type=int, default=3,
                   help="최근 N개월은 캐시를 무시하고 재수집 (신고지연·해제 반영, 기본 3)")
    p.set_defaults(func=cmd_fetch)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
