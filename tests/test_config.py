"""
Unit tests for configuration management.

Tests config sanitization and validation added in v1.0.16.
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import sys


class TestConfigurationSanitization(unittest.TestCase):
    """Test configuration sanitization on initialization."""

    def setUp(self):
        """Set up test fixtures."""
        # Get fresh config for each test
        config_mock = sys.modules['config']
        config_mock.conf = MagicMock()
        config_mock.conf.__getitem__ = MagicMock(return_value={
            "cursorTracking": True,
            "cursorTrackingMode": 1,
            "keyEcho": True,
            "linePause": True,
            "processSymbols": False,
            "punctuationLevel": 2,
            "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!",
            "cursorDelay": 20,
            "quietMode": False,
            "windowTop": 0,
            "windowBottom": 0,
            "windowLeft": 0,
            "windowRight": 0,
            "windowEnabled": False,
        })

    def test_sanitize_config_valid_values(self):
        """Test _sanitizeConfig with all valid values."""
        from globalPlugins.terminalAccess import GlobalPlugin

        # Create mock for GUI dialog
        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

            # Should not raise any errors
            config_mock = sys.modules['config']
            conf = config_mock.conf["terminalAccess"]

            # Values should remain unchanged
            self.assertEqual(conf["cursorTrackingMode"], 1)
            self.assertEqual(conf["punctuationLevel"], 2)
            self.assertEqual(conf["cursorDelay"], 20)

    def test_sanitize_config_invalid_tracking_mode(self):
        """Test _sanitizeConfig with invalid cursor tracking mode."""
        config_mock = sys.modules['config']
        config_dict = config_mock.conf["terminalAccess"]
        config_dict["cursorTrackingMode"] = 99  # Invalid

        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

            # Should be sanitized to default (1)
            self.assertEqual(config_dict["cursorTrackingMode"], 1)

    def test_sanitize_config_invalid_punctuation_level(self):
        """Test _sanitizeConfig with invalid punctuation level."""
        config_mock = sys.modules['config']
        config_dict = config_mock.conf["terminalAccess"]
        config_dict["punctuationLevel"] = -1  # Invalid

        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

            # Should be sanitized to default (2)
            self.assertEqual(config_dict["punctuationLevel"], 2)

    def test_sanitize_config_invalid_cursor_delay(self):
        """Test _sanitizeConfig with invalid cursor delay."""
        config_mock = sys.modules['config']
        config_dict = config_mock.conf["terminalAccess"]
        config_dict["cursorDelay"] = 5000  # Too high

        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

            # Should be sanitized to default (20)
            self.assertEqual(config_dict["cursorDelay"], 20)

    def test_sanitize_config_long_repeated_symbols(self):
        """Test _sanitizeConfig with too long repeated symbols string."""
        config_mock = sys.modules['config']
        config_dict = config_mock.conf["terminalAccess"]
        config_dict["repeatedSymbolsValues"] = "a" * 100  # Too long

        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

            # Should be truncated to MAX_REPEATED_SYMBOLS_LENGTH
            self.assertEqual(len(config_dict["repeatedSymbolsValues"]), 50)

    def test_sanitize_config_invalid_window_bounds(self):
        """Test _sanitizeConfig with invalid window bounds."""
        config_mock = sys.modules['config']
        config_dict = config_mock.conf["terminalAccess"]
        config_dict["windowTop"] = -10  # Negative
        config_dict["windowBottom"] = 20000  # Too high

        from globalPlugins.terminalAccess import GlobalPlugin

        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()

            # Should be sanitized
            self.assertEqual(config_dict["windowTop"], 0)
            self.assertEqual(config_dict["windowBottom"], 0)


class TestConfigConstants(unittest.TestCase):
    """Test configuration constants."""

    def setUp(self):
        """Set up test fixtures."""
        from globalPlugins import terminalAccess
        self.terminalAccess = terminalAccess

    def test_cursor_tracking_constants(self):
        """Test cursor tracking mode constants are defined."""
        self.assertEqual(self.terminalAccess.CT_OFF, 0)
        self.assertEqual(self.terminalAccess.CT_STANDARD, 1)
        self.assertEqual(self.terminalAccess.CT_WINDOW, 2)

    def test_punctuation_constants(self):
        """Test punctuation level constants are defined."""
        self.assertEqual(self.terminalAccess.PUNCT_NONE, 0)
        self.assertEqual(self.terminalAccess.PUNCT_SOME, 1)
        self.assertEqual(self.terminalAccess.PUNCT_MOST, 2)
        self.assertEqual(self.terminalAccess.PUNCT_ALL, 3)

    def test_punctuation_sets_defined(self):
        """Test PUNCTUATION_SETS dictionary is properly defined."""
        self.assertIsNotNone(self.terminalAccess.PUNCTUATION_SETS)
        self.assertIn(self.terminalAccess.PUNCT_NONE, self.terminalAccess.PUNCTUATION_SETS)
        self.assertIn(self.terminalAccess.PUNCT_SOME, self.terminalAccess.PUNCTUATION_SETS)
        self.assertIn(self.terminalAccess.PUNCT_MOST, self.terminalAccess.PUNCTUATION_SETS)
        self.assertIn(self.terminalAccess.PUNCT_ALL, self.terminalAccess.PUNCTUATION_SETS)

    def test_punctuation_sets_content(self):
        """Test PUNCTUATION_SETS contain expected characters."""
        punct_sets = self.terminalAccess.PUNCTUATION_SETS

        # PUNCT_NONE should be empty
        self.assertEqual(len(punct_sets[self.terminalAccess.PUNCT_NONE]), 0)

        # PUNCT_SOME should have basic punctuation
        self.assertIn('.', punct_sets[self.terminalAccess.PUNCT_SOME])
        self.assertIn(',', punct_sets[self.terminalAccess.PUNCT_SOME])

        # PUNCT_MOST should have more punctuation
        self.assertIn('@', punct_sets[self.terminalAccess.PUNCT_MOST])
        self.assertIn('#', punct_sets[self.terminalAccess.PUNCT_MOST])

        # PUNCT_ALL should be None (process everything)
        self.assertIsNone(punct_sets[self.terminalAccess.PUNCT_ALL])


class TestConfigSpec(unittest.TestCase):
    """Test configuration specification."""

    def setUp(self):
        """Set up test fixtures."""
        from globalPlugins import terminalAccess
        self.terminalAccess = terminalAccess

    def test_confspec_defined(self):
        """Test confspec dictionary is defined."""
        self.assertIsNotNone(self.terminalAccess.confspec)

    def test_confspec_has_required_keys(self):
        """Test confspec has all required configuration keys."""
        required_keys = [
            "cursorTracking",
            "cursorTrackingMode",
            "keyEcho",
            "linePause",
            "processSymbols",
            "punctuationLevel",
            "repeatedSymbols",
            "repeatedSymbolsValues",
            "cursorDelay",
            "quietMode",
            "windowTop",
            "windowBottom",
            "windowLeft",
            "windowRight",
            "windowEnabled",
        ]

        for key in required_keys:
            self.assertIn(key, self.terminalAccess.confspec, f"Missing config key: {key}")


class TestConfigMigration(unittest.TestCase):
    """Test configuration migration from old keys to new keys."""

    def test_migrate_processSymbols_to_punctuationLevel_true(self):
        """Test migration from processSymbols=True to punctuationLevel=2."""
        from globalPlugins.terminalAccess import ConfigManager, PUNCT_MOST

        # Mock config with old processSymbols setting
        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True,
            "cursorTrackingMode": 1,
            "keyEcho": True,
            "linePause": True,
            "processSymbols": True,  # Old setting
            # punctuationLevel not set yet
            "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!",
            "cursorDelay": 20,
            "quietMode": False,
            "windowTop": 0,
            "windowBottom": 0,
            "windowLeft": 0,
            "windowRight": 0,
            "windowEnabled": False,
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)

        # Create ConfigManager which should trigger migration
        manager = ConfigManager()

        # Verify migration occurred
        self.assertEqual(config_dict["punctuationLevel"], PUNCT_MOST)
        # Old key should still exist (not deleted)
        self.assertIn("processSymbols", config_dict)

    def test_migrate_processSymbols_to_punctuationLevel_false(self):
        """Test migration from processSymbols=False to punctuationLevel=0."""
        from globalPlugins.terminalAccess import ConfigManager, PUNCT_NONE

        # Mock config with old processSymbols setting
        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True,
            "cursorTrackingMode": 1,
            "keyEcho": True,
            "linePause": True,
            "processSymbols": False,  # Old setting
            # punctuationLevel not set yet
            "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!",
            "cursorDelay": 20,
            "quietMode": False,
            "windowTop": 0,
            "windowBottom": 0,
            "windowLeft": 0,
            "windowRight": 0,
            "windowEnabled": False,
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)

        # Create ConfigManager which should trigger migration
        manager = ConfigManager()

        # Verify migration occurred
        self.assertEqual(config_dict["punctuationLevel"], PUNCT_NONE)
        # Old key should still exist (not deleted)
        self.assertIn("processSymbols", config_dict)

    def test_no_migration_when_punctuationLevel_exists(self):
        """Test that migration doesn't overwrite existing punctuationLevel."""
        from globalPlugins.terminalAccess import ConfigManager, PUNCT_ALL

        # Mock config with both old and new settings
        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True,
            "cursorTrackingMode": 1,
            "keyEcho": True,
            "linePause": True,
            "processSymbols": True,  # Old setting
            "punctuationLevel": PUNCT_ALL,  # New setting already exists
            "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!",
            "cursorDelay": 20,
            "quietMode": False,
            "windowTop": 0,
            "windowBottom": 0,
            "windowLeft": 0,
            "windowRight": 0,
            "windowEnabled": False,
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)

        # Create ConfigManager which should trigger migration check
        manager = ConfigManager()

        # Verify existing value was preserved
        self.assertEqual(config_dict["punctuationLevel"], PUNCT_ALL)


