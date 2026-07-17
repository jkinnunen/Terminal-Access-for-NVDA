# Shared terminal line resolution by text content.
#
# Terminals report their buffer such that splitting the full text on newlines
# does not always agree with UNIT_LINE navigation (wrapped rows, blank padding
# rows). Jumping to "line N" by counting can therefore land on the wrong row.
# Resolving a stored line by its text instead walks the live buffer one
# UNIT_LINE at a time and lands on the line that actually contains the text,
# which is reliable regardless of how the line was originally counted.
#
# Used by search-result jumps and bookmark jumps (the latter only when the
# terminal cannot produce a position bookmark, e.g. legacy consoles).

import textInfos

import lib._runtime as _rt

# Hard cap on the walk so a pathological buffer cannot make a jump unbounded.
MAX_WALK_LINES = 50000


def resolve_line_by_content(terminal, line_text, line_hint=None,
							max_lines=MAX_WALK_LINES):
	"""Return a TextInfo expanded to the buffer line matching *line_text*.

	Walks *terminal* by UNIT_LINE from the top and returns the first line
	whose ANSI-stripped text equals or contains *line_text* (or vice versa).
	When several lines match, the occurrence nearest *line_hint* (a 1-based
	line number) wins. Returns None if nothing matches or the terminal cannot
	be read.
	"""
	target = _rt.strip_ansi(line_text or "").strip()
	if not target or terminal is None:
		return None
	try:
		info = terminal.makeTextInfo(textInfos.POSITION_FIRST)
		info.expand(textInfos.UNIT_LINE)
	except (RuntimeError, AttributeError, TypeError, NotImplementedError,
			ValueError):
		return None

	best = None
	best_delta = None
	index = 0
	while index < max_lines:
		raw = getattr(info, "text", "")
		# A real terminal line is a string; anything else is unreadable.
		cur = _rt.strip_ansi(raw).strip() if isinstance(raw, str) else ""
		if cur and (cur == target or target in cur or cur in target):
			delta = abs((index + 1) - (line_hint or (index + 1)))
			if best is None or delta < best_delta:
				try:
					best = info.copy()
				except (RuntimeError, AttributeError):
					best = info
				best_delta = delta
				if delta == 0:
					break
		try:
			nxt = info.copy()
			moved = nxt.move(textInfos.UNIT_LINE, 1)
		except (RuntimeError, AttributeError, TypeError):
			break
		# move() returns the integer count of units moved; 0 (or a
		# non-integer from a malformed TextInfo) means we cannot advance.
		if not isinstance(moved, int) or moved == 0:
			break
		try:
			nxt.expand(textInfos.UNIT_LINE)
		except (RuntimeError, AttributeError, TypeError):
			break
		info = nxt
		index += 1
	return best
