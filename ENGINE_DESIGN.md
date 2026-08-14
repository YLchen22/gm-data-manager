# 数据服务设计（GM Data Manager Design）

版本 v1.0 · 2026-08-14 · 数据服务活文档 · 配套 PROJECT_PLAN.md

> 本文档描述数据落盘与同步服务的模块边界、存储布局、接口契约与验证流程。
> 总体计划见 PROJECT_PLAN.md；开发日志见 develop.md。

## 1. 目标与非目标

目标：
1. 可落盘——行情与行情元数据（bar / mv_basic / valuation）统一行键、按年分区、原子写入。
2. 可同步——按交易日推进的截面增量，先扫描本地、只补缺失，支持全量/增量与定时调度。
3. 可验证——coverage 覆盖账本可全量重建；no_data 账本分类准入 + 复核自愈；异常记账阈值审计。
4. 可服务——WebUI 一键触发任务、动态进度、任务日志、工作日自动调度；CLI 可脚本化。

非目标：
- 策略研发（回测 / 因子 / 模型 / 组合 / 风控 / 执行）——v1.0 起全部移除；
- 交易与执行相关能力；
- 分钟级/高频数据（当前日频）；
- 跨数据源抽象（当前只对接掘金 gm SDK）。

## 2. 设计原则

1. 依赖单向：core ← data ← webui；数据服务不感知任何策略概念。
2. 数据与逻辑分离：同步任务只经 MetaStore/Store 落盘，不直接写文件；数据源只经 GmDataSource 访问。
3. 幂等补缺：任务先扫描本地覆盖，只补缺失；二次运行零重复抓取。
4. 完整性可审计：某天完整 ⟺ coverage(d) ∪ no_data(d) ⊇ 当日有效股票集合。
5. 原子写入：parquet 一律"临时文件 + os.replace"，避免并发进程读到半截文件。
6. 绝不静默漏抓：异常记账超阈值判定当天清单存疑，清除记账后重新进入抓取验证。

## 3. 模块地图与职责

| 模块 | 职责 | 关键对象/入口 |
|---|---|---|
| core/ | 数据领域模型与数据源契约 | Bar、Event、DataSource（Protocol） |
| data/asset.py | 资产类别与全 A 股票静态表、上市/退市有效性 | AssetClass、load_assets、valid_symbols_on |
| data/gm_source.py | 掘金数据源：行情 / 股票列表 / 交易日历 / 三分区截面 | GmDataSource |
| data/store.py | 行情与 coverage 年度分区仓库（旧 bars 布局，兼容） | Store |
| data/meta_store.py | meta 三分区仓库 + 分区覆盖账本 | MetaStore、META_COLUMNS |
| data/incremental.py | no_data/suspect 账本、分类复核、审计、旧截面增量 | align、audit_no_data |
| data/meta_fetch.py | 三分区统一截面同步任务（按日推进） | align_meta、scan_missing_meta |
| data/rebuild.py | 从 meta 分区重建覆盖清单 + 审计 | rebuild_meta_coverage |
| data/migrate.py | 旧 symbol 文件缓存 → 年度分区布局迁移 | migrate |
| webui/ | Streamlit 数据管理界面 + APScheduler 自动调度 | app.py、tasks.py |
| tests/ | 单元测试（mock 数据源、无网络） | — |

## 4. 数据布局与完整性

```text
data/cache/
├── meta/{bar,mv_basic,valuation}/{year}.parquet   # 数据本体（行键 date+symbol）
├── meta_coverage/{bar,mv_basic,valuation}/{year}.parquet  # 分区覆盖账本
└── status/
    ├── no_data.parquet     # 确认无数据账本（date, symbol, reason, last_seen）
    ├── suspect.parquet     # 待复核（连续 3 次后入账 no_data）
    ├── task_status.json    # WebUI 任务状态（运行态）
    ├── task.log            # 任务日志（运行态）
    └── scheduler.json      # 自动调度配置（运行态）
```

