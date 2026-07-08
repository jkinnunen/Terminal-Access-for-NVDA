# Streaming delta tracker for terminal buffer changes.
# Compares buffer snapshots and produces human-readable delta descriptions
# with debounce support and verbosity-aware output.

import re
import time
from collections import namedtuple

# Lightweight ANSI strip for speech output (avoids importing text_processing)
_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')

# Typed delta result. Fields default to sensible zero values.
# kind: "new", "added_after", "changed", "mixed", "removed"
_DeltaBase = namedtuple("Delta", [
    "kind", "count", "after_line", "lines", "added", "changed_count",
    "new_content",
])


class Delta(_DeltaBase):
    """Structured delta between two buffer snapshots."""
    __slots__ = ()

    def __new__(cls, kind, count=0, after_line=0, lines=(), added=0,
                changed_count=0, new_content=()):
        return super().__new__(
            cls, kind, count, after_line, tuple(lines), added,
            changed_count, tuple(new_content),
        )


class StreamingDeltaTracker:
    """Track changes between terminal buffer snapshots.

    Stores the last buffer snapshot and computes a delta description
    when a new snapshot is provided. Supports debouncing to coalesce
    rapid changes, and verbosity levels to control output detail.

    Verbosity levels:
        0 (quiet): no delta speech, returns None
        1 (normal): announce delta count only ("3 new lines")
        2 (verbose): announce delta count + last new line content

    Args:
        debounce_ms: minimum interval between reported deltas, in
            milliseconds. Changes within this interval return None.
            Default is 500.
        verbosity: verbosity level (0, 1, or 2). Default is 1.
    """

    def __init__(self, debounce_ms=500, verbosity=1):
        self._last_snapshot = None
        self._debounce_ms = debounce_ms
        self._verbosity = verbosity
        self._last_report_time = 0
        self._last_delta = None

    @property
    def has_previous(self):
        """True if at least one snapshot has been taken."""
        return self._last_snapshot is not None

    def set_verbosity(self, level):
        """Update the verbosity level (0=quiet, 1=normal, 2=verbose)."""
        self._verbosity = level

    def take_snapshot(self, current_lines):
        """Store a new snapshot and return a delta description.

        Args:
            current_lines: list of strings representing the current
                buffer content.

        Returns:
            A human-readable delta string, or None if there is no
            previous snapshot, no change, the debounce interval has
            not elapsed, or verbosity is quiet (0).
        """
        snapshot = list(current_lines)

        if self._last_snapshot is None:
            self._last_snapshot = snapshot
            return None

        previous = self._last_snapshot
        self._last_snapshot = snapshot

        # Check debounce
        now = time.monotonic()
        elapsed_ms = (now - self._last_report_time) * 1000
        if self._last_report_time > 0 and elapsed_ms < self._debounce_ms:
            return None

        delta = self._compute_delta(previous, snapshot)
        if delta is None:
            return None

        self._last_report_time = now
        self._last_delta = delta

        if self._verbosity == 0:
            return None

        return self._format_speech(delta)

    def get_braille_delta(self):
        """Return a short braille-format string for the last delta.

        Returns:
            "+N" for N new lines, "~LN" for line N changed, or
            None if there was no change.
        """
        d = self._last_delta
        if d is None:
            return None

        if d.kind == "new":
            return f"+{d.count}"
        if d.kind == "changed":
            if d.count == 1:
                return f"~L{d.lines[0]}"
            return f"~{d.count}"
        if d.kind == "added_after":
            return f"+{d.count}"
        if d.kind == "mixed":
            if d.added > 0:
                return f"+{d.added}"
            return f"~{d.changed_count}"
        if d.kind == "removed":
            return f"-{d.count}"

        return None

    @staticmethod
    def _compute_delta(old_lines, new_lines):
        """Compare two snapshots and return a Delta, or None if identical."""
        old_len = len(old_lines)
        new_len = len(new_lines)

        if old_len == new_len and old_lines == new_lines:
            return None

        # Empty to content
        if old_len == 0 and new_len > 0:
            return Delta("new", count=new_len, new_content=new_lines)

        # Pure append
        if new_len > old_len and new_lines[:old_len] == old_lines:
            added_count = new_len - old_len
            return Delta("added_after", count=added_count,
                         after_line=old_len, new_content=new_lines[old_len:])

        # Find changed lines
        changed_indices = []
        min_len = min(old_len, new_len)
        for i in range(min_len):
            if old_lines[i] != new_lines[i]:
                changed_indices.append(i)

        added_count = max(0, new_len - old_len)
        removed_count = max(0, old_len - new_len)

        if changed_indices and removed_count > 0:
            return Delta("mixed", changed_count=len(changed_indices),
                         count=removed_count)

        if added_count == 0 and changed_indices:
            return Delta("changed", count=len(changed_indices),
                         lines=[i + 1 for i in changed_indices])

        if added_count > 0 and changed_indices:
            return Delta("mixed", changed_count=len(changed_indices),
                         added=added_count,
                         new_content=new_lines[old_len:] if new_len > old_len else [])

        if added_count > 0:
            return Delta("added_after", count=added_count,
                         after_line=old_len, new_content=new_lines[old_len:])

        # Lines removed (no changes)
        if removed_count > 0:
            return Delta("removed", count=removed_count)

        return None

    @staticmethod
    def _clean(text):
        """Strip ANSI escape codes from text for speech output."""
        return _ANSI_RE.sub('', text)

    def _format_speech(self, d):
        """Format a Delta into a speech string."""
        if d.kind == "new":
            base = self._count_label(d.count, "new line")
            if self._verbosity >= 2 and d.new_content:
                return f"{base}: {self._clean(d.new_content[-1])}"
            return base

        if d.kind == "added_after":
            if d.count == 1:
                base = f"1 line added after line {d.after_line}"
            else:
                base = f"{d.count} lines added after line {d.after_line}"
            if self._verbosity >= 2 and d.new_content:
                return f"{base}: {self._clean(d.new_content[-1])}"
            return base

        if d.kind == "changed":
            if d.count == 1:
                return f"line {d.lines[0]} changed"
            return f"{d.count} lines changed"

        if d.kind == "mixed":
            parts = []
            if d.changed_count > 0:
                parts.append(f"{d.changed_count} changed")
            if d.added > 0:
                parts.append(self._count_label(d.added, "new line"))
            if d.count > 0 and d.added == 0:
                parts.append(self._count_label(d.count, "line") + " removed")
            return ", ".join(parts)

        if d.kind == "removed":
            if d.count == 1:
                return "1 line removed"
            return f"{d.count} lines removed"

        return None

    @staticmethod
    def _count_label(count, noun):
        """Return 'N noun' or 'N nouns' with proper pluralization."""
        if count == 1:
            return f"1 {noun}"
        return f"{count} {noun}s"
