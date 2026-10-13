#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valuation_percentile.py — 薄入口（真实自身历史估值分位）
================================================================================
把「公司贵不贵」从当期横截面升级为**对其自身历史的纵向分位**。
本文件只做「参数解析 + 调用」：
  · 算法 → core/percentile（分位计算）、core/report（渲染）
  · 数据 → dataio/（历史估值库 + 名称/行业）

用法：
  py -3.12 valuation_percentile.py --hist-db <valuation_hist.db> --min-days 250 --lookback 750 --top 25 --out pct_out.txt
免责：研究方法论原型，不构成投资建议。
"""
from __future__ import annotations
import argparse
import sqlite3
import sys

from core import percentile, report
from dataio import astock, paths

DEF_HIST = paths.resolve_hist()
DEF_SRC = paths.resolve_db()


def _db_hint(path):
    return (
        "[提示] 打不开数据库：%s\n"
        "  本仓库不含数据库（体积原因，*.db 不入库）。三种做法：\n"
        "  1) 先验证环境（不需要数据库）：   python demo.py\n"
        "  2) 跑真实数据：准备 valuation_hist.db / astock.db 后，用 --hist-db / --src-db 指过去\n"
        "  3) 接自己的库：改 dataio/astock.py（见 dataio/schema.md 与 dataio/example_adapter.py）\n" % path
    )


def build_parser():
    ap = argparse.ArgumentParser(description="自身历史估值分位（薄入口）")
    ap.add_argument("--hist-db", dest="hist_db", default=DEF_HIST, help="历史估值库路径（只读）")
    ap.add_argument("--src-db", dest="src_db", default=DEF_SRC, help="主库路径（取名称/行业；只读）")
    ap.add_argument("--lookback", type=int, default=750)   # 约 3 年
    ap.add_argument("--min-days", dest="min_days", type=int, default=250)   # 至少约 1 年
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", default=None)
    return ap


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")   # GBK 控制台安全：不可编码字符降级而非崩溃
        except Exception:
            pass
    args = build_parser().parse_args()
    if args.lookback < args.min_days:
        print("--lookback (%d) 必须 ≥ --min-days (%d)，否则任何个股都不会进入分位计算"
              % (args.lookback, args.min_days))
        return 2
    try:
        hcon = paths.open_ro(args.hist_db)
    except FileNotFoundError:
        print(_db_hint(args.hist_db))
        return 2
    try:
        hcur = hcon.cursor()
        ncode, nrow = astock.count_valuation_hist(hcur)
        hp = percentile.historical_percentiles(astock.iter_valuation_hist(hcur),
                                               min_days=args.min_days, lookback=args.lookback)
    except sqlite3.Error as e:
        print(_db_hint(args.hist_db) + "  （底层错误：%s）" % e)
        return 3
    finally:
        hcon.close()

    # 名称 / 行业（从主库取；取不到就留空）
    name_map, ind_map = {}, {}
    try:
        scon = paths.open_ro(args.src_db)
        try:
            scur = scon.cursor()
            name_map = astock.load_stock_names(scur)
            ind_map = astock.load_industry_map(scur)
        finally:
            scon.close()
    except (FileNotFoundError, sqlite3.Error):
        pass

    recs = []
    for code, d in hp.items():
        d["code"] = code
        d["name"] = name_map.get(code, "")
        d["industry"] = ind_map.get(code, "")
        recs.append(d)
    recs.sort(key=lambda x: x["cheap"], reverse=True)

    lines = report.render_percentile(ncode, nrow, recs, args.min_days, args.top)
    txt = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(txt)
        print("WROTE %s (%d chars)" % (args.out, len(txt)))
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
