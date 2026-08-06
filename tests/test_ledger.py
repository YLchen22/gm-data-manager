"""no_data 账本 / suspect 复核测试（纯本地，无网络）。"""

from datetime import date, time, timedelta

import pandas as pd

import data.incremental as inc


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(inc, "NO_DATA_PATH", tmp_path / "no_data.parquet")
    monkeypatch.setattr(inc, "SUSPECT_PATH", tmp_path / "suspect.parquet")


def test_completed_days_excludes_today_before_cutoff():
    days = [date(2026, 8, 5), date(2026, 8, 6)]
    # 收盘结算时点(18:00)前：今天剔除
    assert inc._completed_days(days, today=date(2026, 8, 6), now=time(10, 0)) == [date(2026, 8, 5)]
    # 收盘结算时点(18:00)后：今天保留
    assert inc._completed_days(days, today=date(2026, 8, 6), now=time(19, 0)) == days
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


def _fake_assets(n=100):
    return pd.DataFrame(
        {
            "symbol": [f"SZSE.000{i:03d}" for i in range(n)],
            "listed_date": [date(2010, 1, 1)] * n,
            "delisted_date": [date(2038, 1, 1)] * n,
        }
    )


def test_audit_flags_and_cleans_anomaly_days(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    days = [date(2026, 8, 5), date(2026, 8, 6)]
    rows = []
    for i in range(60):  # 8-05: 60 条 anomaly > 阈值 50 → 标记并清除
        rows.append((pd.Timestamp("2026-08-05"), f"SZSE.000{i:03d}", "anomaly"))
    for i in range(10):  # 8-06: 10 条 ≤ 阈值 → 保留
        rows.append((pd.Timestamp("2026-08-06"), f"SZSE.000{i:03d}", "anomaly"))
    nd = pd.DataFrame(rows, columns=["date", "symbol", "reason"])
    nd["last_seen"] = pd.Timestamp.now()
    inc._save_no_data(nd)

    res = inc.audit_no_data(
        date(2016, 1, 1), date(2026, 8, 6), dry_run=False,
        assets=_fake_assets(), trading_days=days,
    )
    assert res["flagged_days"] == ["2026-08-05"]
    assert res["removed_rows"] == 60
    assert len(inc._load_no_data()) == 10


def test_audit_dry_run_keeps_entries(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    days = [date(2026, 8, 5)]
    nd = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-08-05")] * 60,
            "symbol": [f"SZSE.000{i:03d}" for i in range(60)],
            "reason": ["anomaly"] * 60,
            "last_seen": [pd.Timestamp.now()] * 60,
        }
    )
    inc._save_no_data(nd)

    res = inc.audit_no_data(
        date(2016, 1, 1), date(2026, 8, 6), dry_run=True,
        assets=_fake_assets(), trading_days=days,
    )
    assert res["flagged_days"] == ["2026-08-05"]
    assert res["removed_rows"] == 0
    assert len(inc._load_no_data()) == 60
