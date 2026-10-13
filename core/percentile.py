# -*- coding: utf-8 -*-
"""core.percentile —— 自身历史估值分位（纯计算，无 IO）。

把「公司贵不贵」从当期横截面升级为**对其自身历史的纵向分位**：
取近 N 个交易日的 PE(TTM)/PB/PS，算当前值在自身历史中的分位；
便宜度 = mean(100 - 分位)（越大越便宜）。
"""
from __future__ import annotations

import numpy as np


def pct_of(value, hist):
    """当前值在 hist 中的分位（0~100）；有效样本 < 60 返回 None。"""
    v = np.asarray(hist, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 60:
        return None
    return float((v <= value).mean() * 100.0)


def historical_percentiles(group_iter, min_days=250, lookback=750):
    """吃 (code, [[pe, pb, ps], ...]) 分组迭代器，返回 {code: dict(cheap, n, pe_pct/pb_pct/ps_pct)}。

    行数据由 dataio 流式提供（一次只留当前 code 的缓冲），避免把整库读进内存。
    """
    out = {}
    for code, rows in group_iter:
        if not rows or len(rows) < min_days:
            continue
        arr = np.array(rows, dtype=float)[-lookback:]
        if arr.shape[0] < min_days:
            continue
        last = arr[-1]
        ps = {}
        for j, k in enumerate(("pe", "pb", "ps")):
            if np.isfinite(last[j]):
                p = pct_of(last[j], arr[:, j])
                if p is not None:
                    ps[k] = p
        if not ps:
            continue
        out[code] = dict(cheap=float(np.mean([100.0 - v for v in ps.values()])), n=arr.shape[0],
                         pe=last[0], pb=last[1], ps=last[2],
                         **{("%s_pct" % k): ps[k] for k in ps})
    return out
