"""订阅抓取与检查：流量（subscription-userinfo）、节点存活（TCP 探测）"""
import asyncio
import os
import json
import re
import time

import httpx

import db
from parser import parse_subscription

UA = "clash-verge/v2.0.0"
USERINFO_RE = re.compile(r"(upload|download|total|expire)=(\d+)")
TCP_CONCURRENCY = 100
TCP_TIMEOUT = 5.0
# 抓取订阅是否走代理：默认直连（trust_env=False，避免系统代理拦截）；
# 设置环境变量 SUBHUB_PROXY（如 http://127.0.0.1:7890）后所有抓取走该代理
FETCH_PROXY = os.environ.get("SUBHUB_PROXY") or None


def parse_userinfo(header: str):
    info = {}
    for k, v in USERINFO_RE.findall(header or ""):
        info[k] = int(v)
    return info


async def fetch_subscription(url: str):
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=20.0, trust_env=False, proxy=FETCH_PROXY
    ) as client:
        resp = await client.get(url, headers={"User-Agent": UA})
        resp.raise_for_status()
        return resp.text, resp.headers.get("subscription-userinfo", "")


async def tcp_check(server, port, sem):
    async with sem:
        start = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(server, port), TCP_TIMEOUT
            )
        except Exception:
            return False, 0
        delay = round((time.perf_counter() - start) * 1000)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return True, delay


async def check_subscription(sub: dict):
    """抓取订阅 → 解析节点 → 更新流量 → TCP 探测节点存活"""
    sub_id = sub["id"]
    try:
        text, userinfo_header = await fetch_subscription(sub["url"])
        proxies = parse_subscription(text)
    except Exception as e:
        await db.update_subscription(sub_id, status="error", error=str(e)[:500])
        return {"ok": False, "error": str(e)}

    info = parse_userinfo(userinfo_header)
    node_ids = await db.replace_nodes(sub_id, proxies)
    await db.update_subscription(
        sub_id,
        status="ok",
        error="",
        node_count=len(proxies),
        upload=info.get("upload", 0),
        download=info.get("download", 0),
        total=info.get("total", 0),
        expire=info.get("expire", 0),
        config=json.dumps(proxies, ensure_ascii=False),
    )

    sem = asyncio.Semaphore(TCP_CONCURRENCY)

    async def probe(proxy, node_id):
        alive, delay = await tcp_check(proxy.get("server", ""), proxy.get("port", 0), sem)
        return node_id, alive, delay

    results = await asyncio.gather(*(probe(p, nid) for p, nid in zip(proxies, node_ids)))
    await db.update_nodes_status(results)  # 批量单连接写入，避免 database is locked
    alive_count = sum(1 for _, a, _ in results if a)
    await db.update_subscription(sub_id, alive_count=alive_count, last_check_at=time.time())
    return {"ok": True, "node_count": len(proxies), "alive_count": alive_count}


async def check_all():
    results = []
    for s in await db.list_subscriptions():
        if s["enabled"]:
            results.append(await check_subscription(s))
    return results
