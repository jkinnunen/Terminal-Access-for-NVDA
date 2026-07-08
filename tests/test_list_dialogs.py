"""Tests for the generic browsable list dialog module (lib.list_dialogs).

RED phase: these tests define the expected behavior for:
1. build_display_rows() - filtering with a stable original-index map
2. resolve_original_index() - activate callback receives original index
3. make_text_predicate() - type-to-filter text matching
4. BrowsableListDialog / SectionListDialog wrapper importability

wx is mocked (conftest), so dialog behavior is verified through the pure
data-prep helpers rather than real widget interaction.
"""

import sys
from unittest.mock import Mock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# build_display_rows: index map correctness
# ---------------------------------------------------------------------------

class TestBuildDisplayRows:
    """build_display_rows(rows, predicate) -> (display_rows, index_map)."""

    def test_no_predicate_returns_all_rows_with_identity_map(self):
        """Without a predicate, every row is displayed and map is identity."""
        from lib.list_dialogs import build_display_rows

        rows = [("a", "1"), ("b", "2"), ("c", "3")]
        display_rows, index_map = build_display_rows(rows, None)

        assert display_rows == rows
        assert index_map == [0, 1, 2]

    def test_empty_rows_returns_empty(self):
        """Empty input produces empty display rows and empty index map."""
        from lib.list_dialogs import build_display_rows

        display_rows, index_map = build_display_rows([], None)
        assert display_rows == []
        assert index_map == []

    def test_empty_rows_with_predicate_returns_empty(self):
        """Empty input with a predicate still produces empty results."""
        from lib.list_dialogs import build_display_rows

        display_rows, index_map = build_display_rows([], lambda row: True)
        assert display_rows == []
        assert index_map == []

    def test_predicate_filters_rows(self):
        """Only rows matching the predicate appear in display_rows."""
        from lib.list_dialogs import build_display_rows

        rows = [("error", "1"), ("prompt", "2"), ("error", "3")]
        display_rows, index_map = build_display_rows(
            rows, lambda row: row[0] == "error"
        )

        assert display_rows == [("error", "1"), ("error", "3")]

    def test_index_map_preserves_original_indices(self):
        """index_map[i] is the index of display_rows[i] in the original rows."""
        from lib.list_dialogs import build_display_rows

        rows = [("a", "x"), ("b", "y"), ("a", "z"), ("c", "w")]
        display_rows, index_map = build_display_rows(
            rows, lambda row: row[0] in ("a", "c")
        )

        assert index_map == [0, 2, 3]
        for display_idx, original_idx in enumerate(index_map):
            assert display_rows[display_idx] == rows[original_idx]

    def test_predicate_matching_nothing_returns_empty(self):
        """A predicate rejecting every row yields empty results."""
        from lib.list_dialogs import build_display_rows

        rows = [("a", "1"), ("b", "2")]
        display_rows, index_map = build_display_rows(rows, lambda row: False)

        assert display_rows == []
        assert index_map == []

    def test_columns_preserved_in_display_rows(self):
        """Row tuples pass through unchanged: all columns intact, in order."""
        from lib.list_dialogs import build_display_rows

        rows = [("type", "42", "preview text", "extra")]
        display_rows, _ = build_display_rows(rows, lambda row: True)

        assert display_rows[0] == ("type", "42", "preview text", "extra")

    def test_original_rows_not_mutated(self):
        """Filtering must not mutate the caller's row list."""
        from lib.list_dialogs import build_display_rows

        rows = [("a", "1"), ("b", "2")]
        snapshot = list(rows)
        build_display_rows(rows, lambda row: row[0] == "a")

        assert rows == snapshot


# ---------------------------------------------------------------------------
# resolve_original_index: activate callback receives ORIGINAL index
# ---------------------------------------------------------------------------

class TestResolveOriginalIndex:
    """Activation resolves the display selection to the original row index."""

    def test_identity_map_resolves_same_index(self):
        from lib.list_dialogs import resolve_original_index

        assert resolve_original_index([0, 1, 2], 1) == 1

    def test_filtered_map_resolves_to_original_index(self):
        """Selecting display row 1 after filtering returns its original index."""
        from lib.list_dialogs import build_display_rows, resolve_original_index

        rows = [("skip", "0"), ("keep", "1"), ("skip", "2"), ("keep", "3")]
        _, index_map = build_display_rows(rows, lambda row: row[0] == "keep")

        assert resolve_original_index(index_map, 0) == 1
        assert resolve_original_index(index_map, 1) == 3

    def test_out_of_range_returns_none(self):
        from lib.list_dialogs import resolve_original_index

        assert resolve_original_index([0, 1], 5) is None

    def test_negative_index_returns_none(self):
        """wx returns -1 for 'no selection'; that must resolve to None."""
        from lib.list_dialogs import resolve_original_index

        assert resolve_original_index([0, 1], -1) is None

    def test_empty_map_returns_none(self):
        from lib.list_dialogs import resolve_original_index

        assert resolve_original_index([], 0) is None

    def test_activate_callback_receives_original_index(self):
        """End-to-end data flow: filter, select display row, fire callback."""
        from lib.list_dialogs import build_display_rows, resolve_original_index

        rows = [("a", "0"), ("b", "1"), ("a", "2")]
        _, index_map = build_display_rows(rows, lambda row: row[0] == "a")

        received = []
        on_activate = received.append

        # User selects the SECOND displayed row ("a", "2")
        original = resolve_original_index(index_map, 1)
        on_activate(original)

        assert received == [2]
        assert rows[received[0]] == ("a", "2")


