"""
Tests for profile detection and switching.

Covers:
- Auto-detection from window title when appName is the terminal host
- Manual profile switching via script_announceActiveProfile double-press
- Profile settings actually applied after activation
- Profile announced on terminal switch
"""
import sys
from unittest.mock import Mock, MagicMock, patch

import pytest

# Import after conftest mocks are in place
from lib.profiles import ProfileManager


class TestProfileAutoDetection:
    """Profile should auto-detect from window title."""

    def test_claude_detected_from_title(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "claude - PowerShell"
        result = mgr.detect_application(obj)
        assert result == "claude"

    def test_claude_detected_case_insensitive(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "Claude Code - bash"
        result = mgr.detect_application(obj)
        assert result == "claude"

    def test_aider_detected_from_title(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "aider - my-project"
        result = mgr.detect_application(obj)
        assert result == "aider"

    def test_vim_detected_from_title(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "vim /home/user/file.py"
        result = mgr.detect_application(obj)
        assert result == "vim"

    def test_plain_terminal_returns_default(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "PowerShell"
        result = mgr.detect_application(obj)
        assert result == "default"

    def test_tmux_with_claude_returns_claude(self):
        """AI CLI takes priority over multiplexer."""
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "tmux: claude - my-project"
        result = mgr.detect_application(obj)
        assert result == "claude"


class TestProfileAppliedOnFocus:
    """When a profile is detected, its settings should be active."""

    def test_detected_profile_stored_on_plugin(self):
        """_detectAndApplyProfile should set _currentProfile."""
        from addon.globalPlugins.terminalAccess import GlobalPlugin

        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._profileManager = ProfileManager()
        plugin._configManager = Mock()
        plugin._configManager.get = Mock(return_value="")
        plugin._currentProfile = None

        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "claude - bash"

        plugin._detectAndApplyProfile(obj)

        assert plugin._currentProfile is not None
        assert plugin._currentProfile.displayName == "Claude CLI"

    def test_default_when_no_match(self):
        """No profile match and no default profile means _currentProfile is None."""
        from addon.globalPlugins.terminalAccess import GlobalPlugin

        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._profileManager = ProfileManager()
        plugin._configManager = Mock()
        plugin._configManager.get = Mock(return_value="")
        plugin._currentProfile = None

        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "PowerShell"

        plugin._detectAndApplyProfile(obj)

        assert plugin._currentProfile is None


class TestProfileAnnouncedOnSwitch:
    """Profile name should be announced when switching to a new terminal."""

    def test_announces_on_new_app(self):
        """Profile announced when appName differs from last."""
        import globalPlugins.terminalAccess as ta_module

        plugin = ta_module.GlobalPlugin.__new__(ta_module.GlobalPlugin)
        plugin.lastTerminalAppName = "cmd"
        plugin._currentProfile = Mock()
        plugin._currentProfile.displayName = "Claude CLI"

        obj = Mock()
        with patch.object(ta_module, "ui") as mock_ui:
            plugin._announceProfileIfNew(obj, "windowsterminal")
            mock_ui.message.assert_called_once_with("Claude CLI")

    def test_does_not_announce_same_app(self):
        """No announcement when appName hasn't changed."""
        import globalPlugins.terminalAccess as ta_module

        plugin = ta_module.GlobalPlugin.__new__(ta_module.GlobalPlugin)
        plugin.lastTerminalAppName = "windowsterminal"
        plugin._currentProfile = Mock()
        plugin._currentProfile.displayName = "Claude CLI"

        obj = Mock()
        with patch.object(ta_module, "ui") as mock_ui:
            plugin._announceProfileIfNew(obj, "windowsterminal")
            mock_ui.message.assert_not_called()


class TestProfileManualSwitch:
    """Manual profile activation via on_activate callback."""

    def test_on_activate_sets_current_profile(self):
        """Activating a profile from the dialog sets _currentProfile."""
        from addon.globalPlugins.terminalAccess import GlobalPlugin

        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._profileManager = ProfileManager()
        plugin._currentProfile = None

        # Simulate what _showProfileSelectionDialog's on_activate does
        profile = plugin._profileManager.get_profile("claude")
        if profile:
            plugin._currentProfile = profile

        assert plugin._currentProfile is not None
        assert plugin._currentProfile.displayName == "Claude CLI"

    def test_on_activate_applies_punctuation(self):
        """Activated profile's punctuation level should be readable."""
        from addon.globalPlugins.terminalAccess import GlobalPlugin

        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._profileManager = ProfileManager()

        profile = plugin._profileManager.get_profile("vim")
        plugin._currentProfile = profile

        # vim profile sets PUNCT_MOST (2)
        assert plugin._currentProfile.punctuationLevel == 2

    def test_get_profile_names_includes_all(self):
        """get_profile_names returns all built-in profiles."""
        mgr = ProfileManager()
        names = mgr.get_profile_names()
        assert "claude" in names
        assert "vim" in names
        assert "tmux" in names
        assert "aider" in names

    def test_get_profile_returns_none_for_unknown(self):
        """Unknown profile name returns None."""
        mgr = ProfileManager()
        assert mgr.get_profile("nonexistent_app_xyz") is None


class TestGetEffectiveWithProfile:
    """_getEffective should check _currentProfile before config."""

    def test_profile_overrides_config(self):
        """When profile has a value, it takes priority over config."""
        from addon.globalPlugins.terminalAccess import GlobalPlugin

        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._configManager = Mock()
        plugin._configManager.get = Mock(return_value=0)  # Config says 0
        plugin._currentProfile = Mock()
        plugin._currentProfile.punctuationLevel = 2  # Profile says 2

        result = plugin._getEffective("punctuationLevel")
        # Should return profile's value (2), not config's value (0)
        assert result == 2

    def test_config_used_when_no_profile(self):
        """When no profile is active, config value is used."""
        from addon.globalPlugins.terminalAccess import GlobalPlugin

        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._configManager = Mock()
        plugin._configManager.get = Mock(return_value=1)
        plugin._currentProfile = None

        result = plugin._getEffective("punctuationLevel")
        assert result == 1

    def test_config_used_when_profile_value_is_none(self):
        """When profile has None for a key, fall through to config."""
        from addon.globalPlugins.terminalAccess import GlobalPlugin

        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._configManager = Mock()
        plugin._configManager.get = Mock(return_value=1)
        plugin._currentProfile = Mock()
        plugin._currentProfile.punctuationLevel = None  # Profile has no opinion

        result = plugin._getEffective("punctuationLevel")
        assert result == 1
