"""
Phase 6 — F3: DELETE /providers/{name}/key — отзыв API-ключа.

Контракт: docs/PROVIDER_CONTRACT.md, раздел F3, тесты 10–12.

- Ключ удаляется из .env (tmp-файл, реальный .env проекта не трогается)
  и из os.environ текущего процесса (без перезапуска).
- GET /providers после удаления → has_api_key=false, api_key_masked отсутствует.
- Неизвестный провайдер → 404.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestF3DeleteKey:
    """F3: отзыв API-ключа провайдера."""

    async def test_delete_key_clears_env(
        self, client, clean_providers, mock_env_file, monkeypatch
    ):
        """DELETE /providers/{name}/key → ключ исчезает из os.environ и has_api_key=false."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-secret-123")
        mock_env_file.write_text(
            "OPENROUTER_API_KEY=sk-test-secret-123\n", encoding="utf-8"
        )

        resp = await client.delete("/providers/openrouter/key")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["provider"] == "openrouter"
        assert data["api_key_env"] == "OPENROUTER_API_KEY"
        assert data["key_removed"] is True
        assert data["env_cleared"] is True

        # Ключ исчез из текущего процесса без перезапуска
        assert "OPENROUTER_API_KEY" not in os.environ

        provs = (await client.get("/providers")).json()["providers"]
        assert provs["openrouter"]["has_api_key"] is False
        assert "api_key_masked" not in provs["openrouter"]

    async def test_delete_key_removes_line_from_env_file(
        self, client, clean_providers, mock_env_file
    ):
        """Строка KEY= удаляется из .env (tmp), остальные строки сохраняются."""
        mock_env_file.write_text(
            "# comment\nOPENROUTER_API_KEY=sk-secret-123\nOTHER=keep\n",
            encoding="utf-8",
        )

        resp = await client.delete("/providers/openrouter/key")
        assert resp.status_code == 200
        assert resp.json()["key_removed"] is True

        content = mock_env_file.read_text(encoding="utf-8")
        lines = content.splitlines()
        assert not any(l.startswith("OPENROUTER_API_KEY=") for l in lines)
        assert "# comment" in lines
        assert "OTHER=keep" in lines

    async def test_delete_key_unknown_provider_404(self, client, clean_providers):
        """Неизвестный провайдер → 404."""
        resp = await client.delete("/providers/nonexistent-provider/key")
        assert resp.status_code == 404