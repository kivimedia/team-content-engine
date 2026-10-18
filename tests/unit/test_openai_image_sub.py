"""OpenAI images go through the ChatGPT-plan proxy when TCE_IMAGE_SUB_URL is set.

The proxy (codex-image-proxy on 127.0.0.1:8962) answers the OpenAI Images API shape,
bills the plan, and falls back to api.openai.com only with the caller's own Bearer key,
so the Bearer header must still be sent.
"""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

import tce.services.openai_image as oi
from tce.settings import settings

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


class _NoStorage:
    configured = False


@pytest.fixture
def captured(monkeypatch, tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        seen["timeout"] = request.extensions.get("timeout")
        if request.url.host == "127.0.0.1":
            return httpx.Response(
                200,
                json={"created": 1, "data": [{"b64_json": _PNG}], "km_transport": "subscription"},
                headers={"x-km-transport": "subscription"},
            )
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": _PNG}]})

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(oi.httpx, "AsyncClient", factory)
    import tce.services.storage as storage

    monkeypatch.setattr(storage, "StorageService", _NoStorage)
    monkeypatch.setattr(settings, "image_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "image_public_base", "")
    return seen


def _sub_on(monkeypatch, key="sk-test-callerkey"):
    monkeypatch.setattr(settings, "openai_api_key", key)
    monkeypatch.setattr(settings, "image_sub_url", "http://127.0.0.1:8962")
    monkeypatch.setattr(settings, "image_sub_key", "sub-secret-1234")
    monkeypatch.setattr(settings, "image_sub_caller", "team-content-engine")


def test_sub_url_routes_generation_to_the_plan_proxy(monkeypatch, captured):
    _sub_on(monkeypatch)
    out = asyncio.run(
        oi.OpenAIImageService().generate_image("a red kite", aspect_ratio="16:9", model="gpt-image-2")
    )
    assert captured["url"] == "http://127.0.0.1:8962/v1/images/generations"
    h = captured["headers"]
    assert h["x-km-sub-key"] == "sub-secret-1234"
    assert h["x-km-caller"] == "team-content-engine"
    # Bearer stays so the proxy can fall back to the paid API with OUR key
    assert h["authorization"] == "Bearer sk-test-callerkey"
    assert captured["body"]["size"] == "1536x1024"
    assert out["status"] == "generated"
    assert out["km_transport"] == "subscription"
    # plan images cost nothing on the metered bill
    assert out["generation_cost_usd"] == 0.0


def test_sub_path_works_without_an_openai_key(monkeypatch, captured):
    _sub_on(monkeypatch, key="")
    out = asyncio.run(oi.OpenAIImageService().generate_image("a red kite", model="gpt-image-2"))
    assert out["status"] == "generated"
    assert "authorization" not in captured["headers"]


def test_no_sub_url_keeps_the_direct_api(monkeypatch, captured):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-callerkey")
    monkeypatch.setattr(settings, "image_sub_url", "")
    out = asyncio.run(oi.OpenAIImageService().generate_image("a red kite", model="gpt-image-2"))
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert "x-km-sub-key" not in captured["headers"]
    assert out["generation_cost_usd"] == 0.19


_REAL_ASYNC_CLIENT = httpx.AsyncClient  # bound at import, before any fixture patches it


def _client_with(monkeypatch, handler):
    real = _REAL_ASYNC_CLIENT

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(oi.httpx, "AsyncClient", factory)


def test_proxy_down_falls_back_to_the_paid_api_with_our_key(monkeypatch, captured):
    _sub_on(monkeypatch)
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "127.0.0.1":
            raise httpx.ConnectError("connection refused", request=request)
        assert request.headers["authorization"] == "Bearer sk-test-callerkey"
        assert "x-km-sub-key" not in request.headers
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": _PNG}]})

    _client_with(monkeypatch, handler)
    out = asyncio.run(oi.OpenAIImageService().generate_image("a red kite", model="gpt-image-2"))
    assert hosts == ["127.0.0.1", "api.openai.com"]
    assert out["status"] == "generated"


def test_proxy_refusing_our_key_falls_back_instead_of_failing(monkeypatch, captured):
    _sub_on(monkeypatch)
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == "127.0.0.1":
            return httpx.Response(401, json={"error": {"message": "bad key"}})
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": _PNG}]})

    _client_with(monkeypatch, handler)
    out = asyncio.run(oi.OpenAIImageService().generate_image("a red kite", model="gpt-image-2"))
    assert hosts == ["127.0.0.1", "api.openai.com"]
    assert out["status"] == "generated"


def test_empty_sub_key_goes_straight_to_the_paid_api(monkeypatch, captured):
    _sub_on(monkeypatch)
    monkeypatch.setattr(settings, "image_sub_key", "")
    asyncio.run(oi.OpenAIImageService().generate_image("a red kite", model="gpt-image-2"))
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
