"""Unicode width without wcwidth or the native DLL.

NVDA's bundled Python has neither wcwidth nor the Rust DLL on every
machine (and the native layer is being retired). The stdlib
unicodedata-based fallback must keep table-mode column math correct:
CJK/fullwidth characters are 2 columns, combining marks are 0, control
characters are 0, everything else is 1.
"""

from unittest.mock import patch

import pytest

from lib import text_processing
from lib.text_processing import UnicodeWidthHelper


@pytest.fixture
def no_wcwidth():
    """Force the pure-stdlib width path (no wcwidth, no native)."""
    with patch.object(text_processing, "_wcwidth", None), \
            patch.object(text_processing, "_HAS_NATIVE_WIDTH", False, create=True):
        yield


class TestStdlibWidthFallback:
    def test_ascii_is_one(self, no_wcwidth):
        assert UnicodeWidthHelper.getCharWidth("a") == 1
        assert UnicodeWidthHelper.getCharWidth(" ") == 1

    def test_cjk_is_two(self, no_wcwidth):
        assert UnicodeWidthHelper.getCharWidth("中") == 2  # 中
        assert UnicodeWidthHelper.getCharWidth("ア") == 2  # ア
        assert UnicodeWidthHelper.getCharWidth("Ａ") == 2  # Ａ fullwidth

    def test_combining_is_zero(self, no_wcwidth):
        assert UnicodeWidthHelper.getCharWidth("́") == 0  # combining acute

    def test_control_is_zero(self, no_wcwidth):
        assert UnicodeWidthHelper.getCharWidth("\x07") == 0
        assert UnicodeWidthHelper.getCharWidth("\x1b") == 0
        assert UnicodeWidthHelper.getCharWidth("\x7f") == 0

    def test_text_width_mixed(self, no_wcwidth):
        # "ab中" = 1 + 1 + 2
        assert UnicodeWidthHelper.getTextWidth("ab中") == 4

    def test_column_extraction_with_cjk(self, no_wcwidth):
        # "中中ab": columns 1-2 = 中, 3-4 = 中, 5 = a, 6 = b
        assert UnicodeWidthHelper.extractColumnRange("中中ab", 5, 6) == "ab"

    def test_find_column_position_with_cjk(self, no_wcwidth):
        # Column 5 is index 2 (after two 2-wide chars).
        assert UnicodeWidthHelper.findColumnPosition("中中ab", 5) == 2
