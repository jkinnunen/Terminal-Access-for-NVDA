"""
Tests for the profile editor logic in lib.profiles.

The ProfileEditorDialog widget code is untestable (wx is mocked), so all
editable state flows through three pure functions:

- profile_to_editor_values(profile) -> dict of choice indexes / strings
- editor_values_to_profile(values, profile) -> applies values back
- validate_editor_values(values) -> (ok, error_message)

Choice index convention: index 0 always means "Global default" (None on
the profile). Punctuation and cursor tracking values are offset by one;
tri-state booleans map True -> 1, False -> 2.
"""

import pytest

from lib.config import (
    CT_OFF, CT_STANDARD, CT_WINDOW,
    PUNCT_NONE, PUNCT_SOME, PUNCT_MOST, PUNCT_ALL,
    MAX_REPEATED_SYMBOLS_LENGTH,
)
from lib.profiles import (
    ApplicationProfile,
    profile_to_editor_values,
    editor_values_to_profile,
    validate_editor_values,
)


TRISTATE_FIELDS = ("keyEcho", "linePause", "quietMode", "repeatedSymbols")


def make_profile(**overrides):
    profile = ApplicationProfile("myapp", "My App")
    for name, value in overrides.items():
        setattr(profile, name, value)
    return profile


class TestProfileToEditorValues:
    """Mapping from a profile to editor choice indexes and strings."""

    def test_fresh_profile_maps_all_overrides_to_global_default(self):
        values = profile_to_editor_values(make_profile())
        assert values["punctuationLevel"] == 0
        assert values["cursorTrackingMode"] == 0
        for field in TRISTATE_FIELDS:
            assert values[field] == 0, field

    def test_names_copied(self):
        values = profile_to_editor_values(make_profile())
        assert values["appName"] == "myapp"
        assert values["displayName"] == "My App"

    def test_none_repeated_symbols_values_maps_to_empty_string(self):
        values = profile_to_editor_values(make_profile())
        assert values["repeatedSymbolsValues"] == ""

    def test_repeated_symbols_values_string_preserved(self):
        values = profile_to_editor_values(
            make_profile(repeatedSymbolsValues="=-*")
        )
        assert values["repeatedSymbolsValues"] == "=-*"

    def test_punctuation_level_offset_by_one(self):
        assert profile_to_editor_values(
            make_profile(punctuationLevel=PUNCT_NONE)
        )["punctuationLevel"] == 1
        assert profile_to_editor_values(
            make_profile(punctuationLevel=PUNCT_ALL)
        )["punctuationLevel"] == 4

    def test_cursor_tracking_mode_offset_by_one(self):
        assert profile_to_editor_values(
            make_profile(cursorTrackingMode=CT_OFF)
        )["cursorTrackingMode"] == 1
        assert profile_to_editor_values(
            make_profile(cursorTrackingMode=CT_WINDOW)
        )["cursorTrackingMode"] == 3

    @pytest.mark.parametrize("field", TRISTATE_FIELDS)
    def test_tristate_true_maps_to_one(self, field):
        values = profile_to_editor_values(make_profile(**{field: True}))
        assert values[field] == 1

    @pytest.mark.parametrize("field", TRISTATE_FIELDS)
    def test_tristate_false_maps_to_two(self, field):
        values = profile_to_editor_values(make_profile(**{field: False}))
        assert values[field] == 2


