#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_board.py —— 公司价值判定系统 · 自包含可视化看板生成器
================================================================================
只做「展示」：把 core/ 与 dataio/ 的真实运行结果渲染成一个**离线可开**的 HTML。

- 数据：本层不写 SQL，一律走 dataio/astock.py（只读 mode=ro）；算法一律走 core/。
- 产物：单文件 valuation_board.html（数据内嵌、图表原生 JS/SVG、无外网 CDN）。
- 口径：与 quality_value_screener_v2.py 完全一致（质量分/估值分/错配度/综合分），
        检验小卡复用 mispricing_screener_v2 的 testing.run_predictive_test。
- 免责：研究方法论原型，不构成投资建议；所有数字来自真实运行。

用法：
  py -3.12 board/make_board.py                       # 用默认库，出最新快照的看板
  py -3.12 board/make_board.py --vdate 2026-10-09    # 换快照日重出
  py -3.12 board/make_board.py --no-test             # 跳过 IC 检验（省时间）
  py -3.12 board/make_board.py --hist-db <valuation_hist.db>   # 追加「自身历史分位」小节
"""
from __future__ import annotations
import argparse
import datetime as _dt
import html
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from core import percentile as core_percentile   # noqa: E402
from core import quality, stats, testing, valuation  # noqa: E402
from dataio import astock, paths  # noqa: E402

R_DISCOUNT = 0.08
MIN_PEER_N = 5
QUALITY_GATE = 50.0
TOP_N = 15
SCATTER_MAX = 6000          # 散点最多画多少只（超出按估值分分层抽样，保持形状）


# ------------------------------------------------------------------ 小工具
def _f(x):
    """有限数 → float；否则 None。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _r(x, n=4):
    v = _f(x)
    return None if v is None else round(v, n)


# ------------------------------------------------------------------ 计算
def compute_rows(cur, vdate, fperiod):
    """跑与 quality_value_screener_v2 相同的口径，返回 (rows, weights, ann, gate_thresh)。"""
    val = astock.load_valuation_snapshot(cur, vdate)
    fund = astock.load_financials(cur, fperiod)
    shares = astock.load_shares(cur)
    ind_map = astock.load_industry_map(cur)
    rows = quality.build_universe(val, fund, shares, ind_map, exclude_st=True)
    weights = quality.DEFAULT_Q_WEIGHTS
    ann = valuation.ann_factor_for_period(fperiod)
    quality.score_quality(rows, weights)
    valuation.compute_valuation_scores(rows, r_discount=R_DISCOUNT, ann=ann,
                                       min_peer=MIN_PEER_N, neutral=False)
    gate_thresh = quality.composite(rows, QUALITY_GATE)
    return rows, weights, ann, gate_thresh


def pick_lists(rows, top_n):
    """最便宜 / 最贵 Top 榜：只在过质量关且错配度有效的池内，按错配度升/降序。"""
    pool = [r for r in rows.values()
            if r.get("passed_gate") and np.isfinite(_nan(r.get("mispricing")))]
    pool.sort(key=lambda r: r["mispricing"])
    cheap = pool[:top_n]
    rich = pool[-top_n:][::-1] if len(pool) > top_n else pool[::-1]
    return pool, cheap, rich


