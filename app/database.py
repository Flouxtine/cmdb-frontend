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
                assignee TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                first_at TEXT DEFAULT (datetime('now','localtime')),
                last_at TEXT DEFAULT (datetime('now','localtime')),
                resolved_at TEXT,
                escalated_at TEXT,
                escalate_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS rules (
                rule_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                level TEXT DEFAULT 'medium',
                enabled INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS metric_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                ts TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_metric_samples ON metric_samples(service, metric, ts);
            -- 告警表高频筛选/去重索引（列表按 status+level+source、upsert 按 dedup_key、统计按 status）
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alert_events(status);
            CREATE INDEX IF NOT EXISTS idx_alerts_level ON alert_events(level);
            CREATE INDEX IF NOT EXISTS idx_alerts_source ON alert_events(source);
            CREATE INDEX IF NOT EXISTS idx_alerts_dedup ON alert_events(dedup_key);
            CREATE TABLE IF NOT EXISTS auto_actions (
                action_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER,
                action_key TEXT,
                name TEXT,
                detail TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS silences (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                service TEXT DEFAULT '',
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                note TEXT DEFAULT '',
                cron TEXT DEFAULT '',
                duration_minutes INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            """
        )
        # 种子规则（幂等）：内部检测规则 + 合规基线规则（与 compliance.CHECKS 对应）
        conn.executemany(
            "INSERT OR IGNORE INTO rules(rule_key, name, level) VALUES(?,?,?)",
            [
                ("error_rate_spike", "错误率突增", "high"),
                ("latency_high", "平均延迟超标", "medium"),
                ("health_missing", "服务心跳中断", "high"),
                ("sg_public_high_risk_port", "安全组对全网开放高危端口", "high"),
                ("oss_public_access", "OSS Bucket 公共访问", "high"),
                ("disk_not_encrypted", "云盘未加密", "medium"),
            ],
        )
        # 种子自动处置动作（默认关闭，需手动开启）
        conn.executemany(
            "INSERT OR IGNORE INTO auto_actions(action_key, name, description, enabled) VALUES(?,?,?,0)",
            [
                ("auto_assign_bot", "自动认领（机器人）", "未认领告警自动分配给 🤖 auto-ops 并进入处理中", ),
                ("notify_webhook", "告警通知推送", "告警触发时推送 ALERT_WEBHOOK_URL（钉钉/飞书/自定义）", ),
                ("simulate_self_heal", "自愈-模拟重启服务", "演示：模拟重启故障服务并记录审计（不实际执行）", ),
            ],
        )
        # 存量库迁移：alert_events 补 resource_id / assignee / comment / escalated_at / escalate_count 列
        cols = [r[1] for r in conn.execute("PRAGMA table_info(alert_events)").fetchall()]
        for col, ddl in (("resource_id", "INTEGER"), ("assignee", "TEXT"), ("comment", "TEXT"),
                         ("escalated_at", "TEXT"), ("escalate_count", "INTEGER DEFAULT 0")):
            if col not in cols:
                conn.execute(f"ALTER TABLE alert_events ADD COLUMN {col} {ddl}")
        # 存量库迁移：silences 补 cron / duration_minutes 列
        scol = [r[1] for r in conn.execute("PRAGMA table_info(silences)").fetchall()]
        for col, ddl in (("cron", "TEXT DEFAULT ''"), ("duration_minutes", "INTEGER DEFAULT 0")):
            if col not in scol:
                conn.execute(f"ALTER TABLE silences ADD COLUMN {col} {ddl}")


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
