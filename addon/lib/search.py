# Terminal Access search and command history classes.
# Extracted from terminalAccess.py for modularization.

import collections
import re

import api
import textInfos
import ui
import wx

import lib  # noqa: F401 — ensures translation fallback is initialized
import lib._runtime as _rt

_PROMPT_PATTERNS: list[re.Pattern[str]] = [
	# Bash prompts: user@host:~$, root@host:#, simple $/#
	re.compile(r'^[\w\-\.]+@[\w\-\.]+:[^\$#]*[\$#]\s*(.+)$'),
	re.compile(r'^[\$#]\s*(.+)$'),
	# PowerShell prompts: PS>, PS C:\>, PS /home/user>
	re.compile(r'^PS\s+[A-Za-z]:[^>]*>\s*(.+)$'),
	re.compile(r'^PS\s+/[^>]*>\s*(.+)$'),
	re.compile(r'^PS>\s*(.+)$'),
	# Windows CMD prompts: C:\>, D:\Users\name>
	re.compile(r'^[A-Za-z]:[^>]*>\s*(.+)$'),
	# Generic prompt with colon or arrow
	re.compile(r'^[^\s>:]+[>:]\s*(.+)$'),
]

# Compiled URL extraction patterns for UrlExtractorManager.
# OSC 8 hyperlinks embedded by modern terminals: ESC]8;;URL BEL display_text ESC]8;; BEL
_OSC8_URL_PATTERN: re.Pattern[str] = re.compile(
	r'\x1b\]8;'           # OSC 8 start
	r'[^;]*;'             # optional params (id=xxx, etc.)
	r'([^\x07\x1b]+)'     # capture the URL
	r'(?:\x07|\x1b\\)'    # BEL or ST terminator
)

# Plain-text URL pattern applied after ANSI stripping.
_URL_PATTERN: re.Pattern[str] = re.compile(
	r'(?:'
	# Standard http/https/ftp URLs
	r'(?:https?|ftp)://[^\s<>\[\]()\"\'`{}|\\^]+'
	r'|'
	# www. prefixed URLs (common in terminal output)
	r'www\.[^\s<>\[\]()\"\'`{}|\\^]+'
	r'|'
	# file:// protocol
	r'file://[^\s<>\[\]()\"\'`{}|\\^]+'
	r')',
	re.IGNORECASE
)


def _clean_url(url: str) -> str:
	"""Strip trailing punctuation that is likely not part of the URL."""
	_TRAILING_PUNCT = '.,;:!?'

	# Strip trailing punctuation
	while url and url[-1] in _TRAILING_PUNCT:
		url = url[:-1]
	# Strip unbalanced trailing bracket/paren characters
	pairs = {'(': ')', '[': ']', '<': '>'}
	for open_char, close_char in pairs.items():
		while url.endswith(close_char) and url.count(close_char) > url.count(open_char):
			url = url[:-1]
	# Bracket stripping may expose trailing punctuation
	while url and url[-1] in _TRAILING_PUNCT:
		url = url[:-1]
	return url