class TestResetToDefaultsCoversAllKeys(unittest.TestCase):
    """reset_to_defaults must include all config keys including v1.4.0 keys."""

    def test_reset_includes_error_audio_cues(self):
        """reset_to_defaults must reset errorAudioCues to its default."""
        from lib.config import ConfigManager

        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True, "cursorTrackingMode": 1,
            "keyEcho": True, "linePause": True,
            "punctuationLevel": 2, "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!", "cursorDelay": 20,
            "quietMode": False, "windowTop": 0, "windowBottom": 0,
            "windowLeft": 0, "windowRight": 0, "windowEnabled": False,
            "errorAudioCues": False,  # non-default value
            "errorAudioCuesInQuietMode": True,  # non-default value
            "outputActivityTones": True,  # non-default value
            "outputActivityDebounce": 5000,  # non-default value
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)
        manager = ConfigManager()

        manager.reset_to_defaults()

        assert config_dict["errorAudioCues"] is True, (
            "errorAudioCues not reset to default True"
        )
        assert config_dict["errorAudioCuesInQuietMode"] is False, (
            "errorAudioCuesInQuietMode not reset to default False"
        )
        assert config_dict["outputActivityTones"] is False, (
            "outputActivityTones not reset to default False"
        )
        assert config_dict["outputActivityDebounce"] == 1000, (
            "outputActivityDebounce not reset to default 1000"
        )


    def test_validate_all_clamps_out_of_range_debounce(self):
        """validate_all must sanitize out-of-range outputActivityDebounce."""
        from lib.config import ConfigManager

        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True, "cursorTrackingMode": 1,
            "keyEcho": True, "linePause": True,
            "punctuationLevel": 2, "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!", "cursorDelay": 20,
            "quietMode": False, "windowTop": 0, "windowBottom": 0,
            "windowLeft": 0, "windowRight": 0, "windowEnabled": False,
            "errorAudioCues": True, "errorAudioCuesInQuietMode": False,
            "outputActivityTones": False,
            "outputActivityDebounce": 50,  # below minimum of 100
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)
        manager = ConfigManager()

        # validate_all runs in __init__, should have clamped the value
        assert config_dict["outputActivityDebounce"] != 50, (
            "validate_all did not clamp outputActivityDebounce=50 (min=100)"
        )


