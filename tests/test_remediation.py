"""合规修复建议测试"""
from tests.test_api import create_demo_cred


def _setup_violation(client) -> int:
    """创建 demo 账号并同步、扫描，返回第一条违规告警 ID（安全组高危端口）"""
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    client.post(f"/api/credentials/{cid}/scan")
    alerts = client.get("/api/alerts?source=compliance&status=open").json()
    assert len(alerts) >= 1
    return alerts[0]["id"]


def test_remediation_template(client):
    aid = _setup_violation(client)
    r = client.post("/api/compliance/remediation", json={"alert_id": aid})
    assert r.status_code == 200
    d = r.json()
    assert d["engine"] == "template"          # 测试环境无 LLM key
    assert len(d["steps"]) >= 3               # 内置模板分步
    assert any("安全组" in s or "控制台" in s for s in d["steps"])
    assert d["resource"]                       # 违规对象资源名
    assert d["account"] == "测试演示账号"      # 账号上下文可查


def test_remediation_not_found(client):
    assert client.post("/api/compliance/remediation", json={"alert_id": 99999}).status_code == 404


def test_remediation_rule_specific(client):
    """不同规则给不同模板（磁盘未加密的步骤应含快照/加密关键词）"""
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    client.post(f"/api/credentials/{cid}/scan")
    alerts = client.get("/api/alerts?source=compliance&status=open").json()
    disk_alert = next(a for a in alerts if a["title"] == "云盘未加密")
    d = client.post("/api/compliance/remediation", json={"alert_id": disk_alert["id"]}).json()
    assert d["rule_title"] == "云盘未加密"
    assert any("快照" in s or "加密" in s for s in d["steps"])
