# 待办（当前迭代：GM Data Manager v1.0 · 转型完成）

## 已完成（v1.0 实现）

- [x] 转型决策：项目改为 gm data manager，只保留数据库落盘与同步服务
- [x] 删除策略研发：backtest / execution / factors / model / portfolio / risk、STRATEGY_BLUEPRINT.md、config/（策略五 YAML + loader）、core 策略契约与模型、旧取数工具（cache/hub/universe/verify）、策略测试
- [x] 保留并梳理数据服务：data/（asset / gm_source / store / meta_store / incremental / meta_fetch / rebuild / migrate）+ webui/ + core 最小数据契约
- [x] 元数据与文档重写：pyproject 更名 gm-data-manager v1.0.0、WebUI 标题/调度路径、OUTLINE / PROJECT_PLAN / ENGINE_DESIGN / develop / todo
- [x] 测试与入库核对：pytest 22 项通过；data/cache 与 .env 确认不入库（数据仓不推送）

## 待办

- [ ] 用户场景验证：启动 WebUI → 点「重建覆盖清单」→ 手动触发「截面数据任务」→ 确认三分区逐日收敛、二次运行零重复
- [ ] 数据完整性质检：2016→今三分区行键对齐抽查 + no_data 审计无存疑天数（rebuild --compare --dry-run）
- [ ] 自动调度实跑一轮并核对 task.log（工作日定时截面增量）
- [ ] 后续增强：指数 / ETF 资产类别接入（asset.py 已预留 AssetClass 枚举）
- [ ] 后续增强：只读查询 / 数据导出 API（MetaStore 对外暴露）
- [ ] 完成情况总结移入 develop.md

规则：todo.md 只保留最新待办；完成一个版本迭代后，将完成情况总结移入 develop.md。数据服务缺口 backlog 追加到"待办"区，按小版本迭代吸收。
