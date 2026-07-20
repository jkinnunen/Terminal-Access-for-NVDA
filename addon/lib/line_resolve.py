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


def absolute_offset(lines, line_num, char_offset=0):
	"""Codepoint offset of *char_offset* on *line_num* within the buffer.

	The buffer is the lines joined by newlines, so a line's start is the
	sum of the preceding lines plus one newline each. Returns None when
	*line_num* is out of range.
	"""
	if line_num < 0 or line_num >= len(lines):
		return None
	return sum(len(line) + 1 for line in lines[:line_num]) + char_offset


def resolve_by_codepoint_offset(terminal, offset, expected_text=None):
	"""Return a TextInfo expanded to the line at *offset*, or None.

	One call instead of walking the buffer line by line, and unambiguous
	when the same text appears more than once, which is what makes it
	better than resolving by content.

	It is verified rather than trusted: our matching runs over
	ANSI-stripped lines while the story text may still contain escape
	codes, which shifts every offset after the first code. When
	*expected_text* is given and the landed line does not contain it,
	this returns None so the caller falls back to the content walk. A
	wrong landing is worse than a slow one.
	"""
	if terminal is None or offset is None or offset < 0:
		return None
	try:
		info = terminal.makeTextInfo(textInfos.POSITION_FIRST)
		landed = info.moveToCodepointOffset(offset)
		landed.expand(textInfos.UNIT_LINE)
	except (RuntimeError, AttributeError, TypeError, NotImplementedError,
			ValueError, IndexError):
		return None
	if expected_text:
		raw = getattr(landed, "text", "")
		cur = _rt.strip_ansi(raw).strip() if isinstance(raw, str) else ""
		target = _rt.strip_ansi(expected_text).strip()
		if not cur or (cur != target and target not in cur and cur not in target):
			return None
	return landed


def resolve_line_by_content(terminal, line_text, line_hint=None,
							max_lines=MAX_WALK_LINES, offset=None):
	"""Return a TextInfo expanded to the buffer line matching *line_text*.

	When *offset* (an absolute codepoint offset) is given, that is tried
	first: it is one call rather than a walk, and it is unambiguous when
	the same text appears twice. It is verified against *line_text*, and
	anything that does not check out falls through to the walk below.

	The walk is the fallback: it moves *terminal* by UNIT_LINE from the
	top and returns the first line whose ANSI-stripped text equals or
	contains *line_text* (or vice versa). When several lines match, the
	occurrence nearest *line_hint* (a 1-based line number) wins. Returns
	None if nothing matches or the terminal cannot be read.
	"""
	target = _rt.strip_ansi(line_text or "").strip()
	if not target or terminal is None:
		return None

	if offset is not None:
		landed = resolve_by_codepoint_offset(terminal, offset, expected_text=line_text)
		if landed is not None:
			return landed
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
