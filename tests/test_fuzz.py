"""Property-based fuzz tests for Terminal Access pure functions.

Uses hypothesis to generate random inputs and verify invariants.
These tests catch crashes, hangs, and invariant violations that
targeted unit tests miss.
"""
import re
import string

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

# Text that includes ANSI codes, unicode, combining chars, and control chars
ansi_escape = st.sampled_from([
    "\x1b[31m", "\x1b[0m", "\x1b[1;34m", "\x1b[38;5;196m",
    "\x1b[38;2;255;0;0m", "\x1b]8;;https://x.com\x07",
    "\x1b[?25h", "\x1b[2J", "\x1b(B", "",
])

terminal_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "M", "N", "P", "S", "Z"),
        whitelist_characters="\n\t\x1b",
    ),
    min_size=0,
    max_size=200,
)

mixed_text = st.one_of(
    terminal_text,
    st.builds(lambda parts: "".join(parts),
              st.lists(st.one_of(ansi_escape, st.text(max_size=20)), max_size=10)),
)

buffer_lines = st.lists(mixed_text, min_size=0, max_size=50)


# ---------------------------------------------------------------------------
# ANSIParser.stripANSI fuzz
# ---------------------------------------------------------------------------

class TestFuzzANSIParser:

    @given(text=mixed_text)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_strip_ansi_never_crashes(self, text):
        """stripANSI must never raise on any input."""
        from lib.text_processing import ANSIParser
        result = ANSIParser.stripANSI(text)
        assert isinstance(result, str)

    @given(text=mixed_text)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_strip_ansi_no_escape_chars_remain(self, text):
        """After stripping, no ESC characters should remain."""
        from lib.text_processing import ANSIParser
        result = ANSIParser.stripANSI(text)
        # ESC followed by [ or ] should be gone (CSI/OSC sequences)
        assert "\x1b[" not in result
        assert "\x1b]" not in result

    @given(text=st.text(alphabet=string.printable, max_size=100))
    @settings(max_examples=200)
    def test_strip_ansi_idempotent_on_plain_text(self, text):
        """Stripping plain ASCII text (no ESC) returns it unchanged."""
        from lib.text_processing import ANSIParser
        assume("\x1b" not in text)
        assert ANSIParser.stripANSI(text) == text

    @given(text=mixed_text)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_strip_ansi_idempotent(self, text):
        """Stripping twice gives the same result as stripping once."""
        from lib.text_processing import ANSIParser
        once = ANSIParser.stripANSI(text)
        twice = ANSIParser.stripANSI(once)
        assert once == twice

    @given(text=mixed_text)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_parse_never_crashes(self, text):
        """ANSIParser.parse() must never crash on any input."""
        from lib.text_processing import ANSIParser
        parser = ANSIParser()
        result = parser.parse(text)
        assert isinstance(result, dict)
        assert "foreground" in result
        assert "bold" in result

    @given(text=mixed_text)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_format_attributes_never_crashes(self, text):
        """formatAttributes must never crash after parsing any input."""
        from lib.text_processing import ANSIParser
        parser = ANSIParser()
        parser.parse(text)
        for mode in ("brief", "detailed", "change-only"):
            result = parser.formatAttributes(mode)
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# classify_ai_line fuzz
# ---------------------------------------------------------------------------

class TestFuzzClassifyAILine:

    @given(line=mixed_text)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_classify_never_crashes(self, line):
        """classify_ai_line must never raise on any input."""
        from lib.ai_turn_tokenizer import classify_ai_line
        result = classify_ai_line(line)
        assert result is None or (isinstance(result, tuple) and len(result) == 2)

    @given(line=mixed_text)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_classify_returns_known_roles(self, line):
        """If a role is returned, it must be one of the known roles."""
        from lib.ai_turn_tokenizer import classify_ai_line
        result = classify_ai_line(line)
        if result is not None:
            role, preview = result
            assert role in ("user", "assistant", "tool", "system", "code")
            assert isinstance(preview, str)


# ---------------------------------------------------------------------------
# ErrorLineDetector.classify fuzz
# ---------------------------------------------------------------------------

class TestFuzzErrorLineDetector:

    @given(line=mixed_text)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_classify_never_crashes(self, line):
        """ErrorLineDetector.classify must never raise on any input."""
        from lib.text_processing import ErrorLineDetector
        result = ErrorLineDetector.classify(line)
        assert result in (None, "error", "warning", "ai_error", "ai_warning")


