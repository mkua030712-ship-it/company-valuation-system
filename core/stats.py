# -*- coding: utf-8 -*-
"""core.stats —— 纯统计工具（numpy + 标准库，无 IO）。

口径说明：
- pctrank(x)  : (平均秩-1)/(n-1)*100   —— 主入口错配/factor 用的百分位
- pct_rank(x) : 平均秩/n*100           —— 质量+估值排序器用的百分位
  两者只差常数缩放；在 Spearman 相关里等价，但直接展示数值时不同，故都保留。
"""
from __future__ import annotations
import math

import numpy as np


def rankdata(x):
    """平均秩（并列取均值），1-based。"""
    n = len(x)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    sx = x[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and sx[j] == sx[i]:
            j += 1
        ranks[order[i:j]] = (i + j - 1) / 2.0 + 1.0
        i = j
    return ranks


def pctrank(x):
    """百分位秩(0~100)，NaN 保留；(秩-1)/(n-1)*100。"""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    m = np.isfinite(x)
    v = x[m]
    if v.size == 0:
        return out
    r = rankdata(v)
    out[m] = (r - 1) / (v.size - 1) * 100.0 if v.size > 1 else 50.0
    return out


def pct_rank(x):
    """平均秩百分位(0~100，NaN 保留)；秩/n*100。"""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan, dtype=float)
    m = np.isfinite(x)
    v = x[m]
    n = v.size
    if n == 0:
        return out
    out[m] = rankdata(v) / n * 100.0
    return out


def spearman(a, b):
    """Spearman 秩相关（含并列平均秩）。样本 < 5 返回 NaN。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size < 5:
        return float("nan")
    ra, rb = rankdata(a), rankdata(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    d = math.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else float("nan")


def winsorize(x, lo=0.01, hi=0.99):
    """按分位缩尾；有效样本 < 20 原样返回。"""
    x = np.asarray(x, dtype=float)
    v = x[np.isfinite(x)]
    if v.size < 20:
        return x
    a, b = np.nanpercentile(v, [lo * 100, hi * 100])
    return np.clip(x, a, b)


def zscore(x):
    """标准化；非有限处保持 NaN；标准差为 0 时有效值置 0。"""
    x = np.asarray(x, dtype=float)
    m = np.nanmean(x)
    s = np.nanstd(x)
    out = np.full_like(x, np.nan, dtype=float)
    ok = np.isfinite(x)
    if s > 0:
        out[ok] = (x[ok] - m) / s
    else:
        out[ok] = 0.0
    return out


def norm_ppf(p):
    """标准正态分位数（Acklam 有理逼近，免 scipy 依赖）。"""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def bonferroni_t(n_trials, alpha=0.05):
    """Bonferroni 校正后的双尾 |t| 临界值（正态近似）。"""
    return norm_ppf(1 - alpha / (2 * n_trials))


def bootstrap_mean_ci(x, n_boot=2000, rng=None):
    """对一组数做自举，返回均值 95% 区间 (lo, hi)。"""
    x = np.asarray(x, dtype=float)
    n = x.size
    rng = rng if rng is not None else np.random.default_rng(0)
    bs = np.array([x[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(lo), float(hi)


def desc_stats(x):
    """描述统计；空返回 {}。"""
    x = np.asarray(x, dtype=float)
    v = x[np.isfinite(x)]
    if v.size == 0:
        return {}
    return dict(n=int(v.size), mean=float(v.mean()),
                std=float(v.std(ddof=1)) if v.size > 1 else float("nan"),
                min=float(v.min()),
                p10=float(np.percentile(v, 10)), p25=float(np.percentile(v, 25)),
                p50=float(np.percentile(v, 50)), p75=float(np.percentile(v, 75)),
                p90=float(np.percentile(v, 90)), max=float(v.max()))


def rolling_dev(M, t, win=120):
    """价格相对 win 日均线的偏离 M[:,t]/mean - 1；窗口不足返回 None。

    用掩码均值替代 np.nanmean：全 NaN 切片不再触发 RuntimeWarning("Mean of empty slice")。
    """
    if t - win < 0:
        return None
    win_ = M[:, t - win:t]
    cnt = np.isfinite(win_).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.nansum(win_, axis=1)
        ma = np.where(cnt > 0, s / np.where(cnt == 0, 1, cnt), np.nan)
        return M[:, t] / ma - 1.0


def normalize_codes(codes):
    """把逗号分隔代码规整为 6 位字符串集合；空返回 None。"""
    if not codes:
        return None
    out = set()
    for c in str(codes).split(","):
        c = c.strip()
        if c:
            out.add(c.zfill(6) if c.isdigit() else c)
    return out or None


def to_float(x):
    """宽松转 float，失败/空返回 NaN。"""
    try:
        return float(x) if x is not None else np.nan
    except Exception:
        return np.nan
