"""SQLite 数据层：订阅、节点、设置"""
import json
import os
import secrets
import time

import aiosqlite

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "aggregator.db")

INIT_SQL = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_check_at REAL DEFAULT 0,
    upload INTEGER DEFAULT 0,
    download INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    expire INTEGER DEFAULT 0,
    node_count INTEGER DEFAULT 0,
    alive_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    error TEXT DEFAULT '',
    config TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_id INTEGER NOT NULL,
    name TEXT,
    server TEXT,
    port INTEGER,
    type TEXT,
    alive INTEGER DEFAULT 0,
    delay REAL DEFAULT 0,
    last_check_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_sub ON nodes(sub_id);
"""


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    # timeout: 写锁等待 30s，避免并发写入时 database is locked
    return aiosqlite.connect(DB_PATH, timeout=30)


async def init_db():
    async with connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")  # 读写并发友好
        await db.executescript(INIT_SQL)
        for k in ("token", "interval_minutes"):
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (k,))
            row = await cur.fetchone()
            if row is None:
                val = secrets.token_hex(16) if k == "token" else "30"
                await db.execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, val))
        await db.commit()


async def get_settings() -> dict:
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in await cur.fetchall()}


async def set_setting(key, value):
    async with connect() as db:
        await db.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        await db.commit()


async def list_subscriptions():
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM subscriptions ORDER BY id")
        return [dict(r) for r in await cur.fetchall()]


async def get_subscription(sub_id):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_subscription(name, url, enabled=True):
    async with connect() as db:
        cur = await db.execute(
            "INSERT INTO subscriptions(name, url, enabled, created_at) VALUES(?,?,?,?)",
            (name, url, 1 if enabled else 0, time.time()),
        )
        await db.commit()
        return cur.lastrowid


SUB_FIELDS = {
    "name", "url", "enabled", "upload", "download", "total", "expire",
    "node_count", "alive_count", "status", "error", "config", "last_check_at",
}


async def update_subscription(sub_id, **fields):
    fields = {k: v for k, v in fields.items() if k in SUB_FIELDS}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    async with connect() as db:
        await db.execute(f"UPDATE subscriptions SET {sets} WHERE id=?", (*fields.values(), sub_id))
        await db.commit()


async def delete_subscription(sub_id):
    async with connect() as db:
        await db.execute("DELETE FROM nodes WHERE sub_id=?", (sub_id,))
        await db.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
        await db.commit()


async def replace_nodes(sub_id, proxies):
    """全量替换某订阅的节点记录，返回与 proxies 对齐的 node id 列表"""
    ids = []
    async with connect() as db:
        await db.execute("DELETE FROM nodes WHERE sub_id=?", (sub_id,))
        for p in proxies:
            try:
                port = int(p.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            cur = await db.execute(
                "INSERT INTO nodes(sub_id, name, server, port, type) VALUES(?,?,?,?,?)",
                (sub_id, str(p.get("name", "")), str(p.get("server", "")), port, str(p.get("type", ""))),
            )
            ids.append(cur.lastrowid)
        await db.commit()
    return ids


async def update_node_status(node_id, alive, delay):
    async with connect() as db:
        await db.execute(
            "UPDATE nodes SET alive=?, delay=?, last_check_at=? WHERE id=?",
            (1 if alive else 0, delay or 0, time.time(), node_id),
        )
        await db.commit()


async def update_nodes_status(items):
    """批量更新节点状态。items: [(node_id, alive, delay), ...]，单连接写入避免锁冲突"""
    if not items:
        return
    now = time.time()
    async with connect() as db:
        await db.executemany(
            "UPDATE nodes SET alive=?, delay=?, last_check_at=? WHERE id=?",
            [(1 if a else 0, d or 0, now, nid) for nid, a, d in items],
        )
        await db.commit()


async def list_nodes(sub_id):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM nodes WHERE sub_id=? ORDER BY id", (sub_id,))
        return [dict(r) for r in await cur.fetchall()]


async def get_proxy_lists(enabled_only=True):
    """返回所有（启用的）订阅最近一次抓取到的完整代理配置列表"""
    result = []
    for s in await list_subscriptions():
        if enabled_only and not s["enabled"]:
            continue
        try:
            plist = json.loads(s["config"] or "[]")
        except json.JSONDecodeError:
            continue
        if isinstance(plist, list) and plist:
            result.append(plist)
    return result


async def stats():
    subs = await list_subscriptions()
    async with connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM nodes")
        nodes_total = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM nodes WHERE alive=1")
        nodes_alive = (await cur.fetchone())[0]
    return {
        "subs_total": len(subs),
        "subs_enabled": sum(1 for s in subs if s["enabled"]),
        "nodes_total": nodes_total,
        "nodes_alive": nodes_alive,
        "traffic_used": sum(s["upload"] + s["download"] for s in subs),
        "traffic_total": sum(s["total"] for s in subs),
    }
