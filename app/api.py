"""M1 API：云账号管理 + 云资源归属 CMDB + 业务服务关联 + 发布上报 + 概览"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional

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
    sql = ("SELECT r.*, c.name AS credential_name, c.provider FROM resources r "
           "LEFT JOIN credentials c ON c.id=r.credential_id WHERE 1=1")
    params = []
    if credential_id:
        sql += " AND r.credential_id=?"; params.append(credential_id)
    if resource_type:
        sql += " AND r.resource_type=?"; params.append(resource_type)
    if keyword:
        sql += " AND (r.name LIKE ? OR r.resource_id LIKE ?)"; params += [f"%{keyword}%", f"%{keyword}%"]
    sql += " ORDER BY r.resource_type, r.name"
    rows = db.fetch_all(sql, params)
    total = len(rows)
    start = (page - 1) * page_size
    items = [_resource_row(r) for r in rows[start:start + page_size]]
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


# ---------------- 概览 ----------------
@router.get("/overview")
def overview():
    with db.get_conn() as conn:
        cred_total = conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
        res_total = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
        item_total = conn.execute("SELECT COUNT(*) FROM cmdb_items").fetchone()[0]
        by_type = [dict(r) for r in conn.execute(
            "SELECT resource_type, COUNT(*) n FROM resources GROUP BY resource_type")]
        by_account = [dict(r) for r in conn.execute(
            "SELECT r.credential_id, c.name, c.provider, COUNT(*) n FROM resources r LEFT JOIN credentials c ON c.id=r.credential_id GROUP BY r.credential_id")]
        by_project = [dict(r) for r in conn.execute(
            "SELECT project, COUNT(*) n FROM cmdb_items GROUP BY project")]
        unlinked = conn.execute(
            "SELECT COUNT(*) FROM resources r WHERE NOT EXISTS (SELECT 1 FROM cmdb_item_resource ir WHERE ir.resource_id=r.id)").fetchone()[0]
    return {"credential_count": cred_total, "resource_count": res_total, "cmdb_item_count": item_total,
            "resource_by_type": by_type, "resource_by_account": by_account,
            "cmdb_by_project": by_project, "unlinked_resource_count": unlinked,
            "resource_types": RESOURCE_TYPES}