- 三分区行键严格一致：bar = OHLCV/amount/pre_close + upper/lower_limit/adj_factor/turn_rate/is_suspended/is_st；
  mv_basic = tot_mv/a_mv + turnrate/ttl_shr/circ_shr；valuation = PE/PB/PS/PCF/股息率。
- 停牌日保留行（行情列留空、is_suspended=1），保证三分区对齐。
- no_data 分类：suspended（停牌）/ boundary（上市/退市日、代码变更）/ code_change / anomaly（有行情未返回）/ unknown（接口失败）；
  anomaly/unknown 30 天复核，其余 365 天复核，到期重新验证（自愈）。

## 5. 同步任务流程

```text
触发（WebUI 按钮 / 定时调度 / CLI）
  → _plan_meta：静态表 + 交易日 + 三分区覆盖 + no_data 阻塞（先扫本地）
  → scan_missing_meta：找出 (交易日, 缺失分区)
  → 按日推进：get_symbols 定基准行键 → 三分区接口拉取 → 对齐基准行键落盘
      → 未返回/代码变更记 boundary（365 天复核）
  → 完成统计（checked_days / filled_rows / no_data / stopped）
```

CLI 入口：
- `python -m data.meta_fetch [--start YYYY-MM-DD] [--end ...] [--max-days N]`
- `python -m data.rebuild [--dry-run] [--compare] [--no-audit]`
- `python -m data.migrate [--dry-run]`
- `python -m data.incremental`（旧 bars 截面增量，兼容保留）

## 6. 接口契约

```python
@runtime_checkable
class DataSource(Protocol):
    """统一取数入口；实现可以是本地 parquet 仓库或掘金接口。"""
    def bars(self, symbols, start, end) -> pd.DataFrame: ...
    def events(self, kind, symbols, start, end) -> pd.DataFrame: ...
    def universe(self, d) -> Sequence[str]: ...
```

- 领域模型：Bar（日线最小集）、Event（停牌/涨跌停/除权除息）。
- 仓库接口：MetaStore.write_meta / read_meta / write_coverage / coverage_by_date / stats。
- 任务接口：align_meta / scan_missing_meta / scan_missing_meta_summary（支持 progress_cb / stop_event）。

演进规则：v1.x 内接口变更须在本文档第 10 节与 develop.md 记录；对外行为（行键/列名/账本语义）变更需迁移说明。

## 7. 测试与验证

- 单元测试：账本（no_data/suspect/审计）、meta_store 读写/去重/分区校验、rebuild 重建/漂移/清理——全部 mock、无网络。
- 冒烟测试：数据服务全部包与核心模块可导入。
- 真实 API 冒烟（用户场景）：三分区行键严格对齐、停牌日留空行、二次运行零重复。
- 完整性审计：rebuild --compare 校验数据文件与 coverage 漂移；audit_no_data 按日阈值审计异常记账。

## 8. 版本管理策略

- 数据服务版本（语义化）：v1.0 起稳定；功能迭代 v1.x，破坏性变更须迁移说明。
- 变更记录：每次版本变化在本文档第 10 节与 develop.md 各记一条。
- 迭代纪律：todo.md 只保留当前迭代；完成 → 总结进 develop.md → PROJECT_PLAN.md 同步。

## 9. 已知风险与对策

| 风险 | 对策 |
|---|---|
| 数据源静默缺行/瞬时故障被误判为无数据 | suspect 3 次重试 + anomaly 阈值审计 + 30 天复核自愈 |
| 当日未结算被误记 no_data | _completed_days 18:00 前剔除当天；结算后仍拉不到也不记账，留待次日重试 |
| 并发读写 parquet 损坏 | 临时文件 + os.replace 原子替换；幂等补缺兜底 |
| 删数据留 coverage 造成误判完整 | coverage 定义为数据纯投影，rebuild 全量重建并清理残留 |
| 数据仓（parquet 缓存）误入版本控制 | .gitignore 排除 data/cache/、*.parquet；推送前核对文件清单 |

## 10. 变更记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| v1.0 | 2026-08-14 | 从量化引擎转型为 GM Data Manager：移除策略研发，保留数据落盘与同步；文档重写 | 已发布 |
