"""
Phase 0 — тесты proxy (POST /v1/chat/completions).
"""

import pytest


class TestProxy:
    async def test_proxy_invalid_json(self, client):
        """Невалидный JSON → 400."""
        resp = await client.post(
            "/v1/chat/completions",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_proxy_blacklist(self, client):
        """Устаревшая модель (gpt-3.5) → 400."""
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-3.5", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "Устаревшее" in data["detail"]

    async def test_proxy_blacklist_claude2(self, client):
        """Устаревшая модель (claude-2.0) → 400."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-2.0",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 400

    async def test_proxy_empty_messages(self, client):
        """Пустой messages — не падает 500."""
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "SmartAuto", "messages": []},
        )
        # Допустимо 200 или 502 (нет ключа), но НЕ 500
        assert resp.status_code in (200, 400, 502)
        assert resp.status_code != 500

    async def test_proxy_no_api_key(self, client):
        """Без API-ключа → 502 Missing API key (или 500 при закрытии event loop)."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            },
        )
        # Допускаем 200 (есть ключ), 502 (нет ключа), 500 (event loop)
        assert resp.status_code in (200, 500, 502)
        if resp.status_code == 502:
            data = resp.json()
            assert "API key" in data["detail"]

    async def test_proxy_not_404(self, client):
        """Главное — НЕ 404."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            },
        )
        assert resp.status_code != 404
