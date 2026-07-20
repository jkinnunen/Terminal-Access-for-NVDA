"""Read the legacy console's whole screen buffer, not just the viewport.

Users report that find is limited on older terminals, and the guide says
so. The cause is not our search: NVDA's WinConsole._getText returns
winConsoleHandler.getConsoleVisibleLines(), which reads only
srWindow.Top..srWindow.Bottom, the visible rectangle. Everything scrolled
off is invisible to NVDA, so it is invisible to us too.

The console itself still holds that text. GetConsoleScreenBufferInfo
reports dwSize, the FULL buffer, and ReadConsoleOutputCharacter can read
from row 0 rather than from the viewport top. Reading it ourselves is
what lifts the limitation, using the handle NVDA has already attached.
"""
from unittest.mock import MagicMock

import pytest


def _buffer_info(width, height, window_top=0, window_bottom=None):
    info = MagicMock()
    info.dwSize.x = width
    info.dwSize.y = height
    info.srWindow.Top = window_top
    info.srWindow.Bottom = height - 1 if window_bottom is None else window_bottom
    return info


@pytest.fixture
def console(monkeypatch):
    """An attached legacy console holding `rows` of fixed-width text."""
    import wincon
    import winConsoleHandler

    state = {}

    def setup(rows, width=10, handle=1234):
        winConsoleHandler.consoleOutputHandle = handle
        wincon.GetConsoleScreenBufferInfo = MagicMock(
            return_value=_buffer_info(width, len(rows)))
        padded = "".join(r.ljust(width)[:width] for r in rows)
        wincon.ReadConsoleOutputCharacter = MagicMock(return_value=padded)
        state["read"] = wincon.ReadConsoleOutputCharacter
        return state

    yield setup
    winConsoleHandler.consoleOutputHandle = None


class TestReadFullBuffer:
    def test_returns_every_row_including_scrollback(self, console):
        from lib.legacy_console import read_full_buffer_lines

        console(["first", "second", "third"])
        assert read_full_buffer_lines() == ["first", "second", "third"]

    def test_reads_from_row_zero_not_the_viewport(self, console):
        """The whole point: start at the top of the buffer, so scrolled
        off content is included."""
        from lib.legacy_console import read_full_buffer_lines

        state = console(["a", "b", "c"], width=4)
        read_full_buffer_lines()

        # ReadConsoleOutputCharacter(handle, length, x, y)
        args = state["read"].call_args.args
        assert args[1] == 4 * 3  # width * full buffer height
        assert args[2] == 0      # x
        assert args[3] == 0      # y: row zero, not srWindow.Top

    def test_trailing_blank_rows_are_dropped(self, console):
        """A console buffer is preallocated, so unused rows are spaces."""
        from lib.legacy_console import read_full_buffer_lines

        console(["hello", "", "", ""])
        assert read_full_buffer_lines() == ["hello"]

    def test_row_padding_is_stripped_but_content_kept(self, console):
        from lib.legacy_console import read_full_buffer_lines

        console(["ab", "cd"], width=8)
        assert read_full_buffer_lines() == ["ab", "cd"]

    def test_entirely_blank_buffer_returns_empty_list(self, console):
        from lib.legacy_console import read_full_buffer_lines

        console(["", ""])
        assert read_full_buffer_lines() == []


class TestSafety:
    def test_no_attached_console_returns_none(self):
        import winConsoleHandler
        from lib.legacy_console import read_full_buffer_lines

        winConsoleHandler.consoleOutputHandle = None
        assert read_full_buffer_lines() is None

    def test_api_failure_returns_none(self, console):
        import wincon
        from lib.legacy_console import read_full_buffer_lines

        console(["a"])
        wincon.ReadConsoleOutputCharacter = MagicMock(
            side_effect=OSError("handle closed"))
        assert read_full_buffer_lines() is None

    def test_absurd_buffer_is_capped(self, console):
        """Never let a pathological console size turn one read into an
        unbounded allocation."""
        import wincon
        from lib.legacy_console import MAX_CELLS, read_full_buffer_lines

        winConsoleHandler_height = (MAX_CELLS // 10) + 5000
        import winConsoleHandler
        winConsoleHandler.consoleOutputHandle = 1
        wincon.GetConsoleScreenBufferInfo = MagicMock(
            return_value=_buffer_info(10, winConsoleHandler_height))
        wincon.ReadConsoleOutputCharacter = MagicMock(return_value="x" * 100)

        read_full_buffer_lines()

        assert wincon.ReadConsoleOutputCharacter.call_args.args[1] <= MAX_CELLS

    def test_zero_sized_buffer_returns_none(self, console):
        import wincon
        from lib.legacy_console import read_full_buffer_lines

        console(["a"])
        wincon.GetConsoleScreenBufferInfo = MagicMock(
            return_value=_buffer_info(0, 0))
        assert read_full_buffer_lines() is None
