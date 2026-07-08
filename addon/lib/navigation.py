# Terminal Access navigation classes (tabs and bookmarks).
# Extracted from terminalAccess.py for modularization.

import re

import api
import textInfos

from lib.section_tokenizer import SectionTokenizer
from lib.ai_turn_tokenizer import classify_ai_line
from lib.text_processing import ANSIParser


class TabManager:
	"""
	Manage terminal tabs for quick navigation and state tracking.

	Section 9: Tab Management Functionality (v1.0.39+)

	This class enables users to detect, navigate, and manage tabs within terminal
	applications like Windows Terminal, allowing for tab-aware bookmark and search
	state management.

	Features:
	- Tab detection using window properties and content heuristics
	- Tab navigation with keyboard shortcuts
	- Per-tab state isolation for bookmarks, searches, and command history
	- Tab listing and enumeration
	- Support for multiple terminal applications

	Example usage:
		>>> manager = TabManager(terminal_obj)
		>>> tab_id = manager.get_current_tab_id()
		>>> manager.list_tabs()
		>>> manager.switch_to_tab(1)
	"""

	def __init__(self, terminal_obj):
		"""
		Initialize the TabManager.

		Args:
			terminal_obj: Terminal TextInfo object
		"""
		self._terminal = terminal_obj
		self._tabs = {}  # tab_id -> tab_info mapping
		self._current_tab_id = None
		self._last_window_title = None
		self._update_current_tab()

	def _generate_tab_id(self, terminal_obj) -> str:
		"""
		Generate a unique tab identifier based on terminal properties.

		Uses window handle, title, and content hash to create a unique ID.

		Args:
			terminal_obj: Terminal TextInfo object

		Returns:
			str: Unique tab identifier
		"""
		try:
			# Try to get window properties
			components = []

			# Add window handle if available
			if hasattr(terminal_obj, 'windowHandle'):
				components.append(str(terminal_obj.windowHandle))

			# Add window text/title if available
			if hasattr(terminal_obj, 'windowText'):
				components.append(terminal_obj.windowText or "")
			elif hasattr(terminal_obj, 'name'):
				components.append(terminal_obj.name or "")

			# Add object ID if available
			if hasattr(terminal_obj, '_get_ID'):
				try:
					obj_id = terminal_obj._get_ID()
					components.append(str(obj_id))
				except Exception:
					pass

			# Create hash from components
			import hashlib
			tab_str = "|".join(components)
			tab_hash = hashlib.md5(tab_str.encode()).hexdigest()[:12]

			return tab_hash

		except Exception:
			# Fallback to simple counter-based ID
			return f"tab_{len(self._tabs)}"

	def _update_current_tab(self):
		"""Update information about the currently focused tab."""
		try:
			tab_id = self._generate_tab_id(self._terminal)

			# Register tab if it's new
			if tab_id not in self._tabs:
				self._tabs[tab_id] = {
					'id': tab_id,
					'title': self._get_tab_title(),
					'created': None,  # Could add timestamp
					'last_accessed': None
				}

			self._current_tab_id = tab_id

			# Update title cache
			self._last_window_title = self._get_tab_title()

		except Exception:
			pass

	def _get_tab_title(self) -> str:
		"""
		Get the title of the current tab.

		Returns:
			str: Tab title or empty string
		"""
		try:
			if hasattr(self._terminal, 'windowText'):
				return self._terminal.windowText or ""
			elif hasattr(self._terminal, 'name'):
				return self._terminal.name or ""
		except Exception:
			pass
		return ""

	def get_current_tab_id(self) -> str:
		"""
		Get the identifier of the currently focused tab.

		Returns:
			str: Current tab ID or None
		"""
		return self._current_tab_id

	def list_tabs(self) -> list:
		"""
		Get list of all known tabs.

		Returns:
			list: List of tab info dictionaries
		"""
		return list(self._tabs.values())

	def get_tab_count(self) -> int:
		"""
		Get number of known tabs.

		Returns:
			int: Number of tabs
		"""
		return len(self._tabs)

	def update_terminal(self, terminal_obj):
		"""
		Update the terminal reference and check for tab changes.

		This should be called when the terminal is rebound to detect
		tab switches and update tab tracking.

		Args:
			terminal_obj: New terminal TextInfo object
		"""
		self._terminal = terminal_obj
		old_tab_id = self._current_tab_id
		self._update_current_tab()

		# Return True if tab changed
		return self._current_tab_id != old_tab_id

	def has_tab_changed(self) -> bool:
		"""
		Check if the tab has changed since last check.

		Returns:
			bool: True if tab appears to have changed
		"""
		try:
			current_title = self._get_tab_title()
			if current_title != self._last_window_title:
				self._last_window_title = current_title
				self._update_current_tab()
				return True
		except Exception:
			pass
		return False

	def clear_tab_info(self, tab_id: str) -> bool:
		"""
		Remove information about a specific tab.

		Args:
			tab_id: Tab identifier

		Returns:
			bool: True if tab was removed
		"""
		if tab_id in self._tabs:
			del self._tabs[tab_id]
			return True
		return False

	def clear_all_tabs(self):
		"""Clear all tab information."""
		self._tabs.clear()
		self._current_tab_id = None


