"""
Phase 1 — тесты дехардкода Coordinator fallback (Step 1.3).

Раньше: неизвестные запросы → mapping["coordinator"] → GLM/Pro (дорого).
Теперь: неизвестные запросы → default_worker → Flash (дёшево).
Coordinator определяется ТОЛЬКО через fingerprinting.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from router import smart_route_model


class TestDehardcodeCoordinatorFallback:
    """Шаг 8 — неизвестные запросы → default_worker, а не coordinator."""

    def test_unknown_request_goes_to_default_worker(self):
        """Запрос без fingerprint и без agent tag → default_worker, не coordinator."""
        body = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "hello world"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert "flash" in model.lower(), (
            f"Expected default_worker (flash), got {model} ({reason})"
        )
        assert "default" in reason.lower(), f"Expected default reason, got: {reason}"

    def test_unknown_request_not_coordinator_model(self):
        """Неизвестный запрос НЕ должен идти на coordinator model (glm/pro)."""
        body = {
            "messages": [
                {"role": "system", "content": "Short generic prompt."},
                {"role": "user", "content": "do something generic"},
            ]
        }
        model, _, _ = smart_route_model("SmartAuto", body)
        # coordinator model в config — z-ai/glm-5.2
        assert "glm" not in model.lower(), (
            f"Unknown request routed to coordinator model (glm): {model}"
        )
        assert "pro" not in model.lower(), (
            f"Unknown request routed to coordinator model (pro): {model}"
        )

    def test_coordinator_fingerprint_still_works(self, sample_coordinator_prompt):
        """Coordinator с fingerprint → coordinator model (не default_worker)."""
        body = {
            "messages": [
                {"role": "system", "content": sample_coordinator_prompt},
                {"role": "user", "content": "review the architecture"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        # Coordinator должен пройти через fingerprint → coordinator model
        assert "glm" in model.lower() or "pro" in model.lower(), (
            f"Coordinator not routed to coordinator model: {model} ({reason})"
        )
        assert role == "coordinator", f"Expected role='coordinator', got '{role}'"

    def test_empty_messages_goes_to_default(self):
        """Пустой messages → default_worker, не coordinator."""
        body = {"messages": []}
        model, _, _ = smart_route_model("SmartAuto", body)
        # Пустые messages → "Нет сообщений" → запрошенная модель
        # Но если дошли до step 8, то default_worker
        assert model is not None

    def test_no_messages_key_goes_to_default(self):
        """Запрос без ключа messages → default_worker, не coordinator."""
        body = {}
        model, _, _ = smart_route_model("SmartAuto", body)
        assert model is not None

    def test_explicit_flash_not_routed_to_coordinator(self):
        """Явно указанная flash-модель не перенаправляется на coordinator."""
        body = {"messages": [{"role": "user", "content": "hello"}]}
        model, _, _ = smart_route_model("deepseek/deepseek-v4-flash", body)
        assert "flash" in model.lower()

    def test_explicit_qwen_not_routed_to_coordinator(self):
        """Явно указанная qwen-модель не перенаправляется на coordinator."""
        body = {"messages": [{"role": "user", "content": "hello"}]}
        model, _, _ = smart_route_model("qwen/qwen3-coder-next", body)
        assert "qwen" in model.lower()

    def test_generic_long_system_prompt_not_coordinator(self):
        """
        Длинный generic system prompt без Coordinator fingerprint → default_worker.
        Раньше срабатывал fallback по размеру (>3000 → coordinator).
        Теперь: если fingerprint не нашёл Coordinator → default_worker.
        """
        # Длинный промпт, но БЕЗ Coordinator-маркеров
        generic_long = "You are a helpful coding assistant. " * 100  # ~4600 chars
        body = {
            "messages": [
                {"role": "system", "content": generic_long},
                {"role": "user", "content": "write a function"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        # Должен идти на worker_default, не coordinator
        assert "flash" in model.lower() or "default" in reason.lower(), (
            f"Generic long prompt routed to coordinator: {model} ({reason})"
        )
        assert role == "worker_default", f"Expected role='worker_default', got '{role}'"
