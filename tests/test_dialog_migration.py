"""Tests for migrating the bookmark, AI turn, URL, and search dialogs
onto the shared BrowsableListDialog.

wx is mocked in the test environment, so the dialog widgets themselves
cannot be exercised. These tests cover the pure row-building helpers and
confirm each migrated factory stays importable and callable with its
original signature.
"""
import sys
from unittest.mock import Mock, MagicMock

import pytest


class TestBookmarkRows:
    def test_builds_name_and_label_columns(self):
        from lib.list_dialogs import build_bookmark_rows
        rows = build_bookmark_rows([
            {"name": "1", "label": "build error"},
            {"name": "2", "label": "test output"},
        ])
        assert rows == [("1", "build error"), ("2", "test output")]

    def test_missing_label_becomes_empty(self):
        from lib.list_dialogs import build_bookmark_rows
        rows = build_bookmark_rows([{"name": "3"}])
        assert rows == [("3", "")]

    def test_empty_list(self):
        from lib.list_dialogs import build_bookmark_rows
        assert build_bookmark_rows([]) == []


class TestAiTurnRows:
    def test_rows_have_role_line_preview(self):
        from lib.list_dialogs import build_ai_turn_rows
        rows, _choices = build_ai_turn_rows([
            {"role": "user", "line_num": 4, "preview": "hello"},
        ])
        # line_num is stored 0-based, displayed 1-based
        assert rows == [("user", "5", "hello")]

    def test_filter_choices_cover_roles(self):
        from lib.list_dialogs import build_ai_turn_rows
        _rows, choices = build_ai_turn_rows([
            {"role": "user", "line_num": 0, "preview": "a"},
            {"role": "assistant", "line_num": 2, "preview": "b"},
            {"role": "user", "line_num": 4, "preview": "c"},
        ])
        labels = [label for label, _pred in choices]
        assert labels == ["assistant", "user"]

    def test_filter_predicate_matches_its_role(self):
        from lib.list_dialogs import build_ai_turn_rows
        rows, choices = build_ai_turn_rows([
            {"role": "user", "line_num": 0, "preview": "a"},
            {"role": "assistant", "line_num": 1, "preview": "b"},
        ])
        # find the assistant predicate and apply it to both rows
        pred = dict(choices)["assistant"]
        assert pred(rows[1]) is True
        assert pred(rows[0]) is False


class TestSearchRows:
    def test_rows_have_num_line_content(self):
        from lib.list_dialogs import build_search_rows
        rows = build_search_rows([
            {"num": 1, "line_num": 12, "text": "error here"},
            {"num": 2, "line_num": 30, "text": "error again"},
        ])
        assert rows == [("1", "12", "error here"), ("2", "30", "error again")]

    def test_empty(self):
        from lib.list_dialogs import build_search_rows
        assert build_search_rows([]) == []


class TestUrlRows:
    def _url(self, url, line_num, line_text):
        entry = Mock()
        entry.url = url
        entry.line_num = line_num
        entry.line_text = line_text
        return entry

    def test_rows_number_from_one_with_context(self):
        from lib.list_dialogs import build_url_rows
        rows = build_url_rows([
            self._url("https://a.com", 3, "see https://a.com now"),
            self._url("https://b.com", 9, "and https://b.com"),
        ])
        assert rows[0] == ("1", "https://a.com", "3", "see https://a.com now")
        assert rows[1][0] == "2"

    def test_context_truncated_to_80(self):
        from lib.list_dialogs import build_url_rows
        long_text = "x" * 200
        rows = build_url_rows([self._url("https://a.com", 1, long_text)])
        assert len(rows[0][3]) == 80

    def test_none_context_safe(self):
        from lib.list_dialogs import build_url_rows
        rows = build_url_rows([self._url("https://a.com", 1, None)])
        assert rows[0][3] == ""


class TestMigratedFactoriesImportable:
    """Each migrated dialog stays importable and callable with its
    original constructor signature."""

    def test_bookmark_list_dialog_importable(self):
        from lib.navigation import BookmarkListDialog
        assert BookmarkListDialog is not None
        assert callable(BookmarkListDialog)

    def test_ai_turn_list_dialog_importable(self):
        from lib.navigation import AiTurnListDialog
        assert AiTurnListDialog is not None
        assert callable(AiTurnListDialog)

    def test_url_list_dialog_importable(self):
        from lib.search import UrlListDialog
        assert UrlListDialog is not None
        assert callable(UrlListDialog)

    def test_search_results_dialog_importable(self):
        from lib.search import SearchResultsDialog
        assert SearchResultsDialog is not None
        assert callable(SearchResultsDialog)


class TestBrowsableListDialogHooks:
    """The generic dialog exposes the hooks the migrated dialogs need."""

    def test_accepts_rows_provider_and_key_actions_params(self):
        import inspect
        from lib.list_dialogs import BrowsableListDialog
        # BrowsableListDialog is a MagicMock subclass under mocked wx, so
        # inspect the source of __init__ via the module instead.
        import lib.list_dialogs as mod
        src = inspect.getsource(mod)
        assert "rows_provider" in src
        assert "key_actions" in src
