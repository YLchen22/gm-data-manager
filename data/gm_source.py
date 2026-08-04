"""掘金数据源：实现 DataSource 协议（ENGINE_DESIGN.md 第 4 节）。

只负责请求 gm API 并规范化为统一字段；缓存与增量由 DataHub 负责。
"""

from __future__ import annotations

import os
from datetime import date
from typing import Sequence

import pandas as pd
from gm.api import (
    get_dividend,
    get_symbols,
    get_trading_dates,
    history as gm_history,
    set_token,
)

from core.contracts import DataSource

_BAR_FIELDS = "symbol,open,high,low,close,volume,amount,pre_close,bob"
_BAR_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount", "pre_close"]


def _to_date_series(s: pd.Series) -> pd.Series:
    """bob 格式 'YYYY-MM-DD HH:MM:SS+08:00' -> date 对象。"""
    return pd.to_datetime(s.astype(str).str[:10], format="%Y-%m-%d")


class GmDataSource(DataSource):
    """掘金数据源（日线 / 除权除息 / 股票列表 / 交易日历）。"""

    def __init__(self, token: str | None = None):
        token = token or os.environ.get("GM_TOKEN", "")
        if not token:
            raise ValueError("缺少掘金 token：设置环境变量 GM_TOKEN（项目根 .env 会被 fetch 脚本加载）")
        set_token(token)

    # ---- DataSource.bars ----
    def bars(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame(columns=_BAR_COLUMNS)
        df = gm_history(
            symbol=",".join(symbols),
            frequency="1d",
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            fields=_BAR_FIELDS,
            df=True,
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=_BAR_COLUMNS)
        df = df.rename(columns={"bob": "date"})
        df["date"] = _to_date_series(df["date"])
        return df[_BAR_COLUMNS]

    # ---- DataSource.events ----
    def events(self, kind: str, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        if kind == "dividend":
            frames = [get_dividend(symbol=s, start_date=start.isoformat(), end_date=end.isoformat(), df=True) for s in symbols]
            frames = [f for f in frames if f is not None and not f.empty]
            if not frames:
                return pd.DataFrame()
            out = pd.concat(frames, ignore_index=True)
            out = out.rename(columns={"created_at": "date"})
            out["date"] = _to_date_series(out["date"])
            return out
        raise NotImplementedError(f"暂不支持的事件类型: {kind}")

    # ---- DataSource.universe ----
    def universe(self, d: date) -> Sequence[str]:
        return self.instruments()["symbol"].tolist()

    # ---- 辅助 ----
    def instruments(self) -> pd.DataFrame:
        """沪深全部 A 股静态信息（含全部历史退市股，供股票池过滤）。

        用 get_symbols 而非 get_instruments：后者只返回存续股 + 少量保留退市股，
        会漏掉乐视(300104)等 2019–2024 退市潮股票；get_symbols 全量 5542 只
        （含 2002 年退市的 PT金田A 等老案例），delisted_date=2038-01-01 表示存续。
        """
        df = get_symbols(
            sec_type1=1010,
            sec_type2=101001,
            skip_suspended=False,
            skip_st=False,
            df=True,
        )
        for col in ("listed_date", "delisted_date"):
            if col in df.columns:
                df[col] = _to_date_series(df[col])
        return df

    def trading_dates(self, start: date, end: date) -> list[str]:
        return get_trading_dates(exchange="SHSE", start_date=start.isoformat(), end_date=end.isoformat())
