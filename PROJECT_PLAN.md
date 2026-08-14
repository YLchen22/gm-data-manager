# GM Data Manager 项目计划书

版本 v1.0 · 2026-08-14 · 状态：从 CYQUANT 量化引擎转型为纯数据服务（数据落盘 + 同步），策略研发环节已移除

> 阅读指引：总体规划与开发日志见本文件；数据服务设计见 ENGINE_DESIGN.md；协作规则见 AGENTS.md。

## 1. 项目定位

- GM Data Manager：基于掘金量化数据接口（gm SDK）的 A 股行情数据落盘与同步服务。
- 职责边界：
  - 落盘：meta 三分区（bar / mv_basic / valuation）按年 parquet 仓库 + coverage / no_data 完整性账本；
  - 同步：按交易日推进的截面增量（align_meta）、覆盖清单重建（rebuild）、异常记账阈值审计自愈；
  - 服务：WebUI（Streamlit + APScheduler）一键任务、动态进度、工作日自动调度；CLI 可脚本化。
- 非目标：不做策略研发（回测 / 因子 / 模型 / 组合 / 风控 / 执行均已移除）；不做交易执行。
- 数据范围：沪深全 A 股（主板 / 创业板 / 科创板，含全部历史退市股，约 5542 只），2016-01-01 至今，日频。

## 2. 数据仓库

```text
data/cache/
├── meta/{bar,mv_basic,valuation}/{year}.parquet
├── meta_coverage/{bar,mv_basic,valuation}/{year}.parquet
└── status/（no_data / suspect / task_status / task.log / scheduler.json）
```

- 行键统一 (date, symbol)，含停牌日（行情列留空、is_suspended=1），三分区严格对齐。
- coverage = 数据文件的纯投影，可全量重建（rebuild）；完整性 = coverage ∪ no_data ⊇ 当日有效集合。
- 数据仓（data/cache）为本地运行态，已被 .gitignore 排除，不进入版本控制与 GitHub。

## 3. 同步服务

- 截面数据任务（全量/增量）：先扫描本地覆盖 → 只补缺失交易日分区 → 逐日推进落盘。
- 重建覆盖清单：从 meta 分区重建 coverage，清理无数据年份的残留清单，内置异常记账审计。
- 完整性自愈：anomaly/unknown 30 天、suspended/boundary/code_change 365 天复核；审计超阈值自动清除重抓。
- 调度：工作日定时自动截面增量（APScheduler，配置存于 data/cache/status/scheduler.json）。

## 4. 入口

| 入口 | 说明 |
|---|---|
| `启动WebUI.bat` | 启动 WebUI（http://localhost:8501） |
| `python -m data.meta_fetch [--start] [--end] [--max-days]` | 截面数据任务 CLI |
| `python -m data.rebuild [--dry-run] [--compare] [--no-audit]` | 重建覆盖清单 CLI |
| `python -m data.migrate [--dry-run]` | 旧缓存布局迁移 |
| `pytest` | 单元测试（mock、无网络） |

## 5. 版本策略

- 数据服务语义化版本：v1.0 稳定基线；功能迭代 v1.x；破坏性变更附迁移说明。
- 迭代纪律：todo.md 只保留当前迭代；完成 → 总结进 develop.md → PROJECT_PLAN.md 同步。

## 6. 路线图与验收

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| v1.0 基线（已完成） | 转型为数据服务；移除策略研发；文档/元数据重写 | pytest 22 项通过；data/cache 与 .env 不入库 |
| v1.1 场景验证 | WebUI 全流程：重建覆盖 → 截面任务 → 二次运行零重复 | 三分区逐日收敛、无存疑天数 |
| v1.2 数据服务增强 | 指数/ETF 资产类别、只读查询/导出 API、调度监控 | 资产类别独立维护；查询接口可用 |

## 7. 目录结构

```text
gm-data-manager/
├── PROJECT_PLAN.md / ENGINE_DESIGN.md / OUTLINE.md
├── develop.md / todo.md / AGENTS.md / 启动WebUI.bat
├── core/            # 数据源契约与领域模型（DataSource / Bar / Event）
├── data/            # 数据落盘与同步（asset / gm_source / store / meta_store /
│                    #   incremental / meta_fetch / rebuild / migrate）
├── webui/           # Streamlit 数据管理界面 + APScheduler 调度
├── tests/           # 单元测试（mock、无网络）
└── data/cache/      # 本地数据仓（git 忽略，不推送）
```

## 8. 开发日志（最新在前）

### v1.0（2026-08-14）转型 GM Data Manager
- 用户拍板：项目改为 gm data manager，只保留数据库落盘与同步服务，去掉策略研发环节。
- 删除策略研发：backtest/ execution/ factors/ model/ portfolio/ risk/、STRATEGY_BLUEPRINT.md、
  config/（成本/股票池/风控/预警/组合五 YAML + loader）、core 策略契约与模型、
  旧取数工具（data/cache.py / hub.py / universe.py / verify.py）、策略测试（test_contracts.py）。
- 保留数据服务：data/（asset / gm_source / store / meta_store / incremental / meta_fetch / rebuild / migrate）、
  webui/、core 最小数据契约（DataSource / Bar / Event）。
- 元数据：pyproject 更名 gm-data-manager v1.0.0（依赖精简 + webui 可选依赖）；WebUI 更名为 GM Data Manager；
  调度配置路径移至 data/cache/status/scheduler.json；文档全部重写。
- 验证：pytest 22 项通过；git 复核数据仓（data/cache）与 .env 均未纳入版本控制。

### v0.9.4（2026-08-06）数据服务：meta 三分区框架
- 方案确认：meta 框架下三分区（bar/mv_basic/valuation）单任务按日推进，行键统一 (date, symbol)，含停牌日。
- 清理逐股时序（sweep/fetch/align_by_stock）；WebUI 仅"截面数据任务"+"重建覆盖清单"；实测三分区严格对齐、二次运行零重复。

### v0.9（2026-08-05）数据服务增强：coverage 重建 + 空补记账
- coverage 改为"bars 纯投影、可全量重建"；no_data 独立账本 + 分类准入 + 30/365 天复核自愈；
  18:00 当日保护修复 + 异常记账阈值保险检查。

### v0.8（2026-08-04）全历史股票池修正
- get_symbols 全量 5542 只含全部历史退市股；股票池接口 get_instruments → get_symbols；静态策略池补未退市过滤。

### v0.7（2026-08-04）存储重构 + WebUI
- 存储升级为「资产类别/年份」分区 + 覆盖清单；WebUI（Streamlit + APScheduler）上线。

### Phase 0（2026-08-04）工程与数据基座
- Python 3.10 venv、工程骨架、掘金 SDK 接入（gm 单次 16MB 上限分批解决）、股票池与日线缓存、抽样核对通过。
