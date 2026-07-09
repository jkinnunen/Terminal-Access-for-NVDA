# Terminal Access for NVDA - Native Bridge Parity Tests
# Copyright (C) 2024 Pratik Patel
# This add-on is covered by the GNU General Public License, version 3.
# See the file LICENSE for more details.

"""
Parity tests for the native Rust bridge.

These tests verify that the Rust implementations (via ctypes) produce
identical results to the pure-Python implementations for all inputs.
Tests are skipped when the native DLL is not available.
"""

import os
import re
import sys
import time
import unittest

# Ensure addon/ is on sys.path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))

# Import Python implementations
from globalPlugins.terminalAccess import TextDiffer, PositionCache, ANSIParser

# Try to import native implementations
try:
	from native.termaccess_bridge import (
		native_available,
		NativeTextDiffer,
		NativePositionCache,
		native_text_width,
	)
	_HAS_NATIVE = native_available()
except Exception:
	_HAS_NATIVE = False

_skip_msg = "Native DLL not available"


@unittest.skipUnless(_HAS_NATIVE, _skip_msg)
class TestTextDifferParity(unittest.TestCase):
	"""Verify that NativeTextDiffer produces identical results to TextDiffer."""

	def _run_parity(self, updates):
		"""Run the same sequence of updates through both and compare results."""
		py = TextDiffer()
		native = NativeTextDiffer()

		for i, text in enumerate(updates):
			py_result = py.update(text)
			native_result = native.update(text)
			self.assertEqual(
				py_result,
				native_result,
				f"Mismatch at update {i} for text={text!r}: "
				f"python={py_result}, native={native_result}",
			)

	def test_initial(self):
		self._run_parity(["hello world"])

	def test_unchanged(self):
		self._run_parity(["hello", "hello"])

	def test_appended(self):
		self._run_parity(["line1\n", "line1\nline2\n"])

	def test_changed(self):
		self._run_parity(["hello", "goodbye"])

	def test_last_line_updated(self):
		self._run_parity([
			"line1\nline2\nprogress: 50%",
			"line1\nline2\nprogress: 75%",
		])

	def test_empty_text(self):
		self._run_parity(["", ""])

	def test_trailing_spaces_normalized(self):
		"""conhost pads lines with trailing spaces."""
		self._run_parity([
			"hello   \nworld   \n",
			"hello\nworld\n",
		])

	def test_unicode(self):
		self._run_parity([
			"hello 世界\n",
			"hello 世界\nnew line\n",
		])

	def test_multiple_appends(self):
		self._run_parity([
			"a\n",
			"a\nb\n",
			"a\nb\nc\n",
			"a\nb\nc\nd\n",
		])

	def test_mixed_operations(self):
		self._run_parity([
			"initial\n",
			"initial\nappended\n",
			"initial\nappended\n",  # unchanged
			"completely different\n",  # changed
			"completely different\nmore stuff\n",  # appended
		])

	def test_reset(self):
		py = TextDiffer()
		native = NativeTextDiffer()

		py.update("hello")
		native.update("hello")

		py.reset()
		native.reset()

		self.assertEqual(py.update("world"), native.update("world"))

	def test_last_text(self):
		py = TextDiffer()
		native = NativeTextDiffer()

		self.assertIsNone(py.last_text)
		self.assertIsNone(native.last_text)

		py.update("hello")
		native.update("hello")

		self.assertEqual(py.last_text, native.last_text)

	def test_large_text(self):
		"""Test with realistic terminal output size."""
		base = "\n".join(f"line {i}: some content here" for i in range(500)) + "\n"
		appended = base + "new output line\n"
		self._run_parity([base, appended])

	def test_progress_bar_simulation(self):
		"""Simulate a progress bar updating the last line."""
		lines = "Building project...\n"
		updates = [lines + f"Progress: [{('=' * i):50s}] {i*2}%" for i in range(51)]
		self._run_parity(updates)


