"""M1-M2 API：云账号 / 云资源归属 / 业务服务 / 发布上报 / 告警接收与分析 / 概览"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field
from typing import List, Optional

from . import alerts, ai, config
from . import database as db
from . import security
from .providers import registry, get_provider

router = APIRouter(prefix="/api")


class CredentialIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str
    access_key: str = ""
    secret_key: str = ""
    regions: List[str] = []
    remark: str = ""


class CmdbItemIn(BaseModel):
    project: str = "默认项目"
    type: str = "service"
    name: str = Field(..., min_length=1)
    owner: str = ""
    env: str = "prod"
    attributes: Optional[dict] = None


class CmdbLinkIn(BaseModel):
    resource_id: int


class DeploymentIn(BaseModel):
    service: str = Field(..., min_length=1)
    version: str = ""
    commit: str = ""
    author: str = ""
    source: str = "manual"
    rollback: bool = False


class GenericWebhookIn(BaseModel):
    title: str = Field(..., min_length=1)
    level: str = "medium"
    detail: str = ""
    resource_ref: str = ""
    status: str = "open"
    source: str = "custom"
    dedup_key: Optional[str] = None


class RuleIn(BaseModel):
    enabled: bool


class AiExplainIn(BaseModel):
    alert_id: int


def _check_webhook_token(request: Request):
    """Webhook 鉴权：配置了 WEBHOOK_TOKEN 则要求 X-Ops-Scope-Token 匹配"""
    if config.WEBHOOK_TOKEN and request.headers.get("X-Ops-Scope-Token") != config.WEBHOOK_TOKEN:
        raise HTTPException(401, "无效的 Webhook 令牌")


def _decrypted(c):
    c = dict(c)
    c["access_key"] = security.decrypt(c.get("access_key") or "")
    c["secret_key"] = security.decrypt(c.get("secret_key") or "")
    return c


def _public(c):
    c = dict(c)
    c["access_key"] = "******" if c.get("access_key") else ""
    c["secret_key"] = "******" if c.get("secret_key") else ""
    c["regions"] = db.load_json(c.get("regions"), []) or []
    return c


def _resource_row(r):
    return dict(r) | {"attributes": db.load_json(r["attributes"], {}), "tags": db.load_json(r["tags"], {})}


# ---------------- 厂商 / 账号 ----------------
@router.get("/providers")
def providers():
    return registry.list_provider_meta()


@router.get("/credentials")
def list_credentials():
    rows = db.fetch_all(
        "SELECT c.*, (SELECT COUNT(*) FROM resources r WHERE r.credential_id=c.id) AS resource_count "
        "FROM credentials c ORDER BY c.created_at DESC")
    return [_public(r) for r in rows]


@router.post("/credentials")
def create_credential(body: CredentialIn):
    if body.provider not in registry.REGISTRY:
        raise HTTPException(400, f"不支持的厂商: {body.provider}")
    cid = uuid.uuid4().hex
    db.execute(
        "INSERT INTO credentials(id, name, provider, access_key, secret_key, regions, remark) VALUES(?,?,?,?,?,?,?)",
        (cid, body.name, body.provider, security.encrypt(body.access_key), security.encrypt(body.secret_key),
         json.dumps(body.regions), body.remark))
    return {"id": cid}


@router.delete("/credentials/{cid}")
def delete_credential(cid: str):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM resources WHERE credential_id=?", (cid,))
        conn.execute("DELETE FROM credentials WHERE id=?", (cid,))
    return {"ok": True}


@router.post("/credentials/{cid}/test")
def test_credential(cid: str):
    cred = db.fetch_one("SELECT * FROM credentials WHERE id=?", (cid,))
    if not cred:
        raise HTTPException(404, "账号不存在")
    try:
        ok, msg = get_provider(_decrypted(cred)).test_connection()
    except Exception as e:
        ok, msg = False, str(e)
    db.execute("UPDATE credentials SET status=?, last_error=? WHERE id=?",
               ("ok" if ok else "fail", "" if ok else msg, cid))
    return {"ok": ok, "message": msg}


@router.post("/credentials/{cid}/sync")
def sync_credential(cid: str):
    cred = db.fetch_one("SELECT * FROM credentials WHERE id=?", (cid,))
    if not cred:
        raise HTTPException(404, "账号不存在")
    try:
        result = get_provider(_decrypted(cred)).list_resources()
        resources, errors = result if isinstance(result, tuple) else (result, [])
    except Exception as e:
        raise HTTPException(500, f"同步失败: {e}")
    stats = _upsert(cid, cred["provider"], resources)
    db.execute("UPDATE credentials SET status='ok', last_sync_at=datetime('now','localtime') WHERE id=?", (cid,))
    return {**stats, "errors": errors[:10]}


def _upsert(cid, provider, resources):
    with db.get_conn() as conn:
        seen = []
        for r in resources:
            seen.append((r["resource_type"], r["resource_id"]))
            conn.execute(
                """INSERT INTO resources(credential_id, provider, resource_type, resource_id, name, region, attributes, tags, synced_at)
                   VALUES(?,?,?,?,?,?,?,?,datetime('now','localtime'))
                   ON CONFLICT(credential_id, resource_type, resource_id)
                   DO UPDATE SET name=excluded.name, region=excluded.region, attributes=excluded.attributes,
                                 tags=excluded.tags, synced_at=datetime('now','localtime')""",
                (cid, provider, r["resource_type"], r["resource_id"], r.get("name") or r["resource_id"],
                 r.get("region") or "", json.dumps(r.get("attributes", {}), ensure_ascii=False),
                 json.dumps(r.get("tags", {}), ensure_ascii=False)))
        if seen:
            ph = ",".join("(?,?)" for _ in seen)
            conn.execute(
                f"DELETE FROM resources WHERE credential_id=? AND provider=? AND NOT ((resource_type, resource_id) IN ({ph}))",
                [cid, provider] + [x for pair in seen for x in pair])
        else:
            conn.execute("DELETE FROM resources WHERE credential_id=? AND provider=?", (cid, provider))
        total = conn.execute("SELECT COUNT(*) FROM resources WHERE credential_id=?", (cid,)).fetchone()[0]
    return {"synced": len(resources), "total": total}


# ---------------- 云资源 CMDB（归属可查）----------------
RESOURCE_TYPES = {"ecs": "云服务器", "disk": "云盘", "security_group": "安全组", "oss": "对象存储"}


@router.get("/resources")
def list_resources(credential_id: str = "", resource_type: str = "", keyword: str = "",
                   page: int = 1, page_size: int = 30):
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    where, params = ["1=1"], []
    if credential_id:
        where.append("r.credential_id=?"); params.append(credential_id)
    if resource_type:
        where.append("r.resource_type=?"); params.append(resource_type)
    if keyword:
        where.append("(r.name LIKE ? OR r.resource_id LIKE ?)"); params += [f"%{keyword}%", f"%{keyword}%"]
    cond = " AND ".join(where)

    with db.get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM resources r WHERE {cond}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT r.*, c.name AS credential_name, c.provider FROM resources r "
            f"LEFT JOIN credentials c ON c.id=r.credential_id WHERE {cond} "
            f"ORDER BY r.resource_type, r.name LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size]).fetchall()
    items = [_resource_row(r) for r in rows]
    return {"total": total, "page": page, "items": items, "resource_types": RESOURCE_TYPES}


@router.get("/resources/{rid}")
def resource_detail(rid: int):
    r = db.fetch_one(
        "SELECT r.*, c.name AS credential_name, c.provider FROM resources r LEFT JOIN credentials c ON c.id=r.credential_id WHERE r.id=?",
        (rid,))
    if not r:
        raise HTTPException(404, "资源不存在")
    data = _resource_row(r)
    items = db.fetch_all(
        "SELECT i.id, i.project, i.type, i.name, i.owner, i.env FROM cmdb_item_resource ir "
        "JOIN cmdb_items i ON i.id=ir.item_id WHERE ir.resource_id=?", (rid,))
    data["linked_items"] = items
    return data


# ---------------- 业务 CMDB（服务/应用）----------------
@router.get("/cmdb/items")
def list_cmdb_items(project: str = "", type: str = "", keyword: str = ""):
    sql = ("SELECT i.*, (SELECT COUNT(*) FROM cmdb_item_resource ir WHERE ir.item_id=i.id) AS resource_count "
           "FROM cmdb_items i WHERE 1=1")
    params = []
    if project:
        sql += " AND i.project=?"; params.append(project)
    if type:
        sql += " AND i.type=?"; params.append(type)
    if keyword:
        sql += " AND i.name LIKE ?"; params.append(f"%{keyword}%")
    sql += " ORDER BY i.project, i.name"
    return [dict(r) | {"attributes": db.load_json(r["attributes"], {})} for r in db.fetch_all(sql, params)]


@router.get("/cmdb/projects")
def cmdb_projects():
    rows = db.fetch_all("SELECT DISTINCT project FROM cmdb_items ORDER BY project")
    return [r["project"] for r in rows]


@router.post("/cmdb/items")
def create_cmdb_item(body: CmdbItemIn):
    iid = uuid.uuid4().hex
    db.execute("INSERT INTO cmdb_items(id, project, type, name, owner, env, attributes) VALUES(?,?,?,?,?,?,?)",
               (iid, body.project, body.type, body.name, body.owner, body.env,
                json.dumps(body.attributes or {}, ensure_ascii=False)))
    return {"id": iid}


@router.delete("/cmdb/items/{iid}")
def delete_cmdb_item(iid: str):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM cmdb_item_resource WHERE item_id=?", (iid,))
        conn.execute("DELETE FROM cmdb_items WHERE id=?", (iid,))
    return {"ok": True}


@router.get("/cmdb/items/{iid}")
def cmdb_item_detail(iid: str):
    item = db.fetch_one("SELECT * FROM cmdb_items WHERE id=?", (iid,))
    if not item:
        raise HTTPException(404, "业务服务不存在")
    data = dict(item) | {"attributes": db.load_json(item["attributes"], {})}
    res = db.fetch_all(
        "SELECT r.id, r.resource_type, r.resource_id, r.name, r.region, r.attributes, r.tags, c.name AS credential_name, c.provider "
        "FROM cmdb_item_resource ir JOIN resources r ON r.id=ir.resource_id "
        "LEFT JOIN credentials c ON c.id=r.credential_id WHERE ir.item_id=? ORDER BY r.resource_type", (iid,))
    data["resources"] = [_resource_row(r) for r in res]
    return data


@router.post("/cmdb/items/{iid}/link")
def link_resource(iid: str, body: CmdbLinkIn):
    if not db.fetch_one("SELECT id FROM cmdb_items WHERE id=?", (iid,)):
        raise HTTPException(404, "业务服务不存在")
    if not db.fetch_one("SELECT id FROM resources WHERE id=?", (body.resource_id,)):
        raise HTTPException(404, "资源不存在")
    db.execute("INSERT OR IGNORE INTO cmdb_item_resource(item_id, resource_id) VALUES(?,?)", (iid, body.resource_id))
    return {"ok": True}


@router.delete("/cmdb/items/{iid}/link/{rid}")
def unlink_resource(iid: str, rid: int):
    db.execute("DELETE FROM cmdb_item_resource WHERE item_id=? AND resource_id=?", (iid, rid))
    return {"ok": True}


# ---------------- 发布上报（CI/CLI/手动，M3 变更关联数据源）----------------
@router.get("/deployments")
def list_deployments(service: str = ""):
    if service:
        return db.fetch_all("SELECT * FROM deployments WHERE service=? ORDER BY deployed_at DESC LIMIT 100", (service,))
    return db.fetch_all("SELECT * FROM deployments ORDER BY deployed_at DESC LIMIT 100")


@router.post("/deployments")
def create_deployment(body: DeploymentIn):
    db.execute(
        'INSERT INTO deployments(service, version, "commit", author, source, rollback) VALUES(?,?,?,?,?,?)',
        (body.service, body.version, body.commit, body.author, body.source, 1 if body.rollback else 0))
    return {"ok": True}


# ---------------- 告警接收（M2）----------------
@router.post("/webhooks/alertmanager")
async def webhook_alertmanager(request: Request, body: dict = Body(...)):
    """Prometheus Alertmanager 标准 webhook 格式接入"""
    _check_webhook_token(request)
    results = []
    for a in body.get("alerts", []):
        labels = a.get("labels") or {}
        annotations = a.get("annotations") or {}
        status = "resolved" if a.get("status") == "resolved" else "open"
        key = alerts.dedup_key("alertmanager", labels.get("alertname"), labels.get("instance") or labels.get("resource_id"))
        results.append(alerts.upsert_alert({
            "source": "alertmanager",
            "level": labels.get("severity", "warning"),
            "title": annotations.get("summary") or labels.get("alertname") or "Alertmanager 告警",
            "detail": annotations.get("description") or "",
            "resource_ref": labels.get("resource_id") or labels.get("instance") or "",
            "status": status,
            "dedup_key": key,
        }))
    return {"received": len(body.get("alerts", [])), "results": results}


@router.post("/webhooks/generic")
async def webhook_generic(request: Request, body: GenericWebhookIn):
    """通用 Webhook：任意系统 POST {title, level, resource_ref, detail, status, source}"""
    _check_webhook_token(request)
    return alerts.upsert_alert(body.model_dump())


@router.get("/alerts")
def list_alerts(level: str = "", status: str = "", source: str = "", service: str = ""):
    # 过期扫描：超时未恢复的 open 告警 → expired（状态机完整性）
    alerts.expire_stale_events()
    sql = ("SELECT a.*, d.version AS deploy_version, c.name AS credential_name, i.name AS item_name "
           "FROM alert_events a "
           "LEFT JOIN deployments d ON d.id=a.related_deployment_id "
           "LEFT JOIN cmdb_items i ON i.id=a.item_id "
           "LEFT JOIN resources r ON r.id=a.resource_id "
           "LEFT JOIN credentials c ON c.id=r.credential_id WHERE 1=1")
    params = []
    if level:
        sql += " AND a.level=?"; params.append(level)
    if status:
        sql += " AND a.status=?"; params.append(status)
    if source:
        sql += " AND a.source=?"; params.append(source)
    if service:
        sql += " AND (i.name=? OR r.name=?)"; params += [service, service]
    sql += (" ORDER BY CASE a.level WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
            "a.last_at DESC LIMIT 200")
    return db.fetch_all(sql, params)


@router.post("/alerts/{aid}/resolve")
def resolve_alert(aid: int):
    db.execute("UPDATE alert_events SET status='resolved', resolved_at=datetime('now','localtime') WHERE id=? AND status='open'", (aid,))
    return {"ok": True}


@router.get("/rules")
def list_rules():
    return db.fetch_all("SELECT * FROM rules ORDER BY level DESC, rule_key")


@router.patch("/rules/{rule_key}")
def update_rule(rule_key: str, body: RuleIn):
    if not db.fetch_one("SELECT rule_key FROM rules WHERE rule_key=?", (rule_key,)):
        raise HTTPException(404, "规则不存在")
    db.execute("UPDATE rules SET enabled=? WHERE rule_key=?", (1 if body.enabled else 0, rule_key))
    return {"ok": True}


@router.post("/demo/alert")
def demo_alert():
    """演示：模拟外部系统推入一条告警（走通用 webhook 同款流水线）"""
    return alerts.upsert_alert({
        "source": "custom",
        "level": "warning",
        "title": "CPU 使用率超阈值",
        "detail": "演示告警：demo-api 实例 CPU 使用率 92% 持续 10 分钟（模拟外部监控推送）",
        "resource_ref": "i-demo-001",
        "status": "open",
    })


# ---------------- AI 排障分析（M3）----------------
@router.post("/ai/explain")
async def ai_explain(body: AiExplainIn):
    try:
        return await ai.explain_alert(body.alert_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------------- 概览 ----------------
@router.get("/overview")
def overview():
    with db.get_conn() as conn:
        cred_total = conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
        res_total = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
        item_total = conn.execute("SELECT COUNT(*) FROM cmdb_items").fetchone()[0]
        alert_open = conn.execute("SELECT COUNT(*) FROM alert_events WHERE status='open'").fetchone()[0]
        by_type = [dict(r) for r in conn.execute(
            "SELECT resource_type, COUNT(*) n FROM resources GROUP BY resource_type")]
        by_account = [dict(r) for r in conn.execute(
            "SELECT r.credential_id, c.name, c.provider, COUNT(*) n FROM resources r LEFT JOIN credentials c ON c.id=r.credential_id GROUP BY r.credential_id")]
        by_project = [dict(r) for r in conn.execute(
            "SELECT project, COUNT(*) n FROM cmdb_items GROUP BY project")]
        alert_by_level = [dict(r) for r in conn.execute(
            "SELECT level, COUNT(*) n FROM alert_events WHERE status='open' GROUP BY level")]
        unlinked = conn.execute(
            "SELECT COUNT(*) FROM resources r WHERE NOT EXISTS (SELECT 1 FROM cmdb_item_resource ir WHERE ir.resource_id=r.id)").fetchone()[0]
    return {"credential_count": cred_total, "resource_count": res_total, "cmdb_item_count": item_total,
            "open_alert_count": alert_open, "alert_by_level": alert_by_level,
            "resource_by_type": by_type, "resource_by_account": by_account,
            "cmdb_by_project": by_project, "unlinked_resource_count": unlinked,
            "resource_types": RESOURCE_TYPES}
