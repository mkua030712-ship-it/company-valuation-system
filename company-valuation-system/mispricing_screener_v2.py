#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mispricing_screener_v2.py — 薄入口（公司价值评估与错配）
================================================================================
本文件只做「参数解析 + 调用」，本身不含算法：
  · 算法 → core/（valuation 内在价值与错配、testing 检验、report 渲染、stats 统计）
  · 数据 → dataio/（唯一碰数据库的地方；不含数据库本体）

功能（原命令行行为保持不变）：
  · value：三法内在价值 + 秩合成错配 + 盈利质量闸 + 自身历史分位
  · test ：时点重建的真估值因子 / 反转 / 均线偏离 的横截面检验（IC/五分组/alpha/自举）

零外部依赖（numpy + 标准库）。只读数据库（mode=ro）。
用法：
  py -3.12 mispricing_screener_v2.py --mode both --db <astock.db> --hist-db <valuation_hist.db> --out v2_out.txt
  py -3.12 mispricing_screener_v2.py --mode value --codes 600519,000858 --out one.txt
免责：研究方法论原型，不构成投资建议。数字均来自真实运行。
"""
from __future__ import annotations
import argparse
import os
import sqlite3
import sys

from core import percentile, report, stats, testing, valuation
from dataio import astock, paths

DEFAULT_DB = paths.resolve_db()
DEFAULT_HIST = paths.resolve_hist()

# —— 默认参数（全部可用命令行覆盖）——
R_DISCOUNT = 0.08
MIN_PEER_N = 5
EARN_FLOOR = 0.005
MIN_ROWS_PER_DAY = astock.MIN_ROWS_PER_DAY
REBAL_DAYS = testing.REBAL_DAYS
COST_ROUND_TRIP = testing.COST_ROUND_TRIP
SEED = testing.SEED
N_TRIALS = testing.N_TRIALS
HORIZONS = testing.HORIZONS


def _db_hint(path):
    return (
        "[提示] 打不开数据库：%s\n"
        "  本仓库不含数据库（体积原因，*.db 不入库）。三种做法：\n"
        "  1) 先验证环境（不需要数据库）：   python demo.py\n"
        "  2) 跑真实数据：准备 astock.db 后，用 --db <path>，或放到 data/astock.db，或设环境变量 ASTOCK_DB\n"
        "  3) 接自己的库：改 dataio/astock.py（见 dataio/schema.md 与 dataio/example_adapter.py）\n" % path
    )


def _load_hist_percentiles(hist_db, min_days, lookback):
    if not hist_db or not os.path.exists(hist_db):
        return {}
    con = paths.open_ro(hist_db)
    try:
        return percentile.historical_percentiles(astock.iter_valuation_hist(con.cursor()),
                                                 min_days=min_days, lookback=lookback)
    finally:
        con.close()


def run_value(cur, args, out):
    vdate = astock.latest_valuation_date(cur)
    fperiod = astock.latest_fund_period(cur)
    val = astock.load_valuation_snapshot(cur, vdate)
    fund = astock.load_financials_pit(cur)
    shares = astock.load_shares(cur)
    recs = valuation.compute_value_v2(val, fund, shares, vdate,
                                      r_discount=args.r_discount, min_peer_n=args.min_peer_n,
                                      earn_floor=args.earn_floor, ann_override=args.ann_factor)
    hp = _load_hist_percentiles(args.hist_db, args.hist_min_days, args.hist_lookback)
    codeset = stats.normalize_codes(args.codes)
    lines, meta = report.render_value(vdate, fperiod, recs, hp, r_discount=args.r_discount,
                                      earn_floor=args.earn_floor, ann_override=args.ann_factor,
                                      codeset=codeset)
    out.extend(lines)
    return meta


def run_test(cur, args, out):
    dates = astock.load_trade_dates(cur, args.min_rows_per_day)
    codes, dates, M = astock.load_kline(cur, dates)
    fund = astock.load_financials_pit(cur)
    idx = astock.load_index_series(cur, dates)
    res = testing.run_predictive_test(M, dates, codes, fund, idx, ann_override=args.ann_factor,
                                      horizons=HORIZONS, rebal_days=args.rebal_days,
                                      cost=args.cost, seed=args.seed, n_trials=N_TRIALS)
    out.extend(report.render_test(res))
    return res


def build_parser():
    ap = argparse.ArgumentParser(description="公司价值判定系统 · 错配筛查与检验（薄入口）")
    ap.add_argument("--db", default=DEFAULT_DB, help="astock.db 路径（只读；也可用环境变量 ASTOCK_DB）")
    ap.add_argument("--mode", choices=["value", "test", "both"], default="both")
    ap.add_argument("--out", default=None)
    ap.add_argument("--hist-db", dest="hist_db", default=DEFAULT_HIST)
    ap.add_argument("--hist-min-days", dest="hist_min_days", type=int, default=250)
    ap.add_argument("--hist-lookback", dest="hist_lookback", type=int, default=750)
    ap.add_argument("--r-discount", dest="r_discount", type=float, default=R_DISCOUNT)
    ap.add_argument("--ann-factor", dest="ann_factor", type=float, default=None,
                    help="强制 EPS 年化系数（兼容旧口径 ×2）；缺省按报告期自动")
    ap.add_argument("--earn-floor", dest="earn_floor", type=float, default=EARN_FLOOR)
    ap.add_argument("--min-peer-n", dest="min_peer_n", type=int, default=MIN_PEER_N)
    ap.add_argument("--min-rows-per-day", dest="min_rows_per_day", type=int, default=MIN_ROWS_PER_DAY)
    ap.add_argument("--rebal-days", dest="rebal_days", type=int, default=REBAL_DAYS)
    ap.add_argument("--cost", dest="cost", type=float, default=COST_ROUND_TRIP)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--codes", default=None,
                    help="逗号分隔代码，仅显示这些票（如 600519,000858）；行业/全市场分位仍按全池算")
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
        print(_db_hint(args.db))
        return 2
    out = []
    try:
        cur = con.cursor()
        if args.mode in ("value", "both"):
            run_value(cur, args, out)
        if args.mode in ("test", "both"):
            run_test(cur, args, out)
    except sqlite3.Error as e:
        print(_db_hint(args.db) + "  （底层错误：%s）" % e)
        return 3
    finally:
        con.close()
    txt = "\n".join(out)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(txt)
        print("WROTE %s (%d chars)" % (args.out, len(txt)))
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
