"""Performance-oriented behavior for OutputSearchManager.search().

These pin the optimizations that keep search responsive on a large
terminal buffer:

- The stripped/split buffer is cached across searches and reused until the
  plugin signals new output (note_content_changed).
- The ANSI strip is skipped entirely when the buffer has no escape bytes.
- search() can process a pre-acquired buffer (raw_text=...) so the caller
  can do the read on the main thread and the matching on a worker.
- Matching is bounded to the most recent MAX_SEARCH_LINES, with correct
  (absolute) line numbers, and the fuzzy fallback is skipped on very large
  buffers.
"""

from unittest.mock import Mock, patch

import textInfos

from lib.search import OutputSearchManager


class CountingTerminal:
    """Terminal stub that counts POSITION_ALL reads."""

    def __init__(self, text):
        self.text = text
        self.read_count = 0
        self.windowHandle = 0  # falsy: helper fast-path is skipped

    def makeTextInfo(self, pos):
        info = Mock()
        if pos == textInfos.POSITION_ALL:
            self.read_count += 1
            info.text = self.text
        else:
            info.text = ""
        return info


# ---------------------------------------------------------------------------
# #1 Buffer caching
# ---------------------------------------------------------------------------

class TestBufferCache:
    def test_repeat_search_reuses_cached_buffer(self):
        terminal = CountingTerminal("alpha\nbeta\nerror here\ngamma")
        mgr = OutputSearchManager(terminal)

        assert mgr.search("error") == 1
        assert mgr.search("beta") == 1
        # Second search reused the cached lines: only one buffer read.
        assert terminal.read_count == 1

    def test_note_content_changed_invalidates_cache(self):
        terminal = CountingTerminal("alpha\nerror here")
        mgr = OutputSearchManager(terminal)

        mgr.search("error")
        mgr.note_content_changed()
        mgr.search("alpha")
        assert terminal.read_count == 2

    def test_update_terminal_invalidates_cache(self):
        terminal = CountingTerminal("one\ntwo")
        mgr = OutputSearchManager(terminal)
        mgr.search("one")
        mgr.update_terminal(terminal)
        mgr.search("two")
        assert terminal.read_count == 2


# ---------------------------------------------------------------------------
# #4 Skip ANSI strip when there is nothing to strip
# ---------------------------------------------------------------------------

class TestAnsiStripSkip:
    def test_strip_skipped_when_no_escape_bytes(self):
        terminal = CountingTerminal("plain text\nno escapes here")
        mgr = OutputSearchManager(terminal)
        with patch("lib.search._rt.strip_ansi", side_effect=lambda t: t) as spy:
            mgr.search("plain")
            spy.assert_not_called()

    def test_strip_runs_when_escape_present(self):
        terminal = CountingTerminal("\x1b[31mred\x1b[0m text")
        mgr = OutputSearchManager(terminal)
        with patch("lib.search._rt.strip_ansi", side_effect=lambda t: t) as spy:
            mgr.search("red")
            spy.assert_called_once()


# ---------------------------------------------------------------------------
# #2 Process a pre-acquired buffer off the caller's thread
# ---------------------------------------------------------------------------

class TestRawTextInjection:
    def test_search_with_raw_text_skips_terminal_read(self):
        terminal = CountingTerminal("SHOULD NOT BE READ")
        mgr = OutputSearchManager(terminal)
        count = mgr.search("needle", raw_text="a needle in here\nother")
        assert count == 1
        assert terminal.read_count == 0

    def test_acquire_raw_text_reads_buffer(self):
        terminal = CountingTerminal("hello world")
        mgr = OutputSearchManager(terminal)
        assert mgr._acquire_raw_text() == "hello world"
        assert terminal.read_count == 1

    def test_acquire_never_uses_helper(self):
        """The helper process is retired from the search read path: even
        with native available and a live helper, reads go in-process."""
        from lib import search as search_mod
        terminal = CountingTerminal("in-process text")
        terminal.windowHandle = 0x1234
        mgr = OutputSearchManager(terminal)

        helper = Mock()
        helper.is_running = True
        helper.read_text = Mock(return_value="HELPER TEXT (must not be used)")
        with patch.object(search_mod._rt, "native_available", True), \
                patch.object(search_mod._rt, "get_helper",
                             Mock(return_value=helper), create=True):
            assert mgr._acquire_raw_text() == "in-process text"
        helper.read_text.assert_not_called()


