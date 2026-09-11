"""合规基线检查：对已同步的云资源做安全基线扫描，违规项进入告警体系（source=compliance）

检查项（可扩展，新增一项只需在 CHECKS 注册）：
- 安全组：入方向对 0.0.0.0/0 开放高危端口
- OSS：Bucket ACL 允许公共读/读写
- 云盘：未开启加密
"""
import logging

from . import alerts, database as db

logger = logging.getLogger("opsscope.compliance")

# 高危端口（对 0.0.0.0/0 开放即视为风险）
HIGH_RISK_PORTS = {22, 3389, 3306, 5432, 6379, 9200, 27017, 11211}
PROTOCOLS_ALL = {"tcp", "udp", "all", "-1"}


def _port_hits(port_range, risk_ports):
    """解析阿里云 port_range（'22/22' / '1/65535' / '-1/-1'），返回命中的风险端口"""
    if not port_range or port_range in ("-1/-1", "all"):
        return sorted(risk_ports)
    try:
        start, _, end = port_range.partition("/")
        start, end = int(start), int(end or start)
        return sorted(p for p in risk_ports if start <= p <= end)
    except Exception:
        return []


def check_sg_public_high_risk_port(attributes):
    """安全组入方向对全网段开放高危端口"""
    hits = []
    for rule in (attributes.get("rules") or []):
        if rule.get("direction") not in (None, "ingress"):
            continue
        if (rule.get("source_cidr_ip") or "") != "0.0.0.0/0":
            continue
        if (rule.get("protocol") or "").lower() not in PROTOCOLS_ALL:
            continue
        ports = _port_hits(rule.get("port_range"), HIGH_RISK_PORTS)
        if ports:
            hits.append(f"{rule.get('protocol')}/{rule.get('port_range')} 对 0.0.0.0/0 开放 → 风险端口 {ports}")
    return (True, "") if not hits else (False, "；".join(hits))


def check_oss_public_access(attributes):
    """OSS Bucket 允许公共访问"""
    acl = (attributes.get("acl") or "").lower()
    if acl in ("public-read", "public-read-write"):
        return False, f"Bucket ACL 为 {acl}，允许公共访问"
    return True, ""


def check_disk_not_encrypted(attributes):
    """云盘未开启加密"""
    if not attributes.get("encrypted"):
        disk_type = attributes.get("disk_type", "数据")
        return False, f"{disk_type}盘未开启加密"
    return True, ""


# 检查注册表：新增检查项在此追加即可
CHECKS = [
    {"rule_key": "sg_public_high_risk_port", "resource_type": "security_group", "level": "high",
     "title": "安全组对全网开放高危端口", "fn": check_sg_public_high_risk_port},
    {"rule_key": "oss_public_access", "resource_type": "oss", "level": "high",
     "title": "OSS Bucket 公共访问", "fn": check_oss_public_access},
    {"rule_key": "disk_not_encrypted", "resource_type": "disk", "level": "medium",
     "title": "云盘未加密", "fn": check_disk_not_encrypted},
]

# rule_key -> 检查元数据（供 summary 聚合）
CHECK_BY_KEY = {c["rule_key"]: c for c in CHECKS}

# 供数据库种子使用
RULE_SEEDS = [(c["rule_key"], c["title"], c["level"]) for c in CHECKS]


def _enabled_rule_keys():
    rows = db.fetch_all("SELECT rule_key, enabled FROM rules")
    return {r["rule_key"] for r in rows if r["enabled"]}


def _compliance_dedup_key(rule_key, resource_id):
    return alerts.dedup_key("compliance", rule_key, resource_id)


def scan(credential_id=None):
    """扫描资源并产生/收敛合规告警。credential_id 为空则扫描全部资源。
    传入不存在的账号时抛 ValueError（由 API 转 404）。"""
    if credential_id and not db.fetch_one("SELECT id FROM credentials WHERE id=?", (credential_id,)):
        raise ValueError("账号不存在")
    sql = "SELECT * FROM resources"
    params = []
    if credential_id:
        sql += " WHERE credential_id=?"
        params.append(credential_id)
    resources = db.fetch_all(sql, params)

    enabled = _enabled_rule_keys()
    scanned = violations = created = resolved = 0

    for res in resources:
        attrs = db.load_json(res["attributes"], {})
        scanned += 1
        for check in CHECKS:
            if check["resource_type"] != res["resource_type"]:
                continue
            if check["rule_key"] not in enabled:
                continue
            key = _compliance_dedup_key(check["rule_key"], res["resource_id"])
            try:
                ok, detail = check["fn"](attrs)
            except Exception as e:  # 单条检查异常不影响整体扫描
                logger.warning("合规检查异常 %s/%s: %s", check["rule_key"], res["resource_id"], e)
                continue
            if ok:
                # 已合规：收敛历史违规告警
                resolved += alerts.resolve_by_dedup_key(key)
            else:
                violations += 1
                r = alerts.upsert_alert({
                    "source": "compliance",
                    "level": check["level"],
                    "title": check["title"],
                    "detail": f"{res['name']}：{detail}",
                    "resource_ref": res["resource_id"],
                    "status": "open",
                    "dedup_key": key,
                })
                created += 1 if r["action"] == "created" else 0

    return {"scanned": scanned, "violations": violations, "created": created, "resolved": resolved}


def summary():
    """合规概览：资源总量、违规资源数/告警数、合规率、按规则/类型分布、违规明细"""
    total = db.fetch_one("SELECT COUNT(*) AS n FROM resources")["n"]
    rows = db.fetch_all(
        "SELECT a.*, c.name AS credential_name FROM alert_events a "
        "LEFT JOIN resources r ON r.id = a.resource_id "
        "LEFT JOIN credentials c ON c.id = r.credential_id "
        "WHERE a.source='compliance' AND a.status='open' "
        "ORDER BY CASE a.level WHEN 'high' THEN 0 ELSE 1 END, a.last_at DESC")
    violation_count = len(rows)
    violation_resources = len({a["resource_ref"] for a in rows if a["resource_ref"]})

    # 告警不落 rule_key 列，按标题反查检查元数据（title 即规则名）
    title_to_meta = {c["title"]: c for c in CHECKS}
    by_rule_map = {}
    by_type_map = {}
    for a in rows:
        meta = title_to_meta.get(a["title"], {})
        title = a["title"]
        entry = by_rule_map.setdefault(title, {"title": title, "level": a["level"], "n": 0})
        entry["n"] += 1
        rtype = meta.get("resource_type", "unknown")
        by_type_map[rtype] = by_type_map.get(rtype, 0) + 1

    compliant = max(0, total - violation_resources)
    return {
        "resource_total": total,
        "violation_count": violation_count,
        "violation_resources": violation_resources,
        "compliant_count": compliant,
        "compliance_rate": round(compliant / total * 100, 1) if total else 100.0,
        "by_rule": sorted(by_rule_map.values(), key=lambda x: -x["n"]),
        "by_type_violation": [{"resource_type": k, "n": v}
                              for k, v in sorted(by_type_map.items(), key=lambda x: -x[1])],
        "violations": rows,
    }
