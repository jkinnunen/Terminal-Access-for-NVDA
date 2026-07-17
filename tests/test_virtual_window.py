"""Buffer window script wiring: gestures, gating, threading, presentation.

The browse window itself is NVDA's (ui.browseableMessage); what we own
and test is everything up to the call: terminal gating, the buffer read
on the main thread (COM stays where the watchdog can cancel it), the
render on a worker thread, and the exact arguments handed to
browseableMessage, including the identity sanitizer that keeps nh3.clean
off the main thread.
"""
from unittest.mock import MagicMock, Mock, patch

import pytest

from lib.buffer_snapshot import BufferSnapshot


def _make_plugin():
    from globalPlugins.terminalAccess import GlobalPlugin
    return GlobalPlugin()


def _snapshot(lines=("alpha", "beta"), name="WindowsTerminal"):
    term = Mock()
    term.appModule.appName = name
    return BufferSnapshot.capture(term, list(lines))


class TestGestureWiring:
    def test_script_exists(self):
        from globalPlugins.terminalAccess import GlobalPlugin
        assert hasattr(GlobalPlugin, "script_showBufferWindow")

    def test_direct_gesture_is_nvda_enter(self):
        from globalPlugins.terminalAccess import _DEFAULT_GESTURES
        assert _DEFAULT_GESTURES.get("kb:NVDA+enter") == "showBufferWindow"

    def test_command_layer_key_is_enter(self):
        from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
        assert _COMMAND_LAYER_MAP.get("kb:enter") == "showBufferWindow"

    def test_nvda_enter_is_listed_as_a_conflict(self):
        """kb(laptop):NVDA+enter is NVDA's review-activate; users must be
        able to see and unbind the collision in Gesture Conflicts."""
        from globalPlugins.terminalAccess import _CONFLICTING_GESTURES
        assert "kb:NVDA+enter" in _CONFLICTING_GESTURES


class TestScriptGating:
    def test_passes_through_outside_terminal(self):
        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=False)
        gesture = MagicMock()

        plugin.script_showBufferWindow(gesture)

        gesture.send.assert_called_once()

    def test_announces_when_buffer_unreadable(self):
        import ui
        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=True)
        plugin._getBufferLines = Mock(return_value=None)
        ui.message.reset_mock()

        plugin.script_showBufferWindow(MagicMock())

        ui.message.assert_called_once()

    def test_reads_buffer_on_the_calling_thread(self):
        """The COM read stays on the main thread, where NVDA's watchdog
        can cancel a stuck call (the beta.3 lesson: worker-thread COM is
        what deadlocks). Only the render goes to the worker."""
        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=True)
        plugin._getBufferLines = Mock(return_value=["x"])
        plugin._boundTerminal = Mock()

        with patch("threading.Thread") as thread_cls:
            plugin.script_showBufferWindow(MagicMock())

        plugin._getBufferLines.assert_called_once()
        thread_cls.assert_called_once()
        kwargs = thread_cls.call_args.kwargs
        assert kwargs.get("daemon") is True

    def test_worker_receives_a_snapshot_not_the_terminal(self):
        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=True)
        plugin._getBufferLines = Mock(return_value=["a", "b"])
        plugin._boundTerminal = Mock()
        plugin._boundTerminal.appModule.appName = "wt"

        with patch("threading.Thread") as thread_cls:
            plugin.script_showBufferWindow(MagicMock())

        args = thread_cls.call_args.kwargs.get("args") or ()
        assert len(args) == 1
        assert isinstance(args[0], BufferSnapshot)
        assert args[0].lines == ["a", "b"]


class TestWorkerAndPresentation:
    def test_worker_renders_then_presents_via_call_after(self):
        import wx
        plugin = _make_plugin()
        snap = _snapshot()
        wx.CallAfter.reset_mock()

        plugin._bufferWindowWorker(snap)

        wx.CallAfter.assert_called_once()
        target = wx.CallAfter.call_args.args[0]
        assert target == plugin._presentBufferWindow

    def test_worker_output_has_semantic_headings(self):
        """The worker tokenizes and renders structure, not flat text:
        a prompt line must arrive at the window as an H2."""
        import wx
        plugin = _make_plugin()
        snap = _snapshot(lines=("PS C:\\repo> npm test", "1 passed"))
        wx.CallAfter.reset_mock()

        plugin._bufferWindowWorker(snap)

        html_doc = wx.CallAfter.call_args.args[1]
        assert "<h2" in html_doc
        assert "<h1" in html_doc

    def test_present_calls_browseable_message_with_html(self):
        import ui
        plugin = _make_plugin()
        ui.browseableMessage.reset_mock()

        plugin._presentBufferWindow("<p>alpha</p>", "some title")

        ui.browseableMessage.assert_called_once()
        kwargs = ui.browseableMessage.call_args.kwargs
        assert ui.browseableMessage.call_args.args[0] == "<p>alpha</p>"
        assert kwargs.get("title") == "some title"
        assert kwargs.get("isHtml") is True
        assert kwargs.get("copyButton") is True

    def test_present_passes_identity_sanitizer(self):
        """We escape on the worker; nh3.clean on the main thread over a
        multi-megabyte document would be a main-thread stall."""
        import ui
        plugin = _make_plugin()
        ui.browseableMessage.reset_mock()

        plugin._presentBufferWindow("<p>x</p>", "t")

        sanitize = ui.browseableMessage.call_args.kwargs.get("sanitizeHtmlFunc")
        assert sanitize is not None
        marker = "<p>already escaped upstream</p>"
        assert sanitize(marker) == marker

    def test_present_survives_browseable_message_failure(self):
        """browseableMessage warns-and-returns on secure desktops and can
        raise on component failure; the user hears a message either way."""
        import ui
        plugin = _make_plugin()
        ui.browseableMessage.side_effect = RuntimeError("no MSHTML")
        ui.message.reset_mock()
        try:
            plugin._presentBufferWindow("<p>x</p>", "t")
        finally:
            ui.browseableMessage.side_effect = None

        ui.message.assert_called_once()
