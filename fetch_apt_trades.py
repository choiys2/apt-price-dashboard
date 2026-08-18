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
from urllib.request import Request, urlopen

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
    # GitHub Secret 이나 설정 파일에 붙여넣을 때 줄바꿈·공백이 딸려오는 일이 잦다.
    # 그대로 두면 URL 에 %0A 로 실려 나가 인증이 조용히 실패한다.
    if cfg.get("service_key"):
        cfg["service_key"] = cfg["service_key"].strip()
    cfg.setdefault("base_url", "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade")
    cfg.setdefault("operation", "getRTMSDataSvcAptTrade")
    cfg.setdefault("num_of_rows", 1000)
    cfg.setdefault("request_interval_sec", 0.12)
    # data.go.kr 은 응답이 느릴 때가 있다. 20초로는 부족해 첫 실측이 전부 타임아웃했다.
    cfg.setdefault("timeout_sec", 60)
    cfg.setdefault("retries", 3)
    # 대량 수집은 진단과 정책이 달라야 한다. 연결이 되는 러너에서는 0.4~1.0초에
    # 응답이 오므로 15초면 충분하고, 막힌 러너에서는 어차피 몇 번을 더 기다려도
    # 안 온다. 60초 x 4회(=실패 1건당 4분)로 두면 실패율 10%에 8시간이 넘는다.
    cfg.setdefault("bulk_timeout_sec", 15)
    cfg.setdefault("bulk_retries", 1)
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


def build_url(cfg, lawd_cd, deal_ymd, page_no=1, base_url=None, num_of_rows=None):
    params = {
        "serviceKey": cfg["service_key"],
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "pageNo": page_no,
        "numOfRows": num_of_rows or cfg["num_of_rows"],
    }
    base = base_url or cfg["base_url"]
    return f"{base}/{cfg['operation']}?{urlencode(params)}"


# 파이썬 기본 UA(Python-urllib/3.x)를 걸러내는 게이트웨이가 있을 수 있어 브라우저 UA를 쓴다.
# 다만 UA 필터는 보통 403을 즉시 돌려주지 무응답 타임아웃을 내지 않으므로, 이것만으로
# 러너 타임아웃이 풀릴 가능성은 높지 않다. 비용이 싸서 먼저 배제해 두는 것이다.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "close",
}


def request_once(url, timeout, headers=None):
    """단발 호출. (응답본문, 소요초) 반환. 재시도하지 않는다(진단용)."""
    started = time.monotonic()
    req = Request(url, headers=headers if headers is not None else BROWSER_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return body, time.monotonic() - started


def call_api(cfg, lawd_cd, deal_ymd, page_no=1, base_url=None, num_of_rows=None,
             timeout=None, retries=None):
    url = build_url(cfg, lawd_cd, deal_ymd, page_no, base_url, num_of_rows)
    timeout = timeout or cfg["timeout_sec"]
    retries = cfg["retries"] if retries is None else retries
    last_err = None
    for attempt in range(retries + 1):
        try:
            body, _ = request_once(url, timeout)
            return body
        except (URLError, HTTPError, OSError) as e:
            # 403은 인증키가 이 서비스에 등록되지 않았다는 뜻이라 재시도로 풀리지 않는다.
            # 일반 실패로 처리하면 월마다 조용히 건너뛰다 0건으로 끝나 원인이 안 드러난다
            # (실측: 전월세 서비스가 전부 403인데 "수집 0건"으로만 보였다).
            if getattr(e, "code", None) == 403:
                raise ApiError(
                    f"HTTP 403 - 인증키가 이 서비스에 등록되지 않았다. "
                    f"data.go.kr 에서 해당 API 활용신청이 승인됐는지 확인할 것. "
                    f"(endpoint={base_url or cfg['base_url']})") from e
            last_err = e
            # 429(요청 과다)는 짧은 재시도로 안 풀리는 경우가 많아 더 오래 쉰다.
            time.sleep(5 if getattr(e, "code", None) == 429 else 1.5 * (attempt + 1))
    raise ApiError(f"네트워크 오류: {type(last_err).__name__}: {last_err} "
                   f"(LAWD_CD={lawd_cd}, DEAL_YMD={deal_ymd}, "
                   f"timeout={timeout}s x {retries + 1}회)")


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
    bulk = {"timeout": cfg["bulk_timeout_sec"], "retries": cfg["bulk_retries"]}
    items, total = parse_response(call_api(cfg, lawd_cd, deal_ymd, page_no=1, **bulk))
    page = 1
    while len(items) < total:
        page += 1
        time.sleep(cfg["request_interval_sec"])
        more, _ = parse_response(call_api(cfg, lawd_cd, deal_ymd, page_no=page, **bulk))
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


def _rgst_date(text):
    """등기일자 'YY.MM.DD' -> 'YYYY-MM-DD'. 비었거나 형식이 다르면 None.

    실측으로 값이 있는 건은 전부 8자 'YY.MM.DD' 였다. 그래도 형식을 확인하고
    쓰는 이유는, 이 값이 비면 "아직 등기 안 됨"이라는 뜻으로 읽히기 때문이다.
    파싱에 실패한 것을 미등기로 세면 확정도를 실제보다 낮게 보고하게 된다.
    """
    t = (text or "").strip()
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{2})", t)
    if not m:
        return None
    yy, mm, dd = (int(x) for x in m.groups())
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    return f"{2000 + yy:04d}-{mm:02d}-{dd:02d}"


