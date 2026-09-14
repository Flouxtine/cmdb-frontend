"""告警批量操作测试"""
import json


def _mk_alerts(client, n=3):
    ids = []
    for i in range(n):
        r = client.post("/api/webhooks/generic", json={"title": f"批量告警{i}", "level": "high"})
        ids.append(r.json()["id"])
    return ids


def test_batch_resolve(client):
    ids = _mk_alerts(client)
    r = client.post("/api/alerts/batch", json={"action": "resolve", "ids": ids})
    assert r.status_code == 200
    assert r.json()["affected"] == 3 and r.json()["not_found"] == 0
    assert client.get("/api/alerts?status=open").json() == []
    assert len(client.get("/api/alerts?status=resolved").json()) == 3


def test_batch_assign(client):
    ids = _mk_alerts(client, 2)
    r = client.post("/api/alerts/batch", json={"action": "assign", "ids": ids, "assignee": "张三"})
    assert r.json()["affected"] == 2
    alerts = client.get("/api/alerts?status=in_progress").json()
    assert len(alerts) == 2 and all(a["assignee"] == "张三" for a in alerts)


def test_batch_comment(client):
    ids = _mk_alerts(client, 2)
    r = client.post("/api/alerts/batch", json={"action": "comment", "ids": ids, "comment": "维护中"})
    assert r.json()["affected"] == 2
    for a in client.get("/api/alerts").json():
        assert "维护中" in (a["comment"] or "")


def test_batch_validation(client):
    ids = _mk_alerts(client, 1)
    assert client.post("/api/alerts/batch", json={"action": "nope", "ids": ids}).status_code == 400
    assert client.post("/api/alerts/batch", json={"action": "resolve", "ids": []}).status_code == 400
    assert client.post("/api/alerts/batch", json={"action": "assign", "ids": ids}).status_code == 400
    assert client.post("/api/alerts/batch", json={"action": "comment", "ids": ids}).status_code == 400


def test_batch_not_found_counted(client):
    ids = _mk_alerts(client, 2)
    r = client.post("/api/alerts/batch", json={"action": "resolve", "ids": ids + [999999]})
    assert r.status_code == 200
    assert r.json()["affected"] == 2 and r.json()["not_found"] == 1
