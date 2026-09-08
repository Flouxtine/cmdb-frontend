"""M3 AI 排障分析测试"""
from tests.test_api import create_demo_cred


def _mk_alert(client, title="CPU 使用率超阈值", resource_ref="i-demo-001", level="warning"):
    r = client.post("/api/webhooks/generic", json={
        "title": title, "level": level, "resource_ref": resource_ref, "source": "custom",
    })
    return r.json()["id"]


def test_ai_explain_not_found(client):
    r = client.post("/api/ai/explain", json={"alert_id": 99999})
    assert r.status_code == 404


def test_ai_explain_heuristic_with_account(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    aid = _mk_alert(client)
    r = client.post("/api/ai/explain", json={"alert_id": aid})
    assert r.status_code == 200
    data = r.json()
    assert data["engine"] in ("heuristic", "llm-fallback")   # 测试环境无 LLM key → 规则回退
    assert "CPU" in data["analysis"]                          # 关键字启发式命中
    assert "所属账号" in data["context"] and "测试演示账号" in data["context"]
    assert data["alert"]["id"] == aid


def test_ai_explain_context_marks_related_deployment(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    # 绑定"告警将匹配到的资源"（i-demo-001）到业务服务 → 服务名"订单中心"，登记发布 → 告警自动关联
    rid = [r["id"] for r in client.get("/api/resources?page_size=50").json()["items"] if r["resource_id"] == "i-demo-001"][0]
    iid = client.post("/api/cmdb/items", json={"project": "核心交易", "type": "service", "name": "订单中心"}).json()["id"]
    client.post(f"/api/cmdb/items/{iid}/link", json={"resource_id": rid})
    client.post("/api/deployments", json={"service": "订单中心", "version": "v2.3.0", "author": "ops"})
    aid = _mk_alert(client, title="订单中心延迟升高", resource_ref="i-demo-001")
    r = client.post("/api/ai/explain", json={"alert_id": aid})
    data = r.json()
    assert "疑似关联本次发布" in data["context"]
    assert "v2.3.0" in data["context"]
    assert data["alert"]["related_deployment_id"] is not None


def test_rules_seeded(client):
    rules = client.get("/api/rules").json()
    keys = {r["rule_key"] for r in rules}
    assert {"error_rate_spike", "latency_high", "health_missing"} <= keys
    assert client.patch("/api/rules/error_rate_spike", json={"enabled": False}).status_code == 200
    rules = client.get("/api/rules").json()
    assert [r for r in rules if r["rule_key"] == "error_rate_spike"][0]["enabled"] == 0
