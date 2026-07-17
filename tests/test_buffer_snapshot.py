"""BufferSnapshot: the frozen capture behind the buffer window.

The snapshot separates "what we captured" from "how we render it", so
rendering and jumping are testable without a terminal. Line numbers are
ABSOLUTE buffer positions: when the capture is truncated to the most
recent N lines, first_line_num records where the kept slice starts, so a
line keeps the same number whether or not older lines were dropped. Jump
resolution depends on that stability.
"""
from unittest.mock import Mock

import pytest

from lib.buffer_snapshot import MAX_SNAPSHOT_LINES, SNAPSHOT_LINES_CEILING, BufferSnapshot


def _terminal(app_name="WindowsTerminal"):
    term = Mock()
    term.appModule.appName = app_name
    return term


class TestCapture:
    """capture() under, at, and over the line cap."""

    def test_under_the_cap_keeps_everything(self):
        lines = [f"line {i}" for i in range(10)]
        snap = BufferSnapshot.capture(_terminal(), lines)

        assert snap.lines == lines
        assert snap.total_lines == 10
        assert snap.truncated is False
        assert snap.first_line_num == 0

    def test_over_the_cap_keeps_the_most_recent_lines(self):
        lines = [f"line {i}" for i in range(30)]
        snap = BufferSnapshot.capture(_terminal(), lines, max_lines=20)

        assert snap.lines == lines[10:]
        assert snap.truncated is True
        # Absolute numbering: the kept slice starts at line 10.
        assert snap.first_line_num == 10
        # total_lines reports the full buffer, not the kept slice, so the
        # window title can say "showing the most recent 20 of 30 lines".
        assert snap.total_lines == 30

    def test_exactly_at_the_cap_is_not_truncated(self):
        lines = [f"line {i}" for i in range(20)]
        snap = BufferSnapshot.capture(_terminal(), lines, max_lines=20)

        assert snap.truncated is False
        assert snap.first_line_num == 0

    def test_empty_buffer(self):
        snap = BufferSnapshot.capture(_terminal(), [])

        assert snap.lines == []
        assert snap.total_lines == 0
        assert snap.truncated is False
        assert snap.first_line_num == 0

    def test_single_line_buffer(self):
        snap = BufferSnapshot.capture(_terminal(), ["only line"])

        assert snap.lines == ["only line"]
        assert snap.total_lines == 1

    def test_default_cap_is_the_module_cap(self):
        lines = [""] * (MAX_SNAPSHOT_LINES + 5)
        snap = BufferSnapshot.capture(_terminal(), lines)

        assert len(snap.lines) == MAX_SNAPSHOT_LINES
        assert snap.truncated is True


class TestTerminalName:
    """The snapshot records which terminal it came from, for the title."""

    def test_name_from_app_module(self):
        snap = BufferSnapshot.capture(_terminal("wt"), ["x"])
        assert snap.terminal_name == "wt"

    def test_fallback_when_app_module_is_missing(self):
        term = Mock(spec=[])  # no appModule at all
        snap = BufferSnapshot.capture(term, ["x"])
        assert snap.terminal_name == "terminal"


class TestLineAt:
    """line_at() takes ABSOLUTE line numbers, truncated or not."""

    def test_absolute_index_without_truncation(self):
        snap = BufferSnapshot.capture(_terminal(), ["a", "b", "c"])
        assert snap.line_at(1) == "b"

    def test_absolute_index_survives_truncation(self):
        lines = [f"line {i}" for i in range(30)]
        snap = BufferSnapshot.capture(_terminal(), lines, max_lines=20)

        # Line 15 is still line 15, even though lines 0-9 were dropped.
        assert snap.line_at(15) == "line 15"

    def test_index_before_the_kept_slice_returns_none(self):
        lines = [f"line {i}" for i in range(30)]
        snap = BufferSnapshot.capture(_terminal(), lines, max_lines=20)

        assert snap.line_at(5) is None

    def test_index_past_the_end_returns_none(self):
        snap = BufferSnapshot.capture(_terminal(), ["a", "b"])
        assert snap.line_at(2) is None

    def test_negative_index_returns_none(self):
        snap = BufferSnapshot.capture(_terminal(), ["a", "b"])
        assert snap.line_at(-1) is None


class TestCaps:
    """The cap is a measured default; the ceiling is a documented bound."""

    def test_default_is_at_or_below_the_ceiling(self):
        # MAX_SNAPSHOT_LINES starts LOW and may only be raised toward the
        # ceiling once the Task 3 real-NVDA gate measures what stays
        # responsive. The ceiling matches search.MAX_SEARCH_LINES.
        assert MAX_SNAPSHOT_LINES <= SNAPSHOT_LINES_CEILING

    def test_ceiling_matches_search_bound(self):
        from lib.search import OutputSearchManager
        assert SNAPSHOT_LINES_CEILING == OutputSearchManager.MAX_SEARCH_LINES
