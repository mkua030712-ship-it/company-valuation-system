# -*- coding: utf-8 -*-
"""core.testing —— 横截面预测力检验（纯计算，无 IO）。

检验口径：
- 因子：E/P(pit价值)（时点重建的真估值因子）、rev21（21日反转）、dev120（偏离120日均线）
- 每 h 交易日：rank IC（Spearman）+ 五分组（Q5最高代理 - Q1最低代理，扣往返成本）
  + 对市场因子回归取 alpha + 自举 95% CI + Bonferroni 阈值
判读：|IC_t| < 阈值 且 CI 跨 0 → 未通过；样本不足一律 undetermined。
"""
from __future__ import annotations
import math

import numpy as np

from . import stats
from .valuation import eps_ann_at

HORIZONS = (21, 63, 126, 252)
REBAL_DAYS = 21
COST_ROUND_TRIP = 0.0030
SEED = 20261011
N_TRIALS = 12


def reversal(M, t, look=21):
    """21 日反转：过去 look 日涨幅；窗口不足返回 None。"""
    if t - look < 0:
        return None
    return M[:, t] / M[:, t - look] - 1.0


def make_ey_proxy(codes, dates, fund, ann_override=None):
    """构造 E/P(pit价值) 代理：pub_date<=t 的年化 EPS / 当日收盘。"""
    rec_by_code = {c: fund.get(c, []) for c in codes}

    def ey(M, ti):
        d = dates[ti]
        outv = np.full(len(codes), np.nan)
        for i, c in enumerate(codes):
            px = M[i, ti]
            if not np.isfinite(px) or px <= 0:
                continue
            f = eps_ann_at(rec_by_code[c], d, ann_override)
            if not f or f[0] is None or f[0] <= 0:
                continue
            outv[i] = f[0] / px
        return outv

    return ey


def run_predictive_test(M, dates, codes, fund, idx, ann_override=None,
                        horizons=HORIZONS, rebal_days=REBAL_DAYS,
                        cost=COST_ROUND_TRIP, seed=SEED, n_trials=N_TRIALS, n_boot=2000):
    """返回结果 dict（含表头信息与逐 (proxy,h) 明细行），供 report 渲染。"""
    proxies = {
        "E/P(pit价值)": make_ey_proxy(codes, dates, fund, ann_override),
        "rev21": lambda M, t: reversal(M, t, 21),
        "dev120": stats.rolling_dev,
    }
    rebal = list(range(20, len(dates) - min(horizons), rebal_days))
    rng = np.random.default_rng(seed)
    rows = []
    for pname, fn in proxies.items():
        for h in horizons:
            ics, spreads, mkt = [], [], []
            for ti in rebal:
                if ti + h >= len(dates):
                    continue
                pv = fn(M, ti)
                if pv is None:
                    continue
                fwd = M[:, ti + h] / M[:, ti] - 1.0
                ok = np.isfinite(pv) & np.isfinite(fwd)
                if ok.sum() < 50:
                    continue
                ics.append(stats.spearman(pv[ok], fwd[ok]))
                po, fo = pv[ok], fwd[ok]
                order = np.argsort(po)
                q = np.array_split(order, 5)
                spreads.append(fo[q[-1]].mean() - fo[q[0]].mean())
                mkt.append(idx[ti + h] / idx[ti] - 1.0
                           if np.isfinite(idx[ti]) and np.isfinite(idx[ti + h]) else np.nan)
            ics = np.array([x for x in ics if np.isfinite(x)])
            spreads = np.array(spreads)
            mkt = np.array(mkt)
            n = len(ics)
            if n == 0:
                rows.append(dict(proxy=pname, h=h, n=0, ic_mean=None, ic_t=None,
                                 lo=None, hi=None, net=None, alpha=None, a_t=None))
                continue
            icm = ics.mean()
            ict = icm / (ics.std(ddof=1) / math.sqrt(n)) if n > 1 and ics.std(ddof=1) > 0 else float("nan")
            lo, hi = stats.bootstrap_mean_ci(ics, n_boot=n_boot, rng=rng)
            net = spreads.mean() - cost
            okm = np.isfinite(mkt)
            if okm.sum() >= 3 and np.std(mkt[okm]) > 0:
                X = np.column_stack([np.ones(okm.sum()), mkt[okm]])
                beta, *_ = np.linalg.lstsq(X, spreads[okm], rcond=None)
                resid = spreads[okm] - X @ beta
                se = math.sqrt((resid ** 2).sum() / (okm.sum() - 2) * np.linalg.inv(X.T @ X)[1, 1])
                alpha, at = beta[0], (beta[0] / se if se > 0 else float("nan"))
            else:
                alpha, at = float("nan"), float("nan")
            rows.append(dict(proxy=pname, h=h, n=n, ic_mean=float(icm), ic_t=float(ict),
                             lo=lo, hi=hi, net=float(net), alpha=float(alpha), a_t=float(at)))
    return dict(thr=stats.bonferroni_t(n_trials), n_trials=n_trials, horizons=tuple(horizons),
                rebal_days=rebal_days, cost=cost, seed=seed,
                n_dates=len(dates), date0=dates[0], date1=dates[-1], n_codes=len(codes), rows=rows)


def pick_anchor(dates, want):
    """锚点日：>=want 的第一个交易日；没有则取最后一天。"""
    cand = [d for d in dates if d >= want]
    return cand[0] if cand else dates[-1]


def forward_test(codes, q_scores, v_scores, pub_dates, close_anchor, close_end, anchor,
                 point_in_time=True):
    """单一锚点的前向收益检验（纯计算）。返回明细 dict，供 report 渲染。"""
    n = len(codes)
    fwd = np.full(n, np.nan)
    qq = np.full(n, np.nan)
    vv = np.full(n, np.nan)
    kept = 0
    for i, c in enumerate(codes):
        if point_in_time:
            pd_ = pub_dates[i]
            if not pd_ or pd_ > anchor:
                continue
        ca, ce = close_anchor.get(c), close_end.get(c)
        if not ca or not ce or ca <= 0:
            continue
        fwd[i] = ce / ca - 1.0
        qq[i] = q_scores[i]
        vv[i] = v_scores[i]
        kept += 1
    out = dict(kept=kept, fwd=fwd, qq=qq, vv=vv, ic_q=float("nan"), ic_v=float("nan"), terciles={})
    if kept < 30:
        return out
    out["ic_q"] = stats.spearman(qq, fwd)
    out["ic_v"] = stats.spearman(vv, fwd)
    for name, arr in (("quality", qq), ("valuation", vv)):
        ok = np.isfinite(arr) & np.isfinite(fwd)
        if ok.sum() < 30:
            continue
        a, r = arr[ok], fwd[ok]
        order = np.argsort(a)
        t = np.array_split(order, 3)
        means = [float(r[x].mean()) for x in t]
        out["terciles"][name] = dict(means=means, diff=means[0] - means[2],
                                     ns=[len(t[0]), len(t[1]), len(t[2])])
    return out
