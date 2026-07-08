"""Tests that the verbosity level actually gates optional speech.

The verbosity setting (0 quiet, 1 normal, 2 verbose) controls three
categories of optional speech through lib.audio_cues.should_speak:

- section_context (normal and verbose): the category name when jumping
  to a section, e.g. "error" or "prompt".
- search_count (normal and verbose): the number of matches after a
  successful search.
- profile_detail (verbose only): a short summary of what an activated
  profile overrides.

At quiet verbosity none of these are spoken; only the base feedback
(line content, success beep, profile name) is produced.
"""
import sys
from unittest.mock import Mock, MagicMock, patch

import pytest

from lib.section_tokenizer import Section


def _make_plugin(verbosity):
    """Create a plugin whose config reports the given verbosity level."""
    from globalPlugins.terminalAccess import GlobalPlugin

    with patch('gui.settingsDialogs.NVDASettingsDialog'):
        plugin = GlobalPlugin()
    plugin._configManager = MagicMock()
    plugin._configManager.get = MagicMock(side_effect=lambda key, default=None: {
        "verbosityLevel": verbosity,
    }.get(key, default))
    return plugin


class TestSectionContextVerbosity:
    """Section category is announced at normal and verbose, not at quiet."""

    def _navigate(self, plugin):
        terminal = Mock()
        info = MagicMock()
        info.text = "error: boom"
        terminal.makeTextInfo = Mock(return_value=info)
        plugin._boundTerminal = terminal
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()
        section = Section(line_num=3, category="error", text="error: boom")
        plugin._navigateToSection(section)
        return ui_mock.message

    def test_quiet_does_not_announce_category(self):
        plugin = _make_plugin(0)
        msg = self._navigate(plugin)
        # No section_context speech at quiet verbosity
        for call_args in msg.call_args_list:
            assert "error" not in str(call_args).lower() or "section" not in str(call_args).lower()
        # More precisely: message should not have been used to announce the category
        assert msg.call_count == 0

    def test_normal_announces_category(self):
        plugin = _make_plugin(1)
        msg = self._navigate(plugin)
        assert msg.call_count == 1
        assert "error" in msg.call_args[0][0].lower()

    def test_verbose_announces_category(self):
        plugin = _make_plugin(2)
        msg = self._navigate(plugin)
        assert msg.call_count == 1
        assert "error" in msg.call_args[0][0].lower()

    def test_output_category_not_announced(self):
        """The plain 'output' category is not worth announcing at any level."""
        plugin = _make_plugin(2)
        terminal = Mock()
        info = MagicMock()
        info.text = "just some output"
        terminal.makeTextInfo = Mock(return_value=info)
        plugin._boundTerminal = terminal
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()
        section = Section(line_num=1, category="output", text="just some output")
        plugin._navigateToSection(section)
        assert ui_mock.message.call_count == 0


class TestSearchCountVerbosity:
    """Match count is announced at normal and verbose, not at quiet."""

    def test_quiet_no_count(self):
        plugin = _make_plugin(0)
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()
        result = plugin._handleSearchResult("foo", 5)
        assert result is True  # still signals success to open the dialog
        assert ui_mock.message.call_count == 0

    def test_normal_announces_count(self):
        plugin = _make_plugin(1)
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()
        plugin._handleSearchResult("foo", 5)
        assert ui_mock.message.call_count == 1
        assert "5" in ui_mock.message.call_args[0][0]

    def test_verbose_announces_count(self):
        plugin = _make_plugin(2)
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()
        plugin._handleSearchResult("foo", 12)
        assert ui_mock.message.call_count == 1
        assert "12" in ui_mock.message.call_args[0][0]

    def test_zero_matches_still_announces_failure(self):
        """Zero matches is failure feedback, spoken at every verbosity."""
        plugin = _make_plugin(0)
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()
        result = plugin._handleSearchResult("foo", 0)
        assert result is False
        assert ui_mock.message.call_count == 1


class TestProfileDetailVerbosity:
    """Profile override detail is announced only at verbose."""

    def _activate(self, plugin, profile):
        plugin.lastTerminalAppName = "somethingelse"
        plugin._currentProfile = profile
        ui_mock = sys.modules['ui']
        ui_mock.message = MagicMock()
        plugin._announceProfileIfNew(Mock(), "vim")
        return ui_mock.message

    def _make_profile(self):
        from lib.profiles import ApplicationProfile
        from lib.config import PUNCT_MOST
        prof = ApplicationProfile("vim", "Vim/Neovim")
        prof.punctuationLevel = PUNCT_MOST
        prof.keyEcho = False
        return prof

    def test_normal_announces_name_only(self):
        plugin = _make_plugin(1)
        prof = self._make_profile()
        msg = self._activate(plugin, prof)
        assert msg.call_count == 1
        assert msg.call_args[0][0] == "Vim/Neovim"

    def test_verbose_announces_detail(self):
        plugin = _make_plugin(2)
        prof = self._make_profile()
        msg = self._activate(plugin, prof)
        assert msg.call_count == 1
        spoken = msg.call_args[0][0]
        assert "Vim/Neovim" in spoken
        # Verbose appends something beyond the bare name
        assert len(spoken) > len("Vim/Neovim")

    def test_quiet_announces_name_only(self):
        plugin = _make_plugin(0)
        prof = self._make_profile()
        msg = self._activate(plugin, prof)
        assert msg.call_count == 1
        assert msg.call_args[0][0] == "Vim/Neovim"
