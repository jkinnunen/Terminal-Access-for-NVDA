"""Resolve a buffer position by codepoint offset instead of walking lines.

resolve_line_by_content walks UNIT_LINE from the top comparing text: O(n)
UIA calls per jump, and ambiguous whenever the same text appears twice
(the root of the beta.11 blank-row landing and the betas 8-14 jump
saga). TextInfo.moveToCodepointOffset converts a character offset
straight to a position: one call, no walking, no ambiguity.

It is used offset-first with verification, because our matching runs on
ANSI-stripped lines while the story text may still contain escape codes,
which shifts offsets. When the resolved line does not look like the line
we asked for, we fall back to the content walk rather than land wrong.
"""
from unittest.mock import MagicMock

import pytest

import textInfos


def _terminal(story_lines, ansi_shift=0):
    """A terminal whose moveToCodepointOffset lands on a line by offset."""
    term = MagicMock()

    def make(position):
        info = MagicMock()
        info._offset = 0

        def move_to(offset):
            landed = MagicMock()
            # Map the offset back to whichever line contains it.
            running = 0
            text = ""
            for line in story_lines:
                if running + len(line) >= offset - ansi_shift:
                    text = line
                    break
                running += len(line) + 1
            landed.text = text
            landed.expand = MagicMock()
            landed.copy = MagicMock(return_value=landed)
            return landed

        info.moveToCodepointOffset = MagicMock(side_effect=move_to)
        info.expand = MagicMock()
        info.copy = MagicMock(return_value=info)
        return info

    term.makeTextInfo = MagicMock(side_effect=make)
    return term


class TestResolveByOffset:
    def test_lands_on_the_line_containing_the_offset(self):
        from lib.line_resolve import resolve_by_codepoint_offset

        lines = ["first line", "second line", "third line"]
        # "second line" starts at offset 11 ("first line" + newline).
        term = _terminal(lines)

        info = resolve_by_codepoint_offset(term, 11, expected_text="second line")

        assert info is not None
        assert info.text == "second line"

    def test_verification_rejects_a_wrong_landing(self):
        """If the offset lands somewhere that does not match what we
        asked for (ANSI shifted the story), return None so the caller
        can fall back instead of landing on the wrong line."""
        from lib.line_resolve import resolve_by_codepoint_offset

        term = _terminal(["alpha", "beta", "gamma"])

        info = resolve_by_codepoint_offset(term, 0, expected_text="gamma")

        assert info is None

    def test_no_expected_text_skips_verification(self):
        from lib.line_resolve import resolve_by_codepoint_offset

        term = _terminal(["alpha", "beta"])

        info = resolve_by_codepoint_offset(term, 0)

        assert info is not None

    def test_expands_to_the_line(self):
        from lib.line_resolve import resolve_by_codepoint_offset

        term = _terminal(["alpha", "beta"])
        info = resolve_by_codepoint_offset(term, 0, expected_text="alpha")

        info.expand.assert_called_with(textInfos.UNIT_LINE)

    def test_none_terminal_is_safe(self):
        from lib.line_resolve import resolve_by_codepoint_offset
        assert resolve_by_codepoint_offset(None, 5) is None

    def test_negative_offset_is_rejected(self):
        from lib.line_resolve import resolve_by_codepoint_offset
        term = _terminal(["alpha"])
        assert resolve_by_codepoint_offset(term, -1) is None

    def test_missing_api_falls_back_to_none(self):
        """Older or unusual TextInfos may not implement it; never raise
        into a jump."""
        from lib.line_resolve import resolve_by_codepoint_offset

        term = MagicMock()
        info = MagicMock(spec=["expand", "copy"])
        term.makeTextInfo = MagicMock(return_value=info)

        assert resolve_by_codepoint_offset(term, 3) is None

    def test_raising_api_falls_back_to_none(self):
        from lib.line_resolve import resolve_by_codepoint_offset

        term = MagicMock()
        info = MagicMock()
        info.moveToCodepointOffset = MagicMock(
            side_effect=RuntimeError("bad offset"))
        term.makeTextInfo = MagicMock(return_value=info)

        assert resolve_by_codepoint_offset(term, 3) is None


class TestAbsoluteOffsets:
    """Search records where each match sits in the whole buffer."""

    def test_absolute_offset_accounts_for_preceding_lines(self):
        from lib.line_resolve import absolute_offset

        lines = ["abc", "de", "fghi"]
        # line 0 starts at 0; line 1 at 4 ("abc" + \n); line 2 at 7.
        assert absolute_offset(lines, 0, 0) == 0
        assert absolute_offset(lines, 1, 0) == 4
        assert absolute_offset(lines, 2, 0) == 7

    def test_within_line_offset_is_added(self):
        from lib.line_resolve import absolute_offset
        assert absolute_offset(["abc", "de"], 1, 1) == 5

    def test_out_of_range_line_returns_none(self):
        from lib.line_resolve import absolute_offset
        assert absolute_offset(["abc"], 5, 0) is None
