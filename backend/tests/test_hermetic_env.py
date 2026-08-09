"""Guard tests proving the suite is hermetic (see tests/conftest.py).

These exist to fail loudly — not to hang for ~4s and then pass via a
graceful fallback — the moment either the mock-mode default or the network
block in conftest.py stops working.
"""

import socket

import pytest

from app.config import settings


def test_use_mocks_defaults_true_under_pytest():
    """Every test starts in mock mode, regardless of what backend/.env
    (which sets USE_MOCKS=false for the real app and demo) contains. This
    is the autouse `_force_mock_mode` fixture in conftest.py taking effect."""
    assert settings.use_mocks is True


def test_real_socket_connect_is_blocked_during_tests():
    """A real outbound connection attempt (e.g. to the YouCam API host)
    raises immediately instead of reaching the network. This is the
    autouse `_block_network` fixture in conftest.py taking effect; it is
    what makes it impossible for a test to silently spend real API
    credits or depend on network availability."""
    with pytest.raises(RuntimeError, match="Network access attempted"):
        socket.create_connection(("yce-api-01.makeupar.com", 443), timeout=1)
