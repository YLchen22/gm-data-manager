"""DataHub：统一取数入口（缓存优先，缺失从数据源拉取并回写）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

import pandas as pd

from core.contracts import DataSource
from data.cache import ParquetCache


class DataHub:
    def __init__(self, source: DataSource, cache: ParquetCache | None = None):
        self.source = source
        self.cache = cache or ParquetCache()

    def bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """缓存优先读取；对缓存缺失的部分先增量补齐。"""
        self.ensure_bars(symbols, start, end)
        frames = [self.cache.read_bars(s, start, end) for s in symbols]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def ensure_bars(self, symbols: Sequence[str], start: date, end: date, batch_size: int = 50) -> None:
        """增量拉取：只拉缓存缺失的区间（头尾各至多一段）。

        batch_size 控制单次数据源请求的股票数，避免 gm 单次 16MB 上限。
        """
        need: dict[tuple[date, date], list[str]] = {}
        for sym in symbols:
            rng = self.cache.bars_range(sym)
            if rng is None:
                need.setdefault((start, end), []).append(sym)
                continue
            lo, hi = rng
            if lo > start:
                need.setdefault((start, lo - timedelta(days=1)), []).append(sym)
            if hi < end:
                need.setdefault((hi + timedelta(days=1), end), []).append(sym)
        for (s, e), syms in need.items():
            for i in range(0, len(syms), batch_size):
                chunk = syms[i : i + batch_size]
                df = self.source.bars(chunk, s, e)
                self.cache.write_bars(df)

    def events(self, kind: str, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        return self.source.events(kind, symbols, start, end)

    def universe(self, d: date) -> Sequence[str]:
        return self.source.universe(d)
