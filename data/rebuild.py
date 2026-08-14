"""覆盖清单重建：coverage = meta 三分区的纯投影，可从数据文件全量重建。

用途：
- 数据迁移 / 存储布局变更后重建覆盖清单；
- 手动增删 meta 分区文件后修复漂移（如"删数据留 coverage"导致的误判完整）；
- --compare 校验数据文件与 coverage 是否一致（审计模式）。

用法：
    python -m data.rebuild                       # 重建（原子覆盖写，清理残留）
    python -m data.rebuild --dry-run --compare   # 只审计不写

WebUI 通过任务"重建覆盖清单"调用（progress_cb / stop_event）。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from typing import Callable

import pandas as pd

from dotenv import load_dotenv

from data.incremental import audit_no_data
from data.meta_store import META_SUBSETS, MetaStore


def _atomic_write(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def rebuild_meta_coverage(
    dry_run: bool = False,
    compare: bool = False,
    audit: bool = True,
    progress_cb: Callable[[dict], None] | None = None,
    stop_event: Callable[[], bool] | None = None,
    store: MetaStore | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """从 meta 三分区重建 coverage（(date, symbol, partition) 投影）。

    - 只读各分区文件的 (date, symbol) 列，按年去重排序后覆盖写 coverage 年度文件；
    - 无数据年份的残留 coverage 文件删除（修复"删数据留 coverage"漂移）；
    - compare：与现有 coverage 对比输出漂移行数（只报告，不参与写入判定）；
    - dry_run：不写入不删除，仅预览。
    重建后执行"异常记账阈值"保险检查（audit_no_data）：某天 anomaly/unknown
    记账超过阈值判定该天清单存疑，dry_run 只报告，否则移除异常记账使其重抓。
    """
    store = store or MetaStore()
    start = start or date(2016, 1, 1)
    end = end or date.today()
    plans: list[tuple[str, int]] = []
    existing: dict[str, set[int]] = {}
    for partition in META_SUBSETS:
        for y in store.years(partition):
            plans.append((partition, y))
        cov_dir = store.coverage_root / partition
        existing[partition] = (
            {int(p.stem) for p in cov_dir.glob("*.parquet")} if cov_dir.exists() else set()
        )

    total = 0
    drift_added = drift_removed = 0
    stopped = False
    for i, (partition, y) in enumerate(plans):
        if stop_event is not None and stop_event():
            stopped = True
            break
        keys = pd.read_parquet(store.meta_path(partition, y), columns=["date", "symbol"])
        cov = (
            keys.drop_duplicates(subset=["date", "symbol"], keep="last")
            .sort_values(["date", "symbol"])
            .reset_index(drop=True)
        )
        cov["partition"] = partition
        total += len(cov)
        if compare:
            old_path = store.coverage_path(partition, y)
            if old_path.exists():
                old = pd.read_parquet(old_path, columns=["date", "symbol", "partition"])
                old_set = set(zip(pd.to_datetime(old["date"]).dt.date, old["symbol"]))
            else:
                old_set = set()
            new_set = set(zip(pd.to_datetime(cov["date"]).dt.date, cov["symbol"]))
            drift_added += len(new_set - old_set)
            drift_removed += len(old_set - new_set)
        if not dry_run and not cov.empty:
            _atomic_write(cov, store.coverage_path(partition, y))
        print(
            f"[rebuild-meta] {partition}/{y} 已投影 {len(cov)} 行 · 累计 {total} 行"
            f"（{i + 1}/{len(plans)}）",
            flush=True,
        )
        if progress_cb is not None:
            progress_cb(
                {
                    "mode": "rebuild_meta",
                    "current": f"{partition}/{y}",
                    "done_days": i + 1,
                    "total_days": len(plans),
                    "filled_rows": total,
                    "percent": (i + 1) / len(plans) if plans else 1.0,
                }
            )

    stale: list[str] = []
    if not dry_run:
        for partition in META_SUBSETS:
            valid_years = set(store.years(partition))
            for y in existing[partition] - valid_years:
                p = store.coverage_path(partition, y)
                if p.exists():
                    p.unlink()
                    stale.append(f"{partition}/{y}")
    aud = audit_no_data(start, end, dry_run=dry_run) if audit else {
        "flagged_days": [], "removed_rows": 0, "details": []
    }
    return {
        "years": sorted({y for _, y in plans}),
        "rows": total,
        "empty": total == 0,
        "drift_added": drift_added,
        "drift_removed": drift_removed,
        "deleted_stale_years": stale,
        "audit": aud,
        "checked_days": len(plans),
        "stopped": stopped,
        "mode": "rebuild_meta",
    }


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="从 meta 三分区重建覆盖清单（coverage）")
    ap.add_argument("--dry-run", action="store_true", help="只审计不写入")
    ap.add_argument("--compare", action="store_true", help="同时对比现有 coverage 报告漂移")
    ap.add_argument("--no-audit", action="store_true", help="跳过异常记账阈值保险检查")
    args = ap.parse_args()
    load_dotenv()
    res = rebuild_meta_coverage(
        dry_run=args.dry_run, compare=args.compare, audit=not args.no_audit
    )
    print(
        f"[rebuild] {'预览' if args.dry_run else '完成'}: "
        f"{len(res['years'])} 年 / {res['rows']} 行" + ("（空）" if res["empty"] else "")
    )
    if res["deleted_stale_years"]:
        print(f"[rebuild] 清理无数据文件的残留 coverage: {res['deleted_stale_years']}")
    if args.compare:
        print(
            f"[rebuild] 漂移对比: coverage 缺 {res['drift_added']} 行 / "
            f"coverage 冗余 {res['drift_removed']} 行"
        )
    aud = res.get("audit") or {}
    if aud.get("flagged_days"):
        print(
            f"[rebuild] 异常审计: 标记 {len(aud['flagged_days'])} 天清单存疑（需重抓）: "
            f"{aud['flagged_days'][:10]}{'...' if len(aud['flagged_days']) > 10 else ''}"
        )
        if not args.dry_run:
            print(f"[rebuild] 已移除 {aud.get('removed_rows', 0)} 条异常记账，下次抓取将重抓这些天")
    else:
        print("[rebuild] 异常审计: 无存疑天数")


if __name__ == "__main__":
    main()
