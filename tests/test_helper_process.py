"""
Unit tests for HelperProcess auto-restart, backoff, and HWND tracking.

These tests mock subprocess/pipe interactions to verify the HelperProcess
class logic in isolation (no real helper binary needed).
"""

import threading
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# conftest.py (auto-loaded by pytest) sets up NVDA module mocks,
# so the native.helper_process import works outside NVDA.
from native.helper_process import HelperProcess


class TestRestartConfig(unittest.TestCase):
    """Verify auto-restart configuration constants."""

    def test_restart_delays(self):
        """Backoff array is 1, 2, 4, 8, 16, 30."""
        self.assertEqual(
            HelperProcess._RESTART_DELAYS,
            [1.0, 2.0, 4.0, 8.0, 16.0, 30.0],
        )

    def test_max_restart_attempts(self):
        """Max restart attempts is defined and positive."""
        self.assertGreaterEqual(HelperProcess._MAX_RESTART_ATTEMPTS, 1)
        self.assertEqual(HelperProcess._MAX_RESTART_ATTEMPTS, 6)

    def test_response_timeout(self):
        """Response timeout is a positive number."""
        self.assertGreater(HelperProcess._RESPONSE_TIMEOUT, 0)


class TestHelperProcessInit(unittest.TestCase):
    """Verify HelperProcess initialisation state."""

    def setUp(self):
        with patch("native.helper_process._find_helper_exe", return_value=None):
            self.helper = HelperProcess()

    def test_initial_state(self):
        """Fresh HelperProcess is not started/running."""
        self.assertFalse(self.helper._started)
        self.assertFalse(self.helper.is_running)
        self.assertEqual(self.helper._restart_count, 0)
        self.assertFalse(self.helper._stopping)

    def test_subscribed_hwnds_empty(self):
        """Initially no HWNDs are subscribed."""
        self.assertIsInstance(self.helper._subscribed_hwnds, set)
        self.assertEqual(len(self.helper._subscribed_hwnds), 0)

    def test_start_fails_without_exe(self):
        """start() returns False when no EXE is found."""
        self.assertFalse(self.helper.start())


class TestMaybeRestart(unittest.TestCase):
    """Verify _maybe_restart logic."""

    def setUp(self):
        with patch("native.helper_process._find_helper_exe", return_value="fake.exe"):
            self.helper = HelperProcess()
        # Prevent real sleep during backoff
        self._sleep_patcher = patch("native.helper_process.time.sleep")
        self.mock_sleep = self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    def test_stopping_flag_prevents_restart(self):
        """_maybe_restart is a no-op when _stopping is True."""
        self.helper._stopping = True
        self.helper._restart_count = 0
        self.helper._maybe_restart()
        # restart_count should not change
        self.assertEqual(self.helper._restart_count, 0)

    @patch.object(HelperProcess, "_start_process")
    def test_restart_increments_count(self, mock_start):
        """Each restart attempt increments _restart_count."""
        self.helper._stopping = False
        self.helper._restart_count = 0
        self.helper._maybe_restart()
        self.assertEqual(self.helper._restart_count, 1)

    @patch.object(HelperProcess, "_start_process")
    def test_restart_uses_backoff_delay(self, mock_start):
        """Restart sleeps for the correct backoff delay."""
        self.helper._stopping = False
        self.helper._restart_count = 0
        self.helper._maybe_restart()
        self.mock_sleep.assert_called_once_with(1.0)

        self.mock_sleep.reset_mock()
        self.helper._restart_count = 1
        self.helper._maybe_restart()
        self.mock_sleep.assert_called_once_with(2.0)

    @patch.object(HelperProcess, "_start_process")
    def test_restart_caps_at_max_delay(self, mock_start):
        """Delay caps at the last value in _RESTART_DELAYS."""
        self.helper._stopping = False
        self.helper._restart_count = 5  # Last index
        self.helper._maybe_restart()
        self.mock_sleep.assert_called_once_with(30.0)

    def test_max_attempts_gives_up(self):
        """After _MAX_RESTART_ATTEMPTS, _maybe_restart gives up."""
        self.helper._stopping = False
        self.helper._restart_count = HelperProcess._MAX_RESTART_ATTEMPTS

        # Should dispatch helper_crashed notification
        dispatched = []
        self.helper._dispatch_notification = lambda msg: dispatched.append(msg)
        self.helper._maybe_restart()

        # Should NOT have incremented count or slept
        self.assertEqual(
            self.helper._restart_count, HelperProcess._MAX_RESTART_ATTEMPTS
        )
        self.mock_sleep.assert_not_called()

        # Should have dispatched helper_crashed
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["type"], "helper_crashed")

    @patch.object(HelperProcess, "_start_process")
    def test_restart_count_reset_on_successful_start(self, mock_start):
        """_restart_count resets to 0 on successful _start_process."""
        # _start_process sets _restart_count = 0 internally
        self.helper._stopping = False
        self.helper._started = False
        self.helper._restart_count = 3

        # Simulate successful start: _start_process sets _restart_count=0
        # and restores _proc (which _maybe_restart clears during cleanup)
        def fake_start():
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            self.helper._proc = mock_proc
            self.helper._started = True
            self.helper._ready.set()
            self.helper._restart_count = 0

        mock_start.side_effect = fake_start
        self.helper._maybe_restart()
        self.assertEqual(self.helper._restart_count, 0)

    @patch.object(HelperProcess, "_start_process", side_effect=RuntimeError("boom"))
    def test_restart_failure_retries_until_max(self, mock_start):
        """_start_process failures are caught and retried up to max attempts."""
        self.helper._stopping = False
        self.helper._restart_count = 0

        # Capture dispatched notifications
        dispatched = []
        self.helper._dispatch_notification = lambda msg: dispatched.append(msg)

        # Should not raise — retries all 6 attempts, then gives up
        self.helper._maybe_restart()
        self.assertEqual(
            self.helper._restart_count, HelperProcess._MAX_RESTART_ATTEMPTS
        )
        self.assertEqual(mock_start.call_count, HelperProcess._MAX_RESTART_ATTEMPTS)
        # Should have dispatched helper_crashed after exhausting retries
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["type"], "helper_crashed")

    @patch.object(HelperProcess, "_start_process", side_effect=RuntimeError("boom"))
    def test_stopping_during_retry_loop_exits(self, mock_start):
        """Setting _stopping during retry loop causes _maybe_restart to exit."""
        self.helper._stopping = False
        self.helper._restart_count = 0

        call_count = [0]
        original_sleep = self.mock_sleep.side_effect

        def stop_after_two_sleeps(delay):
            call_count[0] += 1
            if call_count[0] >= 2:
                self.helper._stopping = True

        self.mock_sleep.side_effect = stop_after_two_sleeps
        self.helper._maybe_restart()
        # Should have stopped early, not reached max attempts
        self.assertLess(self.helper._restart_count, HelperProcess._MAX_RESTART_ATTEMPTS)


