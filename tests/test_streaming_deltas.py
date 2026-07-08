"""Tests for StreamingDeltaTracker: buffer delta detection with debounce and verbosity."""
import time
from unittest.mock import patch

import pytest


class TestStreamingDeltaEmptyToContent:
    """When buffer goes from empty to having content."""

    def test_empty_to_five_lines(self):
        """Empty snapshot then 5 lines produces '5 new lines'."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot([])
        result = tracker.take_snapshot(["a", "b", "c", "d", "e"])
        assert result == "5 new lines"

    def test_none_to_content(self):
        """First ever snapshot (no previous) returns None (no delta to report)."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        result = tracker.take_snapshot(["a", "b", "c"])
        assert result is None


class TestStreamingDeltaAppend:
    """When lines are appended to existing content."""

    def test_two_lines_appended(self):
        """Appending 2 lines reports them added after the last existing line."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["line1", "line2", "line3"])
        result = tracker.take_snapshot(["line1", "line2", "line3", "line4", "line5"])
        assert result == "2 lines added after line 3"

    def test_one_line_appended(self):
        """Appending 1 line reports it added after the last existing line."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["line1"])
        result = tracker.take_snapshot(["line1", "line2"])
        assert result == "1 line added after line 1"


class TestStreamingDeltaChanged:
    """When existing lines change in place."""

    def test_line_changed_in_place(self):
        """Changing line 3 produces 'line 3 changed'."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c", "d"])
        result = tracker.take_snapshot(["a", "b", "CHANGED", "d"])
        assert result == "line 3 changed"

    def test_multiple_lines_changed(self):
        """Changing 2 lines produces '2 lines changed'."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c", "d"])
        result = tracker.take_snapshot(["a", "X", "Y", "d"])
        assert result == "2 lines changed"


class TestStreamingDeltaMixed:
    """When lines are both changed and added."""

    def test_changed_and_added(self):
        """Mixed changes: reports added lines when both changed and added."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c"])
        result = tracker.take_snapshot(["a", "X", "c", "d", "e"])
        # 1 changed + 2 added: report as combined summary
        assert "2 new lines" in result or "changed" in result


class TestStreamingDeltaDebounce:
    """Debounce: rapid changes within interval produce single delta."""

    def test_debounce_blocks_rapid_changes(self):
        """Changes within debounce interval return None."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(debounce_ms=500)
        tracker.take_snapshot(["a"])
        # First delta after snapshot is allowed
        result1 = tracker.take_snapshot(["a", "b"])
        assert result1 is not None
        # Immediate second call within debounce window returns None
        result2 = tracker.take_snapshot(["a", "b", "c"])
        assert result2 is None

    def test_debounce_allows_after_interval(self):
        """Changes after debounce interval are reported."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(debounce_ms=50)
        tracker.take_snapshot(["a"])
        tracker.take_snapshot(["a", "b"])
        time.sleep(0.06)  # Wait past debounce
        result = tracker.take_snapshot(["a", "b", "c"])
        assert result is not None


class TestStreamingDeltaQuietMode:
    """Quiet mode (verbosity 0): no speech output."""

    def test_quiet_returns_none(self):
        """Verbosity 0 always returns None for speech."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(verbosity=0)
        tracker.take_snapshot(["a"])
        result = tracker.take_snapshot(["a", "b", "c"])
        assert result is None


class TestStreamingDeltaNormalVerbosity:
    """Normal verbosity (1): count only."""

    def test_normal_count_only(self):
        """Verbosity 1 reports count but not content."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(verbosity=1)
        tracker.take_snapshot([])
        result = tracker.take_snapshot(["hello world", "foo bar", "baz"])
        assert result == "3 new lines"
        assert "hello" not in result
        assert "foo" not in result


class TestStreamingDeltaVerbose:
    """Verbose mode (verbosity 2): count + last line content."""

    def test_verbose_includes_last_line(self):
        """Verbosity 2 reports count and the last new line content."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(verbosity=2)
        tracker.take_snapshot([])
        result = tracker.take_snapshot(["alpha", "beta", "gamma"])
        assert "3 new lines" in result
        assert "gamma" in result

    def test_verbose_single_line_includes_content(self):
        """Verbosity 2 with single new line includes its content."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(verbosity=2)
        tracker.take_snapshot(["a"])
        result = tracker.take_snapshot(["a", "the final line"])
        assert "1 line added" in result
        assert "the final line" in result


class TestStreamingDeltaBraille:
    """Braille delta format: short strings for braille display."""

    def test_braille_new_lines(self):
        """New lines produce '+N' braille format."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot([])
        tracker.take_snapshot(["a", "b", "c"])
        assert tracker.get_braille_delta() == "+3"

    def test_braille_changed_line(self):
        """Changed line produces '~LN' braille format."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c"])
        tracker.take_snapshot(["a", "X", "c"])
        assert tracker.get_braille_delta() == "~L2"

    def test_braille_removed_lines(self):
        """Removed lines produce '-N' braille format."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c", "d"])
        tracker.take_snapshot(["a", "b"])
        assert tracker.get_braille_delta() == "-2"

    def test_braille_single_removed(self):
        """Single removed line produces '-1' braille format."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c"])
        tracker.take_snapshot(["a", "b"])
        assert tracker.get_braille_delta() == "-1"

    def test_braille_no_change(self):
        """No change produces empty braille delta."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b"])
        tracker.take_snapshot(["a", "b"])
        assert tracker.get_braille_delta() is None


