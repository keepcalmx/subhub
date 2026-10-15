"""APScheduler 定时检查"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import checker
import db

log = logging.getLogger("subhub.scheduler")
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
JOB_ID = "check_all"


async def _job():
    log.info("定时任务：开始检查所有订阅")
    try:
        await checker.check_all()
    except Exception:
        log.exception("定时检查失败")
    log.info("定时任务：检查完成")


async def start():
    settings = await db.get_settings()
    minutes = max(1, int(settings.get("interval_minutes", 30) or 30))
    scheduler.add_job(_job, "interval", minutes=minutes, id=JOB_ID,
                      max_instances=1, coalesce=True)
    scheduler.start()
    log.info("定时检查已启动，间隔 %s 分钟", minutes)


async def reschedule(minutes):
    minutes = max(1, int(minutes))
    await db.set_setting("interval_minutes", minutes)
    if scheduler.get_job(JOB_ID):
        scheduler.reschedule_job(JOB_ID, trigger="interval", minutes=minutes)
    else:
        scheduler.add_job(_job, "interval", minutes=minutes, id=JOB_ID,
                          max_instances=1, coalesce=True)
