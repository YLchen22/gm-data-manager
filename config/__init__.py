"""config：所有数字与机制选择的唯一住所（代码不写死数字）。"""

from config.loader import (
    AlertConfig,
    Config,
    CostConfig,
    PortfolioConfig,
    RiskConfig,
    UniverseConfig,
    load_config,
)

__all__ = [
    "AlertConfig",
    "Config",
    "CostConfig",
    "PortfolioConfig",
    "RiskConfig",
    "UniverseConfig",
    "load_config",
]
