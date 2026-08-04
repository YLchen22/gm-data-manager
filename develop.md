# 开发日志

## Phase 0 工程与数据基座完成（2026-08-04）
- 环境：选定 Python 3.10.6（64 位）venv（3.14 过新、gm 支持区间 3.6+）；依赖 numpy/pandas 1.5.3/pyarrow/pyyaml/pytest/gm 3.0.186；pytest 5 用例通过。
- 工程骨架：git init（main 分支）；11 目录 + pyproject.toml + .gitignore（.venv/.env/data/cache/.idea 不入库）。
- core 契约：领域模型（Bar/Order/Position/TargetPortfolio/Cost/RiskDecision/StrategyContext 等）+ 5 个接口 Protocol（Strategy/DataSource/CostModel/RiskManager/ExecutionAdapter）+ dummy 策略验证接缝。
- config：costs/universe/risk/alerts/portfolio 五个 YAML + loader 基础校验（比例/正数）；滑点 0.05% 占位待回测标定；免5 佣金待券商确认。
- 掘金接入：token 验证通过；关键工程坑——gm 单次查询 16MB 上限 → fetch 按 50 只/批 × 1 年分段；DataHub.ensure_bars 单批 ≤50 只。
- 股票池：静态过滤（沪深主板/非 ST/上市满 60 交易日/未停牌）2990 只 → 流动性过滤后 2737 只（2026-08-04 口径）。
- 数据：2737 只 × 2018-01-01~2026-08-04 日线 525 万行缓存 parquet（3048 文件含历史测试样本）；抽查 0 空值；除权除息/涨跌停/行情抽样核对通过。
- 工程细节：Windows 管道下 stdout 块缓冲导致 -m 短输出丢失 → 脚本 line_buffering 修复。

## v0.5 主线调整：引擎平台优先（2026-08-04）
- 项目定位升级为双主线：平台层（可复用、可迭代的引擎）+ 策略层（第一个应用 smart beta Top-N）；平台优先，策略研究后置/并行。
- 新增 ENGINE_DESIGN.md：模块地图、接口契约草案（Strategy/DataSource/CostModel/RiskManager/ExecutionAdapter）、版本管理（语义化 + 策略版本独立）、测试验证、项目管理流程。
- 路线图重排：因子实验室与预测模型后移至 Phase 3；引擎核心（回测/组合/风控）提前至 Phase 1–2；Phase 0 增加 core 接口契约草案。
- 文档修正：develop.md 日志统一为最新在前；OUTLINE.md 补齐为项目总纲；PROJECT_PLAN.md 版本号同步至 v0.5；STRATEGY_BLUEPRINT.md 标注为第一个策略的蓝图。

## v0.4 组合构建设计：风险预算化 Top-N（2026-08-03）
- 矛盾：固定行业权重上限错过主线机会，无约束则行业集中放大风险。
- 方案：行业"风险贡献上限"替代"仓位上限"（RC_i = w_i × (Σw)_i / σ_p²），并升级为信号强度条件化的状态依赖风险预算（"超额收益够高就允许赌主线"）；保留硬性风险地板（单行业风险贡献 ≤40–50%）。
- 实现：固定上限基准版 → 风险贡献版（收缩/因子协方差 + 迭代权重调整）→ 信号条件化版；整手取整后重算校验。
- 纪律：扩张规则用实现信号质量（预测 spread 与实现 IC 偏差、hit rate）校准，防止模型过度自信时放大错误集中；术语参考 risk budgeting / Black-Litterman。

## v0.3 收益来源定位与参数管理原则（2026-08-03）
- 收益来源定位：横截面收益率预测（smart beta），long-only 满仓、不对冲、不中性化；整数/整手约束使权重优化失效，采用"预测 → 排序 → Top-N + 约束"范式。
- 预测目标变量：未来 h 日横截面相对收益（z-score），模型直接优化 rank IC；绩效报告含 Grinold 式分解。
- 参数管理：全部参数进 config，结构参数现在定、标定参数（集中度、回撤硬线、熔断阈值、预警控制限等）开发阶段定；改参数自动重跑验证套件。

## v0.2 目标与风控架构修订（2026-08-03）
- 目标体系分层：底线（跑赢基准、回撤 ≤30%）/ 目标（年化 25–40%）/ 雄心（40%+）；"追年化不追夏普"落地为回撤预算内最大化复合收益。
- 风控三层架构：硬性自动风控 / 统计预警（IC 衰退、CUSUM、波动率突变、VaR/CVaR、regime）/ 人工介入协议。
- 回测验收标准上修：扣费后样本外年化 60%+（按 5–8 折实现率对应实盘 40% 目标）。

## v0.1 立项（2026-08-03）
- 定位：10 万、A 股主板、日频、全自动（掘金量化执行），用户专注数据科学。
- 回测方案决策：自研轻量事件驱动引擎为主，掘金回测交叉验证，qlib 暂不引入。
- 关键风险：小资金摩擦成本（佣金最低 5 元、印花税、滑点）、主板权限限制、掘金回测扩展性。
