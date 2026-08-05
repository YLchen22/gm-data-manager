"""rebuild_coverage 测试：从 bars 重建覆盖清单（纯本地，无网络）。"""

from datetime import date

import pandas as pd

from data.rebuild import rebuild_coverage
from data.store import Store


def _bars_df(days, symbols):
    rows = []
    for d in days:
        for s in symbols:
            rows.append(
                {
                    "symbol": s,
                    "date": pd.Timestamp(d),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 100,
                    "amount": 100.0,
                    "pre_close": 1.0,
                }
            )
    return pd.DataFrame(rows)


def test_rebuild_generates_coverage(tmp_path):
    store = Store(root=tmp_path)
    df = _bars_df([date(2020, 1, 2), date(2020, 1, 3)], ["SZSE.000001", "SHSE.600000"])
    store.write_bars("stock", df)

    res = rebuild_coverage("stock", store=store)
    cov = store.coverage("stock")

    assert res["rows"] == 4 and res["empty"] is False
    assert len(cov) == 4
    expected = {
        (date(2020, 1, 2), "SZSE.000001"),
        (date(2020, 1, 2), "SHSE.600000"),
        (date(2020, 1, 3), "SZSE.000001"),
        (date(2020, 1, 3), "SHSE.600000"),
    }
    assert set(zip(cov["date"].dt.date, cov["symbol"])) == expected


def test_rebuild_removes_stale_coverage(tmp_path):
    store = Store(root=tmp_path)
    df = _bars_df([date(2020, 1, 2)], ["SZSE.000001"])
    store.write_bars("stock", df)
    rebuild_coverage("stock", store=store)
    assert store.coverage_path("stock", 2020).exists()

    # 删除 bars 后重建 → coverage 残留应被清理，报告为空
    store.bars_path("stock", 2020).unlink()
    res = rebuild_coverage("stock", store=store)

    assert res["rows"] == 0 and res["empty"] is True
    assert res["deleted_stale_years"] == [2020]
    assert not store.coverage_path("stock", 2020).exists()


def test_rebuild_empty_no_files(tmp_path):
    store = Store(root=tmp_path)
    res = rebuild_coverage("stock", store=store)

    assert res["rows"] == 0 and res["empty"] is True
    assert res["deleted_stale_years"] == []
    cov_dir = store.coverage_root / "stock"
    assert not cov_dir.exists() or not list(cov_dir.glob("*.parquet"))


def test_rebuild_compare_detects_drift(tmp_path):
    store = Store(root=tmp_path)
    df = _bars_df([date(2020, 1, 2)], ["SZSE.000001", "SHSE.600000"])
    store.write_bars("stock", df)
    rebuild_coverage("stock", store=store)

    # 现有 coverage 人为多一条（模拟"删 bars 留 coverage"漂移）
    cov = store.coverage("stock")
    extra = pd.DataFrame(
        {"date": [pd.Timestamp("2020-01-03")], "symbol": ["SZSE.000001"]}
    )
    merged = pd.concat([cov, extra]).drop_duplicates(subset=["date", "symbol"], keep="last")
    merged.to_parquet(store.coverage_path("stock", 2020), index=False)

    res = rebuild_coverage("stock", dry_run=True, compare=True, store=store)
    assert res["drift_added"] == 0
    assert res["drift_removed"] == 1  # 冗余 1 行
