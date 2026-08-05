"""数据对齐：市场全量（按股票）与截面增量（按天）。

两种任务都遵循"先扫描本地覆盖，只补缺失，避免重复抓取"：
- 市场全量（align_by_stock）：按股票逐个对齐——每只股票计算 2016 至今缺失的日期区间，
  合并连续区间后整段拉取（股票维度完整性）；
- 截面增量（align）：按交易日对齐——每天计算有效性集合（已上市未退市）− 已覆盖集合，
  拉取该日缺失的股票（日期维度完整性）。

完整性口径：
- coverage 清单 = bars 的纯投影（date, symbol），只登记"有行情"；
- no_data 独立账本登记"确认无行情"的 (date, symbol, reason)：
    suspended   确认停牌（get_history_instruments is_suspended=1）
    boundary    退市日/上市日当天
    code_change 连续 3 次无状态记录（代码变更特征，如 302132 中航成飞）
    anomaly     连续 3 次"有行情却未返回"（数据缺口/瞬时故障）
    unknown     状态接口失败时降级，走重试
- 某天完整 ⟺ coverage(d) ∪ no_data(d) ⊇ 当日有效性集合；
- 复核（自愈）：anomaly/unknown 30 天，suspended/boundary/code_change 365 天，
  到期后重新进入缺失集合验证一次，防数据源后来补齐却永久漏抓。

WebUI 通过 progress_cb / stop_event 驱动动态进度条与停止操作。
"""

from __future__ import annotations

import argparse
import os
import sys
from bisect import bisect_left, bisect_right
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd
from dotenv import load_dotenv
from gm.api import get_history_instruments

from data.asset import load_assets, valid_symbols_on
from data.gm_source import GmDataSource
from data.store import Store

SUSPECT_PATH = Path(__file__).resolve().parent / "cache" / "status" / "suspect.parquet"
NO_DATA_PATH = Path(__file__).resolve().parent / "cache" / "status" / "no_data.parquet"
MAX_ATTEMPTS = 3
REVIEW_DAYS = 30        # anomaly/unknown：可能恢复 → 短复核
REVIEW_DAYS_LONG = 365  # suspended/boundary/code_change：确定性无数据 → 长复核

ProgressCB = Callable[[dict], None]
StopCheck = Callable[[], bool]


# ---------- suspect（待复核计数，只存"未确认"） ----------


def _load_suspect() -> pd.DataFrame:
    if not SUSPECT_PATH.exists():
        return pd.DataFrame(columns=["date", "symbol", "attempts", "status", "reason", "last_seen"])
    df = pd.read_parquet(SUSPECT_PATH)
    for col in ("last_seen", "reason"):
        if col not in df.columns:
            df[col] = pd.NaT if col == "last_seen" else "unknown"
    return df


def _save_suspect(df: pd.DataFrame) -> None:
    SUSPECT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SUSPECT_PATH, index=False)


