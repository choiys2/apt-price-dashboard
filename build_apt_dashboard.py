#!/usr/bin/env python3
"""
집계 결과 -> 단일 HTML 대시보드

외부 CDN을 쓰지 않는다. 차트와 입체 지도는 인라인 SVG를 바닐라 JS로 그리고, 데이터는
HTML 안에 JSON으로 심는다. 파일 하나만 열면 오프라인에서도 그대로 동작한다.

지도가 왜 SVG 로 직접 그린 축측투영인가: 지도 라이브러리를 쓰면 CDN 의존이 생기고
타일 서버까지 붙는다. 이 저장소는 "파일 하나로 끝난다"를 유지하려고 표준 라이브러리와
바닐라 JS 만 쓴다. 기둥을 세우는 정도의 3D 는 직접 투영하는 편이 오히려 가볍다.

사용법:
  python build_apt_dashboard.py live/analytics.json live/index.html [data/boundaries.json]
"""
import json
import os
import sys

PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#0d1524; --panel:#141f36; --panel-2:#1b2942; --line:#26375a;
  --text:#e6edf8; --muted:#8ba0c4; --accent:#4b8ef7; --accent-soft:#1e3a68;
  --up:#f0715f; --down:#4aa3e0;
  --void:#0a1120; --void-2:#101b30;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.28);
}
html[data-theme="light"]{
  --bg:#eef3fa; --panel:#fff; --panel-2:#f4f7fc; --line:#dce5f2;
  --text:#16233a; --muted:#61728d; --accent:#2563eb; --accent-soft:#dbe8fe;
  --up:#d1483a; --down:#1d6fa8;
  --void:#e4ecf7; --void-2:#f2f6fc;
  --shadow:0 1px 2px rgba(20,40,80,.06),0 8px 24px rgba(20,40,80,.08);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",
    "Malgun Gothic",AppleSDGothicNeo-Regular,sans-serif;
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 64px}
h1{font-size:23px;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:16px;margin:0 0 14px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13.5px;margin:0}
header.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
  flex-wrap:wrap;margin-bottom:18px}
button{font:inherit;color:inherit;cursor:pointer;background:none;border:none}
.ghost{border:1px solid var(--line);background:var(--panel);border-radius:8px;
  padding:6px 12px;font-size:13px;transition:border-color .15s,background .15s}
.ghost:hover{border-color:var(--accent)}
.banner{background:#7a2718;border:1px solid #a8402c;color:#ffe3dc;border-radius:10px;
  padding:12px 16px;margin-bottom:20px;font-size:13.5px}
html[data-theme="light"] .banner{background:#fdeae6;border-color:#f0b3a5;color:#8a2c18}
.banner b{font-weight:650}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;box-shadow:var(--shadow)}
section{margin-bottom:20px}
/* --- 탭 --- */
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin-bottom:20px}
.tab{padding:10px 20px;font-size:14.5px;color:var(--muted);margin-bottom:-1px;
  border-bottom:2px solid transparent;transition:color .15s,border-color .15s}
.tab[aria-selected="true"]{color:var(--text);font-weight:650;border-bottom-color:var(--accent)}
.tab:hover{color:var(--text)}
.tab .badge{font-size:11.5px;color:var(--muted);margin-left:6px;font-weight:400}
/* --- 필터 --- */
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:18px}
.chip{border:1px solid var(--line);background:var(--panel);border-radius:999px;
  padding:6px 15px;font-size:13.5px;transition:all .15s}
.chip[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);
  color:var(--text);font-weight:600}
/* --- KPI --- */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}
.kpi .label{color:var(--muted);font-size:12.5px;letter-spacing:.02em}
.kpi .value{font-size:27px;font-weight:640;letter-spacing:-.025em;margin:6px 0 2px;
  font-variant-numeric:tabular-nums}
.kpi .unit{font-size:14px;font-weight:500;color:var(--muted);margin-left:3px}
.kpi .foot{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.up{color:var(--up);font-weight:600}
.down{color:var(--down);font-weight:600}
/* --- 차트 --- */
.chart-head{display:flex;justify-content:space-between;align-items:baseline;
  gap:12px;flex-wrap:wrap}
.legend{display:flex;gap:16px;font-size:12.5px;color:var(--muted);flex-wrap:wrap}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;
  margin-right:5px;vertical-align:-1px}
