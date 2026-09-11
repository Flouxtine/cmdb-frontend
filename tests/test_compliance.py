"""合规扫描中心测试"""
from tests.test_api import create_demo_cred


def _setup(client) -> str:
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    return cid


def test_scan_finds_violations(client):
    cid = _setup(client)
    r = client.post(f"/api/credentials/{cid}/scan")
    assert r.status_code == 200
    data = r.json()
    assert data["scanned"] == 12
    # demo 数据预期违规：2 安全组(22/3306 对全网) + 1 OSS(public-read) + 1 磁盘(未加密)
    assert data["violations"] == 4
    assert data["created"] == 4

    alerts = client.get("/api/alerts?source=compliance&status=open").json()
    assert len(alerts) == 4
    titles = {a["title"] for a in alerts}
    assert "安全组对全网开放高危端口" in titles
    assert "OSS Bucket 公共访问" in titles
    assert "云盘未加密" in titles
    assert all(a["credential_name"] == "测试演示账号" for a in alerts)


def test_scan_idempotent(client):
    cid = _setup(client)
    client.post(f"/api/credentials/{cid}/scan")
    # 重复扫描 → 不新增告警（去重）
    r2 = client.post(f"/api/credentials/{cid}/scan")
    assert r2.json()["created"] == 0
    assert len(client.get("/api/alerts?source=compliance&status=open").json()) == 4


def test_scan_all_and_summary(client):
    _setup(client)
    rs = client.post("/api/scan-all").json()
    assert sum(r["violations"] for r in rs) == 4

    s = client.get("/api/compliance/summary").json()
    assert s["resource_total"] == 12
    assert s["violation_resources"] == 4
    assert 60 <= s["compliance_rate"] <= 70  # 8/12 ≈ 66.7%
    rule_keys = {r["title"] for r in s["by_rule"]}
    assert "安全组对全网开放高危端口" in rule_keys
    assert sum(r["n"] for r in s["by_rule"]) == 4


def test_scan_missing_credential(client):
    r = client.post("/api/credentials/nonexistent/scan")
    assert r.status_code == 404
