#!/usr/bin/env python3
"""
수도권 시군구 경계 데이터 준비 (예산 지도용)

실거래가 API 에는 좌표가 없어서 경계는 외부에서 가져와야 한다.
출처: southkorea/southkorea-maps 의 KOSTAT 데이터 ("Free to share or remix").
같은 저장소의 GADM 계열은 재배포 금지라 쓰지 않는다.

알려진 한계 — 화면에도 명시한다:
  KOSTAT 경계는 2013년 기준이라 그 뒤 신설된 구가 없다. 인천 제물포/영종/서해/검단구
  (2026-07), 화성 만세/효행/병점/동탄구(2026-02)가 해당된다. 이들은 옛 모구 영역
  (중구+동구, 서구, 화성시)에 합산해 칠한다. 예산 지도의 목적이 "어느 벨트인가"를
  보는 것이라 이 해상도로도 쓸모가 있지만, 그 구들의 개별 경계는 표현되지 않는다.

좌표 단순화는 Douglas-Peucker 를 직접 구현했다. 외부 의존성 없이 표준 라이브러리만
쓰는 이 저장소의 원칙을 지키기 위해서다.

사용법:
  python fetch_boundaries.py --out data/boundaries.json
  python fetch_boundaries.py --inspect        # 원본 속성 이름만 확인
"""
import argparse
import json
import os
import sys
from urllib.request import Request, urlopen

from lawd_codes import REGIONS

# 단순화 버전을 먼저 시도한다. 원본은 수 MB 라 웹 페이지에 싣기 어렵다.
SOURCES = [
    "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/"
    "kostat/2013/json/skorea_municipalities_geo_simple.json",
    "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/"
    "kostat/2013/json/skorea-municipalities-2013-geo.json",
    "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/"
    "kostat/2013/json/municipalities-geo-simple.json",
]

# 2013 경계에 없는 신설 구 -> 그릴 때 쓸 옛 영역. 이름으로 맞춘다.
# (2013 파일은 코드 체계가 우리와 다를 수 있어 이름 매칭을 함께 쓴다)
NEW_TO_OLD = {
    "28125": ["중구"], "28155": ["중구"],            # 제물포·영종 <- 옛 인천 중구
    "28275": ["서구"], "28290": ["서구"],            # 서해·검단 <- 옛 인천 서구
    "41591": ["화성시"], "41593": ["화성시"],
    "41595": ["화성시"], "41597": ["화성시"],
    "41192": ["부천시"], "41194": ["부천시"], "41196": ["부천시"],
}

SIDO_PREFIX = {"11": "서울특별시", "28": "인천광역시", "41": "경기도"}


