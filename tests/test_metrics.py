"""内部规则检测引擎 + 告警通知测试"""
import json


def test_metrics_fault_creates_internal_alerts(client):
    # 初始无告警
    assert client.get("/api/alerts?source=internal").json() == []

    # 模拟故障：错误率/延迟升高 → 内部规则触发
    r = client.post("/api/simulate/fault")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["created"] >= 1

    alerts = client.get("/api/alerts?source=internal&status=open").json()
    assert len(alerts) >= 1
    titles = {a["title"] for a in alerts}
    assert any("错误率突增" in t for t in titles)
    assert all(a["source"] == "internal" for a in alerts)


def test_metrics_recover_resolves_alerts(client):
    client.post("/api/simulate/fault")
    open_before = len(client.get("/api/alerts?source=internal&status=open").json())
    assert open_before >= 1

    # 恢复 → 内部告警自动收敛
    r = client.post("/api/simulate/recover")
    assert r.json()["resolved"] >= 1
    # 恢复后再次检测不应新增
    remaining = client.get("/api/alerts?source=internal&status=open").json()
    assert all("错误率突增" not in a["title"] and "延迟超标" not in a["title"] for a in remaining)


def test_internal_alert_dedup_by_rule(client):
    client.post("/api/simulate/fault")
    client.post("/api/simulate/fault")   # 同规则重复触发 → 去重不新增
    count = len(client.get("/api/alerts?source=internal&status=open").json())
    # 错误率 + 延迟 两条规则，重复触发不应翻倍
    assert count <= 2


def test_health_series(client):
    client.post("/api/simulate/fault")
    series = client.get("/api/health/series?service=demo-api&metric=error_rate&limit=10").json()
    assert len(series) >= 1
    assert "value" in series[0] and "ts" in series[0]
    # 支持多指标：latency 序列应存在且为数值
    lat = client.get("/api/health/series?service=demo-api&metric=latency&limit=5").json()
    assert len(lat) >= 1 and isinstance(lat[0]["value"], (int, float))


def test_alertmanager_webhook_payload(client):
    """webhook 接收的告警应带来源与资源归属（回归保护）"""
    client.post("/api/credentials", json={"name": "t", "provider": "demo"})
    body = {"alerts": [{"status": "firing",
                        "labels": {"alertname": "DiskFull", "severity": "critical"},
                        "annotations": {"summary": "磁盘已满", "description": "usage 99%"}}]}
    r = client.post("/api/webhooks/alertmanager", json=body)
    assert r.status_code == 200
    assert r.json()["received"] == 1
    a = client.get("/api/alerts").json()[0]
    assert a["source"] == "alertmanager" and a["level"] == "high"