# ---------------------------------------------------------------------------
# _clean_url fuzz
# ---------------------------------------------------------------------------

class TestFuzzCleanUrl:

    @given(url=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
        min_size=0, max_size=200,
    ))
    @settings(max_examples=300)
    def test_clean_url_never_crashes(self, url):
        """_clean_url must never raise on any input."""
        from lib.search import _clean_url
        result = _clean_url(url)
        assert isinstance(result, str)
        assert len(result) <= len(url)

    @given(url=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
        min_size=0, max_size=200,
    ))
    @settings(max_examples=200)
    def test_clean_url_no_trailing_punctuation(self, url):
        """After cleaning, URL must not end with trailing punctuation."""
        from lib.search import _clean_url
        result = _clean_url(url)
        if result:
            assert result[-1] not in ".,;:!?"


# ---------------------------------------------------------------------------
# StreamingDeltaTracker._compute_delta fuzz
# ---------------------------------------------------------------------------

class TestFuzzStreamingDelta:

    @given(
        old=st.lists(st.text(max_size=30), max_size=20),
        new=st.lists(st.text(max_size=30), max_size=20),
    )
    @settings(max_examples=500)
    def test_compute_delta_never_crashes(self, old, new):
        """_compute_delta must never raise on any pair of line lists."""
        from lib.streaming_delta import StreamingDeltaTracker
        result = StreamingDeltaTracker._compute_delta(old, new)
        if old == new:
            assert result is None
        elif result is not None:
            assert result.kind in ("new", "added_after", "changed", "mixed", "removed")

    @given(lines=st.lists(st.text(max_size=30), min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_compute_delta_identical_is_none(self, lines):
        """Identical inputs always return None."""
        from lib.streaming_delta import StreamingDeltaTracker
        assert StreamingDeltaTracker._compute_delta(lines, list(lines)) is None

    @given(
        old=st.lists(st.text(max_size=30), max_size=20),
        new=st.lists(st.text(max_size=30), max_size=20),
    )
    @settings(max_examples=300)
    def test_format_speech_never_crashes(self, old, new):
        """_format_speech must never crash on any delta."""
        from lib.streaming_delta import StreamingDeltaTracker
        tracker = StreamingDeltaTracker()
        delta = StreamingDeltaTracker._compute_delta(old, new)
        if delta is not None:
            result = tracker._format_speech(delta)
            assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# SectionTokenizer fuzz
# ---------------------------------------------------------------------------

class TestFuzzSectionTokenizer:

    @given(lines=buffer_lines)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_tokenize_never_crashes(self, lines):
        """tokenize() must never raise on any list of lines."""
        from lib.section_tokenizer import SectionTokenizer
        tokenizer = SectionTokenizer()
        sections = tokenizer.tokenize(lines)
        assert len(sections) == len(lines)

    @given(lines=buffer_lines)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_tokenize_all_categories_known(self, lines):
        """Every section must have a known category."""
        from lib.section_tokenizer import SectionTokenizer
        known = {"prompt", "error", "warning", "stack_trace", "progress",
                 "timestamp", "heading", "output"}
        tokenizer = SectionTokenizer()
        sections = tokenizer.tokenize(lines)
        for sec in sections:
            assert sec.category in known, f"Unknown category: {sec.category}"


# ---------------------------------------------------------------------------
# AITurnTokenizer fuzz
# ---------------------------------------------------------------------------

class TestFuzzAITurnTokenizer:

    @given(lines=buffer_lines)
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_tokenize_never_crashes(self, lines):
        """AITurnTokenizer.tokenize() must never raise."""
        from lib.ai_turn_tokenizer import AITurnTokenizer
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(lines)
        assert isinstance(turns, list)

    @given(lines=buffer_lines)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_turns_within_bounds(self, lines):
        """All turn line numbers must be within buffer bounds."""
        from lib.ai_turn_tokenizer import AITurnTokenizer
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(lines)
        for turn in turns:
            assert 0 <= turn.line_num < len(lines), (
                f"turn.line_num={turn.line_num} out of bounds for {len(lines)} lines"
            )
            assert 0 <= turn.end_line < len(lines), (
                f"turn.end_line={turn.end_line} out of bounds for {len(lines)} lines"
            )


# ---------------------------------------------------------------------------
# UnicodeWidthHelper fuzz
# ---------------------------------------------------------------------------

class TestFuzzUnicodeWidth:

    @given(text=st.text(max_size=100))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_get_text_width_never_negative(self, text):
        """Text width must never be negative."""
        from lib.text_processing import UnicodeWidthHelper
        width = UnicodeWidthHelper.getTextWidth(text)
        assert width >= 0

    @given(text=st.text(min_size=1, max_size=50),
           start=st.integers(min_value=1, max_value=100),
           end=st.integers(min_value=1, max_value=100))
    @settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
    def test_extract_column_range_never_crashes(self, text, start, end):
        """extractColumnRange must never crash on any input."""
        from lib.text_processing import UnicodeWidthHelper
        result = UnicodeWidthHelper.extractColumnRange(text, start, end)
        assert isinstance(result, str)

    @given(text=st.text(min_size=1, max_size=50),
           col=st.integers(min_value=1, max_value=200))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_find_column_position_within_bounds(self, text, col):
        """findColumnPosition must return a valid index."""
        from lib.text_processing import UnicodeWidthHelper
        idx = UnicodeWidthHelper.findColumnPosition(text, col)
        assert 0 <= idx <= len(text)


# ---------------------------------------------------------------------------
# _build_explanation fuzz
# ---------------------------------------------------------------------------

class TestFuzzCodeBlockExplain:

    @given(lines=st.lists(st.text(max_size=80), max_size=30))
    @settings(max_examples=200)
    def test_build_explanation_never_crashes(self, lines):
        """_build_explanation must never raise."""
        from lib.code_block_reader import _build_explanation
        result = _build_explanation(lines)
        assert isinstance(result, str)
        assert len(result) > 0  # always returns something


# ---------------------------------------------------------------------------
# _validateInteger / _validateString fuzz
# ---------------------------------------------------------------------------

class TestFuzzValidation:

    @given(value=st.one_of(
        st.integers(),
        st.floats(allow_nan=False),
        st.text(max_size=20),
        st.none(),
        st.booleans(),
    ))
    @settings(max_examples=300)
    def test_validate_integer_never_crashes(self, value):
        """_validateInteger must never raise on any input type."""
        from lib.config import _validateInteger
        result = _validateInteger(value, 0, 100, 50, "test_field")
        assert isinstance(result, int)
        assert 0 <= result <= 100

    @given(value=st.one_of(
        st.text(max_size=200),
        st.none(),
        st.integers(),
        st.booleans(),
    ))
    @settings(max_examples=200)
    def test_validate_string_never_crashes(self, value):
        """_validateString must never raise on any input type."""
        from lib.config import _validateString
        result = _validateString(value, 50, "default", "test_field")
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# gesture_label fuzz
# ---------------------------------------------------------------------------

class TestFuzzGestureLabel:

    @given(
        gesture=st.text(min_size=1, max_size=30),
        script=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=200)
    def test_gesture_label_never_crashes(self, gesture, script):
        """gesture_label must never raise."""
        from lib._runtime import gesture_label
        result = gesture_label(gesture, script)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# describe_changes fuzz
# ---------------------------------------------------------------------------

class TestFuzzDescribeChanges:

    @given(
        old=st.one_of(st.none(), st.text(max_size=200)),
        new=st.text(max_size=200),
    )
    @settings(max_examples=300)
    def test_describe_changes_never_crashes(self, old, new):
        """describe_changes must never raise."""
        from lib.audio_cues import describe_changes
        result = describe_changes(old, new)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# OutputSummarizer fuzz
# ---------------------------------------------------------------------------

class TestFuzzSummarizer:

    @given(lines=st.lists(mixed_text, max_size=30))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_summarize_never_crashes(self, lines):
        """summarize_lines must never raise."""
        from lib.summarizer import OutputSummarizer
        s = OutputSummarizer()
        result = s.summarize_lines(lines)
        assert isinstance(result, list)
        assert len(result) <= 5  # default max_sentences


# ---------------------------------------------------------------------------
# CodeBlockDetector fuzz
# ---------------------------------------------------------------------------

class TestFuzzCodeBlockDetector:

    @given(lines=buffer_lines)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_detect_never_crashes(self, lines):
        """CodeBlockDetector.detect must never raise."""
        from lib.code_block_reader import CodeBlockDetector
        detector = CodeBlockDetector()
        blocks = detector.detect(lines)
        assert isinstance(blocks, list)
        for block in blocks:
            assert block.start_line < block.end_line
            assert 0 <= block.start_line < len(lines)
            assert 0 <= block.end_line < len(lines)


# ---------------------------------------------------------------------------
# Levenshtein distance fuzz
# ---------------------------------------------------------------------------

class TestFuzzLevenshtein:

    @given(
        s1=st.text(max_size=20),
        s2=st.text(max_size=20),
    )
    @settings(max_examples=300)
    def test_levenshtein_never_crashes(self, s1, s2):
        """Levenshtein distance must never raise."""
        from lib.search import OutputSearchManager
        d = OutputSearchManager._levenshtein_distance(s1, s2)
        assert isinstance(d, int)
        assert d >= 0

    @given(s=st.text(max_size=20))
    @settings(max_examples=100)
    def test_levenshtein_identity(self, s):
        """Distance from a string to itself is always 0."""
        from lib.search import OutputSearchManager
        assert OutputSearchManager._levenshtein_distance(s, s) == 0

    @given(s1=st.text(max_size=15), s2=st.text(max_size=15))
    @settings(max_examples=200)
    def test_levenshtein_symmetric(self, s1, s2):
        """Levenshtein distance must be symmetric: d(a,b) == d(b,a)."""
        from lib.search import OutputSearchManager
        assert OutputSearchManager._levenshtein_distance(s1, s2) == \
               OutputSearchManager._levenshtein_distance(s2, s1)

    @given(s1=st.text(max_size=10), s2=st.text(max_size=10))
    @settings(max_examples=200)
    def test_levenshtein_triangle_inequality(self, s1, s2):
        """d(a,b) <= len(a) + len(b) (loose upper bound)."""
        from lib.search import OutputSearchManager
        d = OutputSearchManager._levenshtein_distance(s1, s2)
        assert d <= len(s1) + len(s2)


# ---------------------------------------------------------------------------
# PrivacyGuard fuzz
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TextDiffer fuzz
# ---------------------------------------------------------------------------

class TestFuzzTextDiffer:

    @given(
        texts=st.lists(st.text(max_size=200), min_size=2, max_size=5),
    )
    @settings(max_examples=200)
    def test_differ_never_crashes(self, texts):
        """TextDiffer.update must never crash on any sequence of texts."""
        from lib.caching import TextDiffer
        differ = TextDiffer()
        for text in texts:
            kind, content = differ.update(text)
            assert kind in ("initial", "unchanged", "appended", "changed",
                           "last_line_updated")
            assert isinstance(content, str)

    @given(text=st.text(max_size=200))
    @settings(max_examples=100)
    def test_differ_same_text_unchanged(self, text):
        """Feeding the same text twice should return 'unchanged'."""
        from lib.caching import TextDiffer
        differ = TextDiffer()
        differ.update(text)
        kind, _ = differ.update(text)
        assert kind == "unchanged"


# ---------------------------------------------------------------------------
# WindowMonitor.add_monitor edge cases
# ---------------------------------------------------------------------------

class TestFuzzWindowMonitor:

    @given(
        top=st.integers(min_value=-100, max_value=200),
        left=st.integers(min_value=-100, max_value=200),
        bottom=st.integers(min_value=-100, max_value=200),
        right=st.integers(min_value=-100, max_value=200),
    )
    @settings(max_examples=200)
    def test_add_monitor_rejects_invalid_bounds(self, top, left, bottom, right):
        """add_monitor must reject invalid window bounds without crashing."""
        from lib.window_management import WindowMonitor
        from unittest.mock import Mock
        monitor = WindowMonitor(Mock(), Mock())
        result = monitor.add_monitor("test", (top, left, bottom, right))
        if top < 1 or left < 1 or top > bottom or left > right:
            assert result is False
        assert isinstance(result, bool)


class TestFuzzPrivacyGuard:

    @given(feature=st.text(max_size=30))
    @settings(max_examples=100)
    def test_check_feature_never_crashes(self, feature):
        """check_feature must never raise on any feature name."""
        from lib.privacy import PrivacyGuard
        from unittest.mock import Mock
        guard = PrivacyGuard()
        mock_config = Mock()
        mock_config.get = Mock(return_value=False)
        allowed, msg = guard.check_feature(feature, mock_config)
        assert isinstance(allowed, bool)
        assert isinstance(msg, str)
