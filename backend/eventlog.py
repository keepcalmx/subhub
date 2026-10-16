"""内存事件日志：环形缓冲，供管理页右侧日志面板展示
（重启后清空；重点记录订阅检查结果与异常原因）"""
import collections
import logging
import time

MAX_EVENTS = 500

_events = collections.deque(maxlen=MAX_EVENTS)


def add(message, level="info", source="system"):
    """level: info | warn | error"""
    _events.append({
        "ts": time.time(),
        "level": level,
        "source": str(source)[:16],
        "message": str(message)[:600],
    })


def get(limit=200, errors_only=False):
    items = list(_events)
    if errors_only:
        items = [e for e in items if e["level"] in ("warn", "error")]
    return items[-limit:]


def clear():
    _events.clear()


class _CaptureHandler(logging.Handler):
    """把应用日志（uvicorn.error）镜像进事件缓冲"""

    def emit(self, record):
        try:
            if record.levelno < logging.INFO:
                return
            level = {"WARNING": "warn", "ERROR": "error", "CRITICAL": "error"}.get(
                record.levelname, "info")
            parts = [p for p in record.name.split(".")]
            # uvicorn.error -> app；subhub.scheduler -> scheduler
            src = parts[-1] if parts[-1] not in ("error", "access", "subhub") else (
                parts[-2] if len(parts) > 1 else "app")
            if src == "uvicorn":
                src = "app"
            add(record.getMessage(), level=level, source=src)
        except Exception:
            pass


def install(logger_name="uvicorn.error"):
    """挂载日志镜像处理器（幂等）"""
    lg = logging.getLogger(logger_name)
    for h in lg.handlers:
        if isinstance(h, _CaptureHandler):
            return
    lg.addHandler(_CaptureHandler())
