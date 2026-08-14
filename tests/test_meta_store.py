"""meta_store / rebuild_meta_coverage 测试：纯本地，无网络。"""

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
                row[col] = 1.0 if col in ("pre_close", "adj_factor") else 0
            rows.append(row)
    return pd.DataFrame(rows)


def test_meta_store_write_read(tmp_path):
    store = MetaStore(root=tmp_path)
    df = _meta_df([date(2020, 1, 2), date(2020, 1, 3)], ["SZSE.000001", "SHSE.600000"], "bar")
    store.write_meta("bar", df)
    store.write_coverage("bar", df)

    assert store.years("bar") == [2020]
    out = store.read_meta("bar", date(2020, 1, 1), date(2020, 12, 31))
    assert len(out) == 4
    assert {"date", "symbol", "adj_factor", "is_st"} <= set(out.columns)

    cov = store.coverage("bar")
    assert len(cov) == 4
    assert set(cov["partition"]) == {"bar"}
    keys = MetaStore.row_keys(cov)
    assert (date(2020, 1, 2), "SZSE.000001") in keys


def test_meta_store_merge_dedup(tmp_path):
    store = MetaStore(root=tmp_path)
    d1 = _meta_df([date(2020, 1, 2)], ["SZSE.000001"], "valuation")
    d2 = _meta_df([date(2020, 1, 2)], ["SZSE.000001"], "valuation")
    store.write_meta("valuation", d1)
    store.write_meta("valuation", d2)
    assert len(store.read_meta("valuation", date(2020, 1, 1), date(2020, 12, 31))) == 1


def test_meta_store_bad_partition(tmp_path):
    store = MetaStore(root=tmp_path)
    try:
        store.write_meta("nope", pd.DataFrame())
    except ValueError:
        pass
    else:
        raise AssertionError("should reject unknown partition")


def test_rebuild_meta_coverage(tmp_path):
    store = MetaStore(root=tmp_path)
    for p in META_SUBSETS:
        df = _meta_df([date(2020, 1, 2)], ["SZSE.000001"], p)
        store.write_meta(p, df)

    res = rebuild_meta_coverage(store=store, audit=False)
    assert res["rows"] == len(META_SUBSETS)
    for p in META_SUBSETS:
        assert len(store.coverage(p)) == 1

    # 删除 meta 文件后重建 -> coverage 残留应被清理
    store.meta_path("valuation", 2020).unlink()
    res2 = rebuild_meta_coverage(store=store, audit=False)
    assert "valuation/2020" in res2["deleted_stale_years"]
    assert not store.coverage_path("valuation", 2020).exists()
