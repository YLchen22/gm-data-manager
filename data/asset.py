"""资产类别与 symbol 集合：全 A 股（主板/创业板/科创板，排除 B 股/北交所）。

资产类别独立成维度：股票/指数/ETF 各自维护，WebUI 可分别触发。
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum

import pandas as pd

from core.contracts import DataSource

# 股票代码规则：SHSE 60(主板)/68(科创板)；SZSE 00(主板含中小板)/30(创业板)
# 天然排除 B 股（200/201/900）与北交所（gm 沪深接口不含）
_A_SHARE_RE = re.compile(r"^(SHSE\.(60|68)\d{4}|SZSE\.(00|30)\d{4})$")


class AssetClass(Enum):
    STOCK = "stock"
    INDEX = "index"
    ETF = "etf"


def board_of(symbol: str) -> str:
    code = symbol.split(".")[1]
    if code.startswith(("60", "00")):
        return "主板"
    if code.startswith("68"):
        return "科创板"
    if code.startswith("30"):
        return "创业板"
    return "其他"


def is_a_share(symbol: str) -> bool:
    return bool(_A_SHARE_RE.match(symbol))


def load_assets(source: DataSource) -> pd.DataFrame:
    """全 A 股静态表：symbol, sec_name, listed_date, delisted_date, board。"""
    ins = source.instruments()
    ins = ins[ins["symbol"].map(is_a_share)].copy()
    ins["listed_date"] = pd.to_datetime(ins["listed_date"]).dt.date
    ins["delisted_date"] = pd.to_datetime(ins["delisted_date"]).dt.date
    ins["board"] = ins["symbol"].map(board_of)
    return ins[["symbol", "sec_name", "listed_date", "delisted_date", "board"]].reset_index(drop=True)


def valid_symbols_on(assets: pd.DataFrame, d: date) -> set[str]:
    """某交易日应存在的股票（已上市且未退市）。"""
    mask = (assets["listed_date"] <= d) & (assets["delisted_date"] >= d)
    return set(assets.loc[mask, "symbol"])
