# 引擎设计（Engine Design）

版本 v0.1 · 2026-08-04 · 平台层活文档 · 配套 PROJECT_PLAN.md

> 本文档是项目最重要的工程文档：记录引擎平台的模块边界、接口契约、版本策略与项目管理流程。
> 策略层细节见 STRATEGY_BLUEPRINT.md；总体规划见 PROJECT_PLAN.md。

## 1. 设计目标与非目标

目标：
1. 可复用——数据、回测、组合构建、风控、绩效作为通用资产，供未来多个策略共享。
2. 可迭代——接口版本化，新版本不破坏旧策略；策略研究可反向驱动引擎演进。
3. 可验证——每个模块可单测；引擎与掘金回测交叉验证；参数变更自动重跑验证套件。
4. 可配置——所有数字进 config；机制（组件选型）也配置化，代码不写死。

非目标：
- 高频/分钟级撮合（日频足够）；
- 通用金融平台（不贪多，只服务本项目策略需求）；
- v0.x 阶段就冻结接口（允许演进，v1.0 才承诺向后兼容）。

## 2. 设计原则

1. 依赖单向：core ←（data/backtest/portfolio/risk）←（factors/model/execution）；平台不感知具体策略。
2. 接口即契约：核心对象用 Protocol 定义，实现可替换（本地缓存 vs 掘金数据源、自研撮合 vs 掘金回测）。
3. 数据与逻辑分离：策略与引擎只通过 DataHub 取数，不直接碰数据源与缓存实现。
4. 策略即插件：新策略 = 新的 Strategy 实现 + 配置注册，不改引擎。
5. 确定性：同一输入 → 同一输出（固定随机种子、数据快照），保证可回归。
6. 最小抽象：接口只在出现真实用例时抽象；v0.x 允许朴素实现先行。

## 3. 模块地图与职责

| 模块 | 职责 | 关键接口/对象 | 不做什么 |
|---|---|---|---|
| core/ | 领域模型与接口契约 | Bar、Order、Position、Portfolio、Event、Strategy、RiskManager、CostModel、DataSource、ExecutionAdapter（Protocol） | 不实现业务逻辑 |
| data/ | DataHub、缓存、字段规范、复权、停牌/涨跌停/除权除息事件 | DataHub、Cache、Universe | 不做策略判断 |
| backtest/ | 事件驱动回测引擎：撮合、T+1、成本、约束执行、绩效 | Engine、Simulator、Performance | 不内置具体策略 |
| portfolio/ | 组合构建框架 | TargetPortfolio、PortfolioBuilder（Top-N 是第一个实现）、约束、整手近似 | 不依赖具体预测模型 |
| factors/ | 特征计算、单特征检验（策略层工具） | FactorLibrary、ICAnalyzer | 不进入引擎核心 |
| model/ | 预测模型框架、滚动训练（策略层工具） | ModelHub、RankIC | 不进入引擎核心 |
| risk/ | 风控框架：硬风控、统计预警、风险乘数、熔断 | RiskManager、AlertEngine、RiskMultiplier | 与具体策略解耦，可插拔 |
| execution/ | 掘金适配器 | ExecutionAdapter(gm) | 只做读信号、风控、下单 |
| research/ | notebook 研究 | — | — |
| config/ | 所有数字与机制选择的唯一住所 | YAML / dataclass | 代码不写死数字 |
| tests/ | 单元测试、回归测试、A/B 对照 | — | — |

## 4. 核心接口契约（草案 v0.1）

以下为草案，允许在 v0.x 内调整；v1.0 冻结。

