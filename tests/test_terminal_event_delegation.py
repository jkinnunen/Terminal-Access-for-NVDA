"""Tests for the terminal event logic the overlay delegates to the plugin.

After the overlay migration, TerminalAccessTerminal (the NVDAObject overlay)
is the entry point for terminal caret, text-change, and typed-character
events, and delegates to these GlobalPlugin methods. The overlay-side
dispatch is covered in test_terminal_overlay.py; here we test the logic.
"""
from unittest.mock import MagicMock, patch

import pytest


def _plugin(cfg):
    from globalPlugins.terminalAccess import GlobalPlugin
    with patch("gui.settingsDialogs.NVDASettingsDialog"):
        plugin = GlobalPlugin()
    plugin._configManager = MagicMock()
    plugin._configManager.get = MagicMock(side_effect=lambda k, d=None: cfg.get(k, d))
    return plugin


class TestHandleTextChange:
    def _plugin(self, cfg):
        plugin = _plugin(cfg)
        plugin._checkProgressMilestone = MagicMock()
        plugin._checkOutputActivityTone = MagicMock()
        plugin._checkErrorAudioCue = MagicMock()
        return plugin

    def test_normal_mode_returns_true(self):
        plugin = self._plugin({"quietMode": False})
        assert plugin._handleTerminalTextChange(MagicMock()) is True

    def test_quiet_mode_returns_false(self):
        plugin = self._plugin({"quietMode": True})
        assert plugin._handleTerminalTextChange(MagicMock()) is False

    def test_records_text_change_time(self):
        plugin = self._plugin({"quietMode": False})
        plugin._lastTextChangeTime = 0
        plugin._handleTerminalTextChange(MagicMock())
        assert plugin._lastTextChangeTime > 0

    def test_activity_tone_checked_when_enabled(self):
        plugin = self._plugin({"quietMode": False, "outputActivityTones": True})
        plugin._handleTerminalTextChange(MagicMock())
        plugin._checkOutputActivityTone.assert_called_once()

    def test_error_cue_in_quiet_mode(self):
        plugin = self._plugin({
            "quietMode": True,
            "errorAudioCues": True,
            "errorAudioCuesInQuietMode": True,
        })
        plugin._handleTerminalTextChange(MagicMock())
        plugin._checkErrorAudioCue.assert_called_once()


class TestTypedCharacter:
    def _plugin(self, quiet, key_echo):
        plugin = _plugin({})
        plugin._getEffective = MagicMock(side_effect=lambda k, d=None: {
            "quietMode": quiet,
            "keyEcho": key_echo,
            "wordEcho": False,
            "repeatedSymbols": False,
        }.get(k, d))
        # Who echoes is decided in test_typing_echo_ownership.py; these
        # tests cover what the delegate does once that is settled.
        plugin._ownsTypingEcho = MagicMock(
            return_value=bool(key_echo and not quiet))
        plugin._isKeyEchoActive = MagicMock(return_value=key_echo)
        plugin._speakCharacter = MagicMock()
        plugin._positionCalculator = MagicMock()
        plugin._contentGeneration = 0
        return plugin

    def test_quiet_mode_suppresses_default_and_echo(self):
        plugin = self._plugin(quiet=True, key_echo=True)
        speak_default = MagicMock()
        plugin._terminalTypedCharacter(MagicMock(), "a", speak_default)
        speak_default.assert_not_called()
        plugin._speakCharacter.assert_not_called()

    def test_normal_mode_calls_speak_default(self):
        plugin = self._plugin(quiet=False, key_echo=False)
        speak_default = MagicMock()
        plugin._terminalTypedCharacter(MagicMock(), "a", speak_default)
        speak_default.assert_called_once()

    def test_echoes_when_key_echo_active(self):
        plugin = self._plugin(quiet=False, key_echo=True)
        plugin._terminalTypedCharacter(MagicMock(), "a", MagicMock())
        plugin._speakCharacter.assert_called_once_with("a")

    def test_records_typed_char_time(self):
        plugin = self._plugin(quiet=False, key_echo=False)
        plugin._lastTypedCharTime = 0
        plugin._terminalTypedCharacter(MagicMock(), "a", MagicMock())
        assert plugin._lastTypedCharTime > 0


class TestHandleCaret:
    def _plugin(self, cfg):
        plugin = _plugin(cfg)
        plugin._checkOutputActivityTone = MagicMock()
        plugin._checkErrorAudioCue = MagicMock()
        plugin._announceCursorPosition = MagicMock()
        plugin._cursorTrackingTimer = None
        return plugin

    def test_quiet_mode_does_not_schedule_tracking(self):
        plugin = self._plugin({"quietMode": True})
        plugin._handleTerminalCaret(MagicMock())
        assert plugin._cursorTrackingTimer is None

    def test_normal_mode_schedules_tracking(self):
        plugin = self._plugin({
            "quietMode": False,
            "cursorTracking": True,
            "streamingSuppression": False,
            "cursorDelay": 20,
        })
        plugin._handleTerminalCaret(MagicMock())
        assert plugin._cursorTrackingTimer is not None

    def test_no_tracking_when_cursor_tracking_off(self):
        plugin = self._plugin({"quietMode": False, "cursorTracking": False})
        plugin._handleTerminalCaret(MagicMock())
        assert plugin._cursorTrackingTimer is None