class TestEditorValuesToProfile:
    """Applying editor values back onto a profile."""

    def test_index_zero_resets_every_override_to_none(self):
        source = make_profile(
            punctuationLevel=PUNCT_MOST,
            cursorTrackingMode=CT_STANDARD,
            keyEcho=True,
            linePause=False,
            quietMode=True,
            repeatedSymbols=False,
            repeatedSymbolsValues="=-",
        )
        values = profile_to_editor_values(make_profile())
        editor_values_to_profile(values, source)
        assert source.punctuationLevel is None
        assert source.cursorTrackingMode is None
        for field in TRISTATE_FIELDS:
            assert getattr(source, field) is None, field
        assert source.repeatedSymbolsValues is None

    def test_round_trip_preserves_every_field(self):
        source = make_profile(
            punctuationLevel=PUNCT_ALL,
            cursorTrackingMode=CT_WINDOW,
            keyEcho=True,
            linePause=False,
            quietMode=True,
            repeatedSymbols=False,
            repeatedSymbolsValues="=-",
        )
        target = ApplicationProfile("myapp")
        editor_values_to_profile(profile_to_editor_values(source), target)
        assert target.displayName == "My App"
        assert target.punctuationLevel == PUNCT_ALL
        assert target.cursorTrackingMode == CT_WINDOW
        assert target.keyEcho is True
        assert target.linePause is False
        assert target.quietMode is True
        assert target.repeatedSymbols is False
        assert target.repeatedSymbolsValues == "=-"

    def test_round_trip_preserves_punctuation_none_level(self):
        # PUNCT_NONE (0) must survive the round trip distinctly from None.
        source = make_profile(punctuationLevel=PUNCT_NONE)
        target = ApplicationProfile("myapp")
        editor_values_to_profile(profile_to_editor_values(source), target)
        assert target.punctuationLevel == PUNCT_NONE

    def test_round_trip_all_inherit(self):
        target = make_profile(punctuationLevel=PUNCT_ALL, keyEcho=True)
        editor_values_to_profile(
            profile_to_editor_values(make_profile()), target
        )
        assert target.punctuationLevel is None
        assert target.keyEcho is None

    def test_tristate_one_sets_true_two_sets_false(self):
        profile = make_profile()
        values = profile_to_editor_values(profile)
        values["keyEcho"] = 1
        values["linePause"] = 2
        editor_values_to_profile(values, profile)
        assert profile.keyEcho is True
        assert profile.linePause is False

    def test_repeated_symbols_values_clamped_to_max_length(self):
        profile = make_profile()
        values = profile_to_editor_values(profile)
        values["repeatedSymbolsValues"] = "x" * (MAX_REPEATED_SYMBOLS_LENGTH + 30)
        editor_values_to_profile(values, profile)
        assert profile.repeatedSymbolsValues is not None
        assert len(profile.repeatedSymbolsValues) <= MAX_REPEATED_SYMBOLS_LENGTH

    def test_out_of_range_punctuation_index_falls_back_to_valid_value(self):
        profile = make_profile()
        values = profile_to_editor_values(profile)
        values["punctuationLevel"] = 99
        editor_values_to_profile(values, profile)
        assert profile.punctuationLevel in (PUNCT_NONE, PUNCT_SOME, PUNCT_MOST, PUNCT_ALL)

    def test_out_of_range_cursor_tracking_index_falls_back_to_valid_value(self):
        profile = make_profile()
        values = profile_to_editor_values(profile)
        values["cursorTrackingMode"] = 42
        editor_values_to_profile(values, profile)
        assert profile.cursorTrackingMode in (CT_OFF, CT_STANDARD, CT_WINDOW)

    def test_empty_display_name_falls_back_to_app_name(self):
        profile = ApplicationProfile("myapp", "My App")
        values = profile_to_editor_values(profile)
        values["displayName"] = ""
        editor_values_to_profile(values, profile)
        assert profile.displayName == "myapp"

    def test_app_name_never_modified(self):
        # Builtin profiles are editable but their appName is locked.
        profile = ApplicationProfile("vim", "Vim/Neovim")
        values = profile_to_editor_values(profile)
        values["appName"] = "hijacked"
        editor_values_to_profile(values, profile)
        assert profile.appName == "vim"

    def test_returns_the_profile(self):
        profile = make_profile()
        values = profile_to_editor_values(profile)
        assert editor_values_to_profile(values, profile) is profile


class TestValidateEditorValues:
    """Standalone validation before values are applied."""

    def _values(self, **overrides):
        values = profile_to_editor_values(make_profile())
        values.update(overrides)
        return values

    def test_valid_values_accepted(self):
        ok, message = validate_editor_values(self._values())
        assert ok is True

    def test_empty_app_name_rejected(self):
        ok, message = validate_editor_values(self._values(appName=""))
        assert ok is False
        assert message

    def test_whitespace_app_name_rejected(self):
        ok, message = validate_editor_values(self._values(appName="   "))
        assert ok is False
        assert message


class TestProfileEditorDialogPresence:
    """The dialog class must exist and the placeholder must be gone."""

    def test_dialog_importable(self):
        from lib.profiles import ProfileEditorDialog
        assert ProfileEditorDialog is not None

    def test_settings_panel_placeholder_removed(self):
        import inspect
        from lib.settings_panel import TerminalAccessSettingsPanel
        source = inspect.getsource(TerminalAccessSettingsPanel)
        assert "will be implemented soon" not in source
        assert "Feature In Development" not in source

    def test_new_and_edit_use_editor_dialog(self):
        import inspect
        from lib.settings_panel import TerminalAccessSettingsPanel
        assert "ProfileEditorDialog" in inspect.getsource(
            TerminalAccessSettingsPanel.onNewProfile
        )
        assert "ProfileEditorDialog" in inspect.getsource(
            TerminalAccessSettingsPanel.onEditProfile
        )
