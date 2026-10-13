# dataio · 数据接口层：期望的表 / 字段 / 单位

核心算法层（`core/`）只吃内存数据；**所有读库逻辑都在本层**。
你只要让 `dataio/astock.py` 里的读取函数能从你的数据源拿到下面这些结构，系统就能跑；
字段名不同就改 SQL / 或照 `example_adapter.py` 写一个适配器。

## 1. astock 主库（`--db`，SQLite，只读 `mode=ro`）

| 表 | 用到的字段 | 单位 | 说明 |
|---|---|---|---|
| `kline_daily` | `code, date, close, adjust` | close=元 | 只用 `adjust='qfq'`（前复权）。有效交易日 = 当天行数 ≥ 3000 |
| `valuation_daily` | `date, code, name, industry, price, pe, total_mv, circ_mv` | price=元；市值=**万元** | `pe` 可为负/空 |
| `fin_report` | `period, code, name, industry, eps, revenue, rev_yoy, net_profit, net_yoy, roe, gross_margin, pub_date` | 收入/净利=**元** | `pub_date` 用于时点重建，避免前视 |
| `float_share_hist` | `code, change_date, total_shares, float_shares` | 股 | 用于 BVPS 近似 |
| `stock_industry` | `code, name, industry` | — | 行业兜底 |

## 2. 历史估值库（`--hist-db`，SQLite，只读）

| 表 | 用到的字段 | 说明 |
|---|---|---|
| `valuation_hist` | `code, date, pe_ttm, pb, ps` | 逐日历史估值序列（本机实测自 2018 起） |

## 3. 单位约定（最容易踩的坑）

- `fin_report.revenue / net_profit` 是**元**；`valuation_daily.total_mv / circ_mv` 是**万元**。
  脚本按此换算（如 `sales_yield = revenue / (total_mv × 1e4)`）。
- `float_share_hist.total_shares` 是**股**；`eps × 总股本 ≈ 净利润`，口径自洽可自检。

## 4. 代码 / 交易日约定

- 代码统一按库内字符串匹配；`--codes` 会自动补零到 6 位。
- 有效交易日判据：`SELECT date FROM kline_daily GROUP BY date HAVING COUNT(*)>=3000`
  ：剔除休市日/残缺日（幽灵行）。阈值可用 `--min-rows-per-day` 调。

## 5. 想接自己的库，改哪里？

1. **字段/单位一致、仍是 SQLite**：直接用 `dataio/astock.py`，命令行 `--db <你的库>` 即可，**零改动**。
2. **字段名或单位不同**：改 `dataio/astock.py` 里对应函数的 SQL；
   或按 `dataio/example_adapter.py` 的签名写一个适配器，再把入口脚本的 import 换过去。
3. **不是 SQLite（CSV / Parquet / 别的库）**：实现同样签名的函数返回等价内存结构即可；
   `core/` 与入口脚本都不用动。
