"""
Phase 1 — тесты дехардкода Coordinator fallback (Step 1.3).

Теперь: неизвестные запросы → Coordinator (он сам распределяет).
Coordinator определяется через fingerprint, agent tag, или дефолт.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from router import smart_route_model


class TestDehardcodeCoordinatorFallback:
    """Неизвестные запросы → coordinator model."""

    def test_unknown_request_goes_to_coordinator(self):
        """Запрос без fingerprint и без agent tag → coordinator."""
        body = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "hello world"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got {role} ({reason})"
        assert "coordinator" in reason.lower(), (
            f"Expected coordinator reason, got: {reason}"
        )

    def test_coordinator_fingerprint_still_works(self, sample_coordinator_prompt):
        """Coordinator с fingerprint → coordinator model."""
        body = {
            "messages": [
                {"role": "system", "content": sample_coordinator_prompt},
                {"role": "user", "content": "review the architecture"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert (
            "pro" in model.lower() or "glm" in model.lower() or "coordinator" in role
        ), f"Coordinator not routed: {model} ({reason})"
        assert role == "coordinator", f"Expected role='coordinator', got '{role}'"

    def test_empty_messages_goes_to_requested(self):
        """Пустой messages → запрошенная модель."""
        body = {"messages": []}
        model, _, _ = smart_route_model("SmartAuto", body)
        assert model is not None

    def test_no_messages_key_goes_to_requested(self):
        """Запрос без ключа messages → запрошенная модель."""
        body = {}
        model, _, _ = smart_route_model("SmartAuto", body)
        assert model is not None

    def test_explicit_flash_stays_flash(self):
        """Явно указанная flash-модель не меняется."""
        body = {"messages": [{"role": "user", "content": "hello"}]}
        model, _, _ = smart_route_model("deepseek/deepseek-v4-flash", body)
        assert "flash" in model.lower()

    def test_explicit_qwen_stays_qwen(self):
        """Явно указанная qwen-модель не меняется."""
        body = {"messages": [{"role": "user", "content": "hello"}]}
        model, _, _ = smart_route_model("qwen/qwen3-coder-next", body)
        assert "qwen" in model.lower()

    def test_generic_long_system_prompt_goes_to_coordinator(self):
        """Длинный generic system prompt → coordinator (а не worker)."""
        generic_long = "You are a helpful coding assistant. " * 100
        body = {
            "messages": [
                {"role": "system", "content": generic_long},
                {"role": "user", "content": "write a function"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got '{role}' ({reason})"
