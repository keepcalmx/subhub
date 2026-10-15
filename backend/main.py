"""SubHub - 机场订阅聚合平台 API"""
import os
import secrets
from contextlib import asynccontextmanager

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import checker
import db
import generator
import scheduler as sched

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
    interval_minutes: int | None = None
    regenerate_token: bool = False


# ---------- 订阅管理 ----------

@app.get("/api/subscriptions")
async def list_subs():
    subs = await db.list_subscriptions()
    for s in subs:
        s.pop("config", None)  # 完整配置不下发给前端
    return subs


@app.post("/api/subscriptions", status_code=201)
async def create_sub(body: SubIn):
    sub_id = await db.create_subscription(body.name.strip(), body.url.strip(), body.enabled)
    sub = await db.get_subscription(sub_id)
    # 添加后立即异步检查一次
    import asyncio
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


# ---------- 统计 / 设置 ----------

@app.get("/api/dashboard")
async def dashboard():
    return await db.stats()


@app.get("/api/settings")
async def get_settings():
    settings = await db.get_settings()
    return {
        "token": settings.get("token", ""),
        "interval_minutes": int(settings.get("interval_minutes", 30) or 30),
    }


@app.put("/api/settings")
async def update_settings(body: SettingsIn):
    if body.interval_minutes is not None:
        await sched.reschedule(body.interval_minutes)
    if body.regenerate_token:
        await db.set_setting("token", secrets.token_hex(16))
    return await get_settings()


# ---------- 聚合订阅输出 ----------

@app.get("/api/subscribe/{token}")
async def subscribe(token: str):
    settings = await db.get_settings()
    if token != settings.get("token"):
        raise HTTPException(404, "无效的订阅地址")

    proxy_lists = await db.get_proxy_lists(enabled_only=True)
    cfg = generator.build_clash_config(proxy_lists)
    text = generator.dump_yaml(cfg)

    enabled = [s for s in await db.list_subscriptions() if s["enabled"]]
    upload = sum(s["upload"] for s in enabled)
    download = sum(s["download"] for s in enabled)
    total = sum(s["total"] for s in enabled)

    return Response(
        content=text,
        media_type="text/yaml; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="subhub.yaml"',
            "subscription-userinfo": f"upload={upload}; download={download}; total={total}",
            "profile-update-interval": "24",
        },
    )


# ---------- 静态页面 ----------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
