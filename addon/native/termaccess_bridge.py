# Terminal Access for NVDA - Native Bridge
# Copyright (C) 2024 Pratik Patel
# This add-on is covered by the GNU General Public License, version 3.
# See the file LICENSE for more details.

"""
ctypes wrapper around the Rust ``termaccess.dll``.

Provides drop-in replacements for the CPU-bound Python classes:

* :class:`NativeTextDiffer` — replaces :class:`TextDiffer`
* :class:`NativePositionCache` — replaces :class:`PositionCache`

ANSI stripping and text search are done in Python (the FFI round-trip
measured about 10x slower), so they are not provided here.

All functions are designed to fail gracefully: if the DLL cannot be loaded,
:func:`native_available` returns ``False`` and callers should fall back to
the pure-Python implementations.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import threading
from ctypes import (
	POINTER,
	Structure,
	byref,
	c_int32,
	c_uint32,
	c_size_t,
	c_ubyte,
)
from typing import Any

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Error codes (must match ffi_types.rs)
# ═══════════════════════════════════════════════════════════════

ERR_OK = 0
ERR_NULL_POINTER = 1
ERR_INVALID_UTF8 = 2
ERR_NOT_FOUND = 3
ERR_INVALID_REGEX = 4

# ═══════════════════════════════════════════════════════════════
#  DLL loading
# ═══════════════════════════════════════════════════════════════

_dll_lock = threading.Lock()
_dll: ctypes.CDLL | None = None
_dll_load_attempted = False


def _find_dll() -> str | None:
	"""Locate ``termaccess.dll`` for the running architecture."""
	arch = "x64" if struct.calcsize("P") == 8 else "x86"
	# Walk up from this file's directory to find addon/lib/<arch>/termaccess.dll
	here = os.path.dirname(os.path.abspath(__file__))
	# Expected: addon/native/termaccess_bridge.py → addon/lib/<arch>/termaccess.dll
	addon_dir = os.path.dirname(here)  # addon/
	dll_path = os.path.join(addon_dir, "lib", arch, "termaccess.dll")
	if os.path.isfile(dll_path):
		return dll_path
	log.debug("Native DLL not found at %s", dll_path)
	return None


def _get_dll() -> ctypes.CDLL | None:
	"""Lazy-load the native DLL.  Thread-safe, loads at most once."""
	global _dll, _dll_load_attempted
	if _dll is not None:
		return _dll
	if _dll_load_attempted:
		return None

	with _dll_lock:
		# Double-check after acquiring lock
		if _dll is not None:
			return _dll
		if _dll_load_attempted:
			return None

		_dll_load_attempted = True
		dll_path = _find_dll()
		if dll_path is None:
			return None

		try:
			lib = ctypes.CDLL(dll_path)
			_setup_signatures(lib)
			# Verify it loaded correctly by checking version
			ver_ptr = lib.ta_version()
			ver_len = lib.ta_version_len()
			ver = ctypes.string_at(ver_ptr, ver_len).decode("utf-8")
			log.info("Native DLL loaded: termaccess v%s from %s", ver, dll_path)
			_dll = lib
			return lib
		except (OSError, AttributeError, UnicodeDecodeError) as e:
			log.warning("Failed to load native DLL from %s: %s", dll_path, e)
			return None


def _setup_signatures(lib: ctypes.CDLL) -> None:
	"""Declare argument and return types for all exported functions."""

	# Version
	lib.ta_version.argtypes = []
	lib.ta_version.restype = POINTER(c_ubyte)

	lib.ta_version_len.argtypes = []
	lib.ta_version_len.restype = c_size_t

	# Memory management
	lib.ta_free_string.argtypes = [POINTER(c_ubyte), c_size_t]
	lib.ta_free_string.restype = None

	# TextDiffer
	lib.ta_text_differ_new.argtypes = []
	lib.ta_text_differ_new.restype = ctypes.c_void_p

	lib.ta_text_differ_free.argtypes = [ctypes.c_void_p]
	lib.ta_text_differ_free.restype = None

	lib.ta_text_differ_update.argtypes = [
		ctypes.c_void_p,   # handle
		POINTER(c_ubyte),  # text_ptr
		c_size_t,          # text_len
		POINTER(c_uint32), # out_kind
		POINTER(POINTER(c_ubyte)),  # out_content_ptr
		POINTER(c_size_t), # out_content_len
	]
	lib.ta_text_differ_update.restype = c_int32

	lib.ta_text_differ_reset.argtypes = [ctypes.c_void_p]
	lib.ta_text_differ_reset.restype = None

	lib.ta_text_differ_last_text.argtypes = [
		ctypes.c_void_p,            # handle
		POINTER(POINTER(c_ubyte)),  # out_ptr
		POINTER(c_size_t),          # out_len
	]
	lib.ta_text_differ_last_text.restype = c_int32

	# ANSI stripping and search are done in Python (faster than the FFI
	# round-trip), so those symbols are no longer declared here.

	# PositionCache
	lib.ta_position_cache_new.argtypes = [c_uint32, c_uint32]
	lib.ta_position_cache_new.restype = ctypes.c_void_p

	lib.ta_position_cache_free.argtypes = [ctypes.c_void_p]
	lib.ta_position_cache_free.restype = None

	lib.ta_position_cache_get.argtypes = [
		ctypes.c_void_p,   # handle
		POINTER(c_ubyte),  # key_ptr
		c_size_t,          # key_len
		POINTER(c_int32),  # out_row
		POINTER(c_int32),  # out_col
	]
	lib.ta_position_cache_get.restype = c_int32

	lib.ta_position_cache_set.argtypes = [
		ctypes.c_void_p,   # handle
		POINTER(c_ubyte),  # key_ptr
		c_size_t,          # key_len
		c_int32,           # row
		c_int32,           # col
	]
	lib.ta_position_cache_set.restype = None

	lib.ta_position_cache_clear.argtypes = [ctypes.c_void_p]
	lib.ta_position_cache_clear.restype = None

	lib.ta_position_cache_invalidate.argtypes = [
		ctypes.c_void_p,   # handle
		POINTER(c_ubyte),  # key_ptr
		c_size_t,          # key_len
	]
	lib.ta_position_cache_invalidate.restype = None

	# Fuzzy search
	lib.ta_fuzzy_search.argtypes = [
		POINTER(c_ubyte),  # pattern_ptr
		c_size_t,          # pattern_len
		POINTER(c_ubyte),  # lines_ptr
		c_size_t,          # lines_len
		c_uint32,          # max_distance
		POINTER(c_ubyte),  # out_buf
		c_size_t,          # out_buf_len
	]
	lib.ta_fuzzy_search.restype = c_int32

	# Scoped search
	lib.ta_scoped_search.argtypes = [
		POINTER(c_ubyte),  # pattern_ptr
		c_size_t,          # pattern_len
		POINTER(c_ubyte),  # lines_ptr
		c_size_t,          # lines_len
		c_uint32,          # start
		c_uint32,          # end
		c_uint32,          # case_sensitive
		POINTER(c_ubyte),  # out_buf
		c_size_t,          # out_buf_len
	]
	lib.ta_scoped_search.restype = c_int32

	# Unicode width
	lib.ta_text_width.argtypes = [POINTER(c_ubyte), c_size_t]
	lib.ta_text_width.restype = c_uint32


# Master switch for native acceleration (DLL + helper). Users can turn it
# off via the "Use native acceleration" setting to force the in-process
# Python path (the pre-2.0 behavior) as an escape hatch.
_native_enabled = True


def set_native_enabled(enabled: bool):
	"""Enable or disable all native acceleration (DLL and helper process).

	When disabled, :func:`native_available` returns False and
	:func:`get_helper` returns None, so every caller falls back to the
	in-process Python implementation. Disabling also stops a running helper.
	"""
	global _native_enabled
	_native_enabled = bool(enabled)
	if not _native_enabled:
		try:
			stop_helper()
		except Exception:
			pass


def native_available() -> bool:
	"""Return True if native acceleration is enabled and the DLL is loaded."""
	return _native_enabled and _get_dll() is not None


# ═══════════════════════════════════════════════════════════════
#  FFI safety state
# ═══════════════════════════════════════════════════════════════

_native_available = False   # Set True after DLL loads successfully
_ffi_error_logged = False   # True after the first FFI error is logged
_fallback_count = 0         # Number of times callers fell back to Python


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _str_to_utf8(s: str) -> tuple[ctypes.Array | None, int]:
	"""Encode a Python str to a ctypes byte buffer.

	Returns (buffer, length).  If the string is empty, returns (None, 0).
	"""
	if not s:
		return None, 0
	encoded = s.encode("utf-8")
	buf = (c_ubyte * len(encoded))(*encoded)
	return buf, len(encoded)


def _read_ffi_string(lib: ctypes.CDLL, ptr: Any, length: int) -> str:
	"""Read a UTF-8 string from an FFI pointer and free it.

	Args:
		lib: The loaded DLL handle.
		ptr: Pointer to the string bytes (POINTER(c_ubyte)).
		length: Length in bytes.

	Returns:
		The decoded Python string.
	"""
	if not ptr or length == 0:
		return ""
	try:
		result = ctypes.string_at(ptr, length).decode("utf-8")
	finally:
		lib.ta_free_string(ptr, c_size_t(length))
	return result


def _check_rc(rc: int, fn_name: str) -> None:
	"""Raise RuntimeError if a native function returned an error."""
	if rc != ERR_OK:
		messages = {
			ERR_NULL_POINTER: "null pointer",
			ERR_INVALID_UTF8: "invalid UTF-8",
			ERR_NOT_FOUND: "key not found",
			ERR_INVALID_REGEX: "invalid regex",
		}
		raise RuntimeError(f"{fn_name} failed: {messages.get(rc, f'error {rc}')}")


# ═══════════════════════════════════════════════════════════════
#  NativeTextDiffer
# ═══════════════════════════════════════════════════════════════

# DiffKind values from Rust (must match text_differ.rs enum)
_DIFF_KIND_MAP = {
	0: "initial",
	1: "unchanged",
	2: "appended",
	3: "changed",
	4: "last_line_updated",
}


class NativeTextDiffer:
	"""Drop-in replacement for :class:`TextDiffer` backed by Rust.

	Uses the same ``update()`` / ``reset()`` / ``last_text`` API so
	callers can swap implementations without changes.

	The underlying Rust TextDiffer is destroyed when this object is
	garbage-collected or when :meth:`close` is called.
	"""

	# Expose the same KIND_* constants for compatibility
	KIND_INITIAL = "initial"
	KIND_UNCHANGED = "unchanged"
	KIND_APPENDED = "appended"
	KIND_CHANGED = "changed"
	KIND_LAST_LINE_UPDATED = "last_line_updated"

	__slots__ = ("_handle", "_lib")

	def __init__(self) -> None:
		lib = _get_dll()
		if lib is None:
			raise RuntimeError("Native DLL not available")
		self._lib = lib
		self._handle = lib.ta_text_differ_new()
		if not self._handle:
			raise RuntimeError("ta_text_differ_new returned null")

	def update(self, current_text: str) -> tuple[str, str]:
		"""Compare *current_text* against the stored snapshot.

		Returns:
			tuple: ``(kind, new_content)`` where *kind* is one of the
			``KIND_*`` string constants.
		"""
		text_buf, text_len = _str_to_utf8(current_text)

		out_kind = c_uint32(0)
		out_ptr = POINTER(c_ubyte)()
		out_len = c_size_t(0)

		rc = self._lib.ta_text_differ_update(
			self._handle,
			text_buf,
			c_size_t(text_len),
			byref(out_kind),
			byref(out_ptr),
			byref(out_len),
		)
		_check_rc(rc, "ta_text_differ_update")

		kind_str = _DIFF_KIND_MAP.get(out_kind.value, "changed")
		content = _read_ffi_string(self._lib, out_ptr, out_len.value)
		return (kind_str, content)

	def reset(self) -> None:
		"""Discard the stored snapshot."""
		if self._handle:
			self._lib.ta_text_differ_reset(self._handle)

	@property
	def last_text(self) -> str | None:
		"""The last snapshot text, or ``None`` if no snapshot."""
		if not self._handle:
			return None

		out_ptr = POINTER(c_ubyte)()
		out_len = c_size_t(0)

		rc = self._lib.ta_text_differ_last_text(
			self._handle,
			byref(out_ptr),
			byref(out_len),
		)
		_check_rc(rc, "ta_text_differ_last_text")

		if not out_ptr or out_len.value == 0:
			return None
		return _read_ffi_string(self._lib, out_ptr, out_len.value)

	def close(self) -> None:
		"""Explicitly release the native handle."""
		if self._handle:
			self._lib.ta_text_differ_free(self._handle)
			self._handle = None

	def __del__(self) -> None:
		self.close()


# ANSI stripping and text search were removed from the native path: the
# FFI round-trip measured about 10x slower than Python's re/str, so both
# are done in Python now. The helper process still reads buffers off the
# main thread (read_text/read_lines); Python searches the result.


# ═══════════════════════════════════════════════════════════════
#  NativePositionCache
# ═══════════════════════════════════════════════════════════════

class NativePositionCache:
	"""Drop-in replacement for :class:`PositionCache` backed by Rust.

	Uses the same ``get()`` / ``set()`` / ``clear()`` / ``invalidate()``
	API.  The Rust implementation uses an LRU cache with timestamp-based
	expiration, matching the Python semantics.
	"""

	# Default values matching the Python PositionCache
	MAX_CACHE_SIZE = 100
	CACHE_TIMEOUT_MS = 1000  # 1 second, matches CACHE_TIMEOUT_S = 1.0

	__slots__ = ("_handle", "_lib")

	def __init__(
		self,
		max_size: int | None = None,
		timeout_ms: int | None = None,
	) -> None:
		lib = _get_dll()
		if lib is None:
			raise RuntimeError("Native DLL not available")
		self._lib = lib

		size = max_size if max_size is not None else self.MAX_CACHE_SIZE
		timeout = timeout_ms if timeout_ms is not None else self.CACHE_TIMEOUT_MS

		self._handle = lib.ta_position_cache_new(
			c_uint32(size), c_uint32(timeout)
		)
		if not self._handle:
			raise RuntimeError("ta_position_cache_new returned null")

	def get(self, bookmark: Any) -> tuple[int, int] | None:
		"""Retrieve cached ``(row, col)`` for *bookmark*, or ``None``."""
		if not self._handle:
			return None

		key = str(bookmark)
		key_buf, key_len = _str_to_utf8(key)

		out_row = c_int32(0)
		out_col = c_int32(0)

		rc = self._lib.ta_position_cache_get(
			self._handle,
			key_buf,
			c_size_t(key_len),
			byref(out_row),
			byref(out_col),
		)

		if rc == ERR_NOT_FOUND:
			return None
		_check_rc(rc, "ta_position_cache_get")

		return (out_row.value, out_col.value)

	def set(self, bookmark: Any, row: int, col: int) -> None:
		"""Store ``(row, col)`` for *bookmark*."""
		if not self._handle:
			return

		key = str(bookmark)
		key_buf, key_len = _str_to_utf8(key)

		self._lib.ta_position_cache_set(
			self._handle,
			key_buf,
			c_size_t(key_len),
			c_int32(row),
			c_int32(col),
		)

	def clear(self) -> None:
		"""Clear all cached positions."""
		if self._handle:
			self._lib.ta_position_cache_clear(self._handle)

	def invalidate(self, bookmark: Any) -> None:
		"""Remove a specific *bookmark* from the cache."""
		if not self._handle:
			return

		key = str(bookmark)
		key_buf, key_len = _str_to_utf8(key)

		self._lib.ta_position_cache_invalidate(
			self._handle,
			key_buf,
			c_size_t(key_len),
		)

	def close(self) -> None:
		"""Explicitly release the native handle."""
		if self._handle:
			self._lib.ta_position_cache_free(self._handle)
			self._handle = None

	def __del__(self) -> None:
		self.close()


# ═══════════════════════════════════════════════════════════════
#  Unicode Width
# ═══════════════════════════════════════════════════════════════

def native_text_width(text: str) -> int:
	"""Calculate total display width of a text string.

	Drop-in replacement for ``UnicodeWidthHelper.getTextWidth(text)``.
	"""
	lib = _get_dll()
	if lib is None:
		raise RuntimeError("Native DLL not available")

	text_buf, text_len = _str_to_utf8(text)
	result = lib.ta_text_width(text_buf, c_size_t(text_len))
	if result == 0xFFFFFFFF:  # u32::MAX = error
		raise RuntimeError("ta_text_width failed")
	return result




# ═══════════════════════════════════════════════════════════════
#  Fuzzy Search
# ═══════════════════════════════════════════════════════════════

# Default output buffer size for JSON results (256 KB).
_SEARCH_BUF_SIZE = 256 * 1024


def native_fuzzy_search(
	pattern: str,
	lines: list[str],
	max_distance: int = 1,
) -> list[dict]:
	"""Fuzzy search across lines using native Rust acceleration.

	Each line is stripped of ANSI codes, then each word is compared
	to *pattern* using Damerau-Levenshtein distance. A line matches
	if any word is within *max_distance* edits of the pattern
	(case-insensitive).

	Returns a list of dicts: ``[{"line": int, "text": str}, ...]``

	Raises RuntimeError if the native DLL is not available.
	"""
	import json

	lib = _get_dll()
	if lib is None:
		raise RuntimeError("Native DLL not available")

	pattern_buf, pattern_len = _str_to_utf8(pattern)
	lines_text = "\n".join(lines)
	lines_buf, lines_len = _str_to_utf8(lines_text)

	out_buf = (c_ubyte * _SEARCH_BUF_SIZE)()

	rc = lib.ta_fuzzy_search(
		pattern_buf,
		c_size_t(pattern_len),
		lines_buf,
		c_size_t(lines_len),
		c_uint32(max_distance),
		out_buf,
		c_size_t(_SEARCH_BUF_SIZE),
	)

	if rc < 0:
		if rc == -1:
			raise RuntimeError("ta_fuzzy_search: output buffer too small")
		if rc == -2:
			raise RuntimeError("ta_fuzzy_search: invalid UTF-8 input")
		raise RuntimeError(f"ta_fuzzy_search failed: error {rc}")

	if rc == 0:
		return []

	json_bytes = bytes(out_buf[:rc])
	return json.loads(json_bytes.decode("utf-8"))


def native_scoped_search(
	pattern: str,
	lines: list[str],
	start_line: int,
	end_line: int,
	case_sensitive: bool = False,
) -> list[dict]:
	"""Scoped substring search within a line range using native Rust.

	Searches lines from *start_line* to *end_line* (inclusive) for
	*pattern*. ANSI codes are stripped before matching.

	Returns a list of dicts: ``[{"line": int, "text": str}, ...]``

	Raises RuntimeError if the native DLL is not available.
	"""
	import json

	lib = _get_dll()
	if lib is None:
		raise RuntimeError("Native DLL not available")

	pattern_buf, pattern_len = _str_to_utf8(pattern)
	lines_text = "\n".join(lines)
	lines_buf, lines_len = _str_to_utf8(lines_text)

	out_buf = (c_ubyte * _SEARCH_BUF_SIZE)()

	rc = lib.ta_scoped_search(
		pattern_buf,
		c_size_t(pattern_len),
		lines_buf,
		c_size_t(lines_len),
		c_uint32(start_line),
		c_uint32(end_line),
		c_uint32(1 if case_sensitive else 0),
		out_buf,
		c_size_t(_SEARCH_BUF_SIZE),
	)

	if rc < 0:
		if rc == -1:
			raise RuntimeError("ta_scoped_search: output buffer too small")
		if rc == -2:
			raise RuntimeError("ta_scoped_search: invalid UTF-8 input")
		raise RuntimeError(f"ta_scoped_search failed: error {rc}")

	if rc == 0:
		return []

	json_bytes = bytes(out_buf[:rc])
	return json.loads(json_bytes.decode("utf-8"))


# ═══════════════════════════════════════════════════════════════
#  Helper process integration (Phase 2)
# ═══════════════════════════════════════════════════════════════

_helper_instance = None
_helper_lock = threading.Lock()
_helper_starting = False


def helper_available() -> bool:
	"""Return True if the helper process is running and ready."""
	h = _helper_instance
	return h is not None and h.is_running


def get_helper():
	"""Return the running helper, or None, without ever blocking the caller.

	Starting the helper involves a named-pipe handshake that can block, so
	this never starts it inline. If the helper is not yet created, it kicks
	off a background start and returns None immediately, so a caller on
	NVDA's main thread (for example the search command) is never frozen by
	helper startup. Once the background start completes, later calls return
	the running instance.

	Returns None while the helper is starting, unavailable, or restarting
	after a crash, so every caller falls back gracefully.
	"""
	if not _native_enabled:
		return None
	inst = _helper_instance
	if inst is not None:
		return inst if inst.is_running else None
	_ensure_helper_starting()
	return None


def _ensure_helper_starting():
	"""Kick off a one-shot background start of the helper if needed."""
	global _helper_starting
	if not _native_enabled:
		return
	with _helper_lock:
		if _helper_instance is not None or _helper_starting:
			return
		_helper_starting = True
	threading.Thread(
		target=_start_helper_worker, daemon=True, name="helper-start"
	).start()


def _start_helper_worker():
	"""Background worker that performs the blocking helper start."""
	global _helper_instance, _helper_starting
	try:
		from native.helper_process import HelperProcess
		helper = HelperProcess()
		if helper.start():
			with _helper_lock:
				_helper_instance = helper
	except Exception:
		log.debug("Failed to start helper process", exc_info=True)
	finally:
		with _helper_lock:
			_helper_starting = False


def start_helper_eagerly():
	"""Start the helper in the background so it's ready when first needed.

	Called from ``GlobalPlugin.__init__()`` so the helper is starting well
	before the first search. Never blocks: it only kicks off the background
	start. If the helper fails to start, that is not fatal; ``get_helper``
	retries on next use.
	"""
	try:
		_ensure_helper_starting()
	except Exception:
		pass  # not fatal — will retry on next use


def stop_helper():
	"""Stop the helper process if running."""
	global _helper_instance
	with _helper_lock:
		if _helper_instance is not None:
			try:
				_helper_instance.stop()
			except Exception:
				pass
			_helper_instance = None
