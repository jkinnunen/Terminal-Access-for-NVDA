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


class TestSearchStatePerWindow:
    """The active search is keyed on the window handle, so it survives a
    refocus (a new NVDAObject for the same window) and is restored when you
    switch to another window and back. update_terminal runs on every focus,
    including the focus return after the search results dialog closes."""

    def test_same_window_keeps_matches(self):
        terminal = CountingTerminal("alpha\nerror here\nbeta")
        terminal.windowHandle = 0x42
        mgr = OutputSearchManager(terminal)
        assert mgr.search("error") == 1

        rebound = CountingTerminal("alpha\nerror here\nbeta")
        rebound.windowHandle = 0x42  # same window, new NVDAObject
        mgr.update_terminal(rebound)

        assert mgr.get_match_count() == 1
        assert mgr._terminal is rebound

    def test_other_window_has_its_own_search(self):
        terminal = CountingTerminal("error here")
        terminal.windowHandle = 0x42
        mgr = OutputSearchManager(terminal)
        assert mgr.search("error") == 1

        other = CountingTerminal("different buffer")
        other.windowHandle = 0x99
        mgr.update_terminal(other)
        # The other window has no search of its own yet.
        assert mgr.get_match_count() == 0

    def test_search_restored_when_returning_to_a_window(self):
        win_a = CountingTerminal("alpha\nerror here\nbeta")
        win_a.windowHandle = 0xAA
        mgr = OutputSearchManager(win_a)
        assert mgr.search("error") == 1

        win_b = CountingTerminal("no matches here")
        win_b.windowHandle = 0xBB
        mgr.update_terminal(win_b)
        assert mgr.get_match_count() == 0

        back = CountingTerminal("alpha\nerror here\nbeta")
        back.windowHandle = 0xAA  # same window as win_a
        mgr.update_terminal(back)
        # win_a's search is restored.
        assert mgr.get_match_count() == 1

    def test_no_handle_uses_shared_slot(self):
        terminal = CountingTerminal("error here")
        terminal.windowHandle = None
        mgr = OutputSearchManager(terminal)
        assert mgr.search("error") == 1
        # A rebind to another handle-less terminal shares the None slot.
        other = CountingTerminal("error here")
        other.windowHandle = None
        mgr.update_terminal(other)
        assert mgr.get_match_count() == 1


class TestSearchSurvivesTabIdChurn:
    """The active search must survive a terminal focus event even with a tab
    manager present. The tab id is a hash of the window title and the NVDA
    object id, both of which change on refocus, so keying search state on it
    orphaned the results and findNext/findPrevious reported no matches. The
    active search is now instance-scoped, cleared only on a real window
    change. (This is the tab-manager path the earlier same-window test did
    not cover.)"""

    class ChurningTabManager:
        """Tab manager whose id changes between calls, as the real one does
        when the title or the focused NVDAObject changes."""
        def __init__(self, tab_id="tabA"):
            self._id = tab_id

        def get_current_tab_id(self):
            return self._id

        def update_terminal(self, obj):
            pass

    def test_matches_survive_refocus_when_tab_id_changes(self):
        terminal = CountingTerminal("alpha\nerror here\nbeta")
        terminal.windowHandle = 0x42
        tabmgr = self.ChurningTabManager("tabA")
        mgr = OutputSearchManager(terminal, tab_manager=tabmgr)
        assert mgr.search("error") == 1

        # Refocus: same window, but a new object and title churn the tab id.
        tabmgr._id = "tabB"
        rebound = CountingTerminal("alpha\nerror here\nbeta")
        rebound.windowHandle = 0x42
        mgr.update_terminal(rebound)

        # findNext/findPrevious read this; it must still see the match.
        assert mgr.get_match_count() == 1
        info = mgr.get_current_match_info()
        assert info is None or info[1] == 1  # total count is 1 if index set

    def test_state_not_split_across_tab_ids(self):
        """Saving under one id and reading under another must see the same
        active search (no per-tab dict to split it)."""
        terminal = CountingTerminal("x\nneedle\ny")
        terminal.windowHandle = 0x7
        tabmgr = self.ChurningTabManager("t1")
        mgr = OutputSearchManager(terminal, tab_manager=tabmgr)
        assert mgr.search("needle") == 1
        tabmgr._id = "t2"
        assert mgr.get_match_count() == 1


