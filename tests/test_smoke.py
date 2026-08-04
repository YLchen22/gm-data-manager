"""冒烟测试：所有包可导入、配置可加载。"""


def test_packages_importable():
    import backtest  # noqa: F401
    import config  # noqa: F401
    import core  # noqa: F401
    import data  # noqa: F401
    import execution  # noqa: F401
    import factors  # noqa: F401
    import model  # noqa: F401
    import portfolio  # noqa: F401
    import risk  # noqa: F401


def test_config_loads():
    from config import load_config

    cfg = load_config()
    assert 0 < cfg.costs.commission_rate < 1
    assert cfg.costs.min_commission >= 0
    assert cfg.portfolio.lot_size == 100
    assert cfg.portfolio.min_top_n <= cfg.portfolio.top_n <= cfg.portfolio.max_top_n
