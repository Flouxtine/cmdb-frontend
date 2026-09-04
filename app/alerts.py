"""告警接收与归一化：Alertmanager / 通用 Webhook → alert_events 统一模型

处理流水线：接收 → 级别映射 → 资源匹配 CMDB → 去重(dedup_key) → 发布关联(30min) → 落库
状态机：open → resolved（收到恢复事件）/ expired（超时未恢复）
"""
import hashlib

from . import database as db

# 外部级别 → 内部三档
LEVEL_MAP = {
    "critical": "high", "error": "high", "fatal": "high", "page": "high", "emergency": "high",
    "warning": "medium", "warn": "medium",
    "info": "low", "notice": "low", "informational": "low",
}


def normalize_level(level):
    if not level:
        return "medium"
    lvl = str(level).lower()
    if lvl in ("high", "medium", "low"):   # 已是内部级别，直接透传
        return lvl
    return LEVEL_MAP.get(lvl, "medium")


def dedup_key(*parts):
    raw = "|".join(str(p) if p is not None else "" for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def match_resource(ref):
    """按 resource_ref 匹配 CMDB：优先资源ID精确，其次名称精确/模糊。
    返回 (resource_id, item_id)；item_id 为资源绑定的第一个业务服务。"""
    if not ref:
        return None, None
    res = db.fetch_one("SELECT id FROM resources WHERE resource_id=? LIMIT 1", (ref,))
    if not res:
        res = db.fetch_one("SELECT id FROM resources WHERE name=? LIMIT 1", (ref,))
    if not res:
        res = db.fetch_one("SELECT id FROM resources WHERE name LIKE ? LIMIT 1", (f"%{ref}%",))
    if not res:
        return None, None
    rid = res["id"]
    item = db.fetch_one("SELECT item_id FROM cmdb_item_resource WHERE resource_id=? LIMIT 1", (rid,))
    return rid, item["item_id"] if item else None


def correlate_deployment(service_name):
    """变更关联：同服务最近 30 分钟内的发布（M3 用于 AI 判断因果）"""
    if not service_name:
        return None
    dep = db.fetch_one(
        "SELECT id FROM deployments WHERE service=? AND rollback=0 "
        "AND datetime(deployed_at) >= datetime('now','localtime','-30 minutes') "
        "ORDER BY deployed_at DESC LIMIT 1", (service_name,))
    return dep["id"] if dep else None


def _service_name_of(item_id, rid):
    if item_id:
        it = db.fetch_one("SELECT name FROM cmdb_items WHERE id=?", (item_id,))
        if it:
            return it["name"]
    if rid:
        r = db.fetch_one("SELECT name FROM resources WHERE id=?", (rid,))
        if r:
            return r["name"]
    return None


def upsert_alert(payload):
    """归一化并落库。
    payload: {source, level, title, detail, resource_ref, status, dedup_key?}
    返回 {"action": created|deduped|resolved, ...}"""
    source = payload.get("source") or "custom"
    level = normalize_level(payload.get("level"))
    title = (payload.get("title") or "").strip()
    if not title:
        raise ValueError("告警缺少 title")
    detail = payload.get("detail") or ""
    resource_ref = payload.get("resource_ref") or ""
    status = str(payload.get("status") or "open").lower()

    rid, item_id = match_resource(resource_ref)
    service_name = _service_name_of(item_id, rid)
    key = payload.get("dedup_key") or dedup_key(source, title, resource_ref)

    if status in ("resolved", "ok", "recovered", "firing:resolved"):
        updated = db.execute(
            "UPDATE alert_events SET status='resolved', resolved_at=datetime('now','localtime') "
            "WHERE dedup_key=? AND status='open'", (key,))
        return {"action": "resolved", "updated": updated}

    # 去重：同 key 且有 open 告警 → 更新时间不新增
    exist = db.fetch_one("SELECT id FROM alert_events WHERE dedup_key=? AND status='open'", (key,))
    if exist:
        db.execute("UPDATE alert_events SET last_at=datetime('now','localtime'), detail=? WHERE id=?",
                   (detail, exist["id"]))
        return {"action": "deduped", "id": exist["id"]}

    dep_id = correlate_deployment(service_name) if service_name else None
    aid = db.execute(
        "INSERT INTO alert_events(source, dedup_key, level, title, detail, resource_ref, resource_id, item_id, related_deployment_id, status) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (source, key, level, title, detail, resource_ref, rid, item_id, dep_id, "open"))
    return {"action": "created", "id": aid, "item_id": item_id, "related_deployment_id": dep_id}


def expire_stale_events(hours=24):
    """超时未恢复的 open 告警 → expired"""
    return db.execute(
        "UPDATE alert_events SET status='expired' WHERE status='open' "
        "AND datetime(last_at) < datetime('now','localtime',?)", (f"-{hours} hours",))
