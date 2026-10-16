"""SubHub - 机场订阅聚合平台 API"""
import json
import re
import os
import secrets
from contextlib import asynccontextmanager

import converters
import generator
import scheduler as sched
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import checker
import db
import regions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await sched.start()
    yield
    if sched.scheduler.running:
        sched.scheduler.shutdown(wait=False)


app = FastAPI(title="SubHub - 机场订阅聚合平台", lifespan=lifespan)


# ---------- Pydantic ----------

class SubIn(BaseModel):
    name: str
    url: str
    enabled: bool = True


class SubPatch(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None


class SettingsIn(BaseModel):
    values: dict          # 可设置项白名单之外的被忽略
    regenerate_token: bool = False


class NodeTestIn(BaseModel):
    sub_id: int
    name: str             # 原始节点名（nodes 表中的 name）


# 可通过 API 修改的设置项（token 除外，走 regenerate_token）
SETTABLE_KEYS = {
    "interval_minutes", "delay_test_mode", "mihomo_api_url", "mihomo_api_secret",
    "test_url", "urltest_interval", "urltest_tolerance", "lb_strategy",
    "region_groups", "node_prefix_airport", "node_filter_regex",
    "node_rename_regex", "node_rename_to", "custom_rules",
    "notify_bark_url", "notify_serverchan_key", "notify_telegram", "notify_webhook_url",
}


# ---------- 订阅管理 ----------

@app.get("/api/subscriptions")
async def list_subs():
    subs = await db.list_subscriptions()
    for s in subs:
        s.pop("config", None)
    return subs


@app.post("/api/subscriptions", status_code=201)
async def create_sub(body: SubIn):
    sub_id = await db.create_subscription(body.name.strip(), body.url.strip(), body.enabled)
    import asyncio
    sub = await db.get_subscription(sub_id)
    asyncio.get_event_loop().create_task(checker.check_subscription(sub))
    sub.pop("config", None)
    return sub


@app.patch("/api/subscriptions/{sub_id}")
async def patch_sub(sub_id: int, body: SubPatch):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(404, "订阅不存在")
    fields = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.url is not None:
        fields["url"] = body.url.strip()
    if body.enabled is not None:
        fields["enabled"] = 1 if body.enabled else 0
    await db.update_subscription(sub_id, **fields)
    updated = await db.get_subscription(sub_id)
    updated.pop("config", None)
    return updated


@app.delete("/api/subscriptions/{sub_id}")
async def delete_sub(sub_id: int):
    if not await db.get_subscription(sub_id):
        raise HTTPException(404, "订阅不存在")
    await db.delete_subscription(sub_id)
    return {"ok": True}


@app.get("/api/subscriptions/{sub_id}/nodes")
async def get_nodes(sub_id: int):
    if not await db.get_subscription(sub_id):
        raise HTTPException(404, "订阅不存在")
    return await db.list_nodes(sub_id)


@app.post("/api/subscriptions/{sub_id}/check")
async def check_sub(sub_id: int):
    sub = await db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(404, "订阅不存在")
    return await checker.check_subscription(sub)


@app.post("/api/check-all")
async def check_all():
    return await checker.check_all()


# ---------- 全部节点视图 ----------

@app.get("/api/nodes/all")
async def nodes_all():
    """聚合后的全部节点（应用前缀/过滤/重命名后的最终名称），含状态与地区"""
    settings = await db.get_settings()
    rows = []
    for s in await db.list_subscriptions():
        if not s["enabled"]:
            continue
        try:
            proxies = json.loads(s["config"] or "[]")
        except json.JSONDecodeError:
            continue
        if not proxies:
            continue
        status = {n["name"]: n for n in await db.list_nodes(s["id"])}
        for p in proxies:
            raw = str(p.get("name", ""))
            disp = generator.transform_name(raw, s["name"], settings)
            if disp is None:
                continue
            st = status.get(raw, {})
            rows.append({
                "sub_id": s["id"], "sub_name": s["name"],
                "name": disp, "raw_name": raw,
                "type": p.get("type", ""),
                "server": p.get("server", ""), "port": p.get("port", 0),
                "region": regions.detect(disp) or "其他",
                "alive": st.get("alive", 0), "delay": st.get("delay", 0),
                "last_check_at": st.get("last_check_at", 0),
            })
    return rows


@app.post("/api/nodes/test")
async def test_node(body: NodeTestIn):
    try:
        return await checker.test_single_node(body.sub_id, body.name)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------- 节点历史 ----------

@app.get("/api/nodes/history")
async def node_history(sub_id: int, name: str, hours: int = Query(48, ge=1, le=720)):
    if not await db.get_subscription(sub_id):
        raise HTTPException(404, "订阅不存在")
    return await db.get_node_history(sub_id, name, hours=hours)


# ---------- 统计 / 设置 ----------

@app.get("/api/dashboard")
async def dashboard():
    return await db.stats()


@app.get("/api/settings")
async def get_settings():
    return await db.get_settings()


@app.put("/api/settings")
async def update_settings(body: SettingsIn):
    for k, v in (body.values or {}).items():
        if k not in SETTABLE_KEYS:
            continue
        if v is None:
            v = ""
        v = str(v).strip()
        if k in ("mihomo_api_url",) and v and not v.startswith("http"):
            raise HTTPException(400, "mihomo API 地址必须以 http(s):// 开头")
        if k in ("urltest_interval", "urltest_tolerance") and (not v.isdigit() or int(v) < 1):
            raise HTTPException(400, "测速间隔/容差必须为正整数")
        if k == "interval_minutes":
            if not v.isdigit() or int(v) < 1:
                raise HTTPException(400, "检查间隔必须为正整数")
            await sched.reschedule(int(v))
        if k == "lb_strategy" and v not in ("consistent-hashing", "round-robin", "sticky-sessions"):
            raise HTTPException(400, "负载策略不合法")
        if k == "custom_rules" and v:
            # 每行必须是 Clash 规则格式：TYPE,VALUE,POLICY（至少两个逗号）
            bad = [ln for ln in v.splitlines() if ln.strip() and ln.count(",") < 2]
            if bad:
                raise HTTPException(400, f"规则格式非法（需 TYPE,VALUE,POLICY）：{bad[0][:40]}")
        if k in ("node_filter_regex", "node_rename_regex") and v:
            try:
                re.compile(v)
            except re.error as e:
                raise HTTPException(400, f"{k} 正则非法：{e}")
        if k == "delay_test_mode" and v not in ("tcp", "mihomo"):
            raise HTTPException(400, "检测模式只支持 tcp / mihomo")
        if len(v) > 8000:
            raise HTTPException(400, f"{k} 内容过长")
        await db.set_setting(k, v)
    if body.regenerate_token:
        await db.set_setting("token", secrets.token_hex(16))
    return await db.get_settings()


# ---------- 聚合订阅输出 ----------

@app.get("/api/subscribe/{token}")
async def subscribe(token: str, target: str = "clash"):
    settings = await db.get_settings()
    if token != settings.get("token"):
        raise HTTPException(404, "无效的订阅地址")
    if target not in ("clash", "singbox", "v2ray"):
        raise HTTPException(400, "target 只支持 clash / singbox / v2ray")

    proxy_lists = await db.get_proxy_lists(enabled_only=True)
    enabled = [s for s in await db.list_subscriptions() if s["enabled"]]
    upload = sum(s["upload"] for s in enabled)
    download = sum(s["download"] for s in enabled)
    total = sum(s["total"] for s in enabled)
    userinfo = f"upload={upload}; download={download}; total={total}"
    base_headers = {
        "subscription-userinfo": userinfo,
        "profile-update-interval": "24",
    }

    if target == "clash":
        cfg = generator.build_clash_config(proxy_lists, settings)
        return Response(
            content=generator.dump_yaml(cfg),
            media_type="text/yaml; charset=utf-8",
            headers={**base_headers, "Content-Disposition": 'attachment; filename="subhub.yaml"'},
        )

    if target == "singbox":
        cfg, skipped = converters.build_singbox_config(proxy_lists, settings)
        return Response(
            content=json.dumps(cfg, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={**base_headers,
                     "Content-Disposition": 'attachment; filename="subhub.json"',
                     "x-skipped-outbounds": str(skipped)},
        )

    # v2ray base64
    import generator as gen
    proxies = gen.apply_node_policies(proxy_lists, settings)
    b64, skipped = converters.build_v2ray_base64(proxies)
    return Response(
        content=b64,
        media_type="text/plain; charset=utf-8",
        headers={**base_headers,
                 "Content-Disposition": 'attachment; filename="subhub.txt"',
                 "x-skipped-nodes": str(skipped)},
    )


# ---------- 静态页面 ----------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
