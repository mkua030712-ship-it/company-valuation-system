# -*- coding: utf-8 -*-
"""dataio —— 数据接口层（唯一碰数据库/文件的地方）。

设计原则：**核心算法层（core/）只吃内存数据**；所有「读库/读文件」都收敛到本层。
仓库**不自带任何数据库**。要接你自己的库，改这里的解析逻辑 / 实现这些读取函数。

公共接口（见 astock.py）：
  open_ro / load_valuation_snapshot / load_kline / load_financials /
  load_financials_pit / load_valid_dates / load_index_series / load_shares /
  load_industry_map / load_close_on / latest_valuation_date / latest_fund_period /
  iter_valuation_hist / count_valuation_hist

路径解析：paths.py（--db / --hist-db / 环境变量 ASTOCK_DB / 相对位置）。
字段与单位说明：schema.md。空壳适配器：example_adapter.py。
"""
