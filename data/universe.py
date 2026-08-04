"""股票池构建：沪深主板静态过滤 + 流动性/历史停牌动态过滤。"""

from __future__ import annotations

import re
from datetime import date
from typing import Sequence

import pandas as pd

from config import UniverseConfig
from data.hub import DataHub

# 主板代码规则：SHSE 60xxxx；SZSE 00x（含中小板 002/003，已并入深主板）
_MAINBOARD_RE = re.compile(r"^(SHSE\.60\d{4}|SZSE\.00[0-3]\d{3})$")


def is_mainboard(symbol: str) -> bool:
    return bool(_MAINBOARD_RE.match(symbol))


def is_st(sec_name: str) -> bool:
    return "ST" in str(sec_name).upper()


def static_universe(hub: DataHub, cfg: UniverseConfig, ref_date: date) -> pd.DataFrame:
    """静态过滤：主板 + 非 ST + 上市满 min_listing_days 交易日 + 当前未停牌。"""
    ins = hub.source.instruments()
    ins = ins[ins["symbol"].map(is_mainboard)].copy()
    ins = ins[~ins["sec_name"].map(is_st)]
    td = hub.source.trading_dates(date(2010, 1, 1), ref_date)
    min_listed = pd.Timestamp(td[-cfg.min_listing_days] if len(td) > cfg.min_listing_days else td[0])
    ins = ins[pd.to_datetime(ins["listed_date"]) <= min_listed]
    ins = ins[ins["is_suspended"] == 0]
    return ins.reset_index(drop=True)


def liquidity_filter(
    hub: DataHub, codes: Sequence[str], cfg: UniverseConfig, ref_date: date, lookback_days: int = 20
) -> list[str]:
    """按最近 lookback_days 日均成交额剔除后 drop_pct 的股票。

    同时剔除区间内成交量全为 0（长期停牌）的股票。
    """
    start = ref_date - pd.Timedelta(days=int(lookback_days * 1.8) + 10)
    df = hub.bars(codes, start, ref_date)
    if df.empty:
        return list(codes)
    df["date"] = pd.to_datetime(df["date"])
    recent = df[df["date"] >= pd.Timestamp(ref_date) - pd.Timedelta(days=lookback_days * 2)]
    stats = recent.groupby("symbol").agg(
        avg_amount=("amount", "mean"),
        zero_volume_days=("volume", lambda s: int((s == 0).sum())),
        total_days=("volume", "count"),
    )
    stats = stats[stats["total_days"] > 0]
    # 长期停牌：超过一半交易日无成交
    stats = stats[stats["zero_volume_days"] <= stats["total_days"] * cfg.suspension_days_limit / lookback_days]
    stats = stats.sort_values("avg_amount", ascending=False)
    keep_n = max(1, int(len(stats) * (1.0 - cfg.liquidity_drop_pct)))
    return stats.index[:keep_n].tolist()


def build_universe_codes(hub: DataHub, cfg: UniverseConfig, ref_date: date) -> list[str]:
    """完整股票池：静态过滤 + 动态过滤。"""
    static = static_universe(hub, cfg, ref_date)
    return liquidity_filter(hub, static["symbol"].tolist(), cfg, ref_date)
