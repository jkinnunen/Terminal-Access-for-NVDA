# Privacy guardrails for Terminal Access.
# Gates opt-in features behind config flags and documents the addon's
# offline-only design. No network calls are made anywhere in this addon.

from typing import Tuple


# Map from feature name to the config key that gates it.
_FEATURE_CONFIG_KEYS = {
    "summarize": "summarizationEnabled",
    "explain_code": "codeBlockExplain",
    "ai_turn_parse": "aiTurnParseEnabled",
}

# Blocked message shown to the user (when privacyAnnounce is True).
_BLOCKED_MESSAGE = "Feature disabled. Enable in Terminal Settings under Privacy."


class PrivacyGuard:
    """Central gatekeeper for privacy-sensitive features.

    Every opt-in feature (summarization, code explanation, AI turn
    parsing) must call check_feature() before proceeding. The guard
    consults the ConfigManager to decide whether the feature is allowed.

    The addon is fully offline; is_offline_only() always returns True.
    """

    def check_feature(
        self, feature_name: str, config_manager
    ) -> Tuple[bool, str]:
        """Check whether a gated feature is allowed by the current config.

        Args:
            feature_name: One of the known feature names (see
                _FEATURE_CONFIG_KEYS) or a future feature string.
            config_manager: A ConfigManager (or mock) with a .get() method.

        Returns:
            (allowed, message) tuple. When allowed is True the message is
            empty. When allowed is False the message explains how to
            enable the feature (unless privacyAnnounce is False, in
            which case the message is also empty).
        """
        if not feature_name or feature_name not in _FEATURE_CONFIG_KEYS:
            # Unknown or empty feature name: block by default.
            announce = True
            try:
                announce = config_manager.get("privacyAnnounce", True)
            except Exception:
                pass
            if announce:
                return (False, _BLOCKED_MESSAGE)
            return (False, "")

        config_key = _FEATURE_CONFIG_KEYS[feature_name]
        enabled = config_manager.get(config_key, False)

        if enabled:
            return (True, "")

        # Feature is disabled. Decide whether to include a spoken message.
        announce = config_manager.get("privacyAnnounce", True)
        if announce:
            return (False, _BLOCKED_MESSAGE)
        return (False, "")

    @staticmethod
    def is_offline_only() -> bool:
        """Return True to document that this addon never makes network calls.

        This is a static assertion, not a runtime check. The addon has
        no dependencies on urllib, requests, http.client, or socket.
        """
        return True

    def format_privacy_status(self, config_manager) -> str:
        """Build a human-readable privacy status string.

        Args:
            config_manager: A ConfigManager (or mock) with a .get() method.

        Returns:
            A string like:
            "Privacy: all features offline.
             Summarization: on. Code explain: off."
        """
        summarization = config_manager.get("summarizationEnabled", False)
        code_explain = config_manager.get("codeBlockExplain", False)

        parts = ["Privacy: all features offline."]
        parts.append(
            "Summarization: {}.".format("on" if summarization else "off")
        )
        parts.append(
            "Code explain: {}.".format("on" if code_explain else "off")
        )
        return " ".join(parts)
