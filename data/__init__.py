"""data：GM Data Manager 数据落盘与同步服务。

- 存储：meta 三分区（bar/mv_basic/valuation）按年 parquet + coverage 覆盖账本；
- 同步：align_meta 按交易日推进（gm 掘金数据源），rebuild 重建覆盖清单；
- 完整性：coverage ∪ no_data ⊇ 当日有效股票集合，异常记账阈值审计自愈。
"""
