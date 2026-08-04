"""parquet 缓存：按 symbol 一文件，增量合并。

原始数据不提交 git（见 .gitignore：data/cache/）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache"


class ParquetCache:
    def __init__(self, root: Path = DEFAULT_CACHE_DIR):
        self.root = root
        self.bars_dir = root / "bars"
        self.bars_dir.mkdir(parents=True, exist_ok=True)

    # ---- bars ----
    def bars_path(self, symbol: str) -> Path:
        return self.bars_dir / f"{symbol.replace('.', '_')}.parquet"

    def has_bars(self, symbol: str) -> bool:
        return self.bars_path(symbol).exists()

    def bars_range(self, symbol: str) -> tuple[date, date] | None:
        """该 symbol 缓存数据的日期范围；无缓存返回 None。"""
        p = self.bars_path(symbol)
        if not p.exists():
            return None
        df = pd.read_parquet(p, columns=["date"])
        dates = pd.to_datetime(df["date"]).dt.date
        return (dates.min(), dates.max())

    def read_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        p = self.bars_path(symbol)
        if not p.exists():
            return pd.DataFrame()
        df = pd.read_parquet(p)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)

    def write_bars(self, df: pd.DataFrame) -> None:
        """写入/合并日线（按 symbol 分区，date 去重取最新）。"""
        if df is None or df.empty:
            return
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        for symbol, grp in df.groupby("symbol", sort=False):
            p = self.bars_path(symbol)
            if p.exists():
                old = pd.read_parquet(p)
                old["date"] = pd.to_datetime(old["date"])
                merged = pd.concat([old, grp]).drop_duplicates(subset=["date"], keep="last").sort_values("date")
            else:
                merged = grp.sort_values("date")
            merged.to_parquet(p, index=False)