class OutputSearchManager:
	"""
	Search and filter terminal output with pattern matching.

	Section 8.2: Output Filtering and Search (v1.0.30+)

	This class enables users to search through terminal output using text patterns
	or regular expressions, navigate between matches, and filter output. Useful for:
	- Finding error messages in logs
	- Locating specific command output
	- Filtering build output for warnings
	- Searching through help text
	- Finding specific entries in terminal history

	Features:
	- Text search with case sensitivity option
	- Regular expression support
	- Navigate forward/backward through matches
	- Show match count
	- Jump to first/last match
	- Wrap-around search

	Example usage:
		>>> manager = OutputSearchManager(terminal_obj)
		>>> manager.search("error", case_sensitive=False)
		>>> manager.next_match()  # Jump to next occurrence
		>>> manager.previous_match()  # Jump to previous occurrence
		>>> manager.get_match_count()  # Get total matches
	"""

	def __init__(self, terminal_obj, tab_manager=None):
		"""
		Initialize the OutputSearchManager.

		Args:
			terminal_obj: Terminal TextInfo object for searching
			tab_manager: Optional TabManager for tab-aware search storage
		"""
		self._terminal = terminal_obj
		self._tab_manager = tab_manager
		# Search history (most recent first, max 10 entries)
		self._search_history: list[str] = []
		# Message from the last search (e.g. fuzzy fallback notification)
		self._last_search_message: str = ""
		# Legacy single-tab storage
		self._pattern = None
		self._matches = []  # List of (bookmark, line_text, line_num) tuples
		self._current_match_index = -1
		self._case_sensitive = False
		self._use_regex = False
		# Per-tab storage
		self._tab_searches = {}  # tab_id -> {pattern, matches, index, case_sensitive, use_regex}

	def _get_current_tab_id(self) -> str:
		"""Get current tab ID, or None if no tab manager."""
		if self._tab_manager:
			return self._tab_manager.get_current_tab_id()
		return None

	def _get_search_state(self):
		"""Get the appropriate search state dict for the current context."""
		tab_id = self._get_current_tab_id()
		if tab_id:
			# Multi-tab mode: use per-tab storage
			if tab_id not in self._tab_searches:
				self._tab_searches[tab_id] = {
					'pattern': None,
					'matches': [],
					'current_match_index': -1,
					'case_sensitive': False,
					'use_regex': False
				}
			return self._tab_searches[tab_id]
		else:
			# Legacy mode: use instance variables
			return {
				'pattern': self._pattern,
				'matches': self._matches,
				'current_match_index': self._current_match_index,
				'case_sensitive': self._case_sensitive,
				'use_regex': self._use_regex
			}

	def _save_search_state(self, state):
		"""Save search state to the appropriate storage."""
		tab_id = self._get_current_tab_id()
		if tab_id:
			# Multi-tab mode
			self._tab_searches[tab_id] = state
		else:
			# Legacy mode
			self._pattern = state['pattern']
			self._matches = state['matches']
			self._current_match_index = state['current_match_index']
			self._case_sensitive = state['case_sensitive']
			self._use_regex = state['use_regex']

	# Safety limits for search input validation
	MAX_PATTERN_LENGTH = 500
	MAX_MATCHES = 1000
	MAX_LINE_LENGTH = 10000

	def search(self, pattern: str, case_sensitive: bool = False,
			  use_regex: bool = False, scope: str = "buffer",
			  current_line: int = 0) -> int:
		"""
		Search for pattern in terminal output.

		Args:
			pattern: Search pattern (text or regex)
			case_sensitive: Case sensitive search
			use_regex: Use regular expression
			scope: Search scope, either "buffer" (whole terminal) or
				"section" (current section only, determined by
				SectionTokenizer)
			current_line: Current cursor line (used when scope="section"
				to determine section boundaries)

		Returns:
			int: Number of matches found

		Raises:
			ValueError: If pattern exceeds MAX_PATTERN_LENGTH or is an
				invalid regex.
		"""
		self._last_search_message = ""

		if not self._terminal or not pattern:
			return 0

		# Reject patterns that exceed the safety cap
		if len(pattern) > self.MAX_PATTERN_LENGTH:
			raise ValueError(
				f"Search pattern too long ({len(pattern)} chars, "
				f"max {self.MAX_PATTERN_LENGTH})"
			)

		# Validate regex early so callers get a clear error instead of a
		# silent 0-match result buried inside the broad except below.
		if use_regex:
			try:
				flags = 0 if case_sensitive else re.IGNORECASE
				re.compile(pattern, flags)
			except re.error as exc:
				try:
					import logHandler
					logHandler.log.warning(f"Terminal Access: Invalid regex '{pattern}': {exc}")
				except Exception:
					pass
				raise ValueError(f"Invalid regular expression: {exc}") from exc

		# Use a local list so matches aren't saved until search completes.
		# Matches are stored as lightweight tuples without TextInfo bookmarks.
		# The TextInfo is resolved lazily only when jumping to a match,
		# avoiding the expensive full-buffer walk that froze NVDA.
		matches = []

		max_line = self.MAX_LINE_LENGTH
		max_matches = self.MAX_MATCHES

		def _store_match(line_text, line_num, char_offset):
			"""Store a search match as a lightweight tuple.

			No TextInfo or bookmark is created here. The TextInfo is resolved
			lazily in _jump_to_match_index() when the user selects a match.
			Line text is truncated to MAX_LINE_LENGTH for safety.
			"""
			if len(matches) >= max_matches:
				return
			if len(line_text) > max_line:
				line_text = line_text[:max_line]
			matches.append((None, line_text, line_num, None, char_offset))

		def _find_match_offset(line_text, pattern, case_sensitive, use_regex):
			"""Find the character offset of the first match in the line."""
			if use_regex:
				flags = 0 if case_sensitive else re.IGNORECASE
				match = re.search(pattern, line_text, flags)
				return match.start() if match else 0
			else:
				search_pattern = pattern if case_sensitive else pattern.lower()
				search_text = line_text if case_sensitive else line_text.lower()
				offset = search_text.find(search_pattern)
				return offset if offset >= 0 else 0

		try:
			# ─── Acquire the buffer text ───
			# Prefer the helper's off-main-thread UIA read when native
			# acceleration is on and the helper is running; otherwise read
			# in-process. Either way the matching runs in Python, which is
			# both faster than the native FFI search (measured) and simpler.
			all_text = None
			if _rt.native_available:
				try:
					helper = _rt.get_helper()
				except Exception:
					helper = None
				if helper is not None and helper.is_running:
					hwnd = getattr(self._terminal, "windowHandle", None)
					if hwnd:
						try:
							all_text = helper.read_text(hwnd)
						except Exception:
							all_text = None

			if all_text is None:
				info = self._terminal.makeTextInfo(textInfos.POSITION_ALL)
				all_text = info.text

			if not all_text:
				return 0

			# Strip ANSI escape sequences that some terminals leave in the
			# text buffer.
			all_text = _rt.strip_ansi(all_text)

			lines = all_text.split('\n')
			total_lines = len(lines)

			if use_regex:
				flags = 0 if case_sensitive else re.IGNORECASE
				compiled = re.compile(pattern, flags)
				matching_indices = [
					i for i, line in enumerate(lines) if compiled.search(line)
				]
			else:
				search_pattern = pattern if case_sensitive else pattern.lower()
				matching_indices = [
					i for i, line in enumerate(lines)
					if search_pattern in (line if case_sensitive else line.lower())
				]

			# ─── Section scoping ───
			# When scope="section", restrict matching_indices to lines
			# within the current section span.
			if scope == "section":
				try:
					from lib.section_tokenizer import SectionTokenizer
					section_lines = lines
					tokenizer = SectionTokenizer()
					tokenizer.tokenize(section_lines)
					spans = tokenizer.get_spans()
					# Find the span containing current_line.
					section_start = None
					section_end = None
					for sp in spans:
						if sp.start_line <= current_line <= sp.end_line:
							section_start = sp.start_line
							section_end = sp.end_line
							break
					if section_start is not None:
						matching_indices = [
							i for i in matching_indices
							if section_start <= i <= section_end
						]
					else:
						matching_indices = []
				except Exception:
					# If section scoping fails, fall back to no matches
					# rather than returning unscoped results.
					matching_indices = []

			# ─── Fuzzy fallback ───
			# If exact search returned nothing, try fuzzy matching
			# (Levenshtein distance <= 1 on each word in each line).
			fuzzy_fallback = False
			if not matching_indices and not use_regex and not case_sensitive:
				fuzzy_lines = lines

				# Apply section scoping to fuzzy search too.
				if scope == "section" and section_start is not None:
					fuzzy_candidate_indices = range(section_start, section_end + 1)
				else:
					fuzzy_candidate_indices = range(len(fuzzy_lines))

				for i in fuzzy_candidate_indices:
					if i >= len(fuzzy_lines):
						break
					line = fuzzy_lines[i]
					if self._line_fuzzy_matches(pattern, line):
						matching_indices.append(i)

				if matching_indices:
					fuzzy_fallback = True
					self._last_search_message = (
						f"No exact matches. Found {len(matching_indices)} "
						f"fuzzy match{'es' if len(matching_indices) != 1 else ''}."
					)

			if not matching_indices:
				self.add_to_history(pattern)
				return 0

			# ─── Store matches without TextInfo ───
			# Matches are stored as lightweight tuples. No bookmark walk
			# is performed here. The TextInfo is resolved lazily in
			# _jump_to_match_index() when the user selects a match.
			def _get_line_text(line_index):
				"""Get line text for a matched line index."""
				if 0 <= line_index < len(lines):
					return lines[line_index]
				return ""

			for line_index in matching_indices:
				line_text = _get_line_text(line_index)
				char_offset = _find_match_offset(
					line_text, pattern, case_sensitive, use_regex
				)
				_store_match(line_text, line_index + 1, char_offset)

			# Record pattern in search history.
			self.add_to_history(pattern)

			# Save results through the tab-aware state mechanism so
			# multi-tab and legacy modes stay in sync.
			self._save_search_state({
				'pattern': pattern,
				'matches': matches,
				'current_match_index': -1,
				'case_sensitive': case_sensitive,
				'use_regex': use_regex
			})

			return len(matches)

		except Exception:
			try:
				import logHandler
				logHandler.log.error("Terminal Access: search() failed", exc_info=True)
			except Exception:
				pass
			return 0

	def next_match(self) -> bool:
		"""
		Jump to next match.

		Returns:
			bool: True if jumped to next match
		"""
		state = self._get_search_state()
		matches = state['matches']
		if not matches:
			return False

		# Move to next match (wrap around)
		state['current_match_index'] = (state['current_match_index'] + 1) % len(matches)
		self._save_search_state(state)
		return self._jump_to_current_match()

	def previous_match(self) -> bool:
		"""
		Jump to previous match.

		Returns:
			bool: True if jumped to previous match
		"""
		state = self._get_search_state()
		matches = state['matches']
		if not matches:
			return False

		# Move to previous match (wrap around)
		state['current_match_index'] = (state['current_match_index'] - 1) % len(matches)
		self._save_search_state(state)
		return self._jump_to_current_match()

	def first_match(self) -> bool:
		"""
		Jump to first match.

		Returns:
			bool: True if jumped to first match
		"""
		state = self._get_search_state()
		if not state['matches']:
			return False

		state['current_match_index'] = 0
		self._save_search_state(state)
		return self._jump_to_current_match()

	def last_match(self) -> bool:
		"""
		Jump to last match.

		Returns:
			bool: True if jumped to last match
		"""
		state = self._get_search_state()
		if not state['matches']:
			return False

		state['current_match_index'] = len(state['matches']) - 1
		self._save_search_state(state)
		return self._jump_to_current_match()

	def _unpack_match(self, match):
		"""Handle legacy (bookmark, text, line), (bookmark, text, line, pos), and new (bookmark, text, line, pos, offset) tuples."""
		if len(match) == 5:
			return match[0], match[1], match[2], match[3], match[4]
		elif len(match) == 4:
			return match[0], match[1], match[2], match[3], 0
		bookmark, line_text, line_num = match
		return bookmark, line_text, line_num, None, 0

	def _jump_to_current_match(self) -> bool:
		"""
		Jump to current match index and position cursor at the search term.

		TextInfo is resolved lazily here (not during search). This avoids
		walking the entire buffer during search, which froze NVDA on large
		scrollback buffers.

		Returns:
			bool: True if jump successful
		"""
		state = self._get_search_state()
		matches = state['matches']
		current_index = state['current_match_index']
		if not matches or current_index < 0:
			return False

		try:
			bookmark, line_text, line_num, pos_info, char_offset = self._unpack_match(
				matches[current_index]
			)

			# Resolve TextInfo lazily: navigate from POSITION_FIRST
			# to the target line. Only one move() call per jump.
			pos = None
			if bookmark is not None:
				try:
					pos = self._terminal.makeTextInfo(bookmark)
				except (RuntimeError, AttributeError, TypeError, ValueError):
					pos = None

			if pos is None and pos_info is not None:
				try:
					pos = pos_info.copy()
				except (RuntimeError, AttributeError):
					pos = pos_info

			if pos is None and line_num is not None:
				try:
					pos = self._terminal.makeTextInfo(textInfos.POSITION_FIRST)
					if line_num > 1:
						pos.move(textInfos.UNIT_LINE, line_num - 1)
				except (RuntimeError, AttributeError, TypeError):
					pos = None

			if pos:
				if char_offset > 0:
					try:
						pos.move(textInfos.UNIT_CHARACTER, char_offset)
					except (RuntimeError, AttributeError, TypeError):
						pass

				_rt.api_module.setReviewPosition(pos)
				return True
		except (RuntimeError, AttributeError, TypeError, IndexError):
			pass

		return False

	def get_match_count(self) -> int:
		"""
		Get total number of matches.

		Returns:
			int: Number of matches
		"""
		state = self._get_search_state()
		return len(state['matches'])

	def get_current_match_info(self) -> tuple:
		"""
		Get information about current match.

		Returns:
			tuple: (match_number, total_matches, line_text, line_num) or None
		"""
		state = self._get_search_state()
		matches = state['matches']
		current_index = state['current_match_index']
		if not matches or current_index < 0:
			return None

		_, line_text, line_num, _, _ = self._unpack_match(matches[current_index])
		return (current_index + 1, len(matches), line_text, line_num)

	def get_all_matches(self) -> list:
		"""Get all search matches as structured dicts for dialog display.

		Returns:
			List of dicts with keys: num, line_num, text, bookmark, pos, offset.
			Empty list if no search has been performed or no matches found.
		"""
		state = self._get_search_state()
		matches = state['matches']
		results = []
		for i, match in enumerate(matches):
			bookmark, line_text, line_num, pos_info, char_offset = self._unpack_match(match)
			truncated = (line_text[:100] + "...") if len(line_text) > 100 else line_text
			results.append({
				"num": i + 1,
				"line_num": line_num,
				"text": truncated,
				"bookmark": bookmark,
				"pos": pos_info,
				"offset": char_offset,
			})
		return results

	def clear_search(self) -> None:
		"""Clear current search results."""
		self._save_search_state({
			'pattern': None,
			'matches': [],
			'current_match_index': -1,
			'case_sensitive': False,
			'use_regex': False
		})

	# ------------------------------------------------------------------
	# Search history
	# ------------------------------------------------------------------

	def add_to_history(self, pattern: str) -> None:
		"""Record a search pattern in the history list.

		Duplicates are removed so the pattern appears only once, at the
		front (most recent position). The history is capped at 10 entries.
		"""
		if not pattern:
			return
		# Remove existing occurrence to avoid duplicates.
		try:
			self._search_history.remove(pattern)
		except ValueError:
			pass
		# Insert at the front (most recent first).
		self._search_history.insert(0, pattern)
		# Cap at 10 entries.
		if len(self._search_history) > 10:
			self._search_history = self._search_history[:10]

	def get_history(self) -> list[str]:
		"""Return the search history list, most recent first."""
		return list(self._search_history)

	# ------------------------------------------------------------------
	# Fuzzy matching
	# ------------------------------------------------------------------

	@staticmethod
	def _levenshtein_distance(s1: str, s2: str) -> int:
		"""Compute Damerau-Levenshtein (optimal string alignment) distance.

		Counts insertions, deletions, substitutions, and adjacent
		transpositions as single edits. This means "erorr" vs "error"
		(which involves a transposition) counts as fewer edits than
		standard Levenshtein. Intended for word-level fuzzy comparisons.
		"""
		len1, len2 = len(s1), len(s2)
		# Build a full matrix so we can look back two rows for
		# transposition detection.
		d = [[0] * (len2 + 1) for _ in range(len1 + 1)]
		for i in range(len1 + 1):
			d[i][0] = i
		for j in range(len2 + 1):
			d[0][j] = j

		for i in range(1, len1 + 1):
			for j in range(1, len2 + 1):
				cost = 0 if s1[i - 1] == s2[j - 1] else 1
				d[i][j] = min(
					d[i - 1][j] + 1,      # deletion
					d[i][j - 1] + 1,      # insertion
					d[i - 1][j - 1] + cost,  # substitution
				)
				# Transposition check.
				if (i > 1 and j > 1
						and s1[i - 1] == s2[j - 2]
						and s1[i - 2] == s2[j - 1]):
					d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)

		return d[len1][len2]

	def _line_fuzzy_matches(self, pattern: str, line: str) -> bool:
		"""Check whether any word in *line* is within Levenshtein
		distance 1 of *pattern* (case-insensitive)."""
		pat_lower = pattern.lower()
		# Split on whitespace and common punctuation to get words.
		words = re.split(r'[\s:;,.()\[\]{}=<>!@#$%^&*|/\\]+', line)
		for word in words:
			if not word:
				continue
			if self._levenshtein_distance(pat_lower, word.lower()) <= 1:
				return True
		return False

	def fuzzy_search(self, pattern: str, lines: list[str]) -> list[str]:
		"""Search *lines* for fuzzy matches of *pattern*.

		Returns a list of matching line texts where at least one word is
		within Levenshtein distance 1 of the pattern (case-insensitive).
		"""
		if not pattern:
			return []
		results = []
		for line in lines:
			if self._line_fuzzy_matches(pattern, line):
				results.append(line)
		return results

	def get_last_search_message(self) -> str:
		"""Return the informational message from the last search.

		This is set when a fuzzy fallback occurs, containing a note like
		'No exact matches. Found N fuzzy matches.'
		"""
		return self._last_search_message

	def update_terminal(self, terminal_obj):
		"""
		Update the terminal reference.

		This should be called when the terminal is rebound to ensure
		searches can be properly performed.

		Args:
			terminal_obj: New terminal TextInfo object
		"""
		self._terminal = terminal_obj
		# Clear search results when terminal changes
		self.clear_search()

	def set_tab_manager(self, tab_manager):
		"""
		Set or update the tab manager for tab-aware search storage.

		Args:
			tab_manager: TabManager instance
		"""
		self._tab_manager = tab_manager