def _agent_is_outside(agent, region):
    """중개사 소재지가 매물 소재지와 다른가(원정 매수 대리 지표).

    양쪽 다 접두로 비교한다. 신설 구는 중개사 소재지가 아직 옛 시 이름으로 찍혀
    ("경기 화성시 만세구" 매물에 중개사는 그냥 "경기 화성시") 한쪽만 보면
    같은 동네인데도 외지로 잡힌다. 실측으로 이 차이가 8.0% 대 6.6% 였다.

    소재지가 비어 있으면(4.9%) 판단하지 않고 None 을 준다 - 모르는 것을
    "같은 동네"로 세면 외지 비중이 실제보다 낮아진다.
    """
    a = (agent or "").strip()
    if not a or not region:
        return None
    # region 은 "서울특별시 강남구" 꼴, agent 는 "서울 강남구" 꼴이다.
    sido, _, sgg = region.partition(" ")
    short = ("서울" if "서울" in sido else "인천" if "인천" in sido else
             "경기" if "경기" in sido else sido)
    home = f"{short} {sgg}".strip()
    return not (a.startswith(home) or home.startswith(a))


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
        "deal_day": day,                              # 주간 시계열용
        "agent_sgg": _first(row, "estateAgentSggNm"), # 중개사 소재지 시군구
        "rgst_date": _rgst_date(_first(row, "rgstDate")),
    }
    rec["is_outside_agent"] = _agent_is_outside(rec["agent_sgg"], rec["region"])
    # 계약 -> 등기까지 걸린 날. 등기가 아직 없으면 None 이고, 그 자체가 신호다
    # (실측 중위 69일이라 최근 두세 달은 대부분 미등기다).
    if rec["rgst_date"]:
        rec["days_to_rgst"] = (date(*map(int, rec["rgst_date"].split("-")))
                               - date(year, month, day)).days
    else:
        rec["days_to_rgst"] = None
    if area:
        rec["price_per_m2"] = round(amount / area, 2)                      # 만원/㎡
        rec["price_per_pyeong"] = round(amount / (area / PYEONG_PER_M2))   # 만원/평
        # 전용면적은 단지마다 소수점이 제각각이라(실측: 고유값 15,951개, 84㎡대만
        # 2,137개) 그대로 두면 같은 단지 같은 평형도 별개로 잡혀 타입별 비교가 안 된다.
        # 내림해서 84.97/84.93/84.89 를 모두 "84㎡형" 하나로 묶는다. 83.x 와 84.x 는
        # 실제로 다른 타입이므로 반올림이 아니라 내림이어야 한다.
        rec["area_type"] = int(area)
    else:
        rec["price_per_m2"] = None
        rec["price_per_pyeong"] = None
        rec["area_type"] = None
    # 직거래는 시세보다 크게 낮게 신고되는 경우가 많아(실측: 중개 대비 -28.5%)
    # 가격 통계에서 분리할 수 있도록 표준화된 값으로 둔다.
    rec["is_broker"] = rec["deal_gbn"] != "직거래"
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


