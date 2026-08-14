"""领域模型：GM Data Manager 数据服务共享的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Bar:
    """日线行情（字段规范统一后的最小集）。"""

    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float  # 股
    amount: float  # 元
    adj_factor: float = 1.0  # 复权因子


@dataclass(frozen=True)
class Event:
    """事件记录：停牌/涨跌停/除权除息等。"""

    symbol: str
    date: date
    kind: str  # limit_up / limit_down / suspension / ex_rights / ...
    payload: dict[str, Any] = field(default_factory=dict)
