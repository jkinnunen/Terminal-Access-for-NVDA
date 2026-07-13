"""
Tests for Rust-accelerated fuzzy and scoped search.

Validates:
1. When native is available, Rust search is used
2. When native is unavailable, Python fallback works
3. Search results match between Rust and Python implementations
4. Scoped search boundaries match SectionTokenizer spans
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# The conftest.py already sets up addon_path in sys.path
# and mocks NVDA modules.


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _get_bridge_module():
	"""Import the bridge module."""
	from native import termaccess_bridge
	return termaccess_bridge


def _get_search_module():
	"""Import the search module."""
	from lib import search
	return search


# ---------------------------------------------------------------------------
#  Python fallback tests (always work, no DLL needed)
# ---------------------------------------------------------------------------

class TestPythonFuzzyFallback:
	"""Tests that verify the Python fuzzy search works as a fallback."""

	def test_levenshtein_kitten_sitting(self):
		"""Levenshtein distance kitten->sitting should be 3."""
		search_mod = _get_search_module()
		mgr = search_mod.OutputSearchManager.__new__(search_mod.OutputSearchManager)
		dist = mgr._levenshtein_distance("kitten", "sitting")
		assert dist == 3

	def test_levenshtein_identical(self):
		search_mod = _get_search_module()
		mgr = search_mod.OutputSearchManager.__new__(search_mod.OutputSearchManager)
		assert mgr._levenshtein_distance("hello", "hello") == 0

	def test_levenshtein_empty(self):
		search_mod = _get_search_module()
		mgr = search_mod.OutputSearchManager.__new__(search_mod.OutputSearchManager)
		assert mgr._levenshtein_distance("", "") == 0
		assert mgr._levenshtein_distance("abc", "") == 3
		assert mgr._levenshtein_distance("", "abc") == 3

	def test_fuzzy_search_basic(self):
		"""Python fuzzy_search finds lines with close word matches."""
		search_mod = _get_search_module()
		mgr = search_mod.OutputSearchManager.__new__(search_mod.OutputSearchManager)
		lines = ["there is an error here", "no match", "warning found"]
		results = mgr.fuzzy_search("error", lines)
		assert len(results) == 1
		assert "error" in results[0]

	def test_fuzzy_search_transposition(self):
		"""Python Damerau-Levenshtein catches transpositions."""
		search_mod = _get_search_module()
		mgr = search_mod.OutputSearchManager.__new__(search_mod.OutputSearchManager)
		# "erorr" is distance 1 from "error" via transposition
		lines = ["there is an erorr here"]
		# The fuzzy search uses distance <= 1
		results = mgr.fuzzy_search("error", lines)
		# "erorr" has letters e-r-o-r-r vs e-r-r-o-r: transposition of 'o' and 'r'
		# Damerau-Levenshtein distance is 1 (one transposition)
		# But "erorr" vs "error": e=e, r=r, o!=r, r!=o, r=r -> that is 2 substitutions
		# Actually "erorr" = e,r,o,r,r and "error" = e,r,r,o,r
		# Transposition of positions 2,3 (o,r -> r,o): DL distance = 1
		assert len(results) == 1

	def test_fuzzy_search_empty_pattern(self):
		search_mod = _get_search_module()
		mgr = search_mod.OutputSearchManager.__new__(search_mod.OutputSearchManager)
		results = mgr.fuzzy_search("", ["hello"])
		assert results == []

	def test_fuzzy_search_no_match(self):
		search_mod = _get_search_module()
		mgr = search_mod.OutputSearchManager.__new__(search_mod.OutputSearchManager)
		results = mgr.fuzzy_search("xyz", ["hello world"])
		assert results == []


# Native bridge wrapper and parity tests were removed along with the
# Rust layer; fuzzy search is Python-only.
