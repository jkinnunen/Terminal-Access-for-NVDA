"""Tests for the native-helper hardening that fixes the find-command freeze.

Covers the pieces that protect NVDA's main thread from a wedged helper:
the force-kill watchdog, the kill-on-timeout in the request round-trip, and
the native-acceleration master switch. The COM apartment change and the
real pipe I/O are exercised only against a live helper on Windows, so they
are not unit-tested here; these tests cover the Python control logic with a
mocked subprocess.
"""
import threading
import time
from unittest.mock import MagicMock

import pytest

from native.helper_process import HelperProcess, _PendingResponse


def _make_helper():
    """A HelperProcess with a fake, live subprocess and no real pipe."""
    h = HelperProcess()
    h._proc = MagicMock()
    h._proc.poll.return_value = None  # None == still running
    return h


class TestKillHelper:
    def test_kills_a_live_process_once(self):
        h = _make_helper()
        h._kill_helper()
        h._proc.kill.assert_called_once()

    def test_noop_when_no_process(self):
        h = HelperProcess()
        h._proc = None
        h._kill_helper()  # must not raise

    def test_noop_when_already_dead(self):
        h = _make_helper()
        h._proc.poll.return_value = 0  # already exited
        h._kill_helper()
        h._proc.kill.assert_not_called()


class TestSendRequestTimeout:
    def test_kills_helper_when_response_times_out(self):
        h = _make_helper()
        h._RESPONSE_TIMEOUT = 0.05  # fast timeout for the test
        h._write_message = MagicMock()  # pretend the write succeeds
        h._kill_helper = MagicMock()
        result = h._send_request("read_text", hwnd=1)
        assert result is None
        h._kill_helper.assert_called_once()

    def test_does_not_kill_while_stopping(self):
        h = _make_helper()
        h._RESPONSE_TIMEOUT = 0.05
        h._stopping = True  # a shutdown request that goes unanswered
        h._write_message = MagicMock()
        h._kill_helper = MagicMock()
        result = h._send_request("shutdown")
        assert result is None
        h._kill_helper.assert_not_called()


class TestWatchdog:
    def test_kills_helper_when_request_stuck_past_hard_timeout(self):
        h = _make_helper()
        h._HARD_TIMEOUT = 0.05
        h._WATCHDOG_INTERVAL = 0.01
        h._kill_helper = MagicMock()
        # A request that has been in flight far longer than the hard timeout.
        pending = _PendingResponse()
        pending.start = time.monotonic() - 100
        with h._pending_lock:
            h._pending[1] = pending

        t = threading.Thread(target=h._watchdog_loop, daemon=True)
        t.start()
        t.join(timeout=2.0)
        h._kill_helper.assert_called()

    def test_does_not_kill_when_requests_are_fresh(self):
        h = _make_helper()
        h._HARD_TIMEOUT = 10.0  # far above the test window
        h._WATCHDOG_INTERVAL = 0.01
        h._kill_helper = MagicMock()
        with h._pending_lock:
            h._pending[1] = _PendingResponse()  # start == now

        t = threading.Thread(target=h._watchdog_loop, daemon=True)
        t.start()
        time.sleep(0.05)
        h._stopping = True  # ask the loop to exit
        t.join(timeout=2.0)
        h._kill_helper.assert_not_called()


class TestNativeToggle:
    def setup_method(self):
        import native.termaccess_bridge as bridge
        self.bridge = bridge
        self._prev = bridge._native_enabled

    def teardown_method(self):
        self.bridge._native_enabled = self._prev

    def test_disabled_makes_native_unavailable(self):
        self.bridge.set_native_enabled(False)
        assert self.bridge.native_available() is False

    def test_disabled_get_helper_returns_none(self):
        self.bridge.set_native_enabled(False)
        assert self.bridge.get_helper() is None

    def test_enabled_returns_a_bool_without_forcing_false(self):
        # With native enabled, availability depends on the DLL; the point is
        # that the switch no longer hard-disables it.
        self.bridge.set_native_enabled(True)
        assert isinstance(self.bridge.native_available(), bool)


def test_use_native_acceleration_config_default():
    from lib.config import confspec
    assert "useNativeAcceleration" in confspec
    assert "default=True" in confspec["useNativeAcceleration"]
