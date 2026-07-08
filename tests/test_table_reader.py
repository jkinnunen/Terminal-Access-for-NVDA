"""Tests for column-aware table reading of terminal output.

Part 1: lib.table_reader (TableDetector, TableRegion, TableNavigator).
Part 2: table mode wiring in globalPlugins.terminalAccess.

Fixtures are realistic captures of docker ps, ls -l, kubectl get pods,
a psql result table, and a markdown table.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DOCKER_PS = [
    'CONTAINER ID   IMAGE          COMMAND                  CREATED       STATUS       PORTS                  NAMES',
    '3f4a9b2c1d0e   nginx:latest   "nginx -g daemon off"    2 hours ago   Up 2 hours   0.0.0.0:8080->80/tcp   web',
    '7b8c6d5e4f3a   redis:7        "docker-entrypoint"      3 days ago    Up 3 days    6379/tcp               cache',
]

KUBECTL_PODS = [
    'NAME                     READY   STATUS             RESTARTS   AGE',
    'web-7d4b9c6f5-x2m8q      1/1     Running            0          2d4h',
    'worker-6c8d7b9f4-p1n3r   1/1     Running            3          5d',
    'db-0                     1/1     CrashLoopBackOff   12         1h',
]

LS_L = [
    'total 3',
    '-rw-r--r--  1  pratik  staff    4096  Jul  1 09:30  notes.txt',
    'drwxr-xr-x  5  pratik  staff     160  Jun 28 14:02  projects',
    '-rw-r--r--  1  pratik  staff  128000  Jul  3 18:45  report.pdf',
]

PSQL = [
    'psql (16.2)',
    ' id | name  | status',
    '----+-------+--------',
    '  1 | alice | active',
    '  2 | bob   | idle',
    '(2 rows)',
]

MARKDOWN = [
    '| Name  | Role     | Team |',
    '| ----- | -------- | ---- |',
    '| Alice | Engineer | Core |',
    '| Bob   | Designer | Web  |',
]

PROSE = [
    'This is an ordinary paragraph of text with no columns at all.',
    'It simply wraps across a few lines like any prose would.',
    'Nothing about it should register as tabular data.',
]

EMPTY_CELL_TABLE = [
    'NAME    PORTS     STATUS',
    'web     8080      up',
    'cache             up',
]

ANSI_KUBECTL = [
    KUBECTL_PODS[0].replace('STATUS', '\x1b[1mSTATUS\x1b[0m'),
    KUBECTL_PODS[1].replace('Running', '\x1b[32mRunning\x1b[0m'),
    KUBECTL_PODS[2],
    KUBECTL_PODS[3].replace('CrashLoopBackOff', '\x1b[31mCrashLoopBackOff\x1b[0m'),
]


def _detect(lines, start):
    from lib.table_reader import TableDetector
    return TableDetector().detect(lines, start)


def _navigator(lines, start):
    from lib.table_reader import TableDetector, TableNavigator
    region = TableDetector().detect(lines, start)
    assert region is not None
    return TableNavigator(region, lines)


# ---------------------------------------------------------------------------
# Detection: kinds and boundaries
# ---------------------------------------------------------------------------

class TestDetection:

    def test_docker_ps_detected_as_aligned(self):
        region = _detect(DOCKER_PS, 1)
        assert region is not None
        assert region.kind == 'aligned'
        assert region.first_line == 0
        assert region.last_line == 2
        assert len(region.column_spans) == 7

    def test_kubectl_detected_as_aligned(self):
        region = _detect(KUBECTL_PODS, 2)
        assert region is not None
        assert region.kind == 'aligned'
        assert region.first_line == 0
        assert region.last_line == 3
        assert len(region.column_spans) == 5

    def test_ls_l_excludes_total_line(self):
        region = _detect(LS_L, 2)
        assert region is not None
        assert region.kind == 'aligned'
        assert region.first_line == 1
        assert region.last_line == 3
        assert len(region.column_spans) == 7

    def test_psql_detected_as_pipe(self):
        region = _detect(PSQL, 3)
        assert region is not None
        assert region.kind == 'pipe'
        assert region.first_line == 1
        assert region.last_line == 4

    def test_markdown_detected_as_pipe(self):
        region = _detect(MARKDOWN, 2)
        assert region is not None
        assert region.kind == 'pipe'
        assert region.first_line == 0
        assert region.last_line == 3

    def test_prose_returns_none(self):
        assert _detect(PROSE, 1) is None

    def test_single_line_returns_none(self):
        assert _detect(['NAME   STATUS'], 0) is None

    def test_start_line_out_of_range_returns_none(self):
        assert _detect(DOCKER_PS, 99) is None
        assert _detect(DOCKER_PS, -1) is None

    def test_empty_buffer_returns_none(self):
        assert _detect([], 0) is None

    def test_table_surrounded_by_prose(self):
        lines = (['Some notes about the cluster follow.', '']
                 + KUBECTL_PODS
                 + ['', 'That concludes the pod listing.'])
        region = _detect(lines, 3)
        assert region is not None
        assert region.first_line == 2
        assert region.last_line == 5

    def test_pipe_region_excludes_surrounding_prose(self):
        region = _detect(PSQL, 3)
        assert region.first_line == 1  # 'psql (16.2)' excluded
        assert region.last_line == 4   # '(2 rows)' excluded

    def test_ragged_trailing_prompt_excluded(self):
        lines = DOCKER_PS + ['$ ']
        region = _detect(lines, 1)
        assert region is not None
        assert region.last_line == 2

    def test_ansi_colored_table_detected(self):
        region = _detect(ANSI_KUBECTL, 1)
        assert region is not None
        assert region.kind == 'aligned'
        assert region.first_line == 0
        assert region.last_line == 3
        assert len(region.column_spans) == 5

    def test_500_line_cap(self):
        lines = ['COL_A      COL_B']
        lines += ['item{0:04d}   val{0:04d}'.format(i) for i in range(600)]
        region = _detect(lines, 300)
        assert region is not None
        assert (region.last_line - region.first_line + 1) <= 500
        assert region.first_line <= 300 <= region.last_line


# ---------------------------------------------------------------------------
# Cell extraction and headers
# ---------------------------------------------------------------------------

class TestCellExtraction:

    def test_docker_cells(self):
        nav = _navigator(DOCKER_PS, 1)
        assert nav.cell(0, 0) == 'CONTAINER ID'
        assert nav.cell(1, 0) == '3f4a9b2c1d0e'
        assert nav.cell(1, 1) == 'nginx:latest'
        assert nav.cell(2, 2) == '"docker-entrypoint"'
        assert nav.cell(1, 3) == '2 hours ago'
        assert nav.cell(2, 4) == 'Up 3 days'
        assert nav.cell(1, 5) == '0.0.0.0:8080->80/tcp'
        assert nav.cell(2, 6) == 'cache'

    def test_kubectl_cells(self):
        nav = _navigator(KUBECTL_PODS, 1)
        assert nav.cell(1, 0) == 'web-7d4b9c6f5-x2m8q'
        assert nav.cell(3, 2) == 'CrashLoopBackOff'
        assert nav.cell(3, 3) == '12'
        assert nav.cell(2, 4) == '5d'

    def test_psql_cells_skip_separator(self):
        nav = _navigator(PSQL, 3)
        assert nav.cell(0, 0) == 'id'
        assert nav.cell(0, 2) == 'status'
        assert nav.cell(1, 1) == 'alice'
        assert nav.cell(2, 2) == 'idle'

    def test_markdown_cells_skip_separator(self):
        nav = _navigator(MARKDOWN, 2)
        assert nav.cell(0, 1) == 'Role'
        assert nav.cell(1, 0) == 'Alice'
        assert nav.cell(2, 2) == 'Web'

    def test_header_lookup(self):
        nav = _navigator(KUBECTL_PODS, 1)
        assert nav.header(0) == 'NAME'
        assert nav.header(2) == 'STATUS'
        assert nav.header(4) == 'AGE'

    def test_out_of_range_cell_is_empty_string(self):
        nav = _navigator(DOCKER_PS, 1)
        assert nav.cell(99, 0) == ''
        assert nav.cell(0, 99) == ''
        assert nav.cell(-5, -5) == ''

    def test_empty_cell_aligned(self):
        nav = _navigator(EMPTY_CELL_TABLE, 1)
        assert nav.cell(2, 0) == 'cache'
        assert nav.cell(2, 1) == ''
        assert nav.cell(2, 2) == 'up'

    def test_empty_cell_pipe(self):
        lines = ['| a |  | c |', '| 1 |  | 3 |']
        nav = _navigator(lines, 0)
        assert nav.cell(1, 0) == '1'
        assert nav.cell(1, 1) == ''
        assert nav.cell(1, 2) == '3'

    def test_ansi_cells_match_plain(self):
        nav = _navigator(ANSI_KUBECTL, 1)
        assert nav.cell(1, 2) == 'Running'
        assert nav.header(2) == 'STATUS'
        assert nav.cell(3, 2) == 'CrashLoopBackOff'


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

class TestMovement:

    def _nav(self):
        return _navigator(KUBECTL_PODS, 1)  # 4 rows x 5 cols

    def test_move_down(self):
        assert self._nav().move(0, 0, 1, 0) == (1, 0)

    def test_move_right(self):
        assert self._nav().move(1, 1, 0, 1) == (1, 2)

    def test_up_from_top_edge_is_none(self):
        assert self._nav().move(0, 2, -1, 0) is None

    def test_down_from_bottom_edge_is_none(self):
        assert self._nav().move(3, 2, 1, 0) is None

    def test_left_from_first_column_is_none(self):
        assert self._nav().move(1, 0, 0, -1) is None

    def test_right_from_last_column_is_none(self):
        assert self._nav().move(1, 4, 0, 1) is None

    def test_large_delta_clamps(self):
        assert self._nav().move(1, 1, 10, 0) == (3, 1)
        assert self._nav().move(2, 3, 0, -10) == (2, 0)

    def test_zero_delta_stays_put(self):
        assert self._nav().move(2, 2, 0, 0) == (2, 2)


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------

class TestAnnouncements:

    def test_data_cell_announced_with_header(self):
        nav = _navigator(KUBECTL_PODS, 1)
        assert nav.announce_for(1, 2) == 'STATUS: Running'

    def test_header_row_announced_as_header(self):
        nav = _navigator(KUBECTL_PODS, 1)
        assert nav.announce_for(0, 0) == 'Header: NAME'

    def test_row_summary(self):
        nav = _navigator(KUBECTL_PODS, 1)
        assert nav.row_summary(3) == (
            'NAME db-0, READY 1/1, STATUS CrashLoopBackOff, '
            'RESTARTS 12, AGE 1h'
        )

    def test_pipe_announce(self):
        nav = _navigator(PSQL, 3)
        assert nav.announce_for(1, 1) == 'name: alice'
        assert nav.row_summary(2) == 'id 2, name bob, status idle'


# ---------------------------------------------------------------------------
# Fuzz tests (hypothesis)
# ---------------------------------------------------------------------------

ansi_escape = st.sampled_from([
    '\x1b[31m', '\x1b[0m', '\x1b[1;34m', '\x1b[38;5;196m', '',
])

fuzz_line = st.one_of(
    st.text(max_size=120),
    st.builds(lambda parts: ''.join(parts),
              st.lists(st.one_of(ansi_escape, st.text(max_size=20)), max_size=8)),
)

fuzz_lines = st.lists(fuzz_line, min_size=0, max_size=40)


class TestFuzz:

    @given(lines=fuzz_lines, start=st.integers(min_value=-5, max_value=60))
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_detect_never_crashes(self, lines, start):
        from lib.table_reader import TableDetector, TableRegion
        region = TableDetector().detect(lines, start)
        assert region is None or isinstance(region, TableRegion)

    @given(row=st.integers(), col=st.integers())
    @settings(max_examples=200)
    def test_cell_never_crashes_aligned(self, row, col):
        nav = _navigator(DOCKER_PS, 1)
        assert isinstance(nav.cell(row, col), str)

    @given(row=st.integers(), col=st.integers())
    @settings(max_examples=200)
    def test_cell_never_crashes_pipe(self, row, col):
        nav = _navigator(MARKDOWN, 0)
        assert isinstance(nav.cell(row, col), str)


# ---------------------------------------------------------------------------
# Part 2: plugin table mode integration
# ---------------------------------------------------------------------------

class TestTableModeIntegration:

    def _make_plugin(self, lines, current_line=1):
        from globalPlugins.terminalAccess import GlobalPlugin
        with patch('gui.settingsDialogs.NVDASettingsDialog'):
            plugin = GlobalPlugin()
        plugin.isTerminalApp = MagicMock(return_value=True)
        plugin._boundTerminal = MagicMock()
        plugin._getBufferLines = MagicMock(return_value=lines)
        plugin._getCurrentLineNumber = MagicMock(return_value=current_line)
        return plugin

    def _last_message(self):
        return sys.modules['ui'].message.call_args[0][0]

    def test_gesture_assignments(self):
        from globalPlugins.terminalAccess import _DEFAULT_GESTURES, _COMMAND_LAYER_MAP
        assert _DEFAULT_GESTURES['kb:NVDA+alt+g'] == 'toggleTableMode'
        assert _COMMAND_LAYER_MAP['kb:g'] == 'toggleTableMode'

    def test_enter_table_mode_on_table(self):
        plugin = self._make_plugin(DOCKER_PS)
        sys.modules['ui'].message.reset_mock()
        plugin.script_toggleTableMode(MagicMock())
        assert plugin._tableNavigator is not None
        assert plugin._gestureMap.get('kb:downArrow') == 'tableNextRow'
        assert plugin._gestureMap.get('kb:escape') == 'exitTableMode'
        message = self._last_message()
        assert 'Table mode' in message
        assert '3 rows' in message
        assert '7 columns' in message

    def test_no_table_stays_out_of_mode(self):
        plugin = self._make_plugin(PROSE)
        sys.modules['ui'].message.reset_mock()
        plugin.script_toggleTableMode(MagicMock())
        assert plugin._tableNavigator is None
        assert 'kb:downArrow' not in plugin._gestureMap
        assert 'No table' in self._last_message()

    def test_arrow_movement_announces_header_and_value(self):
        plugin = self._make_plugin(DOCKER_PS)
        plugin.script_toggleTableMode(MagicMock())
        sys.modules['ui'].message.reset_mock()
        plugin.script_tableNextRow(MagicMock())
        assert self._last_message() == 'CONTAINER ID: 3f4a9b2c1d0e'
        plugin.script_tableNextColumn(MagicMock())
        assert self._last_message() == 'IMAGE: nginx:latest'

    def test_edge_announced_at_boundary(self):
        plugin = self._make_plugin(DOCKER_PS)
        plugin.script_toggleTableMode(MagicMock())
        sys.modules['ui'].message.reset_mock()
        plugin.script_tablePreviousRow(MagicMock())  # already on header row
        assert 'Edge of table' in self._last_message()

    def test_home_end_first_last_column(self):
        plugin = self._make_plugin(DOCKER_PS)
        plugin.script_toggleTableMode(MagicMock())
        sys.modules['ui'].message.reset_mock()
        plugin.script_tableLastColumn(MagicMock())
        assert plugin._tableCol == 6
        plugin.script_tableFirstColumn(MagicMock())
        assert plugin._tableCol == 0

    def test_space_speaks_row_summary(self):
        plugin = self._make_plugin(KUBECTL_PODS, current_line=2)
        plugin.script_toggleTableMode(MagicMock())
        plugin.script_tableNextRow(MagicMock())
        sys.modules['ui'].message.reset_mock()
        plugin.script_tableRowSummary(MagicMock())
        assert 'NAME web-7d4b9c6f5-x2m8q' in self._last_message()

    def test_control_up_announces_column_header(self):
        plugin = self._make_plugin(KUBECTL_PODS, current_line=2)
        plugin.script_toggleTableMode(MagicMock())
        plugin.script_tableNextRow(MagicMock())
        plugin.script_tableNextColumn(MagicMock())
        sys.modules['ui'].message.reset_mock()
        plugin.script_tableColumnHeader(MagicMock())
        assert self._last_message() == 'Header: READY'

    def test_escape_exits_and_unbinds(self):
        plugin = self._make_plugin(DOCKER_PS)
        plugin.script_toggleTableMode(MagicMock())
        sys.modules['ui'].message.reset_mock()
        gesture = MagicMock()
        plugin.script_exitTableMode(gesture)
        assert plugin._tableNavigator is None
        assert 'kb:downArrow' not in plugin._gestureMap
        assert 'kb:escape' not in plugin._gestureMap
        assert 'Table mode off' in self._last_message()
        gesture.send.assert_not_called()

    def test_table_scripts_pass_through_outside_mode(self):
        plugin = self._make_plugin(DOCKER_PS)
        gesture = MagicMock()
        plugin.script_tableNextRow(gesture)
        gesture.send.assert_called_once()

    def test_focus_loss_exits_table_mode(self):
        plugin = self._make_plugin(DOCKER_PS)
        plugin.script_toggleTableMode(MagicMock())
        assert plugin._tableNavigator is not None
        plugin.isTerminalApp = MagicMock(return_value=False)
        non_terminal = MagicMock()
        non_terminal.appModule.appName = 'notepad'
        plugin._updateGestureBindingsForFocus(non_terminal)
        assert plugin._tableNavigator is None
        assert 'kb:downArrow' not in plugin._gestureMap
