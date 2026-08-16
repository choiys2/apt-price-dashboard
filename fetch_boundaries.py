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

# 실측(2013 KOSTAT): 코드 체계가 법정동코드와 다르다. 서울 11, 인천 23, 경기 31 이고
# 시군구 이름은 경기도가 공백 없이 붙어 있다("수원시장안구"). 인천 미추홀구는 개칭 전
# 이름인 "남구"로 실려 있다.
KOSTAT_SIDO = {"서울특별시": "11", "인천광역시": "23", "경기도": "31"}

# 우리 이름 -> 2013 원본 이름. 개칭·신설로 어긋나는 것만 적는다.
NAME_ALIAS = {"미추홀구": "남구"}

# 2013 이후 신설돼 원본에 경계가 없는 구. 지도 셀은 2013 행정구역 단위로 두고
# 우리 데이터를 그 셀로 합산한다. 없는 경계를 지어내지 않으면서 지도를 채우는 방법이다.
#   제물포구·영종구  <- 옛 중구 + 동구
#   서해구·검단구    <- 옛 서구
#   화성 4개 구      <- 화성시
MERGED_CELLS = {
    "인천_옛중구동구": {"members": ["28125", "28155"], "old_names": ["중구", "동구"],
                        "label": "제물포·영종구 (옛 중구+동구)"},
    "인천_옛서구": {"members": ["28275", "28290"], "old_names": ["서구"],
                    "label": "서해·검단구 (옛 서구)"},
    "화성_전체": {"members": ["41591", "41593", "41595", "41597"], "old_names": ["화성시"],
                  "label": "화성시 4개 구"},
}


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
    """2013 행정구역 셀 -> 외곽 링, 그리고 우리 시군구 -> 셀 대응표를 만든다.

    신설 구는 경계가 없으므로 옛 모구 셀에 합산한다. 지도는 2013 단위로 그려지고
    데이터는 우리 83개에서 그 단위로 모인다. 없는 경계를 지어내지 않는다.
    """
    by_key = {}
    for f in geo.get("features", []):
        props = f.get("properties", {})
        code, name = feature_code(props), feature_name(props)
        if code[:2] in ("11", "23", "31") and name:
            by_key.setdefault((code[:2], name.replace(" ", "")), []).append(f)

    def rings_for(feats):
        rings = []
        for f in feats:
            for ring in rings_of(f.get("geometry")):
                pts = [(round(x, 4), round(y, 4)) for x, y in ring]
                s = simplify(pts, tol)
                if len(s) >= min_area_points:
                    rings.append(s)
        return rings

    merged_member = {m: cell for cell, spec in MERGED_CELLS.items()
                     for m in spec["members"]}
    cells, cell_of, labels, missing = {}, {}, {}, []

    # 1) 병합 셀부터 만든다.
    for cell, spec in MERGED_CELLS.items():
        prefix = KOSTAT_SIDO["인천광역시" if cell.startswith("인천") else "경기도"]
        feats = [f for n in spec["old_names"] for f in by_key.get((prefix, n), [])]
        rings = rings_for(feats)
        if rings:
            cells[cell] = rings
            labels[cell] = spec["label"]
            for m in spec["members"]:
                cell_of[m] = cell
        else:
            missing.append(f"{spec['label']} (원본 {'/'.join(spec['old_names'])} 없음)")

    # 2) 나머지는 이름으로 1:1 대응.
    for lawd, sido, sgg in REGIONS:
        if lawd in merged_member:
            continue
        short = sgg.replace(" ", "")
        key = (KOSTAT_SIDO[sido], NAME_ALIAS.get(short, short))
        feats = by_key.get(key)
        if not feats:
            missing.append(f"{sido} {sgg}({lawd})")
            continue
        rings = rings_for(feats)
        if not rings:
            missing.append(f"{sido} {sgg}({lawd}) - 링 없음")
            continue
        cells[lawd] = rings
        cell_of[lawd] = lawd
        labels[lawd] = f"{sido} {sgg}"
    return cells, cell_of, labels, missing


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
        # KOSTAT 코드는 법정동코드와 체계가 다르다(서귀포시가 39020, 법정동은 50130).
        # 매핑을 추측하지 않도록 수도권으로 보이는 피처를 코드-이름 그대로 전부 출력한다.
        print("\n  수도권 후보 피처 (코드 오름차순):")
        cand = []
        for f in feats:
            pr = f.get("properties", {})
            c, n = feature_code(pr), feature_name(pr)
            if c[:2] in ("11", "23", "28", "31", "41"):
                cand.append((c, n))
        for c, n in sorted(cand):
            print(f"    {c}  {n}")
        print(f"  총 {len(cand)}개")
        return

    cells, cell_of, labels, missing = build(geo, args.tol)
    total_pts = sum(len(r) for rs in cells.values() for r in rs)
    payload = {
        "source": url,
        "license": "KOSTAT (southkorea/southkorea-maps) - free to share or remix",
        "vintage": "2013",
        "note": ("2013년 행정구역 경계다. 그 뒤 신설된 인천 제물포·영종·서해·검단구와 "
                 "화성 4개 구는 옛 모구 영역에 합산해 표시한다."),
        "tolerance": args.tol,
        "cells": {k: [[list(p) for p in ring] for ring in v] for k, v in cells.items()},
        "cell_of": cell_of,       # 우리 시군구 코드 -> 지도 셀
        "labels": labels,         # 셀 -> 화면 표시 이름
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n완료 -> {args.out} ({os.path.getsize(args.out)/1024:.0f}KB)")
    print(f"  지도 셀 {len(cells)}개 · 시군구 {len(cell_of)}/{len(REGIONS)}개 매핑 "
          f"· 좌표 {total_pts:,}개")
    if missing:
        print(f"  ! 경계를 못 찾은 {len(missing)}개: " + ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
