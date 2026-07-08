# Progress milestone tracking for terminal output.
#
# Streaming suppression silences per-character speech during rapid output,
# which leaves users with no progress feedback during long operations
# (builds, downloads, AI responses). This module extracts percentage values
# from terminal lines and reports only when a milestone threshold is
# crossed, so a 0-100% download produces four announcements, not hundreds.

import re

from lib.text_processing import ANSIParser


class ProgressMilestoneTracker:
	"""Track progress percentages and report milestone crossings.

	Feed each new terminal line to update(). It returns a milestone
	integer the first time the reported percentage reaches that
	threshold, and None otherwise. Jumping across several thresholds in
	one update reports only the highest one crossed.

	A percentage drop of more than 10 points is treated as a new
	operation and resets the announced state automatically.
	"""

	# Matches "45%", "45.2%", "45 %", and an optional leading minus so
	# negative values can be recognized and ignored.
	_PERCENT_PATTERN = re.compile(r'(-?\d+(?:\.\d+)?)\s*%')

	# A drop larger than this many points means a new progress bar started.
	_RESET_DROP_THRESHOLD = 10

	def __init__(self, milestones=(25, 50, 75, 100)):
		self._milestones = tuple(sorted(milestones))
		self._lastAnnounced: int | None = None
		self._lastPercent: float | None = None

	def update(self, line: str) -> int | None:
		"""Extract a percentage from line and return a newly crossed milestone.

		Args:
			line: A single line of terminal output. ANSI codes are
				stripped before matching. Non-string input is ignored.

		Returns:
			The highest milestone crossed since the last announcement,
			or None if no valid percentage was found or no new milestone
			was reached.
		"""
		if not isinstance(line, str):
			return None
		matches = self._PERCENT_PATTERN.findall(ANSIParser.stripANSI(line))
		if not matches:
			return None
		percent = float(matches[-1])
		if not 0 <= percent <= 100:
			return None
		if (
			self._lastPercent is not None
			and self._lastPercent - percent > self._RESET_DROP_THRESHOLD
		):
			self.reset()
		self._lastPercent = percent
		crossed = [
			m for m in self._milestones
			if percent >= m and (self._lastAnnounced is None or m > self._lastAnnounced)
		]
		if not crossed:
			return None
		self._lastAnnounced = crossed[-1]
		return self._lastAnnounced

	def reset(self) -> None:
		"""Clear tracked state so milestones announce again (new operation)."""
		self._lastAnnounced = None
		self._lastPercent = None
