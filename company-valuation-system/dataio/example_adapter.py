# -*- coding: utf-8 -*-
"""dataio.example_adapter —— 空壳适配器：演示「接自己的库」要改哪几处。

本文件**不连任何真实数据库**，全部 raise NotImplementedError。
它是给使用者的模板：把你的数据源（CSV / Parquet / 别的 SQL / 落库后的新表名）
映射成本系统需要的「内存数据」，core/ 的算法无需改动。

两种接法：
  A. 你的库仍是 SQLite 且字段/单位一致 → 直接用 dataio.astock，什么都不用改；
  B. 字段名 / 单位 / 存储形态不同 → 照抄本文件的函数签名，改写里面的读取逻辑。

每个函数下方的「期望返回」就是本系统对数据的硬性约定。
"""
from __future__ import annotations

import numpy as np


def load_valuation_snapshot(date):
    """期望返回 {code: {code,name,industry,price,pe,total_mv,circ_mv}}。
    单位：price=元；total_mv/circ_mv=万元；pe 可为负或 None。"""
    raise NotImplementedError("把你的估值快照读进来，返回上面的 dict 结构")


def load_financials(period):
    """期望返回 {code: {eps,revenue,rev_yoy,net_profit,net_yoy,roe,gross_margin,pub_date}}。
    单位：revenue/net_profit=元；pub_date 为披露日（做时点检验，避免前视）。"""
    raise NotImplementedError("读某报告期财务")


def load_financials_pit():
    """期望返回 {code: [(pub_date, period, eps, net_profit, roe, rev_yoy), ...] 升序}。"""
    raise NotImplementedError("读全量时点财务，按 pub_date 升序")


def load_kline(dates):
    """期望返回 (codes, dates, M)；M 为前复权收盘矩阵（缺失 NaN）。"""
    raise NotImplementedError("读前复权日K，拼成矩阵")


def load_trade_dates(min_rows=3000):
    """期望返回真实交易日字符串列表（升序）。"""
    raise NotImplementedError("返回有效交易日")


def load_shares():
    """期望返回 {code: {total_shares, float_shares}}。单位：股。"""
    raise NotImplementedError("读最新股本")


def load_industry_map():
    """期望返回 {code: industry}。"""
    raise NotImplementedError("读行业分类")


def load_index_series(dates):
    """期望返回市场指数收盘序列（对齐 dates，缺失 NaN），用于风险调整。"""
    raise NotImplementedError("读市场指数收盘")


def iter_valuation_hist():
    """期望产出 (code, [[pe_ttm, pb, ps], ...]) 分组（按 code,date 升序）。"""
    raise NotImplementedError("流式读逐日历史估值")


def count_valuation_hist():
    """期望返回 (股票数, 行数)。"""
    raise NotImplementedError("返回历史估值库规模")
