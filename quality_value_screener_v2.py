#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quality_value_screener_v2.py — 薄入口（质量 + 估值 双维选股排序）
================================================================================
本文件只做「参数解析 + 调用」：
  · 算法 → core/quality（质量分/质量闸/综合分）、core/valuation（估值分/错配）、core/report（渲染）
  · 数据 → dataio/（唯一碰数据库的地方；不含数据库本体）

原命令行行为保持不变：
  rank：质量分 + 估值分 + 综合分排序（含行业中性 --val-neutral），可写 watchlist.csv
  diag：分布/相关/前向收益检验（含时点守卫）

用法：
  py -3.12 quality_value_screener_v2.py --mode both --top 40 --watchlist watchlist.csv --out qv_out.txt
免责：研究方法论原型，不构成投资建议。所有数字来自真实运行。
"""
from __future__ import annotations
import argparse
import csv
import sqlite3
import sys

import numpy as np

from core import quality, report, stats, testing, valuation
from dataio import astock, paths

DEFAULT_DB = paths.resolve_db()

MIN_PEER_N = 5
R_DISCOUNT = 0.08


def _db_hint(path):
    return (
        "[提示] 打不开数据库：%s\n"
        "  本仓库不含数据库（体积原因，*.db 不入库）。三种做法：\n"
        "  1) 先验证环境（不需要数据库）：   python demo.py\n"
        "  2) 跑真实数据：准备 astock.db 后，用 --db <path>，或放到 data/astock.db，或设环境变量 ASTOCK_DB\n"
        "  3) 接自己的库：改 dataio/astock.py（见 dataio/schema.md 与 dataio/example_adapter.py）\n" % path
    )


def _read_codes_file(path):
    want = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            t = line.strip().split(",")[0].strip().strip('"')
            if t:
                want.add(t.zfill(6) if t.isdigit() else t)
    return want


def universe_desc(args):
    if args.universe == "industry":
        return "行业=%s" % args.industry
    if args.universe == "file":
        return "文件=%s" % args.universe_file
    if args.codes:
        return "指定代码=%s" % args.codes
    return "全市场"


def build_rows(cur, args):
    vdate = args.vdate or astock.latest_valuation_date(cur)
    fperiod = args.fperiod or astock.latest_fund_period(cur)
    val = astock.load_valuation_snapshot(cur, vdate)
    fund = astock.load_financials(cur, fperiod)
    shares = astock.load_shares(cur)
    ind_map = astock.load_industry_map(cur)
    want = None
    if args.universe == "file" and args.universe_file:
        want = _read_codes_file(args.universe_file)
    elif not (args.universe == "industry" and args.industry) and args.codes:
        want = stats.normalize_codes(args.codes)
    rows = quality.build_universe(val, fund, shares, ind_map, exclude_st=args.exclude_st,
                                  universe=args.universe, industry=args.industry, want_codes=want)
    return vdate, fperiod, rows


def score_all(rows, args, fperiod):
    weights = quality.parse_weights(args.q_weights) if args.q_weights else quality.DEFAULT_Q_WEIGHTS
    ann = args.ann_factor if args.ann_factor is not None else valuation.ann_factor_for_period(fperiod)
    quality.score_quality(rows, weights)
    valuation.compute_valuation_scores(rows, r_discount=args.r_discount, ann=ann,
                                       min_peer=args.min_peer_n, neutral=args.val_neutral)
    gate_thresh = quality.composite(rows, args.quality_gate)
    return weights, ann, gate_thresh


def mode_rank(cur, args, out):
    vdate, fperiod, rows = build_rows(cur, args)
    if not rows:
        out.append("股票池为空，请检查 --universe/--industry/--codes 参数。")
        return None
    weights, ann, gate_thresh = score_all(rows, args, fperiod)
    gated = report.gated_sorted(rows)
    out.extend(report.render_rank(vdate, fperiod, ann, args.r_discount, universe_desc(args),
                                  len(rows), args.exclude_st, weights, gate_thresh,
                                  args.quality_gate, gated, args.top))
    if args.watchlist:
        with open(args.watchlist, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(report.CSV_COLS)
            for row in report.watchlist_rows(gated):
                w.writerow(row)
        print("WROTE watchlist %s (%d rows)" % (args.watchlist, len(gated)))
    return dict(vdate=vdate, fperiod=fperiod, n=len(rows), n_gated=len(gated))


def mode_diag(cur, args, out):
    vdate, fperiod, rows = build_rows(cur, args)
    weights, ann, gate_thresh = score_all(rows, args, fperiod)
    codes = list(rows.keys())
    q = np.array([rows[c]["quality_score"] for c in codes], float)
    v = np.array([rows[c]["valuation_score"] for c in codes], float)
    mis = np.array([rows[c]["mispricing"] for c in codes], float)
    pe = np.array([rows[c]["pe"] if rows[c]["pe"] else np.nan for c in codes], float)
    n_gated = sum(1 for c in codes if rows[c].get("passed_gate"))

    out.extend(report.render_diag(vdate, fperiod, universe_desc(args), codes, q, v, mis, pe,
                                  gate_thresh, args.quality_gate, n_gated))

    out.extend(report.forward_title())
    dates = astock.load_valid_dates(cur, astock.MIN_ROWS_PER_DAY)
    if len(dates) < 10:
        out.append("- 有效交易日不足，跳过。\n")
    else:
        anchor = testing.pick_anchor(dates, args.test_anchor)
        end = dates[-1]
        if anchor >= end:
            out.append("- 锚点 %s 之后无交易日，跳过。\n" % anchor)
        else:
            span = len([d for d in dates if anchor <= d <= end])
            out.append(report.anchor_line(anchor, end, span, args.point_in_time))
            close_a = astock.load_close_on(cur, anchor)
            close_e = astock.load_close_on(cur, end)
            pub = [rows[c].get("pub_date") for c in codes]
            ft = testing.forward_test(codes, q, v, pub, close_a, close_e, anchor,
                                      point_in_time=args.point_in_time)
            out.extend(report.render_forward_body(end, ft))

    out.append("### 样本限制（诚实）")
    out.extend(report.sample_limits())
    return dict(n=len(codes), n_gated=n_gated)


def build_parser():
    ap = argparse.ArgumentParser(description="质量+估值选股排序器（薄入口）")
    ap.add_argument("--db", default=DEFAULT_DB, help="astock.db 路径（只读；也可用环境变量 ASTOCK_DB）")
    ap.add_argument("--mode", choices=["rank", "diag", "both"], default="rank")
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--out", default=None)
    ap.add_argument("--watchlist", default=None)
    ap.add_argument("--universe", choices=["all", "industry", "file"], default="all")
    ap.add_argument("--industry", default=None)
    ap.add_argument("--universe-file", dest="universe_file", default=None)
    ap.add_argument("--codes", default=None)
    ap.add_argument("--q-weights", dest="q_weights", default=None)
    ap.add_argument("--quality-gate", dest="quality_gate", type=float, default=50.0)
    ap.add_argument("--val-neutral", dest="val_neutral", action="store_true", default=False,
                    help="估值分在行业内再排序，抑制板块下注")
    ap.add_argument("--exclude-st", dest="exclude_st", action="store_true", default=True)
    ap.add_argument("--include-st", dest="exclude_st", action="store_false")
    ap.add_argument("--vdate", default=None)
    ap.add_argument("--fperiod", default=None)
    ap.add_argument("--r-discount", dest="r_discount", type=float, default=R_DISCOUNT)
    ap.add_argument("--ann-factor", dest="ann_factor", type=float, default=None)
    ap.add_argument("--min-peer-n", dest="min_peer_n", type=int, default=MIN_PEER_N)
    ap.add_argument("--test-anchor", dest="test_anchor", default="2026-08-31")
    ap.add_argument("--point-in-time", dest="point_in_time", action="store_true", default=True)
    ap.add_argument("--no-point-in-time", dest="point_in_time", action="store_false")
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
    out.append("质量+估值选股排序器 — 真实运行输出")
    out.append("生成命令见 诊断.md；数据源：%s（只读）\n" % args.db)
    try:
        cur = con.cursor()
        if args.mode in ("rank", "both"):
            mode_rank(cur, args, out)
        if args.mode in ("diag", "both"):
            mode_diag(cur, args, out)
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
