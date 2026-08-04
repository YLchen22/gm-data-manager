"""领域模型：引擎平台共享的数据结构（ENGINE_DESIGN.md 第 4 节配套）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Bar:
    """日线数据（字段规范统一后的最小集）。"""

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


@dataclass(frozen=True)
class Order:
    """订单：数量为整手（100 股）的倍数。"""

    symbol: str
    side: OrderSide
    quantity: int
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING


@dataclass(frozen=True)
class Cost:
    """一笔订单的费用分解。"""

    commission: float
    stamp_tax: float
    transfer_fee: float
    slippage: float

    @property
    def total(self) -> float:
        return self.commission + self.stamp_tax + self.transfer_fee + self.slippage


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    available_quantity: int  # T+1 可卖数量
    avg_cost: float


@dataclass
class PortfolioState:
    """当前账户状态（引擎维护，策略/风控只读）。"""

    cash: float
    positions: dict[str, Position]
    date: date

    @property
    def market_value(self) -> float:
        # 占位实现：Phase 1 由引擎以最新收盘价估值
        return sum(p.quantity * p.avg_cost for p in self.positions.values())


@dataclass(frozen=True)
class TargetPortfolio:
    """策略输出：目标权重（取整前）+ 可选计划订单。"""

    weights: dict[str, float]
    generated_at: date
    planned_orders: tuple[Order, ...] = ()


@dataclass(frozen=True)
class RiskDecision:
    """风控输出：是否放行 + 风险乘数。"""

    approved: bool
    multiplier: float = 1.0
    reason: str = ""
    alerts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionReport:
    order: Order
    filled_price: float | None
    filled_quantity: int
    cost: Cost | None
    message: str = ""


@dataclass
class StrategyContext:
    """策略在 T 日收盘后看到的全部输入。"""

    date: date
    bars: Any  # DataFrame 或 dict；Phase 1 定型
    universe: Any
    portfolio: PortfolioState
