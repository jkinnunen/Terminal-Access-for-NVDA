"""Tests for privacy guardrails in lib/privacy.py.

RED phase: all tests written before implementation exists.
"""
import os
import sys
import ast
import pytest
from unittest.mock import MagicMock


class TestPrivacyGuardCheckFeature:
    """PrivacyGuard.check_feature gates features by config flags."""

    def test_summarize_blocked_when_disabled(self):
        """Summarization returns blocked when summarizationEnabled is False."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": False,
            "privacyAnnounce": True,
        }.get(key, True if default is None else default)
        allowed, msg = guard.check_feature("summarize", mgr)
        assert allowed is False
        assert msg != ""

    def test_summarize_allowed_when_enabled(self):
        """Summarization returns allowed when summarizationEnabled is True."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.return_value = True
        allowed, msg = guard.check_feature("summarize", mgr)
        assert allowed is True
        assert msg == ""

    def test_code_explain_blocked_when_disabled(self):
        """Code explain returns blocked when codeBlockExplain is False."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "codeBlockExplain": False,
            "privacyAnnounce": True,
        }.get(key, True if default is None else default)
        allowed, msg = guard.check_feature("explain_code", mgr)
        assert allowed is False

    def test_code_explain_allowed_when_enabled(self):
        """Code explain returns allowed when codeBlockExplain is True."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.return_value = True
        allowed, msg = guard.check_feature("explain_code", mgr)
        assert allowed is True
        assert msg == ""

    def test_ai_turn_parse_blocked_when_disabled(self):
        """Future ai_turn_parse feature blocked when its config is False."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "aiTurnParseEnabled": False,
            "privacyAnnounce": True,
        }.get(key, True if default is None else default)
        allowed, msg = guard.check_feature("ai_turn_parse", mgr)
        assert allowed is False

    def test_unknown_feature_returns_blocked(self):
        """An unrecognized feature name returns blocked (safe default)."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        allowed, msg = guard.check_feature("nonexistent_feature", mgr)
        assert allowed is False
        assert "disabled" in msg.lower() or "unknown" in msg.lower()


class TestBlockedMessageContent:
    """Blocked messages must be user-friendly and mention settings."""

    def test_blocked_message_mentions_settings(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": False,
            "privacyAnnounce": True,
        }.get(key, True if default is None else default)
        _, msg = guard.check_feature("summarize", mgr)
        assert "Terminal" in msg or "Settings" in msg or "Privacy" in msg

    def test_blocked_message_mentions_enable(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": False,
            "privacyAnnounce": True,
        }.get(key, True if default is None else default)
        _, msg = guard.check_feature("summarize", mgr)
        # Should guide the user to enable the feature
        assert "enable" in msg.lower() or "disabled" in msg.lower()


class TestPrivacyStatus:
    """format_privacy_status returns a string describing all feature states."""

    def test_status_includes_offline(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.return_value = False
        status = guard.format_privacy_status(mgr)
        assert "offline" in status.lower()

    def test_status_includes_summarization_state(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": True,
            "codeBlockExplain": False,
        }.get(key, default)
        status = guard.format_privacy_status(mgr)
        assert "summarization" in status.lower() or "Summarization" in status

    def test_status_includes_code_explain_state(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": False,
            "codeBlockExplain": True,
        }.get(key, default)
        status = guard.format_privacy_status(mgr)
        assert "code" in status.lower() or "explain" in status.lower()

    def test_status_shows_on_off(self):
        """Status string reflects on/off for each feature."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": True,
            "codeBlockExplain": False,
        }.get(key, default)
        status = guard.format_privacy_status(mgr)
        assert "on" in status.lower() or "off" in status.lower()


class TestIsOfflineOnly:
    """is_offline_only documents that the addon never makes network calls."""

    def test_always_returns_true(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        assert guard.is_offline_only() is True

    def test_return_type_is_bool(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        result = guard.is_offline_only()
        assert isinstance(result, bool)


class TestPrivacyAnnounceConfig:
    """privacyAnnounce config controls whether blocked messages are spoken."""

    def test_announce_true_returns_message(self):
        """When privacyAnnounce is True, check_feature returns message."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": False,
            "privacyAnnounce": True,
        }.get(key, True if default is None else default)
        allowed, msg = guard.check_feature("summarize", mgr)
        assert allowed is False
        assert len(msg) > 0

    def test_announce_false_returns_empty_message(self):
        """When privacyAnnounce is False, blocked message is empty string."""
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.side_effect = lambda key, default=None: {
            "summarizationEnabled": False,
            "privacyAnnounce": False,
        }.get(key, True if default is None else default)
        allowed, msg = guard.check_feature("summarize", mgr)
        assert allowed is False
        assert msg == ""


class TestNoNetworkImports:
    """Scan addon source tree to verify no networking modules are imported."""

    def _scan_addon_files(self):
        """Walk addon/ and return all .py files."""
        addon_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "addon"
        )
        py_files = []
        for root, _dirs, files in os.walk(addon_dir):
            for f in files:
                if f.endswith(".py"):
                    py_files.append(os.path.join(root, f))
        return py_files

    _NETWORK_MODULES = {"urllib", "requests", "http.client", "socket", "httplib"}

    def test_no_network_imports_in_addon(self):
        """No addon .py file imports urllib, requests, http.client, or socket."""
        violations = []
        for filepath in self._scan_addon_files():
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                    source = fh.read()
                tree = ast.parse(source, filename=filepath)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for net_mod in self._NETWORK_MODULES:
                            if alias.name == net_mod or alias.name.startswith(net_mod + "."):
                                violations.append(
                                    f"{filepath}: import {alias.name}"
                                )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for net_mod in self._NETWORK_MODULES:
                            if node.module == net_mod or node.module.startswith(net_mod + "."):
                                violations.append(
                                    f"{filepath}: from {node.module} import ..."
                                )
        assert violations == [], (
            "Network imports found in addon source:\n"
            + "\n".join(violations)
        )


class TestFeatureNameValidation:
    """Feature names passed to check_feature must be from the known set."""

    def test_known_features_accepted(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        mgr.get.return_value = True
        for name in ("summarize", "explain_code", "ai_turn_parse"):
            allowed, _ = guard.check_feature(name, mgr)
            assert allowed is True, f"Known feature {name} should be allowed when config is True"

    def test_empty_feature_name_blocked(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        allowed, msg = guard.check_feature("", mgr)
        assert allowed is False

    def test_none_feature_name_blocked(self):
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = MagicMock()
        allowed, msg = guard.check_feature(None, mgr)
        assert allowed is False
