#!/usr/bin/env python3
"""
집계 결과 -> 단일 HTML 대시보드

외부 CDN을 쓰지 않는다. 차트는 인라인 SVG를 바닐라 JS로 그리고, 데이터는 HTML 안에
JSON으로 심는다. 파일 하나만 열면 오프라인에서도 그대로 동작한다.

사용법:
  python build_apt_dashboard.py live/analytics.json live/index.html
"""
import json
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
  --shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.28);
}
html[data-theme="light"]{
  --bg:#eef3fa; --panel:#fff; --panel-2:#f4f7fc; --line:#dce5f2;
  --text:#16233a; --muted:#61728d; --accent:#2563eb; --accent-soft:#dbe8fe;
  --up:#d1483a; --down:#1d6fa8;
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
  flex-wrap:wrap;margin-bottom:22px}
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
.pline{fill:none;stroke:var(--up);stroke-width:2.2;stroke-linejoin:round}
.pline.prov{stroke-dasharray:5 4}
.pdot{fill:var(--up)}
.hit{fill:transparent;cursor:pointer}
.hit:hover~.hover-bg,.hit:hover{outline:none}
/* --- 테이블 --- */
.table-head{display:flex;justify-content:space-between;align-items:center;
  gap:12px;flex-wrap:wrap;margin-bottom:12px}
input[type=search]{background:var(--panel-2);border:1px solid var(--line);
  color:var(--text);border-radius:8px;padding:7px 12px;font:inherit;font-size:13.5px;
  min-width:190px}
input[type=search]:focus{outline:none;border-color:var(--accent)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:13.5px;
  font-variant-numeric:tabular-nums;white-space:nowrap}
th,td{padding:9px 11px;text-align:right;border-bottom:1px solid var(--line)}
th:nth-child(1),td:nth-child(1),th:nth-child(2),td:nth-child(2){text-align:left}
th{color:var(--muted);font-weight:600;font-size:12.5px;cursor:pointer;
  user-select:none;position:sticky;top:0;background:var(--panel);z-index:1}
th:hover{color:var(--text)}
th[aria-sort]{color:var(--accent)}
tbody tr:hover{background:var(--panel-2)}
td.name{font-weight:560}
.muted{color:var(--muted)}
/* --- 면적 분포 --- */
.dist{display:grid;gap:10px}
.dist-row{display:grid;grid-template-columns:92px 1fr 232px;gap:12px;align-items:center;
  font-size:13.5px}
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
  .dist-row{grid-template-columns:74px 1fr;grid-template-areas:"a b" "c c"}
  .dist-val{grid-area:c;text-align:left}
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

<div class="filters" id="filters"></div>

<section class="kpis" id="kpis"></section>

<section class="card">
  <div class="chart-head">
    <h2>월별 거래량 · 중위 평당가</h2>
    <div class="legend">
      <span><i style="background:var(--accent);opacity:.45"></i>거래건수</span>
      <span><i style="background:var(--up)"></i>중위 평당가(만원)</span>
      <span class="muted">옅은 구간 = 신고 지연 잠정치</span>
    </div>
  </div>
  <div id="chart"></div>
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
  <h2>전용면적 구간별 거래 비중 · 중위 평당가</h2>
  <div class="dist" id="dist"></div>
</section>

<footer>
  <div><b>출처</b> 국토교통부 아파트 매매 실거래가 (data.go.kr, RTMSDataSvcAptTrade)</div>
  <ul>
    <li>해제(취소) 거래는 집계에서 제외했다 — <span id="cancel-note"></span></li>
    <li>대표 단가는 <b>중위 평당가</b>다. 평균은 초고가 몇 건에 끌려가 지역 비교를 왜곡한다.</li>
    <li>실거래가는 계약일 기준 신고분이라, 최근 2개월은 신고 지연으로 거래량이 과소 집계된다(잠정치).</li>
    <li><b>증감률의 기준월은 최신월이 아니라 마지막 확정월</b>(<span id="ref-note"></span>)이다.
        잠정치인 최신월을 확정된 전월·전년동월과 맞대면, 실제로 줄지 않았는데도 거래량이
        급감한 것처럼 보이기 때문이다.</li>
    <li>전용면적이 없는 건은 거래량에는 포함하되 단가 계산에서는 제외했다.</li>
    <li id="yoy-note"></li>
  </ul>
  <div style="margin-top:10px" id="gen"></div>
</footer>

</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
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

/* ---------- 상태 ---------- */
let sido = 'ALL';
let sortKey = 'median_ppp', sortDir = -1;
let query = '';

