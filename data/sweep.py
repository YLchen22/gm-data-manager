"""市场扫描：全量对齐（按股票逐个抓取，先扫描本地只补缺失）。

市场扫描按"股票维度"对齐：每只股票计算 2016 至今缺失的日期区间，
合并连续区间后整段拉取（与截面增量的按天维度不同）。
用法：python -m data.sweep [--start 2016-01-01]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Callable

from dotenv import load_dotenv

from data.incremental import align_by_stock


def sweep(
    start: date,
    end: date,
    max_days: int = 0,
    progress_cb: Callable[[dict], None] | None = None,
    stop_event: Callable[[], bool] | None = None,
) -> dict:
    """市场扫描：按股票逐个对齐（只补缺失）。"""
    print(f"[sweep] 市场扫描 {start} ~ {end}（按股票逐个，只补缺失）", flush=True)
    return align_by_stock(start, end, progress_cb=progress_cb, stop_event=stop_event)


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="市场扫描：全量对齐")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    load_dotenv()
    sweep(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end) if args.end else date.today(),
    )


if __name__ == "__main__":
    main()
