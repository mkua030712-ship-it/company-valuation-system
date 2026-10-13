# -*- coding: utf-8 -*-
"""core.quality —— 质量分合成 + 质量闸 + 综合分（纯计算，无 IO）。

质量分 = 5 个可得财务代理的加权合成，输出池内百分位（0~100）：
  roe 0.30 / gross_margin 0.20 / net_margin 0.20 / rev_yoy 0.15 / net_yoy 0.15
抗极值：先按量纲截断，增长类用秩变换，其余缩尾后 z 标准化；缺失成分自动降权（记 q_n）。
"""
from __future__ import annotations

import numpy as np

from . import stats

DEFAULT_Q_WEIGHTS = {
    "roe": 0.30,
    "gross_margin": 0.20,
    "net_margin": 0.20,
    "rev_yoy": 0.15,
    "net_yoy": 0.15,
}

CAP = {"rev_yoy": (-100.0, 300.0), "net_yoy": (-300.0, 500.0),
       "gross_margin": (0.0, 90.0), "net_margin": (-100.0, 80.0), "roe": (-50.0, 60.0)}


def parse_weights(s):
    """'roe=0.3,gross_margin=0.2' → 归一化权重 dict。"""
    out = {}
    for part in s.split(","):
        k, v = part.split("=")
        out[k.strip()] = float(v)
    tot = sum(out.values())
    if tot <= 0:
        raise ValueError("权重和必须 > 0")
    return {k: v / tot for k, v in out.items()}


def quality_components(rows, weights):
    """按 weights 的键抽取原始成分矩阵 {name: ndarray}。"""
    codes = list(rows.keys())
    n = len(codes)
    comp = {k: np.full(n, np.nan) for k in weights}
    for i, c in enumerate(codes):
        r = rows[c]
        if r.get("roe") is not None and "roe" in comp:
            comp["roe"][i] = r["roe"]
        if r.get("gross_margin") is not None and "gross_margin" in comp:
            comp["gross_margin"][i] = r["gross_margin"]
        if "net_margin" in comp and r.get("net_profit") is not None and r.get("revenue"):
            comp["net_margin"][i] = r["net_profit"] / r["revenue"] * 100.0
        if r.get("rev_yoy") is not None and "rev_yoy" in comp:
            comp["rev_yoy"][i] = r["rev_yoy"]
        if r.get("net_yoy") is not None and "net_yoy" in comp:
            comp["net_yoy"][i] = r["net_yoy"]
    return comp


def score_quality(rows, weights):
    """合成质量分，就地写回 rows[code]["quality_score"] 等；返回成分矩阵 comp。"""
    codes = list(rows.keys())
    n = len(codes)
    comp = quality_components(rows, weights)

    z = {}
    for k in weights:
        c = comp[k].copy()
        lo, hi = CAP.get(k, (None, None))
        if lo is not None:
            c = np.where(np.isfinite(c), np.clip(c, lo, hi), np.nan)
        if k in ("rev_yoy", "net_yoy"):
            z[k] = (stats.pct_rank(c) - 50.0) / 50.0      # 秩变换，抗极值
        else:
            z[k] = stats.zscore(stats.winsorize(c, 0.02, 0.98))

    wsum = np.zeros(n)
    wuse = np.zeros(n)
    q_n = np.zeros(n, dtype=int)
    for k, w in weights.items():
        ok = np.isfinite(z[k])
        wsum[ok] += w * z[k][ok]
        wuse[ok] += w
        q_n[ok] += 1
    q_raw = np.where(wuse > 0, wsum / np.where(wuse == 0, 1, wuse), np.nan)
    q_score = stats.pct_rank(q_raw)
    for i, c in enumerate(codes):
        rows[c]["q_raw"] = q_raw[i]
        rows[c]["quality_score"] = q_score[i]
        rows[c]["q_n"] = int(q_n[i])
        rows[c]["_comp"] = {k: comp[k][i] for k in weights}
    return comp


def composite(rows, gate_pct):
    """质量关 + 综合分：仅对质量分 ≥ 池内第 gate_pct 百分位的票，算 0.5·z(Q)+0.5·z(V)。

    就地写回 rows[code]["passed_gate"] / ["composite_score"]；返回质量关阈值。
    """
    codes = list(rows.keys())
    q = np.array([rows[c]["quality_score"] for c in codes], dtype=float)
    v = np.array([rows[c]["valuation_score"] for c in codes], dtype=float)
    gate_thresh = np.nanpercentile(q, gate_pct)
    passed = q >= gate_thresh
    zq = stats.zscore(q[passed])
    zv = stats.zscore(v[passed])
    comp = 0.5 * np.nan_to_num(zq) + 0.5 * np.nan_to_num(zv)
    comp_pct = stats.pct_rank(comp)
    passed_codes = [c for c, p in zip(codes, passed) if p]
    for c in codes:
        rows[c]["passed_gate"] = False
        rows[c]["composite_score"] = np.nan
    for j, c in enumerate(passed_codes):
        rows[c]["passed_gate"] = True
        rows[c]["composite_score"] = comp_pct[j]
    return gate_thresh


def build_universe(valuation, fund, shares, ind_map, exclude_st=True,
                   universe="all", industry=None, want_codes=None):
    """把内存数据合成打分用股票池 rows（纯计算；文件读取交给调用方）。

    - valuation: {code: {name, industry, price, pe, total_mv, circ_mv}}
    - fund:      {code: {eps, revenue, net_profit, roe, gross_margin, rev_yoy, net_yoy, pub_date}}
    - shares:    {code: {total_shares, float_shares}}
    - ind_map:   {code: industry}（行业兜底）
    - want_codes: 过滤代码集合（None=不过滤）
    """
    rows = {}
    for code, v in valuation.items():
        if exclude_st and v.get("name") and "ST" in v["name"]:
            continue
        f = fund.get(code)
        sh = shares.get(code, {})
        rows[code] = dict(
            code=code, name=v.get("name"), industry=v.get("industry") or ind_map.get(code) or "",
            price=v.get("price"), pe=v.get("pe"), total_mv=v.get("total_mv"), circ_mv=v.get("circ_mv"),
            eps=None if not f else f.get("eps"), revenue=None if not f else f.get("revenue"),
            net_profit=None if not f else f.get("net_profit"), roe=None if not f else f.get("roe"),
            gross_margin=None if not f else f.get("gross_margin"),
            rev_yoy=None if not f else f.get("rev_yoy"), net_yoy=None if not f else f.get("net_yoy"),
            pub_date=None if not f else f.get("pub_date"),
            total_shares=sh.get("total_shares"),
        )
    if universe == "industry" and industry:
        rows = {c: r for c, r in rows.items() if (r["industry"] or "") == industry}
    elif want_codes:
        rows = {c: r for c, r in rows.items() if c in want_codes}
    return rows
