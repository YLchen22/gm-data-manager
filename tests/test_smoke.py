"""冒烟测试：数据服务所有包可导入、核心模块可加载（无网络）。"""


def test_data_service_packages_importable():
    import core  # noqa: F401
    import data  # noqa: F401
    import webui  # noqa: F401


def test_data_modules_importable():
    import data.asset  # noqa: F401
    import data.gm_source  # noqa: F401
    import data.incremental  # noqa: F401
    import data.meta_fetch  # noqa: F401
    import data.meta_store  # noqa: F401
    import data.migrate  # noqa: F401
    import data.rebuild  # noqa: F401
    import data.store  # noqa: F401


def test_data_contract_importable():
    from core.contracts import DataSource
    from core.models import Bar, Event

    assert DataSource is not None
    assert Bar is not None
    assert Event is not None
