# board

这个目录只负责展示。它把 `core/` 和 `dataio/` 跑出来的真实结果渲染成一个单文件 HTML 看板，不改任何算法口径，也不写数据库，数据一律只读打开。

主要文件有四个。`make_board.py` 是生成脚本，从 `astock.db`（可选再加 `valuation_hist.db`）算出质量分、估值分、错配度和检验结果，内嵌进 HTML。`valuation_board.html` 是生成好的样品，内嵌快照日 2026-10-12 的真实数据，双击就能离线打开，也能单独发给别人。`board_preview.png` 是整页截图。`GH_PAGES.md` 写怎么把它挂到 GitHub Pages。

生成方式：

```bash
# 默认库，出最新快照的看板，约一分钟
python board/make_board.py

# 指定快照日和输出路径
python board/make_board.py --vdate 2026-10-09 --out board/valuation_board.html

# 加一节自身历史估值分位，需要 valuation_hist.db，读全库约一到两分钟
python board/make_board.py --hist-db <valuation_hist.db>

# 跳过 IC 检验，省时间
python board/make_board.py --no-test
```

看板里有五块内容：最便宜和最贵的 Top 榜，带代码、名称、行业、价格、PE、质量分、估值分、错配度；质量乘估值的四象限散点，X 轴是估值分、Y 轴是质量分；全市场错配度分布直方图，标出中性 0 和最便宜榜首的位置；预测力检验小卡，给出 E/P、rev21、dev120 的 IC、t 值、自举区间和 Bonferroni 阈值；以及可选的历史估值分位。底部是固定的口径说明和免责。

技术上它是纯前端的单文件，数据内联进 HTML，图表用原生 JS 和 SVG 画，没有任何外部 CDN 或引用，墙内和离线都能打开。编码是 UTF-8，配了中文字体栈，Windows 双击就行。图表依赖 JS 渲染，如果浏览器禁用了 JS，Top 榜的表格仍然是静态 HTML，还能看到。

所有数字都来自本地真实运行，不做美化。检验过不了阈值，就如实写 undetermined。
