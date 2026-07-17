"""Frozen capture of a terminal buffer for the buffer window.

Separates "what we captured" from "how we render it": the browse window,
the jump-to-line dialog, and their tests all consume a BufferSnapshot
without touching a live terminal.

Line numbers are ABSOLUTE buffer positions. When a capture keeps only the
most recent max_lines, first_line_num records where the kept slice
starts, so a line keeps the same number whether or not older lines were
dropped. Jump resolution relies on that stability (and, per project rule,
the final landing in the live terminal is resolved by line content, never
by counting).
"""
import time

# Hard ceiling on snapshot size, matching search.MAX_SEARCH_LINES: the two
# features read the same buffer and should agree on "the whole buffer".
SNAPSHOT_LINES_CEILING = 50000

# The shipped cap. Deliberately LOW to start: MSHTML plus NVDA's
# browse-mode buffer build over tens of thousands of nodes is unmeasured.
# Raise toward SNAPSHOT_LINES_CEILING only to the limit the Task 3
# real-NVDA gate measures as responsive (see
# docs/plans/20260717-terminal-buffer-virtual-window.md).
MAX_SNAPSHOT_LINES = 10000


class BufferSnapshot:
	"""An immutable capture of a terminal's buffer at one moment."""

	def __init__(self, lines, terminal_name, captured_at, total_lines, truncated, first_line_num):
		self.lines = lines
		self.terminal_name = terminal_name
		self.captured_at = captured_at
		self.total_lines = total_lines
		self.truncated = truncated
		self.first_line_num = first_line_num

	@classmethod
	def capture(cls, terminal, lines, max_lines=MAX_SNAPSHOT_LINES):
		"""Snapshot *lines* from *terminal*, keeping the most recent max_lines.

		total_lines reports the full buffer size even when truncated, so
		the window title can say "showing the most recent N of M lines"
		instead of silently pretending the buffer is smaller than it is.
		"""
		total = len(lines)
		if total > max_lines:
			kept = list(lines[total - max_lines:])
			first_line_num = total - max_lines
			truncated = True
		else:
			kept = list(lines)
			first_line_num = 0
			truncated = False
		app_module = getattr(terminal, "appModule", None)
		name = getattr(app_module, "appName", None) if app_module else None
		return cls(
			lines=kept,
			terminal_name=name or "terminal",
			captured_at=time.time(),
			total_lines=total,
			truncated=truncated,
			first_line_num=first_line_num,
		)

	def line_at(self, line_num):
		"""Return the text at ABSOLUTE line number *line_num*, or None.

		None means the line is outside the snapshot: before the kept
		slice (truncated away), past the end, or negative.
		"""
		index = line_num - self.first_line_num
		if line_num < self.first_line_num or index >= len(self.lines):
			return None
		return self.lines[index]
