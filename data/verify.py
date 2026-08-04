"""数据抽样核对脚本：输出除权除息/涨跌停/停牌/复权对照表供人工核验。

用法：
    python -m data.verify [--symbols SHSE.600000,SZSE.000001] [--years 3]
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

from config import load_config
from data.cache import ParquetCache
from data.gm_source import GmDataSource
from data.hub import DataHub
from data.universe import is_mainboard, is_st


def _limit_ratio(prev_close: float, close: float) -> bool:
    """主板涨跌停判定：相对前收 ±10%（四舍五入到 0.01）。"""
    if prev_close <= 0:
        return False
    pct = (close - prev_close) / prev_close
    return pct >= 0.095 and pct <= 0.105  # 容忍舍入


def report(hub: DataHub, symbols: list[str], years: int, end: date) -> None:
    start = end - timedelta(days=int(years * 365))
    print(f"=== 抽样核对（{start} ~ {end}） ===")
    for sym in symbols:
        bars = hub.cache.read_bars(sym, start, end)
        print(f"\n--- {sym} ---")
        if bars.empty:
            print("  无缓存数据（先运行 python -m data.fetch）")
            continue
        bars = bars.sort_values("date")
        divs = hub.events("dividend", [sym], start, end)
        if not divs.empty:
            print("  [除权除息]")
            for _, row in divs.iterrows():
                print(
                    f"    {row['date']} 每股派息 {row['cash_div']} 送转 {row['share_div_ratio']} "
                    f"转增 {row['share_trans_ratio']}"
                )
        else:
            print("  [除权除息] 区间内无记录")
        susp = bars[bars["volume"] == 0]
        print(f"  [停牌] 无成交交易日 {len(susp)} 天" + (f"，最近：{susp['date'].iloc[-1]}" if len(susp) else ""))
        lu = []
        prev = None
        for _, row in bars.iterrows():
            if prev is not None and _limit_ratio(prev, row["close"]):
                lu.append((row["date"], prev, row["close"]))
            prev = row["close"]
        print(f"  [涨跌停] 触及 ±10% 的交易日 {len(lu)} 天" + (f"，最近：{lu[-3:]}" if lu else ""))
        last = bars.tail(5)
        print("  [最近5日行情]")
        for _, row in last.iterrows():
            print(f"    {row['date']} 开{row['open']:.2f} 收{row['close']:.2f} 前收{row['pre_close']:.2f} 额{row['amount']/1e8:.2f}亿")


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="抽样核对缓存数据")
    ap.add_argument("--symbols", default=None, help="逗号分隔；缺省随机抽 5 只主板非 ST")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（默认今天）")
    args = ap.parse_args()
    load_dotenv()
    cfg = load_config()
    hub = DataHub(GmDataSource(), ParquetCache())
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        ins = hub.source.instruments()
        pool = ins[ins["symbol"].map(is_mainboard) & ~ins["sec_name"].map(is_st)]["symbol"].tolist()
        symbols = random.sample(pool, min(5, len(pool)))
    end = date.fromisoformat(args.end) if args.end else date.today()
    report(hub, symbols, args.years, end)


if __name__ == "__main__":
    main()
