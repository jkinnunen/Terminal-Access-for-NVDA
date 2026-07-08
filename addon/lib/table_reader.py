"""Column-aware table reading for terminal output.

Detects tabular regions in a terminal buffer (docker ps, kubectl get pods,
ls -l, psql and markdown pipe tables) and extracts cells so a screen reader
user can navigate column by column with header announcements instead of
hearing whole rows as run-on text.

Pure logic module: no NVDA imports except ANSIParser from lib.text_processing.

Limitations (v1):
- Aligned-table cells are extracted by plain character slicing, so alignment
  with wide (CJK) characters is approximate.
- Analysis is capped at MAX_LINES lines and MAX_LINE_CHARS characters per
  line for safety on huge buffers.
"""
from collections import namedtuple

from lib.text_processing import ANSIParser

# Safety caps for analysis.
MAX_LINES = 500
MAX_LINE_CHARS = 1000

# Minimum fraction of shared gap columns for a line to join an aligned block.
_MIN_GAP_SHARE = 0.5

# Characters allowed in a pipe-table separator row such as ----+----+----.
_SEPARATOR_CHARS = frozenset("-+=|: ")


TableRegion = namedtuple(
    "TableRegion", ["first_line", "last_line", "column_spans", "kind"]
)
"""A contiguous table inside a buffer.

first_line/last_line are inclusive buffer line indices. column_spans is a
list of (start_col, end_col) character offsets, valid only for kind
"aligned"; end_col is exclusive. kind is "aligned" or "pipe".
"""


def _clean(line):
    """Strip ANSI codes and cap length for safe analysis."""
    return ANSIParser.stripANSI(line)[:MAX_LINE_CHARS]


def _gap_columns(line):
    """Return the set of character positions inside runs of 2+ spaces.

    Trailing whitespace is ignored so varying line lengths do not count
    as gaps.
    """
    line = line.rstrip()
    gaps = set()
    run_start = None
    for pos, char in enumerate(line):
        if char == " ":
            if run_start is None:
                run_start = pos
        else:
            if run_start is not None and pos - run_start >= 2:
                gaps.update(range(run_start, pos))
            run_start = None
    return gaps


def _shares_gaps(gaps_a, gaps_b):
    """True when two gap sets overlap by at least _MIN_GAP_SHARE."""
    if not gaps_a or not gaps_b:
        return False
    overlap = len(gaps_a & gaps_b)
    return overlap / min(len(gaps_a), len(gaps_b)) >= _MIN_GAP_SHARE


def _is_separator_line(line):
    """True for rule rows such as ----+----+---- or | --- | --- |."""
    stripped = line.strip()
    return (
        bool(stripped)
        and set(stripped) <= _SEPARATOR_CHARS
        and any(char in "-=" for char in stripped)
    )


def _is_pipe_table_line(line):
    """True when a line can belong to a pipe-delimited table."""
    return line.count("|") >= 1 or _is_separator_line(line)


def _pipe_cells(line):
    """Split a pipe-table row into stripped cells, dropping outer pipes."""
    parts = [part.strip() for part in line.split("|")]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _column_spans(block):
    """Compute (start, end) column spans for an aligned block.

    A position is a separator when it lies in a run of 2+ positions that
    are spaces in every row (positions past a row's end count as spaces).
    Columns are the remaining runs that contain at least one non-space.
    """
    width = max(len(line) for line in block)
    if width == 0:
        return []
    all_space = [
        all(pos >= len(line) or line[pos] == " " for line in block)
        for pos in range(width)
    ]
    separator = [False] * width
    pos = 0
    while pos < width:
        if all_space[pos]:
            run_end = pos
            while run_end < width and all_space[run_end]:
                run_end += 1
            if run_end - pos >= 2:
                for sep_pos in range(pos, run_end):
                    separator[sep_pos] = True
            pos = run_end
        else:
            pos += 1

    spans = []
    start = None
    for pos in range(width + 1):
        inside = pos < width and not separator[pos]
        if inside and start is None:
            start = pos
        elif not inside and start is not None:
            if any(not all_space[cell_pos] for cell_pos in range(start, pos)):
                spans.append((start, pos))
            start = None
    return spans


