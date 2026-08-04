"""WebUI 任务执行器：后台线程 + 文件状态（跨 Streamlit 会话共享）。

任务状态写入 data/cache/status/task_status.json，WebUI 轮询显示动态进度。
日志写入 data/cache/status/task.log（均已被 .gitignore 排除）。
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path

STATUS_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "status"
STATUS_PATH = STATUS_DIR / "task_status.json"
LOG_PATH = STATUS_DIR / "task.log"

_lock = threading.Lock()
_state: dict = {"thread": None, "stop_event": None}


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write(data: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_log(line: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{_now_iso()}] {line}\n")


def get_status() -> dict:
    data: dict = {"task": None, "running": False, "message": "暂无任务"}
    if STATUS_PATH.exists():
        try:
            data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    with _lock:
        th = _state.get("thread")
        alive = th is not None and th.is_alive()
    # 文件标记 running 但当前进程无活动线程 → 上次任务被中断（如进程退出/重启）
    if data.get("running") and not alive:
        data = {**data, "running": False, "message": "上次任务被中断"}
    return data


def is_running() -> bool:
    with _lock:
        th = _state.get("thread")
        return th is not None and th.is_alive()


def stop_task() -> dict:
    with _lock:
        ev = _state.get("stop_event")
        if ev is not None:
            ev.set()
            _append_log("收到停止指令")
            return {"ok": True}
    return {"ok": False, "error": "无运行中任务"}


def start_task(task_name: str, asset: str, start: date, end: date, max_days: int = 0) -> dict:
    with _lock:
        th = _state.get("thread")
        if th is not None and th.is_alive():
            return {"ok": False, "error": "已有任务运行中"}
        stop_event = threading.Event()
        _state["stop_event"] = stop_event
        thread = threading.Thread(
            target=_run_task,
            args=(task_name, asset, start, end, max_days, stop_event),
            daemon=True,
        )
        _state["thread"] = thread
        thread.start()
        return {"ok": True}


def _run_task(
    task_name: str,
    asset: str,
    start: date,
    end: date,
    max_days: int,
    stop_event: threading.Event,
) -> None:
    status = {
        "task": task_name,
        "asset": asset,
        "running": True,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "current_day": "",
        "done_days": 0,
        "total_days": 0,
        "filled_rows": 0,
        "failed_count": 0,
        "percent": 0.0,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "message": "任务已启动",
        "error": None,
    }
    _write(status)
    _append_log(f"任务启动：{task_name}（{start} ~ {end}）")

    def cb(p: dict) -> None:
        cur = get_status()
        cur.update(p)
        cur["updated_at"] = _now_iso()
        cur["running"] = True
        _write(cur)

    try:
        if task_name == "市场扫描":
            from data.sweep import sweep

            result = sweep(start, end, max_days=max_days, progress_cb=cb, stop_event=stop_event.is_set)
        else:
            from data.incremental import align

            result = align(start, end, max_days=max_days, progress_cb=cb, stop_event=stop_event.is_set)
        cur = get_status()
        cur.update(
            {
                "running": False,
                "done_days": result.get("checked_days", cur.get("done_days", 0)),
                "result": result,
                "message": "任务已停止" if result.get("stopped") else "任务完成",
                "updated_at": _now_iso(),
            }
        )
        _write(cur)
        _append_log(f"任务结束：{task_name} result={result}")
    except Exception as e:  # noqa: BLE001
        cur = get_status()
        cur.update(
            {
                "running": False,
                "error": str(e),
                "message": "任务出错",
                "updated_at": _now_iso(),
            }
        )
        _write(cur)
        _append_log(f"任务出错：{task_name} {e}")