svg{display:block;width:100%;height:auto;overflow:visible}
.gridline{stroke:var(--line);stroke-width:1}
.axis-text{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.bar{fill:var(--accent);opacity:.42}
.bar.prov{opacity:.18}
.bar:hover{opacity:.75}
.band{fill:var(--up);opacity:.12;stroke:none}
.pline{fill:none;stroke:var(--up);stroke-width:2.2;stroke-linejoin:round}
.pline.prov{stroke-dasharray:5 4}
.pdot{fill:var(--up)}
/* --- 입체 지도 --- */
.mapctl{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:14px;
  font-size:13px;color:var(--muted)}
.mapctl label{display:flex;align-items:center;gap:7px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}
.seg button{padding:6px 13px;font-size:13px;color:var(--muted);
  border-right:1px solid var(--line);transition:background .15s,color .15s}
.seg button:last-child{border-right:none}
.seg button[aria-pressed="true"]{background:var(--accent-soft);color:var(--text);font-weight:600}
.seg button:hover{color:var(--text)}
input[type=range]{accent-color:var(--accent);width:104px;vertical-align:middle}
.stage{position:relative;border-radius:12px;overflow:hidden;touch-action:none;
  cursor:grab;background:
    radial-gradient(120% 90% at 50% 8%, var(--void-2) 0%, var(--void) 62%, var(--bg) 100%);
  border:1px solid var(--line)}
.stage.drag{cursor:grabbing}
.stage svg{width:100%;height:auto;display:block;overflow:visible}
.stage g[data-cell]{transition:none}
.stage g[data-cell]:hover{filter:brightness(1.22)}
.stage g.sel{filter:brightness(1.3) drop-shadow(0 0 7px rgba(120,180,255,.55))}
.plate{fill:none;stroke:var(--line);stroke-width:.7;opacity:.5}
.maplabel{fill:var(--text);font-size:10.5px;font-weight:650;paint-order:stroke;
  stroke:rgba(0,0,0,.55);stroke-width:2.6px;pointer-events:none}
html[data-theme="light"] .maplabel{stroke:rgba(255,255,255,.8)}
.tip{position:absolute;pointer-events:none;left:0;top:0;z-index:3;
  background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:9px 12px;font-size:12.5px;box-shadow:var(--shadow);white-space:nowrap;
  opacity:0;transition:opacity .12s;font-variant-numeric:tabular-nums}
.tip b{font-size:13.5px}
.tip .parts{color:var(--muted);font-size:11.5px;margin-top:3px}
.mapfoot{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin-top:14px;
  font-size:12.5px;color:var(--muted)}
.rampbar{height:11px;border-radius:6px;width:190px;border:1px solid var(--line)}
.month-pill{font-variant-numeric:tabular-nums;background:var(--panel-2);
  border:1px solid var(--line);border-radius:999px;padding:3px 11px;font-size:12.5px}
.mapgrid{display:grid;grid-template-columns:1fr 300px;gap:20px;align-items:start}
@media(max-width:900px){.mapgrid{grid-template-columns:1fr}}
.rankbar{display:grid;grid-template-columns:88px 1fr 76px;gap:9px;align-items:center;
  font-size:12.5px;padding:2px 0;cursor:pointer;border-radius:6px}
.rankbar:hover{background:var(--panel-2)}
.rankbar.sel{background:var(--accent-soft)}
.rankbar .rt{background:var(--panel-2);border-radius:4px;height:13px;overflow:hidden}
.rankbar .rf{height:100%;border-radius:4px}
.rankbar .rv{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.ranklist{max-height:452px;overflow-y:auto;padding-right:4px}
/* --- 테이블 --- */
.table-head{display:flex;justify-content:space-between;align-items:center;
  gap:12px;flex-wrap:wrap;margin-bottom:12px}
input[type=search]{background:var(--panel-2);border:1px solid var(--line);
  color:var(--text);border-radius:8px;padding:7px 12px;font:inherit;font-size:13.5px;
  min-width:190px}
input[type=search]:focus{outline:none;border-color:var(--accent)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
/* 200행짜리 표를 통째로 펼치면 페이지가 8,000px 가 된다. 표 안에서 스크롤시킨다. */
.scroll.tall{max-height:540px;overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px;
  font-variant-numeric:tabular-nums;white-space:nowrap}
th,td{padding:9px 11px;text-align:right;border-bottom:1px solid var(--line)}
th:nth-child(1),td:nth-child(1),th:nth-child(2),td:nth-child(2){text-align:left}
/* 신고가 표는 계약일·지역·단지 세 칸이 텍스트라 좌측 정렬한다 */
table.rh th:nth-child(3),table.rh td:nth-child(3){text-align:left}
th{color:var(--muted);font-weight:600;font-size:12.5px;cursor:pointer;
  user-select:none;position:sticky;top:0;background:var(--panel);z-index:1}
th:hover{color:var(--text)}
th[aria-sort]{color:var(--accent)}
tbody tr:hover{background:var(--panel-2)}
.rh-row{cursor:pointer}
.rh-detail td{background:var(--panel-2);white-space:normal}
.hist{display:flex;flex-wrap:wrap;gap:6px}
.hist-item{background:var(--panel);border:1px solid var(--line);border-radius:6px;
  padding:4px 9px;font-size:12.5px}
.hist-item.cur{border-color:var(--up);color:var(--text)}
td.name{font-weight:560}
.muted{color:var(--muted)}
/* --- 예산 폼 / 분포 막대 --- */
.budget-form{display:flex;gap:18px;flex-wrap:wrap;align-items:center;font-size:13.5px}
.budget-form label{display:flex;align-items:center;gap:7px;color:var(--muted)}
.budget-form input{background:var(--panel-2);border:1px solid var(--line);color:var(--text);
  border-radius:8px;padding:7px 11px;font:inherit;font-size:13.5px;
  font-variant-numeric:tabular-nums}
.budget-form input[type=number]{width:110px;text-align:right}
.budget-form input:focus{outline:none;border-color:var(--accent)}
.dist{display:grid;gap:10px}
.dist-row{display:grid;grid-template-columns:92px 1fr 232px;gap:12px;align-items:center;
  font-size:13.5px}
/* 매도·매수를 한 줄에 같이 적는 칸은 232px 에 안 들어가 잘린다 */
.dist.wide .dist-row{grid-template-columns:88px 1fr 320px}
.track{background:var(--panel-2);border-radius:6px;height:22px;overflow:hidden}
.fill{background:var(--accent);height:100%;opacity:.5;border-radius:6px}
.dist-val{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted);
  white-space:nowrap}
footer{color:var(--muted);font-size:12.5px;margin-top:34px;
  border-top:1px solid var(--line);padding-top:16px}
footer li{margin-bottom:5px}
footer ul{padding-left:18px;margin:8px 0 0}
@media(max-width:640px){
  .wrap{padding:20px 14px 48px}
  .kpi .value{font-size:23px}
  .dist-row,.dist.wide .dist-row{grid-template-columns:74px 1fr;
    grid-template-areas:"a b" "c c"}
  .dist-val{grid-area:c;text-align:left}
  .tab{padding:9px 13px;font-size:13.5px}
}
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <div>
    <h1>__HEADING__</h1>
    <p class="sub" id="sub"></p>
  </div>
  <button class="ghost" id="theme">라이트 모드</button>
</header>

<div id="banner"></div>

<nav class="tabs" id="tabs" role="tablist">
  <button class="tab" role="tab" data-tab="overview" aria-selected="true">개요</button>
  <button class="tab" role="tab" data-tab="map" aria-selected="false">입체 지도<span class="badge">3D</span></button>
</nav>

<div class="filters" id="filters"></div>
<div class="filters" id="dealfilters"></div>

<!-- ===================== 개요 ===================== -->
<div id="pane-overview">

<section class="kpis" id="kpis"></section>

<section class="card">
  <div class="chart-head">
    <h2 id="chart-title">월별 거래량 · 중위 평당가</h2>
    <div class="seg" id="chart-mode">
      <button data-mode="month" aria-pressed="true">월간</button>
      <button data-mode="week" aria-pressed="false">주간</button>
    </div>
  </div>
  <div class="legend" style="margin-bottom:10px">
    <span><i style="background:var(--accent);opacity:.45"></i>거래건수</span>
    <span><i style="background:var(--up)"></i>중위 평당가(만원)</span>
    <span id="lg-band"><i style="background:var(--up);opacity:.25"></i>25~75% 구간</span>
    <span class="muted">옅은 구간 = 신고 지연 잠정치</span>
  </div>
  <div id="chart"></div>
  <p class="sub" id="chart-note" style="margin-top:10px"></p>
</section>

<!-- 확정도: 앞의 차트에서 "잠정"이라고만 하던 것을 측정값으로 바꾼다 -->
<section class="card" id="settle-card" style="display:none">
  <h2>거래 확정도 (등기완료율)</h2>
  <p class="sub" id="settle-note" style="margin:0 0 14px"></p>
  <div class="dist" id="settle"></div>
  <p class="sub" id="settle-warn" style="margin-top:12px"></p>
</section>

<section class="card">
  <div class="table-head">
    <h2 style="margin:0">시군구 랭킹</h2>
    <div style="display:flex;gap:8px;align-items:center">
      <input type="search" id="q" placeholder="지역 검색">
      <button class="ghost" id="csv">CSV 저장</button>
    </div>
  </div>
  <div class="scroll"><table id="tbl">
    <thead><tr id="thr"></tr></thead>
    <tbody id="tb"></tbody>
  </table></div>
  <p class="sub" id="tblfoot" style="margin-top:10px"></p>
</section>

<section class="card">
  <div class="table-head">
    <h2 style="margin:0">신고가 · 신저가 갱신</h2>
    <div class="filters" style="margin:0" id="rhtabs"></div>
  </div>
  <p class="sub" id="rhnote" style="margin:0 0 12px"></p>
  <div class="scroll"><table class="rh">
    <thead><tr>
      <th style="cursor:default">계약일</th><th style="cursor:default">지역</th>
      <th style="cursor:default">단지</th><th style="cursor:default">전용</th>
      <th style="cursor:default">층</th><th style="cursor:default">거래가</th>
      <th style="cursor:default">직전 기록</th><th style="cursor:default">갱신폭</th>
    </tr></thead>
    <tbody id="rhbody"></tbody>
  </table></div>
</section>

<section class="card">
  <h2>전용면적 구간별 거래 비중 · 중위 평당가</h2>
  <div class="dist" id="dist"></div>
</section>

<section class="card" id="floor-card" style="display:none">
  <h2>층별 프리미엄</h2>
  <p class="sub" id="floor-note" style="margin:0 0 12px"></p>
  <div class="dist" id="floorprem"></div>
</section>

<section class="card" id="jeonse-card" style="display:none">
  <h2>전세가율 (전세보증금 / 매매가)</h2>
  <p class="sub" id="jeonse-note" style="margin:0 0 12px"></p>
  <div class="dist" id="jeonse"></div>
</section>

<section class="card">
  <h2>거래 형태</h2>
  <div class="dist" id="dealtype"></div>
  <p class="sub" style="margin-top:12px">직거래는 가족 간 증여성 거래 등이 섞여 시세보다
    낮게 신고되는 경우가 많다. 위 필터의 "중개거래만"으로 제외하고 볼 수 있다.</p>
</section>

<section class="card" id="party-card" style="display:none">
  <h2>매도자 · 매수자 구성</h2>
  <p class="sub" id="party-note" style="margin:0 0 14px"></p>
  <div class="dist wide" id="party"></div>
  <div id="party-chart" style="margin-top:16px"></div>
  <p class="sub" id="party-foot" style="margin-top:10px"></p>
</section>

<section class="card" id="anom-card" style="display:none">
  <div class="table-head">
    <h2 style="margin:0">확인이 필요한 거래</h2>
    <div class="filters" style="margin:0" id="anom-tabs"></div>
  </div>
  <p class="sub" id="anom-note" style="margin:0 0 12px"></p>
  <div class="scroll tall"><table class="rh">
    <thead><tr>
      <th style="cursor:default">계약일</th><th style="cursor:default">지역</th>
      <th style="cursor:default">단지</th><th style="cursor:default">전용</th>
      <th style="cursor:default">거래가</th><th style="cursor:default">단지 시세</th>
      <th style="cursor:default">괴리</th><th style="cursor:default">신호</th>
    </tr></thead>
    <tbody id="anom-body"></tbody>
  </table></div>
  <p class="sub" id="anom-warn" style="margin-top:12px"></p>
</section>

<!-- 예산으로 찾기는 개요의 마지막 칸이다. 앞의 지표들을 다 본 뒤
     "그래서 내 돈으로는 어디?"로 넘어가는 순서가 자연스럽다. -->
<section class="card" id="budget-card" style="display:none">
  <h2>예산으로 찾기</h2>
  <p class="sub" style="margin:0 0 14px">지역이 아니라 <b>예산</b>에서 출발한다.
    같은 돈으로 어디에서 몇 평을 살 수 있는지 비교한다.
    <span id="b-tomap-wrap">같은 조건을 지도로 보려면
    <a href="#" id="b-tomap" style="color:var(--accent)">입체 지도 탭</a>으로 간다.</span></p>
  <div class="budget-form">
    <label>예산 <input type="number" id="b-budget" step="5000" min="1000"> 만원
      <span class="muted" id="b-budget-eok"></span></label>
    <label>전용 <input type="number" id="b-area" step="1" min="10"> ㎡ 이상</label>
    <label>지역 <input type="search" id="b-region" placeholder="전체 (예: 성남)"></label>
  </div>
  <p class="sub" id="b-summary" style="margin:12px 0"></p>
  <div class="scroll"><table class="rh">
    <thead><tr>
      <th style="cursor:default">지역</th><th style="cursor:default">단지</th>
      <th style="cursor:default">전용</th><th style="cursor:default">준공</th>
      <th style="cursor:default">시세(중위)</th><th style="cursor:default">거래범위</th>
      <th style="cursor:default">평당가</th><th style="cursor:default">거래</th>
    </tr></thead>
    <tbody id="b-body"></tbody>
  </table></div>
  <p class="sub" id="b-note" style="margin-top:10px"></p>
</section>

</div><!-- /pane-overview -->

<!-- ===================== 입체 지도 ===================== -->
<div id="pane-map" hidden>

<section class="card" id="map-card">
  <div class="table-head" style="margin-bottom:10px">
    <h2 style="margin:0">수도권 입체 지도</h2>
    <div class="seg" id="map-metric"></div>
  </div>

  <div class="mapctl">
    <label>회전 <input type="range" id="m-rot" min="-180" max="180" step="1"></label>
    <label>기울기 <input type="range" id="m-tilt" min="14" max="80" step="1"></label>
    <label>높이 <input type="range" id="m-exag" min="30" max="260" step="5"></label>
    <label id="m-labelwrap"><input type="checkbox" id="m-labels"> 지역명</label>
    <button class="ghost" id="m-reset">시점 초기화</button>
  </div>

  <div class="mapctl" id="m-budgetctl" style="display:none">
    <label>예산 <input type="number" id="mb-budget" step="5000" min="1000"
      style="width:104px;text-align:right;background:var(--panel-2);border:1px solid var(--line);
      color:var(--text);border-radius:8px;padding:6px 10px;font:inherit;font-size:13px"> 만원</label>
    <label>전용 <input type="number" id="mb-area" step="1" min="10"
      style="width:78px;text-align:right;background:var(--panel-2);border:1px solid var(--line);
      color:var(--text);border-radius:8px;padding:6px 10px;font:inherit;font-size:13px"> ㎡ 이상</label>
    <span class="muted" id="mb-note"></span>
  </div>

  <div class="mapctl" id="m-playctl">
    <button class="ghost" id="m-play">▶ 재생</button>
    <input type="range" id="m-month" min="0" max="0" step="1" style="width:230px">
    <span class="month-pill" id="m-monthlabel">전체 기간</span>
    <button class="ghost" id="m-allmonths">전체 기간으로</button>
  </div>

  <div class="mapgrid">
    <div>
      <div class="stage" id="stage">
        <div id="map"></div>
        <div class="tip" id="maptip"></div>
      </div>
      <div class="mapfoot">
        <span id="m-lo"></span>
        <div class="rampbar" id="m-ramp"></div>
        <span id="m-hi"></span>
        <span class="muted" id="m-hint">끌어서 돌리고, 기둥을 눌러 고정한다</span>
      </div>
    </div>
    <div>
      <div class="sub" style="margin-bottom:8px" id="m-ranktitle"></div>
      <div class="ranklist" id="m-ranklist"></div>
    </div>
  </div>

  <p class="sub" style="margin-top:14px" id="m-caveat"></p>
</section>

<section class="card" id="m-detail-card">
  <div class="table-head" style="margin-bottom:6px">
    <h2 style="margin:0" id="m-dtitle">지역 상세</h2>
    <div class="filters" style="margin:0" id="m-dmembers"></div>
  </div>
  <p class="sub" id="m-dsub" style="margin:0 0 12px"></p>
  <div id="m-dchart"></div>
</section>

</div><!-- /pane-map -->

<footer>
  <div><b>출처</b> 국토교통부 아파트 매매 실거래가 (data.go.kr, RTMSDataSvcAptTrade)</div>
  <ul>
    <li>해제(취소) 거래는 집계에서 제외했다 — <span id="cancel-note"></span></li>
    <li>대표 단가는 <b>중위 평당가</b>다. 평균은 초고가 몇 건에 끌려가 지역 비교를 왜곡한다.</li>
    <li>실거래가는 계약일 기준 신고분이라, 최근 2개월은 신고 지연으로 거래량이 과소 집계된다(잠정치).</li>
    <li><b>최근 달 수치는 나중에 더 내려갈 수 있다.</b> 해제(취소)도 뒤늦게 반영되기 때문이다.
        이번 집계의 월별 해제율은 <span id="cancel-series"></span> 로 과거일수록 높은데,
        시장이 달라진 것이 아니라 오래된 거래일수록 해제가 반영될 시간이 길었던 관측 편향이다.
        <b>따라서 해제율 자체를 시계열로 비교해서는 안 된다.</b></li>
    <li><b>증감률의 기준월은 최신월이 아니라 마지막 확정월</b>(<span id="ref-note"></span>)이다.
        잠정치인 최신월을 확정된 전월·전년동월과 맞대면, 실제로 줄지 않았는데도 거래량이
        급감한 것처럼 보이기 때문이다.</li>
    <li>전용면적이 없는 건은 거래량에는 포함하되 단가 계산에서는 제외했다.</li>
    <li id="yoy-note"></li>
    <li id="geo-note" hidden></li>
  </ul>
  <div style="margin-top:10px" id="gen"></div>
</footer>

</div>
<script id="data" type="application/json">__DATA__</script>
<script id="geo" type="application/json">__GEO__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const GEO = (() => { const el = document.getElementById('geo');
  const t = el ? el.textContent.trim() : ''; return t ? JSON.parse(t) : null; })();
const $ = s => document.querySelector(s);

/* ---------- 표시 형식 ---------- */
const nf = n => n == null ? '–' : n.toLocaleString('ko-KR');
function fmtAmount(manwon){                       // 만원 -> 억 표기
  if (manwon == null) return '–';
  if (manwon >= 10000) return (manwon/10000).toFixed(manwon >= 100000 ? 0 : 1) + '억';
  return nf(manwon) + '만';
}
function pct(v){
  if (v == null) return '<span class="muted">–</span>';
  const cls = v > 0 ? 'up' : (v < 0 ? 'down' : 'muted');
  const sign = v > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${v.toFixed(1)}%</span>`;
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const shortName = s => String(s).replace('특별시','').replace('광역시','').replace('경기도 ','');

/* ---------- 상태 ---------- */
let tab = 'overview';
let sido = 'ALL';
let sortKey = 'median_ppp', sortDir = -1;
let query = '';
let dealType = 'all';          // 'all' | 'broker' (직거래 제외)
let rhTab = 'highs';           // 'highs' | 'lows'
let chartMode = 'month';       // 'month' | 'week'
// 예산 조건은 개요의 "예산으로 찾기"와 지도의 "예산 도달률"이 함께 쓴다.
// 두 화면이 서로 다른 예산을 보고 있으면 같은 질문에 다른 답이 나온다.
const BST = {budget: 80000, area: 84};

// 전체본과 중개거래본은 같은 모양이라 뷰만 갈아끼운다.
function V(){ return (dealType === 'broker' && D.broker) ? D.broker : D; }

function monthlyFor(s){
  const v = V();
  if (s === 'ALL') return v.monthly;
  const e = v.sido.find(x => x.sido === s);
  return e ? e.monthly : [];
}
function overallFor(s){
  const v = V();
  if (s === 'ALL') return {count:v.kpi.total_deals, median_ppp:v.kpi.median_ppp,
                           median_amount:v.kpi.median_amount, avg_area:v.kpi.avg_area};
  const e = v.sido.find(x => x.sido === s);
  return e ? e : {count:0, median_ppp:null, median_amount:null, avg_area:null};
}
function regionsFor(s){
  const all = V().regions;
  const rows = s === 'ALL' ? all : all.filter(r => r.sido === s);
  return query ? rows.filter(r => r.region.includes(query)) : rows;
}
function change(cur, prev){
  if (prev == null || !prev || cur == null) return null;
  return (cur - prev) / prev * 100;
}

/* ---------- 탭 ---------- */
function switchTab(name){
  if (name === 'map' && !GEO) return;
  tab = name;
  $('#tabs').querySelectorAll('.tab').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.tab === name)));
  $('#pane-overview').hidden = name !== 'overview';
  if ($('#pane-map')) $('#pane-map').hidden = name !== 'map';
  // 지도는 숨겨진 동안 그려도 소용없다. 보이는 시점에 그린다.
  if (name === 'map') renderMap();
}

/* ---------- 필터 ---------- */
function renderFilters(){
  const opts = [['ALL','수도권 전체'], ...D.sido.map(s => [s.sido, s.sido])];
  $('#filters').innerHTML = opts.map(([v,label]) =>
    `<button class="chip" data-sido="${esc(v)}" aria-pressed="${v===sido}">${esc(label)}</button>`
  ).join('');
  $('#filters').querySelectorAll('.chip').forEach(b =>
    b.onclick = () => { sido = b.dataset.sido; renderAll(); });

  if (!D.broker){ $('#dealfilters').innerHTML = ''; return; }
  const dt = D.deal_type;
  const dealOpts = [
    ['all', `전체 거래 (${nf(D.kpi.total_deals)}건)`],
    ['broker', `중개거래만 (직거래 ${dt.direct_share_pct}% 제외)`],
  ];
  $('#dealfilters').innerHTML = dealOpts.map(([v,label]) =>
    `<button class="chip" data-deal="${v}" aria-pressed="${v===dealType}">${esc(label)}</button>`
  ).join('');
  $('#dealfilters').querySelectorAll('.chip').forEach(b =>
    b.onclick = () => { dealType = b.dataset.deal; renderAll(); });
}

/* ---------- KPI ---------- */
function renderKpi(){
  const ov = overallFor(sido), ms = monthlyFor(sido);
  const latest = ms[ms.length-1] || {};
  // 비교 기준은 최신월이 아니라 마지막 "확정월"이다. 최신월은 신고 지연으로 거래량이
  // 덜 잡힌 잠정치라, 확정된 전월/전년동월과 맞대면 실제로 줄지 않았는데도 급감으로 보인다.
  const ri = (() => { for (let i = ms.length-1; i >= 0; i--) if (!ms[i].provisional) return i;
                      return ms.length-1; })();
  const ref = ms[ri] || {}, prev = ms[ri-1] || {};
  // 전년 동월 = 기준월보다 12개월 앞. 13개월 이상 수집했을 때만 존재한다.
  // 기준월의 12개월 전까지 있어야 하므로 최소 15개월(=12+잠정 2+1) 수집이 필요하다
  const yoy = ri >= 12 ? ms[ri-12] : null;

  const cards = [
    {label:`거래건수 (${V().kpi.period_from} ~ ${V().kpi.period_to})`,
     value:nf(ov.count), unit:'건',
     foot:`기준월 ${ref.ym||'–'} ${nf(ref.count)}건 · 전월비 ${pct(change(ref.count, prev.count))}`
        + `<br><span class="muted">최신월 ${latest.ym||'–'} ${nf(latest.count)}건(잠정)</span>`},
    {label:'중위 평당가',
     value:nf(ov.median_ppp), unit:'만원/평',
     foot:`기준월 ${nf(ref.median_ppp)}만원 · 전월비 ${pct(change(ref.median_ppp, prev.median_ppp))}`
        + `<br><span class="muted">최신월 ${nf(latest.median_ppp)}만원(잠정)</span>`},
    {label:'중위 거래가',
     value:fmtAmount(ov.median_amount), unit:'',
     foot:`평균 전용 ${ov.avg_area ?? '–'}㎡`},
  ];

  // 전년 동월 비교는 13개월 이상 모아야 가능하다. 그전까지는 빈 카드를 두는 대신
  // 같은 자리에 "전월비 평당가가 오른/내린 시군구 수"를 보여준다.
  if (yoy){
    cards.push({label:`전년 동월 대비 (${ref.ym} vs ${yoy.ym})`,
      value: pct(change(ref.median_ppp, yoy.median_ppp)), unit:'평당가',
      foot: `거래량 ${pct(change(ref.count, yoy.count))}`});
  } else {
    const rows = regionsFor(sido);
    const up = rows.filter(r => r.mom_ppp_pct > 0).length;
    const down = rows.filter(r => r.mom_ppp_pct < 0).length;
    cards.push({label:'전월비 평당가 상승 시군구',
      value:`<span class="up">${up}</span><span class="muted"> / ${rows.length}</span>`,
      unit:'개',
      foot:`하락 <span class="down">${down}</span>개 · `
         + `보합·산출불가 ${rows.length - up - down}개`});
  }
  $('#kpis').innerHTML = cards.map(c => `<div class="card kpi">
      <div class="label">${c.label}</div>
      <div class="value">${c.value}<span class="unit">${c.unit}</span></div>
      <div class="foot">${c.foot}</div>
    </div>`).join('');
}

/* ---------- 차트 ----------
   월간과 주간을 같은 그림으로 그린다. 월별 차트는 최신 달이 아직 열흘밖에 안 지났어도
   반토막으로 보이는데, 주 단위로 끊으면 그 착시가 없다. */
function weeklyFor(s){
  const v = V();
  if (s === 'ALL') return (v.weekly || {}).weeks || [];
  const e = v.sido.find(x => x.sido === s);
  return e && e.weekly ? e.weekly.weeks : [];
}

function renderChart(){
  if (chartMode === 'week') return renderWeekChart();
  $('#chart-title').textContent = '월별 거래량 · 중위 평당가';
  $('#lg-band').hidden = false;
  $('#chart-note').textContent = '';
  const ms = monthlyFor(sido);
  const W = 860, H = 300, ml = 52, mr = 58, mt = 16, mb = 42;
  const iw = W - ml - mr, ih = H - mt - mb;
  if (!ms.length){ $('#chart').innerHTML = '<p class="sub">데이터 없음</p>'; return; }

  const maxCount = Math.max(...ms.map(m => m.count), 1);
  const ppps = ms.flatMap(m => [m.median_ppp, m.p25_ppp, m.p75_ppp]).filter(v => v != null);
  const pMax = ppps.length ? Math.max(...ppps) : 1;
  const pMin = ppps.length ? Math.min(...ppps) : 0;
  // 가격 축은 0부터 그리면 변동이 안 보인다. 최소~최대에 10% 여백만 준다.
  const pad = Math.max((pMax - pMin) * 0.35, pMax * 0.03);
  const pLo = Math.max(0, pMin - pad), pHi = pMax + pad;

  const bw = iw / ms.length;
  const x = i => ml + bw * i + bw * 0.5;
  const yC = v => mt + ih - (v / maxCount) * ih;
  const yP = v => mt + ih - ((v - pLo) / (pHi - pLo || 1)) * ih;

  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="월별 거래량과 중위 평당가 추이">`;
  // 가로 그리드 + 좌우 축 눈금
  for (let t = 0; t <= 4; t++){
    const y = mt + ih - (ih * t / 4);
    svg += `<line class="gridline" x1="${ml}" y1="${y}" x2="${ml+iw}" y2="${y}"/>`;
    svg += `<text class="axis-text" x="${ml-8}" y="${y+4}" text-anchor="end">${nf(Math.round(maxCount*t/4))}</text>`;
    svg += `<text class="axis-text" x="${ml+iw+8}" y="${y+4}">${nf(Math.round(pLo+(pHi-pLo)*t/4))}</text>`;
  }
  // 막대(거래량)
  ms.forEach((m, i) => {
    const h = ih - (yC(m.count) - mt);
    svg += `<rect class="bar${m.provisional?' prov':''}" x="${ml+bw*i+bw*0.18}" y="${yC(m.count)}"`
         + ` width="${bw*0.64}" height="${Math.max(h,0)}" rx="3"><title>${m.ym} 거래 ${nf(m.count)}건`
         + `${m.provisional?' (잠정)':''}</title></rect>`;
  });
  // 사분위 밴드(25~75%). 중위선만 그리면 "강남구 10,909만원/평" 같은 한 줄이
  // 7,500짜리와 14,200짜리를 뭉갠 값이라는 사실이 화면에서 사라진다.
  const band = ms.filter(m => m.p25_ppp != null && m.p75_ppp != null);
  if (band.length > 1){
    const top = ms.map((m,i) => m.p75_ppp == null ? null : [x(i), yP(m.p75_ppp)]).filter(Boolean);
    const bot = ms.map((m,i) => m.p25_ppp == null ? null : [x(i), yP(m.p25_ppp)]).filter(Boolean);
    const d = top.map((p,i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ')
      + ' ' + bot.reverse().map(p => 'L' + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ') + ' Z';
    svg += `<path class="band" d="${d}"><title>25~75% 구간</title></path>`;
  }

  // 선(중위 평당가) — 확정 구간과 잠정 구간을 나눠 그린다
  const pts = ms.map((m,i) => m.median_ppp == null ? null : [x(i), yP(m.median_ppp)]);
  const firstProv = ms.findIndex(m => m.provisional);
  const solid = pts.slice(0, firstProv < 0 ? pts.length : firstProv + 1).filter(Boolean);
  const dashed = (firstProv < 0 ? [] : pts.slice(firstProv)).filter(Boolean);
  const path = a => a.map((p,i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  if (solid.length > 1) svg += `<path class="pline" d="${path(solid)}"/>`;
  if (dashed.length > 1) svg += `<path class="pline prov" d="${path(dashed)}"/>`;
  ms.forEach((m,i) => {
    if (m.median_ppp == null) return;
    svg += `<circle class="pdot" cx="${x(i)}" cy="${yP(m.median_ppp)}" r="3.4">`
         + `<title>${m.ym} 중위 평당가 ${nf(m.median_ppp)}만원</title></circle>`;
  });
  // x축 라벨 (좁으면 격월)
  const step = ms.length > 8 ? 2 : 1;
  ms.forEach((m,i) => {
    if (i % step && i !== ms.length-1) return;
    svg += `<text class="axis-text" x="${x(i)}" y="${mt+ih+18}" text-anchor="middle">${m.ym.slice(2)}</text>`;
  });
  svg += `<text class="axis-text" x="${ml}" y="${H-6}" text-anchor="start">건수</text>`;
  svg += `<text class="axis-text" x="${ml+iw}" y="${H-6}" text-anchor="end">만원/평</text>`;
  svg += `</svg>`;
  $('#chart').innerHTML = svg;
}

function renderWeekChart(){
  const ws = weeklyFor(sido);
  $('#chart-title').textContent = '주별 거래량 · 중위 평당가 (계약일 기준)';
  $('#lg-band').hidden = true;          // 주간은 사분위를 내지 않는다
  if (!ws.length){ $('#chart').innerHTML = '<p class="sub">주간 데이터 없음</p>'; return; }

  const W = 860, H = 300, ml = 52, mr = 58, mt = 16, mb = 42;
  const iw = W-ml-mr, ih = H-mt-mb;
  const maxC = Math.max(...ws.map(w => w.count), 1);
  const ppps = ws.map(w => w.median_ppp).filter(v => v != null);
  const pMax = ppps.length ? Math.max(...ppps) : 1, pMin = ppps.length ? Math.min(...ppps) : 0;
  const pad = Math.max((pMax-pMin)*0.35, pMax*0.03);
  const pLo = Math.max(0, pMin-pad), pHi = pMax+pad;
  const bw = iw/ws.length;
  const x = i => ml + bw*i + bw*0.5;
  const yC = v => mt + ih - (v/maxC)*ih;
  const yP = v => mt + ih - ((v-pLo)/((pHi-pLo)||1))*ih;

  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="주별 거래량과 중위 평당가">`;
  for (let t = 0; t <= 4; t++){
    const y = mt + ih - ih*t/4;
    svg += `<line class="gridline" x1="${ml}" y1="${y}" x2="${ml+iw}" y2="${y}"/>`
        +  `<text class="axis-text" x="${ml-8}" y="${y+4}" text-anchor="end">${nf(Math.round(maxC*t/4))}</text>`
        +  `<text class="axis-text" x="${ml+iw+8}" y="${y+4}">${nf(Math.round(pLo+(pHi-pLo)*t/4))}</text>`;
  }
  ws.forEach((w,i) => {
    const h = ih - (yC(w.count) - mt);
    svg += `<rect class="bar${w.provisional?' prov':''}" x="${ml+bw*i+bw*0.16}" y="${yC(w.count)}"`
        +  ` width="${bw*0.68}" height="${Math.max(h,0)}" rx="2"><title>${w.week} 주 ${nf(w.count)}건`
        +  `${w.provisional?' (아직 차오르는 중)':''}</title></rect>`;
  });
  const pts = ws.map((w,i) => w.median_ppp == null ? null : [x(i), yP(w.median_ppp)]);
  const firstProv = ws.findIndex(w => w.provisional);
  const path = a => a.map((p,i) => (i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
  const solid = pts.slice(0, firstProv < 0 ? pts.length : firstProv+1).filter(Boolean);
  const dashed = (firstProv < 0 ? [] : pts.slice(firstProv)).filter(Boolean);
  if (solid.length > 1) svg += `<path class="pline" d="${path(solid)}"/>`;
  if (dashed.length > 1) svg += `<path class="pline prov" d="${path(dashed)}"/>`;
  ws.forEach((w,i) => { if (w.median_ppp == null) return;
    svg += `<circle class="pdot" cx="${x(i)}" cy="${yP(w.median_ppp)}" r="2.6">`
        +  `<title>${w.week} 주 ${nf(w.median_ppp)}만원/평</title></circle>`; });
  const step = Math.ceil(ws.length/9);
  ws.forEach((w,i) => { if (i % step && i !== ws.length-1) return;
    svg += `<text class="axis-text" x="${x(i)}" y="${mt+ih+18}" text-anchor="middle">${w.week.slice(5)}</text>`; });
  svg += `<text class="axis-text" x="${ml}" y="${H-6}">건수</text>`
      +  `<text class="axis-text" x="${ml+iw}" y="${H-6}" text-anchor="end">만원/평</text></svg>`;
  $('#chart').innerHTML = svg;
  const wk = (V().weekly || {});
  $('#chart-note').textContent = wk.note || '';
}

/* ---------- 거래 확정도 (등기완료율) ---------- */
function renderSettlement(){
  const s = D.settlement;
  if (!s || !s.months.some(m => m.rate_pct != null)) return;
  $('#settle-card').style.display = '';
  $('#settle-note').innerHTML =
    `계약에서 소유권 이전 등기까지 <b style="color:var(--text)">중위 ${s.overall_median_days}일</b> `
    + `(25~75% ${s.p25_days}~${s.p75_days}일, ${nf(s.measured)}건 실측). `
    + `아래는 각 달의 계약 중 등기가 확인된 비율이다. `
    + `<b style="color:var(--text)">"최근 2개월은 잠정"이라는 규칙을 관측값으로 바꾼 것</b>이다.`;
  const rows = s.months.filter(m => m.total >= s.min_rows);
  $('#settle').innerHTML = rows.map(m => {
    const v = m.rate_pct ?? 0;
    // 확정도가 낮을수록 붉게. 색이 "이 달은 아직 덜 여물었다"를 대신 말한다.
    const col = v >= 90 ? 'var(--down)' : v >= 50 ? 'var(--accent)' : 'var(--up)';
    return `<div class="dist-row">
      <div>${esc(m.ym)}</div>
      <div class="track"><div class="fill" style="width:${v.toFixed(1)}%;background:${col};opacity:.6"></div></div>
      <div class="dist-val"><b style="color:var(--text)">${v.toFixed(1)}%</b>
        · ${nf(m.registered)}/${nf(m.total)}건${m.median_days != null
          ? ` · 중위 ${m.median_days}일`
          : (m.days_biased ? ' · <span class="muted">소요일 산출 보류</span>' : '')}</div>
    </div>`;
  }).join('');
  $('#settle-warn').innerHTML =
    `<b>이 값을 시장 지표로 읽으면 안 된다.</b> 최근 달의 완료율이 낮은 것은 등기가 안 될 `
    + `거래여서가 아니라 아직 등기할 시간이 지나지 않았기 때문이다. 해제율과 같은 종류의 `
    + `관측 편향이라, "요즘 등기가 잘 안 된다"로 읽어서는 안 된다. `
    + `뒤집어 보는 것이 맞다 — 완료율이 낮은 달일수록 앞으로 값이 더 움직일 여지가 크다. `
    + `<br>완료율이 ${s.days_min_rate}% 미만인 달은 소요일을 내지 않는다. 그 달에 등기가 `
    + `확인된 건은 유난히 빨리 끝난 것들뿐이라, 중위값을 내면 실제보다 짧게 나온다 `
    + `(완료율 3.6%인 달을 그대로 계산하면 "중위 2일"이 된다).`;
}

/* ---------- 매도자 · 매수자 구성 ---------- */
function renderParty(){
  const p = D.party;
  if (!p || !p.seller) return;
  $('#party-card').style.display = '';
  const sc = p.seller['법인'], bc = p.buyer['법인'];
  $('#party-note').innerHTML =
    `법인 <b style="color:var(--text)">매도 ${sc ? sc.pct : 0}%</b> vs `
    + `<b style="color:var(--text)">매수 ${bc ? bc.pct : 0}%</b> — `
    + (sc && bc && sc.pct > bc.pct
        ? `법인이 <b style="color:var(--text)">순매도</b> 쪽이다(차이 ${(sc.pct-bc.pct).toFixed(2)}%p).`
        : `법인 매수·매도 비중이 비슷하다.`);

  const order = ['개인','법인','공공기관','기타','미상'];
  const keys = order.filter(k => p.seller[k] || p.buyer[k]);
  $('#party').innerHTML = keys.map(k => {
    const s = p.seller[k] || {count:0, pct:0}, b = p.buyer[k] || {count:0, pct:0};
    const max = Math.max(s.pct, b.pct, 0.01);
    // 개인이 98%라 같은 축으로 그리면 나머지가 보이지 않는다. 행마다 자기 최대로 맞춘다.
    return `<div class="dist-row">
      <div>${esc(k)}</div>
      <div class="track" style="display:flex;flex-direction:column;gap:2px;height:26px;background:none">
        <div style="flex:1;background:var(--panel-2);border-radius:3px;overflow:hidden">
          <div class="fill" style="width:${(s.pct/max*100).toFixed(1)}%;background:var(--up)"></div></div>
        <div style="flex:1;background:var(--panel-2);border-radius:3px;overflow:hidden">
          <div class="fill" style="width:${(b.pct/max*100).toFixed(1)}%;background:var(--down)"></div></div>
      </div>
      <div class="dist-val">매도 <b style="color:var(--text)">${s.pct}%</b> (${nf(s.count)}) ·
        매수 <b style="color:var(--text)">${b.pct}%</b> (${nf(b.count)})</div>
    </div>`;
  }).join('');

  // 법인 매도 비중 추이
  const ms = p.monthly.filter(m => m.seller_corp_pct != null);
  if (ms.length > 1){
    const W = 860, H = 170, ml = 46, mr = 20, mt = 12, mb = 34;
    const iw = W-ml-mr, ih = H-mt-mb;
    const vals = ms.flatMap(m => [m.seller_corp_pct, m.buyer_corp_pct]).filter(v => v != null);
    const hi = Math.max(...vals, 0.5) * 1.15;
    const x = i => ml + (iw/(ms.length-1))*i;
    const y = v => mt + ih - (v/hi)*ih;
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="법인 매도·매수 비중 추이">`;
    for (let t = 0; t <= 3; t++){
      const yy = mt + ih - ih*t/3;
      svg += `<line class="gridline" x1="${ml}" y1="${yy}" x2="${ml+iw}" y2="${yy}"/>`
          +  `<text class="axis-text" x="${ml-8}" y="${yy+4}" text-anchor="end">${(hi*t/3).toFixed(1)}%</text>`;
    }
    const line = (key, cls) => {
      const pts = ms.map((m,i) => m[key] == null ? null : [x(i), y(m[key])]).filter(Boolean);
      return pts.length < 2 ? '' :
        `<path class="pline" style="stroke:var(--${cls})" d="${pts.map((q,i)=>(i?'L':'M')+q[0].toFixed(1)+' '+q[1].toFixed(1)).join(' ')}"/>`
        + pts.map(q => `<circle cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="2.8" fill="var(--${cls})"/>`).join('');
    };
    svg += line('seller_corp_pct','up') + line('buyer_corp_pct','down');
    const step = ms.length > 8 ? 2 : 1;
    ms.forEach((m,i) => { if (i % step && i !== ms.length-1) return;
      svg += `<text class="axis-text" x="${x(i)}" y="${mt+ih+18}" text-anchor="middle">${m.ym.slice(2)}</text>`; });
    svg += '</svg>';
    $('#party-chart').innerHTML =
      `<div class="legend" style="margin-bottom:6px">
         <span><i style="background:var(--up)"></i>법인 매도 비중</span>
         <span><i style="background:var(--down)"></i>법인 매수 비중</span></div>` + svg;
  }
  const top = p.regions.slice(0, 5).map(r =>
    `${esc(shortName(r.region))} ${r.net_corp_sell_pct}%p`).join(' · ');
  $('#party-foot').innerHTML =
    `법인 순매도(매도−매수)가 큰 곳: ${top}. `
    + `거래 ${p.min_rows}건 이상인 시군구만 낸다. `
    + `<span class="muted">법인 매도는 시행사·임대사업자 물량 정리부터 단순 자산 재배치까지 `
    + `원인이 여럿이라, 비중 자체를 호재나 악재로 읽을 수 없다.</span>`;
}

/* ---------- 확인이 필요한 거래 ---------- */
let anomFlag = 'ALL';
function renderAnomalies(){
  const a = D.anomalies;
  if (!a || !a.rows.length) return;
  $('#anom-card').style.display = '';
  // 탭 숫자는 목록에 실제로 실린 건수다. 전체 집계 수는 아래 설명에 따로 적는다.
  const sc = a.shown_flag_counts || a.flag_counts;
  const tabs = [['ALL', `전체 ${nf(a.rows.length)}건`],
    ...Object.entries(sc).sort((x,y) => y[1]-x[1]).map(([f,n]) => [f, `${f} ${nf(n)}`])];
  $('#anom-tabs').innerHTML = tabs.map(([v,label]) =>
    `<button class="chip" data-f="${esc(v)}" aria-pressed="${v===anomFlag}">${esc(label)}</button>`).join('');
  $('#anom-tabs').querySelectorAll('.chip').forEach(b =>
    b.onclick = () => { anomFlag = b.dataset.f; renderAnomalies(); });

  const rows = anomFlag === 'ALL' ? a.rows : a.rows.filter(r => r.flags.includes(anomFlag));
  const allTotals = Object.entries(a.flag_counts).sort((x,y) => y[1]-x[1])
    .map(([f,n]) => `${f} ${nf(n)}`).join(' · ');
  $('#anom-note').innerHTML =
    `${a.window[0]}~${a.window[a.window.length-1]} 계약 중 <b>시세 괴리나 등기 지연이 있으면서 `
    + `다른 신호가 겹친</b> 것은 모두 <b style="color:var(--text)">${nf(a.total)}건</b>(${allTotals}), `
    + `그중 신호가 많이 겹친 순으로 ${nf(a.rows.length)}건만 싣는다 · 지금 표시 ${nf(rows.length)}건. `
    + `시세 괴리는 같은 단지 × 같은 전용타입의 중위가 대비 ${a.discount_pct}% 이상 싼 경우이고, `
    + `${a.peer_window[0]}~${a.peer_window[a.peer_window.length-1]} 안에서만 판정한다. `
    + `등기 지연은 계약 후 ${a.stale_days}일이 지나도록 등기가 없는 경우다.`;
  $('#anom-body').innerHTML = rows.map(r => `<tr>
      <td>${esc(r.deal_date.slice(2))}</td>
      <td>${esc(shortName(r.region))}${r.umd ? ' ' + esc(r.umd) : ''}</td>
      <td class="name">${esc(r.apt || '')}</td>
      <td>${r.area_type ?? '–'}㎡</td>
      <td><b>${fmtAmount(r.amount_manwon)}</b></td>
      <td class="muted">${r.peer_median ? fmtAmount(r.peer_median) : '–'}</td>
      <td>${r.gap_pct == null ? '<span class="muted">–</span>' : pct(r.gap_pct)}</td>
      <td style="text-align:left">${r.flags.map(f =>
        `<span class="hist-item" style="margin-right:3px">${esc(f)}</span>`).join('')}</td>
    </tr>`).join('')
    || `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">해당 신호가 없다</td></tr>`;
  $('#anom-warn').innerHTML =
    `<b>이 목록은 위법의 증거가 아니다.</b> 신축 저층, 특약이 붙은 매매, 가족 간 거래, `
    + `단순 신고 오류가 모두 같은 신호를 낸다. 직거래와 법인 매도는 그 자체로는 흔한 일이라 `
    + `(직거래+법인매도만 겹친 경우는 2천 건이 넘어 제외했다) 시세 괴리나 등기 지연이 `
    + `함께 있을 때만 올렸을 뿐이고, 그래도 <b>판단이 아니라 확인의 출발점</b>이다. `
    + `조합별로는 ${Object.entries(a.combo_counts).slice(0,3)
        .map(([k,v]) => `${esc(k)} ${nf(v)}건`).join(' · ')} 순이다.`;
}

/* ---------- 랭킹 테이블 ---------- */
const COLS = [
  {k:'rank',          t:'#',          f:r => r.rank},
  {k:'region',        t:'지역',        f:r => `<span class="name">${esc(r.region)}</span>`},
  {k:'median_ppp',    t:'중위 평당가',   f:r => nf(r.median_ppp)},
  {k:'iqr_ratio_pct',  t:'25~75% 구간',  f:r => r.p25_ppp == null ? '<span class="muted">–</span>'
      : `<span class="muted">${nf(r.p25_ppp)}~${nf(r.p75_ppp)}</span>`},
  {k:'median_amount', t:'중위 거래가',   f:r => fmtAmount(r.median_amount)},
  {k:'count',         t:'거래건수',     f:r => nf(r.count)},
  {k:'share_pct',     t:'비중',        f:r => r.share_pct.toFixed(1) + '%'},
  {k:'avg_area',      t:'평균 전용',    f:r => (r.avg_area ?? '–') + '㎡'},
  {k:'ref_count',     t:'기준월 건수',   f:r => nf(r.ref_count)},
  {k:'mom_count_pct', t:'전월비 건수',   f:r => pct(r.mom_count_pct)},
  {k:'mom_ppp_pct',   t:'전월비 평당가', f:r => pct(r.mom_ppp_pct)},
  {k:'outside_pct',   t:'외지 중개',    f:r => r.outside_pct == null
      ? '<span class="muted">–</span>' : r.outside_pct.toFixed(1) + '%'},
];

function sorted(rows){
  return [...rows].sort((a,b) => {
    const av = a[sortKey], bv = b[sortKey];
    // 값이 없는 행(거래 0건 등)은 정렬 방향과 무관하게 항상 뒤로 보낸다
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return av.localeCompare(bv, 'ko') * sortDir;
    return (av - bv) * sortDir;
  });
}

function renderTable(){
  $('#thr').innerHTML = COLS.map(c =>
    `<th data-k="${c.k}"${c.k===sortKey?` aria-sort="${sortDir<0?'descending':'ascending'}"`:''}>`
    + `${c.t}${c.k===sortKey?(sortDir<0?' ▾':' ▴'):''}</th>`).join('');
  $('#thr').querySelectorAll('th').forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    if (k === sortKey) sortDir *= -1;
    else { sortKey = k; sortDir = (k === 'region' || k === 'rank') ? 1 : -1; }
    renderTable();
  });

  const rows = sorted(regionsFor(sido));
  $('#tb').innerHTML = rows.map(r =>
    `<tr>${COLS.map(c => `<td>${c.f(r)}</td>`).join('')}</tr>`).join('')
    || `<tr><td colspan="${COLS.length}" class="muted" style="text-align:center;padding:24px">
        조건에 맞는 지역이 없다</td></tr>`;
  $('#tblfoot').textContent =
    `${rows.length}개 시군구 · 순위(#)는 중위 평당가 기준이며 항상 수도권 전체 대상으로 매긴다 · `
    + `증감률은 기준월 ${D.kpi.ref_month}(확정) 대비다.`;
}

function downloadCsv(){
  const rows = sorted(regionsFor(sido));
  const head = ['순위','지역','중위평당가(만원)','중위거래가(만원)','거래건수','비중(%)',
                '25%(만원)','75%(만원)','평균전용(㎡)','기준월건수','전월비건수(%)','전월비평당가(%)',
                '외지중개(%)'];
  const body = rows.map(r => [r.rank, r.region, r.median_ppp, r.median_amount, r.count,
    r.share_pct, r.p25_ppp, r.p75_ppp, r.avg_area, r.ref_count, r.mom_count_pct, r.mom_ppp_pct,
    r.outside_pct]
    .map(v => v == null ? '' : `"${String(v).replace(/"/g,'""')}"`).join(','));
  // 엑셀이 UTF-8을 인식하도록 BOM을 붙인다
  const blob = new Blob(['﻿' + [head.join(','), ...body].join('\r\n')],
                        {type:'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `아파트실거래_시군구랭킹_${sido==='ALL'?'수도권':sido}_${D.kpi.period_to}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------- 면적 분포 ----------
   막대는 거래 비중으로 그린다. 구간별 중위 평당가는 서로 비슷해서 0 기준 막대로 그리면
   네 개가 거의 같은 길이가 되어 아무것도 읽히지 않는다. 평당가는 숫자로 보여준다. */
function renderDist(){
  const rows = D.area_distribution;
  const total = rows.reduce((s,r) => s + r.count, 0) || 1;
  const maxShare = Math.max(...rows.map(r => r.count / total), 0.01);
  $('#dist').innerHTML = rows.map(r => {
    const share = r.count / total;
    return `<div class="dist-row">
      <div>${esc(r.bucket)}</div>
      <div class="track"><div class="fill" style="width:${(share/maxShare*100).toFixed(1)}%"></div></div>
      <div class="dist-val">${(share*100).toFixed(1)}% · ${nf(r.count)}건 ·
        <b style="color:var(--text)">${nf(r.median_ppp)}</b>만원/평</div>
    </div>`;
  }).join('');
}

/* ---------- 신고가 · 신저가 ---------- */
function renderRecordHighs(){
  const rh = D.record_highs;
  if (!rh){ return; }
  const tabs = [['highs', `신고가 ${nf(rh.high_count)}건`], ['lows', `신저가 ${nf(rh.low_count)}건`]];
  $('#rhtabs').innerHTML = tabs.map(([v,label]) =>
    `<button class="chip" data-rh="${v}" aria-pressed="${v===rhTab}">${esc(label)}</button>`).join('');
  $('#rhtabs').querySelectorAll('.chip').forEach(b =>
    b.onclick = () => { rhTab = b.dataset.rh; renderRecordHighs(); });

  const rows = rh[rhTab] || [];
  $('#rhnote').textContent =
    `${rh.window[0]} ~ ${rh.window[rh.window.length-1]} 계약분 · 단지×전용면적 타입별로 `
    + `직전 거래 4건 이상인 경우만 · 갱신폭 순 상위 ${rows.length}건`;
  const hist = D.complex_history || {};
  $('#rhbody').innerHTML = rows.map((r, i) => `<tr class="rh-row" data-i="${i}">
      <td>${esc(r.deal_date.slice(2))}</td>
      <td>${esc(r.region)}${r.umd ? ' ' + esc(r.umd) : ''}</td>
      <td class="name">${esc(r.apt)}</td>
      <td>${r.area_type}㎡</td>
      <td>${r.floor ?? '–'}층</td>
      <td>${fmtAmount(r.amount_manwon)}</td>
      <td class="muted">${fmtAmount(r.prev)}</td>
      <td>${pct(r.gap_pct)}</td>
    </tr>
    <tr class="rh-detail" data-d="${i}" hidden><td colspan="8"></td></tr>`).join('')
    || `<tr><td colspan="8" class="muted" style="text-align:center;padding:24px">
        해당 기간에 갱신 거래가 없다</td></tr>`;

  // 행을 누르면 그 단지·타입의 거래 궤적을 펼친다. 갱신폭만 봐서는 그게 얼마나
  // 이례적인지 알 수 없어서, 맥락을 같은 자리에 붙인다.
  $('#rhbody').querySelectorAll('.rh-row').forEach(tr => tr.onclick = () => {
    const i = +tr.dataset.i, r = rows[i];
    const detail = $(`#rhbody .rh-detail[data-d="${i}"]`);
    if (!detail.hidden){ detail.hidden = true; return; }
    const key = `${lawdOf(r.region)}|${r.apt}|${r.area_type}`;
    const h = hist[key];
    detail.querySelector('td').innerHTML = !h ? '<span class="muted">이력 없음</span>'
      : `<div class="hist">${h.map(x => `<span class="hist-item${x.amt===r.amount_manwon?' cur':''}">`
          + `${x.d.slice(2)} <b>${fmtAmount(x.amt)}</b> <span class="muted">${x.fl ?? '–'}층</span></span>`).join('')}
         </div>`;
    detail.hidden = false;
  });
}

// analytics 는 지역명만 실어서 코드가 필요할 때 역인덱스를 쓴다.
const REGION_CODE = Object.fromEntries((D.regions || []).map(r => [r.region, r.lawd_cd]));
const REGION_BY_CODE = Object.fromEntries((D.regions || []).map(r => [r.lawd_cd, r]));
function lawdOf(region){ return REGION_CODE[region] || ''; }

/* ---------- 예산으로 찾기 ---------- */
// price_index 는 키 이름을 뺀 배열로 실려 온다(13,000행에 키를 매번 실으면 3MB).
const PI = D.price_index;
const PIC = PI ? Object.fromEntries(PI.columns.map((c,i) => [c,i])) : {};
const PI_BY_LAWD = (() => {
  const m = {};
  if (PI) for (const r of PI.rows) (m[r[PIC.lawd_cd]] ||= []).push(r);
  return m;
})();

function renderBudget(){
  if (!PI || !PI.rows.length) return;
  $('#budget-card').style.display = '';

  const budget = BST.budget, minArea = BST.area;
  const q = $('#b-region').value.trim();
  $('#b-budget-eok').textContent = budget ? `(${(budget/10000).toFixed(1)}억)` : '';

  const names = PI.region_names;
  const c = PIC;
  let hits = PI.rows.filter(r =>
    r[c.median_amount] <= budget && r[c.area_type] >= minArea
    && (!q || (names[r[c.lawd_cd]] || '').includes(q)));

  // 예산 안에서 "가장 넓은 것"이 궁금하지, "가장 싼 것"이 궁금한 게 아니다.
  hits.sort((a,b) => b[c.area_type] - a[c.area_type] || a[c.median_amount] - b[c.median_amount]);

  const regions = new Set(hits.map(r => names[r[c.lawd_cd]]));
  $('#b-summary').innerHTML = hits.length
    ? `조건에 맞는 단지 <b style="color:var(--text)">${nf(hits.length)}</b>개 · `
      + `<b style="color:var(--text)">${regions.size}</b>개 시군구 · `
      + `최대 전용 <b style="color:var(--text)">${hits[0][c.area_type]}㎡</b>`
    : '<span class="muted">조건에 맞는 단지가 없다. 예산을 올리거나 면적을 낮춰볼 것.</span>';

  $('#b-body').innerHTML = hits.slice(0, 100).map(r => `<tr>
      <td>${esc(names[r[c.lawd_cd]] || '')}</td>
      <td class="name">${esc(r[c.apt])}</td>
      <td>${r[c.area_type]}㎡</td>
      <td>${r[c.build_year] ?? '–'}</td>
      <td><b>${fmtAmount(r[c.median_amount])}</b></td>
      <td class="muted">${fmtAmount(r[c.min_amount])}~${fmtAmount(r[c.max_amount])}</td>
      <td>${nf(r[c.median_ppp])}</td>
      <td>${r[c.count]}건</td>
    </tr>`).join('');
  $('#b-note').textContent =
    `${PI.window[0]}~${PI.window[PI.window.length-1]} 중개거래 ${PI.min_deals}건 이상인 `
    + `단지×전용타입 ${nf(PI.rows.length)}개가 대상이다. 전용면적이 넓은 순으로 상위 100개만 표시한다. `
    + `시세는 그 기간 중위 거래가이므로 호가가 아니다.`;
}

// 개요의 입력칸과 지도의 입력칸이 같은 값을 가리키게 묶는다.
function syncBudgetInputs(from){
  const pairs = [['#b-budget','#mb-budget','budget'], ['#b-area','#mb-area','area']];
  for (const [a, b, key] of pairs){
    const src = from === 'map' ? b : a, dst = from === 'map' ? a : b;
    const el = $(src); if (!el) continue;
    const v = +el.value;
    if (v > 0) BST[key] = v;
    if ($(dst)) $(dst).value = BST[key];
  }
}

/* ---------- 층별 프리미엄 ---------- */
function renderFloorPremium(){
  const fp = D.floor_premium;
  if (!fp || !fp.buckets.some(b => b.premium_pct != null)) return;
  $('#floor-card').style.display = '';
  $('#floor-note').innerHTML =
    `같은 단지 × 같은 전용타입 안에서, 그 조합의 중위 평당가 대비 편차다 `
    + `(거래 ${fp.min_group}건 이상인 ${nf(fp.groups_used)}개 조합). `
    + `전체 평균으로 저층·고층을 비교하면 고층 단지가 대체로 신축이라는 효과가 섞여 `
    + `실제보다 크게 나온다.`;
  const vals = fp.buckets.map(b => Math.abs(b.premium_pct || 0));
  const max = Math.max(...vals, 1);
  $('#floorprem').innerHTML = fp.buckets.map(b => {
    const v = b.premium_pct;
    const w = v == null ? 0 : Math.abs(v) / max * 50;   // 0을 중앙에 두고 좌우로
    const left = v == null ? 50 : (v < 0 ? 50 - w : 50);
    return `<div class="dist-row">
      <div>${b.bucket}</div>
      <div class="track" style="position:relative">
        <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line)"></div>
        <div class="fill" style="position:absolute;left:${left}%;width:${w}%;
          background:${v < 0 ? 'var(--down)' : 'var(--up)'}"></div>
      </div>
      <div class="dist-val"><b style="color:var(--text)">${v == null ? '–' : (v > 0 ? '+' : '') + v + '%'}</b>
        · 거래 ${nf(b.count)}건</div>
    </div>`;
  }).join('');
}

/* ---------- 전세가율 ---------- */
function renderJeonse(){
  const j = D.jeonse;
  if (!j || !j.regions || !j.regions.length) return;
  $('#jeonse-card').style.display = '';
  $('#jeonse-note').innerHTML =
    `수도권 중위 <b style="color:var(--text)">${j.overall_pct}%</b> · `
    + `같은 단지 × 같은 전용타입끼리 짝지어 계산 (${nf(j.matched_pairs)}쌍 매칭) · `
    + `양쪽 모두 ${j.min_pairs}건 이상, 시군구당 ${j.min_region_samples}개 단지 이상만 집계`;
  const rows = [...j.regions].sort((a,b) => b.jeonse_ratio_pct - a.jeonse_ratio_pct);
  const max = Math.max(...rows.map(r => r.jeonse_ratio_pct), 1);
  $('#jeonse').innerHTML = rows.map(r => `<div class="dist-row">
      <div style="font-size:12.5px">${esc(shortName(r.region))}</div>
      <div class="track"><div class="fill" style="width:${(r.jeonse_ratio_pct/max*100).toFixed(1)}%"></div></div>
      <div class="dist-val"><b style="color:var(--text)">${r.jeonse_ratio_pct}%</b>
        · 단지 ${nf(r.matched_complexes)}개</div>
    </div>`).join('');
}

/* ---------- 거래 형태 ---------- */
function renderDealType(){
  const dt = D.deal_type;
  if (!dt){ return; }
  const total = dt.broker.count + dt.direct.count || 1;
  const rows = [
    ['중개거래', dt.broker, dt.broker.count / total],
    ['직거래', dt.direct, dt.direct.count / total],
  ];
  $('#dealtype').innerHTML = rows.map(([label, s, share]) => `<div class="dist-row">
      <div>${label}</div>
      <div class="track"><div class="fill" style="width:${(share*100).toFixed(1)}%"></div></div>
      <div class="dist-val">${(share*100).toFixed(1)}% · ${nf(s.count)}건 ·
        <b style="color:var(--text)">${nf(s.median_ppp)}</b>만원/평</div>
    </div>`).join('')
    + (dt.direct_vs_broker_pct == null ? '' :
       `<p class="sub" style="margin:6px 0 0">직거래 중위 평당가는 중개거래 대비
        <b style="color:var(--text)">${dt.direct_vs_broker_pct}%</b></p>`);
}

/* ================================================================
   입체 지도

   외부 라이브러리 없이 축측투영(axonometric)으로 직접 그린다. 시군구 경계를
   밑면으로 두고 지표값만큼 기둥을 세운 뒤, 카메라에서 보이는 옆면만 골라
   명암을 넣는다. 순서는 화가 알고리즘 — 먼 셀부터 그려서 가까운 셀이 덮게 한다.
   ================================================================ */
const MAP = {
  metric: 'median_ppp',
  rot: -20, tilt: 47, exag: 1.0,
  month: null,          // null = 전체 기간, 아니면 월 인덱스
  playing: false, timer: null,
  sel: null,            // 고정한 셀
  labels: false,
  geom: null,
};
const MAP_DEFAULT = {rot: -20, tilt: 47, exag: 1.0};

const METRICS = {
  median_ppp: {label:'중위 평당가', unit:'만원/평', kind:'seq', monthly:'ppp',
               fmt:v => nf(Math.round(v))},
  count:      {label:'거래건수', unit:'건', kind:'seq', monthly:'count',
               fmt:v => nf(Math.round(v))},
  mom_ppp_pct:{label:'전월비 평당가', unit:'%', kind:'div', monthly:null,
               fmt:v => (v>0?'+':'') + v.toFixed(1)},
  budget:     {label:'예산 도달률', unit:'%', kind:'seq', monthly:null,
               fmt:v => v.toFixed(1)},
  // 매물 소재지와 중개사 소재지가 다른 거래의 비중. "이 동네를 사는 사람이 이 동네
  // 사람인가"에 가장 가까운 관측값이다.
  outside_pct:{label:'외지 중개', unit:'%', kind:'seq', monthly:null,
               fmt:v => v.toFixed(1)},
};
// 낮은 값 -> 높은 값. 남색에서 시작해 마지막에 산호색으로 튄다. 시작을 너무 어둡게
// 잡으면 값이 하위에 몰린 경기 외곽이 전부 같은 색으로 뭉개진다.
const RAMP_SEQ = ['#20428f','#2160c2','#1b8fbe','#1eab8f','#8cc44f','#f3c53c','#f2803a','#df3d4d'];
// 발산형(전월비)은 가운데가 중립이어야 한다. 0 근처가 회색이 되도록 잡는다.
const RAMP_DIV = ['#2f74c8','#5f9fd8','#93b8cf','#69748c','#d9a08c','#e06a4c','#cf2f36'];
// 값이 없거나 필터에서 빠진 셀의 색. 다크에서 쓰던 남회색을 라이트 배경에 그대로 쓰면
// 흐려지기는커녕 제일 무겁게 보인다. 테마에 맞춰 뒤로 물러나는 쪽으로 잡는다.
const noval = () => document.documentElement.dataset.theme === 'light' ? '#c6d0e0' : '#3a4560';
const LIGHT = [-0.56, -0.83];      // 화면 왼쪽 앞에서 오는 빛

function hex2rgb(h){ const n = parseInt(h.slice(1), 16);
  return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function rgb2hex(c){ return '#' + c.map(v =>
  Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2,'0')).join(''); }
function mixHex(a, b, t){ const A = hex2rgb(a), B = hex2rgb(b);
  return rgb2hex([0,1,2].map(i => A[i] + (B[i]-A[i]) * t)); }
function rampAt(ramp, t){
  t = Math.max(0, Math.min(1, t || 0));
  const x = t * (ramp.length - 1), i = Math.floor(x);
  return i >= ramp.length - 1 ? ramp[ramp.length-1] : mixHex(ramp[i], ramp[i+1], x - i);
}
function shade(hex, f){ return rgb2hex(hex2rgb(hex).map(v => v * f)); }
function rampCss(ramp){
  return `linear-gradient(90deg,${ramp.join(',')})`;
}

/* --- 셀 -> 시군구 코드들 --- */
const CELL_MEMBERS = (() => {
  const m = {};
  if (GEO) for (const [lawd, cell] of Object.entries(GEO.cell_of)) (m[cell] ||= []).push(lawd);
  return m;
})();

/* --- 값 계산 ---------------------------------------------------
   병합 셀(옛 중구+동구 등)은 여러 시군구를 한 칸에 담는다. 중위값은 원자료 없이
   합칠 수 없으므로 거래건수 가중평균으로 근사하고, 그 사실을 툴팁에 적는다.
   거래건수는 단순 합, 예산 도달률은 분자·분모를 각각 합쳐 정확히 계산한다.       */
function budgetShare(lawds){
  if (!PI) return null;
  let hit = 0, tot = 0;
  for (const l of lawds){
    const rows = PI_BY_LAWD[l] || [];
    tot += rows.length;
    for (const r of rows)
      if (r[PIC.median_amount] <= BST.budget && r[PIC.area_type] >= BST.area) hit++;
  }
  return tot ? hit / tot * 100 : null;
}

// 시군구 코드 -> 랭킹 행. cellValue 가 한 프레임에 천 번 넘게 불려서 매번
// 새로 만들면 회전이 눈에 띄게 끊긴다.
let _byLawd = {key:null, map:null};
function regionsByLawd(){
  if (_byLawd.key !== dealType)
    _byLawd = {key:dealType, map:Object.fromEntries(V().regions.map(r => [r.lawd_cd, r]))};
  return _byLawd.map;
}

function cellValue(cell, key, mi){
  const lawds = CELL_MEMBERS[cell] || [];
  if (!lawds.length) return null;
  if (key === 'budget') return budgetShare(lawds);

  const v = V();
  if (mi != null && METRICS[key].monthly){
    const rm = v.region_monthly || D.region_monthly;
    if (!rm) return null;
    if (key === 'count'){
      let s = 0, seen = false;
      for (const l of lawds){ const e = rm.regions[l]; if (!e) continue; seen = true; s += e.count[mi] || 0; }
      return seen ? s : null;
    }
    let num = 0, den = 0;
    for (const l of lawds){
      const e = rm.regions[l]; if (!e) continue;
      const val = e.ppp[mi], w = e.count[mi];
      if (val == null || !w) continue;
      num += val * w; den += w;
    }
    return den ? num / den : null;
  }

  const by = regionsByLawd();
  if (key === 'count'){
    let s = 0, seen = false;
    for (const l of lawds){ const r = by[l]; if (!r) continue; seen = true; s += r.count || 0; }
    return seen ? s : null;
  }
  let num = 0, den = 0;
  for (const l of lawds){
    const r = by[l]; if (!r) continue;
    // 가중치는 지표마다 다르다. 전월비는 기준월 건수, 외지 중개는 판정 가능했던
    // 건수(중개사 소재지가 있는 건)로 묶어야 병합 셀의 합산이 어긋나지 않는다.
    const val = r[key];
    const w = (key === 'mom_ppp_pct' ? r.ref_count
             : key === 'outside_pct' ? r.outside_judged
             : r.count) || 0;
    if (val == null || !w) continue;
    num += val * w; den += w;
  }
  return den ? num / den : null;
}

function mapDomain(key, scope){
  // 눈금을 두 벌로 나눈다.
  //   scope='static'  — 전체 기간 한 장. 그 화면의 최대·최소에 눈금을 꽉 채운다.
  //   scope='monthly' — 모든 달을 한꺼번에 넣어 재생 내내 고정한다. 매달 다시 잡으면
  //                     색이 늘 같아 보여서 아무것도 변하지 않는 것처럼 읽힌다.
  // 한 벌로 합치면 월별 최대치(표본이 얇은 달에 튄다)가 눈금 위쪽을 먹어버려,
  // 정작 첫 화면인 전체 기간이 램프의 아래쪽에만 몰린다(실측: 강남 10,939인데
  // 눈금 상한이 12,907이라 최고가 지역이 빨강까지 가지 못했다).
  const met = METRICS[key], cells = Object.keys(GEO.cells);
  const vals = [];
  const push = mi => { for (const c of cells){ const v = cellValue(c, key, mi); if (v != null) vals.push(v); } };
  if (scope === 'monthly' && met.monthly) (D.region_monthly?.months || []).forEach((_, i) => push(i));
  else push(null);
  if (!vals.length) return {lo:0, hi:1, ramp:RAMP_SEQ, kind:'seq', norm:() => 0, height:() => 0};

  if (met.kind === 'div'){
    const m = Math.max(...vals.map(Math.abs), 0.1);
    return {lo:-m, hi:m, ramp:RAMP_DIV, kind:'div',
            norm:v => 0.5 + 0.5 * v / m,
            height:v => 0.05 + 0.95 * Math.abs(v) / m};
  }
  const lo = Math.min(...vals), hi = Math.max(...vals), span = (hi - lo) || 1;
  return {lo, hi, ramp:RAMP_SEQ, kind:'seq',
          norm:v => (v - lo) / span,
          height:v => 0.05 + 0.95 * (v - lo) / span};
}

// 눈금 계산은 78개 셀 × 16개 월을 훑는다. 시점을 끌 때마다 다시 하면 회전이 끊기고,
// 애초에 시점이 바뀐다고 눈금이 달라지지도 않는다.
let _dom = {k:null, v:null};
function domainFor(key){
  const scope = MAP.month == null ? 'static' : 'monthly';
  const k = [key, scope, dealType, BST.budget, BST.area].join('|');
  if (_dom.k !== k) _dom = {k, v: mapDomain(key, scope)};
  return _dom.v;
}

function mapLabelText(name){
  const s = String(name).split('(')[0].trim()
    .replace(/^(서울특별시|인천광역시|경기도)\s*/, '');
  const w = s.split(' '), last = w[w.length-1];
  // "수원시 장안구" 는 구 이름만, "화성시 4개 구" 는 통째로 쓴다.
  return (w.length > 1 && last.length >= 2 && /[구시군]$/.test(last)) ? last : s;
}

/* --- 기하 준비(한 번만) --- */
function prepGeom(){
  if (MAP.geom || !GEO) return MAP.geom;
  const KX = Math.cos(37.5 * Math.PI / 180);   // 위도 37.5°에서 경도 1°는 위도 1°의 0.79배
  const raw = [];
  for (const [cell, rings] of Object.entries(GEO.cells))
    for (const r of rings){
      let sx = 0, sy = 0;
      for (const p of r){ sx += p[0]; sy += p[1]; }
      raw.push({cell, pts:r, cx:sx/r.length, cy:sy/r.length});
    }
  // 옹진군의 서해 먼바다 섬(백령·연평)은 본토에서 150km 넘게 떨어져 있다. 함께 그리면
  // 화면의 3분의 1이 빈 바다가 되고 수도권 본토가 그만큼 작아진다. 아예 빼고 그 사실을
  // 화면에 적는다 — 시야만 좁히면 잘린 섬이 프레임 가장자리에 걸려 더 이상하다.
  const med = a => { const s = [...a].sort((x,y) => x-y); return s[s.length >> 1]; };
  const mx = med(raw.map(r => r.cx)), my = med(raw.map(r => r.cy));
  const core = raw.filter(r => Math.abs(r.cx-mx) < 1.2 && Math.abs(r.cy-my) < 1.2);
  const outside = raw.length - core.length;
  let lo0=1e9, hi0=-1e9, lo1=1e9, hi1=-1e9;
  for (const r of core) for (const p of r.pts){
    if (p[0]<lo0) lo0=p[0]; if (p[0]>hi0) hi0=p[0];
    if (p[1]<lo1) lo1=p[1]; if (p[1]>hi1) hi1=p[1];
  }
  const cx = (lo0+hi0)/2, cy = (lo1+hi1)/2;
  const toWorld = p => [(p[0]-cx)*KX, p[1]-cy];

  const byCell = {};
  for (const r of core){
    let pts = r.pts.map(toWorld);
    // 감김 방향을 반시계로 통일한다. 옆면의 앞뒤 판정이 이 방향에 걸려 있다.
    let a2 = 0;
    for (let i = 0; i < pts.length; i++){
      const p = pts[i], q = pts[(i+1) % pts.length];
      a2 += p[0]*q[1] - q[0]*p[1];
    }
    if (a2 < 0) pts.reverse();
    (byCell[r.cell] ||= []).push(pts);
  }
  const cells = Object.entries(byCell).map(([cell, rings]) => {
    let sx = 0, sy = 0, n = 0;
    // 대표점은 가장 큰 링 기준이다. 작은 섬들이 중심을 바다로 끌고 가면
    // 라벨과 앞뒤 정렬이 어긋난다.
    const main = rings.reduce((a,b) => a.length >= b.length ? a : b);
    for (const p of main){ sx += p[0]; sy += p[1]; n++; }
    return {cell, rings, cx:sx/n, cy:sy/n};
  });
  const span = Math.max((hi0-lo0)*KX, hi1-lo1);
  MAP.geom = {cells, span, outside};
  return MAP.geom;
}

/* --- 렌더 ---
   quick=true 면 SVG 만 다시 그린다. 시점을 끄는 동안에는 범례·순위·주석이 바뀌지
   않는데, 매 프레임 다시 만들면 그것만으로 프레임이 밀린다. */
function renderMap(quick){
  if (!GEO) return;
  const g = prepGeom();
  const key = MAP.metric, met = METRICS[key], dom = domainFor(key);
  const mi = MAP.month;

  const W = 980, H = 580;
  const a = MAP.rot * Math.PI/180, t = MAP.tilt * Math.PI/180;
  const ca = Math.cos(a), sa = Math.sin(a), st = Math.sin(t), ct = Math.cos(t);

  const activeSido = sido;
  const sidoOf = cell => {
    const l = (CELL_MEMBERS[cell] || [])[0];
    return l && REGION_BY_CODE[l] ? REGION_BY_CODE[l].sido : null;
  };

  // 1) 기둥 높이를 먼저 정한다. 화면 맞춤이 높이에 걸려 있어서다.
  const hMax = g.span * 0.42 * MAP.exag;
  const dull = noval();
  const info = g.cells.map(c => {
    const v = cellValue(c.cell, key, mi);
    const inSido = activeSido === 'ALL' || sidoOf(c.cell) === activeSido;
    const col = v == null ? dull : rampAt(dom.ramp, dom.norm(v));
    return {c, v, inSido,
            base: inSido ? col : mixHex(col, dull, 0.8),
            h: (v == null ? 0.02 : dom.height(v)) * hMax * (inSido ? 1 : 0.12)};
  });

  // 2) 밑면과 윗면을 모두 넣어 실제 차지하는 넓이를 잰다. 밑면만 재고 "가장 높은
  //    기둥만큼" 여백을 잡으면, 그 높이에 닿는 셀이 하나뿐이라 화면의 절반이 빈다.
  let x0=1e9, x1=-1e9, y0=1e9, y1=-1e9;
  for (const {c, h} of info) for (const r of c.rings) for (const p of r){
    const Xr = p[0]*ca - p[1]*sa, Yr = p[0]*sa + p[1]*ca;
    const yb = -(Yr*st), yt = yb - h*ct;
    if (Xr<x0) x0=Xr; if (Xr>x1) x1=Xr;
    if (yt<y0) y0=yt; if (yb>y1) y1=yb;
  }
  const spanX = (x1-x0) || 1, spanY = (y1-y0) || 1;
  const s = Math.min((W-40)/spanX, (H-40)/spanY);
  const ox = (W - spanX*s)/2 - x0*s;
  const oy = (H - spanY*s)/2 - y0*s;
  const P = (X, Y, Z) => {
    const Xr = X*ca - Y*sa, Yr = X*sa + Y*ca;
    return (ox + Xr*s).toFixed(1) + ',' + (oy - (Yr*st + Z*ct)*s).toFixed(1);
  };

  // 3) 먼 셀부터. 카메라는 -Yr 쪽에 있으므로 Yr 이 큰 셀이 멀다.
  const order = info.map((d, i) => ({i, Yr: d.c.cx*sa + d.c.cy*ca}))
                    .sort((p, q) => q.Yr - p.Yr);

  let out = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="수도권 시군구 입체 지도">`;
  // 밑면 윤곽을 먼저 한 겹 깔면 기둥이 바닥에 붙어 보인다.
  let plate = '';
  for (const c of g.cells)
    for (const r of c.rings) plate += 'M' + r.map(p => P(p[0],p[1],0)).join('L') + 'Z';
  out += `<path class="plate" d="${plate}"/>`;

  const labels = [];
  const BUCKETS = 12;   // 옆면 명암 단계. 벽 하나당 path 를 만들면 2천 개가 넘는다.
  for (const {i} of order){
    const {c, v, inSido, base, h} = info[i];
    const buckets = new Map();
    for (const ring of c.rings){
      const n = ring.length;
      for (let k = 0; k < n; k++){
        const p = ring[k], q = ring[(k+1) % n];
        const pXr = p[0]*ca - p[1]*sa, qXr = q[0]*ca - q[1]*sa;
        // 반시계 링에서 바깥 법선이 카메라를 향하는 옆면은 dx>0 인 변이다.
        const dx = qXr - pXr;
        if (dx <= 0) continue;
        const dy = (q[0]*sa + q[1]*ca) - (p[0]*sa + p[1]*ca);
        const L = Math.hypot(dx, dy) || 1;
        const lam = Math.max(0.30, Math.min(1.0,
          0.50 + 0.38 * ((dy/L)*LIGHT[0] + (-dx/L)*LIGHT[1])));
        const b = Math.round(lam * BUCKETS);
        const seg = `M${P(p[0],p[1],0)}L${P(q[0],q[1],0)}L${P(q[0],q[1],h)}L${P(p[0],p[1],h)}Z`;
        buckets.set(b, (buckets.get(b) || '') + seg);
      }
    }
    let body = '';
    for (const [b, d] of buckets) body += `<path d="${d}" fill="${shade(base, b/BUCKETS)}"/>`;
    const top = c.rings.map(r => 'M' + r.map(p => P(p[0],p[1],h)).join('L') + 'Z').join('');
    body += `<path d="${top}" fill="${base}" stroke="${shade(base, 1.45)}" stroke-width=".8"/>`;
    const sel = MAP.sel === c.cell ? ' class="sel"' : '';
    out += `<g data-cell="${esc(c.cell)}"${sel}>${body}</g>`;
    if (MAP.labels && inSido && v != null){
      const [lx, ly] = P(c.cx, c.cy, h).split(',');
      labels.push({x:+lx, y:+ly - 5, v, text: mapLabelText(GEO.labels[c.cell] || c.cell)});
    }
  }
  // 라벨은 기둥에 가리면 못 읽으니 맨 위에 한 겹으로 올린다. 서울 도심은 구가 다닥다닥
  // 붙어 있어 전부 찍으면 글자가 겹쳐 아무것도 안 읽힌다. 값이 큰 곳부터 자리를
  // 잡고, 이미 놓인 라벨과 겹치는 것은 버린다.
  labels.sort((a, b) => b.v - a.v);
  const placed = [];
  for (const L of labels){
    if (placed.some(q => Math.abs(q.x - L.x) < 42 && Math.abs(q.y - L.y) < 13)) continue;
    placed.push(L);
    out += `<text class="maplabel" x="${L.x.toFixed(1)}" y="${L.y.toFixed(1)}" `
         + `text-anchor="middle">${esc(L.text)}</text>`;
  }
  out += '</svg>';
  $('#map').innerHTML = out;
  if (quick) return;

  // 범례 / 눈금
  $('#m-ramp').style.background = rampCss(dom.ramp);
  $('#m-lo').textContent = met.fmt(dom.lo) + met.unit;
  $('#m-hi').textContent = met.fmt(dom.hi) + met.unit;
  renderMapRank(dom);
  renderMapCaveat();
}

function renderMapCaveat(){
  const g = MAP.geom;
  const note = GEO.note ? GEO.note + ' ' : '';
  $('#m-caveat').innerHTML = esc(note)
    + `기둥 높이와 색은 모두 <b>${METRICS[MAP.metric].label}</b>이다. `
    + (MAP.metric === 'mom_ppp_pct'
        ? `발산형 눈금이라 가운데가 0%이고, 높이는 변화의 크기(절대값)다. `
        : '')
    + `병합 셀(옛 중구+동구 등)의 중위값은 원자료 없이 합칠 수 없어 거래건수 가중평균으로 `
    + `근사했다 — 기둥을 누르면 구성 시군구의 개별 값이 나온다. `
    + (g && g.outside ? `옹진군의 서해 먼바다 섬 등 ${g.outside}개 링은 화면 밖이다. ` : '');
}

/* --- 오른쪽 순위 목록: 지도의 범례이자 목차 --- */
function renderMapRank(dom){
  const key = MAP.metric, met = METRICS[key], mi = MAP.month;
  const rows = Object.keys(GEO.cells).map(cell => ({
    cell, name: GEO.labels[cell] || cell, v: cellValue(cell, key, mi),
  })).filter(r => r.v != null);
  rows.sort((a,b) => b.v - a.v);
  const maxAbs = Math.max(...rows.map(r => Math.abs(r.v)), 1e-9);
  $('#m-ranktitle').innerHTML =
    `<b style="color:var(--text)">${esc(met.label)}</b> 순위 · ${rows.length}개 셀`
    + (mi == null ? '' : ` · ${esc(D.region_monthly.months[mi])}`);
  $('#m-ranklist').innerHTML = rows.map(r => `
    <div class="rankbar${MAP.sel===r.cell?' sel':''}" data-cell="${esc(r.cell)}">
      <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
           title="${esc(r.name)}">${esc(shortName(r.name))}</div>
      <div class="rt"><div class="rf" style="width:${(Math.abs(r.v)/maxAbs*100).toFixed(1)}%;
        background:${rampAt(dom.ramp, dom.norm(r.v))}"></div></div>
      <div class="rv">${met.fmt(r.v)}</div>
    </div>`).join('');
  $('#m-ranklist').querySelectorAll('.rankbar').forEach(el =>
    el.onclick = () => selectCell(el.dataset.cell));
}

/* --- 선택한 셀의 월별 궤적 --- */
function selectCell(cell){
  MAP.sel = (MAP.sel === cell) ? null : cell;
  renderMap();
  renderMapDetail();
  if (MAP.sel) $('#m-detail-card').scrollIntoView({behavior:'smooth', block:'nearest'});
}

let detailLawd = null;
function renderMapDetail(){
  const card = $('#m-detail-card');
  if (!MAP.sel){
    $('#m-dtitle').textContent = '지역 상세';
    $('#m-dmembers').innerHTML = '';
    $('#m-dsub').textContent = '지도에서 기둥을 누르거나 오른쪽 순위에서 지역을 고르면 그 지역의 월별 궤적이 여기에 나온다.';
    $('#m-dchart').innerHTML = '';
    return;
  }
  const lawds = CELL_MEMBERS[MAP.sel] || [];
  if (!lawds.includes(detailLawd)) detailLawd = lawds[0];
  $('#m-dtitle').textContent = GEO.labels[MAP.sel] || MAP.sel;
  // 병합 셀은 어느 시군구의 궤적인지 골라야 한다. 합쳐서 그리면 두 지역의
  // 서로 다른 움직임이 한 선으로 뭉개진다.
  $('#m-dmembers').innerHTML = lawds.length < 2 ? '' : lawds.map(l =>
    `<button class="chip" data-l="${esc(l)}" aria-pressed="${l===detailLawd}">`
    + `${esc(shortName((REGION_BY_CODE[l]||{}).region || l))}</button>`).join('');
  $('#m-dmembers').querySelectorAll('.chip').forEach(b =>
    b.onclick = () => { detailLawd = b.dataset.l; renderMapDetail(); });

  const r = REGION_BY_CODE[detailLawd];
  const rm = (V().region_monthly || D.region_monthly);
  const e = rm && rm.regions[detailLawd];
  if (!r || !e){ $('#m-dsub').textContent = '이 지역의 거래 기록이 없다.'; $('#m-dchart').innerHTML = ''; return; }

  $('#m-dsub').innerHTML =
    `중위 평당가 <b style="color:var(--text)">${nf(r.median_ppp)}</b>만원/평 `
    + `(수도권 ${r.rank}위) · 중위 거래가 <b style="color:var(--text)">${fmtAmount(r.median_amount)}</b> · `
    + `거래 ${nf(r.count)}건 · 전월비 평당가 ${pct(r.mom_ppp_pct)} · `
    + `25~75% ${nf(r.p25_ppp)}~${nf(r.p75_ppp)}만원`;

  const months = rm.months, prov = new Set(D.meta.provisional_months || []);
  const W = 860, H = 250, ml = 52, mr = 56, mt = 14, mb = 40;
  const iw = W-ml-mr, ih = H-mt-mb, bw = iw/months.length;
  const maxC = Math.max(...e.count, 1);
  const vals = e.ppp.filter(v => v != null);
  const pMax = vals.length ? Math.max(...vals) : 1, pMin = vals.length ? Math.min(...vals) : 0;
  const pad = Math.max((pMax-pMin)*0.35, pMax*0.03);
  const pLo = Math.max(0, pMin-pad), pHi = pMax+pad;
  const x = i => ml + bw*i + bw*0.5;
  const yC = v => mt + ih - (v/maxC)*ih;
  const yP = v => mt + ih - ((v-pLo)/((pHi-pLo)||1))*ih;

  let svg = `<svg viewBox="0 0 ${W} ${H}">`;
  for (let k = 0; k <= 4; k++){
    const y = mt + ih - ih*k/4;
    svg += `<line class="gridline" x1="${ml}" y1="${y}" x2="${ml+iw}" y2="${y}"/>`
        +  `<text class="axis-text" x="${ml-8}" y="${y+4}" text-anchor="end">${nf(Math.round(maxC*k/4))}</text>`
        +  `<text class="axis-text" x="${ml+iw+8}" y="${y+4}">${nf(Math.round(pLo+(pHi-pLo)*k/4))}</text>`;
  }
  months.forEach((ym, i) => {
    const h = ih - (yC(e.count[i]) - mt);
    svg += `<rect class="bar${prov.has(ym)?' prov':''}" x="${ml+bw*i+bw*0.18}" y="${yC(e.count[i])}"`
        +  ` width="${bw*0.64}" height="${Math.max(h,0)}" rx="3"><title>${ym} ${nf(e.count[i])}건</title></rect>`;
  });
  const pts = months.map((ym,i) => e.ppp[i] == null ? null : [x(i), yP(e.ppp[i])]).filter(Boolean);
  if (pts.length > 1)
    svg += `<path class="pline" d="${pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ')}"/>`;
  months.forEach((ym,i) => { if (e.ppp[i] == null) return;
    svg += `<circle class="pdot" cx="${x(i)}" cy="${yP(e.ppp[i])}" r="3.2">`
        +  `<title>${ym} ${nf(e.ppp[i])}만원/평</title></circle>`; });
  const step = months.length > 8 ? 2 : 1;
  months.forEach((ym,i) => { if (i % step && i !== months.length-1) return;
    svg += `<text class="axis-text" x="${x(i)}" y="${mt+ih+18}" text-anchor="middle">${ym.slice(2)}</text>`; });
  svg += `<text class="axis-text" x="${ml}" y="${H-6}">건수</text>`
      +  `<text class="axis-text" x="${ml+iw}" y="${H-6}" text-anchor="end">만원/평</text></svg>`;
  $('#m-dchart').innerHTML = svg
    + `<p class="sub" style="margin-top:10px">월별 중위 평당가는 표본이 `
    + `${rm.min_samples}건 미만인 달을 비운다. 두세 건짜리 중위값이 시장 변화처럼 보이면 안 된다.</p>`;
}

/* --- 컨트롤 --- */
function setupMap(){
  // 경계 파일 없이도 나머지 대시보드는 그대로 돌아야 한다. 빈 탭을 남기는 대신 숨긴다.
  if (!GEO){
    const b = $('#tabs .tab[data-tab="map"]');
    if (b) b.hidden = true;
    $('#pane-map').remove();
    return;
  }
  $('#map-metric').innerHTML = Object.entries(METRICS).map(([k, m]) =>
    `<button data-m="${k}" aria-pressed="${k===MAP.metric}">${esc(m.label)}</button>`).join('');
  $('#map-metric').querySelectorAll('button').forEach(b => b.onclick = () => {
    MAP.metric = b.dataset.m;
    if (!METRICS[MAP.metric].monthly) MAP.month = null;
    stopPlay(); syncMapControls(); renderMap();
  });

  const months = (D.region_monthly || {}).months || [];
  $('#m-month').max = String(Math.max(months.length - 1, 0));
  $('#m-month').value = String(Math.max(months.length - 1, 0));

  // 시점만 바꾸는 조작은 SVG 만 다시 그린다(범례·순위는 그대로다).
  const bind = (sel, key) => $(sel).oninput = e => { MAP[key] = +e.target.value; renderMap(true); };
  bind('#m-rot', 'rot'); bind('#m-tilt', 'tilt');
  $('#m-exag').oninput = e => { MAP.exag = +e.target.value/100; renderMap(true); };
  $('#m-labels').onchange = e => { MAP.labels = e.target.checked; renderMap(true); };
  $('#m-reset').onclick = () => { Object.assign(MAP, MAP_DEFAULT); syncMapControls(); renderMap(true); };

  $('#m-month').oninput = e => { MAP.month = +e.target.value; syncMapControls(); renderMap(); };
  $('#m-allmonths').onclick = () => { stopPlay(); MAP.month = null; syncMapControls(); renderMap(); };
  $('#m-play').onclick = () => MAP.playing ? stopPlay() : startPlay();

  ['#mb-budget','#mb-area'].forEach(s => $(s).oninput = () => {
    syncBudgetInputs('map'); renderBudget(); if (MAP.metric === 'budget') renderMap(); });

  // 끌어서 시점 변경. 가로는 방위각, 세로는 카메라 고도.
  const stage = $('#stage');
  let drag = null;
  stage.addEventListener('pointerdown', e => {
    // 포인터를 캡처하면 이후 이벤트의 target 이 stage 가 되어 어느 기둥을 눌렀는지
    // 알 수 없다. 누른 순간에 미리 집어둔다.
    const g = e.target.closest && e.target.closest('g[data-cell]');
    drag = {x:e.clientX, y:e.clientY, rot:MAP.rot, tilt:MAP.tilt, moved:0,
            cell: g ? g.dataset.cell : null};
    $('#maptip').style.opacity = 0;
    stage.classList.add('drag'); stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener('pointermove', e => {
    if (!drag){ hoverMap(e); return; }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy));
    MAP.rot = ((drag.rot + dx*0.4 + 180) % 360 + 360) % 360 - 180;
    MAP.tilt = Math.max(14, Math.min(80, drag.tilt + dy*0.25));
    syncMapControls(); renderMap(true);
  });
  const end = () => {
    if (!drag) return;
    // 끌고 나서 손을 떼는 것은 선택이 아니다. 5px 미만만 클릭으로 본다.
    if (drag.moved < 5 && drag.cell) selectCell(drag.cell);
    stage.classList.remove('drag'); drag = null;
  };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);
  stage.addEventListener('pointerleave', () => { $('#maptip').style.opacity = 0; });

  syncMapControls();
  renderMapDetail();
}

function syncMapControls(){
  $('#m-rot').value = String(Math.round(MAP.rot));
  $('#m-tilt').value = String(Math.round(MAP.tilt));
  $('#m-exag').value = String(Math.round(MAP.exag*100));
  $('#m-labels').checked = MAP.labels;
  $('#map-metric').querySelectorAll('button').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.m === MAP.metric)));
  const months = (D.region_monthly || {}).months || [];
  const hasMonthly = !!METRICS[MAP.metric].monthly && months.length > 0;
  $('#m-playctl').style.display = hasMonthly ? '' : 'none';
  $('#m-budgetctl').style.display = MAP.metric === 'budget' ? '' : 'none';
  $('#mb-note').textContent = PI
    ? `${PI.window[0]}~${PI.window[PI.window.length-1]} 중개거래 기준 단지×전용타입 중 조건을 만족하는 비율`
    : '시세 인덱스가 없어 계산할 수 없다';
  // 전체 기간으로 돌아왔는데 슬라이더 손잡이가 중간에 남아 있으면 어느 쪽이 맞는지
  // 알 수 없다. 끝으로 돌려 놓는다.
  $('#m-month').value = String(MAP.month == null ? Math.max(months.length-1, 0) : MAP.month);
  $('#m-monthlabel').textContent = MAP.month == null ? '전체 기간'
    : months[MAP.month] + ((D.meta.provisional_months || []).includes(months[MAP.month]) ? ' (잠정)' : '');
  $('#m-play').textContent = MAP.playing ? '⏸ 정지' : '▶ 재생';
}

function startPlay(){
  const months = (D.region_monthly || {}).months || [];
  if (!months.length || !METRICS[MAP.metric].monthly) return;
  MAP.playing = true;
  if (MAP.month == null) MAP.month = 0;
  MAP.timer = setInterval(() => {
    MAP.month = (MAP.month + 1) % months.length;
    syncMapControls(); renderMap();
  }, 780);
  syncMapControls(); renderMap();
}
function stopPlay(){
  MAP.playing = false;
  if (MAP.timer){ clearInterval(MAP.timer); MAP.timer = null; }
  syncMapControls();
}

function hoverMap(e){
  const tip = $('#maptip');
  const g = e.target.closest && e.target.closest('g[data-cell]');
  if (!g){ tip.style.opacity = 0; return; }
  const cell = g.dataset.cell, met = METRICS[MAP.metric];
  const v = cellValue(cell, MAP.metric, MAP.month);
  const lawds = CELL_MEMBERS[cell] || [];
  // 병합 셀은 합친 값 하나만 보여주면 어느 쪽 이야기인지 알 수 없다. 구성 시군구를
  // 낱개로 같이 적는다.
  const parts = lawds.length < 2 ? '' :
    `<div class="parts">${lawds.map(l => {
      const one = oneRegionValue(l);
      const r = REGION_BY_CODE[l] || {};
      return `${esc(shortName(r.region || l))} ${one == null ? '–' : met.fmt(one)}`;
    }).join(' · ')}</div>`;
  tip.innerHTML = `<b>${esc(GEO.labels[cell] || cell)}</b><br>`
    + `${esc(met.label)} <b>${v == null ? '–' : met.fmt(v)}</b>${esc(met.unit)}`
    + (MAP.month == null ? '' : ` <span class="muted">(${esc((D.region_monthly.months||[])[MAP.month])})</span>`)
    + parts;
  const rect = $('#stage').getBoundingClientRect();
  tip.style.transform =
    `translate(${(e.clientX - rect.left)}px, ${(e.clientY - rect.top)}px) translate(-50%, -125%)`;
  tip.style.opacity = 1;
}

// 병합 셀 툴팁에서 구성 시군구를 따로 보여줄 때 쓴다.
function oneRegionValue(lawd){
  if (MAP.metric === 'budget') return budgetShare([lawd]);
  const rm = V().region_monthly || D.region_monthly;
  if (MAP.month != null && METRICS[MAP.metric].monthly && rm && rm.regions[lawd]){
    const e = rm.regions[lawd];
    return MAP.metric === 'count' ? e.count[MAP.month] : e.ppp[MAP.month];
  }
  const r = REGION_BY_CODE[lawd];
  return r ? r[MAP.metric] : null;
}

/* ---------- 헤더 / 푸터 ---------- */
function renderMeta(){
  const m = D.meta;
  $('#sub').textContent =
    `${D.kpi.period_from} ~ ${D.kpi.period_to} · ${nf(D.regions.length)}개 시군구 · `
    + `거래 ${nf(D.kpi.total_deals)}건`;
  $('#gen').textContent = `집계 기준일 ${m.analyzed_at}`
    + (m.api_calls ? ` · API 호출 ${nf(m.api_calls)}회` : '');
  $('#cancel-note').textContent = `이번 집계에서 ${nf(m.excluded_canceled)}건 제외`;
  $('#ref-note').textContent = `${D.kpi.ref_month} · 최신월 ${D.kpi.latest_month}은 잠정`;
  const cr = (D.cancel_rate || []).filter(x => x.rate_pct != null);
  if (cr.length >= 2){
    const a = cr[0], b = cr[cr.length-1];
    $('#cancel-series').textContent = `${a.ym} ${a.rate_pct}% → ${b.ym} ${b.rate_pct}%`;
  }
  $('#yoy-note').innerHTML = D.monthly.length >= 15
    ? '전년 동월 대비는 기준월과 그 12개월 전을 비교한 값이다.'
    : `현재 ${D.monthly.length}개월치만 수집해 전년 동월 대비는 산출할 수 없다. `
      + '기준월(최신월-2)의 12개월 전까지 있어야 하므로 <code>--months 15</code> 이상이 필요하다.';
  if (GEO){
    const el = $('#geo-note');
    el.hidden = false;
    el.innerHTML = `<b>지도 경계</b> ${esc(GEO.license || '')} · ${esc(GEO.vintage || '')}년 기준. `
      + esc(GEO.note || '');
  }
  if (m.synthetic){
    $('#banner').innerHTML = `<div class="banner"><b>합성 샘플 데이터다.</b> `
      + `실제 실거래가가 아니라 화면 검증용으로 생성한 가짜 값이므로, `
      + `어떤 판단 근거로도 쓰면 안 된다.</div>`;
  }
}

/* ---------- 테마 ---------- */
function initTheme(){
  const saved = localStorage.getItem('apt-theme') || 'dark';
  document.documentElement.dataset.theme = saved;
  const btn = $('#theme');
  const sync = () => btn.textContent =
    document.documentElement.dataset.theme === 'dark' ? '라이트 모드' : '다크 모드';
  sync();
  btn.onclick = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('apt-theme', next);
    sync();
    // 지도 색은 SVG 안에 값으로 박혀 있어 CSS 변수만 바뀌어서는 따라오지 않는다.
    if (tab === 'map') renderMap();
  };
}

function renderAll(){
  renderFilters(); renderKpi(); renderChart(); renderTable();
  if (tab === 'map') { renderMap(); renderMapDetail(); }
}

initTheme();
renderMeta();
renderDist();
renderRecordHighs();
$('#b-budget').value = BST.budget; $('#b-area').value = BST.area;
if (GEO){ $('#mb-budget').value = BST.budget; $('#mb-area').value = BST.area; }
renderBudget();
renderFloorPremium();
renderJeonse();
renderDealType();
renderSettlement();
renderParty();
renderAnomalies();
setupMap();
renderAll();

$('#chart-mode').querySelectorAll('button').forEach(b => b.onclick = () => {
  chartMode = b.dataset.mode;
  $('#chart-mode').querySelectorAll('button').forEach(x =>
    x.setAttribute('aria-pressed', String(x.dataset.mode === chartMode)));
  renderChart();
});

$('#tabs').querySelectorAll('.tab').forEach(b => b.onclick = () => switchTab(b.dataset.tab));
if (GEO){
  $('#b-tomap').onclick = e => { e.preventDefault(); MAP.metric = 'budget';
    switchTab('map'); syncMapControls(); renderMap();
    $('#map-card').scrollIntoView({behavior:'smooth', block:'start'}); };
} else {
  $('#b-tomap-wrap').hidden = true;
}
$('#csv').onclick = downloadCsv;
$('#q').oninput = e => { query = e.target.value.trim(); renderTable(); };
['#b-budget','#b-area'].forEach(s => $(s).oninput = () => {
  syncBudgetInputs('overview'); renderBudget(); if (tab === 'map') renderMap(); });
$('#b-region').oninput = renderBudget;
window.addEventListener('resize', renderChart);
</script>
</body>
</html>
"""


def render(analytics, out_path, boundaries=None):
    synthetic = analytics["meta"].get("synthetic")
    heading = "수도권 아파트 실거래가 대시보드"
    title = ("[샘플] " if synthetic else "") + heading

    # </script> 가 데이터 안에 있으면 스크립트 태그가 조기에 닫힌다.
    def embed(obj):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    html = (PAGE
            .replace("__TITLE__", title)
            .replace("__HEADING__", heading)
            .replace("__GEO__", embed(boundaries) if boundaries else "")
            .replace("__DATA__", embed(analytics)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def load_boundaries(path):
    """경계 파일이 없으면 지도만 빠지고 나머지는 그대로 나온다."""
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "live/index.html"
    geo_path = sys.argv[3] if len(sys.argv) > 3 else "data/boundaries.json"
    with open(src, encoding="utf-8") as f:
        analytics = json.load(f)
    geo = load_boundaries(geo_path)
    render(analytics, dst, boundaries=geo)
    print(f"대시보드 생성 -> {dst} ({os.path.getsize(dst)/1024:.0f}KB)"
          + ("" if geo else " · 경계 없음(지도 탭 비활성)"))


if __name__ == "__main__":
    main()
