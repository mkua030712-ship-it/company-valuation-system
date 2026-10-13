# -*- coding: utf-8 -*-
"""dataio.paths —— 数据库路径解析与只读连接（去掉机器绑定）。

优先级（对 astock 主库）：
  1) 显式 --db <path>
  2) 环境变量 ASTOCK_DB
  3) 仓库相对位置 data/astock.db
  4) 平级相对位置 ../../astock-site/data/astock.db
历史估值库同理，用 --hist-db；默认先找仓库根的 valuation_hist.db，再找 data/valuation_hist.db。
"""
from __future__ import annotations
import os
import sqlite3

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, ".."))

_DB_CANDIDATES = (
    ("data", "astock.db"),
    ("..", "..", "astock-site", "data", "astock.db"),
    ("..", "..", "..", "astock-site", "data", "astock.db"),
)
_HIST_CANDIDATES = (
    ("valuation_hist.db",),
    ("data", "valuation_hist.db"),
)


def resolve_db(env="ASTOCK_DB"):
    """astock 主库默认路径（不保证存在；不存在时由调用方给提示）。"""
    v = os.environ.get(env)
    if v:
        return v
    for parts in _DB_CANDIDATES:
        cand = os.path.abspath(os.path.join(_REPO_ROOT, *parts))
        if os.path.exists(cand):
            return cand
    return os.path.join(_REPO_ROOT, "data", "astock.db")


def resolve_hist(env="VALUATION_HIST_DB"):
    """历史估值库默认路径。"""
    v = os.environ.get(env)
    if v:
        return v
    for parts in _HIST_CANDIDATES:
        cand = os.path.abspath(os.path.join(_REPO_ROOT, *parts))
        if os.path.exists(cand):
            return cand
    return os.path.join(_REPO_ROOT, "valuation_hist.db")


def open_ro(path):
    """只读打开 SQLite（mode=ro）。路径不存在 → FileNotFoundError（便于给友好提示）。"""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(path)
    con = sqlite3.connect("file:%s?mode=ro" % str(path).replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con
