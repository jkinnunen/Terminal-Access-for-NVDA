"""Tests for output-induced caret suppression.

When program output arrives, two events fire in sequence:
  textChange (content added) -> caret (cursor moved to end of output)

The caret movement is a side effect of output, not user navigation.
Character-level speech from event_caret should be suppressed when
it follows a textChange within the output grace period.

Arrow key navigation (no preceding textChange) must always speak.
"""
import time
from unittest.mock import patch, MagicMock

import pytest


class TestOutputInducedCaretSuppression:
    """event_caret must suppress character speech when preceded by textChange."""

    def _make_plugin(self):
        from globalPlugins.terminalAccess import GlobalPlugin
        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()
        plugin._boundTerminal = MagicMock()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(side_effect=lambda key, default=None: {
            "quietMode": False,
            "outputActivityTones": False,
            "cursorTracking": True,
            "cursorDelay": 20,
            "streamingSuppression": True,
        }.get(key, default))
        return plugin

    def test_caret_after_textChange_suppressed(self):
        """Caret event immediately after textChange should not schedule speech."""
        plugin = self._make_plugin()

        # Simulate textChange then caret in quick succession
        plugin._handleTerminalTextChange(MagicMock())

        with patch('wx.CallLater') as mock_later:
            plugin._handleTerminalCaret(MagicMock())
            # Should NOT schedule character announcement
            mock_later.assert_not_called()

    def test_caret_without_textChange_speaks(self):
        """Caret event without preceding textChange (arrow key) should speak."""
        plugin = self._make_plugin()

        # No textChange -- simulate arrow key navigation
        # Ensure _lastTextChangeTime is old (or unset)
        plugin._lastTextChangeTime = 0

        with patch('wx.CallLater') as mock_later:
            plugin._handleTerminalCaret(MagicMock())
            # SHOULD schedule character announcement
            mock_later.assert_called_once()

    def test_caret_long_after_textChange_speaks(self):
        """Caret event well after textChange (user navigated) should speak."""
        plugin = self._make_plugin()

        # textChange happened 500ms ago
        plugin._lastTextChangeTime = time.monotonic() - 0.5

        with patch('wx.CallLater') as mock_later:
            plugin._handleTerminalCaret(MagicMock())
            # SHOULD speak -- enough time passed that this is user nav
            mock_later.assert_called_once()

    def test_textChange_sets_timestamp(self):
        """event_textChange must record its timestamp for caret suppression."""
        plugin = self._make_plugin()

        before = time.monotonic()
        plugin._handleTerminalTextChange(MagicMock())
        after = time.monotonic()

        assert hasattr(plugin, '_lastTextChangeTime')
        assert before <= plugin._lastTextChangeTime <= after

    def test_user_commands_not_affected(self):
        """NVDA+I (script_readCurrentLine) must speak even after textChange."""
        plugin = self._make_plugin()

        # Simulate textChange just now
        plugin._handleTerminalTextChange(MagicMock())

        gesture = MagicMock()
        with patch.object(plugin, 'isTerminalApp', return_value=True):
            with patch.object(plugin, '_readLineWithIndentation') as mock_read:
                plugin.script_readCurrentLine(gesture)
                # User command always speaks
                mock_read.assert_called_once()

    def test_reportNewLines_not_affected(self):
        """Overlay _reportNewLines must still speak (it's the good speech)."""
        import sys
        from lib.terminal_overlay import TerminalAccessTerminal

        overlay = TerminalAccessTerminal()
        overlay._configManager = MagicMock()
        overlay._configManager.get = MagicMock(return_value=True)

        speech_mock = sys.modules.get('speech')
        if speech_mock:
            speech_mock.speakText = MagicMock()

        overlay._reportNewLines(["Compiling mycrate v0.1.0"])

        if speech_mock:
            speech_mock.speakText.assert_called()
