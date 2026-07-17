"""HTML rendering for the buffer window, starting at the security boundary.

Terminal output is attacker-influenced: any program can print anything.
The browse window passes an identity sanitizeHtmlFunc to
ui.browseableMessage so that nh3.clean does not run on NVDA's main thread
over a multi-megabyte document, which makes escape_line the SOLE boundary
between printed bytes and rendered markup. Everything rendered into the
window MUST pass through it.

ANSIParser.stripANSI is imported directly rather than through the
_runtime.strip_ansi indirection: that indirection defaults to an identity
function until the plugin registers the real one, and a security boundary
must not silently no-op.
"""
import html
import re

from lib.text_processing import ANSIParser

# Control characters that survive ANSI stripping and have no place in
# rendered text: C0 controls except tab (legitimate indentation), plus
# DEL, plus the Unicode bidi overrides (U+202A-U+202E, U+2066-U+2069)
# used for Trojan-Source-style visual spoofing. Built from codepoints so
# no invisible character appears literally in this file: literal
# invisibles in the function that strips them is exactly the confusion
# this exists to prevent.
_DISALLOWED_RANGES = (
	(0x00, 0x08),  # C0 controls before tab
	(0x0A, 0x1F),  # C0 controls after tab (tab 0x09 is legitimate content)
	(0x7F, 0x7F),  # DEL
	(0x202A, 0x202E),  # bidi embedding/override controls
	(0x2066, 0x2069),  # bidi isolate controls
)
_DISALLOWED_CHARS = re.compile(
	"[" + "".join(
		re.escape(chr(lo)) + "-" + re.escape(chr(hi)) if lo != hi else re.escape(chr(lo))
		for lo, hi in _DISALLOWED_RANGES
	) + "]"
)


def escape_line(text):
	"""Return *text* safe to embed in the buffer window's HTML.

	Strips ANSI sequences, removes control and bidi-override characters,
	and HTML-escapes the rest. Non-string input (a failed read, a Mock in
	tests) returns the empty string rather than rendering repr() output.
	"""
	if not isinstance(text, str):
		return ""
	text = ANSIParser.stripANSI(text)
	text = _DISALLOWED_CHARS.sub("", text)
	return html.escape(text, quote=True)


def render_plain(snapshot):
	"""Render a snapshot as one escaped paragraph per line, no structure.

	The Task 3 minimal renderer: enough for the real-NVDA gate (arrowing,
	Escape, title, large-buffer timing) before semantic headings exist.
	A blank buffer row renders as a non-breaking space so it still
	occupies a line when arrowing; an empty paragraph would be skipped.
	"""
	return "\n".join(_paragraph(line) for line in snapshot.lines)


# Span categories that head a section. Prompts are chapter boundaries
# (each command the user ran); errors, warnings, and stack traces are the
# places worth jumping to. Everything else renders plain: a heading per
# output span would make the H key useless.
_H2_CATEGORIES = frozenset({"prompt"})
_H3_CATEGORIES = frozenset({"error", "warning", "stack_trace"})


def _inline_html(text):
	"""Escape a line while turning safe URLs into real links.

	Splits on URL matches so the surrounding text and the URL text are
	escaped exactly as escape_line would, then wraps a URL in an anchor
	ONLY when the shared scheme check (the same one the URL list uses)
	accepts it: file://, javascript:, data:, and unknown schemes render
	as inert text. The href is attribute-escaped separately from the
	link text.
	"""
	if not isinstance(text, str):
		return ""
	from lib.search import _URL_PATTERN, UrlExtractorManager
	text = ANSIParser.stripANSI(text)
	text = _DISALLOWED_CHARS.sub("", text)
	parts = []
	last = 0
	for match in _URL_PATTERN.finditer(text):
		parts.append(html.escape(text[last:match.start()], quote=True))
		url = match.group(0)
		safe = None
		try:
			safe = UrlExtractorManager._prepare_safe_url(url)
		except Exception:
			safe = None
		if safe:
			parts.append('<a href="%s">%s</a>' % (
				html.escape(safe, quote=True),
				html.escape(url, quote=True),
			))
		else:
			parts.append(html.escape(url, quote=True))
		last = match.end()
	parts.append(html.escape(text[last:], quote=True))
	return "".join(parts)


def _paragraph(line):
	return "<p>%s</p>" % (_inline_html(line) or "&nbsp;")


# Spans longer than this skip table detection: a real table never
# approaches it (table_reader bounds regions at MAX_LINES anyway), and
# scanning a huge log dump line by line for column alignment is wasted
# worker time.
_MAX_TABLE_SCAN_SPAN = 2000


def _table_html(navigator):
	"""Render a detected table region as a real HTML table.

	Row 0 is the header row (TableNavigator's contract), so it becomes
	<th> cells and NVDA's native table navigation announces headers.
	"""
	rows = []
	header = "".join(
		"<th>%s</th>" % (escape_line(navigator.header(col)) or "&nbsp;")
		for col in range(navigator.n_cols)
	)
	rows.append("<tr>%s</tr>" % header)
	for row in range(1, navigator.n_rows):
		cells = "".join(
			"<td>%s</td>" % (escape_line(navigator.cell(row, col)) or "&nbsp;")
			for col in range(navigator.n_cols)
		)
		rows.append("<tr>%s</tr>" % cells)
	return "<table>%s</table>" % "".join(rows)


