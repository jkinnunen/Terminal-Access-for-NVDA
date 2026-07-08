"""Tests for progress milestone announcements.

Streaming suppression silences per-character speech during rapid output,
which leaves users with no progress feedback during long operations.
ProgressMilestoneTracker extracts percentage values from terminal lines
and reports only when a not-yet-announced milestone threshold is crossed.
"""
import time
from unittest.mock import patch, MagicMock

import pytest

from lib.progress_milestones import ProgressMilestoneTracker


class TestMilestoneCrossing:
    """Basic milestone crossing behavior."""

    def test_crossing_first_milestone_returns_it(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("Progress: 30%") == 25

    def test_exact_milestone_value_counts_as_crossed(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("25%") == 25

    def test_below_first_milestone_returns_none(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("10%") is None

    def test_sequential_milestones_each_announced_once(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("25%") == 25
        assert tracker.update("50%") == 50
        assert tracker.update("75%") == 75
        assert tracker.update("100%") == 100

    def test_no_repeat_announcement_for_same_milestone(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("30%") == 25
        assert tracker.update("35%") is None
        assert tracker.update("49%") is None

    def test_jump_across_multiple_milestones_returns_highest(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("20%") is None
        assert tracker.update("80%") == 75

    def test_jump_straight_to_100_returns_100(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("100%") == 100

    def test_completion_after_partial_progress(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("60%") == 50
        assert tracker.update("100%") == 100


class TestPercentageExtraction:
    """Percentage patterns found in real terminal output."""

    def test_plain_percentage(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("45%") == 25

    def test_progress_bar_line(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("[====>  ] 45%") == 25

    def test_decimal_percentage(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("45.2%") == 25

    def test_space_before_percent_sign(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("Progress: 45 %") == 25

    def test_ansi_wrapped_percentage(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("\x1b[32m50%\x1b[0m") == 50

    def test_ansi_codes_between_digits_and_percent(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("\x1b[1mDownloading\x1b[0m 75%") == 75

    def test_no_percentage_returns_none(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("Compiling mycrate v0.1.0") is None

    def test_empty_line_returns_none(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("") is None


class TestMalformedInput:
    """Malformed input must never crash and must be ignored."""

    def test_over_100_ignored(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("999%") is None

    def test_just_over_100_ignored(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("100.5%") is None

    def test_negative_percentage_ignored(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("-5%") is None

    def test_trailing_garbage_still_extracts(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("45%extra") == 25

    def test_non_string_input_returns_none(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update(None) is None

    def test_ignored_value_does_not_advance_state(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("999%") is None
        assert tracker.update("30%") == 25


class TestAutoReset:
    """A large percentage decrease means a new progress bar started."""

    def test_decrease_over_10_points_resets(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("80%") == 75
        # New operation: drops to 5%, no milestone crossed yet
        assert tracker.update("5%") is None
        # Milestones can be announced again for the new operation
        assert tracker.update("30%") == 25

    def test_small_decrease_does_not_reset(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("50%") == 50
        # Jitter within 10 points: not a new operation
        assert tracker.update("45%") is None
        assert tracker.update("55%") is None

    def test_manual_reset_clears_state(self):
        tracker = ProgressMilestoneTracker()
        assert tracker.update("50%") == 50
        tracker.reset()
        assert tracker.update("50%") == 50


class TestCustomMilestones:
    """Milestone thresholds are configurable."""

    def test_custom_thresholds(self):
        tracker = ProgressMilestoneTracker(milestones=(10, 90))
        assert tracker.update("15%") == 10
        assert tracker.update("50%") is None
        assert tracker.update("95%") == 90

    def test_unsorted_milestones_still_return_highest_crossed(self):
        tracker = ProgressMilestoneTracker(milestones=(75, 25, 50))
        assert tracker.update("60%") == 50


class TestProgressMilestonesConfig:
    """The progressMilestones config key must be fully registered."""

    def test_key_in_confspec(self):
        from lib.config import confspec
        assert confspec.get("progressMilestones") == "boolean(default=True)"

    def test_validate_key_coerces_to_bool(self):
        from lib.config import ConfigManager
        manager = ConfigManager()
        assert manager._validate_key("progressMilestones", 1) is True
        assert manager._validate_key("progressMilestones", 0) is False

    def test_reset_to_defaults_includes_key(self):
        import inspect
        from lib.config import ConfigManager
        source = inspect.getsource(ConfigManager.reset_to_defaults)
        assert "progressMilestones" in source


class TestEventTextChangeIntegration:
    """Milestones are announced from event_textChange via the last buffer line."""

    def _make_plugin(self, settings=None):
        from globalPlugins.terminalAccess import GlobalPlugin
        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()
        plugin._boundTerminal = MagicMock()
        values = {
            "quietMode": False,
            "outputActivityTones": False,
            "cursorTracking": True,
            "cursorDelay": 20,
            "streamingSuppression": True,
            "progressMilestones": True,
        }
        if settings:
            values.update(settings)
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(
            side_effect=lambda key, default=None: values.get(key, default)
        )
        return plugin

    def _set_last_line(self, plugin, text):
        info = MagicMock()
        info.text = text
        plugin._boundTerminal.makeTextInfo.return_value = info
        return info

    def test_milestone_announced_on_text_change(self):
        plugin = self._make_plugin()
        self._set_last_line(plugin, "Downloading 50%")

        with patch('globalPlugins.terminalAccess.ui') as ui_mock:
            plugin.event_textChange(MagicMock(), MagicMock())

        ui_mock.message.assert_called_once()
        assert "50" in ui_mock.message.call_args[0][0]

    def test_throttled_to_one_buffer_read_per_interval(self):
        plugin = self._make_plugin()
        self._set_last_line(plugin, "30%")

        with patch('globalPlugins.terminalAccess.ui') as ui_mock:
            plugin.event_textChange(MagicMock(), MagicMock())
            self._set_last_line(plugin, "60%")
            plugin.event_textChange(MagicMock(), MagicMock())

        # Second event arrived within the throttle window: one read, one announcement
        assert plugin._boundTerminal.makeTextInfo.call_count == 1
        ui_mock.message.assert_called_once()
        assert "25" in ui_mock.message.call_args[0][0]

    def test_check_runs_again_after_throttle_window(self):
        plugin = self._make_plugin()
        self._set_last_line(plugin, "30%")

        with patch('globalPlugins.terminalAccess.ui') as ui_mock:
            plugin.event_textChange(MagicMock(), MagicMock())
            # Simulate the throttle window elapsing
            plugin._lastProgressCheckTime = time.monotonic() - 1.0
            self._set_last_line(plugin, "60%")
            plugin.event_textChange(MagicMock(), MagicMock())

        assert ui_mock.message.call_count == 2
        assert "50" in ui_mock.message.call_args[0][0]

    def test_disabled_setting_means_no_read_and_no_announcement(self):
        plugin = self._make_plugin(settings={"progressMilestones": False})
        self._set_last_line(plugin, "Downloading 50%")

        with patch('globalPlugins.terminalAccess.ui') as ui_mock:
            plugin.event_textChange(MagicMock(), MagicMock())

        plugin._boundTerminal.makeTextInfo.assert_not_called()
        ui_mock.message.assert_not_called()

    def test_no_announcement_without_percentage(self):
        plugin = self._make_plugin()
        self._set_last_line(plugin, "Compiling mycrate v0.1.0")

        with patch('globalPlugins.terminalAccess.ui') as ui_mock:
            plugin.event_textChange(MagicMock(), MagicMock())

        ui_mock.message.assert_not_called()

    def test_buffer_read_failure_does_not_crash(self):
        plugin = self._make_plugin()
        plugin._boundTerminal.makeTextInfo.side_effect = RuntimeError("COM error")

        with patch('globalPlugins.terminalAccess.ui') as ui_mock:
            plugin.event_textChange(MagicMock(), MagicMock())

        ui_mock.message.assert_not_called()

    def test_plugin_instantiates_tracker(self):
        plugin = self._make_plugin()
        assert isinstance(plugin._progressTracker, ProgressMilestoneTracker)
