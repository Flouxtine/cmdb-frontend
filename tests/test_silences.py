"""告警静默/维护窗口测试"""
from datetime import datetime, timedelta

from tests.test_api import create_demo_cred

FMT = "%Y-%m-%d %H:%M"


def _fmt(dt):
    return dt.strftime(FMT)


def _silence_payload(service="", start=None, end=None):
    now = datetime.now()
    return {
        "name": "测试静默", "service": service,
        "starts_at": _fmt(start if start is not None else now - timedelta(minutes=10)),
        "ends_at": _fmt(end if end is not None else now + timedelta(minutes=60)),
        "note": "pytest",
    }


def _create_silence(client, service="", start=None, end=None):
    r = client.post("/api/silences", json=_silence_payload(service, start, end))
    assert r.status_code == 200
    return r.json()["id"]


def test_global_silence_suppresses_alert(client):
    _create_silence(client)
    r = client.post("/api/webhooks/generic", json={"title": "静默测试告警", "level": "high"})
    assert r.json()["action"] == "silenced"
    assert client.get("/api/alerts").json() == []


def test_expired_silence_no_suppress(client):
    now = datetime.now()
    _create_silence(client, start=now - timedelta(hours=2), end=now - timedelta(hours=1))
    r = client.post("/api/webhooks/generic", json={"title": "正常告警", "level": "high"})
    assert r.json()["action"] == "created"
    assert len(client.get("/api/alerts").json()) == 1


def test_service_scoped_silence(client):
    cid = create_demo_cred(client)
    client.post(f"/api/credentials/{cid}/sync")
    _create_silence(client, service="i-demo-001")
    r = client.post("/api/webhooks/generic", json={"title": "命中", "level": "high", "resource_ref": "i-demo-001"})
    assert r.json()["action"] == "silenced"
    r2 = client.post("/api/webhooks/generic", json={"title": "未命中", "level": "high", "resource_ref": "i-demo-002"})
    assert r2.json()["action"] == "created"


def test_silence_crud_and_status(client):
    _create_silence(client)
    rows = client.get("/api/silences").json()
    assert len(rows) == 1 and rows[0]["status"] == "active"
    sid = rows[0]["id"]
    assert client.delete(f"/api/silences/{sid}").status_code == 200
    assert client.get("/api/silences").json() == []
    assert client.delete("/api/silences/nope").status_code == 404
    bad = {**_silence_payload(), "starts_at": "2026-09-01 00:00", "ends_at": "2026-08-01 00:00"}
    assert client.post("/api/silences", json=bad).status_code == 400


def test_silence_status_labels(client):
    now = datetime.now()
    client.post("/api/silences", json={
        "name": "过期", "service": "",
        "starts_at": _fmt(now - timedelta(hours=2)), "ends_at": _fmt(now - timedelta(hours=1))})
    client.post("/api/silences", json={
        "name": "未来", "service": "",
        "starts_at": _fmt(now + timedelta(hours=2)), "ends_at": _fmt(now + timedelta(hours=3))})
    rows = client.get("/api/silences").json()
    statuses = {r["name"]: r["status"] for r in rows}
    assert statuses["过期"] == "expired"
    assert statuses["未来"] == "upcoming"
