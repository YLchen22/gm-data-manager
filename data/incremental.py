"""数据对齐：市场全量（按股票）与截面增量（按天）。

两种任务都遵循"先扫描本地覆盖，只补缺失，避免重复抓取"：
- 市场全量（align_by_stock）：按股票逐个对齐——每只股票计算 2016 至今缺失的日期区间，
  合并连续区间后整段拉取（股票维度完整性）；
- 截面增量（align）：按交易日对齐——每天计算有效性集合（已上市未退市）− 已覆盖集合，
  拉取该日缺失的股票（日期维度完整性）。

拉不到的 (date, symbol) 记入 suspect，连续 3 次后标记为疑似停牌，移出自动补缺。
WebUI 通过 progress_cb / stop_event 驱动动态进度条与停止操作。
"""

from __future__ import annotations

import argparse
import sys
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd
from dotenv import load_dotenv

from data.asset import load_assets, valid_symbols_on
from data.gm_source import GmDataSource
from data.store import Store

SUSPECT_PATH = Path(__file__).resolve().parent / "cache" / "status" / "suspect.parquet"
MAX_ATTEMPTS = 3

ProgressCB = Callable[[dict], None]
StopCheck = Callable[[], bool]


def _load_suspect() -> pd.DataFrame:
    if not SUSPECT_PATH.exists():
        return pd.DataFrame(columns=["date", "symbol", "attempts", "status"])
    return pd.read_parquet(SUSPECT_PATH)


def _save_suspect(df: pd.DataFrame) -> None:
    SUSPECT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SUSPECT_PATH, index=False)


def _update_suspect(failed: list[tuple[date, str]]) -> None:
    """拉取失败的 (date, symbol) 累计尝试次数；满 MAX_ATTEMPTS 标记 suspended。"""
    df = _load_suspect()
    now = pd.DataFrame({"date": [pd.Timestamp(d) for d, _ in failed], "symbol": [s for _, s in failed]})
    merged = pd.concat([df, now.assign(attempts=1, status="retry")], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    grp = merged.groupby(["date", "symbol"], as_index=False).agg(
        attempts=("attempts", "sum"), status=("status", "last")
    )
    grp.loc[grp["attempts"] >= MAX_ATTEMPTS, "status"] = "suspended"
    _save_suspect(grp)


def _missing_blocks(store: Store, assets: pd.DataFrame, start: date, end: date) -> list[tuple[date, set[str]]]:
    """计算每个交易日的缺失 symbol 集合。"""
    source = GmDataSource()
    trading_days = source.trading_dates(start, end)
    trading_days = [date.fromisoformat(d) for d in trading_days]
    covered = store.coverage_by_date("stock")
    suspect = _load_suspect()
    blocked: set[tuple[date, str]] = set()
    if not suspect.empty:
        # 只排除已确认"疑似停牌"的记录；retry 状态继续重试（attempts 递增至 3 后转 suspended）
        sus_active = suspect[suspect["status"] == "suspended"]
        blocked = set(zip(pd.to_datetime(sus_active["date"]).dt.date, sus_active["symbol"]))

    blocks = []
    for d in trading_days:
        valid = valid_symbols_on(assets, d)
        have = covered.get(d, set())
        missing = valid - have - {s for (dd, s) in blocked if dd == d}
        if missing:
            blocks.append((d, missing))
    return blocks


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
    """每只股票 2016 至今缺失的日期区间（按股票维度）。"""
    covered = store.coverage("stock")
    covered_by_symbol: dict[str, set[date]] = {}
    if not covered.empty:
        for sym, g in covered.groupby("symbol"):
            covered_by_symbol[sym] = set(g["date"].dt.date)

    result: list[tuple[str, list[tuple[date, date]]]] = []
    for sym, listed, delisted in assets[["symbol", "listed_date", "delisted_date"]].itertuples(index=False):
        lo = bisect_left(trading_days, max(listed, start))
        hi = bisect_right(trading_days, min(delisted, end))
        valid = trading_days[lo:hi]
        if not valid:
            continue
        have = covered_by_symbol.get(sym, set())
        missing = sorted(set(valid) - have)
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
    """补齐缺失截面（市场扫描与截面增量共用）。"""
    store = Store()
    source = GmDataSource()
    assets = load_assets(source)
    blocks = _missing_blocks(store, assets, start, end)
    if max_days > 0:
        blocks = blocks[:max_days]

    total = len(blocks)
    filled_rows = 0
    failed: list[tuple[date, str]] = []
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
        for s in missing - got:
            failed.append((d, s))
        if progress_cb is not None:
            progress_cb(
                {
                    "mode": "section",
                    "current": d.isoformat(),
                    "done_days": idx + 1,
                    "total_days": total,
                    "missing_count": len(missing),
                    "filled_count": len(got),
                    "filled_rows": filled_rows,
                    "failed_count": len(failed),
                    "percent": (idx + 1) / total if total else 1.0,
                }
            )
        print(f"[align] {d} 缺失 {len(missing)} 只，补齐 {len(got)} 只", flush=True)

    if failed:
        _update_suspect(failed)
    print(f"[align] 完成：补齐 {filled_rows} 行，失败 {len(failed)} 只（已计入 suspect）", flush=True)
    return {
        "checked_days": len(blocks),
        "filled_rows": filled_rows,
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
    failed: list[tuple[date, str]] = []
    stopped = False
    for idx, (sym, ranges) in enumerate(jobs):
        if stop_event is not None and stop_event():
            stopped = True
            break
        sym_filled = 0
        for rs, re_ in ranges:
            df = source.bars([sym], rs, re_)
            got = set(df["symbol"]) if df is not None and not df.empty else set()
            if got:
                store.write_bars("stock", df)
                store.write_coverage("stock", df)
                sym_filled += len(df)
            if sym not in got:
                # 该股票整段缺失未返回（停牌/无数据），逐日记 suspect
                d = rs
                while d <= re_:
                    failed.append((d, sym))
                    d += timedelta(days=1)
        filled_rows += sym_filled
        if progress_cb is not None:
            progress_cb(
                {
                    "mode": "stock",
                    "current": sym,
                    "done_days": idx + 1,
                    "total_days": total,
                    "missing_count": len(ranges),
                    "filled_count": sym_filled,
                    "filled_rows": filled_rows,
                    "failed_count": len(failed),
                    "percent": (idx + 1) / total if total else 1.0,
                }
            )
        print(f"[stock] {idx + 1}/{total} {sym} 缺失 {len(ranges)} 段，补齐 {sym_filled} 行", flush=True)

    if failed:
        _update_suspect(failed)
    print(f"[stock] 完成：处理 {total} 只股票，补齐 {filled_rows} 行，失败 {len(failed)} 条", flush=True)
    return {
        "checked_days": total,
        "filled_rows": filled_rows,
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
