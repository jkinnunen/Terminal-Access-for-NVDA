"""Tests for CaretBurstDetector: streaming output suppression.

When terminal output streams rapidly (AI CLI, cargo build, npm install),
caret events fire faster than human navigation. The burst detector
identifies these bursts and suppresses per-character speech to avoid
a flood of extraneous announcements.
"""
import time
from unittest.mock import patch

import pytest


class TestBurstDetectorBasic:
    """Core burst detection: distinguish streaming from navigation."""

    def test_single_event_not_burst(self):
        """A single caret event is never a burst."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector()
        assert detector.should_speak() is True

    def test_slow_events_not_burst(self):
        """Events spaced > 200ms apart are human navigation, not streaming."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector(burst_threshold_ms=200, burst_count=3)
        for _ in range(5):
            detector.record_event(time.monotonic())
            time.sleep(0.25)  # 250ms apart
        assert detector.should_speak() is True

    def test_rapid_events_trigger_burst(self):
        """Events arriving faster than threshold are a streaming burst."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector(burst_threshold_ms=100, burst_count=3)
        now = time.monotonic()
        # Simulate 5 events within 50ms each
        for i in range(5):
            detector.record_event(now + i * 0.03)  # 30ms apart
        assert detector.should_speak() is False

    def test_burst_ends_after_gap(self):
        """After a gap longer than threshold, burst ends and speech resumes."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector(burst_threshold_ms=100, burst_count=3)
        now = time.monotonic()
        # Rapid burst
        for i in range(5):
            detector.record_event(now + i * 0.03)
        assert detector.should_speak() is False

        # Gap of 200ms
        detector.record_event(now + 0.5)
        assert detector.should_speak() is True


