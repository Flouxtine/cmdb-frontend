"""自愈动作引擎测试"""
from tests.test_api import create_demo_cred


def _enable(client, key):
    assert client.patch(f"/api/auto-actions/{key}", json={"enabled": True}).status_code == 200


def _mk_alert(client, title="自愈测试告警"):
    r = client.post("/api/webhooks/generic", json={"title": title, "level": "high"})
    return r.json()["id"]


def test_auto_actions_list(client):
    rules = client.get("/api/auto-actions").json()
    keys = {r["action_key"] for r in rules}
    assert {"auto_assign_bot", "notify_webhook", "simulate_self_heal"} <= keys
    assert all(r["enabled"] == 0 for r in rules)   # 默认关闭


def test_auto_assign_bot_on_create(client):
    _enable(client, "auto_assign_bot")
    aid = _mk_alert(client)
    a = client.get("/api/alerts").json()[0]
    assert a["assignee"] == "🤖 auto-ops"           # 自动认领
    assert a["status"] == "in_progress"             # 进入处理中
    logs = client.get("/api/action-logs").json()
    assert any(l["action_key"] == "auto_assign_bot" and l["alert_id"] == aid for l in logs)


def test_self_heal_writes_comment_and_log(client):
    _enable(client, "simulate_self_heal")
    aid = _mk_alert(client)
    a = client.get("/api/alerts").json()[0]
    assert "自愈" in (a["comment"] or "")           # 备注留痕
    logs = client.get("/api/action-logs").json()
    assert any(l["action_key"] == "simulate_self_heal" for l in logs)


def test_disabled_action_not_executed(client):
    # 默认全部关闭 → 新告警不产生动作日志
    aid = _mk_alert(client)
    logs = client.get("/api/action-logs").json()
    assert all(l["alert_id"] != aid for l in logs)


def test_manual_run_action(client):
    aid = _mk_alert(client)
    r = client.post(f"/api/actions/simulate_self_heal/run/{aid}")
    assert r.status_code == 200
    assert "自愈" in r.json()["detail"]
    # 手动触发也落审计
    assert client.get("/api/action-logs").json()[0]["alert_id"] == aid
    # 404：动作不存在 / 告警不存在
    assert client.post("/api/actions/nope/run/1").status_code == 404
    assert client.post("/api/actions/simulate_self_heal/run/99999").status_code == 404


def test_enabled_state_persists(client):
    _enable(client, "notify_webhook")
    rules = client.get("/api/auto-actions").json()
    assert [r for r in rules if r["action_key"] == "notify_webhook"][0]["enabled"] == 1
