"""处置统计报表测试（时间窗内聚合）"""
from datetime import date, timedelta

from app import database


def _insert(client, rows):
    """直接插入带相对时间的告警（SQL 表达式生成 first_at/resolved_at），值均来自测试常量"""
    for r in rows:
        with database.get_conn() as conn:
            conn.execute(
                f"INSERT INTO alert_events(source, dedup_key, level, title, status, first_at, resolved_at, assignee) "
                f"VALUES('{r.get('source', 'internal')}', 'k', 'high', '{r.get('title', 't')}', "
                f"'{r.get('status', 'open')}', {r['first']}, {r.get('resolved', 'NULL')}, '{r.get('assignee', '')}')")


NOW = "datetime('now','localtime')"
MINUS1 = "datetime('now','localtime','-1 day')"
MINUS2 = "datetime('now','localtime','-2 day')"
RES2H = "datetime('now','localtime','-1 day','+2 hours')"
RES1H = "datetime('now','localtime','-2 day','+1 hours')"


def test_report_basic_stats(client):
    _insert(client, [
        {"title": "A1", "first": MINUS1, "resolved": RES2H, "status": "resolved", "assignee": "张三"},   # 解决 2h
        {"title": "A2", "first": MINUS1, "status": "open", "assignee": "张三"},
        {"title": "A3", "first": MINUS2, "status": "open", "assignee": ""},
    ])
    r = client.get("/api/alerts/report?days=7").json()
    assert r["produced"] == 3
    assert r["resolved"] == 1
    assert r["open_now"] == 2
    assert r["avg_resolve_hours"] == 2.0
    by_a = {x["assignee"]: x for x in r["by_assignee"]}
    assert by_a["张三"]["total"] == 2 and by_a["张三"]["resolved"] == 1
    assert by_a["(未认领)"]["total"] == 1


def test_report_days_filter(client):
    _insert(client, [
        {"title": "old", "first": "datetime('now','localtime','-31 day')"},   # 30 天窗外
        {"title": "mid", "first": "datetime('now','localtime','-10 day')"},   # 7 天窗外、30 天内
        {"title": "recent", "first": MINUS1},                                  # 7 天内
    ])
    assert client.get("/api/alerts/report?days=7").json()["produced"] == 1
    assert client.get("/api/alerts/report?days=30").json()["produced"] == 2


def test_report_by_day(client):
    _insert(client, [
        {"title": "D1", "first": MINUS2, "resolved": RES1H, "status": "resolved"},
        {"title": "D2", "first": MINUS1, "status": "open"},
    ])
    r = client.get("/api/alerts/report?days=7").json()
    d_minus1 = (date.today() - timedelta(days=1)).isoformat()
    d_minus2 = (date.today() - timedelta(days=2)).isoformat()
    produced = {d["day"]: d["n"] for d in r["by_day"]["produced"]}
    assert produced.get(d_minus1) == 1 and produced.get(d_minus2) == 1
    resolved_days = {d["day"]: d["n"] for d in r["by_day"]["resolved"]}
    assert resolved_days.get(d_minus2) == 1


def test_report_days_bound(client):
    assert client.get("/api/alerts/report?days=999").json()["days"] == 90
    assert client.get("/api/alerts/report?days=0").json()["days"] == 1
