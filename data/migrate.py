"""旧缓存迁移：一股票一文件（data/cache/bars/*.parquet）→ 新年度分区布局。

一次性工具；迁移后旧文件由用户确认后删除（见 AGENTS.md 批量删除规则）。
用法：python -m data.migrate --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from data.store import Store


def migrate(store: Store, legacy_dir: Path | None = None, dry_run: bool = False) -> dict:
    legacy_dir = legacy_dir or store.bars_root
    files = sorted(legacy_dir.glob("*.parquet"))
    frames = [pd.read_parquet(f) for f in files]
    all_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not dry_run and not all_df.empty:
        # 一次性写入：write_bars 内部按年分区，每年文件只合并一次
        store.write_bars("stock", all_df)
        store.write_coverage("stock", all_df)
    return {"legacy_files": len(files), "rows": len(all_df), "dry_run": dry_run}


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="迁移旧 symbol 文件缓存到新年度布局")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = ap.parse_args()
    result = migrate(Store(), dry_run=args.dry_run)
    print(f"迁移{'预览' if args.dry_run else '完成'}: 旧文件 {result['legacy_files']} 个，共 {result['rows']} 行")


if __name__ == "__main__":
    main()
