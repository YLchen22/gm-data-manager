"""配置加载：YAML -> 数据类，带基础校验。

所有参数（结构参数 + 标定参数）的数值都在 config/*.yaml 中；
代码只引用数据类字段，不写死数字。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CostConfig:
    commission_rate: float
    min_commission: float
    stamp_tax_rate: float
    transfer_fee_rate: float
    slippage_rate: float


@dataclass(frozen=True)
class UniverseConfig:
    min_listing_days: int
    suspension_days_limit: int
    liquidity_drop_pct: float


@dataclass(frozen=True)
class RiskConfig:
    max_drawdown_hard: float
    max_drawdown_clear: float
    daily_loss_circuit_breaker: float
    risk_multiplier_after_breaker: float
    max_single_stock_weight: float
    max_single_industry_weight: float
    max_industry_risk_contribution: float


@dataclass(frozen=True)
class AlertConfig:
    ic_ewma_lambda: float
    cusum_k: float
    cusum_h: float
    var_confidence: float
    vol_ratio_threshold: float


@dataclass(frozen=True)
class PortfolioConfig:
    top_n: int
    min_top_n: int
    max_top_n: int
    turnover_limit: float
    lot_size: int
    prediction_horizon: int


@dataclass(frozen=True)
class Config:
    costs: CostConfig
    universe: UniverseConfig
    risk: RiskConfig
    alerts: AlertConfig
    portfolio: PortfolioConfig


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"配置格式错误（应为键值映射）: {path.name}")
    return data


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(f"config 校验失败: {msg}")


def _ratio(value: float, name: str) -> float:
    value = float(value)
    _check(0.0 < value < 1.0, f"{name} 应为 (0,1) 比例，当前 {value}")
    return value


def _positive(value: float, name: str) -> float:
    value = float(value)
    _check(value > 0, f"{name} 应为正数，当前 {value}")
    return value


def load_config(config_dir: Path | None = None) -> Config:
    """加载全部配置并做基础校验。config_dir 仅用于测试注入。"""

    base = config_dir or CONFIG_DIR

    costs = _load_yaml(base / "costs.yaml")
    universe = _load_yaml(base / "universe.yaml")
    risk = _load_yaml(base / "risk.yaml")
    alerts = _load_yaml(base / "alerts.yaml")
    portfolio = _load_yaml(base / "portfolio.yaml")

    cfg = Config(
        costs=CostConfig(
            commission_rate=_ratio(costs["commission_rate"], "commission_rate"),
            min_commission=_positive(costs["min_commission"], "min_commission"),
            stamp_tax_rate=_ratio(costs["stamp_tax_rate"], "stamp_tax_rate"),
            transfer_fee_rate=_ratio(costs["transfer_fee_rate"], "transfer_fee_rate"),
            slippage_rate=_ratio(costs["slippage_rate"], "slippage_rate"),
        ),
        universe=UniverseConfig(
            min_listing_days=int(universe["min_listing_days"]),
            suspension_days_limit=int(universe["suspension_days_limit"]),
            liquidity_drop_pct=_ratio(universe["liquidity_drop_pct"], "liquidity_drop_pct"),
        ),
        risk=RiskConfig(
            max_drawdown_hard=_ratio(risk["max_drawdown_hard"], "max_drawdown_hard"),
            max_drawdown_clear=_ratio(risk["max_drawdown_clear"], "max_drawdown_clear"),
            daily_loss_circuit_breaker=_ratio(risk["daily_loss_circuit_breaker"], "daily_loss_circuit_breaker"),
            risk_multiplier_after_breaker=_ratio(risk["risk_multiplier_after_breaker"], "risk_multiplier_after_breaker"),
            max_single_stock_weight=_ratio(risk["max_single_stock_weight"], "max_single_stock_weight"),
            max_single_industry_weight=_ratio(risk["max_single_industry_weight"], "max_single_industry_weight"),
            max_industry_risk_contribution=_ratio(
                risk["max_industry_risk_contribution"], "max_industry_risk_contribution"
            ),
        ),
        alerts=AlertConfig(
            ic_ewma_lambda=_ratio(alerts["ic_ewma_lambda"], "ic_ewma_lambda"),
            cusum_k=_positive(alerts["cusum_k"], "cusum_k"),
            cusum_h=_positive(alerts["cusum_h"], "cusum_h"),
            var_confidence=_ratio(alerts["var_confidence"], "var_confidence"),
            vol_ratio_threshold=_positive(alerts["vol_ratio_threshold"], "vol_ratio_threshold"),
        ),
        portfolio=PortfolioConfig(
            top_n=int(portfolio["top_n"]),
            min_top_n=int(portfolio["min_top_n"]),
            max_top_n=int(portfolio["max_top_n"]),
            turnover_limit=_ratio(portfolio["turnover_limit"], "turnover_limit"),
            lot_size=int(portfolio["lot_size"]),
            prediction_horizon=int(portfolio["prediction_horizon"]),
        ),
    )
    _check(cfg.portfolio.min_top_n <= cfg.portfolio.top_n <= cfg.portfolio.max_top_n, "min_top_n <= top_n <= max_top_n")
    return cfg
