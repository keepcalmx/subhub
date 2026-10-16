"""APScheduler 定时任务：订阅检查 + 数据库备份"""
import glob
import logging
import os
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import checker
import db

log = logging.getLogger("subhub.scheduler")
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
JOB_ID = "check_all"
BACKUP_JOB_ID = "backup_db"
BACKUP_KEEP = 7
BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")


async def _job():
    log.info("定时任务：开始检查所有订阅")
    try:
        await checker.check_all()
    except Exception:
        log.exception("定时检查失败")
    log.info("定时任务：检查完成")


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


async def reschedule(minutes):
    minutes = max(1, int(minutes))
    await db.set_setting("interval_minutes", minutes)
    if scheduler.get_job(JOB_ID):
        scheduler.reschedule_job(JOB_ID, trigger="interval", minutes=minutes)
    else:
        scheduler.add_job(_job, "interval", minutes=minutes, id=JOB_ID,
                          max_instances=1, coalesce=True)