# ---------------------------------------------------------------------------
# make_text_predicate: type-to-filter search box
# ---------------------------------------------------------------------------

class TestMakeTextPredicate:
    """Text filter predicate for the optional search box."""

    def test_empty_text_returns_none(self):
        """Empty or whitespace filter text means 'no filtering'."""
        from lib.list_dialogs import make_text_predicate

        assert make_text_predicate("") is None
        assert make_text_predicate("   ") is None

    def test_matches_substring_case_insensitive(self):
        from lib.list_dialogs import make_text_predicate

        pred = make_text_predicate("BOOK")
        assert pred(("listBookmarks", "List all bookmarks", "NVDA+Shift+B"))
        assert not pred(("readLine", "Read the current line", "NVDA+I"))

    def test_restricts_matching_to_given_columns(self):
        """With columns=(0, 1), text in other columns must not match."""
        from lib.list_dialogs import make_text_predicate

        pred = make_text_predicate("nvda", columns=(0, 1))
        assert not pred(("readLine", "Read the current line", "NVDA+I"))
        assert pred(("readLine", "Read via NVDA review cursor", "kb:x"))

    def test_index_map_rules_apply_under_text_filter(self):
        """Text filtering follows the same index-map contract."""
        from lib.list_dialogs import (
            build_display_rows, make_text_predicate, resolve_original_index,
        )

        rows = [
            ("copyLine", "Copy the current line", "c"),
            ("readLine", "Read the current line", "i"),
            ("copyScreen", "Copy the whole screen", "s"),
        ]
        pred = make_text_predicate("copy", columns=(0, 1))
        display_rows, index_map = build_display_rows(rows, pred)

        assert [r[0] for r in display_rows] == ["copyLine", "copyScreen"]
        assert resolve_original_index(index_map, 1) == 2


# ---------------------------------------------------------------------------
# Dialog importability (wx is mocked; construction logic only)
# ---------------------------------------------------------------------------

class TestDialogImports:
    """BrowsableListDialog and the SectionListDialog wrapper must exist."""

    def test_browsable_list_dialog_importable(self):
        from lib.list_dialogs import BrowsableListDialog

        assert BrowsableListDialog is not None
        assert hasattr(sys.modules["lib.list_dialogs"], "BrowsableListDialog")

    def test_section_list_dialog_still_importable_from_navigation(self):
        """The refactored SectionListDialog remains importable and callable."""
        from lib.navigation import SectionListDialog

        assert SectionListDialog is not None
        assert callable(SectionListDialog)


# ---------------------------------------------------------------------------
# Command finder: collect_commands
# ---------------------------------------------------------------------------

def _make_plugin():
    from globalPlugins.terminalAccess import GlobalPlugin
    return GlobalPlugin()


class TestCollectCommands:
    """collect_commands(plugin) introspects every script_* method."""

    def test_commands_collected_for_every_script(self):
        """Every script_* method on the plugin yields one command entry."""
        from lib.list_dialogs import collect_commands
        from globalPlugins.terminalAccess import GlobalPlugin

        plugin = _make_plugin()
        commands = collect_commands(plugin)

        script_names = {
            attr[len("script_"):]
            for attr in dir(GlobalPlugin)
            if attr.startswith("script_")
        }
        collected_names = {c["name"] for c in commands}
        assert collected_names == script_names

    def test_commands_have_required_keys(self):
        from lib.list_dialogs import collect_commands

        commands = collect_commands(_make_plugin())
        assert commands
        for command in commands:
            assert set(command) >= {
                "name", "description", "gesture_display", "layer_key"
            }

    def test_commands_sorted_by_name(self):
        from lib.list_dialogs import collect_commands

        commands = collect_commands(_make_plugin())
        names = [c["name"] for c in commands]
        assert names == sorted(names)

    def test_description_falls_back_to_docstring_first_line(self):
        """The test decorator stores no description, so the docstring's
        first line is used."""
        from lib.list_dialogs import collect_commands
        from globalPlugins.terminalAccess import GlobalPlugin

        commands = collect_commands(_make_plugin())
        by_name = {c["name"]: c for c in commands}

        expected = GlobalPlugin.script_listBookmarks.__doc__.strip()
        expected_first_line = expected.split("\n")[0].strip()
        assert by_name["listBookmarks"]["description"] == expected_first_line

    def test_gesture_display_uses_gesture_label_helper(self):
        """Gesture formatting goes through lib._runtime.gesture_label."""
        from lib.list_dialogs import collect_commands
        from lib._runtime import gesture_label

        commands = collect_commands(_make_plugin())
        by_name = {c["name"]: c for c in commands}

        # readCurrentLine is bound to kb:NVDA+i in _DEFAULT_GESTURES
        expected = gesture_label("kb:NVDA+i", "readCurrentLine")
        assert expected in by_name["readCurrentLine"]["gesture_display"]

    def test_layer_key_reflects_command_layer_map(self):
        """listSections is on shift+s in the command layer."""
        from lib.list_dialogs import collect_commands

        commands = collect_commands(_make_plugin())
        by_name = {c["name"]: c for c in commands}
        assert "shift+s" in by_name["listSections"]["layer_key"]

    def test_script_without_layer_key_has_empty_layer_key(self):
        """spellCurrentWord has no command layer binding."""
        from lib.list_dialogs import collect_commands

        commands = collect_commands(_make_plugin())
        by_name = {c["name"]: c for c in commands}
        assert by_name["spellCurrentWord"]["layer_key"] == ""


