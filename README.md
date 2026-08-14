# GM Data Manager

基于掘金量化数据接口（gm SDK）的 A 股行情数据落盘与同步服务：只做数据，不做策略研发。

- 落盘：meta 三分区（bar / mv_basic / valuation）按年 parquet 仓库 + coverage / no_data 完整性账本
- 同步：按交易日推进的截面增量任务，先扫描本地、只补缺失；覆盖清单可一键重建
- 服务：WebUI（Streamlit + APScheduler）任务触发 / 动态进度 / 工作日自动调度；CLI 可脚本化
- 数据范围：沪深全 A 股（主板 / 创业板 / 科创板，含历史退市股），2016-01-01 至今，日频

## 一、环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11（本项目在 Windows 上开发与验证） |
| Python | 3.10（推荐 3.10.x，掘金 gm SDK 兼容性最稳） |
| git | 用于克隆代码与更新 |
| 掘金量化账号 | 需有效的 GM Token（用于调用行情 / 基本面 / 估值接口） |

## 二、获取代码

```bash
git clone https://github.com/YLchen22/gm-data-manager.git
cd gm-data-manager
```

> 仓库为私有仓库，需要仓库访问权限；也可以直接拷贝项目文件夹到新机器使用（保持目录结构不变即可）。

## 三、创建虚拟环境并安装依赖

在项目根目录打开 PowerShell / CMD：

```bash
# 1. 创建虚拟环境（用 Python 3.10；若 py 启动器找不到 3.10，改用 3.10 完整安装路径）
py -3.10 -m venv .venv

# 2. 安装依赖（核心依赖 + 开发测试 + WebUI）
.venv\Scripts\python.exe -m pip install -e ".[dev,webui]"
```

如需分步安装：

```bash
.venv\Scripts\python.exe -m pip install -e .            # 核心依赖（numpy/pandas/pyarrow/gm 等）
.venv\Scripts\python.exe -m pip install pytest streamlit apscheduler   # 测试 + WebUI
```

> 国内网络安装慢时，可加镜像源，例如 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

## 四、配置掘金 Token

1. 注册 / 登录掘金量化（myquant），在掘金终端或用户中心获取你的 GM Token。
2. 在项目根目录创建 `.env` 文件（参照 `.env.example`）：

```ini
GM_TOKEN=你的掘金token
```

3. 验证 token 能被读到：

```bash
.venv\Scripts\python.exe -c "import os; from dotenv import load_dotenv; load_dotenv(); print('token ok' if os.environ.get('GM_TOKEN') else 'MISSING')"
```

> ⚠️ `.env` 已被 `.gitignore` 排除，绝不提交、不要改名；token 泄露等于数据权限外借。

## 五、验证安装

```bash
.venv\Scripts\python.exe -m pytest -q
```

预期结果：`22 passed`（全部为本地 mock 测试，不需要网络 / token）。

## 六、启动 WebUI

方式一（推荐）：双击根目录 `启动WebUI.bat`，浏览器自动打开 <http://localhost:8501>。

方式二（命令行）：

```bash
.venv\Scripts\python.exe -m streamlit run webui/app.py
```

首次使用流程：

1. 侧边栏点「🗂 重建覆盖清单」——从已有数据文件重建 coverage 账本（新环境为空白清单）；
2. 点「🚀 截面数据任务（全量/增量）」——按交易日补齐三分区，动态进度条与任务日志实时显示；
3. 再次运行同一任务应显示零重复（幂等）；
4. 如需自动同步，在「自动调度」区启用工作日定时任务并保存。

## 七、CLI 用法

```bash
# 截面数据任务（全量：2016-01-01 至今；--max-days 限制单次补几天）
.venv\Scripts\python.exe -m data.meta_fetch [--start 2016-01-01] [--end 2026-12-31] [--max-days 0]

# 重建覆盖清单（--dry-run 只审计不写入；--compare 报告漂移；--no-audit 跳过异常记账审计）
.venv\Scripts\python.exe -m data.rebuild [--dry-run] [--compare] [--no-audit]

# 旧缓存布局迁移（一次性工具）
.venv\Scripts\python.exe -m data.migrate [--dry-run]
```

