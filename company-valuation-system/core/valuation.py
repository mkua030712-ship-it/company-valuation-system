# -*- coding: utf-8 -*-
"""core.valuation —— 内在价值多法 + 错配度（纯计算，无 IO）。

两条口径并存，分别服务两个入口：
- compute_value_v2(...)          : 主入口 mispricing_screener_v2 用（3 法 IV + 对数缺口 + 秩合成 + E/P 闸）
- compute_valuation_scores(...)  : 质量+估值排序器用（ey/by/sy/mis + 分位信号 + 可选行业中性）

输入一律是内存字典/列表：
- valuation: {code: {name, price, pe, industry, ...}}          （估值快照）
- fund:      {code: [(pub_date, period, eps, net_profit, roe, rev_yoy), ...] 升序}
- shares:    {code: total_shares}
"""
from __future__ import annotations
from collections import defaultdict

import numpy as np

from . import stats

ANN_FACTOR = 2.0            # 年化系数兜底值；正常按报告期自动推断


def ann_factor_for_period(period, default=ANN_FACTOR):
    """按报告期推断 EPS 年化系数：0331×4 / 0630×2 / 0930×4/3 / 1231×1。"""
    if period is None:
        return default
    return {"0331": 4.0, "0630": 2.0, "0930": 4.0 / 3.0, "1231": 1.0}.get(str(period)[4:8], default)


def _ann_for(period, ann_override):
    return ann_override if ann_override is not None else ann_factor_for_period(period)


def eps_ann_at(recs, date, ann_override=None):
    """时点年化 EPS：取 pub_date<=date 的最近一期，按报告期年化。
    返回 (eps_ann, roe, rev_yoy) 或 None。"""
    best = None
    for pd_, period, eps, npf, roe, rev in recs:
        if pd_ <= date:
            best = (period, eps, roe, rev)
        else:
            break
    if best is None or best[1] is None:
        return None
    return best[1] * _ann_for(best[0], ann_override), best[2], best[3]


def compute_value_v2(valuation, fund, shares, vdate, r_discount=0.08, min_peer_n=5,
                     earn_floor=0.005, ann_override=None):
    """三法内在价值 + 秩合成错配 + 盈利质量闸。返回 recs 列表（每项一个 dict）。"""
    by_ind_pe = defaultdict(list)
    by_ind_pb = defaultdict(list)
    tmp = []
    for code, v in valuation.items():
        if v.get("name") and "ST" in v["name"]:
            continue
        price = v.get("price")
        pe = v.get("pe")
        recs_code = fund.get(code, [])
        f = eps_ann_at(recs_code, vdate, ann_override)
        if not f or not price or price <= 0:
            continue
        eps_ann, roe, rev = f
        if eps_ann is None or eps_ann <= 0:
            continue
        # 账面价值近似：equity = net_profit/(ROE/100)
        bvps = None
        rec = [r for r in recs_code if r[0] <= vdate]
        if rec:
            _, _, _, npf, roe0, _ = rec[-1]
            sh = shares.get(code)
            if isinstance(sh, dict):            # 支持 {code: {total_shares,...}} 或 {code: total_shares}
                sh = sh.get("total_shares")
            if npf and roe0 not in (None, 0) and sh and sh > 0:
                eq = npf / (roe0 / 100.0)
                if eq > 0:
                    bvps = eq / sh
        tmp.append(dict(code=code, name=v.get("name"), industry=v.get("industry"), price=price,
                        pe=pe, eps_ann=eps_ann, bvps=bvps))
        if pe and pe > 0:
            by_ind_pe[v.get("industry")].append(pe)
        if bvps and bvps > 0:
            by_ind_pb[v.get("industry")].append(price / bvps)

    ind_pe = {k: float(np.median(v)) for k, v in by_ind_pe.items() if v}
    ind_pb = {k: float(np.median(v)) for k, v in by_ind_pb.items() if v}
    all_pe = float(np.median([p for v in by_ind_pe.values() for p in v])) if by_ind_pe else None
    all_pb = float(np.median([p for v in by_ind_pb.values() for p in v])) if by_ind_pb else None

    recs = []
    for r in tmp:
        eps_ann, price = r["eps_ann"], r["price"]
        iv_b = eps_ann / r_discount
        peer_pe = ind_pe.get(r["industry"]) if len(by_ind_pe.get(r["industry"], [])) >= min_peer_n else all_pe
        iv_a = peer_pe * eps_ann if peer_pe else None
        iv_c = None
        if r["bvps"]:
            peer_pb = ind_pb.get(r["industry"]) if len(by_ind_pb.get(r["industry"], [])) >= min_peer_n else all_pb
            if peer_pb:
                iv_c = peer_pb * r["bvps"]
        r.update(iv_a=iv_a, iv_b=iv_b, iv_c=iv_c, ep=eps_ann / price)
        recs.append(r)

    # 对数缺口 → 逐列秩合成
    for key, ivk in (("gap_a", "iv_a"), ("gap_b", "iv_b"), ("gap_c", "iv_c")):
        arr = np.array([np.log(x["price"] / x[ivk]) if x[ivk] and x[ivk] > 0 else np.nan for x in recs])
        for x, g in zip(recs, arr):
            x[key] = g
    ga = np.array([x["gap_a"] for x in recs])
    gb = np.array([x["gap_b"] for x in recs])
    gc = np.array([x["gap_c"] for x in recs])
    ra, rb, rc = stats.pctrank(ga), stats.pctrank(gb), stats.pctrank(gc)
    for i, x in enumerate(recs):
        vals = [v for v in (ra[i], rb[i], rc[i]) if np.isfinite(v)]
        x["mispr_rank"] = float(np.mean(vals)) if vals else np.nan
        x["low_quality"] = x["ep"] < earn_floor
    return recs


