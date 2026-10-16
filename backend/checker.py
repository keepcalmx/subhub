"""订阅抓取与检查：流量、节点存活/延迟（TCP 握手或 mihomo 真实测速）、历史记录、告警"""
import asyncio
import json
import os
import re
import time
from urllib.parse import quote, urlparse

import httpx
import yaml

import db
import notifier
from generator import dedupe_proxies
from parser import parse_subscription

UA = "clash-verge/v2.0.0"
USERINFO_RE = re.compile(r"(upload|download|total|expire)=(\d+)")
TCP_CONCURRENCY = 100
TCP_TIMEOUT = 5.0
MIHOMO_CONCURRENCY = 20
MIHOMO_TEST_TIMEOUT_MS = 5000
# 抓取订阅默认直连；设 SUBHUB_PROXY 环境变量可让所有抓取走代理
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


# ---------- TCP 握手测活 ----------

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


# ---------- mihomo 真实 URL 测速 ----------

async def mihomo_delay_test(proxies, settings):
    """把节点推给 mihomo 实例，通过其 API 对每个节点做真实 URL 延迟测试。
    返回与 proxies 对齐的 [(alive, delay), ...]；推送失败抛异常（由调用方回退 TCP）"""
    base = (settings.get("mihomo_api_url") or "").rstrip("/")
    secret = settings.get("mihomo_api_secret") or ""
    test_url = settings.get("test_url") or "http://www.gstatic.com/generate_204"
    hostport = urlparse(base).netloc
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}

    proxies = dedupe_proxies([dict(p) for p in proxies])
    payload_cfg = {
        "external-controller": hostport,
        "secret": secret,
        "mode": "rule",
        "log-level": "warning",
        "proxies": proxies,
    }
    payload = yaml.dump(payload_cfg, allow_unicode=True, sort_keys=False)

    results = {}
    sem = asyncio.Semaphore(MIHOMO_CONCURRENCY)
    async with httpx.AsyncClient(timeout=12.0, trust_env=False, headers=headers) as client:
        r = await client.put(f"{base}/configs?force=true", json={"payload": payload, "path": ""})
        r.raise_for_status()

        async def one(p):
            name = p["name"]
            async with sem:
                try:
                    resp = await client.get(
                        f"{base}/proxies/{quote(name, safe='')}/delay",
                        params={"timeout": MIHOMO_TEST_TIMEOUT_MS, "url": test_url},
                    )
                    if resp.status_code == 200:
                        results[name] = (True, int(resp.json().get("delay", 0)))
                    else:
                        results[name] = (False, 0)
                except Exception:
                    results[name] = (False, 0)

        await asyncio.gather(*(one(p) for p in proxies))

    return [results.get(p["name"], (False, 0)) for p in proxies]


# ---------- 主检查流程 ----------

async def check_subscription(sub: dict):
    sub_id = sub["id"]
    settings = await db.get_settings()

    # 1) 抓取 + 解析
    try:
        text, userinfo_header = await fetch_subscription(sub["url"])
        proxies = parse_subscription(text)
    except Exception as e:
        await db.update_subscription(sub_id, status="error", error=str(e)[:500])
        await notifier.check_and_notify(sub_id)
        return {"ok": False, "error": str(e)}

    # 2) 流量信息 + 节点表更新
    info = parse_userinfo(userinfo_header)
    node_ids = await db.replace_nodes(sub_id, proxies)
    await db.update_subscription(
        sub_id,
        status="ok", error="", node_count=len(proxies),
        upload=info.get("upload", 0), download=info.get("download", 0),
        total=info.get("total", 0), expire=info.get("expire", 0),
        config=json.dumps(proxies, ensure_ascii=False),
    )

    # 3) 延迟检测：mihomo 真实测速（配置了才启用），失败回退 TCP
    delay_mode = "tcp"
    alive_delays = None
    if settings.get("delay_test_mode") == "mihomo" and (settings.get("mihomo_api_url") or "").strip():
        try:
            alive_delays = await mihomo_delay_test(proxies, settings)
            delay_mode = "mihomo"
        except Exception:
            alive_delays = None
    if alive_delays is None:
        sem = asyncio.Semaphore(TCP_CONCURRENCY)

        async def probe(p):
            return await tcp_check(p.get("server", ""), p.get("port", 0), sem)

        alive_delays = list(await asyncio.gather(*(probe(p) for p in proxies)))

    # 4) 批量写节点状态 + 历史记录
    items = [(nid, a, d) for nid, (a, d) in zip(node_ids, alive_delays)]
    await db.update_nodes_status(items)
    await db.insert_node_history(sub_id, [(p["name"], a, d) for p, (a, d) in zip(proxies, alive_delays)])
    alive_count = sum(1 for _, a, _ in items if a)
    await db.update_subscription(sub_id, alive_count=alive_count, last_check_at=time.time())

    # 5) 告警检查
    await notifier.check_and_notify(sub_id)
    return {"ok": True, "node_count": len(proxies), "alive_count": alive_count, "delay_mode": delay_mode}


async def check_all():
    results = []
    for s in await db.list_subscriptions():
        if s["enabled"]:
            results.append(await check_subscription(s))
    await db.prune_node_history(days=30)
    return results


async def test_single_node(sub_id, name):
    """对单个节点测速（mihomo 真实测速优先，失败/未配置回退 TCP），并写入状态与历史"""
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise ValueError("订阅不存在")
    try:
        proxies = json.loads(sub["config"] or "[]")
    except json.JSONDecodeError:
        proxies = []
    proxy = next((p for p in proxies if p.get("name") == name), None)
    if not proxy:
        raise ValueError("节点不存在（订阅可能已更新，请先重新检查）")

    settings = await db.get_settings()
    mode = "tcp"
    alive, delay = False, 0
    if settings.get("delay_test_mode") == "mihomo" and (settings.get("mihomo_api_url") or "").strip():
        try:
            res = await mihomo_delay_test([proxy], settings)
            alive, delay = res[0]
            mode = "mihomo"
        except Exception:
            alive, delay = await tcp_check(proxy.get("server", ""), proxy.get("port", 0),
                                            asyncio.Semaphore(1))
    else:
        alive, delay = await tcp_check(proxy.get("server", ""), proxy.get("port", 0),
                                       asyncio.Semaphore(1))

    await db.update_node_status_by_name(sub_id, name, alive, delay)
    await db.insert_node_history(sub_id, [(name, alive, delay)])
    return {"alive": alive, "delay": delay, "mode": mode}