class TestBurstDetectorEdgeCases:
    """Edge cases for the burst detector."""

    def test_exactly_threshold_events(self):
        """Exactly burst_count events at threshold speed triggers burst."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector(burst_threshold_ms=100, burst_count=3)
        now = time.monotonic()
        for i in range(3):
            detector.record_event(now + i * 0.05)  # 50ms apart, 3 events
        assert detector.should_speak() is False

    def test_below_threshold_count_no_burst(self):
        """Fewer than burst_count rapid events do not trigger burst."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector(burst_threshold_ms=100, burst_count=5)
        now = time.monotonic()
        for i in range(3):  # Only 3, need 5
            detector.record_event(now + i * 0.03)
        assert detector.should_speak() is True

    def test_reset_clears_burst_state(self):
        """reset() clears burst state."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector(burst_threshold_ms=100, burst_count=3)
        now = time.monotonic()
        for i in range(5):
            detector.record_event(now + i * 0.03)
        assert detector.should_speak() is False

        detector.reset()
        assert detector.should_speak() is True

    def test_no_events_recorded_should_speak(self):
        """Before any events are recorded, should_speak returns True."""
        from lib.streaming_delta import CaretBurstDetector

        detector = CaretBurstDetector()
        assert detector.should_speak() is True


class TestBurstDoesNotAffectUserCommands:
    """User-initiated reading commands must NEVER be suppressed by burst detection."""

    def _make_plugin_in_burst(self):
        """Create a GlobalPlugin with burst detector in active burst state."""
        import time
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        # Force into burst state
        now = time.monotonic()
        for i in range(10):
            plugin._burstDetector.record_event(now + i * 0.02)
        assert plugin._burstDetector.should_speak() is False
        return plugin

    def test_read_current_line_speaks_during_burst(self):
        """NVDA+I (read current line) must speak even during a burst."""
        from unittest.mock import MagicMock, patch
        plugin = self._make_plugin_in_burst()
        plugin._boundTerminal = MagicMock()

        gesture = MagicMock()
        # script_readCurrentLine delegates to globalCommands, not event_caret
        # It should NOT check the burst detector at all
        with patch.object(plugin, 'isTerminalApp', return_value=True):
            with patch.object(plugin, '_readLineWithIndentation') as mock_read:
                plugin.script_readCurrentLine(gesture)
                mock_read.assert_called_once()

    def test_navigate_section_speaks_during_burst(self):
        """Section navigation must speak even during a burst."""
        from unittest.mock import MagicMock
        from lib.section_tokenizer import Section
        import sys

        plugin = self._make_plugin_in_burst()
        plugin._boundTerminal = MagicMock()
        plugin._boundTerminal.makeTextInfo = MagicMock(side_effect=RuntimeError("test"))

        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()

        section = Section(line_num=0, category="error", text="error: fail")
        plugin._navigateToSection(section)

        # Should have spoken despite burst state
        ui_mock.message.assert_called_once()


class TestTextChangeStreamingSuppression:
    """event_textChange must also suppress NVDA native speech during streaming."""

    def test_textChange_still_calls_nextHandler_during_burst(self):
        """event_textChange must ALWAYS call nextHandler -- it wakes the
        monitor thread which triggers _reportNewLines (coalesced output).
        Only per-character caret speech should be suppressed, not line output."""
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
            "streamingSuppression": True,
        }.get(key, default))

        # Force into burst state
        now = time.monotonic()
        for i in range(10):
            plugin._burstDetector.record_event(now + i * 0.02)

        nextHandler = MagicMock()
        obj = MagicMock()
        plugin.event_textChange(obj, nextHandler)

        # nextHandler MUST still be called -- it wakes the output pipeline
        nextHandler.assert_called_once()

    def test_textChange_calls_nextHandler_when_no_burst(self):
        """When no burst, event_textChange should call nextHandler normally."""
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

        # No burst recorded
        nextHandler = MagicMock()
        obj = MagicMock()
        plugin.event_textChange(obj, nextHandler)

        # nextHandler SHOULD be called
        nextHandler.assert_called_once()


class TestBurstPreservesAudioCues:
    """Audio cues (tones) must still fire during bursts -- only speech is suppressed."""

    def test_activity_tones_fire_during_burst(self):
        """Output activity tones must still play during a streaming burst."""
        import time
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

        # Force burst
        now = time.monotonic()
        for i in range(10):
            plugin._burstDetector.record_event(now + i * 0.02)

        with patch.object(plugin, '_checkOutputActivityTone') as mock_tone:
            plugin.event_textChange(MagicMock(), MagicMock())
            mock_tone.assert_called_once()

    def test_streaming_delta_speaks_during_burst(self):
        """NVDA+Shift+D (streaming delta) must speak during a burst."""
        import time
        import sys
        from unittest.mock import patch, MagicMock
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

        plugin._boundTerminal = MagicMock()

        # Force burst
        now = time.monotonic()
        for i in range(10):
            plugin._burstDetector.record_event(now + i * 0.02)

        # script_streamingDelta uses _getBufferLines + _deltaTracker,
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


class TestOverlayReportNewLinesSuppression:
    """_reportNewLines in the overlay must be suppressed during burst."""

    def test_reportNewLines_STILL_speaks_during_burst(self):
        """Overlay _reportNewLines must ALWAYS speak -- it's the coalesced
        line-level announcement, not extraneous character noise."""
        import time
        from unittest.mock import MagicMock
        from lib.terminal_overlay import TerminalAccessTerminal
        from lib.streaming_delta import CaretBurstDetector

        overlay = TerminalAccessTerminal()
        detector = CaretBurstDetector(burst_threshold_ms=100, burst_count=3)
        overlay._burstDetector = detector
        overlay._configManager = MagicMock()
        overlay._configManager.get = MagicMock(return_value=True)

        # Force burst
        now = time.monotonic()
        for i in range(5):
            detector.record_event(now + i * 0.02)
        assert detector.should_speak() is False

        import sys
        speech_mock = sys.modules.get('speech')
        if speech_mock:
            speech_mock.speakText = MagicMock()

        overlay._reportNewLines(["line1", "line2", "line3"])

        # _reportNewLines MUST still speak even during burst
        if speech_mock:
            speech_mock.speakText.assert_called()

    def test_reportNewLines_speaks_when_no_burst(self):
        """Overlay _reportNewLines must speak normally when no burst."""
        from unittest.mock import MagicMock
        from lib.terminal_overlay import TerminalAccessTerminal
        from lib.streaming_delta import CaretBurstDetector

        overlay = TerminalAccessTerminal()
        detector = CaretBurstDetector()
        overlay._burstDetector = detector
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
        plugin.event_textChange(MagicMock(), MagicMock())
        after = time.monotonic()

        assert before <= plugin._lastTextChangeTime <= after


class TestBurstDetectorConfig:
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
            plugin.event_caret(MagicMock(), MagicMock())
            mock_call_later.assert_not_called()