# Categories that render as plain paragraphs and may participate in a
# table. Merged into one block before scanning because the tokenizer
# splits a table from its header row: an all-caps header line like
# "CONTAINER ID   IMAGE" classifies as "heading" while the rows below
# are "output".
_TABLE_CANDIDATE_CATEGORIES = frozenset({"output", "heading", "timestamp", "progress"})


def _render_block(snapshot, first_idx, last_idx):
	"""Render a plain block, upgrading detected columnar runs to tables.

	Detection reuses TableDetector, the same heuristic behind live table
	mode, and it is experimental there too: anything it is not confident
	about stays plain paragraphs, because a wrong table is worse than no
	table.
	"""
	lines = snapshot.lines[first_idx:last_idx + 1]
	count = len(lines)
	if count < 2 or count > _MAX_TABLE_SCAN_SPAN:
		return [_paragraph(line) for line in lines]
	from lib.table_reader import TableDetector, TableNavigator
	detector = TableDetector()
	parts = []
	pos = 0
	while pos < count:
		region = None
		try:
			region = detector.detect(lines, pos)
		except Exception:
			region = None
		if region is not None and region.first_line >= pos:
			parts.append(_table_html(TableNavigator(region, lines)))
			pos = region.last_line + 1
		else:
			parts.append(_paragraph(lines[pos]))
			pos += 1
	return parts


def render(snapshot, spans):
	"""Render a snapshot with semantic headings from tokenizer spans.

	H1 is the terminal, H2 each prompt line (a command the user ran),
	H3 the first line of each error/warning/stack-trace span; the rest
	of such a span stays plain so a 30-line traceback is one heading
	stop, not thirty. Headings carry id="L{n}" with the ABSOLUTE line
	number, for the jump dialog and for opening at the review cursor.

	*spans* are SectionSpan tuples over snapshot.lines (relative
	indexes); ids translate through snapshot.first_line_num.

	Adjacent H3-category spans coalesce into ONE heading stop: the
	tokenizer classifies "Traceback:" as error and the "File ..." lines
	under it as stack_trace, but to a reader they are a single event and
	must not cost two presses of H.

	When any headings exist, a table of contents linking each one sits at
	the top: browseableMessage renders from the top with no scroll
	parameter, so the TOC is how structure is reachable without arrowing
	through thousands of lines.
	"""
	body = []
	toc_entries = []
	in_h3_run = False
	span_index = 0
	while span_index < len(spans):
		span = spans[span_index]
		if span.category in _TABLE_CANDIDATE_CATEGORIES:
			# Merge the run of adjacent plain spans and scan it for tables.
			run_end = span_index
			while (run_end + 1 < len(spans)
					and spans[run_end + 1].category in _TABLE_CANDIDATE_CATEGORIES):
				run_end += 1
			body.extend(_render_block(
				snapshot, span.start_line, spans[run_end].end_line))
			in_h3_run = False
			span_index = run_end + 1
			continue
		is_h3_span = span.category in _H3_CATEGORIES
		for idx in range(span.start_line, span.end_line + 1):
			line = snapshot.lines[idx]
			absolute = snapshot.first_line_num + idx
			if span.category in _H2_CATEGORIES:
				text = escape_line(line) or "&nbsp;"
				body.append('<h2 id="L%d">%s</h2>' % (absolute, text))
				toc_entries.append((absolute, text))
			elif is_h3_span and idx == span.start_line and not in_h3_run:
				text = escape_line(line) or "&nbsp;"
				body.append('<h3 id="L%d">%s</h3>' % (absolute, text))
				toc_entries.append((absolute, text))
			else:
				body.append(_paragraph(line))
		in_h3_run = is_h3_span
		span_index += 1
	parts = ["<h1>%s</h1>" % escape_line(snapshot.terminal_name)]
	if toc_entries:
		# Translators: Label above the table of contents in the buffer window
		parts.append("<p>%s</p>" % escape_line(_("Contents:")))
		parts.append("<ul>%s</ul>" % "".join(
			'<li><a href="#L%d">%s</a></li>' % (absolute, text)
			for absolute, text in toc_entries
		))
	parts.extend(body)
	return "\n".join(parts)


def window_title(snapshot):
	"""Title for the browse window: names the terminal, admits truncation.

	A stale snapshot silently presented as live is the worst failure
	mode, so the title always says "snapshot"; and when lines were
	dropped it says how many of how many remain rather than pretending
	the buffer is smaller than it is. The terminal name is
	program-influenced text, so it passes through escape_line like any
	other line.
	"""
	name = escape_line(snapshot.terminal_name)
	if snapshot.truncated:
		# Translators: Title of the terminal buffer window when older lines
		# were dropped. {terminal} is the terminal application's name;
		# {kept} and {total} are line counts.
		return _("{terminal} buffer snapshot, most recent {kept} of {total} lines - Terminal Access").format(
			terminal=name, kept=len(snapshot.lines), total=snapshot.total_lines,
		)
	# Translators: Title of the terminal buffer window. {terminal} is the
	# terminal application's name; {count} is the number of lines shown.
	return _("{terminal} buffer snapshot, {count} lines - Terminal Access").format(
		terminal=name, count=snapshot.total_lines,
	)
