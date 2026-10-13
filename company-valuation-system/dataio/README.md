# dataio

这一层把读库和读文件的操作收到一起，向 `core/` 只吐内存数据，也就是 dict、list 和 numpy 数组。仓库不自带任何数据库，`*.db` 一律不入库。

`paths.py` 负责路径解析和只读连接。它按 `--db`、`--hist-db`、环境变量 `ASTOCK_DB`、仓库相对位置的顺序找库，`open_ro(path)` 用只读方式打开，文件不存在时抛 FileNotFoundError，入口脚本据此给出友好提示。

`astock.py` 是读取接口。对外的主要函数有 `load_valuation_snapshot`、`load_universe`、`load_kline`、`load_close_on`、`load_financials`、`load_financials_pit`、`load_valid_dates`、`load_index_series`、`load_shares`、`load_industry_map`、`load_stock_names`、`latest_valuation_date`、`latest_fund_period`、`iter_valuation_hist` 和 `count_valuation_hist`。

`schema.md` 记录期望的表、字段和单位，接自己的库之前先看它。`example_adapter.py` 是一个空壳适配器，不连真库，用来演示要改哪几处。

接自己的数据时改哪里：字段和单位一致、仍然是 SQLite，就零改动，直接 `--db` 指过去；字段名或单位不同，就改 `astock.py` 里对应函数的 SQL，或者照 `example_adapter.py` 写一个适配器；不是 SQLite，比如 CSV、Parquet 或者别的库，就实现同名函数返回等价的内存结构，`core/` 不用动。细节见 `schema.md` 最后一节。
