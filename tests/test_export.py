"""CSV 导出测试"""
from datetime import datetime, timedelta

from app import database
from tests.test_api import create_demo_cred


def test_alerts_export_csv(client):
    create_demo_cred(client)
    client.post("/api/webhooks/generic", json={"title": "导出测试", "level": "high", "resource_ref": "i-demo-001"})
    r = client.get("/api/alerts/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    body = r.text.lstrip("\ufeff")
    lines = body.strip().split("\n")
    assert lines[0].startswith("ID,级别,标题")          # 表头
    assert any("导出测试" in line for line in lines)     # 数据行


def test_alerts_export_respects_filter(client):
    client.post("/api/webhooks/generic", json={"title": "高危告警", "level": "high"})
    client.post("/api/webhooks/generic", json={"title": "低危告警", "level": "low"})
    body = client.get("/api/alerts/export.csv?level=high").text
    assert "高危告警" in body and "低危告警" not in body


def test_report_export_csv(client):
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO alert_events(source,dedup_key,level,title,status,first_at) "
            "VALUES('internal','k','high','报表导出', 'open', datetime('now','localtime','-1 day'))")
    r = client.get("/api/alerts/report/export.csv?days=7")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    body = r.text.lstrip("\ufeff")
    assert "处置统计报表" in body
    assert "按天趋势" in body
    assert "认领人工作量" in body
    assert "报表导出" in body or "产生告警: 1" in body
