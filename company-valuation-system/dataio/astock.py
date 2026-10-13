# -*- coding: utf-8 -*-
"""dataio.astock —— A 股主库 / 历史估值库的读取接口（本层唯一碰 sqlite 的地方）。

你只要实现下面这些函数（或改它们的 SQL），就能把系统接到**你自己的库**上；
core/ 里的算法一行都不用动。字段/单位约定见 schema.md。

返回一律是「内存数据」：dict / list / numpy 数组。
"""
from __future__ import annotations
import numpy as np

MIN_ROWS_PER_DAY = 3000     # 有效交易日判据：当日 kline_daily 行数 ≥ 此值（剔除休市/残缺日）
FUND_MIN_COVERAGE = 0.5     # 财务期「充分覆盖」阈值：行数 ≥ 最大期行数×此比例（避免单行残期）


# ---------------------------------------------------------------- 交易日 / 快照日
def load_trade_dates(cur, min_rows=MIN_ROWS_PER_DAY):
    """真实交易日（升序）：当日 kline_daily 行数 ≥ min_rows。"""
    cur.execute("SELECT date FROM kline_daily GROUP BY date HAVING COUNT(*)>=? ORDER BY date", (min_rows,))
    return [r[0] for r in cur.fetchall()]


def load_valid_dates(cur, min_rows=MIN_ROWS_PER_DAY):
    """load_trade_dates 的别名（供质量+估值排序器使用）。"""
    return load_trade_dates(cur, min_rows)


def latest_valuation_date(cur):
    return cur.execute("SELECT MAX(date) FROM valuation_daily").fetchone()[0]


def latest_fund_period(cur, min_coverage=FUND_MIN_COVERAGE):
    """选「覆盖充分的最近报告期」：只在行数 ≥ 最大期行数×min_coverage 的期中取最近一期。
    （避免只有 1 行的残期把股票池塌缩；这是健壮性修复，不改变因子定义。）"""
    rows = cur.execute("SELECT period, COUNT(*) FROM fin_report GROUP BY period").fetchall()
    if not rows:
        return None
    counts = {r[0]: r[1] for r in rows}
    thr = max(1, int(max(counts.values()) * min_coverage))
    eligible = [p for p, n in counts.items() if n >= thr]
    return max(eligible) if eligible else max(counts)


# ---------------------------------------------------------------- 估值快照 / 股票池
def load_valuation_snapshot(cur, date):
    """某日估值快照：{code: {code,name,industry,price,pe,total_mv,circ_mv}}。"""
    cur.execute("SELECT code,name,industry,price,pe,total_mv,circ_mv FROM valuation_daily WHERE date=?", (date,))
    return {r["code"]: dict(r) for r in cur.fetchall()}


def load_universe(cur, date):
    """load_valuation_snapshot 的语义化别名（= 当日可打分股票池）。"""
    return load_valuation_snapshot(cur, date)


# ---------------------------------------------------------------- 财务报表
def load_financials(cur, period):
    """某报告期的财务：{code: {...含 pub_date}}（质量+估值排序器用）。"""
    cur.execute("""SELECT code,name,industry,eps,revenue,rev_yoy,net_profit,net_yoy,
                          roe,gross_margin,pub_date FROM fin_report WHERE period=?""", (period,))
    return {r["code"]: dict(r) for r in cur.fetchall()}


def load_financials_pit(cur):
    """全量时点财务：{code: [(pub_date, period, eps, net_profit, roe, rev_yoy), ...] 升序}。

    用于时点重建（pub_date<=t），避免前视。主入口 value/test 都用它。
    """
    cur.execute("SELECT code,period,eps,net_profit,roe,rev_yoy,pub_date FROM fin_report")
    out = {}
    for r in cur.fetchall():
        pd_ = r["pub_date"] or r["period"]
        out.setdefault(r["code"], []).append(
            (pd_, r["period"], r["eps"], r["net_profit"], r["roe"], r["rev_yoy"]))
    for c in out:
        out[c].sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------- 股本 / 行业
def load_shares(cur):
    """最新一期总股本/流通股本：{code: {total_shares, float_shares}}。"""
    cur.execute("""SELECT code,total_shares,float_shares,change_date FROM float_share_hist fs
                   WHERE change_date=(SELECT MAX(change_date) FROM float_share_hist
                                      WHERE code=fs.code)""")
    return {r["code"]: dict(total_shares=r["total_shares"], float_shares=r["float_shares"])
            for r in cur.fetchall()}


def load_industry_map(cur):
    """行业兜底分类：{code: industry}。"""
    cur.execute("SELECT code, industry FROM stock_industry")
    return {r["code"]: r["industry"] for r in cur.fetchall()}


def load_stock_names(cur):
    """股票名称：{code: name}。"""
    cur.execute("SELECT code, name FROM stock_industry")
    return {r["code"]: r["name"] for r in cur.fetchall()}


# ---------------------------------------------------------------- 行情
def load_kline(cur, dates):
    """前复权收盘矩阵：返回 (codes, dates, M)，M[code_i, date_j]（缺失 NaN）。"""
    didx = {d: i for i, d in enumerate(dates)}
    dset = set(dates)
    cur.execute("SELECT code,date,close FROM kline_daily WHERE adjust='qfq'")
    rows = cur.fetchall()
    codes = sorted({r["code"] for r in rows if r["date"] in dset})
    cidx = {c: i for i, c in enumerate(codes)}
    M = np.full((len(codes), len(dates)), np.nan)
    for r in rows:
        if r["date"] in dset:
            M[cidx[r["code"]], didx[r["date"]]] = r["close"]
    return codes, dates, M


def load_close_on(cur, date):
    """某日 qfq 收盘：{code: close}。"""
    cur.execute("SELECT code,close FROM kline_daily WHERE date=? AND adjust='qfq'", (date,))
    return {r["code"]: r["close"] for r in cur.fetchall()}


def load_index_series(cur, dates):
    """市场因子：指数收盘对齐到 dates（缺失 NaN）。按 sh000001 → 000001 → sh000300 找第一个存在的。"""
    idx = {}
    for code in ("sh000001", "000001", "sh000300"):
        cur.execute("SELECT date,close FROM kline_daily WHERE code=? ORDER BY date", (code,))
        rows = cur.fetchall()
        if rows:
            idx = {r["date"]: r["close"] for r in rows}
            break
    return np.array([idx.get(d, np.nan) for d in dates], dtype=float)


# ---------------------------------------------------------------- 历史估值库
def count_valuation_hist(cur):
    """历史估值库规模：(股票数, 行数)。"""
    return cur.execute("SELECT COUNT(DISTINCT code), COUNT(*) FROM valuation_hist").fetchone()


def iter_valuation_hist(cur):
    """流式产出 (code, [[pe_ttm, pb, ps], ...]) 分组，按 code,date 升序。

    流式而非一次性读入：历史库可达千万行，逐只票 flush 控制内存。
    """
    cur.execute("SELECT code, pe_ttm, pb, ps FROM valuation_hist ORDER BY code, date")
    code0 = None
    buf = []
    for r in cur:
        c = r[0]
        if c != code0:
            if code0 is not None:
                yield code0, buf
            code0, buf = c, []
        buf.append([_ff(r[1]), _ff(r[2]), _ff(r[3])])
    if code0 is not None:
        yield code0, buf


def _ff(x):
    try:
        return float(x) if x is not None else np.nan
    except Exception:
        return np.nan
