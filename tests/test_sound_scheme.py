"""
Tests for the sound scheme settings in lib.audio_cues and lib.config.

Users with high-frequency or low-frequency hearing loss can adjust
earcon volume (10-100 percent) and pitch shift (50-200 percent).
play_cue reads both settings from config at call time and clamps the
shifted frequency to the audible 55-8000 Hz range.
"""

import sys

import pytest

from lib.audio_cues import _TONE_MAP, apply_sound_scheme, play_cue


@pytest.fixture
def beep():
    """The shared tones.beep mock, reset for each test."""
    import tones
    tones.beep.reset_mock()
    return tones.beep


def set_sound_config(volume=None, pitch=None):
    conf = sys.modules["config"].conf["terminalAccess"]
    if volume is not None:
        conf["earconVolume"] = volume
    if pitch is not None:
        conf["earconPitchShift"] = pitch


class TestApplySoundScheme:
    """Pure pitch shift math with clamping."""

    def test_hundred_percent_is_identity(self):
        assert apply_sound_scheme(880, 100) == 880

    def test_half_pitch(self):
        assert apply_sound_scheme(880, 50) == 440

    def test_double_pitch(self):
        assert apply_sound_scheme(440, 200) == 880

    def test_clamps_at_low_rail(self):
        assert apply_sound_scheme(100, 50) == 55

    def test_clamps_at_high_rail(self):
        assert apply_sound_scheme(4400, 200) == 8000

    def test_returns_int(self):
        assert isinstance(apply_sound_scheme(333, 150), int)


class TestPlayCueSoundScheme:
    """play_cue applies volume and pitch shift from config."""

    def test_defaults_leave_tones_identical_to_tone_map(self, beep):
        for event, tones_list in _TONE_MAP.items():
            beep.reset_mock()
            play_cue(event)
            played = [call.args[:2] for call in beep.call_args_list]
            assert played == list(tones_list), event

    def test_volume_passed_through(self, beep):
        set_sound_config(volume=60)
        play_cue("error")
        assert beep.call_args.kwargs.get("left") == 60
        assert beep.call_args.kwargs.get("right") == 60

    def test_default_volume_is_full(self, beep):
        play_cue("error")
        assert beep.call_args.kwargs.get("left") == 100
        assert beep.call_args.kwargs.get("right") == 100

    def test_pitch_shift_applied(self, beep):
        set_sound_config(pitch=50)
        play_cue("command_layer_enter")  # 880 Hz in the tone map
        assert beep.call_args.args[0] == 440

    def test_pitch_shift_preserves_duration(self, beep):
        set_sound_config(pitch=200)
        play_cue("error")  # (220, 50)
        assert beep.call_args.args == (440, 50)

    def test_multi_tone_events_shift_every_tone(self, beep):
        set_sound_config(pitch=200)
        play_cue("ai_code_block")  # (880, 20), (660, 20)
        played = [call.args[:2] for call in beep.call_args_list]
        assert played == [(1760, 20), (1320, 20)]

    def test_unknown_event_is_silent_no_op(self, beep):
        play_cue("no_such_event")
        beep.assert_not_called()


class TestSoundSchemeConfig:
    """Config keys exist and are validated."""

    def test_confspec_has_earcon_volume(self):
        from lib.config import confspec
        assert confspec["earconVolume"] == "integer(default=100, min=10, max=100)"

    def test_confspec_has_earcon_pitch_shift(self):
        from lib.config import confspec
        assert confspec["earconPitchShift"] == "integer(default=100, min=50, max=200)"

    def test_config_manager_rejects_out_of_range_volume(self):
        from lib.config import ConfigManager
        mgr = ConfigManager()
        mgr.set("earconVolume", 5)
        assert mgr.get("earconVolume") == 100

    def test_config_manager_rejects_out_of_range_pitch(self):
        from lib.config import ConfigManager
        mgr = ConfigManager()
        mgr.set("earconPitchShift", 999)
        assert mgr.get("earconPitchShift") == 100

    def test_config_manager_accepts_valid_values(self):
        from lib.config import ConfigManager
        mgr = ConfigManager()
        assert mgr.set("earconVolume", 40) is True
        assert mgr.get("earconVolume") == 40
        assert mgr.set("earconPitchShift", 150) is True
        assert mgr.get("earconPitchShift") == 150

    def test_validate_all_seeds_defaults(self):
        from lib.config import ConfigManager
        mgr = ConfigManager()
        assert mgr.get("earconVolume") == 100
        assert mgr.get("earconPitchShift") == 100

    def test_reset_to_defaults_restores_both(self):
        from lib.config import ConfigManager
        mgr = ConfigManager()
        mgr.set("earconVolume", 40)
        mgr.set("earconPitchShift", 150)
        mgr.reset_to_defaults()
        assert mgr.get("earconVolume") == 100
        assert mgr.get("earconPitchShift") == 100


class TestSoundSettingsPanel:
    """The settings panel exposes and persists the sound settings."""

    def test_panel_has_sound_spinners(self):
        import inspect
        from lib.settings_panel import TerminalAccessSettingsPanel
        source = inspect.getsource(TerminalAccessSettingsPanel)
        assert "earconVolumeSpinner" in source
        assert "earconPitchSpinner" in source

    def test_on_save_persists_sound_settings(self):
        import inspect
        from lib.settings_panel import TerminalAccessSettingsPanel
        source = inspect.getsource(TerminalAccessSettingsPanel.onSave)
        assert "earconVolume" in source
        assert "earconPitchShift" in source

    def test_reset_to_defaults_covers_sound_settings(self):
        import inspect
        from lib.settings_panel import TerminalAccessSettingsPanel
        source = inspect.getsource(TerminalAccessSettingsPanel.onResetToDefaults)
        assert "earconVolume" in source
        assert "earconPitchShift" in source
