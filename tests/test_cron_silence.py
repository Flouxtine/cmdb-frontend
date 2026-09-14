"""cron 重复静默测试"""
from datetime import datetime, timedelta

import croniter  # noqa: F401  （作为依赖存在性引用）
from tests.test_api import create_demo_cred


def _now_cron_every_minute():
    """每分钟触发一次的 cron（配合 duration 必命中当前时刻）"""
    return "* * * * *"


def test_cron_silence_hits_now(client):
    cron_expr = _now_cron_every_minute()
    r = client.post("/api/silences", json={
        "name": "定期静默", "service": "", "starts_at": "2026-01-01 00:00", "ends_at": "2026-01-01 01:00",
        "cron": cron_expr, "duration_minutes": 30})
    assert r.status_code == 200 and r.json()["kind"] == "cron"

    resp = client.post("/api/webhooks/generic", json={"title": "cron 命中", "level": "high"})
    assert resp.json()["action"] == "silenced"


def test_cron_silence_not_hit(client):
    # 每 3 小时一次，下一次在很久之后 → 当前不命中
    r = client.post("/api/silences", json={
        "name": "低频", "service": "", "starts_at": "2026-01-01 00:00", "ends_at": "2026-01-01 01:00",
        "cron": "0 */3 * * *", "duration_minutes": 10})
    assert r.status_code == 200
    resp = client.post("/api/webhooks/generic", json={"title": "cron 未命中", "level": "high"})
    assert resp.json()["action"] == "created"


def test_cron_silence_validation(client):
    # duration 必须为正
    r = client.post("/api/silences", json={
        "name": "坏数据", "service": "", "starts_at": "2026-01-01 00:00", "ends_at": "2026-01-01 01:00",
        "cron": "* * * * *", "duration_minutes": 0})
    assert r.status_code == 400
    # 非法 cron 表达式 → 400
    r = client.post("/api/silences", json={
        "name": "坏 cron", "service": "", "starts_at": "2026-01-01 00:00", "ends_at": "2026-01-01 01:00",
        "cron": "not-a-cron", "duration_minutes": 30})
    assert r.status_code == 400


def test_once_silence_still_works(client):
    """一次性静默（无 cron）保持原行为"""
    now = datetime.now()
    payload = {
        "name": "一次性", "service": "",
        "starts_at": now.strftime("%Y-%m-%d %H:%M"),
        "ends_at": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }
    r = client.post("/api/silences", json=payload)
    assert r.json()["kind"] == "once"
    resp = client.post("/api/webhooks/generic", json={"title": "一次性命中", "level": "high"})
    assert resp.json()["action"] == "silenced"


def test_cron_service_scoped(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    client.post("/api/silences", json={
        "name": "按服务", "service": "i-demo-001", "starts_at": "2026-01-01 00:00", "ends_at": "2026-01-01 01:00",
        "cron": _now_cron_every_minute(), "duration_minutes": 30})
    assert client.post("/api/webhooks/generic", json={"title": "命中资源", "level": "high", "resource_ref": "i-demo-001"}).json()["action"] == "silenced"
    assert client.post("/api/webhooks/generic", json={"title": "不命中", "level": "high", "resource_ref": "i-demo-002"}).json()["action"] == "created"
