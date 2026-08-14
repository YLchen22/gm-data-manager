"""行情元数据仓库：bar / mv_basic / valuation 三个分区，按年分片。

布局（行键统一为 (date, symbol)，含停牌日）：
    data/cache/meta/{partition}/{year}.parquet
    data/cache/meta_coverage/{partition}/{year}.parquet   # (date, symbol, partition)

设计约束（用户确认）：
- bar      = 行情 + p0（OHLCV/amount/pre_close + 涨跌停/复权因子/换手/停牌/ST）
- mv_basic = 市值 + 股本（tot_mv/a_mv + turnrate/ttl_shr/circ_shr）
- valuation = 估值（PE/PB/PS/PCF/股息率）
- 三个分区由同一按日任务抓取，行键 = 当日有效集合（含停牌，停牌日行情列为空）；
- coverage 独立记账（meta_coverage），完整性 = coverage ∪ no_data ⊇ 当日有效集合。
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache"

# 分区 -> 落盘列（symbol, date 由仓库统一处理）
META_COLUMNS: dict[str, list[str]] = {
    "bar": [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pre_close",
        "upper_limit",
        "lower_limit",
        "adj_factor",
        "turn_rate",
        "is_suspended",
        "is_st",
    ],
    "mv_basic": ["tot_mv", "a_mv", "turnrate", "ttl_shr", "circ_shr"],
    "valuation": [
        "pe_ttm",
        "pe_ttm_cut",
        "pb_mrq",
        "ps_ttm",
        "pcf_ttm_oper",
        "dy_ttm",
    ],
}

META_SUBSETS: tuple[str, ...] = tuple(META_COLUMNS)


class MetaStore:
    def __init__(self, root: Path = DEFAULT_CACHE_DIR):
        self.root = root
        self.meta_root = root / "meta"
        self.coverage_root = root / "meta_coverage"

    # ---- 路径 ----
    def meta_path(self, partition: str, year: int) -> Path:
        return self.meta_root / partition / f"{year}.parquet"

    def coverage_path(self, partition: str, year: int) -> Path:
        return self.coverage_root / partition / f"{year}.parquet"

    def years(self, partition: str) -> list[int]:
        d = self.meta_root / partition
        if not d.exists():
            return []
        return sorted(int(p.stem) for p in d.glob("*.parquet"))

    # ---- 写入 ----
    def write_meta(self, partition: str, df: pd.DataFrame) -> None:
        """按年分区写入（date+symbol 去重，原子替换）。"""
        if partition not in META_COLUMNS:
            raise ValueError(f"未知 meta 分区: {partition}")
        if df is None or df.empty:
            return
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        for year, grp in df.groupby(df["date"].dt.year):
            self._merge_parquet(self.meta_path(partition, int(year)), grp, ["date", "symbol"])

    def write_coverage(self, partition: str, df: pd.DataFrame) -> None:
        """写入 (date, symbol, partition) 覆盖清单。"""
        if df is None or df.empty:
            return
        cov = df[["date", "symbol"]].copy()
        cov["partition"] = partition
        cov["date"] = pd.to_datetime(cov["date"])
        for year, grp in cov.groupby(cov["date"].dt.year):
            self._merge_parquet(self.coverage_path(partition, int(year)), grp, ["date", "symbol"])

    def _merge_parquet(self, path: Path, new: pd.DataFrame, subset: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            old = pd.read_parquet(path)
            merged = pd.concat([old, new], ignore_index=True)
        else:
            merged = new
        merged = merged.drop_duplicates(subset=subset, keep="last")
        merged = merged.sort_values(subset).reset_index(drop=True)
        tmp = path.with_name(path.name + ".tmp")
        merged.to_parquet(tmp, index=False)
        os.replace(tmp, path)

    # ---- 读取 ----
    def read_meta(
        self,
        partition: str,
        start: date,
        end: date,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frames = []
        for year in range(start.year, end.year + 1):
            p = self.meta_path(partition, year)
            if not p.exists():
                continue
            df = pd.read_parquet(p)
            df["date"] = pd.to_datetime(df["date"])
            frames.append(df)
        if not frames:
            return pd.DataFrame(columns=["symbol", "date"] + META_COLUMNS[partition])
        out = pd.concat(frames, ignore_index=True)
        out = out[(out["date"] >= pd.Timestamp(start)) & (out["date"] <= pd.Timestamp(end))]
        if symbols:
            out = out[out["symbol"].isin(set(symbols))]
        return out.reset_index(drop=True)

    def coverage(self, partition: str) -> pd.DataFrame:
        d = self.coverage_root / partition
        if not d.exists():
            return pd.DataFrame(columns=["date", "symbol", "partition"])
        frames = [pd.read_parquet(p) for p in sorted(d.glob("*.parquet"))]
        if not frames:
            return pd.DataFrame(columns=["date", "symbol", "partition"])
        out = pd.concat(frames, ignore_index=True)
        out["date"] = pd.to_datetime(out["date"])
        return out.reset_index(drop=True)

    def coverage_by_date(self, partition: str) -> dict[date, set[str]]:
        cov = self.coverage(partition)
        result: dict[date, set[str]] = {}
        if cov.empty:
            return result
        for d, g in cov.groupby(cov["date"].dt.date):
            result[d] = set(g["symbol"])
        return result

    # ---- 行键对齐断言 ----
    @staticmethod
    def row_keys(df: pd.DataFrame) -> set[tuple[date, str]]:
        if df is None or df.empty:
            return set()
        return set(zip(pd.to_datetime(df["date"]).dt.date, df["symbol"]))

    def stats(self, partition: str) -> dict:
        cov = self.coverage(partition)
        dates = sorted(cov["date"].dt.date.unique()) if not cov.empty else []
        return {
            "partition": partition,
            "years": self.years(partition),
            "covered_days": len(dates),
            "first_day": dates[0] if dates else None,
            "last_day": dates[-1] if dates else None,
            "covered_cells": len(cov),
        }
