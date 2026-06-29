"""
Phase 2 — тесты разделения портов (Step 2.3).

Чтение портов из config.yaml:
  router_port, admin_port, admin_host, single_port

Single-port (default): всё на router_port.
Dual-port: router на router_port, admin на admin_port.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestServerConfig:
    """Чтение server-секции из config.yaml."""

    def test_router_port_loaded(self):
        """router_port читается из config."""
        assert router.ROUTER_PORT == 8765

    def test_admin_port_loaded(self):
        """admin_port читается из config."""
        assert router.ADMIN_PORT == 8766

    def test_admin_host_loaded(self):
        """admin_host читается из config."""
        assert router.ADMIN_HOST == "127.0.0.1"

    def test_single_port_default_true(self):
        """single_port = true по умолчанию (обратная совместимость)."""
        assert router.SINGLE_PORT is True

    def test_server_cfg_present(self):
        """SERVER_CFG — dict с ключами."""
        assert isinstance(router.SERVER_CFG, dict)
        assert "router_port" in router.SERVER_CFG
        assert "admin_port" in router.SERVER_CFG

    def test_router_port_is_int(self):
        """Порт — целое число (не строка из yaml)."""
        assert isinstance(router.ROUTER_PORT, int)
        assert isinstance(router.ADMIN_PORT, int)

    def test_admin_port_differs_from_router_port(self):
        """В dual-port режиме порты должны различаться."""
        # В config они разные: 8765 и 8766
        assert router.ADMIN_PORT != router.ROUTER_PORT


class TestServerRunFunctions:
    """Функции запуска определены и корректны."""

    def test_run_single_port_exists(self):
        assert hasattr(router, "_run_single_port")
        assert callable(router._run_single_port)

    def test_run_dual_port_exists(self):
        assert hasattr(router, "_run_dual_port")
        assert callable(router._run_dual_port)
