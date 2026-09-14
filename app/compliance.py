"""合规基线检查：对已同步的云资源做安全基线扫描，违规项进入告警体系（source=compliance）

检查项（可扩展，新增一项只需在 CHECKS 注册）：
- 安全组：入方向对 0.0.0.0/0 开放高危端口
- OSS：Bucket ACL 允许公共读/读写
- 云盘：未开启加密
"""
import logging

from . import alerts, config
from . import database as db

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


# 检查注册表：新增检查项在此追加即可（remediation 为内置整改步骤模板）
CHECKS = [
    {"rule_key": "sg_public_high_risk_port", "resource_type": "security_group", "level": "high",
     "title": "安全组对全网开放高危端口", "fn": check_sg_public_high_risk_port,
     "remediation": [
         "登录云控制台 → 云服务器 ECS → 网络与安全 → 安全组，定位到该安全组",
         "进入入方向规则，找到对 0.0.0.0/0 开放的高危端口规则",
         "将授权对象 0.0.0.0/0 收窄为业务网段（如 10.0.0.0/8、办公网出口 IP）",
         "确需公网访问的端口仅保留 80/443 等必要端口，并开启安全组 5 元组限制",
         "删除冗余规则后，回到本平台「合规中心」重新扫描验证",
     ]},
    {"rule_key": "oss_public_access", "resource_type": "oss", "level": "high",
     "title": "OSS Bucket 公共访问", "fn": check_oss_public_access,
     "remediation": [
         "登录云控制台 → 对象存储 OSS → 对应 Bucket → 权限管理 → Bucket ACL",
         "将 ACL 由公共读/公共读写改为【私有（private）】",
         "检查 Bucket Policy 是否存在匿名主体（Principal:*）的 Statement，如有则移除",
         "确需公开访问的文件改用 CDN 分发或临时签名 URL（STS 授权）",
         "保存后回到本平台「合规中心」重新扫描验证",
     ]},
    {"rule_key": "disk_not_encrypted", "resource_type": "disk", "level": "medium",
     "title": "云盘未加密", "fn": check_disk_not_encrypted,
     "remediation": [
         "登录云控制台 → 云服务器 ECS → 云盘，定位到该未加密云盘",
         "数据盘：先创建快照备份，再执行『开启加密』（或通过复制到加密盘迁移）",
         "系统盘：新建实例时选择加密盘/KMS 加密，存量系统盘通过镜像重建迁移",
         "建议在 KMS 启用默认加密策略，后续新盘默认加密",
         "操作完成后回到本平台「合规中心」重新扫描验证",
     ]},
]

# rule_key -> 检查元数据（供 summary 聚合 / 修复建议）
CHECK_BY_KEY = {c["rule_key"]: c for c in CHECKS}
REMEDIATION_BY_KEY = {c["rule_key"]: c["remediation"] for c in CHECKS}

# 供数据库种子使用
RULE_SEEDS = [(c["rule_key"], c["title"], c["level"]) for c in CHECKS]


def _enabled_rule_keys():
    rows = db.fetch_all("SELECT rule_key, enabled FROM rules")
    return {r["rule_key"] for r in rows if r["enabled"]}


def _compliance_dedup_key(rule_key, resource_id):
    return alerts.dedup_key("compliance", rule_key, resource_id)


def remediation_for_alert(alert_id: int):
    """为具体合规违规告警生成修复建议。
    返回 {engine, rule_title, resource, account, detail, steps, llm_enhanced}
    engine: template（内置模板）/ llm（配了 LLM key）/ llm-fallback（LLM 失败回退模板）"""
    alert = db.fetch_one("SELECT * FROM alert_events WHERE id=?", (alert_id,))
    if not alert:
        raise ValueError("告警不存在")
    meta = next((c for c in CHECKS if c["title"] == alert["title"]), None)
    template = (meta or {}).get("remediation") or []

    # 资源与账号上下文
    resource_name, account = alert.get("resource_ref") or "", ""
    if alert.get("resource_id"):
        r = db.fetch_one(
            "SELECT r.name, c.name AS account FROM resources r "
            "LEFT JOIN credentials c ON c.id=r.credential_id WHERE r.id=?",
            (alert["resource_id"],))
        if r:
            resource_name = r["name"]
            account = r.get("account") or ""

    result = {
        "engine": "template",
        "rule_title": alert["title"],
        "resource": resource_name,
        "account": account,
        "detail": alert.get("detail") or "",
        "steps": template,
    }
    # LLM 增强（可选）
    if config.LLM_API_KEY:
        try:
            result["steps"] = _llm_remediation(alert, template, resource_name, account)
            result["engine"] = "llm"
        except Exception as e:
            logging.getLogger("opsscope.compliance").warning("修复建议 LLM 调用失败: %s", e)
            result["engine"] = "llm-fallback"
    return result


def _llm_remediation(alert, template, resource_name, account):
    import httpx
    prompt = (
        "你是云安全工程师。以下资源存在合规违规，请给出整改步骤（云控制台操作 + 可选 API/CLI），"
        "分步、可执行、注明影响面。\n\n"
        f"违规: {alert['title']}（{alert.get('detail') or ''}）\n"
        f"资源: {resource_name or '-'}（账号: {account or '-'}）\n"
        f"参考模板: {'；'.join(template) if template else '无'}"
    )
    resp = httpx.post(
        f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json={"model": config.LLM_MODEL, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.2, "max_tokens": 600},
        timeout=40)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return [s.strip() for s in content.split("\n") if s.strip()]


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
