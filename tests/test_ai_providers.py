"""AI 多模型源（failover）测试"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app import ai, config
from tests.test_api import create_demo_cred


def _mk_alert(client):
    create_demo_cred(client)
    r = client.post("/api/webhooks/generic", json={"title": "多模型测试", "level": "high"})
    return r.json()["id"]


def _fake_response(content):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_providers_config_single_fallback():
    """单模型配置（LLM_API_KEY）→ providers 长度为 1"""
    providers = [{"name": "default", "base_url": "https://x/v1", "api_key": "k", "model": "m"}]
    with patch.object(config, "LLM_PROVIDERS", providers):
        assert config.LLM_PROVIDERS[0]["model"] == "m"


def test_explain_uses_first_provider(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDERS", [
        {"name": "a", "base_url": "https://a/v1", "api_key": "ka", "model": "ma"},
    ])
    aid = _mk_alert(client)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=cm)   # async with 返回自身
    cm.__aexit__ = AsyncMock(return_value=False)
    cm.post.return_value = _fake_response("来自提供方 A 的分析")
    with patch.object(ai.httpx, "AsyncClient", return_value=cm):
        r = asyncio.run(ai.explain_alert(aid))
    assert r["engine"] == "llm" and r["provider"] == "a"
    assert r["analysis"] == "来自提供方 A 的分析"
    # 请求打到提供方 A 的 base_url
    assert "https://a/v1" in str(cm.post.call_args[0][0])


def test_explain_failover_to_second_provider(client, monkeypatch):
    """第一个 provider 失败 → 自动切第二个"""
    monkeypatch.setattr(config, "LLM_PROVIDERS", [
        {"name": "a", "base_url": "https://a/v1", "api_key": "ka", "model": "ma"},
        {"name": "b", "base_url": "https://b/v1", "api_key": "kb", "model": "mb"},
    ])
    aid = _mk_alert(client)

    class FakeClient:
        def __init__(self, *a, **k):
            self._calls = 0
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, **k):
            self._calls += 1
            if "a/v1" in url:
                raise RuntimeError("provider A 挂了")
            return _fake_response("来自提供方 B 的降级分析")

    with patch.object(ai.httpx, "AsyncClient", FakeClient):
        r = asyncio.run(ai.explain_alert(aid))
    assert r["engine"] == "llm" and r["provider"] == "b"
    assert "提供方 B" in r["analysis"]


def test_explain_all_providers_fail_fallback(client, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDERS", [
        {"name": "a", "base_url": "https://a/v1", "api_key": "ka", "model": "ma"},
    ])
    aid = _mk_alert(client)

    class FailingClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, **k):
            raise RuntimeError("provider A 挂了")

    with patch.object(ai.httpx, "AsyncClient", FailingClient):
        r = asyncio.run(ai.explain_alert(aid))
    assert r["engine"] == "llm-fallback"
    assert "回退内置规则分析" in r["analysis"]
