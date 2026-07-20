"""Read the whole screen buffer of a legacy Windows console.

NVDA exposes only the visible window for these consoles:
``WinConsole._getText`` returns ``winConsoleHandler.getConsoleVisibleLines()``,
which reads ``srWindow.Top`` through ``srWindow.Bottom`` (the viewport
rectangle). Anything scrolled off is invisible to NVDA, so search, the
buffer window, and transcript export inherit that limit. That is the
"find is limited on older terminals" report.

The console still holds the text. ``GetConsoleScreenBufferInfo`` reports
``dwSize``, the full buffer, and ``ReadConsoleOutputCharacter`` can start
at row 0 instead of the viewport top. Reading it ourselves is what lifts
the limitation.

This reuses the console handle NVDA has already attached
(``winConsoleHandler.consoleOutputHandle``); it does not attach, detach,
or otherwise manage the console, so it cannot disturb NVDA's own console
support. Pure ctypes through NVDA's existing ``wincon`` wrappers: no
native binary, no helper process, nothing that reopens the problems the
Rust layer caused.
"""

# One read is one allocation, so cap it. A 200-column console with a
# 50,000-line scrollback is 10 million cells, far past any real setting
# (Windows caps console screen buffer height at 9,999 by default).
MAX_CELLS = 10_000_000


def read_full_buffer_lines():
	"""Return every line in the attached console's buffer, or None.

	None means "not available, use the normal path": no console is
	attached, the API failed, or the buffer reported a nonsensical size.
	Callers must treat None as a fallback signal, never as an empty
	buffer.

	Trailing blank rows are dropped. A console screen buffer is
	preallocated to its full height and unused rows are spaces, so
	keeping them would append thousands of empty lines to every read.
	"""
	try:
		import wincon
		import winConsoleHandler
	except ImportError:
		return None

	handle = getattr(winConsoleHandler, "consoleOutputHandle", None)
	if not handle:
		return None

	try:
		info = wincon.GetConsoleScreenBufferInfo(handle)
		width = int(info.dwSize.x)
		height = int(info.dwSize.y)
		if width <= 0 or height <= 0:
			return None
		# Read from row 0, not srWindow.Top: that single difference is
		# what turns "the visible screen" into "the whole scrollback".
		if width * height > MAX_CELLS:
			height = MAX_CELLS // width
		text = wincon.ReadConsoleOutputCharacter(handle, width * height, 0, 0)
	except Exception:
		return None

	if not isinstance(text, str):
		return None

	lines = [text[i:i + width].rstrip() for i in range(0, len(text), width)]
	while lines and not lines[-1]:
		lines.pop()
	return lines


def is_attached_console(terminal):
	"""True when *terminal* is the legacy console NVDA is attached to.

	Guards the full-buffer read so it is only used for the object it
	actually describes; every other terminal keeps the normal path.
	"""
	if terminal is None:
		return False
	try:
		import winConsoleHandler
	except ImportError:
		return False
	console_obj = getattr(winConsoleHandler, "consoleObject", None)
	if console_obj is None:
		return False
	return console_obj is terminal
