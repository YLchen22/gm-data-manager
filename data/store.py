"""数据仓库：按「资产类别 / 年份」分区存储 + 覆盖清单。

布局（与 ENGINE_DESIGN 的模块化原则一致，资产类别独立）：
    data/cache/bars/{asset}/{year}.parquet      # 行情，date+symbol 去重
    data/cache/coverage/{asset}/{year}.parquet  # 覆盖清单（date, symbol）

设计理由：
- 截面增量只动"当年"文件（读-合并-重写 1~3 秒/天），不做全量重写；
- 回测/研究按年份裁剪，读取高效；
- 完整性检查只查覆盖清单，不碰物理文件。
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache"

BAR_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "pre_close"]


class Store:
    def __init__(self, root: Path = DEFAULT_CACHE_DIR):
        self.root = root
        self.bars_root = root / "bars"
        self.coverage_root = root / "coverage"

    # ---- 路径 ----
    def bars_path(self, asset: str, year: int) -> Path:
        return self.bars_root / asset / f"{year}.parquet"

    def coverage_path(self, asset: str, year: int) -> Path:
        return self.coverage_root / asset / f"{year}.parquet"

    def years(self, asset: str) -> list[int]:
        d = self.bars_root / asset
        if not d.exists():
            return []
        return sorted(int(p.stem) for p in d.glob("*.parquet"))

    # ---- 写入 ----
    def write_bars(self, asset: str, df: pd.DataFrame) -> None:
        """写入行情（按年分区，date+symbol 去重）。"""
        if df is None or df.empty:
            return
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        for year, grp in df.groupby(df["date"].dt.year):
            self._merge_parquet(self.bars_path(asset, int(year)), grp, ["date", "symbol"])

    def write_coverage(self, asset: str, df: pd.DataFrame) -> None:
        """写入覆盖清单（date, symbol）。"""
        if df is None or df.empty:
            return
        cov = df[["date", "symbol"]].copy()
        cov["date"] = pd.to_datetime(cov["date"])
        for year, grp in cov.groupby(cov["date"].dt.year):
            self._merge_parquet(self.coverage_path(asset, int(year)), grp, ["date", "symbol"])

    def _merge_parquet(self, path: Path, new: pd.DataFrame, subset: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            old = pd.read_parquet(path)
            merged = pd.concat([old, new], ignore_index=True)
        else:
            merged = new
        merged = merged.drop_duplicates(subset=subset, keep="last")
        merged = merged.sort_values(subset).reset_index(drop=True)
        # 原子写入：先写临时文件再替换，避免并发进程读到半截文件导致损坏
        # （并发"读-合并-写"仍可能丢失最后写入的部分行，但补缺任务幂等，下次扫描会补回）
        tmp = path.with_name(path.name + ".tmp")
        merged.to_parquet(tmp, index=False)
        os.replace(tmp, path)

    # ---- 读取 ----
    def read_bars(
        self,
        asset: str,
        start: date,
        end: date,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frames = []
        for year in range(start.year, end.year + 1):
            p = self.bars_path(asset, year)
            if not p.exists():
                continue
            df = pd.read_parquet(p)
            df["date"] = pd.to_datetime(df["date"])
            frames.append(df)
        if not frames:
            return pd.DataFrame(columns=BAR_COLUMNS)
        out = pd.concat(frames, ignore_index=True)
        out = out[(out["date"] >= pd.Timestamp(start)) & (out["date"] <= pd.Timestamp(end))]
        if symbols:
            out = out[out["symbol"].isin(set(symbols))]
        return out.reset_index(drop=True)

    def coverage(self, asset: str) -> pd.DataFrame:
        """全部覆盖清单（date, symbol）。"""
        d = self.coverage_root / asset
        if not d.exists():
            return pd.DataFrame(columns=["date", "symbol"])
        frames = [pd.read_parquet(p) for p in sorted(d.glob("*.parquet"))]
        if not frames:
            return pd.DataFrame(columns=["date", "symbol"])
        out = pd.concat(frames, ignore_index=True)
        out["date"] = pd.to_datetime(out["date"])
        return out.reset_index(drop=True)

    def coverage_by_date(self, asset: str) -> dict[date, set[str]]:
        cov = self.coverage(asset)
        result: dict[date, set[str]] = {}
        if cov.empty:
            return result
        for d, g in cov.groupby(cov["date"].dt.date):
            result[d] = set(g["symbol"])
        return result

    # ---- 统计 ----
    def stats(self, asset: str) -> dict:
        """覆盖统计：文件数、总行数、截面覆盖范围。"""
        cov = self.coverage(asset)
        dates = sorted(cov["date"].dt.date.unique()) if not cov.empty else []
        return {
            "asset": asset,
            "years": self.years(asset),
            "covered_days": len(dates),
            "first_day": dates[0] if dates else None,
            "last_day": dates[-1] if dates else None,
            "covered_cells": len(cov),
        }