# ---------------------------------------------------------------------------
# #3 Bound the scan to the most recent lines (line numbers stay absolute)
# ---------------------------------------------------------------------------

class TestScanBounding:
    def test_old_lines_beyond_cap_not_searched(self):
        mgr = OutputSearchManager(CountingTerminal(""))
        mgr.MAX_SEARCH_LINES = 3
        # 6 lines; only the last 3 are in scope.
        lines = ["needle old", "x", "x", "y", "y", "needle new"]
        count = mgr.search("needle", raw_text="\n".join(lines))
        assert count == 1
        state = mgr._get_search_state()
        # The single match is the recent one: absolute line number 6.
        assert state["matches"][0][2] == 6

    def test_bounding_reported(self):
        mgr = OutputSearchManager(CountingTerminal(""))
        mgr.MAX_SEARCH_LINES = 3
        mgr.search("nomatch", raw_text="\n".join(["l"] * 10))
        assert "recent" in mgr.get_last_search_message().lower()

    def test_no_bounding_when_under_cap(self):
        mgr = OutputSearchManager(CountingTerminal(""))
        mgr.MAX_SEARCH_LINES = 100
        count = mgr.search("hit", raw_text="a\nhit\nb")
        assert count == 1
        assert state_line(mgr, 0) == 2


def state_line(mgr, idx):
    return mgr._get_search_state()["matches"][idx][2]


# ---------------------------------------------------------------------------
# #4 Fuzzy fallback skipped on very large buffers
# ---------------------------------------------------------------------------

class TestFuzzyGating:
    def test_fuzzy_skipped_on_large_buffer(self):
        mgr = OutputSearchManager(CountingTerminal(""))
        mgr.FUZZY_MAX_LINES = 3
        # "erro" is fuzzy-close to "error" but the buffer is too large to
        # justify the fuzzy scan, so no matches are returned.
        raw = "\n".join(["an erro here"] + ["x"] * 10)
        assert mgr.search("error", raw_text=raw) == 0

    def test_fuzzy_runs_on_small_buffer(self):
        mgr = OutputSearchManager(CountingTerminal(""))
        mgr.FUZZY_MAX_LINES = 100
        assert mgr.search("error", raw_text="an erro here") == 1


# ---------------------------------------------------------------------------
# #2 Plugin-level: read on main thread, match off-thread for big buffers
# ---------------------------------------------------------------------------

class TestRunTerminalSearch:
    def _plugin(self, raw_text, count):
        from globalPlugins.terminalAccess import GlobalPlugin
        plugin = GlobalPlugin.__new__(GlobalPlugin)
        mgr = Mock()
        mgr._acquire_raw_text = Mock(return_value=raw_text)
        mgr.search = Mock(return_value=count)
        plugin._searchManager = mgr
        return plugin, mgr

    def test_small_buffer_runs_synchronously(self):
        plugin, mgr = self._plugin("short buffer", 3)
        results = []
        plugin._runTerminalSearch("err", lambda text, n: results.append((text, n)))
        # Ran inline on this thread with the pre-read buffer.
        assert results == [("err", 3)]
        assert mgr.search.call_args.kwargs.get("raw_text") == "short buffer"

    def test_large_buffer_runs_on_worker_thread(self):
        import threading
        import globalPlugins.terminalAccess as ta
        plugin, mgr = self._plugin("x" * 500_000, 7)
        done = threading.Event()
        results = []

        def on_complete(text, n):
            results.append((text, n))
            done.set()

        # Make the mocked wx.CallAfter invoke inline so the worker's result
        # is delivered deterministically.
        with patch.object(ta.ui, "message"), \
                patch("wx.CallAfter", side_effect=lambda fn, *a, **k: fn(*a, **k)):
            plugin._runTerminalSearch("err", on_complete)
            assert done.wait(timeout=5.0)
        assert results == [("err", 7)]
        assert mgr.search.call_args.kwargs.get("raw_text") == "x" * 500_000