def download(url, timeout=30):
    req = Request(url, headers={"User-Agent": "apt-price-dashboard/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def load_source(urls=SOURCES):
    """후보 URL 을 순서대로 시도한다. 저장소 파일명이 바뀌어도 버티게 한다."""
    last = None
    for url in urls:
        try:
            print(f"  시도: {url.rsplit('/', 1)[-1]}")
            return json.loads(download(url)), url
        except Exception as e:                      # noqa: BLE001 - 다음 후보로 넘어간다
            last = f"{type(e).__name__}: {e}"
            print(f"    실패 — {last}")
    raise SystemExit(f"경계 데이터를 받지 못했다. 마지막 오류: {last}")


def _perp_distance(pt, a, b):
    (x, y), (x1, y1), (x2, y2) = pt, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def simplify(points, tol):
    """Douglas-Peucker. 외부 의존성 없이 좌표 수를 줄인다."""
    if len(points) < 3:
        return points
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _perp_distance(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax <= tol:
        return [points[0], points[-1]]
    return simplify(points[:idx + 1], tol)[:-1] + simplify(points[idx:], tol)


def rings_of(geometry):
    """Polygon / MultiPolygon 에서 외곽 링만 뽑는다(구멍은 예산 지도에 불필요)."""
    g = geometry or {}
    if g.get("type") == "Polygon":
        return [g["coordinates"][0]] if g.get("coordinates") else []
    if g.get("type") == "MultiPolygon":
        return [poly[0] for poly in g.get("coordinates", []) if poly]
    return []


def feature_name(props):
    for k in ("name", "NAME_2", "SIG_KOR_NM", "sigungu", "SGG_NM"):
        v = props.get(k)
        if v:
            return str(v)
    return ""


def feature_code(props):
    for k in ("code", "SIG_CD", "sigungu_cd", "adm_cd"):
        v = props.get(k)
        if v:
            return str(v)
    return ""


def build(geo, tol, min_area_points=8):
    """우리 83개 시군구 -> 외곽 링 목록. 코드로 먼저, 안 되면 이름으로 맞춘다."""
    feats = geo.get("features", [])
    by_code, by_name = {}, {}
    for f in feats:
        props = f.get("properties", {})
        code, name = feature_code(props), feature_name(props)
        if code:
            by_code.setdefault(code[:5], []).append(f)
        if name:
            by_name.setdefault(name, []).append(f)

    out, missing = {}, []
    for lawd, sido, sgg in REGIONS:
        feats_for = by_code.get(lawd)
        if not feats_for:
            # 신설 구는 옛 모구 영역으로 대체한다.
            for old in NEW_TO_OLD.get(lawd, []):
                feats_for = [f for f in by_name.get(old, [])
                             if feature_code(f.get("properties", {})).startswith(lawd[:2])]
                if feats_for:
                    break
        if not feats_for:
            short = sgg.split()[-1]
            feats_for = [f for f in by_name.get(short, [])
                         if feature_code(f.get("properties", {})).startswith(lawd[:2])]
        if not feats_for:
            missing.append(f"{sido} {sgg}({lawd})")
            continue

        rings = []
        for f in feats_for:
            for ring in rings_of(f.get("geometry")):
                pts = [(round(x, 4), round(y, 4)) for x, y in ring]
                s = simplify(pts, tol)
                if len(s) >= min_area_points:
                    rings.append(s)
        if rings:
            out[lawd] = rings
        else:
            missing.append(f"{sido} {sgg}({lawd}) - 링 없음")
    return out, missing


def main():
    ap = argparse.ArgumentParser(description="수도권 시군구 경계 준비")
    ap.add_argument("--out", default="data/boundaries.json")
    ap.add_argument("--tol", type=float, default=0.0015,
                    help="단순화 허용오차(도). 클수록 가벼워지고 거칠어진다")
    ap.add_argument("--inspect", action="store_true",
                    help="원본 속성 이름과 샘플만 출력하고 끝낸다")
    args = ap.parse_args()

    sys.setrecursionlimit(20000)    # 해안선 링이 길어 재귀가 깊어진다
    print("경계 데이터 내려받기")
    geo, url = load_source()
    feats = geo.get("features", [])
    print(f"  피처 {len(feats):,}개 — {url.rsplit('/', 1)[-1]}")

    if args.inspect or not feats:
        p = feats[0].get("properties", {}) if feats else {}
        print("  속성 키:", list(p))
        print("  샘플:", json.dumps(p, ensure_ascii=False)[:300])
        return

    shapes, missing = build(geo, args.tol)
    total_pts = sum(len(r) for rs in shapes.values() for r in rs)
    payload = {
        "source": url,
        "license": "KOSTAT (southkorea/southkorea-maps) - free to share or remix",
        "vintage": "2013",
        "note": ("2013년 행정구역 경계다. 그 뒤 신설된 인천 제물포·영종·서해·검단구와 "
                 "화성 4개 구는 옛 모구 영역에 합산해 표시한다."),
        "tolerance": args.tol,
        "shapes": {k: [[list(p) for p in ring] for ring in v] for k, v in shapes.items()},
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n완료 -> {args.out} ({os.path.getsize(args.out)/1024:.0f}KB)")
    print(f"  시군구 {len(shapes)}/{len(REGIONS)}개 · 좌표 {total_pts:,}개")
    if missing:
        print(f"  ! 경계를 못 찾은 {len(missing)}개: " + ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
