"""Terminal Access owns typing echo inside terminals.

Key Echo used to do nothing whenever either of NVDA's global typing
settings was on, because NVDA's speakTypedCharacters() both speaks the
character AND accumulates the word buffer that word echo is built from.
Skipping it to avoid double-speech corrupted word echo, so the add-on
stood down entirely. The result was a setting that silently did nothing.

The word buffer only matters when word echo is on, which is what makes
this fixable:

- Speak typed words OFF: skipping NVDA's handler costs nothing, so our
  echo takes over and Key Echo finally applies.
- Speak typed words ON, our Word Echo off: NVDA keeps the keystrokes so
  its word echo still works, and we stand down as before.
- Our Word Echo on: we own words too, so we take over regardless.

Nobody loses word echo without explicitly enabling ours to replace it.
"""
from unittest.mock import MagicMock, patch

import pytest


def _plugin(key_echo=True, word_echo=False, nvda_chars=0, nvda_words=0,
            quiet=False):
    import config
    from globalPlugins.terminalAccess import GlobalPlugin
    with patch("gui.settingsDialogs.NVDASettingsDialog"):
        plugin = GlobalPlugin()
    cfg = {
        "keyEcho": key_echo, "wordEcho": word_echo, "quietMode": quiet,
        "repeatedSymbols": False,
    }
    plugin._configManager = MagicMock()
    plugin._configManager.get = MagicMock(side_effect=lambda k, d=None: cfg.get(k, d))
    plugin._getEffective = MagicMock(side_effect=lambda k, d=None: cfg.get(k, d))
    config.conf["keyboard"]["speakTypedCharacters"] = nvda_chars
    config.conf["keyboard"]["speakTypedWords"] = nvda_words
    return plugin


def _type(plugin, text):
    """Feed characters through the typed-character path."""
    called = []
    for ch in text:
        plugin._terminalTypedCharacter(MagicMock(), ch,
                                       lambda: called.append(True))
    return called


class TestWhoEchoes:
    def test_takes_over_when_only_nvda_characters_is_on(self):
        """The reported confusion: Key Echo on, NVDA characters on, and
        nothing from Key Echo. Now we own it."""
        plugin = _plugin(key_echo=True, nvda_chars=2, nvda_words=0)
        plugin._speakCharacter = MagicMock()

        nvda_called = _type(plugin, "a")

        assert not nvda_called, "NVDA's handler must not also echo"
        plugin._speakCharacter.assert_called_once_with("a")

    def test_takes_over_when_nvda_echo_is_entirely_off(self):
        plugin = _plugin(key_echo=True, nvda_chars=0, nvda_words=0)
        plugin._speakCharacter = MagicMock()

        nvda_called = _type(plugin, "a")

        assert not nvda_called
        plugin._speakCharacter.assert_called_once()

    def test_defers_when_nvda_word_echo_is_on_and_ours_is_off(self):
        """NVDA needs every keystroke to build its words, so it must
        still receive them, and we must not double-speak."""
        plugin = _plugin(key_echo=True, word_echo=False,
                         nvda_chars=2, nvda_words=2)
        plugin._speakCharacter = MagicMock()

        nvda_called = _type(plugin, "a")

        assert nvda_called, "NVDA must keep receiving keystrokes"
        plugin._speakCharacter.assert_not_called()

    def test_takes_over_word_echo_when_ours_is_enabled(self):
        """Enabling our word echo is the explicit opt-in to replace
        NVDA's, so we own typing completely."""
        plugin = _plugin(key_echo=True, word_echo=True,
                         nvda_chars=2, nvda_words=2)
        plugin._speakCharacter = MagicMock()

        nvda_called = _type(plugin, "a")

        assert not nvda_called
        plugin._speakCharacter.assert_called_once()

    def test_key_echo_off_leaves_nvda_alone(self):
        plugin = _plugin(key_echo=False, word_echo=False,
                         nvda_chars=2, nvda_words=0)
        plugin._speakCharacter = MagicMock()

        nvda_called = _type(plugin, "a")

        assert nvda_called
        plugin._speakCharacter.assert_not_called()

    def test_quiet_mode_silences_everything(self):
        plugin = _plugin(key_echo=True, nvda_chars=2, quiet=True)
        plugin._speakCharacter = MagicMock()

        nvda_called = _type(plugin, "a")

        assert not nvda_called
        plugin._speakCharacter.assert_not_called()


class TestOurWordEcho:
    def _plugin_with_words(self, **kw):
        plugin = _plugin(key_echo=False, word_echo=True, **kw)
        plugin._speakCharacter = MagicMock()
        return plugin

    def test_word_spoken_on_a_word_boundary(self):
        import ui
        plugin = self._plugin_with_words()
        ui.message.reset_mock()

        _type(plugin, "git ")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "git" in spoken

    def test_word_not_spoken_until_the_boundary(self):
        import ui
        plugin = self._plugin_with_words()
        ui.message.reset_mock()

        _type(plugin, "git")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "git" not in spoken

    def test_backspace_removes_from_the_buffer(self):
        import ui
        plugin = self._plugin_with_words()
        ui.message.reset_mock()

        _type(plugin, "gitx\bs ")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "gits" in spoken

    def test_protected_typing_never_speaks_the_word(self):
        """A password is exactly a run of characters ending in Enter."""
        import api
        import ui
        api.isTypingProtected = MagicMock(return_value=True)
        plugin = self._plugin_with_words()
        ui.message.reset_mock()

        _type(plugin, "hunter2 ")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "hunter2" not in spoken

    def test_word_echo_off_speaks_no_words(self):
        import ui
        plugin = _plugin(key_echo=True, word_echo=False,
                         nvda_chars=0, nvda_words=0)
        plugin._speakCharacter = MagicMock()
        ui.message.reset_mock()

        _type(plugin, "git ")

        spoken = " ".join(str(c.args[0]) for c in ui.message.call_args_list)
        assert "git" not in spoken


class TestInertEchoWarning:
    """Key Echo must never be silently inert.

    One combination still leaves it quiet by design (NVDA's word echo on,
    ours off). That is defensible, but the user has to be told, or they
    enable a setting, hear nothing, and have no way to find out why.
    """

    def _panel(self, key_echo, word_echo, nvda_words):
        import config
        from lib.settings_panel import TerminalAccessSettingsPanel

        panel = TerminalAccessSettingsPanel.__new__(TerminalAccessSettingsPanel)
        config.conf["terminalAccess"]["keyEcho"] = key_echo
        config.conf["terminalAccess"]["wordEcho"] = word_echo
        config.conf["keyboard"]["speakTypedWords"] = nvda_words
        return panel

    def test_warns_when_nvda_word_echo_wins(self):
        import ui
        panel = self._panel(key_echo=True, word_echo=False, nvda_words=2)
        ui.message.reset_mock()

        panel._warnIfEchoInert()

        assert ui.message.called

    def test_silent_when_we_own_the_echo(self):
        import ui
        panel = self._panel(key_echo=True, word_echo=False, nvda_words=0)
        ui.message.reset_mock()

        panel._warnIfEchoInert()

        assert not ui.message.called

    def test_silent_when_our_word_echo_takes_over(self):
        import ui
        panel = self._panel(key_echo=True, word_echo=True, nvda_words=2)
        ui.message.reset_mock()

        panel._warnIfEchoInert()

        assert not ui.message.called

    def test_silent_when_key_echo_is_off(self):
        import ui
        panel = self._panel(key_echo=False, word_echo=False, nvda_words=2)
        ui.message.reset_mock()

        panel._warnIfEchoInert()

        assert not ui.message.called