@unittest.skipUnless(_HAS_NATIVE, _skip_msg)
class TestPositionCacheParity(unittest.TestCase):
	"""Verify NativePositionCache matches PositionCache behavior."""

	def test_get_set(self):
		py = PositionCache()
		native = NativePositionCache()

		py.set("bm1", 10, 20)
		native.set("bm1", 10, 20)

		self.assertEqual(py.get("bm1"), native.get("bm1"))

	def test_get_miss(self):
		py = PositionCache()
		native = NativePositionCache()

		self.assertEqual(py.get("missing"), native.get("missing"))
		self.assertIsNone(native.get("missing"))

	def test_clear(self):
		py = PositionCache()
		native = NativePositionCache()

		py.set("bm1", 1, 2)
		native.set("bm1", 1, 2)

		py.clear()
		native.clear()

		self.assertEqual(py.get("bm1"), native.get("bm1"))
		self.assertIsNone(native.get("bm1"))

	def test_invalidate(self):
		py = PositionCache()
		native = NativePositionCache()

		py.set("bm1", 1, 2)
		native.set("bm1", 1, 2)

		py.invalidate("bm1")
		native.invalidate("bm1")

		self.assertEqual(py.get("bm1"), native.get("bm1"))
		self.assertIsNone(native.get("bm1"))

	def test_update_existing(self):
		py = PositionCache()
		native = NativePositionCache()

		py.set("bm1", 1, 2)
		native.set("bm1", 1, 2)

		py.set("bm1", 3, 4)
		native.set("bm1", 3, 4)

		self.assertEqual(py.get("bm1"), native.get("bm1"))
		self.assertEqual(native.get("bm1"), (3, 4))

	def test_expiration(self):
		"""Entries expire after timeout."""
		# Use a very short timeout for testing
		native = NativePositionCache(max_size=100, timeout_ms=50)

		native.set("bm1", 1, 2)
		self.assertEqual(native.get("bm1"), (1, 2))

		# Wait for expiration
		time.sleep(0.1)
		self.assertIsNone(native.get("bm1"))

	def test_multiple_keys(self):
		py = PositionCache()
		native = NativePositionCache()

		for i in range(50):
			key = f"bookmark_{i}"
			py.set(key, i, i * 10)
			native.set(key, i, i * 10)

		for i in range(50):
			key = f"bookmark_{i}"
			self.assertEqual(py.get(key), native.get(key))

	def test_negative_coordinates(self):
		"""Position coordinates can be negative in some edge cases."""
		native = NativePositionCache()
		native.set("bm1", -1, -5)
		self.assertEqual(native.get("bm1"), (-1, -5))


@unittest.skipUnless(_HAS_NATIVE, _skip_msg)
class TestNativeResourceCleanup(unittest.TestCase):
	"""Verify that native handles are properly cleaned up."""

	def test_text_differ_close(self):
		d = NativeTextDiffer()
		d.update("test")
		d.close()
		# After close, operations should not crash
		# (handle is None, methods should handle gracefully)

	def test_position_cache_close(self):
		c = NativePositionCache()
		c.set("key", 1, 2)
		c.close()

	def test_many_allocations(self):
		"""Create and destroy many objects to check for leaks."""
		for _ in range(100):
			d = NativeTextDiffer()
			d.update("some text here\n")
			d.update("some text here\nmore output\n")
			d.close()

		for _ in range(100):
			c = NativePositionCache()
			for j in range(20):
				c.set(f"key_{j}", j, j)
			c.close()


@unittest.skipUnless(_HAS_NATIVE, _skip_msg)
class TestUnicodeWidth(unittest.TestCase):
	"""Tests for native unicode width functions."""

	def test_native_text_width_ascii(self):
		"""Pure ASCII text width equals length."""
		result = native_text_width("Hello")
		self.assertEqual(result, 5)

	def test_native_text_width_cjk(self):
		"""Mixed ASCII and CJK text."""
		result = native_text_width("Hello\u4e16\u754c")
		self.assertEqual(result, 9)  # 5 + 2*2

	def test_native_text_width_empty(self):
		"""Empty text width is 0."""
		result = native_text_width("")
		self.assertEqual(result, 0)


if __name__ == "__main__":
	unittest.main()
