"""市场扫描：全量对齐（先扫描本地，只补缺失，避免重复抓取）。

与截面增量共用 data.incremental.align 核心，区别仅在起始日期语义：
市场扫描默认从 2016-01-01 起全量对齐到最新。
用法：python -m data.sweep [--start 2016-01-01]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Callable

from dotenv import load_dotenv

from data.incremental import align


def sweep(
    start: date,
    end: date,
    max_days: int = 0,
    progress_cb: Callable[[dict], None] | None = None,
    stop_event: Callable[[], bool] | None = None,
) -> dict:
    """市场扫描：从 start 起全量对齐（只补缺失）。"""
    print(f"[sweep] 市场扫描 {start} ~ {end}（先扫描本地，只补缺失）", flush=True)
    return align(start, end, max_days=max_days, progress_cb=progress_cb, stop_event=stop_event)


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
