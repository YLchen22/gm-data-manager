"""rebuild_meta_coverage 测试：从 meta 分区重建覆盖清单（纯本地，无网络）。"""

from datetime import date

import pandas as pd

from data.meta_store import META_COLUMNS, META_SUBSETS, MetaStore
from data.rebuild import rebuild_meta_coverage


def _meta_df(days, symbols, partition):
    rows = []
    for d in days:
        for s in symbols:
            row = {"symbol": s, "date": pd.Timestamp(d)}
            for col in META_COLUMNS[partition]:
                row[col] = 1.0
            rows.append(row)
    return pd.DataFrame(rows)


def test_rebuild_generates_coverage(tmp_path):
    store = MetaStore(root=tmp_path)
    for p in META_SUBSETS:
        store.write_meta(
            p, _meta_df([date(2020, 1, 2), date(2020, 1, 3)], ["SZSE.000001", "SHSE.600000"], p)
        )

    res = rebuild_meta_coverage(store=store, audit=False)
    assert res["rows"] == len(META_SUBSETS) * 4
    assert res["empty"] is False
    for p in META_SUBSETS:
        cov = store.coverage(p)
        assert len(cov) == 4
        expected = {
            (date(2020, 1, 2), "SZSE.000001"),
            (date(2020, 1, 2), "SHSE.600000"),
            (date(2020, 1, 3), "SZSE.000001"),
            (date(2020, 1, 3), "SHSE.600000"),
        }
        assert set(zip(cov["date"].dt.date, cov["symbol"])) == expected


def test_rebuild_removes_stale_coverage(tmp_path):
    store = MetaStore(root=tmp_path)
    store.write_meta("valuation", _meta_df([date(2020, 1, 2)], ["SZSE.000001"], "valuation"))
    rebuild_meta_coverage(store=store, audit=False)
    assert store.coverage_path("valuation", 2020).exists()

    store.meta_path("valuation", 2020).unlink()
    res = rebuild_meta_coverage(store=store, audit=False)
    assert res["rows"] == 0 and res["empty"] is True
    assert res["deleted_stale_years"] == ["valuation/2020"]
    assert not store.coverage_path("valuation", 2020).exists()


def test_rebuild_empty_no_files(tmp_path):
    store = MetaStore(root=tmp_path)
    res = rebuild_meta_coverage(store=store, audit=False)
    assert res["rows"] == 0 and res["empty"] is True
    assert res["deleted_stale_years"] == []


def test_rebuild_compare_detects_drift(tmp_path):
    store = MetaStore(root=tmp_path)
    store.write_meta("valuation", _meta_df([date(2020, 1, 2)], ["SZSE.000001"], "valuation"))
    rebuild_meta_coverage(store=store, audit=False)

    # 现有 coverage 人为多一行（模拟"删数据留 coverage"漂移）
    cov = store.coverage("valuation")
    extra = pd.DataFrame(
        {"date": [pd.Timestamp("2020-01-03")], "symbol": ["SZSE.000001"], "partition": ["valuation"]}
    )
    merged = pd.concat([cov, extra]).drop_duplicates(subset=["date", "symbol"], keep="last")
    merged.to_parquet(store.coverage_path("valuation", 2020), index=False)

    res = rebuild_meta_coverage(dry_run=True, compare=True, store=store, audit=False)
    assert res["drift_added"] == 0
    assert res["drift_removed"] == 1  # 冗余 1 行
