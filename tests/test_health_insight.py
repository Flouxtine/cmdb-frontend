"""健康故障模式分析测试"""
from app import database


def _insert_samples(client, error_rate, latency, qps):
    """直接插入一组采样（制造故障/正常状态）"""
    with database.get_conn() as conn:
        for i in range(6):
            conn.execute(
                "INSERT INTO metric_samples(service, metric, value, ts) "
                "VALUES('demo-api', 'error_rate', ?, datetime('now','localtime'))",
                (error_rate,))
            conn.execute(
                "INSERT INTO metric_samples(service, metric, value, ts) "
                "VALUES('demo-api', 'latency', ?, datetime('now','localtime'))",
                (latency,))
            conn.execute(
                "INSERT INTO metric_samples(service, metric, value, ts) "
                "VALUES('demo-api', 'qps', ?, datetime('now','localtime'))",
                (qps,))


def test_healthy_no_findings(client):
    _insert_samples(client, 0.2, 100, 200)
    r = client.get("/api/health/insight?service=demo-api")
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "healthy" and d["findings"] == []


def test_error_rate_finding(client):
    _insert_samples(client, 8.0, 100, 200)
    d = client.get("/api/health/insight").json()
    assert d["state"] == "abnormal"
    types = {f["type"] for f in d["findings"]}
    assert "error_rate" in types and "resonance" not in types


def test_resonance_detected(client):
    """错误率+延迟同时超标 → 多指标共振"""
    _insert_samples(client, 8.0, 700, 200)
    d = client.get("/api/health/insight").json()
    assert any(f["type"] == "resonance" for f in d["findings"])
    assert d["state"] == "abnormal"


def test_traffic_spike(client):
    """QPS 骤变检测：最新值远高于窗口均值"""
    with database.get_conn() as conn:
        for v in (200, 210, 205, 195, 800):   # 最新 800 vs 前 4 均值 ~200 → 激增
            conn.execute(
                "INSERT INTO metric_samples(service, metric, value, ts) "
                "VALUES('demo-api','qps',?,datetime('now','localtime'))", (v,))
    d = client.get("/api/health/insight").json()
    assert any(f["type"] == "traffic" for f in d["findings"])
