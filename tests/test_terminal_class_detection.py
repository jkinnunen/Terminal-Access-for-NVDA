"""Detect terminals by what NVDA decided they are, not just by app name.

Users reported terminals the add-on did not support. Detection matched
`appModule.appName` against a hand-maintained list, so any terminal not
enumerated was invisible, and every new terminal needed a code change.

NVDA already classifies terminals: it inserts a Terminal subclass into
clsList (WinConsoleUIA for the modern console, and
KeyboardHandlerBasedTypedCharSupport for PuTTY and mintty). Note it
inserts SUBCLASSES; `Terminal` itself is never in clsList, so the check
must be issubclass, not `Terminal in clsList`.

The app-name list is kept as a union, not replaced: roughly half of the
supported names (ConEmu, Cmder, Alacritty, WezTerm, MobaXterm, Tera
Term...) have no NVDA appModule, so it is unproven whether NVDA classes
them as terminals. Union widens coverage without losing anything.
"""
from unittest.mock import MagicMock, patch

import pytest

from NVDAObjects.behaviors import Terminal


class _ConsoleLike(Terminal):
    """Stands in for WinConsoleUIA / KeyboardHandlerBasedTypedCharSupport."""


class _NotATerminal:
    pass


def _plugin():
    from globalPlugins.terminalAccess import GlobalPlugin
    with patch("gui.settingsDialogs.NVDASettingsDialog"):
        return GlobalPlugin()


class TestHasTerminalClass:
    def test_true_for_a_terminal_subclass(self):
        """The real case: NVDA inserts a subclass, never Terminal itself."""
        from lib.terminal_overlay import has_terminal_class
        assert has_terminal_class([_ConsoleLike, _NotATerminal]) is True

    def test_true_for_terminal_itself(self):
        from lib.terminal_overlay import has_terminal_class
        assert has_terminal_class([Terminal]) is True

    def test_false_without_a_terminal(self):
        from lib.terminal_overlay import has_terminal_class
        assert has_terminal_class([_NotATerminal]) is False

    def test_false_for_empty_list(self):
        from lib.terminal_overlay import has_terminal_class
        assert has_terminal_class([]) is False

    def test_ignores_non_class_entries(self):
        """clsList should hold classes, but never raise if it does not."""
        from lib.terminal_overlay import has_terminal_class
        assert has_terminal_class(["not a class", 42, None]) is False


class TestOverlayInsertion:
    def test_inserts_for_unknown_app_that_nvda_calls_a_terminal(self):
        """The bug being fixed: a terminal we never enumerated."""
        from lib.terminal_overlay import TerminalAccessTerminal
        plugin = _plugin()
        obj = MagicMock()
        obj.appModule.appName = "someterminalwehaveneverheardof"
        clsList = [_ConsoleLike]

        plugin.chooseNVDAObjectOverlayClasses(obj, clsList)

        assert clsList[0] is TerminalAccessTerminal

    def test_still_inserts_for_known_app_without_a_terminal_class(self):
        """Union, not replacement: app-name support must survive."""
        from lib.terminal_overlay import TerminalAccessTerminal
        plugin = _plugin()
        obj = MagicMock()
        obj.appModule.appName = "windowsterminal"
        clsList = [_NotATerminal]

        plugin.chooseNVDAObjectOverlayClasses(obj, clsList)

        assert clsList[0] is TerminalAccessTerminal

    def test_does_not_insert_for_unrelated_app(self):
        from lib.terminal_overlay import TerminalAccessTerminal
        plugin = _plugin()
        obj = MagicMock()
        obj.appModule.appName = "notepad"
        clsList = [_NotATerminal]

        plugin.chooseNVDAObjectOverlayClasses(obj, clsList)

        assert TerminalAccessTerminal not in clsList

    def test_does_not_insert_twice(self):
        from lib.terminal_overlay import TerminalAccessTerminal
        plugin = _plugin()
        obj = MagicMock()
        obj.appModule.appName = "windowsterminal"
        clsList = [TerminalAccessTerminal, _ConsoleLike]

        plugin.chooseNVDAObjectOverlayClasses(obj, clsList)

        assert clsList.count(TerminalAccessTerminal) == 1

    def test_missing_app_module_still_works_via_class(self):
        """An object with no appModule is not a reason to ignore a
        terminal NVDA already identified."""
        from lib.terminal_overlay import TerminalAccessTerminal
        plugin = _plugin()
        obj = MagicMock()
        type(obj).appModule = property(
            lambda self: (_ for _ in ()).throw(AttributeError("no appModule"))
        )
        clsList = [_ConsoleLike]

        plugin.chooseNVDAObjectOverlayClasses(obj, clsList)

        assert clsList[0] is TerminalAccessTerminal


class TestIsTerminalApp:
    def test_true_for_terminal_instance_with_unknown_app_name(self):
        plugin = _plugin()
        obj = _ConsoleLike()
        obj.appModule = MagicMock()
        obj.appModule.appName = "brandnewterminal"

        assert plugin.isTerminalApp(obj) is True

    def test_true_for_known_app_name_without_terminal_class(self):
        plugin = _plugin()
        obj = MagicMock(spec=[])
        obj.appModule = MagicMock()
        obj.appModule.appName = "putty"

        assert plugin.isTerminalApp(obj) is True

    def test_false_for_unrelated_app(self):
        plugin = _plugin()
        obj = MagicMock(spec=[])
        obj.appModule = MagicMock()
        obj.appModule.appName = "notepad"

        assert plugin.isTerminalApp(obj) is False

    def test_terminal_instance_result_is_not_cached_by_app_name(self):
        """One app can own both terminal and non-terminal windows, so a
        class-based hit must not poison the app-name cache."""
        plugin = _plugin()
        term = _ConsoleLike()
        term.appModule = MagicMock()
        term.appModule.appName = "mixedapp"
        assert plugin.isTerminalApp(term) is True

        other = MagicMock(spec=[])
        other.appModule = MagicMock()
        other.appModule.appName = "mixedapp"
        assert plugin.isTerminalApp(other) is False
