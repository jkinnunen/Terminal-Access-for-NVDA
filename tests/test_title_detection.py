"""
Tests for window title-based profile detection.

The bug: detect_application checked focusObject.name for the window title,
but the focus object inside a terminal is the text area, not the window.
The window title is on api.getForegroundObject().name.
"""
from unittest.mock import Mock, MagicMock, patch
import sys

import pytest

from lib.profiles import ProfileManager


class TestFocusObjectVsForegroundObject:
    """Profile detection should use the foreground object's name for title."""

    def test_focus_obj_name_empty_foreground_has_title(self):
        """Focus object has empty name, foreground has the window title."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = ""  # Text area has no name

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "✳ Claude Code"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "claude"

    def test_focus_obj_name_is_text_area(self):
        """Focus object name is 'Text Area', foreground has real title."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "Text Area"

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "vim /home/user/file.py"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "vim"

    def test_claude_code_with_star(self):
        """Window title '✳ Claude Code' should detect claude profile."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = ""

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "✳ Claude Code"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "claude"

    def test_aider_in_tmux_title(self):
        """Foreground title 'tmux: aider session' should detect aider."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = ""

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "tmux: aider session"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "aider"

    def test_gemini_foreground_title(self):
        """Foreground title with Gemini should detect gemini profile."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = ""

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "gemini - conversation"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "gemini"

    def test_codex_foreground_title(self):
        """Foreground title with Codex should detect codex profile."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = ""

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "codex - my-project"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "codex"

    def test_plain_powershell_returns_default(self):
        """Plain terminal with no AI tool returns default."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = ""

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "Windows PowerShell"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "default"

    def test_fallback_to_focus_name_when_foreground_unavailable(self):
        """If api.getForegroundObject() fails, fall back to obj.name."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "vim /tmp/test.py"

        api_mock = sys.modules["api"]
        api_mock.getForegroundObject = Mock(side_effect=RuntimeError("no foreground"))

        result = mgr.detect_application(obj)
        assert result == "vim"

    def test_pytest_detected_from_foreground(self):
        """pytest in foreground title should detect pytest profile."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = ""

        api_mock = sys.modules["api"]
        fg = Mock()
        fg.name = "pytest - tests/test_main.py"
        api_mock.getForegroundObject = Mock(return_value=fg)

        result = mgr.detect_application(obj)
        assert result == "pytest"
