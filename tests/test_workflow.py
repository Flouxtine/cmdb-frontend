"""告警认领/处置流程测试（M6）"""
from tests.test_api import create_demo_cred


def _mk_alert(client, title="CPU 超限", resource_ref="i-demo-001"):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    r = client.post("/api/webhooks/generic", json={"title": title, "level": "high", "resource_ref": resource_ref})
    return r.json()["id"]


def test_assign_flow(client):
    aid = _mk_alert(client)
    # 认领 → 负责人 + 状态进入处理中
    r = client.post(f"/api/alerts/{aid}/assign", json={"assignee": "张三"})
    assert r.status_code == 200
    a = client.get("/api/alerts").json()[0]
    assert a["assignee"] == "张三"
    assert a["status"] == "in_progress"
    # 处理中筛选可见
    assert len(client.get("/api/alerts?status=in_progress").json()) == 1


def test_comment_and_resolve(client):
    aid = _mk_alert(client)
    assert client.post(f"/api/alerts/{aid}/comment", json={"comment": "已扩容处理"}).status_code == 200
    a = client.get("/api/alerts").json()[0]
    assert a["comment"] == "已扩容处理"

    assert client.post(f"/api/alerts/{aid}/status", json={"comment": "resolved"}).status_code == 200
    a = client.get("/api/alerts").json()[0]
    assert a["status"] == "resolved" and a["resolved_at"] is not None


def test_status_flow_back_to_open(client):
    aid = _mk_alert(client)
    client.post(f"/api/alerts/{aid}/assign", json={"assignee": "李四"})
    # 重新打开（in_progress → open）
    assert client.post(f"/api/alerts/{aid}/status", json={"comment": "open"}).status_code == 200
    assert client.get("/api/alerts").json()[0]["status"] == "open"


def test_alert_not_found(client):
    assert client.post("/api/alerts/999999/assign", json={"assignee": "x"}).status_code == 404
    assert client.post("/api/alerts/999999/comment", json={"comment": "x"}).status_code == 404
