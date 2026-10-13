# -*- coding: utf-8 -*-
"""core —— 核心算法层（纯计算，无 IO / 无路径 / 无 sqlite）。

本层只吃内存数据（dict / list / numpy 数组），不碰数据库、不读文件、不管命令行。
- stats.py      : 秩变换、去极值、标准化、Spearman、正态分位、Bonferroni、描述统计
- valuation.py  : 内在价值多法 + 错配度（秩合成 / 缩尾+z）+ 时点年化 EPS
- quality.py    : 质量分合成 + 质量闸 + 综合分
- testing.py    : 横截面检验（rank IC、五分组、对市场因子 alpha、自举 CI）
- percentile.py : 自身历史估值分位
- report.py     : 把算好的结果渲染成文本（纯字符串，不写文件）

数据从哪来？见 dataio/。命令行入口？见仓库根目录的三个薄脚本。
"""