# ── URL entry data structure ─────────────────────────────────────────
UrlEntry = collections.namedtuple('UrlEntry', ['url', 'line_num', 'line_text', 'source', 'count'])


class UrlExtractorManager:
	"""
	Extract and manage URLs found in terminal output.

	Scans terminal buffer for URLs (HTTP/HTTPS/FTP, www-prefixed,
	file:// protocol, and OSC 8 terminal hyperlinks) and provides
	a navigable list with copy/open/move-to actions.
	"""

	def __init__(self, terminal_obj, tab_manager=None):
		self._terminal = terminal_obj
		self._tab_manager = tab_manager
		self._urls: list = []  # list of UrlEntry

	def extract_urls(self) -> list:
		"""Scan terminal buffer and return deduplicated URLs with context.

		Returns:
			List of UrlEntry namedtuples ordered by first occurrence.
		"""
		if not self._terminal:
			return []

		try:
			text_info = self._terminal.makeTextInfo(textInfos.POSITION_ALL)
			raw_text = text_info.text
		except (RuntimeError, AttributeError, TypeError):
			try:
				import logHandler
				logHandler.log.debugWarning("UrlExtractorManager: failed to read terminal text", exc_info=True)
			except (ImportError, AttributeError):
				pass
			return []

		if not raw_text:
			return []

		# Phase 1: Extract OSC 8 hyperlinks from raw text (before ANSI strip)
		osc8_urls: dict[str, int] = {}  # url -> first line_num
		raw_lines = raw_text.split('\n')
		for line_num, line in enumerate(raw_lines, start=1):
			for match in _OSC8_URL_PATTERN.finditer(line):
				url = _clean_url(match.group(1).strip())
				if url and url not in osc8_urls:
					osc8_urls[url] = line_num

		# Phase 2: Extract plain-text URLs after ANSI stripping
		clean_text = _rt.strip_ansi(raw_text)
		lines = clean_text.split('\n')

		# Deduplicate preserving first-occurrence order
		seen: collections.OrderedDict = collections.OrderedDict()

		# Add OSC 8 URLs first
		for url, line_num in osc8_urls.items():
			line_text = lines[line_num - 1].strip() if line_num <= len(lines) else ''
			seen[url] = {'line_num': line_num, 'line_text': line_text, 'source': 'osc8', 'count': 1}

		# Scan each line for plain-text URLs
		for line_num, line in enumerate(lines, start=1):
			for match in _URL_PATTERN.finditer(line):
				url = _clean_url(match.group(0).strip())
				if not url:
					continue
				if url in seen:
					seen[url]['count'] += 1
				else:
					seen[url] = {
						'line_num': line_num,
						'line_text': line.strip(),
						'source': 'text',
						'count': 1,
					}

		self._urls = [
			UrlEntry(url=url, line_num=meta['line_num'], line_text=meta['line_text'],
			         source=meta['source'], count=meta['count'])
			for url, meta in seen.items()
		]
		return list(self._urls)

	def get_url_count(self) -> int:
		"""Return number of extracted URLs."""
		return len(self._urls)

	def copy_url(self, index: int) -> bool:
		"""Copy URL at index to clipboard."""
		if 0 <= index < len(self._urls):
			_rt.api_module.copyToClip(self._urls[index].url)
			return True
		return False

	# Schemes considered safe to open in a browser.
	_SAFE_SCHEMES = ('http://', 'https://', 'ftp://')

	# Schemes that are always blocked regardless of user settings.
	_BLOCKED_SCHEMES = ('file://', 'javascript:', 'data:')

	def _is_safe_url(self, url: str) -> bool:
		"""Check whether a URL uses a safe scheme.

		Returns True for http://, https://, and ftp:// URLs.
		Returns False for file://, javascript:, data:, and any other
		unrecognized scheme.
		"""
		lower = url.lower()
		if any(lower.startswith(s) for s in self._BLOCKED_SCHEMES):
			return False
		# www. URLs are treated as safe (will get https:// prepended)
		if lower.startswith('www.'):
			return True
		return lower.startswith(self._SAFE_SCHEMES)

	def open_url(self, index: int) -> bool:
		"""Open URL at index in default browser.

		Only http://, https://, and ftp:// URLs are opened.  Other schemes
		(file://, javascript:, etc.) are rejected to prevent a malicious
		terminal from launching local executables.
		"""
		if 0 <= index < len(self._urls):
			url = self._urls[index].url
			# Ensure scheme for www. URLs
			if url.lower().startswith('www.'):
				url = 'https://' + url
			# Block unsafe schemes using centralized check
			if not self._is_safe_url(url):
				return False
			try:
				_rt.webbrowser_module.open(url)
				return True
			except (OSError, ValueError):
				return False
		return False

	def update_terminal(self, terminal_obj):
		"""Update terminal reference and clear cached URLs."""
		self._terminal = terminal_obj
		self._urls = []

	def set_tab_manager(self, tab_manager):
		"""Set or update tab manager."""
		self._tab_manager = tab_manager


