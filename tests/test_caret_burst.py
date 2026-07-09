"""Tests for output-induced caret suppression (output grace period).

When terminal output streams rapidly (AI CLI, cargo build, npm install),
textChange and caret events fire in quick succession. The plugin records
_lastTextChangeTime on every textChange and suppresses caret character
announcements for _OUTPUT_CARET_GRACE seconds afterwards, so cursor
movement caused by program output does not flood speech. User-initiated
reading commands must never be suppressed by this mechanism.
"""
import time
from unittest.mock import patch

import pytest


class TestUserCommandsDuringOutputGrace:
    """User-initiated reading commands must NEVER be suppressed by the grace period."""

    def _make_plugin_with_recent_output(self):
        """Create a GlobalPlugin that just received a textChange event."""
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        # Simulate program output arriving right now
        plugin._lastTextChangeTime = time.monotonic()
        return plugin

    def test_read_current_line_speaks_during_output_grace(self):
        """NVDA+I (read current line) must speak even inside the grace window."""
        from unittest.mock import MagicMock, patch
        plugin = self._make_plugin_with_recent_output()
        plugin._boundTerminal = MagicMock()

        gesture = MagicMock()
        # script_readCurrentLine delegates to _readLineWithIndentation.
        # It must NOT consult the output grace timestamp at all.
        with patch.object(plugin, 'isTerminalApp', return_value=True):
            with patch.object(plugin, '_readLineWithIndentation') as mock_read:
                plugin.script_readCurrentLine(gesture)
                mock_read.assert_called_once()

    def test_navigate_section_speaks_during_output_grace(self):
        """Section navigation must speak even inside the grace window."""
        from unittest.mock import MagicMock
        from lib.section_tokenizer import Section
        import sys

        plugin = self._make_plugin_with_recent_output()
        plugin._boundTerminal = MagicMock()
        plugin._boundTerminal.makeTextInfo = MagicMock(side_effect=RuntimeError("test"))

        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()

        section = Section(line_num=0, category="error", text="error: fail")
        plugin._navigateToSection(section)

        # Should have spoken despite recent output
        ui_mock.message.assert_called_once()


class TestTextChangeAlwaysWakesPipeline:
    """event_textChange must always call nextHandler -- it wakes the
    monitor thread which produces the coalesced line output. Only caret
    character speech is suppressed during streaming, not line output."""

    def _make_plugin(self):
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        plugin._boundTerminal = MagicMock()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(side_effect=lambda key, default=None: {
            "quietMode": False,
            "outputActivityTones": False,
            "streamingSuppression": True,
        }.get(key, default))
        return plugin

    def test_textChange_signals_speech_during_rapid_output(self):
        """Rapid successive textChange events must each signal the overlay
        to wake the monitor (return True in normal mode)."""
        from unittest.mock import MagicMock

        plugin = self._make_plugin()

        obj = MagicMock()
        # Simulate a streaming burst: several textChange events back to back
        results = [plugin._handleTerminalTextChange(obj) for _ in range(5)]

        assert results == [True, True, True, True, True]

    def test_textChange_signals_speech_after_idle(self):
        """A lone textChange (no recent output) signals speech normally."""
        from unittest.mock import MagicMock

        plugin = self._make_plugin()

        obj = MagicMock()
        assert plugin._handleTerminalTextChange(obj) is True


class TestOutputGracePreservesAudioCues:
    """Audio cues (tones) must still fire during streaming -- only caret speech is suppressed."""

    def test_activity_tones_fire_during_streaming(self):
        """Output activity tones must still play while output streams."""
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        plugin._boundTerminal = MagicMock()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(side_effect=lambda key, default=None: {
            "quietMode": False,
            "outputActivityTones": True,
            "streamingSuppression": True,
        }.get(key, default))

        # Simulate output that arrived moments ago (inside the grace window)
        plugin._lastTextChangeTime = time.monotonic()

        with patch.object(plugin, '_checkOutputActivityTone') as mock_tone:
            plugin._handleTerminalTextChange(MagicMock())
            mock_tone.assert_called_once()

    def test_streaming_delta_speaks_during_output_grace(self):
        """NVDA+Shift+D (streaming delta) must speak even inside the grace window."""
        import sys
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        plugin._boundTerminal = MagicMock()

        # Simulate output that arrived moments ago
        plugin._lastTextChangeTime = time.monotonic()

        # script_whatChanged uses _getBufferLines + _deltaTracker,
        # not event_caret. It should always speak.
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()

        with patch.object(plugin, 'isTerminalApp', return_value=True):
            with patch.object(plugin, '_getBufferLines', return_value=["line1", "line2"]):
                with patch.object(plugin, '_ensureDeltaTracker'):
                    plugin._deltaTracker = MagicMock()
                    plugin._deltaTracker.take_snapshot = MagicMock(return_value="2 new lines")
                    plugin._deltaTracker.has_previous = True
                    plugin._deltaTracker.get_braille_delta = MagicMock(return_value=None)

                    gesture = MagicMock()
                    plugin.script_whatChanged(gesture)

                    ui_mock.message.assert_called_with("2 new lines")


