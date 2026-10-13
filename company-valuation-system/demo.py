#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根目录 demo.py —— 薄壳：转调 examples/demo.py。

保证 `python demo.py`（在仓库根）照旧可用；真正的示例代码在 examples/（文档与示例层）。
也可以直接跑： python examples/demo.py
"""
from __future__ import annotations
import os
import runpy
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "examples", "demo.py")
    if not os.path.exists(target):
        print("找不到 examples/demo.py（是否少了 examples/ 目录？）")
        return 2
    sys.argv[0] = target
    runpy.run_path(target, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
