"""Never speak a password out loud.

NVDA masks typed characters when api.isTypingProtected() is true,
substituting PROTECTED_CHAR ("*") for the real character, and suppresses
word echo entirely. Terminal Access does its own typing echo, so it must
honour the same rule: an echo that ignores protection reads the user's
password aloud to the room.

This mattered less while the add-on stood down whenever NVDA was
echoing, because NVDA did the masking. Now that Terminal Access takes
over typing echo inside terminals, the responsibility is ours.
"""
from unittest.mock import MagicMock, patch

import pytest


def _plugin(cfg=None):
    from globalPlugins.terminalAccess import GlobalPlugin
    with patch("gui.settingsDialogs.NVDASettingsDialog"):
        plugin = GlobalPlugin()
    cfg = cfg or {}
    plugin._configManager = MagicMock()
    plugin._configManager.get = MagicMock(side_effect=lambda k, d=None: cfg.get(k, d))
    plugin._getEffective = MagicMock(side_effect=lambda k, d=None: cfg.get(k, d))
    return plugin


@pytest.fixture
def protected():
    """Toggle NVDA's protected-typing state."""
    import api
    original = getattr(api, "isTypingProtected", None)

    def setup(value):
        api.isTypingProtected = MagicMock(return_value=value)

    yield setup
    if original is not None:
        api.isTypingProtected = original


class TestCharacterEchoMasking:
    def test_password_character_is_not_spoken(self, protected):
        """The whole point: the typed character must not reach speech."""
        import ui
        protected(True)
        plugin = _plugin()
        ui.message.reset_mock()

        plugin._speakCharacter("s")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "s" not in spoken.replace("star", "").replace("asterisk", "")

    def test_masked_character_is_announced_instead(self, protected):
        """Silence would be worse than a mask: the user needs feedback
        that the keystroke registered."""
        import ui
        protected(True)
        plugin = _plugin()
        ui.message.reset_mock()

        plugin._speakCharacter("s")

        assert ui.message.called

    def test_normal_character_is_unaffected(self, protected):
        import ui
        protected(False)
        plugin = _plugin()
        ui.message.reset_mock()

        plugin._speakCharacter("s")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "s" in spoken

    def test_missing_api_defaults_to_masking(self, protected):
        """If protection state cannot be determined, assume protected.
        Speaking a password by accident is far worse than masking a
        character that did not need it."""
        import api
        import ui
        plugin = _plugin()
        api.isTypingProtected = MagicMock(side_effect=RuntimeError("gone"))
        ui.message.reset_mock()

        plugin._speakCharacter("s")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "s" not in spoken.replace("star", "").replace("asterisk", "")


class TestTypedCharacterPathMasking:
    def _typed(self, plugin, ch):
        plugin._terminalTypedCharacter(MagicMock(), ch, lambda: None)

    def test_repeated_symbol_condensing_does_not_leak(self, protected):
        """Condensing must not run on protected input: it would build a
        run out of the real characters."""
        import ui
        protected(True)
        plugin = _plugin({
            "keyEcho": True, "quietMode": False,
            "repeatedSymbols": True, "repeatedSymbolsValues": "-",
        })
        plugin._isKeyEchoActive = MagicMock(return_value=True)
        ui.message.reset_mock()

        for _ in range(4):
            self._typed(plugin, "-")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "4 times" not in spoken

    def test_protected_typing_still_updates_braille(self, protected):
        """Braille tracking is a cursor move, not content disclosure, and
        the display itself is already private to the reader."""
        import braille
        protected(True)
        plugin = _plugin({"keyEcho": True, "quietMode": False})
        braille.handler.handleCaretMove.reset_mock()

        self._typed(plugin, "s")

        braille.handler.handleCaretMove.assert_called()
