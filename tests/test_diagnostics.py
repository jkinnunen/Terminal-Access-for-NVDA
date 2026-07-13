"""Tests for the diagnostic issue report."""
from unittest.mock import MagicMock, patch

import pytest

from lib.diagnostics import build_issue_report


class TestBuildIssueReport:
    def _context(self, **overrides):
        ctx = {
            "addon_version": "2.0.0-beta.3",
            "nvda_version": "2026.1",
            "terminal_app": "windowsterminal",
            "window_title": "Windows Terminal",
            "profile": "Vim/Neovim",
            "verbosity_level": 1,
            "review_line": 12,
        }
        ctx.update(overrides)
        return ctx

    def test_includes_all_context_fields(self):
        report = build_issue_report(self._context(), ["line one", "line two"])
        for expected in (
            "2.0.0-beta.3", "2026.1", "windowsterminal", "Windows Terminal",
            "Vim/Neovim", "line one", "line two",
        ):
            assert expected in report

    def test_no_native_line_in_report(self):
        """The native/helper report line was removed with the native layer."""
        report = build_issue_report(self._context(), [])
        assert "Native acceleration" not in report

    def test_missing_fields_show_unknown(self):
        report = build_issue_report({}, [])
        assert "Add-on version: unknown" in report
        assert "NVDA version: unknown" in report

    def test_prompts_the_user_to_describe(self):
        report = build_issue_report(self._context(), [])
        assert "What happened:" in report
        assert "expected" in report.lower()

    def test_truncates_to_last_lines(self):
        lines = [f"line {i}" for i in range(3000)]
        report = build_issue_report(self._context(), lines, max_buffer_lines=1000)
        assert "line 2999" in report      # kept (last)
        assert "line 0\n" not in report   # dropped (oldest)
        assert "last 1000 lines" in report

    def test_ends_with_newline(self):
        assert build_issue_report(self._context(), ["x"]).endswith("\n")


class TestCollectDiagnosticContext:
    def _plugin(self):
        from globalPlugins.terminalAccess import GlobalPlugin
        with patch("gui.settingsDialogs.NVDASettingsDialog"):
            plugin = GlobalPlugin()
        plugin._configManager = MagicMock()
        plugin._configManager.get = MagicMock(return_value=1)
        plugin._currentProfile = None
        plugin.lastTerminalAppName = "cmd"
        plugin._boundTerminal = MagicMock()
        plugin._boundTerminal.name = "Command Prompt"
        plugin._getCurrentLineNumber = MagicMock(return_value=42)
        return plugin

    def test_collects_core_fields(self):
        plugin = self._plugin()
        ctx = plugin._collectDiagnosticContext()
        assert ctx["terminal_app"] == "cmd"
        assert ctx["window_title"] == "Command Prompt"
        assert ctx["review_line"] == 42
        assert ctx["profile"] == "none"
        assert ctx["verbosity_level"] == 1
        # Native/helper fields were removed with the native layer.
        assert "native_available" not in ctx
        assert "helper_running" not in ctx

    def test_report_from_collected_context_is_buildable(self):
        plugin = self._plugin()
        ctx = plugin._collectDiagnosticContext()
        report = build_issue_report(ctx, ["output line"])
        assert "cmd" in report
        assert "output line" in report
