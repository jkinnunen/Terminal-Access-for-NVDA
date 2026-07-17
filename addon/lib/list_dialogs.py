# Terminal Access generic browsable list dialog.
# Shared foundation for the bookmark, section, AI turn, search result,
# and command finder dialogs.

"""Generic browsable list dialog and its pure data-prep helpers.

The dialog itself needs wx, but every piece of data transformation
(filtering, index mapping, text matching) lives in plain functions so
the behavior is unit-testable without a GUI.

Index-map contract: the dialog always reports activation with the
ORIGINAL row index, no matter how the visible list has been filtered.
"""


def build_display_rows(rows, predicate=None):
    """Filter rows for display while preserving original indices.

    Args:
        rows: List of tuples, one per row.
        predicate: Optional callable(row) -> bool. None means "show all".

    Returns:
        (display_rows, index_map) where index_map[i] is the index in
        *rows* of display_rows[i].
    """
    if predicate is None:
        return list(rows), list(range(len(rows)))
    display_rows = []
    index_map = []
    for original_index, row in enumerate(rows):
        if predicate(row):
            display_rows.append(row)
            index_map.append(original_index)
    return display_rows, index_map


def resolve_original_index(index_map, display_index):
    """Map a display-list selection back to the original row index.

    Args:
        index_map: Index map produced by build_display_rows().
        display_index: Selected position in the displayed list. wx uses
            -1 for "no selection".

    Returns:
        int original index, or None when nothing valid is selected.
    """
    if 0 <= display_index < len(index_map):
        return index_map[display_index]
    return None


def make_text_predicate(filter_text, columns=None):
    """Build a row predicate for type-to-filter search boxes.

    Args:
        filter_text: Text typed by the user. Matching is a
            case-insensitive substring test.
        columns: Optional tuple of column indices to search. None
            searches every column.

    Returns:
        A callable(row) -> bool, or None when filter_text is blank
        (meaning "no filtering").
    """
    needle = (filter_text or "").strip().lower()
    if not needle:
        return None

    def predicate(row):
        if columns is None:
            cells = row
        else:
            cells = [row[c] for c in columns if c < len(row)]
        return any(needle in str(cell).lower() for cell in cells)

    return predicate


def export_transcript_text(lines):
    """Convert raw terminal buffer lines into a plain-text transcript.

    Strips ANSI escape sequences from every line, drops None entries,
    and joins with newlines. Pure function so it is testable without wx.

    Args:
        lines: List of buffer lines (str or None).

    Returns:
        The transcript as a single string.
    """
    from lib.text_processing import ANSIParser

    return "\n".join(
        ANSIParser.stripANSI(line) for line in lines if line is not None
    )


def build_bookmark_rows(bookmarks):
    """Build (number, label) rows from a bookmark list.

    Args:
        bookmarks: List of dicts with "name" and optional "label".

    Returns:
        List of (name, label) tuples.
    """
    return [(bm["name"], bm.get("label", "")) for bm in bookmarks]


def build_ai_turn_rows(turns):
    """Build AI turn rows and per-role filter choices.

    Args:
        turns: List of dicts with "role", "line_num" (0-based), "preview".

    Returns:
        (rows, filter_choices) where rows are (role, line_display, preview)
        tuples with a 1-based line number, and filter_choices is a list of
        (role, predicate) pairs, one per distinct role.
    """
    rows = [
        (turn["role"], str(turn["line_num"] + 1), turn["preview"])
        for turn in turns
    ]
    roles = sorted(set(turn["role"] for turn in turns))
    filter_choices = [
        (role, lambda row, r=role: row[0] == r)
        for role in roles
    ]
    return rows, filter_choices


def build_search_rows(matches):
    """Build (number, line, content) rows from search matches.

    Args:
        matches: List of dicts with "num", "line_num", "text".

    Returns:
        List of (num, line, text) string tuples.
    """
    return [
        (str(match["num"]), str(match["line_num"]), match["text"])
        for match in matches
    ]


def build_url_rows(urls):
    """Build (index, url, line, context) rows from URL entries.

    Args:
        urls: List of UrlEntry-like objects with url, line_num, line_text.

    Returns:
        List of string tuples. The index is 1-based; context is the line
        text truncated to 80 characters.
    """
    rows = []
    for i, entry in enumerate(urls, start=1):
        context = (entry.line_text or "")[:80]
        rows.append((str(i), entry.url, str(entry.line_num), context))
    return rows