# 연속 실패가 이만큼 쌓이면 러너가 통째로 막힌 것으로 보고 중단한다. data.go.kr 은
# 러너에 따라 아예 연결이 안 되는 경우가 있는데, 그때는 남은 수천 건을 계속 시도해도
# 전부 타임아웃만 태울 뿐이다. 받아둔 캐시는 그대로 남으므로 다음 실행이 이어받는다.
MAX_CONSECUTIVE_FAILURES = 8


def collect(cfg, months=15, sido=None, cache_dir=CACHE_DIR, refresh_months=3, verbose=True,
            max_consecutive_failures=MAX_CONSECUTIVE_FAILURES):
    targets = regions(sido)
    ymds = month_range(months)
    refresh_set = set(ymds[-refresh_months:]) if refresh_months > 0 else set()

    records, failures = [], []
    api_calls = cache_hits = 0
    total_jobs = len(targets) * len(ymds)
    done = 0
    consecutive_failures = 0
    aborted = False

    for code, _sido, sgg in targets:
        if aborted:
            break
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
                    consecutive_failures += 1
                    if verbose:
                        print(f"  ! {code} {ymd} 실패({consecutive_failures}연속): {e}",
                              file=sys.stderr)
                    if consecutive_failures >= max_consecutive_failures:
                        print(f"\n[중단] {consecutive_failures}회 연속 실패. 이 러너에서 "
                              f"data.go.kr 에 닿지 않는 것으로 보고 수집을 멈춘다. "
                              f"여기까지 받은 캐시는 저장돼 다음 실행이 이어받는다.",
                              file=sys.stderr)
                        aborted = True
                        break
                    time.sleep(cfg["request_interval_sec"])
                    continue
                consecutive_failures = 0
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
        "aborted_early": aborted,
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
    """진단 모드.

    첫 실측에서 요청이 전부 타임아웃해 원인이 무엇인지(호스트 도달 불가 / 특정 스킴만
    막힘 / 응답이 느릴 뿐 / 파라미터 오류) 구분되지 않았다. 변형을 순서대로 시도하면서
    각각의 소요 시간과 결과를 남겨, 어디까지 되는지 로그만 보고 판단할 수 있게 한다.
    """
    cfg = load_config(args.config)
    print(f"엔드포인트: {cfg['base_url']}/{cfg['operation']}")
    print(f"인증키: 길이 {len(cfg['service_key'])}자, "
          f"앞 4자 {cfg['service_key'][:4]}… (값은 출력하지 않는다)")
    print(f"타임아웃 {args.timeout}초, 변형별 1회씩만 시도\n")

    https_base = cfg["base_url"]
    http_base = https_base.replace("https://", "http://", 1)
    urllib_ua = {"User-Agent": "Python-urllib/3.12"}
    variants = [
        ("① HTTPS, 브라우저 UA, numOfRows=10", https_base, 10, BROWSER_HEADERS),
        ("② HTTPS, 브라우저 UA, numOfRows=1000", https_base, 1000, BROWSER_HEADERS),
        ("③ HTTPS, 기본 UA(Python-urllib)", https_base, 10, urllib_ua),
        ("④ HTTP(평문), 브라우저 UA", http_base, 10, BROWSER_HEADERS),
    ]

    xml_text = None
    for label, base, rows, headers in variants:
        url = build_url(cfg, args.lawd, args.ymd, 1, base_url=base, num_of_rows=rows)
        try:
            body, elapsed = request_once(url, args.timeout, headers=headers)
            print(f"{label}: 성공 ({elapsed:.1f}초, {len(body):,}바이트)")
            if xml_text is None:
                xml_text = body
        except Exception as e:                      # noqa: BLE001 - 진단이라 전부 잡는다
            print(f"{label}: 실패 — {type(e).__name__}: {e}")

    if xml_text is None:
        print("\n" + "=" * 70)
        print("모든 변형이 실패했다. 응답 자체가 오지 않았으므로 필드명은 확인할 수 없다.")
        print("활용신청이 승인 상태이고 국내 브라우저에서는 정상 호출되는 것이 확인됐으므로,")
        print("남은 원인은 이 러너에서 data.go.kr 로 나가는 경로가 막혀 있다는 것이다.")
        print("위의 '네트워크 도달 확인' 스텝에서 TCP 접속(time_connect)이 0이면 IP 차단,")
        print("접속은 되는데 응답만 없으면 게이트웨이가 요청을 삼키는 것이다.")
        print("어느 쪽이든 수집을 국내 IP에서 돌리는 구조로 바꿔야 한다.")
        print("=" * 70)
        raise SystemExit(1)

    print("\n" + "=" * 70)
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


