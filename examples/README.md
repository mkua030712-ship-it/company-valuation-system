# examples

这里放不需要数据库就能跑的东西，用来验证环境和看懂口径。

`demo.py` 是一个最小的演示，只用 numpy 和标准库。它读 `data/sample_valuation_snapshot.csv`，跑行业相对倍数法加秩合成错配，打印一张贵和便宜的排序表，最后一行输出 `DEMO OK ✔`。Windows 默认的 GBK 控制台会把 ✔ 降级成 √，属正常。

`data/sample_valuation_snapshot.csv` 是手造的脱敏样例，不是真实行情，只用来演示列结构。

两种跑法都行：

```bash
python demo.py               # 仓库根的薄壳，转调本目录的示例
python examples/demo.py      # 直接跑本目录
```

它演示的是主脚本 `--mode value` 里"行业 PE 中位数到内在价值再到错配秩"这条链路。样例只有 price 和 pe，没有 EPS 明细，所以用 EPS 约等于 price 除以 pe 做了简化，等价于比较相对 PE。要跑真实全市场，得自备 `astock.db`，字段约定见 `../dataio/schema.md`，安装和运行见 `../docs/安装说明.md`。
