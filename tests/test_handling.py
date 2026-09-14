"""告警处置协作测试（认领/备注）"""
from tests.test_api import create_demo_cred


def _mk_alert(client, title="CPU 告警", resource_ref=""):
    r = client.post("/api/webhooks/generic", json={"title": title, "level": "high", "resource_ref": resource_ref})
    return r.json()["id"]


def test_assign_alert(client):
    aid = _mk_alert(client)
    # 认领 → 负责人 + 进入处理中
    r = client.post(f"/api/alerts/{aid}/assign", json={"assignee": "张三"})
    assert r.status_code == 200
    a = client.get("/api/alerts").json()[0]
    assert a["assignee"] == "张三"
    assert a["status"] == "in_progress"
    # 状态筛选可查到处理中
    assert len(client.get("/api/alerts?status=in_progress").json()) == 1


def test_comment_append(client):
    aid = _mk_alert(client)
    client.post(f"/api/alerts/{aid}/comment", json={"comment": "已重启实例"})
    client.post(f"/api/alerts/{aid}/comment", json={"comment": "观察 10 分钟后恢复"})
    a = client.get("/api/alerts").json()[0]
    # 备注为追加合并（两条都在，带时间戳）
    assert "已重启实例" in a["comment"]
    assert "观察 10 分钟后恢复" in a["comment"]
    assert a["comment"].count("[") >= 2   # 两条各带一个时间戳


def test_assign_comment_not_found(client):
    assert client.post("/api/alerts/99999/assign", json={"assignee": "x"}).status_code == 404
    assert client.post("/api/alerts/99999/comment", json={"comment": "x"}).status_code == 404
    assert client.post("/api/alerts/99999/assign", json={"assignee": ""}).status_code == 422
    assert client.post("/api/alerts/99999/comment", json={"comment": ""}).status_code == 422


def test_alert_list_contains_handling_fields(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    aid = _mk_alert(client, resource_ref="i-demo-001")
    client.post(f"/api/alerts/{aid}/assign", json={"assignee": "李四"})
    client.post(f"/api/alerts/{aid}/comment", json={"comment": "排查中"})
    a = client.get("/api/alerts").json()[0]
    # 告警归属账号仍可查（处置字段不破坏 JOIN）
    assert a["credential_name"] == "测试演示账号"
    assert a["assignee"] == "李四"