def UrlListDialog(parent, urls, manager):
	"""Dialog for displaying and interacting with URLs found in terminal output.

	Thin wrapper: builds # / URL / Line / Context rows and delegates to
	BrowsableListDialog. Enter or the Open button opens the selected URL in
	the browser (unsafe schemes are blocked), the Copy URL and Move to line
	buttons act on the selection and close, a type-to-filter box matches the
	URL and context columns, and Escape closes.

	Modeled after NVDA's Elements List (NVDA+F7) but designed for terminal
	focus mode where the Elements List is unavailable.

	Args:
		parent: Parent window.
		urls: List of UrlEntry namedtuples with url, line_num, line_text.
		manager: The UrlExtractorManager (kept for signature compatibility).

	Returns:
		A BrowsableListDialog instance ready for ShowModal().
	"""
	from lib.list_dialogs import BrowsableListDialog, build_url_rows

	rows = build_url_rows(urls)

	def on_open(original_index):
		entry = urls[original_index]
		url = entry.url
		if url.lower().startswith('www.'):
			url = 'https://' + url
		# Block unsafe schemes (file://, javascript:, etc.)
		if not url.lower().startswith(UrlExtractorManager._SAFE_SCHEMES):
			# Translators: Announced when a URL with an unsafe scheme is blocked
			ui.message(_("Cannot open this URL type for security reasons"))
			return
		try:
			_rt.webbrowser_module.open(url)
		except Exception:
			pass

	def on_copy(original_index):
		_rt.api_module.copyToClip(urls[original_index].url)
		# Translators: Announced after URL is copied
		ui.message(_("URL copied"))
		return True

	def on_move(original_index):
		entry = urls[original_index]
		# Translators: Announced when moving to a URL line
		ui.message(_("Line {num}: {text}").format(
			num=entry.line_num, text=(entry.line_text or "")[:100]))
		return True

	return BrowsableListDialog(
		parent,
		# Translators: Title for URL list dialog
		title=_("URL List - Terminal Access"),
		columns=[
			# Translators: Column header for URL list index
			(_("#"), 40),
			# Translators: Column header for URL
			(_("URL"), 320),
			# Translators: Column header for line number
			(_("Line"), 55),
			# Translators: Column header for line context
			(_("Context"), 220),
		],
		rows=rows,
		on_activate=on_open,
		extra_buttons=[
			# Translators: Button to copy URL to clipboard
			(_("&Copy URL"), on_copy),
			# Translators: Button to move cursor to URL line
			(_("&Move to line"), on_move),
		],
		enable_search=True,
		search_columns=(1, 3),
	)