class TestStreamingDeltaLarge:
    """Large deltas: bulk count, not individual descriptions."""

    def test_large_delta_count(self):
        """47 new lines produces '47 new lines'."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot([])
        lines = [f"line {i}" for i in range(47)]
        result = tracker.take_snapshot(lines)
        assert result == "47 new lines"


class TestStreamingDeltaNoChange:
    """When buffer has not changed."""

    def test_no_change_returns_none(self):
        """Identical snapshots return None."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c"])
        result = tracker.take_snapshot(["a", "b", "c"])
        assert result is None


class TestStreamingDeltaSnapshotIsolation:
    """Each snapshot is independent: changes are relative to the last snapshot."""

    def test_snapshot_isolation(self):
        """Delta is computed from the most recent snapshot, not the first."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(debounce_ms=0)
        tracker.take_snapshot(["a"])
        tracker.take_snapshot(["a", "b"])
        # Now the "last" snapshot is ["a", "b"]
        result = tracker.take_snapshot(["a", "b", "c"])
        assert result == "1 line added after line 2"

    def test_snapshot_stores_copy(self):
        """Mutating the input list after snapshot does not affect stored data."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        lines = ["a", "b"]
        tracker.take_snapshot(lines)
        lines.append("c")  # Mutate original
        # Snapshot should still be ["a", "b"]
        result = tracker.take_snapshot(["a", "b"])
        assert result is None  # No change relative to stored snapshot


class TestStreamingDeltaChangedAndRemoved:
    """When lines are both changed and removed simultaneously."""

    def test_changed_and_removed_reports_both(self):
        """Changing 1 line and removing 2 should report both changes and removals."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c", "d"])
        result = tracker.take_snapshot(["x", "b"])
        # Must mention both the change AND the removal
        assert "changed" in result
        assert "removed" in result

    def test_all_remaining_changed_and_lines_removed(self):
        """All surviving lines changed plus lines removed: reports both."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c", "d", "e"])
        result = tracker.take_snapshot(["x", "y", "z"])
        assert "changed" in result
        assert "removed" in result

    def test_changed_and_removed_delta_kind(self):
        """Delta object should capture both changed and removed counts."""
        from lib.streaming_delta import StreamingDeltaTracker

        delta = StreamingDeltaTracker._compute_delta(
            ["a", "b", "c", "d"], ["x", "b"]
        )
        assert delta is not None
        assert delta.changed_count >= 1
        assert delta.count >= 2  # 2 lines removed


class TestStreamingDeltaVerboseAnsi:
    """Verbose mode must not leak raw ANSI codes into speech output."""

    def test_verbose_new_lines_strips_ansi(self):
        """Verbose mode content for new lines must not contain ANSI."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(verbosity=2)
        tracker.take_snapshot([])
        result = tracker.take_snapshot(["\x1b[31merror: fail\x1b[0m"])
        assert "\x1b" not in result, (
            f"Verbose speech contains raw ANSI: {repr(result)}"
        )
        assert "error: fail" in result

    def test_verbose_appended_strips_ansi(self):
        """Verbose mode content for appended lines must not contain ANSI."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker(verbosity=2)
        tracker.take_snapshot(["line1"])
        result = tracker.take_snapshot(["line1", "\x1b[32mok\x1b[0m"])
        assert "\x1b" not in result, (
            f"Verbose speech contains raw ANSI: {repr(result)}"
        )
        assert "ok" in result


class TestErrorDetectorAnsi:
    """ErrorLineDetector must detect errors even with ANSI codes present."""

    def test_classify_fatal_with_ansi_prefix(self):
        """FATAL keyword preceded by ANSI color code must still be detected."""
        from lib.text_processing import ErrorLineDetector

        result = ErrorLineDetector.classify("\x1b[1;31mFATAL: crash\x1b[0m")
        assert result == "error", (
            f"Expected 'error' but got {result!r} -- ANSI prefix blocked detection"
        )

    def test_classify_traceback_with_ansi(self):
        """Python traceback header with ANSI must still be detected."""
        from lib.text_processing import ErrorLineDetector

        result = ErrorLineDetector.classify(
            "\x1b[31mTraceback (most recent call last):\x1b[0m"
        )
        assert result == "error", (
            f"Expected 'error' but got {result!r}"
        )


class TestStreamingDeltaAddedAfterLine:
    """Delta format for lines added after a specific position."""

    def test_lines_added_after_position(self):
        """2 lines added after existing content: '2 lines added after line 3'."""
        from lib.streaming_delta import StreamingDeltaTracker

        tracker = StreamingDeltaTracker()
        tracker.take_snapshot(["a", "b", "c"])
        result = tracker.take_snapshot(["a", "b", "c", "d", "e"])
        assert result == "2 lines added after line 3"