class BookmarkManager:
	"""
	Manage bookmarks/markers in terminal output for quick navigation.

	Section 8.3: Bookmark/Marker Functionality (v1.0.29+)

	This class enables users to set named bookmarks at specific positions in
	the terminal output and quickly jump back to those positions. Useful for:
	- Marking important log entries
	- Saving positions in long output
	- Navigating back to command results
	- Quick navigation in code review sessions

	Features:
	- Named bookmarks (0-9 and custom names)
	- Quick jump to bookmarks
	- List all bookmarks
	- Remove bookmarks
	- Persistent across terminal sessions (position-relative)

	Example usage:
		>>> manager = BookmarkManager(terminal_obj)
		>>> manager.set_bookmark("1")  # Quick bookmark with number
		>>> manager.set_bookmark("build_error")  # Named bookmark
		>>> manager.jump_to_bookmark("1")
		>>> manager.list_bookmarks()
		>>> manager.remove_bookmark("1")
	"""

	_LABEL_MAX_LENGTH = 50
	_BLANK_LINE_LABEL = "(blank line)"

	def __init__(self, terminal_obj, tab_manager=None):
		"""
		Initialize the BookmarkManager.

		Args:
			terminal_obj: Terminal TextInfo object for bookmark storage
			tab_manager: Optional TabManager for tab-aware bookmark storage
		"""
		self._terminal = terminal_obj
		self._tab_manager = tab_manager
		self._bookmarks = {}  # name -> {"bookmark": obj, "label": str}
		self._tab_bookmarks = {}  # tab_id -> {name -> {"bookmark": obj, "label": str}}
		self._max_bookmarks = 50  # Maximum number of bookmarks per tab

	def _get_current_tab_id(self) -> str:
		"""Get current tab ID, or None if no tab manager."""
		if self._tab_manager:
			return self._tab_manager.get_current_tab_id()
		return None

	def _get_bookmark_dict(self):
		"""Get the appropriate bookmark dictionary for the current context."""
		tab_id = self._get_current_tab_id()
		if tab_id:
			# Multi-tab mode: use per-tab storage
			if tab_id not in self._tab_bookmarks:
				self._tab_bookmarks[tab_id] = {}
			return self._tab_bookmarks[tab_id]
		else:
			# Legacy mode: use shared storage
			return self._bookmarks

	# Prompt patterns for extracting command text from prompt lines.
	_PROMPT_COMMAND_RE = [
		# user@host:path$ <command>
		re.compile(r'^[a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+:[^\$#]*[\$#]\s+(.+)'),
		# PS C:\path> <command>
		re.compile(r'^PS\s+[A-Za-z]:\\.*>\s*(.+)', re.IGNORECASE),
		# "$ <command>"
		re.compile(r'^\$\s+(.+)'),
		# "> <command>"
		re.compile(r'^>\s+(.+)'),
	]

	@staticmethod
	def _make_label(text) -> str:
		"""Build a bookmark label from line text, trimmed and capped."""
		if not isinstance(text, str) or not text.strip():
			return BookmarkManager._BLANK_LINE_LABEL
		label = text.strip()
		if len(label) > BookmarkManager._LABEL_MAX_LENGTH:
			label = label[:BookmarkManager._LABEL_MAX_LENGTH]
		return label

	def _auto_label(self, line_text, line_num, buffer_lines) -> str:
		"""Generate a context-aware label using SectionTokenizer.

		Classification priority:
		0. AI turn roles (user/assistant/system/code block)
		1. Prompt line: "prompt: <command text>"
		2. Error line: "error: <first 40 chars>"
		3. Heading line: "heading: <heading text>"
		4. Near a prompt (within 5 lines above): "<command>: <line text>"
		5. Fallback: first 50 chars of line text

		Args:
			line_text: Text of the current line.
			line_num: 0-based line index in the buffer.
			buffer_lines: Full list of buffer lines.

		Returns:
			str: The generated label, capped at 50 chars.
		"""
		stripped = ANSIParser.stripANSI(line_text).strip()

		# Priority 0: AI turn role detection
		ai_result = self._classify_ai_turn(stripped)
		if ai_result is not None:
			role, preview = ai_result
			ai_label = f"{role}: {preview}" if preview else role
			if len(ai_label) > self._LABEL_MAX_LENGTH:
				ai_label = ai_label[:self._LABEL_MAX_LENGTH]
			return ai_label

		# Classify this single line without tokenizing the entire buffer.
		tokenizer = SectionTokenizer()
		category = tokenizer._classify(line_text, line_num, buffer_lines)

		# Use ANSI-stripped text for all label content.
		clean_text = stripped

		label = None

		if category == "prompt":
			# Extract the command portion after the prompt symbol
			cmd_text = self._extract_command(clean_text)
			if cmd_text:
				label = f"prompt: {cmd_text}"
			else:
				label = f"prompt: {clean_text}"

		elif category in ("error", "warning"):
			trimmed = clean_text[:40]
			label = f"error: {trimmed}"

		elif category == "heading":
			label = f"heading: {clean_text}"

		else:
			# Check if we're near a prompt (within 5 lines above)
			nearest_prompt = self._find_nearest_prompt_above(
				line_num, buffer_lines, max_distance=5
			)
			if nearest_prompt is not None:
				prompt_clean = ANSIParser.stripANSI(buffer_lines[nearest_prompt])
				cmd_text = self._extract_command(prompt_clean)
				if cmd_text:
					label = f"{cmd_text}: {clean_text}"

		# Fallback: use cleaned text
		if label is None:
			label = clean_text

		# Truncate
		if len(label) > self._LABEL_MAX_LENGTH:
			label = label[:self._LABEL_MAX_LENGTH]

		return label if label else self._BLANK_LINE_LABEL

	@staticmethod
	def _classify_ai_turn(stripped_text):
		"""Classify a line as an AI turn role.

		Delegates to the shared classify_ai_line() in ai_turn_tokenizer.
		Returns a (role, preview) tuple, or None.
		"""
		return classify_ai_line(stripped_text)

	@staticmethod
	def _extract_command(prompt_line):
		"""Extract the command text from a prompt line.

		Returns the command portion (after the prompt symbol), or None.
		"""
		for pat in BookmarkManager._PROMPT_COMMAND_RE:
			m = pat.match(prompt_line)
			if m:
				return m.group(1).strip()
		return None

	@staticmethod
	def _find_nearest_prompt_above(line_num, buffer_lines, max_distance=5):
		"""Find the nearest prompt line within max_distance lines above.

		Returns the 0-based line index of the prompt, or None.
		"""
		tokenizer = SectionTokenizer()
		start = max(0, line_num - max_distance)
		for idx in range(line_num - 1, start - 1, -1):
			cat = tokenizer._classify(buffer_lines[idx], idx, buffer_lines)
			if cat == "prompt":
				return idx
		return None

	@staticmethod
	def _resolve_line_number(pos) -> int | None:
		"""Determine the 1-based line number of a TextInfo position.

		Tries the _lineNumber attribute (NVDA UIA), then falls back
		to counting lines backwards from the current position.
		Returns None if line number cannot be determined.
		"""
		# Some UIA TextInfos expose a line number directly
		line_num = getattr(pos, "_lineNumber", None)
		if isinstance(line_num, int) and line_num >= 0:
			return line_num + 1  # convert 0-based to 1-based

		# Fallback: count lines backwards from current position.
		# Safety limit prevents infinite loop if move() never returns 0.
		_MAX_LINES = 50000
		try:
			copy = pos.copy()
			copy.collapse()
			count = 0
			for _ in range(_MAX_LINES):
				moved = copy.move(textInfos.UNIT_LINE, -1)
				if moved == 0:
					break
				count += 1
			return count + 1
		except (AttributeError, RuntimeError, TypeError):
			return None

	def set_bookmark(self, name: str) -> bool:
		"""
		Set bookmark at current review position.

		Captures the current line text as the bookmark label (first 50
		characters, stripped). Blank lines get a descriptive placeholder.

		Args:
			name: Bookmark name (e.g., "1", "error", "important")

		Returns:
			bool: True if bookmark set successfully
		"""
		if not self._terminal:
			return False

		# Validate bookmark name
		if not name or len(name) > 50:
			return False

		bookmarks = self._get_bookmark_dict()

		# Check max bookmarks limit
		if name not in bookmarks and len(bookmarks) >= self._max_bookmarks:
			return False

		try:
			# Get current review position
			pos = api.getReviewPosition()
			if not pos:
				return False

			# Expand to full line to capture meaningful label text.
			# getReviewPosition() returns a TextInfo at the review unit
			# (character or word), not the full line. Without expanding,
			# the label would be just one character.
			line_text = ""
			try:
				line_copy = pos.copy()
				line_copy.expand(textInfos.UNIT_LINE)
				expanded = getattr(line_copy, "text", "")
				if isinstance(expanded, str) and expanded.strip():
					line_text = expanded
			except (AttributeError, RuntimeError, TypeError):
				pass
			if not line_text:
				line_text = getattr(pos, "text", "") or ""

			# Try context-aware auto-labeling if buffer lines are available.
			line_num = self._resolve_line_number(pos)
			buffer_lines = getattr(self, "_buffer_lines", None)
			if buffer_lines and line_num is not None:
				line_idx = line_num - 1  # convert 1-based to 0-based
				if 0 <= line_idx < len(buffer_lines):
					label = self._auto_label(
						buffer_lines[line_idx], line_idx, buffer_lines
					)
				else:
					label = self._make_label(line_text)
			else:
				label = self._make_label(line_text)

			# Store bookmark with label and line number.
			# Many terminal UIA implementations don't support bookmarks
			# (pos.bookmark is None). We store the line number so
			# jump_to_bookmark can navigate by POSITION_FIRST + move().
			bookmark_obj = getattr(pos, "bookmark", None)
			bookmarks[name] = {
				"bookmark": bookmark_obj,
				"label": label,
				"line_num": line_num,
			}
			return True

		except Exception:
			return False

	def jump_to_bookmark(self, name: str) -> bool:
		"""
		Jump to named bookmark.

		Tries the stored bookmark object first. If that fails (common
		when UIA doesn't support bookmarks), falls back to navigating
		by line number using POSITION_FIRST + move(UNIT_LINE).

		Never silently deletes a bookmark on jump failure.

		Args:
			name: Bookmark name

		Returns:
			bool: True if jump successful
		"""
		bookmarks = self._get_bookmark_dict()
		if not self._terminal or name not in bookmarks:
			return False

		entry = bookmarks[name]
		bookmark_obj = entry.get("bookmark")
		line_num = entry.get("line_num")

		# Try bookmark object first
		if bookmark_obj is not None:
			try:
				pos = self._terminal.makeTextInfo(bookmark_obj)
				if pos:
					api.setReviewPosition(pos)
					return True
			except Exception:
				pass

		# Fall back to line number navigation
		if line_num is not None and line_num >= 1:
			try:
				pos = self._terminal.makeTextInfo(textInfos.POSITION_FIRST)
				if line_num > 1:
					pos.move(textInfos.UNIT_LINE, line_num - 1)
				pos.expand(textInfos.UNIT_LINE)
				api.setReviewPosition(pos)
				return True
			except Exception:
				pass

		return False

	def remove_bookmark(self, name: str) -> bool:
		"""
		Remove named bookmark.

		Args:
			name: Bookmark name

		Returns:
			bool: True if bookmark removed
		"""
		bookmarks = self._get_bookmark_dict()
		if name in bookmarks:
			del bookmarks[name]
			return True
		return False

	def list_bookmarks(self) -> list:
		"""
		Get structured list of all bookmarks for the current tab.

		Returns:
			list: Sorted list of dicts with keys 'name', 'label', 'bookmark'.
		"""
		bookmarks = self._get_bookmark_dict()
		return [
			{"name": name, "label": entry["label"], "bookmark": entry["bookmark"]}
			for name, entry in sorted(bookmarks.items())
		]

	def has_bookmark(self, name: str) -> bool:
		"""
		Check if bookmark exists in the current tab.

		Args:
			name: Bookmark name

		Returns:
			bool: True if bookmark exists
		"""
		bookmarks = self._get_bookmark_dict()
		return name in bookmarks

	def get_bookmark_label(self, name: str):
		"""
		Get the label for a named bookmark.

		Args:
			name: Bookmark name

		Returns:
			str or None: The bookmark label, or None if not found.
		"""
		bookmarks = self._get_bookmark_dict()
		entry = bookmarks.get(name)
		if entry:
			return entry["label"]
		return None

	def rename_bookmark(self, name: str, new_label: str) -> bool:
		"""Rename a bookmark's label.

		Args:
			name: Bookmark name.
			new_label: New label text.

		Returns:
			bool: True if the bookmark was found and renamed.
		"""
		bookmarks = self._get_bookmark_dict()
		if name not in bookmarks:
			return False
		bookmarks[name]["label"] = new_label
		return True

	def list_sections(self, buffer_lines, category=None):
		"""Return all detected sections in the buffer.

		Each entry is a dict with keys: type, line_num, preview.

		Args:
			buffer_lines: List of terminal buffer lines.
			category: Optional filter; only return sections of this type.

		Returns:
			list[dict]: Section entries.
		"""
		tokenizer = SectionTokenizer()
		sections = tokenizer.tokenize(buffer_lines)
		result = []
		for sec in sections:
			if category is not None and sec.category != category:
				continue
			raw = ANSIParser.stripANSI(sec.text).strip() if sec.text else ""
			preview = raw[:self._LABEL_MAX_LENGTH]
			result.append({
				"type": sec.category,
				"line_num": sec.line_num,
				"preview": preview,
			})
		return result

	def list_ai_turns(self, buffer_lines):
		"""Return all detected AI conversation turns in the buffer.

		Scans each line for AI turn markers (user prompts, assistant
		responses, system messages, code blocks) using the same regex
		patterns as _auto_label.

		Args:
			buffer_lines: List of terminal buffer lines.

		Returns:
			list[dict]: Each dict has keys: role, line_num, preview.
		"""
		result = []
		for idx, line in enumerate(buffer_lines):
			stripped = ANSIParser.stripANSI(line).strip()
			ai_result = self._classify_ai_turn(stripped)
			if ai_result is None:
				continue
			role, preview = ai_result
			result.append({
				"role": role,
				"line_num": idx,
				"preview": preview,
			})
		return result

	def clear_all(self) -> None:
		"""Clear all bookmarks for the current tab."""
		bookmarks = self._get_bookmark_dict()
		bookmarks.clear()

	def get_bookmark_count(self) -> int:
		"""Get number of bookmarks for the current tab."""
		bookmarks = self._get_bookmark_dict()
		return len(bookmarks)

	def update_terminal(self, terminal_obj):
		"""
		Update the terminal reference.

		This should be called when the terminal is rebound to ensure
		bookmarks can be properly retrieved.

		Args:
			terminal_obj: New terminal TextInfo object
		"""
		self._terminal = terminal_obj

	def set_tab_manager(self, tab_manager):
		"""
		Set or update the tab manager for tab-aware bookmark storage.

		Args:
			tab_manager: TabManager instance
		"""
		self._tab_manager = tab_manager