function monthlyFor(s){
  if (s === 'ALL') return D.monthly;
  const e = D.sido.find(x => x.sido === s);
  return e ? e.monthly : [];
}
function overallFor(s){
  if (s === 'ALL') return {count:D.kpi.total_deals, median_ppp:D.kpi.median_ppp,
                           median_amount:D.kpi.median_amount, avg_area:D.kpi.avg_area};
  const e = D.sido.find(x => x.sido === s);
  return e ? e : {count:0, median_ppp:null, median_amount:null, avg_area:null};
}
function regionsFor(s){
  const rows = s === 'ALL' ? D.regions : D.regions.filter(r => r.sido === s);
  return query ? rows.filter(r => r.region.includes(query)) : rows;
}
function change(cur, prev){
  if (prev == null || !prev || cur == null) return null;
  return (cur - prev) / prev * 100;
}

/* ---------- 필터 ---------- */
function renderFilters(){
  const opts = [['ALL','수도권 전체'], ...D.sido.map(s => [s.sido, s.sido])];
  $('#filters').innerHTML = opts.map(([v,label]) =>
    `<button class="chip" data-sido="${esc(v)}" aria-pressed="${v===sido}">${esc(label)}</button>`
  ).join('');
  $('#filters').querySelectorAll('.chip').forEach(b =>
    b.onclick = () => { sido = b.dataset.sido; renderAll(); });
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
    {label:`거래건수 (${D.kpi.period_from} ~ ${D.kpi.period_to})`,
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

/* ---------- 차트 ---------- */
function renderChart(){
  const ms = monthlyFor(sido);
  const W = 860, H = 300, ml = 52, mr = 58, mt = 16, mb = 42;
  const iw = W - ml - mr, ih = H - mt - mb;
  if (!ms.length){ $('#chart').innerHTML = '<p class="sub">데이터 없음</p>'; return; }

  const maxCount = Math.max(...ms.map(m => m.count), 1);
  const ppps = ms.map(m => m.median_ppp).filter(v => v != null);
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

/* ---------- 랭킹 테이블 ---------- */
const COLS = [
  {k:'rank',          t:'#',          f:r => r.rank},
  {k:'region',        t:'지역',        f:r => `<span class="name">${esc(r.region)}</span>`},
  {k:'median_ppp',    t:'중위 평당가',   f:r => nf(r.median_ppp)},
  {k:'median_amount', t:'중위 거래가',   f:r => fmtAmount(r.median_amount)},
  {k:'count',         t:'거래건수',     f:r => nf(r.count)},
  {k:'share_pct',     t:'비중',        f:r => r.share_pct.toFixed(1) + '%'},
  {k:'avg_area',      t:'평균 전용',    f:r => (r.avg_area ?? '–') + '㎡'},
  {k:'ref_count',     t:'기준월 건수',   f:r => nf(r.ref_count)},
  {k:'mom_count_pct', t:'전월비 건수',   f:r => pct(r.mom_count_pct)},
  {k:'mom_ppp_pct',   t:'전월비 평당가', f:r => pct(r.mom_ppp_pct)},
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
                '평균전용(㎡)','기준월건수','전월비건수(%)','전월비평당가(%)'];
  const body = rows.map(r => [r.rank, r.region, r.median_ppp, r.median_amount, r.count,
    r.share_pct, r.avg_area, r.ref_count, r.mom_count_pct, r.mom_ppp_pct]
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
  $('#yoy-note').innerHTML = D.monthly.length >= 15
    ? '전년 동월 대비는 기준월과 그 12개월 전을 비교한 값이다.'
    : `현재 ${D.monthly.length}개월치만 수집해 전년 동월 대비는 산출할 수 없다. `
      + '기준월(최신월-2)의 12개월 전까지 있어야 하므로 <code>--months 15</code> 이상이 필요하다.';
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
  };
}

function renderAll(){ renderFilters(); renderKpi(); renderChart(); renderTable(); }

initTheme();
renderMeta();
renderDist();
renderAll();
$('#csv').onclick = downloadCsv;
$('#q').oninput = e => { query = e.target.value.trim(); renderTable(); };
window.addEventListener('resize', renderChart);
</script>
</body>
</html>
"""


def render(analytics, out_path):
    synthetic = analytics["meta"].get("synthetic")
    heading = "수도권 아파트 실거래가 대시보드"
    title = ("[샘플] " if synthetic else "") + heading
    # </script> 가 데이터 안에 있으면 스크립트 태그가 조기에 닫힌다.
    payload = json.dumps(analytics, ensure_ascii=False, separators=(",", ":")) \
        .replace("</", "<\\/")

    html = (PAGE
            .replace("__TITLE__", title)
            .replace("__HEADING__", heading)
            .replace("__DATA__", payload))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "live/index.html"
    with open(src, encoding="utf-8") as f:
        analytics = json.load(f)
    render(analytics, dst)
    import os
    print(f"대시보드 생성 -> {dst} ({os.path.getsize(dst)/1024:.0f}KB)")


if __name__ == "__main__":
    main()