def SearchResultsDialog(parent, search_manager, on_jump_callback=None):
	"""Dialog for browsing and jumping to search results.

	Thin wrapper: builds # / Line / Content rows and delegates to
	BrowsableListDialog. Enter or the Activate button records the chosen
	match as the manager's current index (so findNext/findPrevious continue
	from there), jumps to it, and closes. Escape closes. The match count and
	pattern go in the dialog title so they are announced on open.

	Args:
		parent: Parent window.
		search_manager: Manager exposing get_all_matches(),
			_get_search_state(), _save_search_state() and
			_jump_to_current_match().
		on_jump_callback: Optional callable() fired after a jump.

	Returns:
		A BrowsableListDialog instance ready for ShowModal().
	"""
	from lib.list_dialogs import BrowsableListDialog, build_search_rows

	matches = search_manager.get_all_matches()
	rows = build_search_rows(matches)
	state = search_manager._get_search_state()
	pattern = state.get('pattern', '')
	# Translators: Title for search results dialog, with the match count and pattern
	title = _("Search Results: {count} matches for '{pattern}'").format(
		count=len(matches), pattern=pattern)

	def on_jump(original_index):
		# Set the search manager's current index so findNext/findPrevious
		# continue from this position after the dialog closes.
		jump_state = search_manager._get_search_state()
		jump_state['current_match_index'] = original_index
		search_manager._save_search_state(jump_state)
		search_manager._jump_to_current_match()
		if on_jump_callback:
			on_jump_callback()

	return BrowsableListDialog(
		parent,
		title=title,
		columns=[
			# Translators: Column header for match number
			(_("#"), 50),
			# Translators: Column header for line number
			(_("Line"), 60),
			# Translators: Column header for line content
			(_("Content"), 400),
		],
		rows=rows,
		on_activate=on_jump,
	)

