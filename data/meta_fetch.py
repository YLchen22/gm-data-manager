"""行情元数据统一截面任务：bar / mv_basic / valuation 三分区按日一键抓取。

设计（用户确认）：
- 单任务、按交易日逐日推进：每天 get_symbols 定基准行键（当日有效集合，含停牌），
  行情/市值股本/估值三个分区对齐到该行键后落盘，停牌日行情列为空；
- 三个分区行键严格一致（(date, symbol)），coverage 按分区记账，
  完整性 = coverage ∪ no_data ⊇ 当日有效集合；
- 代码变更/边界（如 SZSE.302132）记入 no_data（boundary），365 天复核；
- 一次性跑完 2016→今即满足全部数据需求；之后每日增量一次。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable

import pandas as pd
from dotenv import load_dotenv

from data.asset import load_assets, valid_symbols_on
from data.gm_source import GmDataSource
from data.incremental import _classify_unreturned, _completed_days, _mark_no_data, _no_data_blocked
from data.meta_store import META_SUBSETS, MetaStore

TODAY_CUTOFF = time(18, 0)

ProgressCB = Callable[[dict], None]
StopCheck = Callable[[], bool]


def _merge_to_base(
    raw: pd.DataFrame, d: date, base: pd.DataFrame, value_cols: list[str]
) -> pd.DataFrame:
    """把某分区抓取结果对齐到基准行键（base 为当日全部有效股票）。

    base 只含 date/symbol；raw 按 (symbol, date) merge 到 base，
    缺失（接口未返回）的股票保留行、字段为 NaN——保证三分区行键一致。
    """
    if raw is None or raw.empty:
        out = base.copy()
        for c in value_cols:
            out[c] = pd.NA
        return out
    sub = raw[raw["date"].dt.date == d]
    sub = sub.drop_duplicates(subset=["date", "symbol"])
    return base.merge(sub, on=["date", "symbol"], how="left")


def _plan_meta(
    start: date, end: date, source: GmDataSource | None = None, store: MetaStore | None = None
) -> tuple[pd.DataFrame, list[date], dict[str, dict[date, set[str]]], set[tuple[date, str]]]:
    """任务规划：资产表 / 已完成交易日 / 三分区按日覆盖 / no_data 阻塞集合。"""
    source = source or GmDataSource()
    store = store or MetaStore()
    assets = load_assets(source)
    days = [date.fromisoformat(d) for d in source.trading_dates(start, end)]
    days = _completed_days(days)
    covered: dict[str, dict[date, set[str]]] = {}
    for p in META_SUBSETS:
        covered[p] = store.coverage_by_date(p)
    blocked = _no_data_blocked()
    return assets, days, covered, blocked


def scan_missing_meta(
    start: date,
    end: date,
    progress_cb: ProgressCB | None = None,
    source: GmDataSource | None = None,
    store: MetaStore | None = None,
) -> list[tuple[date, tuple[str, ...]]]:
    """返回 [(交易日, 缺失分区)]：分区当天覆盖不满即视为缺失。"""
    assets, days, covered, blocked = _plan_meta(start, end, source=source, store=store)
    blocks: list[tuple[date, tuple[str, ...]]] = []
    total = len(days)
    for i, d in enumerate(days):
        valid = valid_symbols_on(assets, d)
        need: list[str] = []
        for p in META_SUBSETS:
            have = covered[p].get(d, set())
            missing = {s for s in valid - have if (d, s) not in blocked}
            if missing:
                need.append(p)
        if need:
            blocks.append((d, tuple(need)))
        if progress_cb is not None and (i % 200 == 0 or i == total - 1):
            progress_cb(
                {
                    "mode": "meta",
                    "phase": "scan",
                    "current": d.isoformat(),
                    "done_days": i + 1,
                    "total_days": total,
                    "percent": (i + 1) / total if total else 1.0,
                }
            )
    return blocks


def scan_missing_meta_summary(
    start: date,
    end: date,
    source: GmDataSource | None = None,
    store: MetaStore | None = None,
) -> dict:
    """WebUI 数据详情：三分区缺失概览。"""
    blocks = scan_missing_meta(start, end, source=source, store=store)
    rows = sum(len(subs) for _, subs in blocks)
    first = blocks[0][0].isoformat() if blocks else None
    subsets = sorted({s for _, subs in blocks for s in subs})
    return {
        "meta_days": len(blocks),
        "meta_rows": rows,
        "meta_first_missing_day": first,
        "meta_subsets": subsets,
    }


def align_meta(
    start: date,
    end: date,
    max_days: int = 0,
    progress_cb: ProgressCB | None = None,
    stop_event: StopCheck | None = None,
    source: GmDataSource | None = None,
    store: MetaStore | None = None,
) -> dict:
    """统一截面任务：按日推进补齐三分区；停牌日行情留空行；边界记账。"""
    store = store or MetaStore()
    source = source or GmDataSource()
    assets, days, covered, blocked = _plan_meta(start, end, source=source, store=store)
    blocks = scan_missing_meta(start, end, progress_cb=progress_cb, source=source, store=store)
    if max_days > 0:
        blocks = blocks[:max_days]

    total = len(blocks)
    filled_rows = 0
    boundary_count = 0
    stopped = False
    for idx, (d, need) in enumerate(blocks):
        if stop_event is not None and stop_event():
            stopped = True
            break
        # 1) 基准行键与 p0 字段
        p0 = source.meta_p0(d)
        if p0 is None or p0.empty:
            print(f"[meta] {d} 基准为空，跳过（{idx + 1}/{total}）", flush=True)
            continue
        base = p0[["date", "symbol"]].copy()
        valid = valid_symbols_on(assets, d)
        day_boundary: list[tuple[date, str]] = []
        for s in valid - set(p0["symbol"]):
            if (d, s) not in blocked:
                day_boundary.append((d, s))
        raw_set: dict[str, set[str]] = {}
        day_rows: dict[str, int] = {}
        # 2) bar 分区：行情对齐基准行键（停牌日行情列为空）
        if "bar" in need:
            raw_bar = source.meta_bar(d, sorted(set(p0["symbol"])))
            raw_set["bar"] = set(raw_bar["symbol"]) if raw_bar is not None and not raw_bar.empty else set()
            bar = _merge_to_base(raw_bar, d, base, ["open", "high", "low", "close", "volume", "amount", "pre_close"])
            p0_fields = ["pre_close", "upper_limit", "lower_limit", "adj_factor", "turn_rate", "is_suspended", "is_st"]
            bar = bar.drop(columns=["pre_close"], errors="ignore")
            bar = bar.merge(p0.drop(columns=["pre_close"], errors="ignore"), on=["date", "symbol"], how="left")
            store.write_meta("bar", bar)
            store.write_coverage("bar", bar)
            filled_rows += len(bar)
            day_rows["bar"] = len(bar)
        # 3) mv_basic 分区
        if "mv_basic" in need:
            raw_mv = source.meta_mv_basic(d, sorted(set(p0["symbol"])))
            raw_set["mv_basic"] = set(raw_mv["symbol"]) if raw_mv is not None and not raw_mv.empty else set()
            mv_basic = _merge_to_base(raw_mv, d, base, ["tot_mv", "a_mv", "turnrate", "ttl_shr", "circ_shr"])
            store.write_meta("mv_basic", mv_basic)
            store.write_coverage("mv_basic", mv_basic)
            filled_rows += len(mv_basic)
            day_rows["mv_basic"] = len(mv_basic)
        # 4) valuation 分区
        if "valuation" in need:
            raw_val = source.meta_valuation(d, sorted(set(p0["symbol"])))
            raw_set["valuation"] = set(raw_val["symbol"]) if raw_val is not None and not raw_val.empty else set()
            val = _merge_to_base(
                raw_val, d, base,
                ["pe_ttm", "pe_ttm_cut", "pb_mrq", "ps_ttm", "pcf_ttm_oper", "dy_ttm"],
            )
            store.write_meta("valuation", val)
            store.write_coverage("valuation", val)
            filled_rows += len(val)
            day_rows["valuation"] = len(val)
        # 5) 边界记账：get_symbols 未返回（代码变更/边界）+ 分区接口少返回（NaN 补齐但记账复核）
        for p in need:
            have = raw_set.get(p, set())
            for s in set(p0["symbol"]) - have:
                if (d, s) not in blocked:
                    day_boundary.append((d, s))
        if day_boundary:
            _mark_no_data(day_boundary, "boundary")
            boundary_count += len(day_boundary)
        parts = [f"{d}"]
        for p in ("bar", "mv_basic", "valuation"):
            if p in day_rows:
                parts.append(f"{p} {day_rows[p]}")
        if day_boundary:
            parts.append(f"边界 {len(day_boundary)}")
        print(
            "[meta] " + " · ".join(parts),
            flush=True,
        )
        if progress_cb is not None:
            progress_cb(
                {
                    "mode": "meta",
                    "phase": "fetch",
                    "current": d.isoformat(),
                    "done_days": idx + 1,
                    "total_days": total,
                    "missing_count": len(need),
                    "filled_count": len(need),
                    "no_data_count": len(day_boundary),
                    "retry_count": 0,
                    "filled_rows": filled_rows,
                    "percent": (idx + 1) / total if total else 1.0,
                }
            )

    print(
        f"[meta] 完成：处理 {total} 天，已入库 {filled_rows} 行，边界记账 {boundary_count} 条",
        flush=True,
    )
    return {
        "checked_days": total,
        "filled_rows": filled_rows,
        "no_data": boundary_count,
        "failed": boundary_count,
        "stopped": stopped,
        "mode": "meta",
    }


def meta_incremental(start: date, end: date, max_days: int = 0) -> dict:
    """命令行/调度入口。"""
    return align_meta(start, end, max_days=max_days)


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="行情元数据截面任务：三分区按日补齐")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--max-days", type=int, default=0, help="单次最多补 N 天（0=全部）")
    args = ap.parse_args()
    load_dotenv()
    meta_incremental(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end) if args.end else date.today(),
        max_days=args.max_days,
    )


if __name__ == "__main__":
    main()
