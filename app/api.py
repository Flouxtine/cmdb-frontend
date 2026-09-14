"""M1-M2 API：云账号 / 云资源归属 / 业务服务 / 发布上报 / 告警接收与分析 / 概览"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Optional

from . import alerts, ai, compliance, config
from . import actions
from . import database as db
from . import metrics, prom, security
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


class AlertAssignIn(BaseModel):
    assignee: str = Field(..., min_length=1, max_length=50)


class AlertCommentIn(BaseModel):
    comment: str = Field(..., min_length=1, max_length=500)


class SilenceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    service: str = ""
    starts_at: str
    ends_at: str
    note: str = ""


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
def list_alerts(level: str = "", status: str = "", source: str = "", service: str = "",
                assignee: str = "", unassigned: int = 0):
    """告警列表（处置协作筛选：assignee 按负责人、unassigned=1 只看未认领）"""
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
    if assignee:
        sql += " AND a.assignee=?"; params.append(assignee)
    if unassigned:
        sql += " AND (a.assignee IS NULL OR a.assignee='')"
    sql += (" ORDER BY CASE a.level WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
            "a.last_at DESC LIMIT 200")
    return db.fetch_all(sql, params)


@router.get("/alerts/stats")
def alert_stats():
    """处置工作台统计：未解决/处理中/未认领 + 按认领人/来源/级别分布"""
    open_rows = db.fetch_all("SELECT * FROM alert_events WHERE status IN ('open','in_progress')")
    open_count = len(open_rows)
    in_progress = sum(1 for a in open_rows if a["status"] == "in_progress")
    unassigned = sum(1 for a in open_rows if not (a["assignee"] or "").strip())

    by_assignee = {}
    by_source = {}
    by_level = {}
    for a in open_rows:
        who = (a["assignee"] or "").strip()
        if who:
            by_assignee[who] = by_assignee.get(who, 0) + 1
        by_source[a["source"]] = by_source.get(a["source"], 0) + 1
        by_level[a["level"]] = by_level.get(a["level"], 0) + 1

    return {
        "open_count": open_count,
        "in_progress_count": in_progress,
        "unassigned_count": unassigned,
        "by_assignee": [{"assignee": k, "n": v} for k, v in sorted(by_assignee.items(), key=lambda x: -x[1])],
        "by_source": [{"source": k, "n": v} for k, v in sorted(by_source.items(), key=lambda x: -x[1])],
        "by_level": [{"level": k, "n": v} for k, v in sorted(by_level.items(), key=lambda x: -x[1])],
    }


@router.get("/alerts/report")
def alert_report(days: int = 7):
    """处置统计报表：时间窗内产生/解决/平均解决时长 + 按认领人工作量 + 按天趋势"""
    days = min(max(days, 1), 90)
    with db.get_conn() as conn:
        # 时间窗内产生与解决
        produced = conn.execute(
            "SELECT COUNT(*) FROM alert_events WHERE datetime(first_at) >= datetime('now','localtime',?)",
            (f"-{days} days",)).fetchone()[0]
        resolved = conn.execute(
            "SELECT COUNT(*) FROM alert_events WHERE status='resolved' AND resolved_at IS NOT NULL "
            "AND datetime(resolved_at) >= datetime('now','localtime',?)",
            (f"-{days} days",)).fetchone()[0]
        # 平均解决时长（小时）
        avg_row = conn.execute(
            "SELECT AVG((julianday(resolved_at) - julianday(first_at)) * 24) AS h FROM alert_events "
            "WHERE status='resolved' AND resolved_at IS NOT NULL AND first_at IS NOT NULL "
            "AND datetime(resolved_at) >= datetime('now','localtime',?)",
            (f"-{days} days",)).fetchone()
        avg_hours = round(avg_row["h"], 2) if avg_row and avg_row["h"] is not None else None
        open_now = conn.execute(
            "SELECT COUNT(*) FROM alert_events WHERE status IN ('open','in_progress')").fetchone()[0]
        # 按认领人（时间窗内）
        by_assignee = [dict(r) for r in conn.execute(
            "SELECT COALESCE(NULLIF(assignee,''), '(未认领)') AS assignee, "
            "COUNT(*) AS total, "
            "SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved "
            "FROM alert_events WHERE datetime(first_at) >= datetime('now','localtime',?) "
            "GROUP BY COALESCE(NULLIF(assignee,''), '(未认领)') ORDER BY total DESC",
            (f"-{days} days",))]
        # 按天趋势（近 N 天：产生/解决）
        by_day_produced = [dict(r) for r in conn.execute(
            "SELECT substr(first_at,1,10) AS day, COUNT(*) AS n FROM alert_events "
            "WHERE datetime(first_at) >= datetime('now','localtime',?) GROUP BY substr(first_at,1,10) ORDER BY day",
            (f"-{days} days",))]
        by_day_resolved = [dict(r) for r in conn.execute(
            "SELECT substr(resolved_at,1,10) AS day, COUNT(*) AS n FROM alert_events "
            "WHERE status='resolved' AND resolved_at IS NOT NULL "
            "AND datetime(resolved_at) >= datetime('now','localtime',?) GROUP BY substr(resolved_at,1,10) ORDER BY day",
            (f"-{days} days",))]
        # 按来源
        by_source = [dict(r) for r in conn.execute(
            "SELECT source, COUNT(*) AS n FROM alert_events "
            "WHERE datetime(first_at) >= datetime('now','localtime',?) GROUP BY source ORDER BY n DESC",
            (f"-{days} days",))]
    return {
        "days": days,
        "produced": produced,
        "resolved": resolved,
        "open_now": open_now,
        "avg_resolve_hours": avg_hours,
        "by_assignee": by_assignee,
        "by_day": {"produced": by_day_produced, "resolved": by_day_resolved},
        "by_source": by_source,
    }


@router.post("/alerts/{aid}/resolve")
def resolve_alert(aid: int):
    db.execute("UPDATE alert_events SET status='resolved', resolved_at=datetime('now','localtime') WHERE id=? AND status='open'", (aid,))
    return {"ok": True}


@router.post("/alerts/{aid}/assign")
def assign_alert(aid: int, body: AlertAssignIn):
    """认领/转派告警：记录负责人并进入处理中状态"""
    if not db.fetch_one("SELECT id FROM alert_events WHERE id=?", (aid,)):
        raise HTTPException(404, "告警不存在")
    db.execute("UPDATE alert_events SET assignee=?, status='in_progress', last_at=datetime('now','localtime') WHERE id=?",
               (body.assignee, aid))
    return {"ok": True}


@router.post("/alerts/{aid}/comment")
def comment_alert(aid: int, body: AlertCommentIn):
    """追加处置备注（合并多条备注）"""
    if not db.fetch_one("SELECT id FROM alert_events WHERE id=?", (aid,)):
        raise HTTPException(404, "告警不存在")
    cur = db.fetch_one("SELECT comment FROM alert_events WHERE id=?", (aid,))
    old_comment = (cur["comment"] or "").strip()
    merged = f"{old_comment}\n[{service_now()} ] {body.comment}".strip() if old_comment else f"[{service_now()}] {body.comment}"
    db.execute("UPDATE alert_events SET comment=? WHERE id=?", (merged, aid))
    return {"ok": True}


def service_now():
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


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


# ---------------- 内部规则检测 / 演示故障剧本 ----------------
@router.post("/simulate/fault")
def simulate_fault():
    """模拟故障：demo-api 错误率/延迟升高 → 内部规则触发告警"""
    summary = metrics.simulate_fault()
    return {"ok": True, "message": "已模拟故障，内部规则即将产生告警", **summary}


@router.post("/simulate/recover")
def simulate_recover():
    """恢复：demo-api 指标回落 → 内部规则告警自动收敛"""
    summary = metrics.simulate_recover()
    return {"ok": True, "message": "已恢复，相关内部告警将收敛", **summary}


@router.get("/health/series")
def health_series(service: str, metric: str = "error_rate", limit: int = 120):
    """服务指标时间序列（内部规则检测数据，供前端绘图）"""
    return db.fetch_all(
        "SELECT value, ts FROM metric_samples WHERE service=? AND metric=? ORDER BY id DESC LIMIT ?",
        (service, metric, min(limit, 500)))[::-1]


# ---------------- 合规扫描中心 ----------------
@router.post("/credentials/{cid}/scan")
def scan_credential(cid: str):
    """对单个账号的云资源执行安全基线扫描（安全组高危端口/OSS 公共访问/磁盘未加密）"""
    try:
        return compliance.scan(cid)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/scan-all")
def scan_all():
    """扫描全部账号的安全基线，返回各账号扫描结果"""
    results = []
    for c in db.fetch_all("SELECT id, name FROM credentials"):
        r = compliance.scan(c["id"])
        r["credential_id"] = c["id"]
        r["credential_name"] = c["name"]
        results.append(r)
    return results


@router.post("/compliance/remediation")
def compliance_remediation(body: AiExplainIn):
    """为合规违规告警生成修复建议（内置模板 / LLM 增强）"""
    try:
        return compliance.remediation_for_alert(body.alert_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/compliance/summary")
def compliance_summary():
    """合规概览：资源总量/违规资源数/合规率 + 按规则、类型分布 + 违规明细"""
    return compliance.summary()


# ---------------- 告警静默 / 维护窗口 ----------------
@router.get("/silences")
def list_silences():
    """静默规则列表（带生效状态）"""
    rows = db.fetch_all("SELECT * FROM silences ORDER BY starts_at DESC")
    now = db.fetch_one("SELECT datetime('now','localtime') AS n")["n"]
    for r in rows:
        r["status"] = "active" if r["starts_at"] <= now <= r["ends_at"] else (
            "upcoming" if r["starts_at"] > now else "expired")
    return rows


@router.post("/silences")
def create_silence(body: SilenceIn):
    if body.starts_at >= body.ends_at:
        raise HTTPException(400, "结束时间必须晚于开始时间")
    sid = uuid.uuid4().hex
    db.execute("INSERT INTO silences(id, name, service, starts_at, ends_at, note) VALUES(?,?,?,?,?,?)",
               (sid, body.name, body.service, body.starts_at, body.ends_at, body.note))
    return {"id": sid}


@router.delete("/silences/{sid}")
def delete_silence(sid: str):
    if not db.fetch_one("SELECT id FROM silences WHERE id=?", (sid,)):
        raise HTTPException(404, "静默不存在")
    db.execute("DELETE FROM silences WHERE id=?", (sid,))
    return {"ok": True}


# ---------------- 自动处置 / 自愈规则 ----------------
@router.get("/auto-actions")
def list_auto_actions():
    """自愈规则列表（含启停状态）"""
    return db.fetch_all("SELECT * FROM auto_actions ORDER BY action_key")


@router.patch("/auto-actions/{action_key}")
def update_auto_action(action_key: str, body: RuleIn):
    if not db.fetch_one("SELECT action_key FROM auto_actions WHERE action_key=?", (action_key,)):
        raise HTTPException(404, "动作不存在")
    db.execute("UPDATE auto_actions SET enabled=? WHERE action_key=?", (1 if body.enabled else 0, action_key))
    return {"ok": True}


@router.get("/action-logs")
def list_action_logs(limit: int = 50):
    """自愈动作审计日志（最近 N 条）"""
    limit = min(max(limit, 1), 200)
    return db.fetch_all("SELECT * FROM action_logs ORDER BY id DESC LIMIT ?", (limit,))


@router.post("/actions/{action_key}/run/{alert_id}")
def run_action(action_key: str, alert_id: int):
    """手动触发自愈动作"""
    try:
        return actions.run_action_manually(action_key, alert_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------------- 处置协作 / 指标输出 ----------------
@router.get("/metrics")
def prometheus_metrics():
    """Prometheus 文本格式指标输出（外部监控可直接抓取，如 scrape 此 URL）"""
    body, content_type = prom.render()
    return Response(content=body, media_type=content_type)


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
