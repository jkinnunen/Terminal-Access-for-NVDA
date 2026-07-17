"""Punctuation keys are named by word, never left as a bare symbol.

A screen reader reads a bare symbol at the user's punctuation level, and
at the low levels most people use for terminal work it says nothing at
all. So "NVDA+'" is spoken as "NVDA plus" and the command is unusable by
ear. Naming the key ("NVDA+apostrophe") keeps every command audible
regardless of punctuation level.

KEY_WORDS in lib._runtime is the single source of truth: the command
finder, the settings panel, and the shipped guide all resolve through it,
so a new punctuation binding cannot be documented one way and spoken
another.
"""
import pytest

from lib._runtime import KEY_WORDS, gesture_label, spell_key


class TestKeyWords:
    """The symbol -> word map covers every punctuation key we bind."""

    def test_covers_every_punctuation_key_bound_by_the_addon(self):
        from globalPlugins.terminalAccess import (
            _COMMAND_LAYER_MAP,
            _DEFAULT_GESTURES,
            _TABLE_MODE_BINDINGS,
        )

        bound_punctuation = set()
        for mapping in (_DEFAULT_GESTURES, _COMMAND_LAYER_MAP, _TABLE_MODE_BINDINGS):
            for gesture in mapping:
                # A double-press binding is two gestures joined by a comma,
                # e.g. "kb:NVDA+k,kb:NVDA+k". Split those apart first so the
                # separator is not mistaken for a bound key.
                for single in gesture.split(","):
                    for part in single.replace("kb:", "").split("+"):
                        if part and not part.isalnum():
                            bound_punctuation.add(part)

        missing = sorted(bound_punctuation - set(KEY_WORDS))
        assert not missing, (
            f"Punctuation keys are bound but have no spoken word: {missing}. "
            "Add them to KEY_WORDS so they are announced and documented."
        )

    def test_words_are_alphabetic_so_they_always_speak(self):
        for symbol, word in KEY_WORDS.items():
            assert word.replace(" ", "").isalpha(), (
                f"{symbol!r} maps to {word!r}, which is not plain words"
            )


class TestSpellKey:
    """spell_key names punctuation and leaves everything else alone."""

    @pytest.mark.parametrize(
        "symbol,word",
        [
            ("'", "apostrophe"),
            (",", "comma"),
            (".", "period"),
            (";", "semicolon"),
            ("-", "minus"),
            ("=", "equals"),
        ],
    )
    def test_punctuation_becomes_a_word(self, symbol, word):
        assert spell_key(symbol) == word

    def test_letters_and_named_keys_pass_through(self):
        assert spell_key("a") == "a"
        assert spell_key("shift") == "shift"
        assert spell_key("f1") == "f1"


class TestGestureLabelSpellsPunctuation:
    """The label shown in the command finder names punctuation keys."""

    def test_command_layer_key_is_named(self):
        label = gesture_label("kb:NVDA+'", "toggleCommandLayer")
        assert "NVDA+apostrophe" in label
        assert "NVDA+'" not in label

    def test_punctuation_level_keys_are_named(self):
        assert "NVDA+minus" in gesture_label("kb:NVDA+-", "decreasePunctuationLevel")
        assert "NVDA+equals" in gesture_label("kb:NVDA+=", "increasePunctuationLevel")

    def test_character_reading_keys_are_named(self):
        assert "NVDA+comma" in gesture_label("kb:NVDA+,", "readCurrentChar")
        assert "NVDA+period" in gesture_label("kb:NVDA+.", "readNextChar")

    def test_position_key_is_named(self):
        assert "NVDA+semicolon" in gesture_label("kb:NVDA+;", "announcePosition")

    def test_letter_gestures_are_unchanged(self):
        assert gesture_label("kb:NVDA+c", "copyLinearSelection").startswith("NVDA+C")

    def test_modifier_combination_still_formats(self):
        assert gesture_label("kb:NVDA+alt+g", "toggleTableMode").startswith(
            "NVDA+Alt+G"
        )


class TestDoublePressLabel:
    """A double-press binding reads as one gesture pressed twice.

    The binding joins two gestures with a comma ("kb:NVDA+k,kb:NVDA+k").
    Rendered literally that becomes "NVDA+K,nvda+K": the comma is silent
    at most punctuation levels and the second half loses its casing, so
    the command finder announced a command that does not look like any
    key the user can press.
    """

    def test_repeated_gesture_reads_as_twice(self):
        label = gesture_label("kb:NVDA+k,kb:NVDA+k", "spellCurrentWord")
        assert "NVDA+K twice" in label

    def test_double_press_does_not_mangle_the_nvda_key(self):
        label = gesture_label("kb:NVDA+k,kb:NVDA+k", "spellCurrentWord")
        assert "nvda" not in label.split("—")[0].replace("NVDA", "")

    def test_distinct_gestures_are_listed(self):
        label = gesture_label("kb:NVDA+k,kb:NVDA+j", "someScript")
        assert "NVDA+K, NVDA+J" in label