def _update_suspect(failed: list[tuple[date, str, str]]) -> None:
    """待复核 (date, symbol, reason) 累计尝试；满 MAX_ATTEMPTS 移入 no_data（按 reason）。"""
    df = _load_suspect()
    now = pd.Timestamp.now()
    now_df = pd.DataFrame(
        {
            "date": [pd.Timestamp(d) for d, _, _ in failed],
            "symbol": [s for _, s, _ in failed],
            "attempts": 1,
            "status": "retry",
            "reason": [r for _, _, r in failed],
            "last_seen": now,
        }
    )
    merged = pd.concat([df, now_df], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    grp = merged.groupby(["date", "symbol"], as_index=False).agg(
        attempts=("attempts", "sum"),
        status=("status", "last"),
        reason=("reason", "last"),
        last_seen=("last_seen", "last"),
    )
    done = grp[grp["attempts"] >= MAX_ATTEMPTS]
    if not done.empty:
        for reason, sub in done.groupby("reason"):
            _mark_no_data(
                list(zip(pd.to_datetime(sub["date"]).dt.date, sub["symbol"])),
                str(reason),
            )
    keep = grp[grp["attempts"] < MAX_ATTEMPTS]
    _save_suspect(keep)


# ---------- no_data 账本（确认无行情，参与完整性判定） ----------


def _load_no_data() -> pd.DataFrame:
    if not NO_DATA_PATH.exists():
        return pd.DataFrame(columns=["date", "symbol", "reason", "last_seen"])
    return pd.read_parquet(NO_DATA_PATH)


def _save_no_data(df: pd.DataFrame) -> None:
    NO_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = NO_DATA_PATH.with_name(NO_DATA_PATH.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, NO_DATA_PATH)


def _mark_no_data(pairs: list[tuple[date, str]], reason: str) -> None:
    if not pairs:
        return
    df = _load_no_data()
    now = pd.Timestamp.now()
    new = pd.DataFrame(
        {
            "date": [pd.Timestamp(d) for d, _ in pairs],
            "symbol": [s for _, s in pairs],
            "reason": reason,
            "last_seen": now,
        }
    )
    merged = pd.concat([df, new], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    merged = merged.drop_duplicates(subset=["date", "symbol"], keep="last")
    _save_no_data(merged)


def _no_data_blocked() -> set[tuple[date, str]]:
    df = _load_no_data()
    if df.empty:
        return set()
    return set(zip(pd.to_datetime(df["date"]).dt.date, df["symbol"]))


def _review_no_data() -> None:
    """按 reason 复核周期清理 no_data；清理后重新进入缺失集合验证（自愈）。"""
    df = _load_no_data()
    if df.empty or df["last_seen"].isna().all():
        return
    now = pd.Timestamp.now()
    last = pd.to_datetime(df["last_seen"])
    short_cut = now - pd.Timedelta(days=REVIEW_DAYS)
    long_cut = now - pd.Timedelta(days=REVIEW_DAYS_LONG)
    expire = ((df["reason"].isin(["anomaly", "unknown"])) & (last < short_cut)) | (last < long_cut)
    if expire.any():
        _save_no_data(df[~expire])


# ---------- 缺失计算 ----------


def _missing_blocks(store: Store, assets: pd.DataFrame, start: date, end: date) -> list[tuple[date, set[str]]]:
    """计算每个交易日的缺失 symbol 集合（coverage ∪ no_data 之外）。"""
    _review_no_data()
    source = GmDataSource()
    trading_days = source.trading_dates(start, end)
    trading_days = [date.fromisoformat(d) for d in trading_days]
    covered = store.coverage_by_date("stock")
    blocked = _no_data_blocked()
    blocks = []
    for d in trading_days:
        valid = valid_symbols_on(assets, d)
        have = covered.get(d, set())
        missing = valid - have - {s for (dd, s) in blocked if dd == d}
        if missing:
            blocks.append((d, missing))
    return blocks


# ---------- 分类（供"确认无数据"记账 + 展示） ----------


def _classify_unreturned(
    assets: pd.DataFrame, d: date, symbols: list[str]
) -> tuple[list[str], list[str], list[str], list[str], bool]:
    """截面模式：未返回符号分类 → (停牌, 边界, 异常, 无状态, 状态接口可用)。

    - 边界：退市日/上市日当天 → 直接 no_data(boundary)；
    - 停牌：is_suspended=1 → 直接 no_data(suspended)；
    - 异常：is_suspended=0 却无行情 → suspect 重试（数据缺口/瞬时）；
    - 无状态：同批其他符号有记录、唯独它没有 → suspect 重试（代码变更特征）；
    状态接口失败 → 全部按 unknown 走 suspect 重试。
    """
    if not symbols:
        return [], [], [], [], True
    bd = assets.set_index("symbol")[["listed_date", "delisted_date"]]
    boundary: list[str] = []
    rest: list[str] = []
    for s in symbols:
        row = bd.loc[s]
        if row["listed_date"] == d or row["delisted_date"] == d:
            boundary.append(s)
        else:
            rest.append(s)
    if not rest:
        return [], boundary, [], [], True
    try:
        hi = get_history_instruments(
            symbols=",".join(rest), start_date=d.isoformat(), end_date=d.isoformat(), df=True
        )
    except Exception:
        return [], [], [], list(symbols), False
    if hi is None or hi.empty:
        return [], [], [], list(symbols), False
    status_map = dict(zip(hi["symbol"], hi["is_suspended"]))
    suspended: list[str] = []
    anomaly: list[str] = []
    nostatus: list[str] = []
    for s in rest:
        st = status_map.get(s)
        if st == 1:
            suspended.append(s)
        elif st == 0:
            anomaly.append(s)
        else:
            nostatus.append(s)
    return suspended, boundary, anomaly, nostatus, True


def _classify_unreturned_days(
    assets: pd.DataFrame, sym: str, days: list[date]
) -> tuple[list[date], list[date], list[date], list[date], bool]:
    """股票模式：某股票缺失交易日分类 → (停牌日, 边界日, 异常日, 无状态日, 接口可用)。"""
    if not days:
        return [], [], [], [], True
    row = assets.set_index("symbol").loc[sym]
    boundary: list[date] = []
    rest: list[date] = []
    for d in days:
        if row["listed_date"] == d or row["delisted_date"] == d:
            boundary.append(d)
        else:
            rest.append(d)
    if not rest:
        return [], boundary, [], [], True
    try:
        hi = get_history_instruments(
            symbols=sym, start_date=rest[0].isoformat(), end_date=rest[-1].isoformat(), df=True
        )
    except Exception:
        return [], [], [], list(days), False
    if hi is None or hi.empty:
        return [], [], [], list(days), False
    status_map = dict(zip(pd.to_datetime(hi["trade_date"]).dt.date, hi["is_suspended"]))
    suspended: list[date] = []
    anomaly: list[date] = []
    nostatus: list[date] = []
    for d in rest:
        st = status_map.get(d)
        if st == 1:
            suspended.append(d)
        elif st == 0:
            anomaly.append(d)
        else:
            nostatus.append(d)
    return suspended, boundary, anomaly, nostatus, True


def scan_missing(start: date, end: date) -> list[tuple[date, set[str]]]:
    """只扫描本地覆盖，不拉取：返回 [(日期, 缺失 symbol 集合)]。

    用于 WebUI 在启动任务前展示"尚未对齐"统计。
    """
    store = Store()
    source = GmDataSource()
    assets = load_assets(source)
    return _missing_blocks(store, assets, start, end)


def _merge_trading_ranges(missing: list[date], trading_days: list[date]) -> list[tuple[date, date]]:
    """把缺失日期按"交易日连续"合并成区间段。"""
    idx = {d: i for i, d in enumerate(trading_days)}
    missing = sorted(missing)
    ranges: list[tuple[date, date]] = []
    seg_start = seg_end = missing[0]
    for d in missing[1:]:
        if idx.get(d) == idx.get(seg_end, -1) + 1:
            seg_end = d
        else:
            ranges.append((seg_start, seg_end))
            seg_start = seg_end = d
    ranges.append((seg_start, seg_end))
    return ranges


def _missing_ranges_by_stock(
    store: Store, assets: pd.DataFrame, trading_days: list[date], start: date, end: date
) -> list[tuple[str, list[tuple[date, date]]]]:
    """每只股票缺失的日期区间（coverage ∪ no_data 之外）。"""
    _review_no_data()
    covered = store.coverage("stock")
    covered_by_symbol: dict[str, set[date]] = {}
    if not covered.empty:
        for sym, g in covered.groupby("symbol"):
            covered_by_symbol[sym] = set(g["date"].dt.date)
    blocked = _no_data_blocked()

    result: list[tuple[str, list[tuple[date, date]]]] = []
    for sym, listed, delisted in assets[["symbol", "listed_date", "delisted_date"]].itertuples(index=False):
        lo = bisect_left(trading_days, max(listed, start))
        hi = bisect_right(trading_days, min(delisted, end))
        valid = trading_days[lo:hi]
        if not valid:
            continue
        have = covered_by_symbol.get(sym, set())
        missing = [d for d in valid if d not in have and (d, sym) not in blocked]
        if not missing:
            continue
        result.append((sym, _merge_trading_ranges(missing, trading_days)))
    return result


def scan_missing_stocks(start: date, end: date) -> list[tuple[str, list[tuple[date, date]]]]:
    """只扫描本地覆盖，不拉取：返回 [(股票, 缺失日期区间段)]，供市场全量任务使用。"""
    store = Store()
    source = GmDataSource()
    assets = load_assets(source)
    trading_days = [date.fromisoformat(d) for d in source.trading_dates(start, end)]
    return _missing_ranges_by_stock(store, assets, trading_days, start, end)


def align(
    start: date,
    end: date,
    max_days: int = 0,
    progress_cb: ProgressCB | None = None,
    stop_event: StopCheck | None = None,
) -> dict:
    """截面增量（按天）：补齐缺失截面；确认无数据记入 no_data 账本。"""
    store = Store()
    source = GmDataSource()
    assets = load_assets(source)
    blocks = _missing_blocks(store, assets, start, end)
    if max_days > 0:
        blocks = blocks[:max_days]

    total = len(blocks)
    filled_rows = 0
    no_data_rows = 0
    failed: list[tuple[date, str, str]] = []
    stopped = False
    for idx, (d, missing) in enumerate(blocks):
        if stop_event is not None and stop_event():
            stopped = True
            break
        df = source.bars(sorted(missing), d, d)
        got = set(df["symbol"]) if df is not None and not df.empty else set()
        if got:
            store.write_bars("stock", df)
            store.write_coverage("stock", df)
            filled_rows += len(df)
        unreturned = sorted(missing - got)
        susp_syms, boundary_syms, anomaly_syms, nostatus_syms, api_ok = _classify_unreturned(
            assets, d, unreturned
        )
        if api_ok:
            _mark_no_data([(d, s) for s in susp_syms], "suspended")
            _mark_no_data([(d, s) for s in boundary_syms], "boundary")
            failed.extend((d, s, "anomaly") for s in anomaly_syms)
            failed.extend((d, s, "code_change") for s in nostatus_syms)
        else:
            failed.extend((d, s, "unknown") for s in unreturned)
        no_data_n = len(susp_syms) + len(boundary_syms)
        no_data_rows += no_data_n
        if progress_cb is not None:
            progress_cb(
                {
                    "mode": "section",
                    "current": d.isoformat(),
                    "done_days": idx + 1,
                    "total_days": total,
                    "missing_count": len(missing),
                    "filled_count": len(got),
                    "no_data_count": no_data_n,
                    "retry_count": len(unreturned) - no_data_n,
                    "filled_rows": filled_rows,
                    "failed_count": len(failed),
                    "percent": (idx + 1) / total if total else 1.0,
                }
            )
        print(
            f"[align] {d} 待补 {len(missing)} → 已入库 {len(got)} · "
            f"空补 {no_data_n}（停牌 {len(susp_syms)}/边界 {len(boundary_syms)}）· "
            f"待复核 {len(unreturned) - no_data_n}",
            flush=True,
        )

    if failed:
        _update_suspect(failed)
    print(
        f"[align] 完成：处理 {total} 天，已入库 {filled_rows} 行，空补 {no_data_rows} 条，"
        f"待复核 {len(failed)} 条",
        flush=True,
    )
    return {
        "checked_days": len(blocks),
        "filled_rows": filled_rows,
        "no_data": no_data_rows,
        "failed": len(failed),
        "stopped": stopped,
        "mode": "section",
    }


def align_by_stock(
    start: date,
    end: date,
    progress_cb: ProgressCB | None = None,
    stop_event: StopCheck | None = None,
) -> dict:
    """市场全量：按股票逐个对齐（每只股票 2016 至今的缺失区间）。"""
    store = Store()
    source = GmDataSource()
    assets = load_assets(source)
    trading_days = [date.fromisoformat(d) for d in source.trading_dates(start, end)]
    jobs = _missing_ranges_by_stock(store, assets, trading_days, start, end)
    total = len(jobs)
    filled_rows = 0
    no_data_rows = 0
    failed: list[tuple[date, str, str]] = []
    stopped = False
    for idx, (sym, ranges) in enumerate(jobs):
        if stop_event is not None and stop_event():
            stopped = True
            break
        sym_filled = 0
        sym_no_data = 0
        sym_retry = 0
        for rs, re_ in ranges:
            df = source.bars([sym], rs, re_)
            got_days = set(pd.to_datetime(df["date"]).dt.date) if df is not None and not df.empty else set()
            if got_days:
                store.write_bars("stock", df)
                store.write_coverage("stock", df)
                sym_filled += len(df)
            unfilled = [d for d in trading_days if rs <= d <= re_ and d not in got_days]
            susp_days, boundary_days, anomaly_days, nostatus_days, api_ok = _classify_unreturned_days(
                assets, sym, unfilled
            )
            if api_ok:
                _mark_no_data([(d, sym) for d in susp_days], "suspended")
                _mark_no_data([(d, sym) for d in boundary_days], "boundary")
                failed.extend((d, sym, "anomaly") for d in anomaly_days)
                failed.extend((d, sym, "code_change") for d in nostatus_days)
            else:
                failed.extend((d, sym, "unknown") for d in unfilled)
            sym_no_data += len(susp_days) + len(boundary_days)
            sym_retry += len(anomaly_days) + len(nostatus_days) if api_ok else len(unfilled)
        filled_rows += sym_filled
        no_data_rows += sym_no_data
        if progress_cb is not None:
            progress_cb(
                {
                    "mode": "stock",
                    "current": sym,
                    "done_days": idx + 1,
                    "total_days": total,
                    "missing_count": len(ranges),
                    "filled_count": sym_filled,
                    "no_data_count": sym_no_data,
                    "retry_count": sym_retry,
                    "filled_rows": filled_rows,
                    "failed_count": len(failed),
                    "percent": (idx + 1) / total if total else 1.0,
                }
            )
        print(
            f"[stock] {idx + 1}/{total} {sym} 缺失 {len(ranges)} 段，已入库 {sym_filled} 行，"
            f"空补 {sym_no_data}，待复核 {sym_retry}",
            flush=True,
        )

    if failed:
        _update_suspect(failed)
    print(
        f"[stock] 完成：处理 {total} 只股票，已入库 {filled_rows} 行，空补 {no_data_rows} 条，"
        f"待复核 {len(failed)} 条",
        flush=True,
    )
    return {
        "checked_days": total,
        "filled_rows": filled_rows,
        "no_data": no_data_rows,
        "failed": len(failed),
        "stopped": stopped,
        "mode": "stock",
    }


def incremental(start: date, end: date, max_days: int = 0) -> dict:
    """截面增量（命令行/调度入口）：按天对齐。"""
    return align(start, end, max_days=max_days)


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="截面增量：补齐缺失交易日截面")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--max-days", type=int, default=0, help="单次最多补 N 天（0=全部）")
    args = ap.parse_args()
    load_dotenv()
    incremental(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end) if args.end else date.today(),
        max_days=args.max_days,
    )


if __name__ == "__main__":
    main()
