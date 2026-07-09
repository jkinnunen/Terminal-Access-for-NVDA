"""
Tests for safety and IPC validation hardening.

Covers:
1. Input validation for search and regex
2. URL safety
3. Named pipe JSON hardening
4. Native fallback reliability
"""
import json
import re
import struct
import time
import logging
from unittest.mock import Mock, MagicMock, patch

import pytest


# ================================================================
#  1. Search input validation
# ================================================================


class TestSearchPatternMaxLength:
    """test_search_pattern_max_length: pattern > 500 chars rejected."""

    def test_search_rejects_pattern_over_500_chars(self):
        from lib.search import OutputSearchManager

        terminal = Mock()
        # Provide a terminal with matching text so we know it returns 0
        # specifically because the pattern is too long, not because of
        # a missing terminal or empty buffer.
        terminal.makeTextInfo.return_value = Mock(text="a" * 600)
        mgr = OutputSearchManager(terminal)
        long_pattern = "a" * 501
        with pytest.raises(ValueError, match="too long"):
            mgr.search(long_pattern)

    def test_search_accepts_pattern_at_500_chars(self):
        from lib.search import OutputSearchManager

        terminal = Mock()
        terminal.makeTextInfo.return_value = Mock(text="a" * 500 + "\nother line")
        mgr = OutputSearchManager(terminal)
        pattern = "a" * 500
        result = mgr.search(pattern)
        # Should not be rejected for length
        assert result >= 0


class TestSearchMaxMatches:
    """test_search_max_matches: returns at most 1000 matches."""

    def test_search_caps_matches_at_1000(self):
        from lib.search import OutputSearchManager

        terminal = Mock()
        # Create text with 2000 lines each containing "error"
        lines = ["error on this line"] * 2000
        terminal.makeTextInfo.return_value = Mock(text="\n".join(lines))
        mgr = OutputSearchManager(terminal)
        result = mgr.search("error")
        assert result <= 1000


class TestSearchInvalidRegex:
    """test_search_invalid_regex: bad regex returns error, not crash."""

    def test_search_invalid_regex_raises_value_error(self):
        from lib.search import OutputSearchManager

        terminal = Mock()
        mgr = OutputSearchManager(terminal)
        with pytest.raises(ValueError, match="Invalid regular expression"):
            mgr.search("[invalid(", use_regex=True)

    def test_search_invalid_regex_no_crash(self):
        from lib.search import OutputSearchManager

        terminal = Mock()
        mgr = OutputSearchManager(terminal)
        # Should raise ValueError, not re.error or anything else
        try:
            mgr.search("(unclosed", use_regex=True)
        except ValueError:
            pass  # expected
        except Exception as e:
            pytest.fail(f"Unexpected exception type: {type(e).__name__}: {e}")


class TestSearchLineLengthCap:
    """test_search_line_length_cap: lines > 10000 chars truncated."""

    def test_long_lines_truncated_in_match_results(self):
        from lib.search import OutputSearchManager

        terminal = Mock()
        long_line = "x" * 15000
        terminal.makeTextInfo.return_value = Mock(text=long_line)
        mgr = OutputSearchManager(terminal)
        result = mgr.search("x")
        assert result >= 1
        # Check that stored match line_text is capped
        state = mgr._get_search_state()
        for match in state['matches']:
            line_text = match[1]  # line_text is at index 1
            assert len(line_text) <= 10000


# ================================================================
#  2. URL safety
# ================================================================


class TestUrlSafeHttp:
    """test_url_safe_http: http:// URLs are safe."""

    def test_http_url_is_safe(self):
        from lib.search import UrlExtractorManager

        mgr = UrlExtractorManager(Mock())
        assert mgr._is_safe_url("http://example.com") is True


class TestUrlSafeHttps:
    """test_url_safe_https: https:// URLs are safe."""

    def test_https_url_is_safe(self):
        from lib.search import UrlExtractorManager

        mgr = UrlExtractorManager(Mock())
        assert mgr._is_safe_url("https://example.com") is True


class TestUrlUnsafeFile:
    """test_url_unsafe_file: file:// URLs blocked."""

    def test_file_url_blocked(self):
        from lib.search import UrlExtractorManager

        mgr = UrlExtractorManager(Mock())
        assert mgr._is_safe_url("file:///etc/passwd") is False

    def test_file_url_case_insensitive(self):
        from lib.search import UrlExtractorManager

        mgr = UrlExtractorManager(Mock())
        assert mgr._is_safe_url("FILE:///C:/Windows/System32") is False


class TestUrlUnsafeJavascript:
    """test_url_unsafe_javascript: javascript: URLs blocked."""

    def test_javascript_url_blocked(self):
        from lib.search import UrlExtractorManager

        mgr = UrlExtractorManager(Mock())
        assert mgr._is_safe_url("javascript:alert(1)") is False


