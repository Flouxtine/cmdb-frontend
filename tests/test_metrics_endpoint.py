"""Prometheus 指标输出测试"""
from tests.test_api import create_demo_cred

KNOWN_KEYS = [
    "ops_alert_open_total",
    "ops_alert_open_by_level",
    "ops_alert_open_by_source",
    "ops_resource_total",
    "ops_credential_total",
    "ops_cmdb_item_total",
    "ops_compliance_violation_open",
]


def test_metrics_endpoint_returns_prometheus_text(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    text = r.text
    # 暴露所有指标键
    for key in KNOWN_KEYS:
        assert key in text, f"缺少指标键 {key}"


def test_metrics_reflect_alert_and_resources(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")        # 12 资源
    client.post("/api/demo/alert")                      # 1 告警(未解决)
    text = client.get("/api/metrics").text
    # 告警总数应 >=1（open）
    import re
    m = re.search(r"ops_alert_open_total (\d+)", text)
    assert m and int(m.group(1)) >= 1
    # 资源按类型带 label
    assert 'ops_resource_total{type="ecs"} 4' in text


def test_metrics_after_resolve( client):
    client.post("/api/demo/alert")
    # 解决后告警总数降为 0
    aid = client.get("/api/alerts?status=open").json()[0]["id"]
    client.post(f"/api/alerts/{aid}/resolve")
    import re
    text = client.get("/api/metrics").text
    m = re.search(r"ops_alert_open_total (\d+)", text)
    assert m and int(m.group(1)) == 0