class TableDetector:
    """Finds the contiguous table containing a given buffer line."""

    def detect(self, lines, start_line):
        """Return the TableRegion containing start_line, or None.

        Args:
            lines: The buffer as a list of strings (may contain ANSI codes).
            start_line: 0-based index of the line the user is on.
        """
        if not lines or not 0 <= start_line < len(lines):
            return None
        start_clean = _clean(lines[start_line])
        if start_clean.count("|") >= 2:
            return self._detect_pipe(lines, start_line, start_clean)
        return self._detect_aligned(lines, start_line, start_clean)

    def _detect_pipe(self, lines, start_line, start_clean):
        first = start_line
        while (
            first > 0
            and start_line - first + 1 < MAX_LINES
            and _is_pipe_table_line(_clean(lines[first - 1]))
        ):
            first -= 1
        last = start_line
        while (
            last < len(lines) - 1
            and last - first + 1 < MAX_LINES
            and _is_pipe_table_line(_clean(lines[last + 1]))
        ):
            last += 1
        if last - first + 1 < 2:
            return None
        if len(_pipe_cells(start_clean)) < 2:
            return None
        return TableRegion(first, last, [], "pipe")

    def _detect_aligned(self, lines, start_line, start_clean):
        start_gaps = _gap_columns(start_clean)
        if not start_gaps:
            return None

        first = start_line
        edge_gaps = start_gaps
        while first > 0 and start_line - first + 1 < MAX_LINES:
            candidate = _clean(lines[first - 1])
            candidate_gaps = _gap_columns(candidate)
            if not _shares_gaps(candidate_gaps, edge_gaps):
                break
            first -= 1
            edge_gaps = candidate_gaps

        last = start_line
        edge_gaps = start_gaps
        while last < len(lines) - 1 and last - first + 1 < MAX_LINES:
            candidate = _clean(lines[last + 1])
            candidate_gaps = _gap_columns(candidate)
            if not _shares_gaps(candidate_gaps, edge_gaps):
                break
            last += 1
            edge_gaps = candidate_gaps

        if last - first + 1 < 2:
            return None
        block = [_clean(lines[index]) for index in range(first, last + 1)]
        spans = _column_spans(block)
        if len(spans) < 2:
            return None
        return TableRegion(first, last, spans, "aligned")


class TableNavigator:
    """Cell-level access and movement within a detected TableRegion.

    Row 0 is the first table row and is assumed to be the header row.
    Separator rows in pipe tables (markdown/psql rules) are skipped, so
    row 1 is the first data row in every table kind.
    """

    def __init__(self, region, lines):
        self._region = region
        cleaned = [
            _clean(lines[index]) if 0 <= index < len(lines) else ""
            for index in range(region.first_line, region.last_line + 1)
        ]
        if region.kind == "pipe":
            self._rows = [
                _pipe_cells(line)
                for line in cleaned
                if not _is_separator_line(line)
            ]
            self._lines = None
        else:
            self._rows = None
            self._lines = cleaned

    @property
    def n_rows(self):
        if self._rows is not None:
            return len(self._rows)
        return len(self._lines)

    @property
    def n_cols(self):
        if self._rows is not None:
            return len(self._rows[0]) if self._rows else 0
        return len(self._region.column_spans)

    def cell(self, row_idx, col_idx):
        """Return the stripped cell text, or "" when out of range."""
        if not 0 <= row_idx < self.n_rows or not 0 <= col_idx < self.n_cols:
            return ""
        if self._rows is not None:
            row = self._rows[row_idx]
            return row[col_idx] if col_idx < len(row) else ""
        start, end = self._region.column_spans[col_idx]
        return self._lines[row_idx][start:end].strip()

    def header(self, col_idx):
        """Return the header cell (first row) for a column."""
        return self.cell(0, col_idx)

    def move(self, row_idx, col_idx, drow, dcol):
        """Return the clamped (new_row, new_col), or None at an edge.

        None is returned only when the position is already at the edge in
        the requested direction; larger deltas clamp to the table bounds.
        """
        if self.n_rows == 0 or self.n_cols == 0:
            return None
        if drow > 0 and row_idx >= self.n_rows - 1:
            return None
        if drow < 0 and row_idx <= 0:
            return None
        if dcol > 0 and col_idx >= self.n_cols - 1:
            return None
        if dcol < 0 and col_idx <= 0:
            return None
        new_row = min(max(row_idx + drow, 0), self.n_rows - 1)
        new_col = min(max(col_idx + dcol, 0), self.n_cols - 1)
        return (new_row, new_col)

    def announce_for(self, row_idx, col_idx):
        """Return the speech text for a cell, e.g. "STATUS: Running"."""
        value = self.cell(row_idx, col_idx)
        if row_idx == 0:
            return "Header: {}".format(value)
        return "{}: {}".format(self.header(col_idx), value)

    def row_summary(self, row_idx):
        """Return all cells of a row as "HEADER value, HEADER value, ..."."""
        return ", ".join(
            "{} {}".format(self.header(col), self.cell(row_idx, col))
            for col in range(self.n_cols)
        )
