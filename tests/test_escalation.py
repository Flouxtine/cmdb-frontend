"""告警升级策略测试"""
from app import database


def _insert_alert(client, level="high", first_at_expr="datetime('now','localtime')", title="升级测试"):
    with database.get_conn() as conn:
        conn.execute(
            f"INSERT INTO alert_events(source, dedup_key, level, title, status, first_at) "
            f"VALUES('internal', 'k', '{level}', '{title}', 'open', {first_at_expr})")
    return client.get("/api/alerts").json()[0]["id"]


def _run_check(client):
    r = client.post("/api/escalation/check")
    assert r.status_code == 200
    return r.json()


def test_high_escalates_after_30min(client):
    _insert_alert(client, level="high", first_at_expr="datetime('now','localtime','-1 hour')")
    result = _run_check(client)
    assert result["escalated"] == 1
    a = client.get("/api/alerts").json()[0]
    assert a["level"] == "critical"
    assert a["escalated_at"] is not None and a["escalate_count"] == 1
    # 审计留痕
    logs = client.get("/api/action-logs").json()
    assert any(l["action_key"] == "escalation_auto" for l in logs)


def test_escalation_idempotent(client):
    # medium 3h：第一轮升 high，第二轮升 critical（最多两级），第三轮不再升
    _insert_alert(client, level="medium", first_at_expr="datetime('now','localtime','-3 hour')")
    _run_check(client)
    a = client.get("/api/alerts").json()[0]
    assert a["level"] == "high" and a["escalate_count"] == 1
    _run_check(client)
    a = client.get("/api/alerts").json()[0]
    assert a["level"] == "critical" and a["escalate_count"] == 2
    _run_check(client)   # 已满两级 → 不再升级
    assert client.get("/api/alerts").json()[0]["escalate_count"] == 2


def test_fresh_alert_not_escalated(client):
    _insert_alert(client, level="high")   # 刚创建
    result = _run_check(client)
    assert result["escalated"] == 0
    assert client.get("/api/alerts").json()[0]["level"] == "high"


def test_medium_threshold_two_hours(client):
    # medium 2.5h → 升级 high；medium 1h → 不升级
    _insert_alert(client, level="medium", first_at_expr="datetime('now','localtime','-2.5 hour')", title="老告警")
    _insert_alert(client, level="medium", first_at_expr="datetime('now','localtime','-1 hour')", title="新告警")
    result = _run_check(client)
    assert result["escalated"] == 1
    alerts = client.get("/api/alerts").json()
    by_title = {a["title"]: a for a in alerts}
    assert by_title["老告警"]["level"] == "high"
    assert by_title["新告警"]["level"] == "medium"


def test_escalation_config(client):
    cfg = client.get("/api/escalation/config").json()
    assert cfg["enabled"] is True
    thresholds = {t["level"]: t for t in cfg["thresholds"]}
    assert thresholds["high"]["upgrade_to"] == "critical" and thresholds["high"]["hours"] == 0.5
