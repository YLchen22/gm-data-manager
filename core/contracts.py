"""接口契约（草案 v0.1）：见 ENGINE_DESIGN.md 第 4 节。

v0.x 内允许调整；v1.0 冻结。
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd

from core.models import Cost, ExecutionReport, Order, RiskDecision, StrategyContext, TargetPortfolio


@runtime_checkable
class Strategy(Protocol):
    """策略只负责产出目标持仓/信号，不碰撮合与成本。

    引擎在 T 日收盘后调用，T+1 执行。
    """

    def generate(self, ctx: StrategyContext) -> TargetPortfolio: ...


@runtime_checkable
class DataSource(Protocol):
    """统一取数入口；实现可以是本地 parquet 缓存或掘金接口。"""

    def bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame: ...

    def events(self, kind: str, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame: ...

    def universe(self, d: date) -> Sequence[str]: ...


@runtime_checkable
class CostModel(Protocol):
    """成本是一等公民：佣金(免5)/印花税/过户费/滑点。"""

    def estimate(self, order: Order, price: float) -> Cost: ...


@runtime_checkable
class RiskManager(Protocol):
    """硬风控 + 风险乘数 + 统计预警的入口；与策略解耦。"""

    def check(self, proposed: TargetPortfolio, state: PortfolioState) -> RiskDecision: ...


@runtime_checkable
class ExecutionAdapter(Protocol):
    """执行层适配器；掘金是第一个实现，未来可替换。"""

    def submit(self, orders: Sequence[Order]) -> Sequence[ExecutionReport]: ...