## 八、数据库交付指南

### 8.1 总体约定

数据仓位于 `data/cache/`（本地运行态，git 忽略、不上传；交付/迁移时直接拷贝该目录）。存储介质为 Parquet（PyArrow），按年分片，全部表的主键为 `(date, symbol)`：

| 约定 | 说明 |
|---|---|
| 主键 | `(date, symbol)`，无重复 |
| date | 交易日，`datetime64[ns]` |
| symbol | 掘金代码格式，如 `SHSE.600000` / `SZSE.000001`；覆盖沪深全 A（含历史退市股） |
| 分片 | 每年一个 parquet 文件：`data/cache/meta/{分区}/{year}.parquet` |
| 停牌日 | 行保留、行情列为空（NaN）、`is_suspended=True`，保证三分区对齐 |
| 完整性 | 某天完整 ⟺ `coverage(d) ∪ no_data(d) ⊇` 当日有效股票集合 |

### 8.2 bar 分区（行情 + 基础元数据）

路径：`data/cache/meta/bar/{year}.parquet`

| 列名 | 类型 | 含义 | 单位 |
|---|---|---|---|
| date | datetime64 | 交易日 | — |
| symbol | str | 股票代码 | — |
| open / high / low / close | float64 | 开 / 高 / 低 / 收价 | 元/股 |
| volume | float64 | 成交量 | 股 |
| amount | float64 | 成交额 | 元 |
| upper_limit / lower_limit | float64 | 涨停价 / 跌停价 | 元/股 |
| adj_factor | float64 | 复权因子 | — |
| turn_rate | float64 | 换手率 | %（如 0.3672 = 0.37%） |
| is_suspended | bool | 是否停牌 | — |
| is_st | bool | 是否 ST / *ST | — |

> 注意：`pre_close`（前收盘）不落盘，抓取时用于计算后丢弃；需要前收时可用前一交易日 `close` 代替，或从掘金接口重取。

### 8.3 mv_basic 分区（市值 + 股本）

路径：`data/cache/meta/mv_basic/{year}.parquet`

| 列名 | 类型 | 含义 | 单位 |
|---|---|---|---|
| date / symbol | — | 交易日 / 代码 | — |
| tot_mv | float64 | 总市值 | 元 |
| a_mv | float64 | A 股流通市值 | 元 |
| ttl_shr | float64 | 总股本 | 股 |
| circ_shr | float64 | 流通股本 | 股 |
| turnrate | float64 | 换手率 | % |

### 8.4 valuation 分区（估值）

路径：`data/cache/meta/valuation/{year}.parquet`

| 列名 | 类型 | 含义 | 单位 |
|---|---|---|---|
| date / symbol | — | 交易日 / 代码 | — |
| pe_ttm | float64 | 市盈率（TTM），亏损为负 | 倍 |
| pe_ttm_cut | float64 | 扣非市盈率（TTM） | 倍 |
| pb_mrq | float64 | 市净率（MRQ） | 倍 |
| ps_ttm | float64 | 市销率（TTM） | 倍 |
| pcf_ttm_oper | float64 | 经营现金流市盈率（TTM） | 倍 |
| dy_ttm | float64 | 股息率（TTM） | %（如 3.15 = 3.15%） |

### 8.5 coverage 覆盖账本

路径：`data/cache/meta_coverage/{分区}/{year}.parquet`，列：`date, symbol, partition`。

- coverage 是数据文件的纯投影（只登记"有行"），可随时全量重建：`python -m data.rebuild`；
- 三个分区各自记账（partition 字段区分 bar / mv_basic / valuation）；
- 完整性判定：当日 coverage 加上 no_data（确认无行情）必须覆盖当日有效股票集合。

### 8.6 no_data / suspect 状态账本

路径：`data/cache/status/`

| 文件 | 列 | 说明 |
|---|---|---|
| no_data.parquet | date, symbol, reason, last_seen | 确认无数据的账本 |
| suspect.parquet | date, symbol, attempts, status, reason, last_seen | 待复核，连续 3 次转 no_data |
| task_status.json / task.log / scheduler.json | — | WebUI 运行态（任务状态 / 日志 / 调度配置） |

no_data 的 `reason` 枚举：