class TestPrivacyConfigKeys(unittest.TestCase):
    """Privacy-gated features must have confspec entries and settings panel UI."""

    def test_aiTurnParseEnabled_in_confspec(self):
        """aiTurnParseEnabled must exist in confspec since PrivacyGuard references it."""
        from lib.config import confspec
        assert "aiTurnParseEnabled" in confspec, (
            "aiTurnParseEnabled referenced by PrivacyGuard but missing from confspec"
        )

    def test_all_privacy_keys_in_confspec(self):
        """All PrivacyGuard feature keys must exist in confspec."""
        from lib.config import confspec
        from lib.privacy import _FEATURE_CONFIG_KEYS
        for feature, config_key in _FEATURE_CONFIG_KEYS.items():
            assert config_key in confspec, (
                f"Privacy feature '{feature}' maps to config key '{config_key}' "
                f"which is missing from confspec"
            )

    def test_privacy_keys_in_validate_key(self):
        """Privacy boolean keys must be validated by ConfigManager._validate_key."""
        from lib.config import ConfigManager
        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True, "cursorTrackingMode": 1,
            "keyEcho": True, "linePause": True,
            "punctuationLevel": 2, "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!", "cursorDelay": 20,
            "quietMode": False, "windowTop": 0, "windowBottom": 0,
            "windowLeft": 0, "windowRight": 0, "windowEnabled": False,
            "errorAudioCues": True, "errorAudioCuesInQuietMode": False,
            "outputActivityTones": False, "outputActivityDebounce": 1000,
            "summarizationEnabled": False, "codeBlockExplain": False,
            "privacyAnnounce": True, "aiTurnParseEnabled": False,
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)
        manager = ConfigManager()

        # Setting a string value should be coerced to bool
        manager.set("summarizationEnabled", "truthy")
        assert config_dict["summarizationEnabled"] is True, (
            "summarizationEnabled not coerced to bool"
        )
        assert isinstance(config_dict["summarizationEnabled"], bool)

    def test_privacy_keys_in_reset_to_defaults(self):
        """reset_to_defaults must reset privacy keys to their defaults."""
        from lib.config import ConfigManager
        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True, "cursorTrackingMode": 1,
            "keyEcho": True, "linePause": True,
            "punctuationLevel": 2, "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!", "cursorDelay": 20,
            "quietMode": False, "windowTop": 0, "windowBottom": 0,
            "windowLeft": 0, "windowRight": 0, "windowEnabled": False,
            "errorAudioCues": True, "errorAudioCuesInQuietMode": False,
            "outputActivityTones": False, "outputActivityDebounce": 1000,
            "summarizationEnabled": True,  # non-default
            "codeBlockExplain": True,  # non-default
            "privacyAnnounce": False,  # non-default
            "aiTurnParseEnabled": True,  # non-default
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)
        manager = ConfigManager()
        manager.reset_to_defaults()

        assert config_dict["summarizationEnabled"] is False, "summarizationEnabled not reset"
        assert config_dict["codeBlockExplain"] is False, "codeBlockExplain not reset"
        assert config_dict["privacyAnnounce"] is True, "privacyAnnounce not reset"
        assert config_dict["aiTurnParseEnabled"] is False, "aiTurnParseEnabled not reset"


