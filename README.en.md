# Company Value & Mispricing

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-numpy-informational)](requirements.txt)

A research prototype that asks whether an A-share company is cheap or expensive, and whether that question can be answered honestly at all. It splits the problem into three steps: score companies on quality and valuation using several independent measures, test whether those scores predict future returns, then decide under transaction costs and a multiple-testing threshold whether the evidence supports a conclusion. When it cannot clear the bar, it says so instead of picking a flattering number out of the noise.

The project depends only on numpy and the Python standard library. pandas, scipy, and sklearn are deliberately left out, because the point is reproducibility rather than throughput. The repository ships no database. To run it on real data you provide a SQLite database that matches the schema in `dataio/schema.md`.

![Board preview](board/board_preview.png)

The image above is `board/valuation_board.html`. It is a single self-contained HTML file with the data embedded, so it opens offline with a double click and can be handed to someone else without Python, a database, or a network connection. The snapshot date in this one is 2026-10-12.

## Layout

The code is split into three layers. `core/` takes in-memory data only and holds every algorithm, touching neither files nor the database. `dataio/` is the only place that talks to a database and returns plain dicts and numpy arrays. Documentation, examples, and the board sit in their own layer. The root holds thin entry scripts that parse arguments and call down. Imports flow one way: `core/` never imports `dataio/`, so there are no cycles.

```
company-value-system/
├─ core/          algorithms: stats / valuation / quality / testing / percentile / report
├─ dataio/        data access: paths (path resolution, read-only connections), astock (loaders), schema.md
├─ docs/          research design, data boundaries, install and usage notes, reports
├─ examples/      demo.py and a small desensitized sample
├─ board/         board generator and the generated HTML
├─ mispricing_screener_v2.py     multi-method intrinsic value, mispricing, tests, history percentile
├─ quality_value_screener_v2.py  quality + valuation ranking
├─ valuation_percentile.py       own-history valuation percentile
├─ demo.py                       thin wrapper around examples/demo.py
└─ README.md / README.en.md / requirements.txt / LICENSE
```

## Quick start

numpy is the only dependency; everything else is standard library.

```bash
python -m pip install -r requirements.txt
python demo.py
```

`demo.py` needs no database. It reads the hand-made sample at `examples/data/sample_valuation_snapshot.csv`, runs the industry-multiple method with a rank-composite mispricing measure, prints a sorted table, and ends with `DEMO OK`. Seeing that line means the environment is ready.

On Windows, `python` and `py -3.12` both work. On macOS and Linux, use `python3`. `docs/安装说明.md` covers the cross-platform steps in more detail.

## Running on real data

No database is included. `*.db` and large `*.csv` files are gitignored. You supply two SQLite databases, opened read-only:

`astock.db` holds daily prices, financials, valuation snapshots, industry classification, and share counts. `valuation_hist.db` holds the day-by-day valuation series. Field and unit conventions are in `dataio/schema.md`. If your tables match, the scripts run without modification.

```bash
# Whole market: mispricing, tests, history percentile
python mispricing_screener_v2.py --mode both --db data/astock.db --hist-db data/valuation_hist.db --out v2_out.txt

# A few tickers. The filter only changes what is shown; percentiles still use the full pool
python mispricing_screener_v2.py --mode value --codes 600519,000858 --out one.txt

# Quality + valuation ranking, plus a CSV of names passing the quality gate
python quality_value_screener_v2.py --mode both --top 40 --watchlist watchlist.csv --out qv_out.txt

# Own-history valuation percentile
python valuation_percentile.py --hist-db data/valuation_hist.db --top 25 --out pct_out.txt
```

The board generator folds the results into one HTML file:

```bash
python board/make_board.py --db data/astock.db --out board/valuation_board.html
```

`board/GH_PAGES.md` explains how to publish that file on GitHub Pages.

## Reading the output

In the value mode, `IV_A`, `IV_B`, and `IV_C` are three intrinsic-value estimates: industry median PE times annualized EPS, annualized EPS over a discount rate (the zero-growth DCF special case), and industry median PB times book value per share. `mispr` is the mispricing measure, a pooled rank percentile between 0 and 100, where above 50 is rich and below 50 is cheap. It is not the price gap itself, only that gap's rank across the market.

In the test mode, `IC_mean` is the average cross-sectional rank correlation, `IC_t` its t-statistic, and `IC95%CI` a bootstrap confidence interval. `Q5-Q1净` is the cheap-minus-rich spread net of round-trip cost, and `alpha` is the intercept from regressing that spread on the market factor. The Bonferroni threshold in the header tightens the significance bar by the number of proxies times horizons.

`undetermined` is the most common verdict here. It means the data cannot decide, which is not the same as deciding the factor is ineffective. A conclusion of "effective" requires enough independent samples and a bootstrap interval whose lower bound clears zero after costs. With a short history the interval is wide and most combinations miss the bar.

## Current finding

The current verdict is undetermined.

That is the correct call rather than a failure. Two hard constraints sit underneath it. Full-market daily prices cover about 276 trading days (from 2025-08-19), which leaves essentially zero non-overlapping 12-month samples, and valuation snapshots cover only 4 trading days, so PE and PB history percentiles are unavailable under the snapshot method. Book value, cash flow, dividends, and debt are also missing, which rules out a straightforward DCF, RIM, or DDM; absolute valuation falls back to an earnings-capitalization proxy with strong assumptions.

Writing undetermined is better than passing off a near-zero spread as excess return. The full list of limits is in `docs/数据边界.md`.

## Documentation

`说明书.md` is the operator's manual, from installing the environment through reading the output, including the issues found in the pre-release self-check. `README.md` is the Chinese version. The rest: `docs/使用说明.md` walks through each command and output column, `docs/安装说明.md` covers installation, `docs/数据边界.md` lists what the data can and cannot support, `docs/研究方案.md` is the method design, and the two report files record the iteration.

## License

MIT, see `LICENSE`.

## Disclaimer

This is a research methodology prototype. It promises a reproducible process, not any return, and it is not investment advice. Every number in the documents comes from a real local run and is tagged with its snapshot date and financial period.

Author: mkua030712-ship-it / 刘明豪