| reason | 含义 | 复核周期 |
|---|---|---|
| suspended | 确认停牌（状态接口 is_suspended=1） | 365 天 |
| boundary | 上市日 / 退市日 / 代码变更边界 | 365 天 |
| code_change | 批次状态正常但唯独无记录（代码变更特征） | 365 天 |
| anomaly | 有行情却未返回（数据缺口/瞬时故障） | 30 天 |
| unknown | 状态接口失败降级 | 30 天 |

到期后记录被清除并重新进入缺失集合验证一次（自愈），防数据源后来补齐却永久漏抓。

### 8.7 读取示例

```python
from datetime import date
from data.meta_store import MetaStore

store = MetaStore()

# 读某分区全市场某区间（可加 symbols 过滤）
bar = store.read_meta("bar", date(2024, 1, 1), date(2024, 12, 31))
val = store.read_meta(
    "valuation", date(2024, 1, 1), date(2024, 12, 31),
    symbols=["SHSE.600000", "SZSE.000001"],
)

# 覆盖账本与统计
cov = store.coverage("bar")          # DataFrame(date, symbol, partition)
stats = store.stats("mv_basic")      # 覆盖天数 / 范围 / 行数
```

也可以直接用 pandas 读取物理文件：

```python
import pandas as pd
df = pd.read_parquet("data/cache/meta/bar/2024.parquet")
```

> 旧版 bars / coverage 布局（`data/cache/bars/`、`data/cache/coverage/`）已废弃，仅 `data/migrate.py` 兼容迁移用；新交付一律使用 meta 三分区。

### 8.8 交付与验收要点

- 三分区行键严格一致：同日 `(date, symbol)` 集合三个分区完全相同；
- 停牌日行保留、行情列 NaN、`is_suspended=True`；
- 同一任务二次运行零重复抓取（幂等）；
- 交付不经过 Git：数据仓被 `.gitignore` 排除，迁移数据直接拷贝 `data/cache/` 目录；
- 验收命令：`.venv\Scripts\python.exe -m data.rebuild --dry-run --compare`（漂移应为 0）+ `.venv\Scripts\python.exe -m pytest -q`（22 项通过）。

## 九、目录结构

```text
gm-data-manager/
├── README.md / AGENTS.md / 启动WebUI.bat / pyproject.toml / .env.example
├── core/            # 数据源契约与领域模型（DataSource / Bar / Event）
├── data/            # 数据落盘与同步（asset / gm_source / store / meta_store /
│                    #   incremental / meta_fetch / rebuild / migrate）
├── webui/           # Streamlit 数据管理界面 + APScheduler 调度
├── tests/           # 单元测试（mock、无网络）
└── data/cache/      # 本地数据仓（git 忽略，不提交、不上传）
```

本地说明：

- `data/cache/` 是运行时数据仓（parquet 数据 + 任务状态），不进入版本控制；
- 开发文档（PROJECT_PLAN / ENGINE_DESIGN / develop / todo 等）存放在本地 `开发文档/` 目录，不上传 GitHub；
- `.venv`、`.idea`、`.pytest_cache` 均为本地环境，不入库。

## 十、常见问题排查

| 问题 | 处理 |
|---|---|
| `缺少掘金 token：设置环境变量 GM_TOKEN` | 检查根目录 `.env` 是否存在且格式为 `GM_TOKEN=...` |
| 创建 venv 报 Python 版本不符 | 确认使用 Python 3.10（`py -3.10 --version`）；gm SDK 对过高版本兼容性差 |
| `pip install gm` 失败 | 国内网络换清华/阿里镜像源重试 |
| streamlit 端口 8501 被占用 | `streamlit run webui/app.py --server.port 8502` |
| 任务一直显示"上次任务被中断" | 上一进程异常退出，重新触发任务即可；数据不会被破坏（原子写入） |
| 数据任务提示大量"边界"记账 | 上市/退市日、代码变更属正常无行情，365 天复核会自动再验证 |
| GitHub 拉取/推送失败 | 国内网络直连不稳定时配置代理；推送到本仓库可用 `git push`（已配置 origin） |
| pytest 有 numpy 弃用警告 | 可忽略，不影响功能 |
