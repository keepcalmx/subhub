"""SQLite 数据层：订阅、节点、节点历史、告警去重、设置"""
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
CREATE TABLE IF NOT EXISTS node_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    delay REAL DEFAULT 0,
    alive INTEGER DEFAULT 0,
    checked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_log (
    sub_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (sub_id, kind, day)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_sub ON nodes(sub_id);
CREATE INDEX IF NOT EXISTS idx_history_lookup ON node_history(sub_id, name, checked_at);
"""

DEFAULT_SETTINGS = {
    "token": "",
    "interval_minutes": "30",
    # 延迟检测
    "delay_test_mode": "tcp",          # tcp | mihomo
    "mihomo_api_url": "",              # 如 http://127.0.0.1:9097
    "mihomo_api_secret": "",
    "test_url": "http://www.gstatic.com/generate_204",
    # 策略组参数
    "urltest_interval": "300",
    "urltest_tolerance": "50",
    "lb_strategy": "consistent-hashing",
    "region_groups": "1",
    # 节点处理
    "node_prefix_airport": "1",
    "node_filter_regex": "",
    "node_rename_regex": "",
    "node_rename_to": "",
    "custom_rules": "",
    # 通知
    "notify_bark_url": "",
    "notify_serverchan_key": "",
    "notify_telegram": "",
    "notify_webhook_url": "",
}


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    return aiosqlite.connect(DB_PATH, timeout=30)


async def init_db():
    async with connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript(INIT_SQL)
        for k, v in DEFAULT_SETTINGS.items():
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (k,))
            if await cur.fetchone() is None:
                val = v or secrets.token_hex(16)
                await db.execute("INSERT INTO settings(key, value) VALUES(?,?)", (k, val))
        await db.commit()


# ---------- 设置 ----------

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


# ---------- 订阅 ----------

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


# ---------- 节点 ----------

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


async def update_nodes_status(items):
    """批量更新节点状态。items: [(node_id, alive, delay), ...]"""
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


async def update_node_status_by_name(sub_id, name, alive, delay):
    async with connect() as db:
        await db.execute(
            "UPDATE nodes SET alive=?, delay=?, last_check_at=? WHERE sub_id=? AND name=?",
            (1 if alive else 0, delay or 0, time.time(), sub_id, name),
        )
        await db.commit()


# ---------- 节点历史 ----------

async def insert_node_history(sub_id, items):
    """items: [(name, alive, delay), ...]"""
    if not items:
        return
    now = time.time()
    async with connect() as db:
        await db.executemany(
            "INSERT INTO node_history(sub_id, name, delay, alive, checked_at) VALUES(?,?,?,?,?)",
            [(sub_id, n, d or 0, 1 if a else 0, now) for n, a, d in items],
        )
        await db.commit()


async def prune_node_history(days=30):
    async with connect() as db:
        await db.execute("DELETE FROM node_history WHERE checked_at < ?", (time.time() - days * 86400,))
        await db.commit()


async def get_node_history(sub_id, name, hours=48, limit=240):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT delay, alive, checked_at FROM node_history "
            "WHERE sub_id=? AND name=? AND checked_at > ? ORDER BY checked_at ASC LIMIT ?",
            (sub_id, name, time.time() - hours * 3600, limit),
        )
        return [{"delay": r["delay"], "alive": r["alive"], "t": r["checked_at"]} for r in await cur.fetchall()]


# ---------- 告警去重 ----------

async def should_send_alert(sub_id, kind, day):
    async with connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM alert_log WHERE sub_id=? AND kind=? AND day=?", (sub_id, kind, day))
        return await cur.fetchone() is None


async def mark_alert_sent(sub_id, kind, day):
    async with connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO alert_log(sub_id, kind, day) VALUES(?,?,?)", (sub_id, kind, day))
        await db.commit()


# ---------- 聚合数据 ----------

async def get_proxy_lists(enabled_only=True):
    """返回 [(sub_name, proxies_list)]（含完整代理配置，用于生成聚合输出）"""
    result = []
    for s in await list_subscriptions():
        if enabled_only and not s["enabled"]:
            continue
        try:
            plist = json.loads(s["config"] or "[]")
        except json.JSONDecodeError:
            continue
        if isinstance(plist, list) and plist:
            result.append((s["name"], plist))
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
