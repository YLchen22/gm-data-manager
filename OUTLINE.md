# GM Data Manager 项目总纲

- 定位：基于掘金量化数据接口（gm SDK）的 A 股行情数据落盘与同步服务；只做数据，不做策略研发。
- 落盘：meta 三分区（bar / mv_basic / valuation）按年 parquet 仓库 + coverage / no_data 完整性账本。
- 同步：按交易日推进的截面增量任务（align_meta）、覆盖清单重建（rebuild）、异常记账阈值审计自愈。
- 服务：WebUI（Streamlit + APScheduler）一键触发任务、动态进度、工作日定时自动同步。

## 文档地图

| 文档 | 角色 | 更新时机 |
|---|---|---|
| PROJECT_PLAN.md | 总体规划：定位、架构、路线图、开发日志 | 每次版本迭代 |
| ENGINE_DESIGN.md | 数据服务设计：存储布局、接口契约、同步流程、验证 | 任何设计/接口变更 |
| develop.md | 开发日志（最新在前） | 每次迭代完成 |
| todo.md | 最新待办（只保留当前迭代） | 迭代开始/进行中 |
| AGENTS.md | 项目协作规则 | 规则变更 |