class TestSubscribedHwndsTracking(unittest.TestCase):
    """Verify _subscribed_hwnds tracking in subscribe/unsubscribe."""

    def setUp(self):
        with patch("native.helper_process._find_helper_exe", return_value="fake.exe"):
            self.helper = HelperProcess()
        # Make the helper appear running
        self.helper._started = True
        self.helper._ready.set()

    @patch.object(HelperProcess, "_send_request")
    def test_subscribe_adds_hwnd(self, mock_send):
        """Successful subscribe adds HWND to tracking set."""
        mock_send.return_value = {"type": "subscribe_ok", "id": 1}
        result = self.helper.subscribe(12345)
        self.assertTrue(result)
        self.assertIn(12345, self.helper._subscribed_hwnds)

    @patch.object(HelperProcess, "_send_request")
    def test_subscribe_failure_no_tracking(self, mock_send):
        """Failed subscribe does not add HWND."""
        mock_send.return_value = {"type": "error", "id": 1, "code": "fail"}
        result = self.helper.subscribe(12345)
        self.assertFalse(result)
        self.assertNotIn(12345, self.helper._subscribed_hwnds)

    @patch.object(HelperProcess, "_send_request")
    def test_unsubscribe_removes_hwnd(self, mock_send):
        """Successful unsubscribe removes HWND from tracking set."""
        self.helper._subscribed_hwnds.add(12345)
        mock_send.return_value = {"type": "unsubscribe_ok", "id": 2}
        result = self.helper.unsubscribe(12345)
        self.assertTrue(result)
        self.assertNotIn(12345, self.helper._subscribed_hwnds)

    @patch.object(HelperProcess, "_send_request")
    def test_unsubscribe_failure_keeps_hwnd(self, mock_send):
        """Failed unsubscribe keeps HWND in tracking set."""
        self.helper._subscribed_hwnds.add(12345)
        mock_send.return_value = {"type": "error", "id": 2, "code": "fail"}
        result = self.helper.unsubscribe(12345)
        self.assertFalse(result)
        self.assertIn(12345, self.helper._subscribed_hwnds)


class TestIsRunning(unittest.TestCase):
    """Verify is_running property."""

    def setUp(self):
        with patch("native.helper_process._find_helper_exe", return_value=None):
            self.helper = HelperProcess()

    def test_not_running_initially(self):
        self.assertFalse(self.helper.is_running)

    def test_running_when_started_and_ready(self):
        self.helper._started = True
        self.helper._ready.set()
        self.assertTrue(self.helper.is_running)

    def test_not_running_when_started_but_not_ready(self):
        self.helper._started = True
        self.helper._ready.clear()
        self.assertFalse(self.helper.is_running)

    def test_not_running_after_crash(self):
        self.helper._started = True
        self.helper._ready.set()
        # Simulate crash
        self.helper._started = False
        self.helper._ready.clear()
        self.assertFalse(self.helper.is_running)


class TestNotificationCallbacks(unittest.TestCase):
    """Verify on/off callback registration."""

    def setUp(self):
        with patch("native.helper_process._find_helper_exe", return_value=None):
            self.helper = HelperProcess()

    def test_on_registers_callback(self):
        cb = lambda msg: None
        self.helper.on("test_event", cb)
        self.assertIn(cb, self.helper._notification_callbacks["test_event"])

    def test_off_removes_callback(self):
        cb = lambda msg: None
        self.helper.on("test_event", cb)
        self.helper.off("test_event", cb)
        self.assertNotIn(cb, self.helper._notification_callbacks.get("test_event", []))

    def test_off_nonexistent_callback_no_error(self):
        """Removing a callback that wasn't registered doesn't raise."""
        cb = lambda msg: None
        self.helper.off("test_event", cb)  # Should not raise

    def test_dispatch_text_changed(self):
        """text_changed notification dispatches hwnd and text to callback."""
        received = []
        self.helper.on("text_changed", lambda h, t: received.append((h, t)))
        self.helper._dispatch_notification({
            "type": "text_changed", "hwnd": 42, "text": "hello"
        })
        self.assertEqual(received, [(42, "hello")])

    def test_dispatch_helper_crashed(self):
        """helper_crashed notification dispatches the full message."""
        received = []
        self.helper.on("helper_crashed", lambda msg: received.append(msg))
        self.helper._dispatch_notification({"type": "helper_crashed"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["type"], "helper_crashed")


if __name__ == "__main__":
    unittest.main()
