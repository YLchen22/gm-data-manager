"""契约冒烟测试：dummy 实现满足接口、可被调用（验证接缝）。"""

from datetime import date

from core.contracts import CostModel, RiskManager, Strategy
from core.models import (
    Cost,
    Order,
    OrderSide,
    PortfolioState,
    RiskDecision,
    StrategyContext,
    TargetPortfolio,
)


class DummyStrategy:
    """占位策略：等权 Top-N 假信号，用于验证契约可实例化。"""

    def generate(self, ctx: StrategyContext) -> TargetPortfolio:
        return TargetPortfolio(weights={"SHSE.600000": 0.5, "SZSE.000001": 0.5}, generated_at=ctx.date)


class FixedCostModel:
    """占位成本模型：佣金(免5)/印花税/过户费/滑点。"""

    def __init__(self, commission_rate=0.00025, min_commission=5.0, stamp_tax_rate=0.0005,
                 transfer_fee_rate=0.00001, slippage_rate=0.0005):
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate
        self.transfer_fee_rate = transfer_fee_rate
        self.slippage_rate = slippage_rate

    def estimate(self, order: Order, price: float) -> Cost:
        notional = order.quantity * price
        commission = max(notional * self.commission_rate, self.min_commission)
        stamp_tax = notional * self.stamp_tax_rate if order.side == OrderSide.SELL else 0.0
        transfer_fee = notional * self.transfer_fee_rate
        slippage = notional * self.slippage_rate
        return Cost(commission, stamp_tax, transfer_fee, slippage)


class DummyRiskManager:
    def check(self, proposed: TargetPortfolio, state: PortfolioState) -> RiskDecision:
        return RiskDecision(approved=True, multiplier=1.0)


def _ctx(d: date = date(2024, 1, 2)) -> StrategyContext:
    return StrategyContext(
        date=d,
        bars=None,
        universe=(),
        portfolio=PortfolioState(cash=100_000.0, positions={}, date=d),
    )


def test_strategy_contract():
    strat: Strategy = DummyStrategy()  # 类型检查：满足 Protocol
    target = strat.generate(_ctx())
    assert isinstance(target, TargetPortfolio)
    assert abs(sum(target.weights.values()) - 1.0) < 1e-9


def test_cost_model_contract_min_commission():
    cm: CostModel = FixedCostModel()
    order = Order(symbol="SHSE.600000", side=OrderSide.BUY, quantity=100)
    cost = cm.estimate(order, price=10.0)  # 名义 1000 元
    assert cost.commission == 5.0  # 0.25 < 最低 5 元
    assert cost.total > cost.commission


def test_risk_manager_contract():
    rm: RiskManager = DummyRiskManager()
    decision = rm.check(TargetPortfolio(weights={"SHSE.600000": 1.0}, generated_at=date(2024, 1, 2)), _ctx().portfolio)
    assert decision.approved and decision.multiplier == 1.0
