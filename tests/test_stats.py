"""处置工作台统计测试（告警负载聚合）"""
from tests.test_api import create_demo_cred


def _mk_alert(client, title, source="custom"):
    r = client.post("/api/webhooks/generic", json={"title": title, "level": "high", "source": source})
    return r.json()["id"]


def test_alert_stats_unassigned(client):
    _mk_alert(client, "告警A")
    _mk_alert(client, "告警B")
    s = client.get("/api/alerts/stats").json()
    assert s["open_count"] == 2
    assert s["unassigned_count"] == 2
    assert s["in_progress_count"] == 0
    assert s["by_assignee"] == []


def test_alert_stats_after_assign(client):
    a1 = _mk_alert(client, "告警A")
    a2 = _mk_alert(client, "告警B")
    client.post(f"/api/alerts/{a1}/assign", json={"assignee": "张三"})   # 张三 + 处理中
    s = client.get("/api/alerts/stats").json()
    assert s["open_count"] == 2
    assert s["unassigned_count"] == 1            # 告警B 未认领
    assert s["in_progress_count"] == 1           # 张三's 处理中
    assert [x for x in s["by_assignee"] if x["assignee"] == "张三"][0]["n"] == 1
    # 告警B 已解决 → open_count 降
    client.post(f"/api/alerts/{a2}/resolve")
    s = client.get("/api/alerts/stats").json()
    assert s["open_count"] == 1


def test_alerts_unassigned_filter(client):
    a1 = _mk_alert(client, "认领的告警")
    _mk_alert(client, "未认领的告警")
    client.post(f"/api/alerts/{a1}/assign", json={"assignee": "李四"})   # 认领后 status=in_progress
    # 只看未认领：认领的告警（in_progress）不应出现
    un = client.get("/api/alerts?unassigned=1").json()
    assert len(un) == 1 and un[0]["title"] == "未认领的告警"
    # 按认领人筛选：in_progress 也查得到（不看默认 status=open 过滤）
    assigned = client.get(f"/api/alerts?assignee=李四&status=").json()
    assert len(assigned) == 1 and assigned[0]["title"] == "认领的告警"


def test_alert_stats_sources_and_levels(client):
    _mk_alert(client, "外部告警", source="alertmanager")
    _mk_alert(client, "内部告警", source="internal")
    s = client.get("/api/alerts/stats").json()
    sources = {x["source"] for x in s["by_source"]}
    assert {"alertmanager", "internal"} <= sources
    assert s["open_count"] == 2