```python
from typing import Protocol, Sequence

class Strategy(Protocol):
    """策略只负责产出目标持仓/信号，不碰撮合与成本。
    引擎在 T 日收盘后调用，T+1 执行。"""
    def generate(self, ctx: StrategyContext) -> TargetPortfolio: ...

class DataSource(Protocol):
    """统一取数入口；实现可以是本地 parquet 缓存或掘金接口。"""
    def bars(self, symbols: Sequence[str], start, end) -> DataFrame: ...
    def events(self, kind: str, start, end) -> DataFrame: ...   # 停牌/涨跌停/除权除息
    def universe(self, date) -> Sequence[str]: ...

class CostModel(Protocol):
    """成本是一等公民：佣金(免5)/印花税/过户费/滑点。"""
    def estimate(self, order: Order, price: float) -> Cost: ...

class RiskManager(Protocol):
    """硬风控 + 风险乘数 + 统计预警的入口；与策略解耦。"""
    def check(self, proposed: TargetPortfolio, state: PortfolioState) -> RiskDecision: ...

class ExecutionAdapter(Protocol):
    """执行层适配器；掘金是第一个实现，未来可替换。"""
    def submit(self, orders: Sequence[Order]) -> ExecutionReport: ...
```

演进规则：
- v0.x：接口可按需调整，调整时在变更记录中说明；
- v1.0：冻结，之后只做兼容新增（新字段给默认值）；
- 每个接口保持单一职责，避免出现万能对象。

## 5. 回测引擎事件流与钩子点

```text
T 日 16:30  引擎触发 → DataHub 提供数据切片 → Strategy.generate → TargetPortfolio
            → RiskManager.check（硬风控/风险乘数）
T+1 09:15  订单生成（整手、限价）→ Simulator 撮合（涨跌停不可成交、停牌跳过、T+1 校验）
            → CostModel 计费 → 持仓更新
全天/收盘  绩效记录（收益/回撤/换手/IC）→ 预警统计量 → 日志/看板
```

钩子点（供未来扩展）：before_strategy / after_signals / before_orders / after_fill / on_alert。
默认钩子为空实现，策略与风控按配置注册。

## 6. 版本管理策略

- 平台版本（语义化）：v0.1.x 内部接口可变 → v1.0.0 首个冻结发布 → v1.x 兼容新增。
- 策略版本独立：v1.0 = smart beta Top-N（见 STRATEGY_BLUEPRINT.md），策略升级不影响引擎版本。
- 变更记录：每次引擎版本变化在本文档第 10 节与 develop.md 各记一条。
- 决策规则：v1.0 之后的接口变更必须经过弃用期并附迁移说明。

## 7. 测试与验证

- 单元测试：每个模块独立测试（撮合细节、成本计算、整手取整、约束边界是重点）。
- 回归测试：任何参数/代码变更 → 自动重跑验证套件（回归 + 关键回测）。
- 交叉验证：同一策略在自研引擎与掘金回测 A/B，偏差须可解释。
- 数据校验：复权、涨跌停、除权除息抽样人工核对（Phase 0 验收项）。

## 8. 项目管理流程

- todo.md 只保留最新待办（当前迭代）；不堆历史。
- 迭代节奏：每阶段完成 → 总结进 develop.md → PROJECT_PLAN.md 开发日志同步 → 开启下一轮 todo。
- 策略研究驱动的引擎迭代：研究中发现引擎缺口 → 记入引擎 backlog → 小版本迭代吸收（不阻塞策略主线）。
- 参数变更纪律：改参数 → 自动重跑验证套件 → 记录。
- 文档纪律：迭代完成即更新本文档与相关蓝图，不允许文档滞后。

## 9. 已知风险与对策

| 风险 | 对策 |
|---|---|
| 过度抽象（为不存在的策略设计接口） | 最小抽象原则：接口只在真实用例出现时抽象；v0.x 朴素实现先行 |
| 接口频繁变动拖慢开发 | 版本化 + 变更记录 + 迁移说明；v1.0 冻结 |
| 测试缺失导致回归 | 模块合入必须有单测；验证套件自动跑 |
| 引擎与掘金偏差无法解释 | 交叉验证制度化，偏差报告是 Phase 1 验收项 |
| 文档滞后 | 迭代完成即更新，写入流程规则 |

## 10. 引擎版本记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| v0.1 | 2026-08-04 | 文档确立：模块地图与接口契约草案 | 设计稿 |
