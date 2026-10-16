"""流量 / 到期 / 抓取异常告警：Bark、Server酱、Telegram、通用 Webhook（按天去重）"""
import datetime
import time

import httpx

import db

TRAFFIC_THRESHOLD = 0.10  # 剩余流量占比阈值
EXPIRE_DAYS = 7           # 到期提醒天数

NOTIFY_KEYS = ("notify_bark_url", "notify_serverchan_key", "notify_telegram", "notify_webhook_url",
               "notify_wecom_url", "notify_dingtalk_url", "notify_feishu_url")


def _fmt_bytes(n):
    if not n or n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.1f} {units[i]}"


async def _send(title, body, settings):
    """向所有已配置渠道发送，任一成功即返回 True"""
    sent = False
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        bark = (settings.get("notify_bark_url") or "").strip()
        if bark:
            try:
                r = await client.post(bark.rstrip("/"), json={"title": title, "body": body, "group": "subhub"})
                sent = sent or r.status_code < 300
            except Exception:
                pass
        sc = (settings.get("notify_serverchan_key") or "").strip()
        if sc:
            try:
                r = await client.post(f"https://sctapi.ftqq.com/{sc}.send",
                                      data={"title": title, "desp": body})
                sent = sent or r.status_code < 300
            except Exception:
                pass
        tg = (settings.get("notify_telegram") or "").strip()
        if tg and ":" in tg:
            token, chat = tg.split(":", 1)
            try:
                r = await client.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                      json={"chat_id": chat, "text": f"{title}\n{body}"})
                sent = sent or r.status_code < 300
            except Exception:
                pass
        wh = (settings.get("notify_webhook_url") or "").strip()
        if wh:
            try:
                r = await client.post(wh, json={"title": title, "body": body, "ts": int(time.time())})
                sent = sent or r.status_code < 300
            except Exception:
                pass
        wecom = (settings.get("notify_wecom_url") or "").strip()
        if wecom:
            try:
                r = await client.post(wecom, json={"msgtype": "text",
                                                   "text": {"content": f"{title}\n{body}"}})
                sent = sent or r.status_code < 300
            except Exception:
                pass
        dingtalk = (settings.get("notify_dingtalk_url") or "").strip()
        if dingtalk:
            try:
                r = await client.post(dingtalk, json={"msgtype": "text",
                                                      "text": {"content": f"{title}\n{body}"}})
                sent = sent or r.status_code < 300
            except Exception:
                pass
        feishu = (settings.get("notify_feishu_url") or "").strip()
        if feishu:
            try:
                r = await client.post(feishu, json={"msg_type": "text",
                                                    "content": {"text": f"{title}\n{body}"}})
                sent = sent or r.status_code < 300
            except Exception:
                pass
    return sent


async def check_and_notify(sub_id):
    """检查某订阅的告警条件并发送（每 sub+kind+天 只发一次）"""
    settings = await db.get_settings()
    if not any((settings.get(k) or "").strip() for k in NOTIFY_KEYS):
        return  # 未配置任何通知渠道
    sub = await db.get_subscription(sub_id)
    if not sub:
        return

    now = time.time()
    alerts = []

    if sub["status"] == "error":
        alerts.append(("fetch_error",
                       f"⚠️ 订阅「{sub['name']}」抓取失败：{(sub['error'] or '')[:100]}"))
    if sub["total"] > 0:
        remaining = sub["total"] - (sub["upload"] + sub["download"])
        if remaining / sub["total"] < TRAFFIC_THRESHOLD:
            alerts.append(("traffic_low",
                           f"📉 订阅「{sub['name']}」剩余流量不足 10%："
                           f"剩余 {_fmt_bytes(remaining)} / 总量 {_fmt_bytes(sub['total'])}"))
    if sub["expire"] > 0:
        days = (sub["expire"] - now) / 86400
        if 0 <= days < EXPIRE_DAYS:
            alerts.append(("expire_soon",
                           f"⏰ 订阅「{sub['name']}」将于 {days:.0f} 天后到期"
                           f"（{datetime.date.fromtimestamp(sub['expire'])}）"))

    day = datetime.date.today().isoformat()
    for kind, text in alerts:
        if await db.should_send_alert(sub_id, kind, day):
            if await _send("SubHub 订阅告警", text, settings):
                await db.mark_alert_sent(sub_id, kind, day)