# 让 compute_value_v2 保持「只吃内存数据」的签名；快照日 vdate 显式入参。

def compute_valuation_scores(rows, r_discount=0.08, ann=ANN_FACTOR, min_peer=5, neutral=False):
    """质量+估值排序器的估值分口径：ey/by/sy/mis + 分位信号（+可选行业中性）。

    直接就地写回 rows[code] 的 earnings_yield/book_yield/sales_yield/mispricing/valuation_score/v_n。
    返回 {signal_name: ndarray}。
    """
    codes = list(rows.keys())
    n = len(codes)

    by_ind = defaultdict(list)
    for c in codes:
        pe = rows[c].get("pe")
        if pe is not None and pe > 0:
            by_ind[rows[c].get("industry")].append(pe)
    ind_med = {k: float(np.median(v)) for k, v in by_ind.items() if v}
    all_pe = [p for v in by_ind.values() for p in v]
    all_med = float(np.median(all_pe)) if all_pe else None

    ey = np.full(n, np.nan)
    by = np.full(n, np.nan)
    sy = np.full(n, np.nan)
    gap_a = np.full(n, np.nan)
    gap_b = np.full(n, np.nan)
    pb = np.full(n, np.nan)

    for i, c in enumerate(codes):
        r = rows[c]
        price = r.get("price")
        pe = r.get("pe")
        if price and price > 0 and pe and pe > 0:
            ey[i] = 1.0 / pe
        if (price and price > 0 and r.get("net_profit") not in (None, 0)
                and r.get("roe") not in (None, 0) and r.get("total_shares")):
            eq = r["net_profit"] / (r["roe"] / 100.0)
            if np.isfinite(eq) and eq > 0 and r["total_shares"] > 0:
                bvps = eq / r["total_shares"]
                by[i] = bvps / price
                pb[i] = price / bvps
        if r.get("revenue") and r.get("total_mv") and r["revenue"] > 0 and r["total_mv"] > 0:
            sy[i] = r["revenue"] / (r["total_mv"] * 1e4)
        # 必须同时为正 PE + 正 EPS 才给「便宜」信用
        eps = r.get("eps")
        if price and price > 0 and pe and pe > 0 and eps is not None and eps > 0:
            eps_ann = eps * ann
            iv_b = eps_ann / r_discount
            gap_b[i] = price / iv_b - 1.0
            peer = ind_med.get(r.get("industry"))
            if peer is None or len(by_ind.get(r.get("industry"), [])) < min_peer:
                peer = all_med
            if peer:
                iv_a = peer * eps_ann
                gap_a[i] = price / iv_a - 1.0

    ga_w, gb_w = stats.winsorize(gap_a), stats.winsorize(gap_b)
    za, zb = stats.zscore(ga_w), stats.zscore(gb_w)
    mis = np.where(np.isfinite(za) & np.isfinite(zb), 0.5 * za + 0.5 * zb,
                   np.where(np.isfinite(zb), zb, np.where(np.isfinite(za), za, np.nan)))

    sig = {
        "earnings_yield": stats.pct_rank(stats.winsorize(ey)),
        "book_yield": stats.pct_rank(stats.winsorize(by)),
        "sales_yield": stats.pct_rank(stats.winsorize(sy)),
        "mis_cheap": stats.pct_rank(stats.winsorize(-mis)),
    }
    ssum = np.zeros(n)
    scnt = np.zeros(n)
    for arr in sig.values():
        ok = np.isfinite(arr)
        ssum[ok] += arr[ok]
        scnt[ok] += 1
    v_raw = np.where(scnt > 0, ssum / np.where(scnt == 0, 1, scnt), np.nan)
    v_score = stats.pct_rank(v_raw)

    if neutral:
        idx_by_ind = defaultdict(list)
        for i, c in enumerate(codes):
            idx_by_ind[rows[c].get("industry")].append(i)
        glob = stats.pct_rank(v_raw)
        v_score = np.full(n, np.nan)
        for _ind, idxs in idx_by_ind.items():
            if len(idxs) >= 15:
                v_score[idxs] = stats.pct_rank(v_raw[idxs])
            else:
                v_score[idxs] = glob[idxs]

    for i, c in enumerate(codes):
        r = rows[c]
        r["earnings_yield"] = ey[i]
        r["book_yield"] = by[i]
        r["pb_approx"] = pb[i]
        r["sales_yield"] = sy[i]
        r["gap_a"] = gap_a[i]
        r["gap_b"] = gap_b[i]
        r["mispricing"] = mis[i]
        r["valuation_score"] = v_score[i]
        r["v_n"] = int(scnt[i])
    return sig