try:
	import wx
	_wx_available = True
except ImportError:
	_wx_available = False


if _wx_available:
	def BookmarkListDialog(parent, bookmark_manager):
		"""Accessible dialog for viewing and navigating bookmarks.

		Thin wrapper: builds Number / Line Content rows live from the
		bookmark manager and delegates to BrowsableListDialog. Enter or
		the Activate button jumps to the selected bookmark, the Delete
		key removes it (the list re-reads from the manager), Escape closes.

		Args:
			parent: Parent window.
			bookmark_manager: Manager exposing list_bookmarks(),
				jump_to_bookmark(name) and remove_bookmark(name).

		Returns:
			A BrowsableListDialog instance ready for ShowModal().
		"""
		from lib.list_dialogs import BrowsableListDialog, build_bookmark_rows

		def rows_provider():
			return build_bookmark_rows(bookmark_manager.list_bookmarks())

		def _name_at(original_index):
			bookmarks = bookmark_manager.list_bookmarks()
			if 0 <= original_index < len(bookmarks):
				return bookmarks[original_index]["name"]
			return None

		def on_activate(original_index):
			name = _name_at(original_index)
			if name is not None:
				bookmark_manager.jump_to_bookmark(name)

		def on_delete(original_index):
			name = _name_at(original_index)
			if name is not None:
				bookmark_manager.remove_bookmark(name)

		return BrowsableListDialog(
			parent,
			# Translators: Title of the bookmark list dialog
			title=_("Bookmarks"),
			columns=[
				# Translators: Column header for the bookmark number
				(_("Number"), 80),
				# Translators: Column header for the bookmark line content
				(_("Line Content"), 400),
			],
			rows=[],
			on_activate=on_activate,
			rows_provider=rows_provider,
			key_actions={wx.WXK_DELETE: on_delete},
		)

	def SectionListDialog(parent, sections, jump_callback):
		"""Accessible dialog for viewing and navigating detected sections.

		Thin wrapper: builds Section Type / Line / Preview rows and a
		per-type filter, then delegates to BrowsableListDialog. Enter or
		the Activate button jumps to the selected section, Escape closes.

		Args:
			parent: Parent window.
			sections: List of section dicts (type, line_num, preview).
			jump_callback: Callable(line_num) to jump to a section.

		Returns:
			A BrowsableListDialog instance ready for ShowModal().
		"""
		from lib.list_dialogs import BrowsableListDialog

		rows = [
			(sec["type"], str(sec["line_num"] + 1), sec["preview"])
			for sec in sections
		]
		types = sorted(set(sec["type"] for sec in sections))
		filter_choices = [
			(section_type, lambda row, t=section_type: row[0] == t)
			for section_type in types
		]

		def on_activate(original_index):
			jump_callback(sections[original_index]["line_num"])

		return BrowsableListDialog(
			parent,
			# Translators: Title of the section list dialog
			title=_("Sections"),
			columns=[
				# Translators: Column header for the section type
				(_("Section Type"), 120),
				# Translators: Column header for the line number
				(_("Line"), 60),
				# Translators: Column header for the section preview text
				(_("Preview"), 350),
			],
			rows=rows,
			on_activate=on_activate,
			filter_choices=filter_choices,
		)

	def AiTurnListDialog(parent, turns, jump_callback):
		"""Accessible dialog for viewing and navigating AI conversation turns.

		Thin wrapper: builds Role / Line / Preview rows and a per-role
		filter, then delegates to BrowsableListDialog. Enter or the
		Activate button jumps to the selected turn, Escape closes.

		Args:
			parent: Parent window.
			turns: List of turn dicts (role, line_num, preview).
			jump_callback: Callable(line_num) to jump to a turn.

		Returns:
			A BrowsableListDialog instance ready for ShowModal().
		"""
		from lib.list_dialogs import BrowsableListDialog, build_ai_turn_rows

		rows, filter_choices = build_ai_turn_rows(turns)

		def on_activate(original_index):
			jump_callback(turns[original_index]["line_num"])

		return BrowsableListDialog(
			parent,
			# Translators: Title of the AI turn list dialog
			title=_("AI Turns"),
			columns=[
				# Translators: Column header for the AI turn role
				(_("Role"), 100),
				# Translators: Column header for the line number
				(_("Line"), 60),
				# Translators: Column header for the AI turn preview text
				(_("Preview"), 380),
			],
			rows=rows,
			on_activate=on_activate,
			filter_choices=filter_choices,
		)

else:
	# Placeholder so imports don't break in test environments without wx.
	BookmarkListDialog = None
	SectionListDialog = None
	AiTurnListDialog = None
