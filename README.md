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

## 八、目录结构

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

## 九、常见问题排查

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
