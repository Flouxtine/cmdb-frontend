"""SQLite 访问 + 建表（M1 表 + M2-M4 预留）"""
import json
import sqlite3
import threading
from contextlib import contextmanager

from . import config

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_conn():
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS credentials (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                access_key TEXT,
                secret_key TEXT,
                regions TEXT DEFAULT '[]',
                remark TEXT DEFAULT '',
                status TEXT DEFAULT 'untested',
                last_error TEXT,
                last_sync_at TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                credential_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                name TEXT NOT NULL,
                region TEXT DEFAULT '',
                attributes TEXT DEFAULT '{}',
                tags TEXT DEFAULT '{}',
                synced_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(credential_id, resource_type, resource_id)
            );
            CREATE TABLE IF NOT EXISTS cmdb_items (
                id TEXT PRIMARY KEY,
                project TEXT DEFAULT '默认项目',
                type TEXT DEFAULT 'service',
                name TEXT NOT NULL,
                owner TEXT DEFAULT '',
                env TEXT DEFAULT 'prod',
                attributes TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS cmdb_item_resource (
                item_id TEXT NOT NULL,
                resource_id INTEGER NOT NULL,
                PRIMARY KEY(item_id, resource_id)
            );
            CREATE TABLE IF NOT EXISTS deployments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                version TEXT,
                "commit" TEXT,
                author TEXT DEFAULT '',
                source TEXT DEFAULT 'manual',
                rollback INTEGER DEFAULT 0,
                deployed_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT DEFAULT 'internal',
                dedup_key TEXT,
                level TEXT DEFAULT 'medium',
                title TEXT NOT NULL,
                detail TEXT DEFAULT '',
                resource_ref TEXT,
                resource_id INTEGER,
                item_id TEXT,
                related_deployment_id INTEGER,
                status TEXT DEFAULT 'open',
                first_at TEXT DEFAULT (datetime('now','localtime')),
                last_at TEXT DEFAULT (datetime('now','localtime')),
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS rules (
                rule_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                level TEXT DEFAULT 'medium',
                enabled INTEGER DEFAULT 1
            );
            """
        )
        # 存量库轻量迁移：alert_events 补 resource_id 列
        cols = [r[1] for r in conn.execute("PRAGMA table_info(alert_events)").fetchall()]
        if "resource_id" not in cols:
            conn.execute("ALTER TABLE alert_events ADD COLUMN resource_id INTEGER")


def fetch_all(sql, params=()):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def fetch_one(sql, params=()):
    with get_conn() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql, params=()):
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def load_json(text, default=None):
    try:
        return json.loads(text) if text else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}
