"""Webhook HMAC 签名校验测试"""
import hashlib
import hmac
import json

from app import config


def _sig(secret, payload):
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _post(client, payload, signature=None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Ops-Scope-Signature"] = signature
    return client.post("/api/webhooks/generic", content=payload, headers=headers)


def test_hmac_enforced_when_secret_set(client, monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "test-secret")
    payload = json.dumps({"title": "签名测试", "level": "high"})

    # 缺签名 → 401
    assert _post(client, payload).status_code == 401
    # 错误签名 → 401
    assert _post(client, payload, signature="deadbeef").status_code == 401
    # 正确签名 → 200 + created
    r = _post(client, payload, signature=_sig("test-secret", payload))
    assert r.status_code == 200
    assert r.json()["action"] == "created"


def test_hmac_body_tamper_detected(client, monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "test-secret")
    payload = json.dumps({"title": "tamper", "level": "high"})
    tampered = payload.replace('"high"', '"low"')   # 篡改 level（JSON 结构不变，字节必变）
    # 用原 payload 的签名发被篡改的 body → 401
    r = _post(client, tampered, signature=_sig("test-secret", payload))
    assert r.status_code == 401


def test_alertmanager_hmac(client, monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "am-secret")
    payload = json.dumps({"alerts": [{"status": "firing", "labels": {"alertname": "X", "severity": "critical"}}]})
    r = client.post("/api/webhooks/alertmanager", content=payload,
                    headers={"Content-Type": "application/json",
                             "X-Ops-Scope-Signature": _sig("am-secret", payload)})
    assert r.status_code == 200 and r.json()["received"] == 1
    assert client.post("/api/webhooks/alertmanager", content=payload,
                       headers={"Content-Type": "application/json"}).status_code == 401


def test_token_fallback_without_secret(client, monkeypatch):
    # 未配 secret → 走 token 兼容；未配 token → 不校验（宽松）
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "")
    monkeypatch.setattr(config, "WEBHOOK_TOKEN", "")
    payload = json.dumps({"title": "宽松模式", "level": "low"})
    assert _post(client, payload).status_code == 200
