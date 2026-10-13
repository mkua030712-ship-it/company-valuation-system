# -*- coding: utf-8 -*-
"""core.report —— 把算好的结果渲染成文本 / CSV 行（纯字符串，不写文件）。

入口脚本负责把本层返回的 lines 落到 --out 文件；本层不碰文件系统。
输出格式与旧版脚本逐字保持一致，保证原命令行行为不变。
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .valuation import ann_factor_for_period


def _ann_label(period, ann_override=None):
    if ann_override is not None:
        return "×%.4g（--ann-factor 强制）" % ann_override
    return "×%.4g（按报告期 %s 自动）" % (ann_factor_for_period(period), period or "?")


def _is_num(x):
    try:
        return np.isfinite(x)
    except TypeError:
        return False


def _r(x):
    """CSV 单元格：None/非有限 → 空串；否则 round 6。"""
    if x is None:
        return ""
    if not _is_num(x):
        return ""
    return round(float(x), 6)


def _s2(x):
    return "NA" if x is None or not _is_num(x) else "%.2f" % x


# ------------------------------------------------------------------ value
def render_value(vdate, fperiod, recs, hist_pcts, r_discount=0.08, earn_floor=0.005,
                 ann_override=None, codeset=None):
    out = []
    main = [r for r in recs if not r["low_quality"] and np.isfinite(r["mispr_rank"])]
    lowq = [r for r in recs if r["low_quality"]]
    main.sort(key=lambda r: r["mispr_rank"])
    main_show = [r for r in main if (codeset is None or r["code"] in codeset)]
    lowq_show = [r for r in lowq if (codeset is None or r["code"] in codeset)]

    out.append("## 模式 value (v2) — 多法内在价值与秩合成错配\n")
    out.append("- 估值快照日：%s；财务时点：%s（EPS 年化 %s，r=%.0f%%，E/P 闸=%.2f%%）"
               % (vdate, fperiod, _ann_label(fperiod, ann_override), r_discount * 100, earn_floor * 100))
    out.append("- 参与：%d 只；进主榜（盈利质量达标）：%d 只；单列低盈利质量：%d 只"
               % (len(recs), len(main), len(lowq)))
    if codeset is not None:
        out.append("- 单票过滤：仅显示 %s（行业/全市场分位、错配秩仍按全池计算）"
                   % "、".join(sorted(codeset)))
    out.append("- 内在价值三法：IV_A 行业PE×年化EPS；IV_B 年化EPS/r；IV_C 行业PB×每股净资产(BVPS)")
    out.append("- 错配 = mean(pctrank(log(price/IV)))：秩合成，>50 偏贵、<50 偏便宜（无缩尾饱和）\n")

    def show(title, sub):
        out.append("### %s（前 12）" % title)
        out.append("%-8s %-8s %-10s %8s %8s %10s %10s %10s %8s" %
                   ("code", "name", "industry", "price", "eps_ann", "IV_A", "IV_B", "IV_C", "mispr"))
        for r in sub[:12]:
            out.append("%-8s %-8s %-10s %8.2f %8.2f %10s %10s %10s %8.1f" % (
                r["code"], (r["name"] or "")[:8], (r["industry"] or "-")[:10], r["price"], r["eps_ann"],
                ("%.2f" % r["iv_a"]) if r["iv_a"] else "NA", "%.2f" % r["iv_b"],
                ("%.2f" % r["iv_c"]) if r["iv_c"] else "NA", r["mispr_rank"]))
        out.append("")

    show("最便宜（mispr_rank 最小）", main_show)
    show("最贵（mispr_rank 最大）", main_show[::-1])
    out.append("### 低盈利质量清单（E/P<%.2f%%，单列，不进主榜，前 10）" % (earn_floor * 100))
    out.append("%-8s %-8s %-10s %8s %8s %9s" % ("code", "name", "industry", "price", "eps_ann", "E/P%"))
    for r in sorted(lowq_show, key=lambda r: r["ep"])[:10]:
        out.append("%-8s %-8s %-10s %8.2f %8.2f %8.3f" % (
            r["code"], (r["name"] or "")[:8], (r["industry"] or "-")[:10], r["price"], r["eps_ann"], r["ep"] * 100))
    out.append("")
    top_vals = [r["mispr_rank"] for r in main][-15:]
    out.append("### 饱和检查：主榜最贵 15 只 mispr_rank 去重值 = %s（v1 为并列单一值 6.581）"
               % ("、".join("%.1f" % v for v in sorted(set(top_vals), reverse=True)[:5])))
    out.append("")
    hp = hist_pcts or {}
    hit = [r for r in main if r["code"] in hp and (codeset is None or r["code"] in codeset)]
    for r in hit:
        h = hp[r["code"]]
        r["hist_cheap"] = h["cheap"]
        r["pe_pct"] = h.get("pe_pct")
        r["hist_n"] = h["n"]
    hit.sort(key=lambda r: r["hist_cheap"], reverse=True)
    out.append("### 自身历史估值分位（真实纵向分位；覆盖 %d 只，历史数据回补中）" % len(hit))
    out.append("%-8s %-8s %-10s %8s %9s %8s %6s" % ("code", "name", "industry", "PE", "PE分位", "便宜度", "天数"))
    for r in hit[:10]:
        out.append("%-8s %-8s %-10s %8s %9s %8.1f %6d" % (
            r["code"], (r["name"] or "")[:8], (r["industry"] or "-")[:10],
            ("%.2f" % r["pe"]) if r.get("pe") else "NA",
            ("%.1f" % r["pe_pct"]) if r.get("pe_pct") is not None else "NA",
            r["hist_cheap"], r["hist_n"]))
    out.append("")
    return out, dict(n=len(recs), n_main=len(main), n_lowq=len(lowq), n_hist=len(hit))


# ------------------------------------------------------------------ test
def render_test(res):
    out = []
    out.append("## 模式 test (v2) — 真实估值因子（时点 PE 重建）的预测力\n")
    out.append("- 有效交易日：%d（%s ~ %s）；股票池 %d 只；再平衡 %d 日"
               % (res["n_dates"], res["date0"], res["date1"], res["n_codes"], res["rebal_days"]))
    out.append("- 关键升级：'E/P(pit价值)' 用 pub_date<=t 的财务 + 当日收盘重建逐日 PE，**是真估值因子**，非价格代理")
    out.append("- 方向：E/P 越大=越便宜 → 预期**正 IC**；rev21/dev120 越大=越贵/越强 → 预期负 IC")
    out.append("- 检验：rank IC + 五分组(Q5最便宜-Q1最贵) + 扣往返 %.2f%% + 对市场因子回归取 alpha + 自举 95%%CI\n"
               % (res["cost"] * 100))
    out.append("Bonferroni（N=%d，α=0.05）|t| 临界 ≈ %.2f\n" % (res["n_trials"], res["thr"]))
    out.append("%-12s %5s %9s %7s %12s %11s %9s %8s %7s" %
               ("proxy", "h", "IC_mean", "IC_t", "IC95%CI", "Q5-Q1净", "alpha", "a_t", "n"))
    for row in res["rows"]:
        if row["n"] == 0:
            out.append("%-12s %5d %9s %7s %12s %11s %9s %8s %7d" %
                       (row["proxy"], row["h"], "-", "-", "-", "-", "-", "-", 0))
            continue
        out.append("%-12s %5d %9.4f %7.2f %12s %11.4f %9.4f %8.2f %7d" % (
            row["proxy"], row["h"], row["ic_mean"], row["ic_t"],
            "[%+.3f,%+.3f]" % (row["lo"], row["hi"]), row["net"], row["alpha"], row["a_t"], row["n"]))
    out.append("")
    out.append("判读：|IC_t|<%.2f 且自举 CI 跨 0 → 未通过。样本受限于本地日K约 13.5 个月。" % res["thr"])
    out.append("")
    return out


# ------------------------------------------------------------------ rank
CSV_COLS = ["code", "name", "industry", "price", "pe", "quality_score", "valuation_score",
            "mispricing", "composite_score", "q_n", "v_n", "roe", "gross_margin", "net_margin",
            "rev_yoy", "net_yoy", "eps", "book_yield", "sales_yield"]


def gated_sorted(rows):
    gated = [r for r in rows.values() if r.get("passed_gate") and np.isfinite(r.get("composite_score", np.nan))]
    gated.sort(key=lambda r: r["composite_score"], reverse=True)
    return gated


def render_rank(vdate, fperiod, ann, r_discount, universe_desc, n_rows, exclude_st,
                weights, gate_thresh, quality_gate, gated, top):
    out = []
    out.append("## 模式 rank — 质量+估值排序")
    out.append("- 估值快照日：%s；财务报告期：%s（EPS 年化 ×%.4g，r=%.0f%%）" % (vdate, fperiod, ann, r_discount * 100))
    out.append("- 股票池：%s；参与打分 %d 只（剔 ST=%s）" % (universe_desc, n_rows, exclude_st))
    out.append("- 质量权重：%s" % ", ".join("%s=%.2f" % (k, w) for k, w in weights.items()))
    out.append("- 质量关：质量分 ≥ %.1f（该池第 %.0f 百分位）" % (gate_thresh, quality_gate))
    out.append("- 综合分 = 0.5·z(质量分) + 0.5·z(估值分)，仅在通过质量关的池内计算并百分位化\n")

    cnt = Counter((r["industry"] or "-") for r in gated[:top])
    out.append("- 前 %d 名行业分布 top5：%s" % (top, ", ".join("%s×%d" % (k, v) for k, v in cnt.most_common(5))))
    out.append("通过质量关：%d 只。以下为前 %d 名（按综合分降序）：" % (len(gated), top))
    out.append("%-7s %-8s %-10s %7s %8s %7s %7s %8s %7s %3s %3s" %
               ("code", "name", "industry", "price", "pe", "Q", "V", "mispr", "comp", "qN", "vN"))
    for r in gated[:top]:
        out.append(_fmt_rank_row(r))
    out.append("")
    return out


def _fmt_rank_row(r):
    return "%-7s %-8s %-10s %7.2f %8s %7.1f %7.1f %8s %7.1f %3d %3d" % (
        r["code"], (r["name"] or "")[:8], (r["industry"] or "-")[:10], r["price"] or float("nan"),
        ("%.1f" % r["pe"]) if r["pe"] else "NA",
        r["quality_score"], r["valuation_score"],
        ("%.3f" % r["mispricing"]) if np.isfinite(r["mispricing"]) else "NA",
        r["composite_score"], r["q_n"], r["v_n"])


def watchlist_rows(gated):
    """返回 CSV 数据行（list of list），供调用方写文件。"""
    out = []
    for r in gated:
        nm = None
        if r.get("net_profit") is not None and r.get("revenue"):
            nm = r["net_profit"] / r["revenue"] * 100.0
        out.append([
            r["code"], r["name"], r["industry"],
            _r(r["price"]), _r(r["pe"]), _r(r["quality_score"]), _r(r["valuation_score"]),
            _r(r["mispricing"]), _r(r["composite_score"]), r["q_n"], r["v_n"],
            _r(r["roe"]), _r(r["gross_margin"]), _r(nm), _r(r["rev_yoy"]), _r(r["net_yoy"]),
            _r(r["eps"]), _r(r["book_yield"]), _r(r["sales_yield"])])
    return out


# ------------------------------------------------------------------ diag
def render_diag(vdate, fperiod, universe_desc, codes, q, v, mis, pe, gate_thresh,
                quality_gate, n_gated):
    out = []
    out.append("## 模式 diag — 诊断")
    out.append("- 估值快照日：%s；财务报告期：%s" % (vdate, fperiod))
    out.append("- 股票池：%s；样本 %d 只\n" % (universe_desc, len(codes)))

    def dump(title, arr):
        s = _desc(arr)
        out.append("### %s 分布（%d 个有效值）" % (title, s.get("n", 0)))
        if s:
            out.append("mean=%.2f std=%.2f min=%.2f p10=%.2f p25=%.2f p50=%.2f p75=%.2f p90=%.2f max=%.2f" %
                       (s["mean"], s["std"], s["min"], s["p10"], s["p25"], s["p50"], s["p75"], s["p90"], s["max"]))
        out.append("")
    dump("质量分", q)
    dump("估值分", v)
    dump("错配度 mispricing（>0 偏贵）", mis)
    dump("PE（原值，含负）", pe)

    from . import stats
    out.append("### 横截面相关（Spearman）")
    out.append("- corr(质量分, 估值分) = %.3f" % stats.spearman(q, v))
    out.append("- corr(质量分, mispricing) = %.3f" % stats.spearman(q, mis))
    out.append("- corr(估值分, mispricing) = %.3f" % stats.spearman(v, mis))
    out.append("- corr(质量分, PE) = %.3f" % stats.spearman(q, pe))
    out.append("- corr(估值分, PE) = %.3f" % stats.spearman(v, pe))
    out.append("")
    out.append("### 质量关")
    out.append("- 阈值：质量分 ≥ %.1f（第 %.0f 百分位）" % (gate_thresh, quality_gate))
    out.append("- 通过 %d / %d 只（%.1f%%）\n" % (n_gated, len(codes), 100.0 * n_gated / len(codes)))
    return out


def _desc(arr):
    from . import stats
    return stats.desc_stats(arr)


def forward_title():
    return ["### 前向收益检验（简单、诚实标注）"]


def anchor_line(anchor, end, span, point_in_time):
    return "- 锚点日：%s（区间 %s ~ %s，%d 个交易日）；时点守卫=%s" % (anchor, anchor, end, span, point_in_time)


def render_forward_body(end, ft):
    out = []
    if ft is None:
        return out
    out.append("- 有效样本：%d 只（持有到 %s 的 qfq 收益）" % (ft["kept"], end))
    if ft["kept"] < 30:
        out.append("- 样本 < 30，统计不可靠，仅记录不做判读。\n")
        return out
    out.append("- IC（Spearman，分数 vs 前向收益）：质量分 = %.3f；估值分 = %.3f" % (ft["ic_q"], ft["ic_v"]))
    for key, label in (("quality", "质量分"), ("valuation", "估值分")):
        t = ft["terciles"].get(key)
        if not t:
            continue
        m = t["means"]
        out.append("- %s三分组（低/中/高）平均前向收益：%.4f / %.4f / %.4f（低-高差 %.4f，n=%d/%d/%d）"
                   % (label, m[0], m[1], m[2], t["diff"], t["ns"][0], t["ns"][1], t["ns"][2]))
    out.append("")
    return out


def sample_limits():
    return [
        "- 财务只有 20260630 / 20260331 两期 → 无法做长周期质量稳定性（如 ROIC 连续为正年数）。",
        "- 估值快照仅 3 个交易日 → 无法做 PE/PB 历史分位；估值分只是当期横截面。",
        "- 无账面价值/现金流/负债/股利/分析师预期/融券数据 → 质量六维中「现金流」「资本配置」「财务稳健」多数项缺失，以可得代理近似。",
        "- 前向收益检验为单一锚点、单窗口、未扣费、未做多重检验 → 只作一致性观察，不构成有效性结论（按研究方案应判 undetermined）。",
        "",
    ]


# ------------------------------------------------------------------ percentile
def render_percentile(ncode, nrow, recs, min_days, top):
    lines = []
    lines.append("## 历史估值分位（真实纵向分位；数据源 valuation_hist.db）\n")
    lines.append("- 库内：%d 只 / %d 行；进入分位计算（历史≥%d日）：%d 只" % (ncode, nrow, min_days, len(recs)))
    lines.append("- 便宜度 = mean(100 − 自身历史分位)；>50 偏便宜、<50 偏贵\n")

    def show(title, sub):
        lines.append("### %s（前 %d）" % (title, top))
        lines.append("%-8s %-8s %-10s %7s %7s %7s %7s %7s %7s %6s" %
                     ("code", "name", "industry", "PE", "PB", "PE分位", "PB分位", "PS分位", "便宜度", "天数"))
        for r in sub:
            lines.append("%-8s %-8s %-10s %7s %7s %7s %7s %7s %7.1f %6d" % (
                r["code"], (r["name"] or "")[:8], (r["industry"] or "-")[:10],
                _s2(r.get("pe")), _s2(r.get("pb")), _s2(r.get("pe_pct")),
                _s2(r.get("pb_pct")), _s2(r.get("ps_pct")), r["cheap"], r["n"]))
        lines.append("")
    show("最便宜（自身历史分位最低）", recs[:top])
    show("最贵（自身历史分位最高）", recs[-top:][::-1])
    return lines