class TestUrlUnsafeData:
    """test_url_unsafe_data: data: URLs blocked."""

    def test_data_url_blocked(self):
        from lib.search import UrlExtractorManager

        mgr = UrlExtractorManager(Mock())
        assert mgr._is_safe_url("data:text/html,<h1>hi</h1>") is False


class TestUrlWarningSettingExists:
    """test_url_warning_setting_exists: confspec has urlOpenWarning."""

    def test_confspec_has_url_open_warning(self):
        from lib.config import confspec

        assert "urlOpenWarning" in confspec
        # Should default to True
        assert "default=True" in confspec["urlOpenWarning"]


# ================================================================
#  3. Named pipe JSON hardening
# ================================================================


class TestHelperPayloadMaxSize:
    """test_helper_payload_max_size: >1MB payload rejected."""

    def test_oversized_payload_rejected(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        # Simulate reading a message with payload > 1MB
        # The _read_message method should reject it
        oversized_length = 2 * 1024 * 1024  # 2MB
        header = struct.pack("<I", oversized_length)

        with patch.object(hp, '_read_exact', side_effect=[header]):
            result = hp._read_message()
            assert result is None


class TestHelperMalformedJson:
    """test_helper_malformed_json: bad JSON handled gracefully."""

    def test_malformed_json_returns_none(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        # Valid length header but invalid JSON payload
        bad_payload = b"not valid json{{"
        header = struct.pack("<I", len(bad_payload))

        with patch.object(hp, '_read_exact', side_effect=[header, bad_payload]):
            result = hp._read_message()
            assert result is None


class TestHelperBackoffIncreases:
    """test_helper_backoff_increases: restart delay doubles each time."""

    def test_backoff_doubles(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        # Check that _get_restart_delay returns exponentially increasing values
        assert hp._get_restart_delay(0) == 1.0
        assert hp._get_restart_delay(1) == 2.0
        assert hp._get_restart_delay(2) == 4.0
        assert hp._get_restart_delay(3) == 8.0

    def test_backoff_capped_at_30(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        # After many restarts, delay should not exceed 30 seconds
        assert hp._get_restart_delay(10) <= 30.0


class TestHelperMaxRestartAttempts:
    """test_helper_max_restart_attempts: stops after 5 attempts in 60s."""

    def test_max_restart_attempts_is_5(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        assert hp._MAX_RESTART_ATTEMPTS == 5

    def test_restart_window_is_60s(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        assert hp._RESTART_WINDOW == 60.0

    def test_should_not_restart_after_5_in_60s(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        now = time.monotonic()
        # Simulate 5 restarts within the window
        hp._restart_timestamps = [now - i for i in range(5)]
        assert hp._should_restart() is False

    def test_should_restart_if_old_attempts_expired(self):
        from native.helper_process import HelperProcess

        hp = HelperProcess()
        now = time.monotonic()
        # All restarts are older than 60s
        hp._restart_timestamps = [now - 120 for _ in range(5)]
        assert hp._should_restart() is True


# ================================================================
#  4. Sweep hardening: DoS bounds, report injection, dead-path fixes
# ================================================================


def _terminal_with_lines(lines):
    """Mock terminal whose makeTextInfo returns the joined lines."""
    terminal = Mock()
    info = Mock()
    info.text = "\n".join(lines)
    terminal.makeTextInfo = Mock(return_value=info)
    return terminal


class TestFuzzyLengthBound:
    """A word whose length differs from the pattern by more than 1 can never
    be within Levenshtein distance 1, so it is rejected before the O(n*m)
    matrix is built -- bounding work against a giant unbroken token."""

    def _mgr(self):
        from lib.search import OutputSearchManager
        return OutputSearchManager.__new__(OutputSearchManager)

    def test_huge_word_rejected_without_building_matrix(self):
        # 5,000,000-char token: without the guard this allocates a
        # ~500 x 5,000,000 matrix on NVDA's main thread.
        assert self._mgr()._line_fuzzy_matches("error", "a" * 5_000_000) is False

    def test_near_length_word_still_matches(self):
        mgr = self._mgr()
        assert mgr._line_fuzzy_matches("error", "the erro happened") is True
        assert mgr._line_fuzzy_matches("error", "an errorr occurred") is True

    def test_transposition_still_matches(self):
        assert self._mgr()._line_fuzzy_matches("error", "an erorr here") is True

    def test_search_against_giant_line_is_bounded(self):
        from lib.search import OutputSearchManager
        terminal = _terminal_with_lines(["x" * 2_000_000])
        mgr = OutputSearchManager(terminal)
        assert mgr.search("error") == 0


class TestLineCapAffectsMatching:
    """The per-line cap applies to matching, not just stored match text."""

    def test_match_beyond_cap_not_found(self):
        from lib.search import OutputSearchManager
        cap = OutputSearchManager.MAX_LINE_LENGTH
        terminal = _terminal_with_lines(["a" * (cap + 100) + " needle"])
        mgr = OutputSearchManager(terminal)
        assert mgr.search("needle") == 0

    def test_match_within_cap_found(self):
        from lib.search import OutputSearchManager
        terminal = _terminal_with_lines(["needle " + "a" * 20000])
        mgr = OutputSearchManager(terminal)
        assert mgr.search("needle") == 1


class TestSectionScopeFuzzyNoLeak:
    """Section-scoped fuzzy search must not fall back to the whole buffer
    when no span contains the cursor line."""

    def test_no_containing_span_yields_nothing(self):
        from lib.search import OutputSearchManager
        lines = ["$ make build", "compiling main.c", "an erro happened"]
        terminal = _terminal_with_lines(lines)
        mgr = OutputSearchManager(terminal)
        assert mgr.search("error", scope="section", current_line=99999) == 0


class TestUrlSharedChecker:
    """open_url and the dialog Open action share one normalize+scheme check."""

    def test_safe_schemes_prepared(self):
        from lib.search import UrlExtractorManager
        for url in ("http://x.com", "https://x.com/p", "ftp://f.x.com",
                    "www.x.com", "  https://x.com  "):
            assert UrlExtractorManager._prepare_safe_url(url) is not None

    def test_unsafe_schemes_rejected(self):
        from lib.search import UrlExtractorManager
        for url in ("javascript:alert(1)", "file:///c:/x", "data:text/html,x",
                    "vbscript:msgbox", "mailto:a@b.c", ""):
            assert UrlExtractorManager._prepare_safe_url(url) is None

    def test_www_normalized_to_https(self):
        from lib.search import UrlExtractorManager
        assert UrlExtractorManager._prepare_safe_url("www.x.com") == \
            "https://www.x.com"

    def test_surrounding_whitespace_trimmed(self):
        from lib.search import UrlExtractorManager
        assert UrlExtractorManager._prepare_safe_url("  http://x.com  ") == \
            "http://x.com"


class TestDiagnosticInjection:
    """A crafted window title cannot forge extra report fields."""

    def test_title_newlines_do_not_forge_fields(self):
        from lib import diagnostics
        context = {
            "addon_version": "2.0.0",
            "nvda_version": "2026.1",
            "window_title": "evil\nNVDA version: HACKED\rmore",
        }
        report = diagnostics.build_issue_report(context, ["output"])
        nvda_lines = [ln for ln in report.splitlines()
                      if ln.startswith("NVDA version:")]
        assert nvda_lines == ["NVDA version: 2026.1"]
        assert "Window title: evil NVDA version: HACKED more" in report

    def test_control_chars_stripped(self):
        from lib import diagnostics
        report = diagnostics.build_issue_report(
            {"terminal_app": "wt\x07\x08\x00"}, [])
        assert "Terminal: wt" in report
        assert "\x07" not in report and "\x00" not in report


class TestClassifyLengthCap:
    """classify() bounds regex/ANSI work against a giant single line."""

    def test_marker_past_cap_not_classified(self):
        from lib.text_processing import ErrorLineDetector
        cap = ErrorLineDetector._MAX_CLASSIFY_LENGTH
        assert ErrorLineDetector.classify("x" * (cap + 50) + " error: late") is None

    def test_marker_at_start_still_classified(self):
        from lib.text_processing import ErrorLineDetector
        assert ErrorLineDetector.classify("error: boom " + "x" * 5_000_000) == "error"

    def test_strip_ansi_terminates_on_long_escape_run(self):
        from lib.text_processing import ANSIParser
        # Must return (not hang) on a long run of escape introducers.
        out = ANSIParser.stripANSI("\x1b" * 5000)
        assert isinstance(out, str)

    def test_strip_ansi_removes_real_sequences(self):
        from lib.text_processing import ANSIParser
        assert ANSIParser.stripANSI("\x1b[31mred\x1b[0m text") == "red text"


class TestProgressMilestoneTerminal:
    """_checkProgressMilestone reads the terminal that changed, not the
    last-bound terminal."""

    def test_reads_passed_terminal(self):
        from globalPlugins.terminalAccess import GlobalPlugin
        plugin = GlobalPlugin.__new__(GlobalPlugin)
        plugin._lastProgressCheckTime = 0.0
        plugin._PROGRESS_CHECK_INTERVAL = 0.0
        plugin._progressTracker = Mock()
        plugin._progressTracker.update = Mock(return_value=None)
        bound = Mock(name="bound")
        changed = _terminal_with_lines(["build 50%"])
        plugin._boundTerminal = bound

        plugin._checkProgressMilestone(changed)

        changed.makeTextInfo.assert_called_once()
        bound.makeTextInfo.assert_not_called()


