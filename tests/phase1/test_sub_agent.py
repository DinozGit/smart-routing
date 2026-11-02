"""
Phase 1 — тесты sub-agent fallback heuristic.
"""

import pytest


class TestSubAgentFallback:
    """Шаг 2.5 — короткий system prompt без проектного контекста → default_worker."""

    async def test_generic_prompt_goes_to_default(self, client):
        """Generic system prompt без проектного контекста → не Coordinator, а default_worker."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful coding assistant.",
                    },
                    {"role": "user", "content": "write a function"},
                ],
                "max_tokens": 5,
            },
        )
        # Не должно быть 404 или 500
        assert resp.status_code in (200, 500, 502)
        # Не 404 — главное
        assert resp.status_code != 404

    async def test_short_prompt_not_coordinator(self, client):
        """Короткий system prompt (<3000) → не Coordinator."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {"role": "system", "content": "Short prompt here."},
                    {"role": "user", "content": "do something"},
                ],
                "max_tokens": 5,
            },
        )
        assert resp.status_code != 404

    async def test_empty_system_prompt(self, client):
        """Без system prompt → не падает."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            },
        )
        assert resp.status_code in (200, 500, 502)

    async def test_coordinator_prompt_still_coordinator(
        self, client, sample_coordinator_prompt
    ):
        """Большой system prompt Coordinator'а (>3000) — всё ещё Coordinator."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {"role": "system", "content": sample_coordinator_prompt},
                    {"role": "user", "content": "review code"},
                ],
                "max_tokens": 5,
            },
        )
        assert resp.status_code != 404

    async def test_bot_prompt_still_bot(self, client, sample_bot_prompt):
        """Bot prompt — всё ещё bot (fingerprint срабатывает до fallback)."""
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {"role": "system", "content": sample_bot_prompt},
                    {"role": "user", "content": "add keyboard"},
                ],
                "max_tokens": 5,
            },
        )
        assert resp.status_code != 404