def collect_commands(plugin, default_gestures=None, layer_map=None):
    """Collect every Terminal Access command for the command finder.

    Introspects the plugin's script_* methods. The description comes
    from the script's docstring first line (NVDA's @script decorator
    copies the description there in production; the test decorator
    preserves the original docstring). Gesture bindings are gathered
    from the default gesture dict and the decorator metadata, and
    formatted with lib._runtime.gesture_label. The command layer key
    comes from the layer map. Both name punctuation keys by word
    (lib._runtime.KEY_WORDS), since this list exists to be read aloud and
    a bare symbol is silent at most punctuation levels.

    Args:
        plugin: The GlobalPlugin instance.
        default_gestures: Optional gesture -> script-name dict. Defaults
            to _DEFAULT_GESTURES from the plugin's module.
        layer_map: Optional gesture -> script-name dict for the command
            layer. Defaults to _COMMAND_LAYER_MAP from the plugin's module.

    Returns:
        List of dicts {name, description, gesture_display, layer_key},
        sorted by name.
    """
    import sys

    from lib._runtime import gesture_label, spell_key

    plugin_module = sys.modules.get(type(plugin).__module__)
    if default_gestures is None:
        default_gestures = getattr(plugin_module, "_DEFAULT_GESTURES", {})
    if layer_map is None:
        layer_map = getattr(plugin_module, "_COMMAND_LAYER_MAP", {})

    commands = []
    for attr in dir(type(plugin)):
        if not attr.startswith("script_"):
            continue
        method = getattr(plugin, attr, None)
        if not callable(method):
            continue
        name = attr[len("script_"):]

        doc = getattr(method, "__doc__", None) or ""
        description = doc.strip().split("\n")[0].strip()

        gestures = [
            gesture for gesture, script_name in default_gestures.items()
            if script_name == name
        ]
        for gesture in getattr(method, "__gestures__", []):
            if gesture not in gestures:
                gestures.append(gesture)
        gesture_display = ", ".join(
            gesture_label(gesture, name) for gesture in gestures
        )

        layer_key = ", ".join(sorted(
            "+".join(spell_key(part) for part in gesture[len("kb:"):].split("+"))
            for gesture, script_name in layer_map.items()
            if script_name == name
        ))

        commands.append({
            "name": name,
            "description": description,
            "gesture_display": gesture_display,
            "layer_key": layer_key,
        })

    commands.sort(key=lambda command: command["name"])
    return commands


try:
    import wx
    _wx_available = True
except ImportError:
    _wx_available = False


