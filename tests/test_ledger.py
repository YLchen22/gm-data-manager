"""no_data 账本 / suspect 复核测试（纯本地，无网络）。"""

from datetime import date, time, timedelta

import pandas as pd

import data.incremental as inc


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(inc, "NO_DATA_PATH", tmp_path / "no_data.parquet")
    monkeypatch.setattr(inc, "SUSPECT_PATH", tmp_path / "suspect.parquet")


def test_completed_days_excludes_today_before_cutoff():
    days = [date(2026, 8, 5), date(2026, 8, 6)]
    # 结算时点前：今天剔除
    assert inc._completed_days(days, today=date(2026, 8, 6), now=time(10, 0)) == [date(2026, 8, 5)]
    # 结算时点后：今天保留
    assert inc._completed_days(days, today=date(2026, 8, 6), now=time(16, 0)) == days
    # 最后一天不是今天：不受影响
    assert inc._completed_days([date(2026, 8, 5)], today=date(2026, 8, 6), now=time(10, 0)) == [
        date(2026, 8, 5)
    ]


def test_suspect_moves_to_no_data_after_3(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    pair = (date(2020, 1, 2), "SZSE.000001", "anomaly")
    for _ in range(3):
        inc._update_suspect([pair])

    nd = inc._load_no_data()
    assert len(nd) == 1
    assert nd["reason"].iloc[0] == "anomaly"
    assert len(inc._load_suspect()) == 0


def test_suspect_keeps_retry_under_3(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    pair = (date(2020, 1, 2), "SZSE.000001", "code_change")
    inc._update_suspect([pair])
    inc._update_suspect([pair])

    assert len(inc._load_suspect()) == 1
    assert len(inc._load_no_data()) == 0


def test_review_no_data_expiry_by_reason(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    now = pd.Timestamp.now()
    old = now - timedelta(days=40)   # anomaly 超 30 天 → 到期
    old_long = now - timedelta(days=40)  # suspended/code_change 超 30 但 < 365 → 保留
    df = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2020-01-02"),
                pd.Timestamp("2020-01-03"),
                pd.Timestamp("2020-01-04"),
            ],
            "symbol": ["SZSE.000001", "SHSE.600000", "SZSE.302132"],
            "reason": ["anomaly", "suspended", "code_change"],
            "last_seen": [old, old_long, old_long],
        }
    )
    inc._save_no_data(df)

    inc._review_no_data()
    nd = inc._load_no_data()
    # anomaly 被清；suspended/code_change 保留（长复核）
    assert list(nd["symbol"]) == ["SHSE.600000", "SZSE.302132"]


def test_no_data_blocked_set(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    inc._mark_no_data([(date(2020, 1, 2), "SZSE.000001")], "suspended")
    blocked = inc._no_data_blocked()
    assert (date(2020, 1, 2), "SZSE.000001") in blocked
