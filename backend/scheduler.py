"""APScheduler 定时任务：订阅检查 + 数据库备份 + 启动补检"""
import glob
import logging
import os
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import checker
import db

# 借用 uvicorn 的日志处理器，确保日志出现在容器日志中
log = logging.getLogger("uvicorn.error")
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
JOB_ID = "check_all"
BACKUP_JOB_ID = "backup_db"
BACKUP_KEEP = 7
BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")


async def _job():
    log.info("定时任务：开始检查所有订阅")
    try:
        results = await checker.check_all()
        results = [r for r in results if isinstance(r, dict)]
        nodes = sum(r.get("node_count", 0) for r in results)
        alive = sum(r.get("alive_count", 0) for r in results)
        log.info("定时任务：检查完成 %d 个订阅，%d 节点，存活 %d", len(results), nodes, alive)
    except Exception:
        log.exception("定时任务：检查失败")


async def backup_db():
    """用 VACUUM INTO 生成一致性快照，保留最近 BACKUP_KEEP 份"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"aggregator-{stamp}.db")
    await db.backup_to(dest)
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, "aggregator-*.db")))
    for f in files[:-BACKUP_KEEP]:
        try:
            os.remove(f)
        except OSError:
            pass
    log.info("数据库已备份：%s（保留 %d 份）", dest, BACKUP_KEEP)
    return dest


async def _backup_job():
    try:
        await backup_db()
    except Exception:
        log.exception("数据库备份失败")


async def start():
    settings = await db.get_settings()
    minutes = max(1, int(settings.get("interval_minutes", 30) or 30))
    scheduler.add_job(_job, "interval", minutes=minutes, id=JOB_ID,
                      max_instances=1, coalesce=True)
    scheduler.add_job(_backup_job, "cron", hour=3, minute=30, id=BACKUP_JOB_ID,
                      max_instances=1, coalesce=True)
    scheduler.start()
    log.info("定时检查已启动，间隔 %s 分钟；每日 03:30 自动备份数据库", minutes)

    # 启动补检：容器重启会重置间隔计时器，若上次检查已超过一个间隔则立即补检
    now = time.time()
    stale = any(
        s["last_check_at"] and now - s["last_check_at"] > minutes * 60
        for s in await db.list_subscriptions() if s["enabled"]
    )
    if stale:
        scheduler.add_job(_job, "date", run_date=datetime.now() + timedelta(seconds=10),
                          id="catchup_check")
        log.info("检测到检查数据已过期（可能刚重启），10 秒后执行补检")


def next_run_epoch():
    """下次定时检查时间（epoch 秒），未调度返回 0"""
    job = scheduler.get_job(JOB_ID)
    if job and job.next_run_time:
        return job.next_run_time.timestamp()
    return 0


async def reschedule(minutes):
    minutes = max(1, int(minutes))
    await db.set_setting("interval_minutes", minutes)
    if scheduler.get_job(JOB_ID):
        scheduler.reschedule_job(JOB_ID, trigger="interval", minutes=minutes)
    else:
        scheduler.add_job(_job, "interval", minutes=minutes, id=JOB_ID,
                          max_instances=1, coalesce=True)
