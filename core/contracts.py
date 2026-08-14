"""数据源接口契约：GM Data Manager 统一取数入口。

实现可以是掘金 API（data/gm_source.GmDataSource），或未来的本地仓库读取器；
数据落盘与同步任务只依赖本协议，不绑定具体数据源。
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd


@runtime_checkable
class DataSource(Protocol):
    """统一取数入口；实现可以是本地 parquet 仓库或掘金接口。"""

    def bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame: ...

    def events(self, kind: str, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame: ...

    def universe(self, d: date) -> Sequence[str]: ...
