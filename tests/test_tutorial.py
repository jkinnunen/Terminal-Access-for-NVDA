"""Tests for the first-run tutorial.

The first time a user ever focuses a supported terminal, the addon offers
a short spoken walkthrough of the essential gestures instead of the
one-line "support active" message. The tutorial can be replayed on demand
via the command layer (NVDA+apostrophe, then Shift+H).
"""
from unittest.mock import patch, MagicMock

import pytest


class TestShouldOfferTutorial:
    """should_offer_tutorial reads the tutorialShown flag."""

    def test_true_when_flag_false(self):
        from lib.tutorial import should_offer_tutorial
        config_manager = MagicMock()
        config_manager.get = MagicMock(return_value=False)
        assert should_offer_tutorial(config_manager) is True

    def test_false_when_flag_true(self):
        from lib.tutorial import should_offer_tutorial
        config_manager = MagicMock()
        config_manager.get = MagicMock(return_value=True)
        assert should_offer_tutorial(config_manager) is False


class TestBuildTutorialMessage:
    """build_tutorial_message joins the steps into one spoken string."""

    def test_contains_key_gesture_names(self):
        from lib.tutorial import build_tutorial_message
        message = build_tutorial_message()
        assert "NVDA+apostrophe" in message
        assert "NVDA+F" in message
        assert "Shift+H" in message

    def test_no_em_dashes(self):
        from lib.tutorial import build_tutorial_message
        message = build_tutorial_message()
        assert "—" not in message
        assert " -- " not in message

    def test_joins_all_steps(self):
        from lib.tutorial import build_tutorial_message, TUTORIAL_STEPS
        message = build_tutorial_message()
        for step in TUTORIAL_STEPS:
            assert step in message

    def test_steps_end_with_periods_joined_by_single_space(self):
        from lib.tutorial import build_tutorial_message, TUTORIAL_STEPS
        for step in TUTORIAL_STEPS:
            assert step.endswith(".")
        assert build_tutorial_message() == " ".join(TUTORIAL_STEPS)


class TestConfspec:
    """The tutorialShown flag must be declared in the confspec."""

    def test_tutorialShown_in_confspec(self):
        from lib.config import confspec
        assert "tutorialShown" in confspec
        assert confspec["tutorialShown"] == "boolean(default=False)"

    def test_tutorialShown_validated_as_boolean(self):
        from lib.config import ConfigManager
        manager = ConfigManager()
        assert manager._validate_key("tutorialShown", 1) is True
        assert manager._validate_key("tutorialShown", 0) is False


class TestFirstFocusTutorial:
    """First terminal focus with tutorialShown False speaks the tutorial."""

    def _make_plugin(self, tutorial_shown):
        from globalPlugins.terminalAccess import GlobalPlugin
        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(side_effect=lambda key, default=None: {
            "tutorialShown": tutorial_shown,
        }.get(key, default))
        plugin._configManager.set = MagicMock(return_value=True)
        plugin.announcedHelp = False
        plugin.lastTerminalAppName = None
        return plugin

    def test_first_focus_speaks_tutorial_and_sets_flag(self):
        from lib.tutorial import build_tutorial_message
        plugin = self._make_plugin(tutorial_shown=False)
        import ui
        ui.message = MagicMock()

        plugin._announceHelpIfNeeded('windowsterminal')

        ui.message.assert_called_once_with(build_tutorial_message())
        plugin._configManager.set.assert_called_once_with("tutorialShown", True)

    def test_second_focus_speaks_short_message_only(self):
        from lib.tutorial import build_tutorial_message
        plugin = self._make_plugin(tutorial_shown=True)
        import ui
        ui.message = MagicMock()

        plugin._announceHelpIfNeeded('windowsterminal')

        ui.message.assert_called_once()
        spoken = ui.message.call_args[0][0]
        assert spoken != build_tutorial_message()
        assert "support active" in spoken
        plugin._configManager.set.assert_not_called()

    def test_same_app_refocus_stays_silent(self):
        plugin = self._make_plugin(tutorial_shown=False)
        plugin.announcedHelp = True
        plugin.lastTerminalAppName = 'windowsterminal'
        import ui
        ui.message = MagicMock()

        plugin._announceHelpIfNeeded('windowsterminal')

        ui.message.assert_not_called()


class TestReplayTutorialScript:
    """script_replayTutorial speaks the tutorial on demand."""

    def _make_plugin(self):
        from globalPlugins.terminalAccess import GlobalPlugin
        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(return_value=True)
        return plugin

    def test_replay_speaks_even_when_flag_true(self):
        from lib.tutorial import build_tutorial_message
        plugin = self._make_plugin()
        import ui
        ui.message = MagicMock()
        gesture = MagicMock()

        with patch.object(plugin, 'isTerminalApp', return_value=True):
            plugin.script_replayTutorial(gesture)

        ui.message.assert_called_once_with(build_tutorial_message())
        gesture.send.assert_not_called()

    def test_replay_passes_gesture_through_outside_terminal(self):
        plugin = self._make_plugin()
        import ui
        ui.message = MagicMock()
        gesture = MagicMock()

        with patch.object(plugin, 'isTerminalApp', return_value=False):
            plugin.script_replayTutorial(gesture)

        gesture.send.assert_called_once()
        ui.message.assert_not_called()

    def test_command_layer_binds_shift_h_to_replay(self):
        from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
        assert _COMMAND_LAYER_MAP.get("kb:shift+h") == "replayTutorial"
