"""Keep the user guide and the code in sync on gestures.

Two invariants, both aimed at the claim-vs-reality gap:

1. code -> script: every gesture bound in the code (_DEFAULT_GESTURES,
   the command layer, and the table-mode map) names a script that actually
   exists on GlobalPlugin. Catches a binding pointing at a missing script.

2. guide -> code: every direct gesture (NVDA+...) the shipped user guide
   names is a real binding in _DEFAULT_GESTURES. Catches the guide
   documenting a shortcut that does not exist.

Command-layer single keys in the guide's prose are intentionally not
parsed here; they are too ambiguous to normalize without false alarms.
The code->script check already covers every command-layer binding.
"""
import os
import re

import pytest

from globalPlugins.terminalAccess import (
    GlobalPlugin,
    _DEFAULT_GESTURES,
    _COMMAND_LAYER_MAP,
    _TABLE_MODE_BINDINGS,
)
from lib._runtime import KEY_WORDS

_GUIDE = os.path.join("addon", "doc", "en", "readme.md")


_WORDS_TO_SYMBOLS = {word: symbol for symbol, word in KEY_WORDS.items()}


def _norm(gesture):
    """Normalize a gesture string for comparison (code key or guide token).

    The guide names punctuation keys ("NVDA+apostrophe") while the code
    binds the symbol ("kb:NVDA+'"), so map the words back to compare.
    KEY_WORDS is the shared source of truth, so a punctuation key added
    to the code cannot be missed here.
    """
    g = gesture.lower().replace("kb:", "")
    return "+".join(_WORDS_TO_SYMBOLS.get(part, part) for part in g.split("+"))


def _all_bound_script_names():
    names = set()
    for mapping in (_DEFAULT_GESTURES, _COMMAND_LAYER_MAP, _TABLE_MODE_BINDINGS):
        names.update(mapping.values())
    return names


class TestCodeToScript:
    """Every bound gesture points at a script that exists."""

    def test_every_bound_gesture_has_a_script(self):
        missing = [
            name for name in _all_bound_script_names()
            if not hasattr(GlobalPlugin, f"script_{name}")
        ]
        assert not missing, f"Gestures bound to nonexistent scripts: {missing}"


class TestGuideToCode:
    """Every direct gesture the guide names is a real binding."""

    def _guide_direct_gestures(self):
        text = open(_GUIDE, encoding="utf-8").read()
        return set(re.findall(r"NVDA\+[A-Za-z0-9;,.=+-]+", text))

    def test_guide_exists(self):
        assert os.path.isfile(_GUIDE), "Shipped user guide is missing"

    def test_every_documented_direct_gesture_is_bound(self):
        bound = {_norm(k) for k in _DEFAULT_GESTURES}
        undocumented = sorted(
            g for g in self._guide_direct_gestures() if _norm(g) not in bound
        )
        assert not undocumented, (
            f"Guide documents direct gestures with no binding: {undocumented}"
        )


class TestPunctuationNamedByWord:
    """The guide never presents a punctuation key as a bare symbol.

    A screen reader speaks a bare symbol at the reader's punctuation
    level, which is usually low or off for terminal work, so "NVDA+;"
    is heard as "NVDA plus" and the command cannot be learned by ear.
    Every punctuation key is written as a word instead.
    """

    def _guide_text(self):
        return open(_GUIDE, encoding="utf-8").read()

    def test_no_direct_gesture_uses_a_bare_symbol(self):
        text = self._guide_text()
        offenders = sorted(
            f"NVDA+{symbol}" for symbol in KEY_WORDS if f"NVDA+{symbol}" in text
        )
        assert not offenders, (
            f"Guide writes punctuation gestures as symbols: {offenders}. "
            "Use the word instead, e.g. NVDA+apostrophe."
        )

    def test_no_command_layer_key_is_a_bare_symbol(self):
        """Catches the key column of the command reference tables.

        Those cells are bold, so check bold spans and split the "a / b"
        alternatives the tables use.
        """
        offenders = []
        for span in re.findall(r"\*\*(.+?)\*\*", self._guide_text()):
            for token in span.split("/"):
                if token.strip() in KEY_WORDS:
                    offenders.append(span)
        assert not offenders, (
            f"Guide lists punctuation keys as bare symbols: {sorted(set(offenders))}. "
            "Name the key instead, e.g. semicolon."
        )


class TestNormalizer:
    """Guard the normalizer so the checks above cannot silently pass."""

    def test_symbol_words_map_to_symbols(self):
        assert _norm("NVDA+minus") == "nvda+-"
        assert _norm("NVDA+equals") == "nvda+="
        assert _norm("NVDA+apostrophe") == "nvda+'"
        assert _norm("NVDA+comma") == "nvda+,"
        assert _norm("NVDA+period") == "nvda+."
        assert _norm("NVDA+semicolon") == "nvda+;"

    def test_case_and_prefix_stripped(self):
        assert _norm("kb:NVDA+Alt+G") == "nvda+alt+g"

    def test_unknown_parts_pass_through_untouched(self):
        assert _norm("NVDA+shift+f1") == "nvda+shift+f1"