def cmd_discover(args):
    """코드 범위를 훑어 실제로 거래가 잡히는 시군구 코드를 찾는다.

    행정구역 개편으로 lawd_codes.py 의 코드가 현행과 어긋나면 API 가 오류 없이
    totalCount=0 을 돌려줘 그 지역이 조용히 통째로 빠진다. 실제로 수도권 백필에서
    인천 중구·동구·서구·옹진군, 경기 부천시·화성시가 0건으로 나왔다.

    코드를 추측하지 않고 범위를 실제로 호출해 확인한다. 응답의 estateAgentSggNm 에
    "인천 서구" 같은 사람이 읽는 지역명이 들어 있어 코드-이름 대응까지 함께 얻는다.
    """
    cfg = load_config(args.config)
    known = {code for code, _, _ in REGIONS}
    # 막힌 러너에서는 코드마다 타임아웃을 꽉 채우므로 짧게 잡는다. 연결되는 러너는
    # 0.4~1.0초에 응답하므로 5초면 충분하고, 141개 코드 스캔이 70분에서 12분이 된다.
    bulk = {"timeout": args.timeout, "retries": 0}
    found, checked, failed = [], 0, 0

    for code in range(args.start, args.end + 1, args.step):
        code = f"{code:05d}"
        checked += 1
        try:
            items, total = parse_response(
                call_api(cfg, code, args.ymd, num_of_rows=1, **bulk))
        except ApiError:
            failed += 1
            continue
        if total <= 0:
            continue
        name = items[0].get("estateAgentSggNm", "") if items else ""
        umd = items[0].get("umdNm", "") if items else ""
        mark = "" if code in known else "  <-- 테이블에 없는 코드"
        print(f"  {code}  거래 {total:>5,}건  {name:<12} (예: {umd}){mark}")
        found.append((code, name, total, code in known))
        time.sleep(cfg["request_interval_sec"])

    print(f"\n{checked}개 코드 확인 / 거래 있는 코드 {len(found)}개 / 호출 실패 {failed}개")
    new_codes = [f for f in found if not f[3]]
    if new_codes:
        print("\nlawd_codes.py 에 없는 코드:")
        for code, name, total, _ in new_codes:
            print(f'    ("{code}", "?", "{name}"),   # {total:,}건')
    else:
        print("\n테이블에 없는 코드는 발견되지 않았다.")


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

    p = sub.add_parser("probe", help="HTTPS/HTTP·페이지크기 변형을 시도해 응답과 필드명 확인")
    p.add_argument("--lawd", default="11680", help="시군구 법정동코드 5자리 (기본: 강남구)")
    p.add_argument("--ymd", default=month_range(2)[0], help="계약연월 YYYYMM (기본: 지난달)")
    p.add_argument("--timeout", type=int, default=60, help="변형별 타임아웃 초 (기본 60)")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("discover", help="코드 범위를 훑어 실제 거래가 잡히는 시군구 코드를 찾는다")
    p.add_argument("--start", type=int, required=True, help="시작 코드 (예: 28100)")
    p.add_argument("--end", type=int, required=True, help="끝 코드 (예: 28800)")
    p.add_argument("--step", type=int, default=5, help="증분 (기본 5)")
    p.add_argument("--ymd", default=month_range(4)[0], help="확인에 쓸 계약연월 YYYYMM")
    p.add_argument("--timeout", type=int, default=5, help="코드당 타임아웃 초 (기본 5)")
    p.set_defaults(func=cmd_discover)

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
