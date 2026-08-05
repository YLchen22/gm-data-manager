"""覆盖清单重建：coverage = bars 的纯投影，可从 bars 全量重建。

用途：
- 数据迁移 / 存储布局变更后重建覆盖清单；
- 手动增删 bars 文件后修复漂移（如"删 bars 留 coverage"导致的误判完整）；
- --compare 校验 bars 与 coverage 是否一致（审计模式）。

用法：
    python -m data.rebuild                       # 重建（原子覆盖写，清理残留）
    python -m data.rebuild --dry-run --compare   # 只审计不写
    python -m data.rebuild --asset stock

WebUI 通过任务"重建覆盖清单"调用（progress_cb / stop_event）。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

import pandas as pd

from data.store import Store


def _atomic_write(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def rebuild_coverage(
    asset: str = "stock",
    dry_run: bool = False,
    compare: bool = False,
    progress_cb: Callable[[dict], None] | None = None,
    stop_event: Callable[[], bool] | None = None,
    store: Store | None = None,
) -> dict:
    """从 bars 全量重建 coverage（date, symbol 投影）。

    - 只读 bars 的 (date, symbol) 列，按年去重排序后覆盖写 coverage 年度文件；
    - 无 bars 年份的残留 coverage 文件删除（修复"删 bars 留 coverage"漂移）；
    - compare：与现有 coverage 对比输出漂移行数（只报告，不参与写入判定）；
    - dry_run：不写入不删除，仅预览。
    """
    store = store or Store()
    bars_dir = store.bars_root / asset
    cov_dir = store.coverage_root / asset
    years = sorted(int(p.stem) for p in bars_dir.glob("*.parquet")) if bars_dir.exists() else []
    existing_years = (
        sorted(int(p.stem) for p in cov_dir.glob("*.parquet")) if cov_dir.exists() else []
    )

    total = 0
    drift_added = drift_removed = 0
    stopped = False
    for i, y in enumerate(years):
        if stop_event is not None and stop_event():
            stopped = True
            break
        keys = pd.read_parquet(bars_dir / f"{y}.parquet", columns=["date", "symbol"])
        cov = (
            keys.drop_duplicates(subset=["date", "symbol"], keep="last")
            .sort_values(["date", "symbol"])
            .reset_index(drop=True)
        )
        total += len(cov)
        if compare:
            old_path = store.coverage_path(asset, y)
            if old_path.exists():
                old = pd.read_parquet(old_path, columns=["date", "symbol"])
                old_set = set(zip(pd.to_datetime(old["date"]).dt.date, old["symbol"]))
            else:
                old_set = set()
            new_set = set(zip(pd.to_datetime(cov["date"]).dt.date, cov["symbol"]))
            drift_added += len(new_set - old_set)
            drift_removed += len(old_set - new_set)
        if not dry_run and not cov.empty:
            _atomic_write(cov, store.coverage_path(asset, y))
        if progress_cb is not None:
            progress_cb(
                {
                    "mode": "rebuild",
                    "current": str(y),
                    "done_days": i + 1,
                    "total_days": len(years),
                    "filled_rows": total,
                    "percent": (i + 1) / len(years) if years else 1.0,
                }
            )

    stale = [y for y in existing_years if y not in years]
    if not dry_run:
        for y in stale:
            p = store.coverage_path(asset, y)
            if p.exists():
                p.unlink()
    return {
        "asset": asset,
        "years": years,
        "rows": total,
        "empty": total == 0,
        "drift_added": drift_added,
        "drift_removed": drift_removed,
        "deleted_stale_years": stale,
        "checked_days": len(years),
        "stopped": stopped,
        "mode": "rebuild",
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="从 bars 重建覆盖清单（coverage）")
    ap.add_argument("--asset", default="stock")
    ap.add_argument("--dry-run", action="store_true", help="只审计不写入")
    ap.add_argument("--compare", action="store_true", help="同时对比现有 coverage 报告漂移")
    args = ap.parse_args()
    res = rebuild_coverage(asset=args.asset, dry_run=args.dry_run, compare=args.compare)
    print(
        f"[rebuild] {'预览' if args.dry_run else '完成'}: {res['asset']} "
        f"{len(res['years'])} 年 / {res['rows']} 行" + ("（空）" if res["empty"] else "")
    )
    if res["deleted_stale_years"]:
        print(f"[rebuild] 清理无 bars 的残留 coverage 年份: {res['deleted_stale_years']}")
    if args.compare:
        print(
            f"[rebuild] 漂移对比: coverage 缺 {res['drift_added']} 行 / "
            f"coverage 冗余 {res['drift_removed']} 行"
        )


if __name__ == "__main__":
    main()