if _wx_available:
    class BrowsableListDialog(wx.Dialog):
        """Accessible list dialog with filtering and stable row indices.

        Presents rows in a report-mode ListCtrl. Enter or the Activate
        button fires on_activate with the ORIGINAL row index (stable
        across filtering), Escape closes. An optional filter dropdown
        and an optional type-to-filter search box re-populate the list
        while preserving original indices via an index map.
        """

        def __init__(self, parent, title, columns, rows, on_activate,
                filter_choices=None, extra_buttons=None,
                enable_search=False, search_columns=None,
                rows_provider=None, key_actions=None):
            """Initialize the BrowsableListDialog.

            Args:
                parent: Parent window.
                title: Dialog title.
                columns: List of (header, width) tuples.
                rows: List of tuples matching the columns. Ignored when
                    rows_provider is given.
                on_activate: Callable(original_row_index) fired on
                    Enter or the Activate button.
                filter_choices: Optional list of (label, predicate)
                    tuples for a filter dropdown. An "All" entry is
                    prepended automatically.
                extra_buttons: Optional list of (label, callback)
                    tuples for additional buttons. If a callback returns
                    True, the dialog closes; otherwise it stays open and
                    re-populates the list.
                enable_search: When True, show a type-to-filter box.
                search_columns: Optional tuple of column indices the
                    search box matches against (None = all columns).
                rows_provider: Optional callable() -> rows. When given,
                    the list is rebuilt from it on every repopulate so
                    mutations (such as deletions) stay in sync with the
                    underlying data source.
                key_actions: Optional dict mapping a wx key code to a
                    callable(original_row_index). Fired when that key is
                    pressed with a row selected, then the list re-populates.
            """
            super().__init__(
                parent,
                title=title,
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            )
            self._columns = list(columns)
            self._rows_provider = rows_provider
            self._rows = list(rows) if rows_provider is None else list(rows_provider())
            self._on_activate_cb = on_activate
            self._filter_choices = list(filter_choices or [])
            self._extra_buttons = list(extra_buttons or [])
            self._enable_search = enable_search
            self._search_columns = search_columns
            self._key_actions = dict(key_actions or {})
            self._index_map = []
            self._build_ui()
            self._repopulate()
            self.Raise()

        def _build_ui(self):
            sizer = wx.BoxSizer(wx.VERTICAL)

            if self._enable_search:
                search_sizer = wx.BoxSizer(wx.HORIZONTAL)
                search_sizer.Add(
                    # Translators: Label of the type-to-filter box in list dialogs
                    wx.StaticText(self, label=_("&Search:")),
                    flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4,
                )
                self._search_box = wx.TextCtrl(self)
                search_sizer.Add(self._search_box, proportion=1)
                sizer.Add(search_sizer, flag=wx.EXPAND | wx.ALL, border=8)
                self._search_box.Bind(wx.EVT_TEXT, self._on_filter_changed)
            else:
                self._search_box = None

            if self._filter_choices:
                filter_sizer = wx.BoxSizer(wx.HORIZONTAL)
                filter_sizer.Add(
                    # Translators: Label of the filter dropdown in list dialogs
                    wx.StaticText(self, label=_("&Filter:")),
                    flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=4,
                )
                self._filter_choice = wx.Choice(self)
                # Translators: Filter dropdown entry that shows every row
                self._filter_choice.Append(_("All"))
                for label, _predicate in self._filter_choices:
                    self._filter_choice.Append(label)
                self._filter_choice.SetSelection(0)
                filter_sizer.Add(self._filter_choice, proportion=1)
                sizer.Add(filter_sizer, flag=wx.EXPAND | wx.ALL, border=8)
                self._filter_choice.Bind(wx.EVT_CHOICE, self._on_filter_changed)
            else:
                self._filter_choice = None

            self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            for col_index, (header, width) in enumerate(self._columns):
                self._list.InsertColumn(col_index, header, width=width)
            sizer.Add(self._list, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            # Translators: Label of the default action button in list dialogs
            self._activate_btn = wx.Button(self, label=_("&Activate"))
            btn_sizer.Add(self._activate_btn, flag=wx.RIGHT, border=4)
            for label, callback in self._extra_buttons:
                btn = wx.Button(self, label=label)
                btn.Bind(
                    wx.EVT_BUTTON,
                    lambda event, cb=callback: self._on_extra_button(cb),
                )
                btn_sizer.Add(btn, flag=wx.RIGHT, border=4)
            # Translators: Label of the close button in list dialogs
            self._close_btn = wx.Button(self, wx.ID_CLOSE, label=_("&Close"))
            btn_sizer.Add(self._close_btn)
            sizer.Add(btn_sizer, flag=wx.ALIGN_RIGHT | wx.ALL, border=8)

            self.SetSizer(sizer)
            self.SetSize(600, 400)

            self._activate_btn.Bind(wx.EVT_BUTTON, self._on_activate)
            self._close_btn.Bind(wx.EVT_BUTTON, self._on_close)
            self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
            self._list.Bind(wx.EVT_KEY_DOWN, self._on_key)

        def _current_predicate(self):
            """Combine the dropdown and search box into one predicate."""
            predicates = []
            if self._filter_choice is not None:
                selection = self._filter_choice.GetSelection()
                if selection > 0:
                    predicates.append(self._filter_choices[selection - 1][1])
            if self._search_box is not None:
                text_predicate = make_text_predicate(
                    self._search_box.GetValue(), self._search_columns
                )
                if text_predicate is not None:
                    predicates.append(text_predicate)
            if not predicates:
                return None
            return lambda row: all(p(row) for p in predicates)

        def _repopulate(self):
            if self._rows_provider is not None:
                self._rows = list(self._rows_provider())
            display_rows, self._index_map = build_display_rows(
                self._rows, self._current_predicate()
            )
            self._list.DeleteAllItems()
            for row in display_rows:
                item = self._list.InsertItem(
                    self._list.GetItemCount(), str(row[0])
                )
                for col_index, cell in enumerate(row[1:], start=1):
                    self._list.SetItem(item, col_index, str(cell))
            if display_rows:
                self._list.Select(0)
                self._list.Focus(0)

        def _selected_original_index(self):
            return resolve_original_index(
                self._index_map, self._list.GetFirstSelected()
            )

        def _on_activate(self, event):
            original_index = self._selected_original_index()
            if original_index is not None:
                self._on_activate_cb(original_index)
                self.Close()

        def _on_extra_button(self, callback):
            original_index = self._selected_original_index()
            if original_index is not None:
                if callback(original_index):
                    self.Close()
                else:
                    self._repopulate()

        def _on_filter_changed(self, event):
            self._repopulate()

        def _on_close(self, event):
            self.Close()

        def _on_key(self, event):
            key = event.GetKeyCode()
            if key == wx.WXK_RETURN:
                self._on_activate(event)
            elif key == wx.WXK_ESCAPE:
                self.Close()
            elif key in self._key_actions:
                original_index = self._selected_original_index()
                if original_index is not None:
                    self._key_actions[key](original_index)
                    self._repopulate()
            else:
                event.Skip()
else:
    # Placeholder so imports don't break in environments without wx.
    BrowsableListDialog = None