class TestRefreshStaleSearch:
    """Search results are a snapshot; refresh_search_if_stale re-runs the
    search when the buffer changed so find next/previous reflect the live
    buffer."""

    def test_refresh_picks_up_new_matches(self):
        terminal = CountingTerminal("error one")
        terminal.windowHandle = 0x1
        mgr = OutputSearchManager(terminal)
        assert mgr.search("error") == 1

        terminal.text = "error one\nnoise\nerror two"
        mgr.note_content_changed()
        assert mgr.refresh_search_if_stale() is True
        assert mgr.get_match_count() == 2

    def test_no_refresh_when_not_stale(self):
        terminal = CountingTerminal("error one")
        mgr = OutputSearchManager(terminal)
        mgr.search("error")
        assert mgr.refresh_search_if_stale() is False

    def test_no_refresh_without_active_search(self):
        terminal = CountingTerminal("hello")
        mgr = OutputSearchManager(terminal)
        mgr.note_content_changed()
        assert mgr.refresh_search_if_stale() is False

    def test_refresh_preserves_position_by_text(self):
        terminal = CountingTerminal("alpha error\nbeta error")
        terminal.windowHandle = 0x2
        mgr = OutputSearchManager(terminal)
        assert mgr.search("error") == 2
        # Point at the second match.
        st = mgr._get_search_state()
        st["current_match_index"] = 1
        mgr._save_search_state(st)
        assert mgr.get_current_match_info()[2] == "beta error"

        # New output prepends a line: line numbers shift, text persists.
        terminal.text = "new top line\nalpha error\nbeta error"
        mgr.note_content_changed()
        assert mgr.refresh_search_if_stale() is True
        assert mgr.get_current_match_info()[2] == "beta error"


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

    def test_acquire_uses_only_maketextinfo(self):
        """The native helper was deleted: the read path is makeTextInfo,
        and the runtime registry no longer exposes helper hooks."""
        from lib import _runtime as rt
        assert not hasattr(rt, "get_helper")
        assert not hasattr(rt, "native_available")

        terminal = CountingTerminal("in-process text")
        terminal.windowHandle = 0x1234
        mgr = OutputSearchManager(terminal)
        assert mgr._acquire_raw_text() == "in-process text"
        assert terminal.read_count == 1


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

    def test_large_plain_text_buffer_runs_synchronously(self):
        """Threading cannot make a search faster, and a plain substring
        scan over a real buffer takes milliseconds, so the worker is not
        worth its concurrency. Only regex keeps it (see below)."""
        plugin, mgr = self._plugin("e" * 500_000, 2)
        results = []

        with patch("threading.Thread") as thread_cls:
            plugin._runTerminalSearch(
                "err", lambda t, n: results.append((t, n)), use_regex=False)

        thread_cls.assert_not_called()
        assert results == [("err", 2)]

    def test_large_regex_buffer_still_uses_a_worker(self):
        """A user-supplied pattern can backtrack catastrophically, e.g.
        (a+)+b, and would otherwise freeze NVDA's main thread."""
        plugin, mgr = self._plugin("a" * 500_000, 1)

        with patch("threading.Thread") as thread_cls:
            plugin._runTerminalSearch(
                "(a+)+b", lambda t, n: None, use_regex=True)

        thread_cls.assert_called_once()
        assert thread_cls.call_args.kwargs.get("daemon") is True

    def test_options_passed_to_search(self):
        plugin, mgr = self._plugin("short buffer", 1)
        plugin._runTerminalSearch("Err", lambda t, n: None,
                                  case_sensitive=True, use_regex=False)
        kwargs = mgr.search.call_args.kwargs
        assert kwargs.get("case_sensitive") is True
        assert kwargs.get("use_regex") is False

    def test_invalid_regex_announced_and_not_searched(self):
        import globalPlugins.terminalAccess as ta
        plugin, mgr = self._plugin("short buffer", 0)
        plugin._searchDialogOpen = True
        called = []
        with patch.object(ta.ui, "message") as mock_msg:
            plugin._runTerminalSearch("[bad(", lambda t, n: called.append(n),
                                      use_regex=True)
        # Announced the error, never ran the search, never completed.
        assert mock_msg.called
        assert "regular expression" in mock_msg.call_args[0][0].lower()
        mgr.search.assert_not_called()
        assert called == []
        assert plugin._searchDialogOpen is False

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
