"""Tests for the newly wired code-block copy and verbosity-cycle commands."""
import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_plugin():
    from globalPlugins.terminalAccess import GlobalPlugin
    with patch("gui.settingsDialogs.NVDASettingsDialog"):
        plugin = GlobalPlugin()
    plugin.isTerminalApp = MagicMock(return_value=True)
    return plugin


class TestCopyCodeBlock:
    def _plugin_with_buffer(self, buffer, current):
        from lib.code_block_reader import CodeBlockDetector
        plugin = _make_plugin()
        plugin._codeBlockDetector = CodeBlockDetector()
        plugin._getBufferLines = MagicMock(return_value=buffer)
        plugin._getCurrentLineNumber = MagicMock(return_value=current)
        plugin._copyToClipboard = MagicMock(return_value=True)
        sys.modules["ui"].message = MagicMock()
        return plugin

    def test_copies_block_content(self):
        buffer = ["```python", "print('hi')", "x = 1", "```"]
        plugin = self._plugin_with_buffer(buffer, current=1)
        plugin.script_copyCodeBlock(MagicMock())
        plugin._copyToClipboard.assert_called_once()
        copied = plugin._copyToClipboard.call_args[0][0]
        assert "print('hi')" in copied
        assert "x = 1" in copied

    def test_announces_when_not_in_block(self):
        plugin = self._plugin_with_buffer(["plain text", "more text"], current=0)
        plugin.script_copyCodeBlock(MagicMock())
        plugin._copyToClipboard.assert_not_called()
        assert sys.modules["ui"].message.called


class TestCycleVerbosity:
    def _plugin_at_level(self, level):
        plugin = _make_plugin()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(return_value=level)
        sys.modules["ui"].message = MagicMock()
        return plugin

    def test_normal_cycles_to_verbose(self):
        plugin = self._plugin_at_level(1)
        plugin.script_cycleVerbosity(MagicMock())
        plugin._configManager.set.assert_called_once_with("verbosityLevel", 2)
        assert "verbose" in sys.modules["ui"].message.call_args[0][0].lower()

    def test_verbose_wraps_to_quiet(self):
        plugin = self._plugin_at_level(2)
        plugin.script_cycleVerbosity(MagicMock())
        plugin._configManager.set.assert_called_once_with("verbosityLevel", 0)
        assert "quiet" in sys.modules["ui"].message.call_args[0][0].lower()

    def test_quiet_cycles_to_normal(self):
        plugin = self._plugin_at_level(0)
        plugin.script_cycleVerbosity(MagicMock())
        plugin._configManager.set.assert_called_once_with("verbosityLevel", 1)
