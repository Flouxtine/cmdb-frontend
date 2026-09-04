"""M2 告警接收与归一化测试"""
from tests.test_api import create_demo_cred, DEMO_CRED


def _setup_resource(client) -> str:
    """创建 demo 账号并同步，返回一个资源ID（i-demo-001）"""
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    rows = client.get("/api/resources?page_size=50").json()["items"]
    rid = [r["id"] for r in rows if r["resource_id"] == "i-demo-001"][0]
    return rid


def test_generic_webhook_create_and_match(client):
    _setup_resource(client)
    r = client.post("/api/webhooks/generic", json={
        "title": "CPU 超限", "level": "warning", "detail": "92%",
        "resource_ref": "i-demo-001", "source": "custom",
    })
    assert r.status_code == 200
    assert r.json()["action"] == "created"

    alerts = client.get("/api/alerts").json()
    assert len(alerts) == 1
    a = alerts[0]
    assert a["level"] == "medium"          # warning → medium 归一化
    assert a["source"] == "custom"
    assert a["resource_ref"] == "i-demo-001"
    assert a["credential_name"] == DEMO_CRED["name"]   # 归属账号可查


def test_generic_webhook_dedup(client):
    _setup_resource(client)
    payload = {"title": "内存告警", "level": "high", "resource_ref": "i-demo-001"}
    assert client.post("/api/webhooks/generic", json=payload).json()["action"] == "created"
    # 同 key 再次推送 → deduped，不新增
    assert client.post("/api/webhooks/generic", json=payload).json()["action"] == "deduped"
    assert len(client.get("/api/alerts").json()) == 1


def test_generic_webhook_resolve(client):
    _setup_resource(client)
    payload = {"title": "磁盘告警", "level": "low", "resource_ref": "i-demo-001"}
    client.post("/api/webhooks/generic", json=payload)
    assert client.get("/api/alerts?status=open").json()[0]["status"] == "open"
    # 推送恢复事件 → 自动收敛
    client.post("/api/webhooks/generic", json={**payload, "status": "resolved"})
    alerts = client.get("/api/alerts").json()
    assert alerts[0]["status"] == "resolved"


def test_alertmanager_webhook_parse(client):
    _setup_resource(client)
    body = {"alerts": [{
        "status": "firing",
        "labels": {"alertname": "InstanceDown", "severity": "critical", "instance": "i-demo-002"},
        "annotations": {"summary": "实例已宕机", "description": "probe_success 为 0"},
    }]}
    r = client.post("/api/webhooks/alertmanager", json=body)
    assert r.status_code == 200
    assert r.json()["received"] == 1

    alerts = client.get("/api/alerts").json()
    assert alerts[0]["source"] == "alertmanager"
    assert alerts[0]["title"] == "实例已宕机"
    assert alerts[0]["level"] == "high"     # critical → high


def test_alerts_filters_and_resolve(client):
    _setup_resource(client)
    client.post("/api/webhooks/generic", json={"title": "A", "level": "high", "resource_ref": "i-demo-001"})
    client.post("/api/webhooks/generic", json={"title": "B", "level": "low", "source": "custom2"})
    assert client.get("/api/alerts?level=high").json()[0]["title"] == "A"
    assert len(client.get("/api/alerts?source=custom2").json()) == 1

    aid = client.get("/api/alerts?status=open").json()[0]["id"]
    assert client.post(f"/api/alerts/{aid}/resolve").status_code == 200
    # 一条已解决，另一条仍为 open
    assert len(client.get("/api/alerts?status=open").json()) == 1


def test_alert_correlates_deployment(client):
    rid = _setup_resource(client)
    # 登记同服务发布（订单中心 30 分钟窗口内），再推告警 → 应关联
    iid = client.post("/api/cmdb/items", json={"project": "核心交易", "type": "service", "name": "订单中心"}).json()["id"]
    client.post(f"/api/cmdb/items/{iid}/link", json={"resource_id": rid})
    client.post("/api/deployments", json={"service": "订单中心", "version": "v2.3.0", "author": "ops"})

    client.post("/api/webhooks/generic", json={"title": "订单中心延迟", "level": "warning", "resource_ref": "i-demo-001"})
    alerts = client.get("/api/alerts").json()
    assert alerts[0]["related_deployment_id"] is not None
    assert alerts[0]["deploy_version"] == "v2.3.0"


def test_overview_alert_stats(client):
    _setup_resource(client)
    client.post("/api/demo/alert")
    ov = client.get("/api/overview").json()
    assert ov["open_alert_count"] == 1
    assert any(x["level"] == "medium" and x["n"] == 1 for x in ov["alert_by_level"])