class TestValidateKeyCoversNewConfigKeys(unittest.TestCase):
    """v1.4.0 config keys must be validated by _validate_key."""

    def _make_manager(self):
        config_mock = sys.modules['config']
        config_dict = {
            "cursorTracking": True, "cursorTrackingMode": 1,
            "keyEcho": True, "linePause": True,
            "punctuationLevel": 2, "repeatedSymbols": False,
            "repeatedSymbolsValues": "-_=!", "cursorDelay": 20,
            "quietMode": False, "windowTop": 0, "windowBottom": 0,
            "windowLeft": 0, "windowRight": 0, "windowEnabled": False,
            "errorAudioCues": True, "errorAudioCuesInQuietMode": False,
            "outputActivityTones": False, "outputActivityDebounce": 1000,
        }
        config_mock.conf.__getitem__ = MagicMock(return_value=config_dict)
        from lib.config import ConfigManager
        return ConfigManager(), config_dict

    def test_outputActivityDebounce_validated_as_integer(self):
        """outputActivityDebounce must be validated as integer with range check."""
        manager, config_dict = self._make_manager()
        # Set an out-of-range value (below minimum of 100)
        manager.set("outputActivityDebounce", 10)
        # Should be clamped to default, not stored as 10
        assert config_dict["outputActivityDebounce"] != 10, (
            "outputActivityDebounce=10 was accepted without validation (min=100)"
        )

    def test_errorAudioCues_validated_as_bool(self):
        """errorAudioCues must be coerced to bool by _validate_key."""
        manager, config_dict = self._make_manager()
        manager.set("errorAudioCues", "truthy_string")
        assert config_dict["errorAudioCues"] is True, (
            "errorAudioCues should be coerced to bool True"
        )
        assert isinstance(config_dict["errorAudioCues"], bool), (
            f"errorAudioCues should be bool, got {type(config_dict['errorAudioCues']).__name__}"
        )


if __name__ == '__main__':
    unittest.main()
