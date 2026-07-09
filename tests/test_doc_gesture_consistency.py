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

_GUIDE = os.path.join("addon", "doc", "en", "readme.md")


def _norm(gesture):
    """Normalize a gesture string for comparison (code key or guide token)."""
    g = gesture.lower().replace("kb:", "")
    for word, symbol in (("minus", "-"), ("equals", "="), ("apostrophe", "'")):
        g = g.replace(word, symbol)
    return g


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


class TestNormalizer:
    """Guard the normalizer so the checks above cannot silently pass."""

    def test_symbol_words_map_to_symbols(self):
        assert _norm("NVDA+minus") == "nvda+-"
        assert _norm("NVDA+equals") == "nvda+="
        assert _norm("NVDA+apostrophe") == "nvda+'"

    def test_case_and_prefix_stripped(self):
        assert _norm("kb:NVDA+Alt+G") == "nvda+alt+g"
