"""历史数据拉取脚本（写入 parquet 缓存）。

用法（项目根目录）：
    python -m data.fetch --start 2018-01-01 [--end 2026-08-04] [--batch-size 200] [--limit 50]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

from config import load_config
from data.cache import ParquetCache
from data.gm_source import GmDataSource
from data.hub import DataHub
from data.universe import build_universe_codes


def main() -> None:
    # 修复 Windows 管道下 stdout 块缓冲导致进度输出丢失的问题
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="拉取历史日线并缓存为 parquet")
    ap.add_argument("--start", default="2018-01-01", help="起始日期 YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--batch-size", type=int, default=50, help="每批股票数（gm 单次查询有 16MB 上限，默认 50）")
    ap.add_argument("--step-years", type=int, default=1, help="按多少年一段切分拉取（gm 单次 16MB 上限，默认 1 年）")
    ap.add_argument("--limit", type=int, default=0, help="仅拉前 N 只（测试用）")
    args = ap.parse_args()

    load_dotenv()
    cfg = load_config()
    source = GmDataSource()
    hub = DataHub(source, ParquetCache())

    end = date.fromisoformat(args.end) if args.end else date.today()
    start = date.fromisoformat(args.start)
    print(f"[fetch] ref_date={end.isoformat()}")

    codes = build_universe_codes(hub, cfg.universe, end)
    if args.limit:
        codes = codes[: args.limit]
    print(f"[fetch] 股票池 {len(codes)} 只（limit={args.limit or 'all'}）")

    chunks = []
    cur = start
    while cur <= end:
        ce = min(date(cur.year + args.step_years, 1, 1) - timedelta(days=1), end)
        chunks.append((cur, ce))
        cur = ce + timedelta(days=1)

    total = 0
    for i in range(0, len(codes), args.batch_size):
        batch = codes[i : i + args.batch_size]
        batch_rows = 0
        for cs, ce in chunks:
            df = source.bars(batch, cs, ce)
            hub.cache.write_bars(df)
            batch_rows += len(df)
        total += batch_rows
        print(f"[fetch] {min(i + args.batch_size, len(codes))}/{len(codes)}  cached {batch_rows} 行")
    print(f"[fetch] 完成：共缓存 {total} 行，起始 {start.isoformat()} 至 {end.isoformat()}")


if __name__ == "__main__":
    main()
