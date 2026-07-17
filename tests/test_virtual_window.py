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


class TestBuildJumpRows:
    """Rows for the jump dialog: every line, with its command context."""

    def _rows(self, lines, max_lines=None):
        from lib.list_dialogs import build_jump_rows
        from lib.section_tokenizer import SectionTokenizer

        snap = _snapshot(lines=lines) if max_lines is None else None
        if snap is None:
            term = Mock()
            term.appModule.appName = "wt"
            snap = BufferSnapshot.capture(term, list(lines), max_lines=max_lines)
        tok = SectionTokenizer()
        sections = tok.tokenize(snap.lines)
        return build_jump_rows(snap, sections)

    def test_one_row_per_line(self):
        rows = self._rows(["a", "b", "c"])
        assert len(rows) == 3

    def test_row_carries_absolute_number_and_text(self):
        rows = self._rows(["alpha", "beta"])
        assert rows[0][:2] == (0, "alpha")
        assert rows[1][:2] == (1, "beta")

    def test_absolute_numbers_survive_truncation(self):
        rows = self._rows([f"line {i}" for i in range(30)], max_lines=20)
        assert rows[0][0] == 10
        assert rows[0][1] == "line 10"

    def test_context_is_the_governing_command(self):
        rows = self._rows([
            "PS C:\\repo> npm run build",
            "compiling",
            "done",
        ])
        assert "npm run build" in rows[1][2]
        assert "npm run build" in rows[2][2]

    def test_prompt_row_is_its_own_context(self):
        rows = self._rows([
            "PS C:\\repo> first",
            "out",
            "PS C:\\repo> second",
        ])
        assert "second" in rows[2][2]
        assert "first" not in rows[2][2]

    def test_lines_before_any_prompt_have_empty_context(self):
        rows = self._rows(["banner text", "PS C:\\repo> go"])
        assert rows[0][2] == ""


class TestJumpDialogScript:
    def test_script_exists_and_gestures_bound(self):
        from globalPlugins.terminalAccess import (
            GlobalPlugin,
            _COMMAND_LAYER_MAP,
            _DEFAULT_GESTURES,
        )
        assert hasattr(GlobalPlugin, "script_jumpToBufferLine")
        assert _DEFAULT_GESTURES.get("kb:NVDA+shift+enter") == "jumpToBufferLine"
        assert _COMMAND_LAYER_MAP.get("kb:shift+enter") == "jumpToBufferLine"

    def test_passes_through_outside_terminal(self):
        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=False)
        gesture = MagicMock()

        plugin.script_jumpToBufferLine(gesture)

        gesture.send.assert_called_once()

    def test_activation_sets_jump_target_by_content(self):
        """Selection arms the SAME reapply machinery the search dialog
        uses: _searchJumpPending plus a (text, line_num) target that the
        focus-return handler resolves by content, never by counting."""
        plugin = _make_plugin()
        plugin._boundTerminal = Mock()
        snap = _snapshot(lines=("PS C:\\repo> run", "output line"))
        rows = [(0, "PS C:\\repo> run", ""), (1, "output line", "PS C:\\repo> run")]

        with patch("lib.list_dialogs.BrowsableListDialog") as dlg_cls:
            plugin._showJumpToLineDialog(snap, rows)

        on_activate = dlg_cls.call_args.kwargs.get("on_activate")
        if on_activate is None:
            on_activate = dlg_cls.call_args.args[4]
        plugin._searchJumpPending = False
        plugin._searchJumpTarget = None

        on_activate(1)

        assert plugin._searchJumpPending is True
        assert plugin._searchJumpTarget == ("output line", 1)

    def test_activation_with_terminal_gone_announces_instead(self):
        import ui
        plugin = _make_plugin()
        plugin._boundTerminal = None
        snap = _snapshot()
        rows = [(0, "alpha", "")]

        with patch("lib.list_dialogs.BrowsableListDialog") as dlg_cls:
            plugin._showJumpToLineDialog(snap, rows)
        on_activate = dlg_cls.call_args.kwargs.get("on_activate")
        if on_activate is None:
            on_activate = dlg_cls.call_args.args[4]
        plugin._searchJumpPending = False
        ui.message.reset_mock()

        on_activate(0)

        assert plugin._searchJumpPending is False
        ui.message.assert_called_once()


class TestReapplyFallbackAnnouncement:
    """The shared reapply path speaks up when the line cannot be reached.

    Both search jumps and buffer jumps land through _reapplySearchJump.
    It retries once after NVDA's focus transition; when every attempt
    fails to resolve the line (scrolled out of history), the user must
    hear that, not silence. Exactly one announcement, after the LAST
    attempt only.
    """

    def _armed_plugin(self, resolves):
        plugin = _make_plugin()
        plugin._searchJumpTarget = ("some line", 5)
        mgr = Mock()
        mgr._resolve_line_by_content = Mock(
            return_value=Mock() if resolves else None
        )
        plugin._searchManager = mgr
        plugin._scheduleSearchJumpReapply()
        return plugin

    def test_failure_announced_once_after_final_attempt(self):
        import ui
        plugin = self._armed_plugin(resolves=False)
        ui.message.reset_mock()

        plugin._reapplySearchJump()
        assert ui.message.call_count == 0

        plugin._reapplySearchJump()
        assert ui.message.call_count == 1

    def test_no_announcement_when_the_jump_resolves(self):
        import ui
        plugin = self._armed_plugin(resolves=True)
        ui.message.reset_mock()

        plugin._reapplySearchJump()
        plugin._reapplySearchJump()

        assert ui.message.call_count == 0

    def test_success_on_retry_is_not_a_failure(self):
        """First attempt misses (NVDA still rebinding), second lands."""
        import ui
        plugin = self._armed_plugin(resolves=False)
        ui.message.reset_mock()

        plugin._reapplySearchJump()
        plugin._searchManager._resolve_line_by_content.return_value = Mock()
        plugin._reapplySearchJump()

        assert ui.message.call_count == 0