class TestFindCommandScript:
    """script_findCommand wiring on the plugin."""

    def test_find_command_script_exists(self):
        from globalPlugins.terminalAccess import GlobalPlugin

        assert hasattr(GlobalPlugin, "script_findCommand")

    def test_find_command_in_command_layer_on_h(self):
        from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP

        assert _COMMAND_LAYER_MAP.get("kb:h") == "findCommand"

    def test_find_command_direct_gesture(self):
        """Direct gesture is NVDA+alt+h via the @script decorator."""
        from globalPlugins.terminalAccess import GlobalPlugin

        gestures = getattr(GlobalPlugin.script_findCommand, "__gestures__", [])
        assert "kb:NVDA+alt+h" in gestures

    def test_find_command_passes_through_outside_terminal(self):
        from globalPlugins.terminalAccess import GlobalPlugin

        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=False)
        gesture = MagicMock()
        plugin.script_findCommand(gesture)
        gesture.send.assert_called_once()

    def test_activation_announces_gesture_not_executes(self):
        """Activating a command announces its bindings via ui.message and
        never calls the command's script."""
        import ui
        from lib.list_dialogs import collect_commands

        plugin = _make_plugin()
        commands = collect_commands(plugin)
        by_name = {c["name"]: c for c in commands}
        command = by_name["readCurrentLine"]

        plugin.script_readCurrentLine = Mock()
        ui.message.reset_mock()

        plugin._announceCommandInvocation(command)

        ui.message.assert_called_once()
        announced = ui.message.call_args[0][0]
        assert "readCurrentLine" in announced or "Read Current Line" in announced
        plugin.script_readCurrentLine.assert_not_called()


# ---------------------------------------------------------------------------
# Transcript export: export_transcript_text
# ---------------------------------------------------------------------------

class TestExportTranscriptText:
    """export_transcript_text(lines) -> str, unit-testable without wx."""

    def test_strips_ansi_sequences(self):
        from lib.list_dialogs import export_transcript_text

        lines = ["\x1b[31merror: boom\x1b[0m", "\x1b[1mBOLD\x1b[22m text"]
        result = export_transcript_text(lines)

        assert "\x1b" not in result
        assert "error: boom" in result
        assert "BOLD text" in result

    def test_joins_lines_with_newline(self):
        from lib.list_dialogs import export_transcript_text

        assert export_transcript_text(["one", "two", "three"]) == "one\ntwo\nthree"

    def test_empty_buffer_returns_empty_string(self):
        from lib.list_dialogs import export_transcript_text

        assert export_transcript_text([]) == ""

    def test_none_lines_filtered(self):
        from lib.list_dialogs import export_transcript_text

        assert export_transcript_text(["a", None, "b", None]) == "a\nb"


class TestExportTranscriptScript:
    """script_exportTranscript wiring on the plugin."""

    def test_export_transcript_script_exists(self):
        from globalPlugins.terminalAccess import GlobalPlugin

        assert hasattr(GlobalPlugin, "script_exportTranscript")

    def test_export_transcript_in_command_layer_on_control_s(self):
        from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP

        assert _COMMAND_LAYER_MAP.get("kb:control+s") == "exportTranscript"

    def test_export_transcript_direct_gesture(self):
        """Direct gesture is NVDA+alt+x via the @script decorator."""
        from globalPlugins.terminalAccess import GlobalPlugin

        gestures = getattr(
            GlobalPlugin.script_exportTranscript, "__gestures__", []
        )
        assert "kb:NVDA+alt+x" in gestures

    def test_export_transcript_passes_through_outside_terminal(self):
        from globalPlugins.terminalAccess import GlobalPlugin

        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=False)
        gesture = MagicMock()
        plugin.script_exportTranscript(gesture)
        gesture.send.assert_called_once()

    def test_export_transcript_reports_unreadable_buffer(self):
        """When the buffer cannot be read, the user hears an error message."""
        import ui
        from globalPlugins.terminalAccess import GlobalPlugin

        plugin = _make_plugin()
        plugin.isTerminalApp = Mock(return_value=True)
        plugin._getBufferLines = Mock(return_value=None)
        ui.message.reset_mock()

        plugin.script_exportTranscript(MagicMock())

        ui.message.assert_called_once()