def _nan(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def build_scatter(rows, max_pts):
    """(V, Q, code, name, mis) 点集；超出上限时按估值分分层抽样。"""
    pts = []
    for r in rows.values():
        q, v = _f(r.get("quality_score")), _f(r.get("valuation_score"))
        if q is None or v is None:
            continue
        pts.append([v, q, r.get("code"), r.get("name") or "", _r(r.get("mispricing"), 4)])
    pts.sort(key=lambda p: p[0])
    if len(pts) > max_pts:
        idx = np.linspace(0, len(pts) - 1, max_pts).round().astype(int)
        pts = [pts[i] for i in idx]
    return pts


def build_hist(rows, nbins=44):
    """全市场错配度分布直方图（含最便宜/最贵榜位标记）。"""
    vals = np.array([_nan(r.get("mispricing")) for r in rows.values()], dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None
    lo, hi = float(np.percentile(vals, 0.5)), float(np.percentile(vals, 99.5))
    if hi <= lo:
        hi = lo + 1e-6
    edges = np.linspace(lo, hi, nbins + 1)
    counts, edges = np.histogram(np.clip(vals, lo, hi), bins=edges)
    centers = [(edges[i] + edges[i + 1]) / 2.0 for i in range(len(counts))]
    return dict(lo=lo, hi=hi,
                centers=[round(c, 4) for c in centers],
                counts=[int(c) for c in counts],
                n=int(vals.size), median=round(float(np.median(vals)), 4),
                p25=round(float(np.percentile(vals, 25)), 4),
                p75=round(float(np.percentile(vals, 75)), 4))


def hist_percentiles(hist_db, min_days, lookback):
    """可选：自身历史估值分位（读 valuation_hist.db）。不存在则返回 {}。"""
    if not hist_db or not os.path.exists(hist_db):
        return {}
    con = paths.open_ro(hist_db)
    try:
        return core_percentile.historical_percentiles(astock.iter_valuation_hist(con.cursor()),
                                                      min_days=min_days, lookback=lookback)
    finally:
        con.close()


def run_ic(cur):
    """IC / t / Bonferroni 检验（真实运行 core.testing）。"""
    dates = astock.load_trade_dates(cur, astock.MIN_ROWS_PER_DAY)
    if len(dates) < 40:
        return None
    codes, dates, M = astock.load_kline(cur, dates)
    fund = astock.load_financials_pit(cur)
    idx = astock.load_index_series(cur, dates)
    return testing.run_predictive_test(M, dates, codes, fund, idx,
                                       horizons=testing.HORIZONS, rebal_days=testing.REBAL_DAYS,
                                       cost=testing.COST_ROUND_TRIP, seed=testing.SEED,
                                       n_trials=testing.N_TRIALS)


# ------------------------------------------------------------------ 渲染用结构
def _stock_dict(r):
    return dict(code=r["code"], name=r.get("name") or "", industry=r.get("industry") or "-",
                price=_r(r.get("price"), 2), pe=_r(r.get("pe"), 1),
                q=_r(r.get("quality_score"), 1), v=_r(r.get("valuation_score"), 1),
                mis=_r(r.get("mispricing"), 3), comp=_r(r.get("composite_score"), 1))


def ic_rows(card):
    rows = []
    if not card:
        return rows
    for row in card["rows"]:
        if row["n"] == 0:
            rows.append(dict(proxy=row["proxy"], h=row["h"], n=0, ic=None, t=None,
                             lo=None, hi=None, net=None, alpha=None, at=None))
            continue
        rows.append(dict(proxy=row["proxy"], h=row["h"], n=row["n"],
                         ic=_r(row["ic_mean"], 4), t=_r(row["ic_t"], 2),
                         lo=_r(row["lo"], 3), hi=_r(row["hi"], 3),
                         net=_r(row["net"], 4), alpha=_r(row["alpha"], 4), at=_r(row["a_t"], 2)))
    return rows


# ------------------------------------------------------------------ 静态 HTML 片段
def esc(s):
    return html.escape("" if s is None else str(s))


def _bar(pct, cls):
    """0~100 的分数条。"""
    w = 0 if pct is None else max(0.0, min(100.0, float(pct)))
    return '<div class="bar"><span class="%s" style="width:%.1f%%"></span></div>' % (cls, w)


def _mis_chip(mis):
    if mis is None:
        return '<span class="chip na">NA</span>'
    cls = "neg" if mis < 0 else "pos"
    tag = "便宜" if mis < 0 else "偏贵"
    return '<span class="chip %s">%+.3f <i>%s</i></span>' % (cls, mis, tag)


def stock_table(items, cap):
    h = ['<table class="rank"><thead><tr>',
         '<th>#</th><th>代码</th><th>名称</th><th>行业</th>',
         '<th class="num">价格</th><th class="num">PE</th>',
         '<th>质量分</th><th>估值分</th><th class="num">错配度</th></tr></thead><tbody>']
    for i, r in enumerate(items, 1):
        d = _stock_dict(r)
        h.append("<tr>")
        h.append("<td class='rk'>%d</td><td class='code'>%s</td><td>%s</td><td class='ind'>%s</td>"
                 % (i, esc(d["code"]), esc(d["name"]), esc(d["industry"])))
        h.append("<td class='num'>%s</td>" % ("—" if d["price"] is None else "%.2f" % d["price"]))
        h.append("<td class='num'>%s</td>" % ("—" if d["pe"] is None else "%.1f" % d["pe"]))
        h.append("<td class='qw'>%s<span class='qv'>%s</span></td>"
                 % (_bar(d["q"], "bq"), "—" if d["q"] is None else "%.0f" % d["q"]))
        h.append("<td class='qw'>%s<span class='qv'>%s</span></td>"
                 % (_bar(d["v"], "bv"), "—" if d["v"] is None else "%.0f" % d["v"]))
        h.append("<td class='num'>%s</td>" % _mis_chip(d["mis"]))
        h.append("</tr>")
    h.append("</tbody></table>")
    h.append('<p class="cap">%s</p>' % cap)
    return "\n".join(h)


def ic_table(card, rows):
    if not card:
        return '<p class="muted">检验未运行（--no-test）。</p>'
    h = ['<table class="ic"><thead><tr>',
         '<th>因子</th><th class="num">期限(交易日)</th><th class="num">IC 均值</th>',
         '<th class="num">IC t 值</th><th class="num">IC 95%% 自举区间</th>',
         '<th class="num">Q5−Q1 扣费后</th><th class="num">alpha t</th><th class="num">样本 n</th>',
         '</tr></thead><tbody>']
    for row in rows:
        passed = (row["t"] is not None and abs(row["t"]) >= card["thr"])
        cls = "pass" if passed else ""
        if row["n"] == 0:
            cells = ("<td colspan=7 class='muted'>样本不足（该期限非重叠样本为 0）</td>",)
            h.append("<tr class='%s'><td>%s</td><td class='num'>%d</td>%s</tr>"
                     % (cls, esc(row["proxy"]), row["h"], cells[0]))
            continue
        ci = "—" if row["lo"] is None else "[%+.3f, %+.3f]" % (row["lo"], row["hi"])
        h.append("<tr class='%s'>" % cls)
        h.append("<td>%s</td>" % esc(row["proxy"]))
        h.append("<td class='num'>%d</td>" % row["h"])
        h.append("<td class='num'>%s</td>" % ("—" if row["ic"] is None else "%+.4f" % row["ic"]))
        h.append("<td class='num'><b>%s</b>%s</td>"
                 % ("—" if row["t"] is None else "%+.2f" % row["t"],
                    "" if not passed else " √"))
        h.append("<td class='num mono'>%s</td>" % ci)
        h.append("<td class='num'>%s</td>" % ("—" if row["net"] is None else "%+.4f" % row["net"]))
        h.append("<td class='num'>%s</td>" % ("—" if row["at"] is None else "%+.2f" % row["at"]))
        h.append("<td class='num'>%d</td>" % row["n"])
        h.append("</tr>")
    h.append("</tbody></table>")
    return "\n".join(h)


def pct_table(rows, hists, top=12):
    if not hists:
        return ""
    hit = []
    for r in rows.values():
        h = hists.get(r.get("code"))
        if h:
            hit.append((h["cheap"], r, h))
    if not hit:
        return ""
    hit.sort(key=lambda t: t[0], reverse=True)
    line = ['<table class="rank"><thead><tr><th>#</th><th>代码</th><th>名称</th><th>行业</th>',
            '<th class="num">PE</th><th class="num">PE分位</th><th class="num">PB分位</th>',
            '<th class="num">便宜度</th><th class="num">历史天数</th></tr></thead><tbody>']
    for i, (cheap, r, h) in enumerate(hit[:top], 1):
        line.append("<tr><td class='rk'>%d</td><td class='code'>%s</td><td>%s</td><td class='ind'>%s</td>"
                    "<td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                    "<td class='num'><b>%.1f</b></td><td class='num'>%d</td></tr>" % (
                        i, esc(r["code"]), esc(r.get("name")), esc(r.get("industry") or "-"),
                        "—" if h.get("pe") is None else "%.1f" % h["pe"],
                        "—" if h.get("pe_pct") is None else "%.0f" % h["pe_pct"],
                        "—" if h.get("pb_pct") is None else "%.0f" % h["pb_pct"],
                        cheap, h["n"]))
    line.append("</tbody></table>")
    line.append('<p class="cap">便宜度 = mean(100 − 自身历史分位)，>50 偏便宜；历史≥250 日的票才计入。'
                '覆盖 %d 只（真实纵向分位，数据源 valuation_hist.db）。</p>' % len(hit))
    return "\n".join(line)


# ------------------------------------------------------------------ 页面模板
TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>公司价值判定系统 · 可视化看板</title>
<style>
:root{
  --bg:#0f1420; --panel:#172033; --panel2:#1d2942; --line:#2a3category;
  --line:#2a3752; --tx:#e7ecf5; --tx2:#9fb0cc; --acc:#5cc8ff;
  --cheap:#37c98b; --rich:#ff6b6b; --warn:#ffcc66; --mute:#7a8aa8;
}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(180deg,#0d1220,#0f1420 40%,#0c101b);
  color:var(--tx);font-family:"Microsoft YaHei","PingFang SC","Hiragino Sans GB",
  "Noto Sans CJK SC","Source Han Sans SC",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
header.top{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;justify-content:space-between;
  border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:22px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:.5px}
.sub{color:var(--tx2);font-size:13.5px}
.badges{display:flex;flex-wrap:wrap;gap:8px}
.badge{background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:5px 12px;font-size:12.5px;color:var(--tx2)}
.badge b{color:var(--tx);font-weight:600}
section{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:20px 20px 16px;margin:16px 0;box-shadow:0 8px 26px rgba(0,0,0,.22)}
section h2{font-size:17px;margin:0 0 4px}
section .hint{color:var(--tx2);font-size:12.5px;margin:0 0 14px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.card{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px}
.card h3{font-size:14px;margin:0 0 10px;display:flex;align-items:center;gap:8px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.dot.c{background:var(--cheap)} .dot.r{background:var(--rich)}
table{border-collapse:collapse;width:100%;font-size:12.8px}
table th,table td{padding:6px 8px;border-bottom:1px solid #23304a;text-align:left;white-space:nowrap}
table th{color:var(--tx2);font-weight:600;font-size:11.8px;position:sticky;top:0}
table td.num,table th.num{text-align:right;font-variant-numeric:tabular-nums}
td.rk{color:var(--tx2)} td.code{font-family:ui-monospace,Consolas,monospace;color:var(--acc)}
td.ind{color:var(--tx2);max-width:120px;overflow:hidden;text-overflow:ellipsis}
.qw{min-width:104px} .qv{float:right;color:var(--tx2);margin-left:6px;font-variant-numeric:tabular-nums}
.bar{display:inline-block;vertical-align:middle;width:64px;height:8px;border-radius:5px;
  background:#26334d;overflow:hidden}
.bar span{display:block;height:100%;border-radius:5px}
.bar .bq{background:linear-gradient(90deg,#3d7dff,#5cc8ff)}
.bar .bv{background:linear-gradient(90deg,#37c98b,#9be86f)}
.chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11.6px;
  font-variant-numeric:tabular-nums}
.chip.neg{background:rgba(55,201,139,.16);color:var(--cheap);border:1px solid rgba(55,201,139,.4)}
.chip.pos{background:rgba(255,107,107,.16);color:var(--rich);border:1px solid rgba(255,107,107,.4)}
.chip.na{background:#26334d;color:var(--mute)}
.chip i{font-style:normal;opacity:.8;font-size:10.6px;margin-left:3px}
p.cap{color:var(--mute);font-size:11.6px;margin:8px 2px 0}
.muted{color:var(--mute)}
.chartwrap{position:relative}
svg{display:block;width:100%;height:auto}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:10px 2px 0;font-size:12px;color:var(--tx2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
#tip{position:absolute;pointer-events:none;background:#0b1018;border:1px solid var(--acc);
  border-radius:8px;padding:7px 10px;font-size:12px;color:var(--tx);opacity:0;transition:opacity .08s;
  white-space:nowrap;z-index:5;box-shadow:0 6px 20px rgba(0,0,0,.5)}
#tip b{color:var(--acc)}
.ic td.pass,.ic tr.pass{background:rgba(55,201,139,.1)}
.ic .mono{font-family:ui-monospace,Consolas,monospace;font-size:11.8px}
.verdict{margin-top:12px;border-radius:10px;padding:12px 14px;font-size:13px;
  background:rgba(255,204,102,.1);border:1px solid rgba(255,204,102,.35);color:#ffd98a}
.verdict b{color:#ffe6a8}
footer{color:var(--mute);font-size:12px;margin-top:22px;border-top:1px solid var(--line);padding-top:14px}
footer .fine{margin-top:6px}
.kv{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.kv .badge{background:var(--panel2)}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <h1>公司价值判定系统 · 可视化看板</h1>
      <div class="sub">质量分 × 估值分 × 错配度 → 便宜/贵 Top 榜 · 四象限 · 分布 · 预测力检验</div>
    </div>
    <div class="badges" id="badges"></div>
  </header>

  <section>
    <h2>1. 最便宜 / 最贵 Top 榜</h2>
    <p class="hint">在<strong>过质量关</strong>的池内，按<strong>错配度</strong>排序（越小越便宜、越大越贵）。
      质量分/估值分均为 0~100 的池内百分位，<strong>估值分越高越便宜</strong>。</p>
    <div class="grid2">
      <div class="card"><h3><span class="dot c"></span>最便宜 Top <span id="ncheap"></span></h3><div id="tblCheap"></div></div>
      <div class="card"><h3><span class="dot r"></span>最贵 Top <span id="nrich"></span></h3><div id="tblRich"></div></div>
    </div>
  </section>

  <section>
    <h2>2. 质量 × 估值 四象限</h2>
    <p class="hint">X 轴＝估值分（左＝便宜，右＝贵）；Y 轴＝质量分（越上越好）。每点＝一只个股；
      绿点标记最便宜 Top 榜。虚线为池内中位（50）。</p>
    <div class="chartwrap" id="scatterWrap">
      <svg id="scatter" viewBox="0 0 900 560" preserveAspectRatio="xMidYMid meet"></svg>
      <div id="tip"></div>
    </div>
    <div class="legend">
      <span><i class="sw" style="background:#37c98b"></i>便宜又好</span>
      <span><i class="sw" style="background:#3d7dff"></i>好但贵</span>
      <span><i class="sw" style="background:#ffcc66"></i>便宜但质量弱</span>
      <span><i class="sw" style="background:#ff6b6b"></i>贵而差</span>
      <span><i class="sw" style="background:#fff;border-radius:50%"></i>最便宜 Top</span>
    </div>
  </section>

  <section>
    <h2>3. 错配度分布（全市场）</h2>
    <p class="hint">横轴＝错配度（0 中性，&lt;0 偏便宜、&gt;0 偏贵）；柱高＝个股数量。
      竖线标出当前最便宜榜首位与中性 0 的位置。</p>
    <div class="chartwrap" id="histWrap">
      <svg id="hist" viewBox="0 0 900 360" preserveAspectRatio="xMidYMid meet"></svg>
      <div id="tip2"></div>
    </div>
  </section>

  <section>
    <h2>4. 预测力检验小卡（IC / t / Bonferroni）</h2>
    <p class="hint">横截面 rank IC + 五分组（Q5 最便宜 − Q1 最贵，扣往返成本）+ 对市场因子回归取 alpha。
      「√」表示 |t| 达到 Bonferroni 校正阈值。</p>
    <div id="icBlock"></div>
    <div class="verdict" id="verdict"></div>
  </section>

  __PCT_SECTION__

  <footer>
    <div><strong>口径</strong>：研究原型，不构成投资建议；基准＝选股日收盘。
      质量分＝5 成分（roe/gross_margin/net_margin/rev_yoy/net_yoy）加权池内百分位；
      估值分＝E/P、B/P、S/P、错配四信号池内百分位（高＝便宜）；
      错配度＝0.5·z(行业PE缺口)+0.5·z(零增长 DCF 缺口)，&gt;0 偏贵；
      综合分＝0.5·z(质量)+0.5·z(估值)，仅过质量关池内计算。</div>
    <div class="fine" id="foot"></div>
  </footer>
</div>

<script>
const DATA = /*__DATA__*/;
const $ = (id)=>document.getElementById(id);
const fmt = (x,n=2)=> (x===null||x===undefined)?"—":(+x).toFixed(n);

/* ---- 顶部徽标 ---- */
(function(){
  const m = DATA.meta;
  const bs = [
    ["快照日", m.vdate], ["财务期", m.fperiod], ["EPS年化", "×"+m.ann],
    ["评分股票池", m.n_rows+" 只"], ["过质量关", m.n_gated+" 只"],
    ["质量关阈值", m.gate.toFixed(1)], ["错配度样本", m.hist.n+" 只"],
  ];
  $("badges").innerHTML = bs.map(b=>`<span class="badge">${b[0]} <b>${b[1]}</b></span>`).join("");
  $("ncheap").textContent = "15"; $("nrich").textContent = "15";
})();

/* ---- 静态表格 ---- */
(function(){
  function rowHTML(i,r){
    const bar=(p,cl)=>`<div class="bar"><span class="${cl}" style="width:${p===null?0:Math.max(0,Math.min(100,p))}%"></span></div>`;
    const chip = r.mis===null ? `<span class="chip na">NA</span>`
      : `<span class="chip ${r.mis<0?'neg':'pos'}">${r.mis>0?'+':''}${r.mis.toFixed(3)} <i>${r.mis<0?'便宜':'偏贵'}</i></span>`;
    return `<tr>
      <td class="rk">${i}</td><td class="code">${r.code}</td><td>${r.name}</td><td class="ind">${r.industry}</td>
      <td class="num">${r.price===null?"—":r.price.toFixed(2)}</td>
      <td class="num">${r.pe===null?"—":r.pe.toFixed(1)}</td>
      <td class="qw">${bar(r.q,'bq')}<span class="qv">${r.q===null?"—":Math.round(r.q)}</span></td>
      <td class="qw">${bar(r.v,'bv')}<span class="qv">${r.v===null?"—":Math.round(r.v)}</span></td>
      <td class="num">${chip}</td></tr>`;
  }
  const th = `<tr><th>#</th><th>代码</th><th>名称</th><th>行业</th><th class="num">价格</th>
    <th class="num">PE</th><th>质量分</th><th>估值分</th><th class="num">错配度</th></tr>`;
  const t=(items)=>`<table class="rank"><thead>${th}</thead><tbody>${items.map((r,i)=>rowHTML(i+1,r)).join("")}</tbody></table>`;
  $("tblCheap").innerHTML = t(DATA.top_cheap);
  $("tblRich").innerHTML = t(DATA.top_rich);
})();

/* ---- 四象限散点 ---- */
(function(){
  const svg=$("scatter"), W=900,H=560, m={l:64,r:24,t:26,b:52};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const cls=["#ff6b6b","#ffcc66","#3d7dff","#37c98b"]; // 象限底色
  const X=(v)=>m.l+(1-v/100)*iw;      // 估值分高(便宜)在左
  const Y=(q)=>m.t+(1-q/100)*ih;      // 质量分高在上
  let s="";
  // 象限底色
  const xm=X(50), ym=Y(50);
  s+=`<rect x="${X(100)}" y="${m.t}" width="${xm-X(100)}" height="${ym-m.t}" fill="rgba(55,201,139,.07)"/>`;
  s+=`<rect x="${xm}" y="${m.t}" width="${X(0)-xm}" height="${ym-m.t}" fill="rgba(61,125,255,.07)"/>`;
  s+=`<rect x="${X(100)}" y="${ym}" width="${xm-X(100)}" height="${Y(0)-ym}" fill="rgba(255,204,102,.07)"/>`;
  s+=`<rect x="${xm}" y="${ym}" width="${X(0)-xm}" height="${Y(0)-ym}" fill="rgba(255,107,107,.07)"/>`;
  // 轴线
  s+=`<line x1="${X(100)}" y1="${Y(0)}" x2="${X(0)}" y2="${Y(0)}" stroke="#2a3752"/>`;
  s+=`<line x1="${X(100)}" y1="${m.t}" x2="${X(100)}" y2="${Y(0)}" stroke="#2a3752"/>`;
  s+=`<line x1="${xm}" y1="${m.t}" x2="${xm}" y2="${Y(0)}" stroke="#3a4a6b" stroke-dasharray="4 4"/>`;
  s+=`<line x1="${X(100)}" y1="${ym}" x2="${X(0)}" y2="${ym}" stroke="#3a4a6b" stroke-dasharray="4 4"/>`;
  // 象限文字
  const q=[["便宜又好",X(100)+14,m.t+22,"#9be86f"],
           ["好但贵",xm+14,m.t+22,"#8fb4ff"],
           ["便宜但质量弱",X(100)+14,Y(0)-12,"#ffd98a"],
           ["贵而差",xm+14,Y(0)-12,"#ff9a9a"]];
  q.forEach(t=>{s+=`<text x="${t[1]}" y="${t[2]}" fill="${t[3]}" font-size="14" opacity=".85">${t[0]}</text>`;});
  // 刻度
  for(let v=0;v<=100;v+=25){
    s+=`<text x="${X(v)}" y="${Y(0)+20}" fill="#7a8aa8" font-size="11" text-anchor="middle">${v}</text>`;
    s+=`<text x="${X(100)}" y="${Y(v)+4}" fill="#7a8aa8" font-size="11" text-anchor="end">${v}</text>`;
  }
  s+=`<text x="${m.l+iw/2}" y="${H-14}" fill="#9fb0cc" font-size="12.5" text-anchor="middle">估值分　←　便宜　　　　　　贵　→</text>`;
  s+=`<text x="16" y="${m.t+ih/2}" fill="#9fb0cc" font-size="12.5" text-anchor="middle" transform="rotate(-90 16 ${m.t+ih/2})">质量分　（越高越好）</text>`;
  // 点
  const P=DATA.scatter;
  for(let i=0;i<P.length;i++){
    const v=P[i][0], qq=P[i][1];
    let col;
    if(v>=50&&qq>=50)col="#37c98b"; else if(v<50&&qq>=50)col="#3d7dff";
    else if(v>=50&&qq<50)col="#ffcc66"; else col="#ff6b6b";
    s+=`<circle cx="${X(v).toFixed(1)}" cy="${Y(qq).toFixed(1)}" r="1.7" fill="${col}" opacity=".5"/>`;
  }
  // 最便宜 Top 高亮
  DATA.top_cheap.forEach(r=>{
    if(r.v===null||r.q===null)return;
    s+=`<circle cx="${X(r.v).toFixed(1)}" cy="${Y(r.q).toFixed(1)}" r="5" fill="none" stroke="#fff" stroke-width="1.6"/>`;
  });
  svg.innerHTML=s;
  // tooltip
  const tip=$("tip");
  svg.addEventListener("mousemove",(e)=>{
    const rect=svg.getBoundingClientRect();
    const sx=(e.clientX-rect.left)/rect.width*W, sy=(e.clientY-rect.top)/rect.height*H;
    let best=-1,bd=1e9;
    for(let i=0;i<P.length;i++){
      const dx=X(P[i][0])-sx, dy=Y(P[i][1])-sy, d=dx*dx+dy*dy;
      if(d<bd){bd=d;best=i;}
    }
    if(best>=0&&bd<90){
      const p=P[best];
      tip.innerHTML=`<b>${p[2]}</b> ${p[3]}<br>质量分 ${p[1].toFixed(1)} · 估值分 ${p[0].toFixed(1)}<br>`+
                    `错配度 ${p[4]===null?"—":(p[4]>0?"+":"")+p[4].toFixed(3)}`;
      tip.style.left=(e.clientX-rect.left+14)+"px";
      tip.style.top=(e.clientY-rect.top+10)+"px";
      tip.style.opacity=1;
    } else tip.style.opacity=0;
  });
  svg.addEventListener("mouseleave",()=>{tip.style.opacity=0;});
})();

/* ---- 直方图 ---- */
(function(){
  const H=DATA.hist;
  if(!H){$("hist").innerHTML=""; return;}
  const svg=$("hist"), W=900,HH=360, m={l:48,r:20,t:20,b:48};
  const iw=W-m.l-m.r, ih=HH-m.t-m.b;
  const n=H.counts.length, maxc=Math.max(...H.counts);
  const bw=iw/n;
  const X=(v)=>m.l+(v-H.lo)/(H.hi-H.lo)*iw;
  const Y=(c)=>m.t+(1-c/maxc)*ih;
  let s="";
  s+=`<line x1="${m.l}" y1="${Y(0)}" x2="${m.l+iw}" y2="${Y(0)}" stroke="#2a3752"/>`;
  for(let i=0;i<n;i++){
    const x=m.l+i*bw, c=H.counts[i], y=Y(c), h=Y(0)-y;
    const col=H.centers[i]<0?"#37c98b":"#ff6b6b";
    s+=`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw-1).toFixed(1)}" height="${Math.max(0,h).toFixed(1)}" fill="${col}" opacity=".62"/>`;
  }
  // 0 线
  if(0>=H.lo&&0<=H.hi){
    const x0=X(0);
    s+=`<line x1="${x0}" y1="${m.t}" x2="${x0}" y2="${Y(0)}" stroke="#9fb0cc" stroke-dasharray="4 4"/>`;
    s+=`<text x="${x0}" y="${m.t-6}" fill="#9fb0cc" font-size="11" text-anchor="middle">中性 0</text>`;
  }
  // 最便宜榜首位
  const rk=DATA.top_cheap[0];
  if(rk&&rk.mis!==null&&rk.mis>=H.lo&&rk.mis<=H.hi){
    const xr=X(rk.mis);
    s+=`<line x1="${xr}" y1="${m.t}" x2="${xr}" y2="${Y(0)}" stroke="#37c98b" stroke-width="1.6"/>`;
    s+=`<circle cx="${xr}" cy="${m.t+8}" r="4" fill="#37c98b"/>`;
    s+=`<text x="${xr+6}" y="${m.t+12}" fill="#37c98b" font-size="11.5">最便宜榜首 ${rk.code} ${rk.name}（${rk.mis.toFixed(3)}）</text>`;
  }
  // 轴刻度
  for(let v=Math.ceil(H.lo*10)/10; v<=H.hi+1e-9; v+=0.2){
    const x=X(v);
    s+=`<line x1="${x}" y1="${Y(0)}" x2="${x}" y2="${Y(0)+5}" stroke="#3a4a6b"/>`;
    s+=`<text x="${x}" y="${Y(0)+20}" fill="#7a8aa8" font-size="11" text-anchor="middle">${v.toFixed(1)}</text>`;
  }
  s+=`<text x="${m.l+iw/2}" y="${HH-12}" fill="#9fb0cc" font-size="12.5" text-anchor="middle">错配度　（&lt;0 便宜　|　&gt;0 偏贵）</text>`;
  s+=`<text x="14" y="${m.t+ih/2}" fill="#9fb0cc" font-size="12" text-anchor="middle" transform="rotate(-90 14 ${m.t+ih/2})">个股数量</text>`;
  svg.innerHTML=s;
  // tooltip
  const tip=$("tip2");
  svg.addEventListener("mousemove",(e)=>{
    const rect=svg.getBoundingClientRect();
    const sx=(e.clientX-rect.left)/rect.width*W;
    const i=Math.floor((sx-m.l)/bw);
    if(i>=0&&i<n){
      tip.innerHTML=`错配度 ≈ <b>${H.centers[i].toFixed(3)}</b><br>${H.counts[i]} 只`;
      tip.style.left=(e.clientX-rect.left+14)+"px";
      tip.style.top=(e.clientY-rect.top)+"px";
      tip.style.opacity=1;
    } else tip.style.opacity=0;
  });
  svg.addEventListener("mouseleave",()=>{tip.style.opacity=0;});
})();

/* ---- IC 表 ---- */
(function(){
  const C=DATA.ic;
  if(!C){$("icBlock").innerHTML='<p class="muted">检验未运行。</p>';return;}
  let h=`<table class="ic"><thead><tr><th>因子</th><th class="num">期限(交易日)</th>
    <th class="num">IC 均值</th><th class="num">IC t 值</th><th class="num">IC 95% 自举区间</th>
    <th class="num">Q5−Q1 扣费后</th><th class="num">alpha t</th><th class="num">样本 n</th></tr></thead><tbody>`;
  C.rows.forEach(r=>{
    if(r.n===0){h+=`<tr><td>${r.proxy}</td><td class="num">${r.h}</td>
       <td colspan="6" class="muted">样本不足（该期限非重叠样本为 0）</td></tr>`;return;}
    const passed=(r.t!==null&&Math.abs(r.t)>=C.thr);
    h+=`<tr class="${passed?'pass':''}"><td>${r.proxy}</td><td class="num">${r.h}</td>
      <td class="num">${fmt(r.ic,4)}</td>
      <td class="num"><b>${fmt(r.t,2)}</b>${passed?' √':''}</td>
      <td class="num mono">${r.lo===null?'—':`[${(r.lo>0?'+':'')}${r.lo.toFixed(3)}, ${(r.hi>0?'+':'')}${r.hi.toFixed(3)}]`}</td>
      <td class="num">${fmt(r.net,4)}</td><td class="num">${fmt(r.at,2)}</td><td class="num">${r.n}</td></tr>`;
  });
  h+="</tbody></table>";
  $("icBlock").innerHTML=h;
  $("verdict").innerHTML=`<b>结论：${C.verdict}</b> — Bonferroni（N=${C.n_trials}，α=0.05）|t| 临界 ≈ ${C.thr.toFixed(2)}；
    有效交易日 ${C.n_dates} 天（${C.date0} ~ ${C.date1}）。${C.verdict_note}`;
})();

/* ---- 页脚 ---- */
(function(){
  const m=DATA.meta;
  $("foot").innerHTML=`数据源：${m.db}（只读）；快照日 ${m.vdate}；财务期 ${m.fperiod}；
    生成时间 ${m.generated_at}；本页数据已内嵌，离线可开。`;
})();
</script>
</body>
</html>
"""


def render_html(payload, pct_section):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return TEMPLATE.replace("/*__DATA__*/", data).replace("__PCT_SECTION__", pct_section)


# ------------------------------------------------------------------ main
def build_parser():
    ap = argparse.ArgumentParser(description="生成公司价值判定系统的自包含可视化看板")
    ap.add_argument("--db", default=paths.resolve_db(), help="astock.db 路径（只读）")
    ap.add_argument("--hist-db", dest="hist_db", default=None,
                    help="可选 valuation_hist.db；给了就追加「自身历史分位」小节")
    ap.add_argument("--vdate", default=None, help="估值快照日（默认最新）")
    ap.add_argument("--fperiod", default=None, help="财务报告期（默认覆盖充分的最近一期）")
    ap.add_argument("--top", type=int, default=TOP_N, help="Top 榜条数")
    ap.add_argument("--hist-min-days", dest="hist_min_days", type=int, default=250)
    ap.add_argument("--hist-lookback", dest="hist_lookback", type=int, default=750)
    ap.add_argument("--no-test", dest="no_test", action="store_true", help="跳过 IC 检验（省时间）")
    ap.add_argument("--out", default=os.path.join(_HERE, "valuation_board.html"))
    return ap


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")   # GBK 控制台安全：不可编码字符降级而非崩溃
        except Exception:
            pass
    args = build_parser().parse_args()
    try:
        con = paths.open_ro(args.db)
    except FileNotFoundError:
        print("[错误] 打不开数据库：%s（试试 --db，或先跑 python demo.py 验证环境）" % args.db)
        return 2
    cur = con.cursor()
    vdate = args.vdate or astock.latest_valuation_date(cur)
    fperiod = args.fperiod or astock.latest_fund_period(cur)
    print("快照日=%s 财务期=%s" % (vdate, fperiod))
    try:
        rows, weights, ann, gate_thresh = compute_rows(cur, vdate, fperiod)
        n_gated = sum(1 for r in rows.values() if r.get("passed_gate"))
        print("打分 %d 只，过质量关 %d 只" % (len(rows), n_gated))

        pool, cheap, rich = pick_lists(rows, args.top)
        scatter = build_scatter(rows, SCATTER_MAX)
        hist = build_hist(rows)
        print("错配有效 %d 只，散点 %d 点" % (len(pool), len(scatter)))

        card = None if args.no_test else run_ic(cur)
        icrs = ic_rows(card)
        verdict, note = ("undetermined（不可判定）", "")
        if card:
            thr = card["thr"]
            hit = [r for r in card["rows"] if r["n"] > 0 and r["ic_t"] is not None and abs(r["ic_t"]) >= thr]
            if hit:
                verdict = "存在通过阈值者（需人工复核）"
                note = "有 %d 行 |t| ≥ %.2f。" % (len(hit), thr)
            else:
                note = "无任何因子在扣费 + 多重检验校正后显著；样本受限于本地日 K 约 13.5 个月。"

        hists = hist_percentiles(args.hist_db, args.hist_min_days, args.hist_lookback) if args.hist_db else {}
        pct_section = ""
        if hists:
            pct_section = ("<section><h2>5. 自身历史估值分位（真实纵向分位）</h2>"
                           "<p class='hint'>把「贵不贵」从当期横截面升级为对自身历史的纵向分位："
                           "便宜度 = mean(100 − 自身历史分位)。</p>" + pct_table(rows, hists) + "</section>")
            print("历史分位覆盖 %d 只" % len(hists))

        payload = dict(
            meta=dict(vdate=vdate, fperiod=fperiod, ann=ann, n_rows=len(rows), n_gated=n_gated,
                      gate=gate_thresh, weights=weights, r_discount=R_DISCOUNT,
                      db=os.path.basename(args.db),
                      generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                      hist=dict(n=(hist or {}).get("n", 0))),
            top_cheap=[_stock_dict(r) for r in cheap],
            top_rich=[_stock_dict(r) for r in rich],
            scatter=scatter,
            hist=hist,
            ic=(None if not card else dict(thr=card["thr"], n_trials=card["n_trials"],
                                           cost=card["cost"], n_dates=card["n_dates"],
                                           date0=card["date0"], date1=card["date1"],
                                           verdict=verdict, verdict_note=note, rows=icrs)),
        )
        htmltxt = render_html(payload, pct_section)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(htmltxt)
        print("WROTE %s (%.1f KB)" % (args.out, len(htmltxt.encode("utf-8")) / 1024.0))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