class TestOverlayReportNewLines:
    """Overlay _reportNewLines is the coalesced line-level announcement
    and must always speak, including during streaming output."""

    def test_reportNewLines_speaks_during_streaming_output(self):
        """Multiple rapid lines must still be spoken (small batch: all lines)."""
        from unittest.mock import MagicMock
        from lib.terminal_overlay import TerminalAccessTerminal

        overlay = TerminalAccessTerminal()
        overlay._configManager = MagicMock()
        overlay._configManager.get = MagicMock(return_value=True)

        # Simulate rapid textChange events preceding the report
        for _ in range(5):
            overlay.event_textChange()

        import sys
        speech_mock = sys.modules.get('speech')
        if speech_mock:
            speech_mock.speakText = MagicMock()

        overlay._reportNewLines(["line1", "line2", "line3"])

        if speech_mock:
            speech_mock.speakText.assert_called()

    def test_reportNewLines_speaks_single_line(self):
        """A single output line is spoken normally."""
        from unittest.mock import MagicMock
        from lib.terminal_overlay import TerminalAccessTerminal

        overlay = TerminalAccessTerminal()
        overlay._configManager = MagicMock()
        overlay._configManager.get = MagicMock(return_value=True)

        import sys
        speech_mock = sys.modules.get('speech')
        if speech_mock:
            speech_mock.speakText = MagicMock()

        overlay._reportNewLines(["output line"])

        if speech_mock:
            speech_mock.speakText.assert_called()


class TestAnnounceCursorPositionRechecksOutputGrace:
    """_announceCursorPosition must re-check output grace when callback fires."""

    def test_announceCursorPosition_suppressed_if_textChange_arrived_after_scheduling(self):
        """If textChange arrives after CallLater scheduled but before it fires, suppress."""
        import time
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        plugin._boundTerminal = MagicMock()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(side_effect=lambda key, default=None: {
            "streamingSuppression": True,
            "cursorTrackingMode": 1,
        }.get(key, default))

        # Simulate textChange arriving just now (after the timer was scheduled)
        plugin._lastTextChangeTime = time.monotonic()

        with patch.object(plugin, '_announceStandardCursor') as mock_announce:
            plugin._announceCursorPosition(MagicMock())
            mock_announce.assert_not_called()


class TestTextChangeRecordsTimestamp:
    """event_textChange must record timestamp for output-induced caret suppression."""

    def test_textChange_sets_lastTextChangeTime(self):
        """event_textChange must set _lastTextChangeTime."""
        import time
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        plugin._boundTerminal = MagicMock()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(side_effect=lambda key, default=None: {
            "quietMode": False,
            "outputActivityTones": False,
        }.get(key, default))

        before = time.monotonic()
        plugin._handleTerminalTextChange(MagicMock())
        after = time.monotonic()

        assert before <= plugin._lastTextChangeTime <= after


class TestOutputGraceConfig:
    """Config integration: streamingSuppression setting controls the feature."""

    def test_confspec_has_streaming_suppression(self):
        """streamingSuppression must exist in confspec."""
        from lib.config import confspec
        assert "streamingSuppression" in confspec

    def test_plugin_has_lastTextChangeTime(self):
        """GlobalPlugin must have _lastTextChangeTime for output grace period."""
        from unittest.mock import patch
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()
        assert hasattr(plugin, '_lastTextChangeTime')

    def test_event_caret_suppresses_after_textChange(self):
        """When textChange just fired, event_caret skips announcement."""
        import time
        from unittest.mock import patch, MagicMock
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

        # Simulate textChange just now
        plugin._lastTextChangeTime = time.monotonic()

        with patch('wx.CallLater') as mock_call_later:
            plugin._handleTerminalCaret(MagicMock())
            mock_call_later.assert_not_called()
