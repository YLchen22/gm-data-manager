"""meta_fetch 任务测试：mock 数据源，无网络。"""

from datetime import date

import pandas as pd

from data.meta_fetch import align_meta, scan_missing_meta_summary
from data.meta_store import META_COLUMNS, META_SUBSETS, MetaStore
import data.incremental as inc

DAYS = [date(2024, 1, 2), date(2024, 1, 3)]
SYMS = ["SZSE.000001", "SHSE.600000", "SZSE.300002"]

MOCK_COLUMNS = {
    "bar": META_COLUMNS["bar"],
    "mv_basic": META_COLUMNS["mv_basic"],
    "valuation": META_COLUMNS["valuation"],
}


def _row_df(symbols, d, kind):
    rows = []
    for s in symbols:
        row = {"date": pd.Timestamp(d), "symbol": s}
        for col in MOCK_COLUMNS[kind]:
            row[col] = 1.23 if col in ("pre_close", "adj_factor") else 0
        rows.append(row)
    return pd.DataFrame(rows)


class FakeSource:
    """模拟掘金数据源：交易日历 / 股票池 / p0 / 行情 / 市值股本 / 估值。"""

    def __init__(self, missing_valuation: dict[tuple[date, str], bool] | None = None):
        self.missing_valuation = missing_valuation or {}
        self.calls: list[tuple[str, date]] = []

    def trading_dates(self, start, end):
        return [d.isoformat() for d in DAYS if start <= d <= end]

    def instruments(self):
        rows = [
            {
                "symbol": s,
                "sec_name": f"N{s}",
                "listed_date": pd.Timestamp("2015-01-01"),
                "delisted_date": pd.Timestamp("2038-01-01"),
            }
            for s in SYMS
        ]
        return pd.DataFrame(rows)

    def meta_p0(self, d):
        self.calls.append(("p0", d))
        rows = []
        for s in SYMS:
            rows.append(
                {
                    "date": pd.Timestamp(d),
                    "symbol": s,
                    "pre_close": 10.0,
                    "upper_limit": 11.0,
                    "lower_limit": 9.0,
                    "adj_factor": 1.5,
                    "turn_rate": 1.0,
                    "is_suspended": False,
                    "is_st": False,
                }
            )
        return pd.DataFrame(rows)

    def meta_bar(self, d, symbols):
        self.calls.append(("bar", d))
        rows = []
        for s in symbols:
            rows.append(
                {
                    "symbol": s,
                    "date": pd.Timestamp(d),
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000,
                    "amount": 10000.0,
                    "pre_close": 10.0,
                }
            )
        return pd.DataFrame(rows)

    def meta_mv_basic(self, d, symbols):
        self.calls.append(("mv_basic", d))
        return _row_df(symbols, d, "mv_basic")

    def meta_valuation(self, d, symbols):
        self.calls.append(("valuation", d))
        syms = list(symbols)
        if self.missing_valuation.get((d, "SZSE.300002")):
            syms = [s for s in syms if s != "SZSE.300002"]
        return _row_df(syms, d, "valuation")


def _setup(tmp_path, monkeypatch):
    store = MetaStore(root=tmp_path)
    monkeypatch.setattr(inc, "NO_DATA_PATH", tmp_path / "no_data.parquet")
    return store


def test_align_meta_fills_all_partitions_aligned(tmp_path, monkeypatch):
    store = _setup(tmp_path, monkeypatch)
    source = FakeSource()
    res = align_meta(
        date(2024, 1, 1),
        date(2024, 12, 31),
        source=source,
        store=store,
    )
    # 三分区 × 2 天 × 3 只
    assert res["filled_rows"] == 3 * 2 * 3
    assert res["failed"] == 0

    keys = None
    for p in META_SUBSETS:
        df = store.read_meta(p, date(2024, 1, 1), date(2024, 12, 31))
        k = MetaStore.row_keys(df)
        assert len(k) == 6
        if keys is None:
            keys = k
        else:
            assert k == keys, f"{p} 行键与基准不一致"
        assert len(store.coverage(p)) == 6


def test_align_meta_second_run_skips(tmp_path, monkeypatch):
    store = _setup(tmp_path, monkeypatch)
    source = FakeSource()
    align_meta(date(2024, 1, 1), date(2024, 12, 31), source=source, store=store)
    calls1 = len(source.calls)
    res = align_meta(date(2024, 1, 1), date(2024, 12, 31), source=source, store=store)
    assert res["checked_days"] == 0
    assert len(source.calls) == calls1  # 无任何重复抓取


def test_align_meta_records_missing_and_blocks(tmp_path, monkeypatch):
    store = _setup(tmp_path, monkeypatch)
    source = FakeSource(missing_valuation={(date(2024, 1, 2), "SZSE.300002"): True})
    res = align_meta(date(2024, 1, 1), date(2024, 12, 31), source=source, store=store)
    # 缺失的估值以 NaN 行保留（对齐），同时记入 no_data 边界
    val = store.read_meta("valuation", date(2024, 1, 1), date(2024, 12, 31))
    assert len(val) == 6
    assert res["failed"] >= 1


def test_scan_missing_meta_summary(tmp_path, monkeypatch):
    store = _setup(tmp_path, monkeypatch)
    source = FakeSource()
    s = scan_missing_meta_summary(
        date(2024, 1, 1), date(2024, 12, 31), source=source, store=store
    )
    assert s["meta_rows"] == 3 * 2
    assert set(s["meta_subsets"]) == set(META_SUBSETS)
    align_meta(date(2024, 1, 1), date(2024, 12, 31), source=source, store=store)
    s2 = scan_missing_meta_summary(
        date(2024, 1, 1), date(2024, 12, 31), source=source, store=store
    )
    assert s2["meta_rows"] == 0
