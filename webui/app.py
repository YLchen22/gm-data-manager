"""GM Data Manager WebUI（Streamlit + APScheduler）。

功能：
- 截面数据任务（全量/增量）：按钮触发，动态进度条（fragment 自动轮询）；
- 数据状态：覆盖天数、范围、未对齐统计（先扫描本地，避免重复抓取）；
- 自动调度：工作日定时截面增量（配置持久化到 data/cache/status/scheduler.json）。

启动：streamlit run webui/app.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, time as dtime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from webui.tasks import get_status, is_running, start_task, stop_task  # noqa: E402

ASSET = "stock"
SCHEDULE_PATH = PROJECT_ROOT / "data" / "cache" / "status" / "scheduler.json"


# ---------- 数据状态（缓存 10 分钟；统计在后台并行 fragment 中计算，不阻塞页面） ----------
@st.cache_data(ttl=600, show_spinner=False)
def load_data_overview() -> dict:
    """一次性统计：meta 三分区覆盖 + 尚未对齐口径。"""
    from data.meta_fetch import scan_missing_meta_summary
    from data.meta_store import META_SUBSETS, MetaStore

    overview = scan_missing_meta_summary(date(2016, 1, 1), date.today())
    store = MetaStore()
    overview["cells"] = {p: len(store.coverage(p)) for p in META_SUBSETS}
    return overview


# ---------- 调度（APScheduler 单例） ----------
_scheduler = None
_applied_schedule: tuple | None = None


def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler


def _run_scheduled() -> None:
    start_task("截面数据", ASSET, date(2016, 1, 1), date.today(), max_days=0)


def apply_schedule(enabled: bool, hour: int, minute: int) -> None:
    global _applied_schedule
    key = (enabled, hour, minute)
    if key == _applied_schedule:
        return
    sched = _get_scheduler()
    if sched.get_job("daily_incremental"):
        sched.remove_job("daily_incremental")
    if enabled:
        sched.add_job(
            _run_scheduled,
            "cron",
            day_of_week="mon-fri",
            hour=hour,
            minute=minute,
            id="daily_incremental",
            misfire_grace_time=3600,
        )
    _applied_schedule = key


def load_schedule() -> dict:
    if SCHEDULE_PATH.exists():
        try:
            return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"enabled": False, "hour": 17, "minute": 0}


def save_schedule(data: dict) -> None:
    SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 页面 ----------
st.set_page_config(page_title="GM Data Manager", page_icon="📊", layout="wide")
st.title("GM Data Manager")
st.caption(
    f"资产类别：{ASSET} · 数据范围：2016-01-01 至今 · "
    "覆盖：沪深全 A 股（主板/创业板/科创板，含全部历史退市股），先扫描本地只补缺失"
)

running = is_running()
status = get_status()

# ---------- 侧边栏：任务控制 ----------
with st.sidebar:
    st.header("任务控制")
    st.caption("任务由你手动点击触发，进度实时显示在主区。")
    if running:
        st.warning(f"运行中：{status.get('task')}")
    else:
        st.info("空闲")

    if st.button("🚀 截面数据任务（全量/增量）", disabled=running, use_container_width=True):
        r = start_task("截面数据", ASSET, date(2016, 1, 1), date.today(), max_days=0)
        st.toast("已启动" if r.get("ok") else f"启动失败：{r.get('error')}")
    if st.button("🗂 重建覆盖清单", disabled=running, use_container_width=True):
        r = start_task("重建覆盖清单", ASSET, date(2016, 1, 1), date.today(), max_days=0)
        st.toast("已启动" if r.get("ok") else f"启动失败：{r.get('error')}")
    if running:
        if st.button("⏹ 停止", use_container_width=True):
            stop_task()

    st.divider()
    st.header("自动调度")
    settings = load_schedule()
    enabled = st.toggle("启用工作日自动截面数据", value=bool(settings["enabled"]))
    t = st.time_input("运行时间", dtime(settings["hour"], settings["minute"]))
    if st.button("保存调度设置", use_container_width=True):
        save_schedule({"enabled": bool(enabled), "hour": t.hour, "minute": t.minute})
        apply_schedule(bool(enabled), t.hour, t.minute)
        st.toast("调度设置已保存并生效")

# 页面加载即应用持久化的调度设置（避免重复注册）
apply_schedule(bool(settings["enabled"]), settings["hour"], settings["minute"])

# ---------- 主区：数据状态（后台并行计算，页面其余部分先渲染） ----------
@st.fragment(parallel=True)
def stats_section() -> None:
    try:
        with st.spinner("正在扫描本地覆盖，计算尚未对齐…"):
            o = load_data_overview()
    except Exception as e:
        st.error(f"数据状态加载失败：{e}")
        return
    cells = o.get("cells") or {}
    total_cells = sum(cells.values())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("覆盖交易日", f"{o.get('meta_days', 0)} 天（缺失）")
    c2.metric("数据范围", f"{o.get('meta_first_missing_day') or '已全部对齐'}")
    c3.metric("覆盖数据量", f"{total_cells:,} 行")
    c4.metric("待补分区", f"{o.get('meta_rows', 0):,} 子集天")
    if o.get("meta_first_missing_day"):
        st.caption(
            f"未对齐：{o.get('meta_rows', 0)} 个子集天（bar/mv_basic/valuation 按日对齐）· "
            f"最早缺失 {o.get('meta_first_missing_day')} · 待补 {', '.join(o.get('meta_subsets', []) or [])}"
            "（点击上方任务按钮开始补齐）"
        )
    else:
        st.caption("三个分区（bar / mv_basic / valuation）已全部对齐")
    if st.button("刷新统计", width="content"):
        load_data_overview.clear()
        st.rerun(scope="fragment")


stats_section()


# ---------- 动态进度（fragment 轮询） ----------
@st.fragment(run_every=2.0)
def show_progress() -> None:
    s = get_status()
    if s.get("running"):
        st.subheader("任务进度")
        st.progress(min(float(s.get("percent", 0.0)), 1.0))
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("任务", s.get("task"))
        if s.get("mode") == "rebuild":
            p2.metric("当前年份", s.get("current") or "-")
            p3.metric("进度", f"{s.get('done_days', 0)} / {s.get('total_days', 0)} 年")
            p4.metric("已生成行数", f"{s.get('filled_rows', 0):,}")
        elif s.get("mode") == "rebuild_meta":
            p2.metric("当前分区/年份", s.get("current") or "-")
            p3.metric("进度", f"{s.get('done_days', 0)} / {s.get('total_days', 0)} 份")
            p4.metric("已投影行数", f"{s.get('filled_rows', 0):,}")
        else:
            p2.metric("当前日期", s.get("current") or "-")
            p3.metric("进度", f"{s.get('done_days', 0)} / {s.get('total_days', 0)} 天")
            p4.metric("已入库行数", f"{s.get('filled_rows', 0):,}")
        if s.get("mode") == "meta":
            if s.get("phase") == "scan":
                st.caption(
                    f"正在扫描三分区覆盖：{s.get('done_days', 0)} / {s.get('total_days', 0)} 天"
                    "（先扫本地、只补缺失）"
                )
            else:
                missing = s.get("missing_count", 0)
                filled = s.get("filled_count", 0)
                no_data = s.get("no_data_count", 0)
                st.caption(
                    f"当日：{s.get('current') or '-'} · 待补 {missing} 分区 → 已入库 {filled} · 边界 {no_data}"
                    "（边界=代码变更/上市退市日，365 天复核）"
                )
        if st.button("⏹ 停止任务", use_container_width=False):
            stop_task()
            st.toast("已发送停止指令，任务将在当前步骤结束后停止")
    elif s.get("result") is not None or s.get("error"):
        st.subheader("最近任务结果")
        if s.get("error"):
            st.error(f"出错：{s.get('error')}")
        else:
            r = s.get("result") or {}
            note = "（已停止）" if r.get("stopped") else ""
            if r.get("years") is not None:
                empty = "（空）" if r.get("rows", 0) == 0 else ""
                stale = len(r.get("deleted_stale_years", []))
                aud = r.get("audit") or {}
                if aud.get("flagged_days"):
                    audit_txt = (
                        f"，异常审计标记 {len(aud['flagged_days'])} 天需重抓 / "
                        f"清除 {aud.get('removed_rows', 0)} 条"
                    )
                else:
                    audit_txt = "，异常审计无存疑"
                st.success(
                    f"{s.get('message')}{note}：重建覆盖清单{empty}"
                    f"：{len(r.get('years', []))} 年 / {r.get('rows', 0):,} 行"
                    + (f"，清理残留 {stale} 个年份" if stale else "")
                    + audit_txt
                )
            else:
                failed_n = r.get("failed", 0)
                no_data_n = r.get("no_data", 0)
                tail = f"，空补 {no_data_n} 条" if no_data_n else ""
                tail2 = f"，待复核 {failed_n} 条" if failed_n else ""
                st.success(
                    f"{s.get('message')}{note}：检查 {r.get('checked_days', 0)} 天，"
                    f"已入库 {r.get('filled_rows', 0)} 行{tail}{tail2}"
                )


show_progress()

# ---------- 任务日志 ----------
st.subheader("任务日志")
log_path = PROJECT_ROOT / "data" / "cache" / "status" / "task.log"
if log_path.exists():
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    st.code("\n".join(lines[-20:]), language="text")
else:
    st.caption("暂无日志（任务尚未运行）")
