#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo.py — 开箱即跑的最小演示（只用 numpy + 标准库 + 仓库内脱敏样例）
================================================================================
不需要数据库！用它证明「环境装好了、代码能跑通」。

它演示的是本系统「价值判定」里的哪一部分：
  1. 行业相对倍数法：   IV_A = 行业 PE 中位数 × 年化 EPS
  2. 秩合成错配度：      mispr = pctrank( log(price / IV_A) )，取值 0~100（>50 偏贵、<50 偏便宜）
  3. 「越便宜估值分越高」的方向：cheapness = 100 - mispr

注意：因为样例只有 price / pe，没有 EPS 明细，这里用 EPS≈price/pe 反推，
所以 log(price/IV_A) 等价于 log(pe / 行业PE中位数) —— 这是**相对 PE** 的简化演示。
真实的完整版（多法 IV、盈利质量闸、历史分位、时点检验）见：
  mispricing_screener_v2.py / quality_value_screener_v2.py / valuation_percentile.py

数据：data/sample_valuation_snapshot.csv（手造脱敏示例，**非真实行情**）
用法：
  python demo.py
  python demo.py --csv data/sample_valuation_snapshot.csv
"""
from __future__ import annotations
import argparse
import csv
import math
import os
import sys

import numpy as np


def _ok_mark():
    """选一个当前控制台能编码的完成标记：UTF-8 下用 ✔，GBK/legacy 控制台降级为 √。

    Windows 默认 cmd.exe 代码页是 GBK(936)，U+2714(✔) 不在 GBK 字符集里，
    直接 print 会抛 UnicodeEncodeError —— 这里做降级，保证「开箱即跑」不崩。
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    for ch in ("\u2714", "\u221a"):
        try:
            ch.encode(enc)
            return ch
        except Exception:
            continue
    return "OK"


def pctrank(x: np.ndarray) -> np.ndarray:
    """平均秩百分位（0~100，NaN 保留）；与主脚本口径一致。"""
    out = np.full(len(x), np.nan)
    m = np.isfinite(x)
    v = x[m]
    n = v.size
    if n == 0:
        return out
    order = np.argsort(v, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i + 1
        while j < n and v[order[j]] == v[order[i]]:
            j += 1
        ranks[order[i:j]] = (i + j - 1) / 2.0 + 1.0  # 1-based 平均秩
        i = j
    out[m] = (ranks - 1) / (n - 1) * 100.0 if n > 1 else 50.0
    return out


def load_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            def f(k):
                try:
                    return float(r.get(k))
                except (TypeError, ValueError):
                    return float("nan")
            rows.append(dict(code=r.get("code", ""), name=r.get("name", ""),
                             industry=r.get("industry") or "-",
                             price=f("price"), pe=f("pe")))
    return rows


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")   # GBK 控制台安全：不可编码字符降级而非崩溃
        except Exception:
            pass
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="价值判定系统 · 开箱即跑 demo（无需数据库）")
    ap.add_argument("--csv", default=os.path.join(here, "data", "sample_valuation_snapshot.csv"))
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        raise SystemExit("找不到样例文件：%s" % args.csv)
    rows = load_rows(args.csv)
    if not rows:
        raise SystemExit("样例为空：%s" % args.csv)

    n = len(rows)
    pe = np.array([r["pe"] for r in rows], dtype=float)
    price = np.array([r["price"] for r in rows], dtype=float)
    ind = [r["industry"] for r in rows]

    # 行业 PE 中位数（仅用正 PE）；行业样本不足退回全市场中位数
    ind_pe, all_pos = {}, []
    for i in range(n):
        if np.isfinite(pe[i]) and pe[i] > 0:
            ind_pe.setdefault(ind[i], []).append(pe[i])
            all_pos.append(pe[i])
    ind_med = {k: float(np.median(v)) for k, v in ind_pe.items()}
    all_med = float(np.median(all_pos)) if all_pos else float("nan")

    # IV_A = 行业PE中位数 × EPS，EPS≈price/pe  =>  price/IV_A = pe/行业PE中位数
    gap = np.full(n, np.nan)
    for i in range(n):
        if not (np.isfinite(pe[i]) and pe[i] > 0):
            continue
        peer = ind_med.get(ind[i], all_med)
        if peer and peer > 0:
            gap[i] = math.log(pe[i] / peer)

    mispr = pctrank(gap)            # 0~100，>50 偏贵
    cheapness = 100.0 - mispr       # 越大越便宜
    ey = np.where(np.isfinite(pe) & (pe > 0), 1.0 / np.where(pe == 0, np.nan, pe), np.nan)

    order = np.argsort(np.where(np.isfinite(mispr), mispr, np.inf))

    print("=" * 78)
    print("价值判定系统 · 开箱 demo（样例：%s）" % os.path.relpath(args.csv, here))
    print("=" * 78)
    print("- 样例股票数：%d；涉及行业：%d 个" % (n, len(ind_med)))
    print("- 行业 PE 中位数：%s" % ", ".join("%s=%.2f" % (k, v) for k, v in sorted(ind_med.items())))
    print("- 全市场 PE 中位数（行业样本不足时兜底）：%.2f" % all_med)
    print("- 口径：IV_A=行业PE中位数×EPS；错配=pctrank(log(price/IV_A))，>50 偏贵")
    print()
    print("%-8s %-10s %-12s %8s %8s %9s %11s %10s" %
          ("code", "name", "industry", "price", "pe", "1/PE", "mispr", "cheapness"))
    for i in order:
        print("%-8s %-10s %-12s %8s %8s %9s %11s %10s" % (
            rows[i]["code"], rows[i]["name"][:10], rows[i]["industry"][:12],
            ("%.2f" % price[i]) if np.isfinite(price[i]) else "NA",
            ("%.2f" % pe[i]) if np.isfinite(pe[i]) else "NA",
            ("%.4f" % ey[i]) if np.isfinite(ey[i]) else "NA",
            ("%.1f" % mispr[i]) if np.isfinite(mispr[i]) else "NA",
            ("%.1f" % cheapness[i]) if np.isfinite(cheapness[i]) else "NA"))
    print()
    print("读法：mispr 越小越偏便宜、越大越偏贵；NA=亏损或 PE 缺失（不参与排序）。")
    print("提示：样例是手造脱敏数据，只演示口径链路。要跑真实全市场，准备 astock.db 后用：")
    print("  python mispricing_screener_v2.py --mode both --db <astock.db> --hist-db <valuation_hist.db> --out v2_out.txt")
    print()
    print("DEMO OK %s  环境已装好，可以跑正式脚本了。" % _ok_mark())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
