"""Tests for _navigateToSection ANSI handling in the main plugin."""
import sys
from unittest.mock import Mock, MagicMock, patch

import pytest

from lib.section_tokenizer import Section


class TestNavigateToSectionAnsi:
    """_navigateToSection fallback must strip ANSI before speaking."""

    def _make_plugin(self):
        """Create a minimal GlobalPlugin instance with _navigateToSection."""
        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()
        return plugin

    def test_fallback_speech_strips_ansi(self):
        """When TextInfo navigation fails, fallback ui.message must not contain ANSI."""
        plugin = self._make_plugin()

        # Set up a terminal mock that raises on makeTextInfo (trigger fallback)
        terminal_mock = Mock()
        terminal_mock.makeTextInfo = Mock(side_effect=RuntimeError("no TextInfo"))
        plugin._boundTerminal = terminal_mock

        # Section with raw ANSI in text
        section = Section(
            line_num=5,
            category="error",
            text="\x1b[31merror: connection refused\x1b[0m",
        )

        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()

        plugin._navigateToSection(section)

        # ui.message should have been called
        ui_mock.message.assert_called_once()
        spoken_text = ui_mock.message.call_args[0][0]

        assert "\x1b" not in spoken_text, (
            f"Fallback speech contains raw ANSI: {repr(spoken_text)}"
        )
        assert "error" in spoken_text.lower()

    def test_fallback_speech_preserves_content(self):
        """Fallback speech should contain the meaningful text without ANSI."""
        plugin = self._make_plugin()

        terminal_mock = Mock()
        terminal_mock.makeTextInfo = Mock(side_effect=RuntimeError("no TextInfo"))
        plugin._boundTerminal = terminal_mock

        section = Section(
            line_num=0,
            category="output",
            text="\x1b[1;34mClaude:\x1b[0m Hello world",
        )

        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()

        plugin._navigateToSection(section)

        spoken_text = ui_mock.message.call_args[0][0]
        assert "Claude:" in spoken_text
        assert "Hello world" in spoken_text

    def test_none_section_beeps(self):
        """Passing None should beep, not crash."""
        plugin = self._make_plugin()
        tones_mock = sys.modules['tones']
        tones_mock.beep = MagicMock()

        plugin._navigateToSection(None)

        tones_mock.beep.assert_called_once()

    def test_no_terminal_returns_silently(self):
        """With no bound terminal, should return without error."""
        plugin = self._make_plugin()
        plugin._boundTerminal = None

        section = Section(line_num=0, category="output", text="test")

        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()

        # Should not crash or speak
        plugin._navigateToSection(section)
