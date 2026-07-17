# Terminal Buffer Virtual Window

## Overview

Give the user a key that pulls the terminal's buffer into a browsable virtual
window: a frozen snapshot they can arrow through line by line, navigate by
semantic heading, find within, copy from, and leave with Escape. A companion
modal "jump to line" list dialog lets the user land the review cursor on any
line in the live terminal, so reaching a spot found in the snapshot is one
dialog away.

Reading a terminal today means driving the review cursor through a live buffer
that can move under you. A snapshot cannot move, reads with ordinary arrow keys,
and exposes structure (which command produced this? where did the error start?)
that the review cursor cannot express.

### Architecture decision: read-only browse window + modal jump dialog

An earlier draft assumed the user could press Enter on a line *inside* the
browse window to jump back to the live terminal. That is impossible, and it was
confirmed against the NVDA source before any code was written:

- `ui.browseableMessage` renders the HTML in a **modeless MSHTML (Trident)
  dialog** via `winBindings.mshtml.ShowHTMLDialogEx(..., HTMLDLG_MODELESS, ...)`
  (`nvda/source/ui.py:223-230`). The call is fire-and-forget: it returns `None`,
  with no window handle, no close callback, and no way to register a gesture
  scoped to that window. NVDA browse mode engages because it is a real MSHTML
  document, but that browse mode is NVDA-internal. Pressing Enter on an anchor
  performs the link's default action *inside MSHTML* (navigate the href); it
  cannot call back into the add-on. **The window is opaque once opened.**
- Independently, the `_searchJumpTarget`/`_reapplySearchJump` review-cursor
  pattern is driven by the terminal's `event_gainFocus`
  (`terminalAccess.py:1099-1114`), which the existing **modal** list dialogs
  trigger on close. A modeless browse window gives the add-on no close signal,
  so that pattern cannot be wired to it.

Therefore the feature is split, reusing patterns already shipped in this
codebase:

- **Read** is `ui.browseableMessage(isHtml=True)`: a frozen, escaped, headed
  snapshot. Arrow-by-line, `H` heading quick-nav, browse-mode find, and copy all
  work here and are the whole point of the primitive.
- **Jump** is a **modal `wx` list dialog** (the `listSections` /
  `BookmarkListDialog` / `listUrls` pattern), which already closes-then-lands the
  review cursor correctly via `_searchJumpTarget`/`_reapplySearchJump` because it
  is modal. "Refresh" is simply re-opening; there is no in-window mutation.

This keeps every capability the user asked for (browse the whole buffer, navigate
by structure, reach a line in the live terminal) without depending on an
interaction the primitive cannot support.

### Considered and deferred: WebView2 (wx.html2 Edge backend)

A custom `wx.Dialog` hosting a WebView2 control would make the in-window jump
possible (`EVT_WEBVIEW_NAVIGATING` is interceptable) and would allow
programmatic close/refresh. Evaluated 2026-07-17 against the real environment
and deferred. Findings, so this is not re-litigated from scratch:

- **Blocker: NVDA ships `wx._html2.pyd` but NOT `WebView2Loader.dll`** (verified
  against the installed NVDA under `C:\Program Files\NVDA`). wxPython needs that
  loader to instantiate the Edge backend; without it `wx.html2.WebView` falls
  back to Trident, the same MSHTML engine `browseableMessage` already uses, with
  none of the benefits. The add-on would have to ship the DLL itself: native
  code, per-architecture (x86/x64/ARM64), reopening exactly the multi-arch
  binary distribution problem 2.0.0 eliminated. CLAUDE.md: do not reintroduce
  native code paths. (The WebView2 *runtime* is broadly present on updated
  Windows 10/11 and was present on the dev machine; the missing piece is the
  loader inside NVDA's process, not the runtime.)
- **Cold start**: environment + control init + navigation is realistically 1-2s
  to readable on first open, vs low hundreds of ms for the MSHTML dialog. For a
  keystroke-invoked reading window this is very noticeable.
- **Memory**: each WebView2 control spawns a family of `msedgewebview2.exe`
  processes (~100-300MB combined) for the life of the window; MSHTML renders
  in-process.
- **Large documents**: raw DOM rendering favors Chromium, but the dominant cost
  for a screen reader is NVDA's browse-mode virtual buffer build, which is
  roughly linear in node count on either engine. WebView2 does not materially
  help the reading path this feature exists for.
- **Unproven wiring**: NVDA reading an embedded WebView2 inside NVDA's own wx
  dialog has support code (`Chrome_WidgetWin_0` handling in
  `nvda/source/NVDAObjects/IAccessible/wx.py`) but is exactly the class of
  focus/buffer behaviour CLAUDE.md says cannot be trusted until verified in real
  NVDA.

**Revisit trigger**: if, after shipping, the two-door workflow (read window +
jump dialog) genuinely grates in daily use, WebView2 is the v2 candidate. By
then the Task 3 gate measurements will also say how large a snapshot either
engine can hold. Until then: read-only `browseableMessage` + modal jump dialog.

### What this is NOT: the search-scope correction

The feature was originally motivated by an assumption that search only covers
the visible window and that virtualizing would widen it. That assumption is
incorrect, and the plan must not be justified on it:

- `OutputSearchManager._read_terminal_text` calls
  `makeTextInfo(textInfos.POSITION_ALL)` (`addon/lib/search.py:218`). NVDA maps
  `POSITION_ALL` to the UIA `documentRange`
  (`nvda/source/NVDAObjects/UIA/__init__.py:505`), which on Windows Terminal and
  modern conhost spans **the whole buffer including scrollback**, not the
  viewport. Search then scans the most recent `MAX_SEARCH_LINES = 50000` lines.
  The comment at `search.py:164` says as much: "so a huge scrollback cannot make
  a single search unbounded."
- Corroborating evidence: the 2.0.0-beta.3 freeze was 4,999 UIA calls over 5,000
  lines, orders of magnitude more than a viewport.
- **The one exception:** the legacy console. NVDA's `WinConsole._getText` returns
  `winConsoleHandler.getConsoleVisibleLines()`, which reads only
  `srWindow.Top..srWindow.Bottom` (the viewport rectangle). There, search really
  is visible-only.

**Crucially, the virtual window cannot fix the exception**, because it reads the
same `POSITION_ALL`/`_getBufferLines()` source that search does. Same source,
same scope. Widening scope beyond what the terminal exposes would require an
accumulating transcript (capturing output continuously into our own buffer),
which is explicitly **out of scope**: it grows without bound, does work on every
text change against the main-thread safety rule, and TUI apps that repaint
(vim, htop, lazygit) would poison it with redraw noise.

The two genuine search-adjacent wins we *do* get:

1. The snapshot is frozen, so matches cannot shift under the user the way live
   results did before `refresh_search_if_stale()`.
2. Browse mode brings NVDA's own find and quick navigation for free.

### Acceptance criteria

- A key opens the current terminal's buffer in a browsable window whose title
  names the terminal and makes clear it is a frozen snapshot.
- Arrow keys read line by line; `H` moves by semantic heading; browse-mode find
  and copy work.
- Escape closes the window.
- A companion modal "jump to line" list dialog lands the review cursor on the
  chosen line in the live terminal (this is the jump-back path; it is NOT Enter
  inside the browse window, which the primitive cannot support).
- Terminal output is HTML-escaped; no markup a program prints can render.
- The buffer read, HTML build, and sanitization never block NVDA's main thread.
- Every gesture is documented in the user guide with punctuation named as words.

## Context (from discovery)

**Files/components involved:**

- `addon/globalPlugins/terminalAccess.py` — gesture maps (`_DEFAULT_GESTURES`,
  `_COMMAND_LAYER_MAP`, `_CONFLICTING_GESTURES`), scripts, `_getBufferLines()`
- `addon/lib/section_tokenizer.py` — `SectionTokenizer.tokenize()` /
  `get_spans()` returning `SectionSpan(start_line, end_line, category)`
- `addon/lib/ai_turn_tokenizer.py` — AI turn structure for AI CLI profiles
- `addon/lib/line_resolve.py` — `resolve_line_by_content()` for the jump back
- `addon/lib/search.py` — `_getBufferLines()` read path, `MAX_SEARCH_LINES`
- `addon/lib/table_reader.py` — existing heuristic column detection
- `addon/lib/search.py` (`UrlExtractorManager`) — URL detection for links
- `addon/doc/en/readme.md` — user guide
- `addon/lib/_runtime.py` — `KEY_WORDS`, `gesture_label`

**Related patterns found:**

- `ui.browseableMessage(message, title=None, isHtml=False, closeButton=False,
  copyButton=False, sanitizeHtmlFunc=nh3.clean)` (`nvda/source/ui.py:143`) is
  NVDA's built-in browse-mode HTML window. It supplies the window, the title,
  browse-mode arrowing, heading quick-nav, and a copy button. We do not write a
  virtualBuffer. Its docstring explicitly warns to sanitize untrusted sources.
- `SectionTokenizer` categories: `prompt`, `error`, `warning`, `stack_trace`,
  `progress`, `timestamp`, `heading`, `output`. This is the heading structure,
  already built and already tested.
- `resolve_line_by_content()` is the project's answer to "never jump to a
  terminal line by counting lines" (CLAUDE.md). The jump back reuses it rather
  than inventing a second mechanism.
- `_CONFLICTING_GESTURES` + the Gesture Conflicts settings section is the
  established way to ship a gesture that shadows an NVDA command (see NVDA+C).

**Dependencies identified:**

- `nh3` is bundled with NVDA (used as `browseableMessage`'s default sanitizer).
  We escape first and do not rely on it alone.
- `ui.browseableMessage` is unavailable on the secure desktop; it warns and
  returns. The feature must degrade gracefully.

### Gesture decision

`NVDA+Enter` (direct) and `Enter` (command layer) **open the browse window**.
(Enter is no longer "symmetric" with an in-window jump, since that interaction
is impossible; it simply opens the window.) The modal jump-to-line dialog gets
its own binding, `Shift+Enter` in the command layer, verified free below.

**Conflict, and why it is acceptable:** `kb(laptop):NVDA+enter` is bound in NVDA
core to `script_review_activate`, "performs the default action on the current
navigator object" (`nvda/source/globalCommands.py:1759`). Desktop layout uses
`NVDA+numpadEnter`, so it is free there. The exposure is narrow because
`getScript()` returns None outside terminals, so we only shadow it inside a
supported terminal, where activating a navigator object is rarely meaningful.
Mitigation: add `kb:NVDA+enter` to `_CONFLICTING_GESTURES` so laptop-layout users
see it in NVDA Gesture Conflicts and can unbind it, exactly as NVDA+C is handled.

`Enter` is free in `_COMMAND_LAYER_MAP` (verified: the layer binds every letter,
plus `escape`, `home`, `end`, `pageUp`, `pageDown`, `f1`, `f3`, but not `enter`).

Neither gesture contains punctuation, so both are already compliant with the
naming convention.

## Development Approach

- **testing approach**: TDD (red/green/refactor), per project standing rule
- complete each task fully before moving to the next
- make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- run tests after each change: `py -m pytest tests/ -q --no-cov --timeout=120`
- maintain backward compatibility

### Project-specific constraints

- **Main-thread safety** (CLAUDE.md): the buffer read is a COM/UIA call and the
  HTML build is real work over up to 50,000 lines. Both go off the main thread
  with `wx.CallAfter` to present. Never block NVDA's main thread. **Note the
  hidden main-thread cost:** `ui.browseableMessage` sanitizes on the calling
  thread (`sanitizeHtmlFunc(message)` at `nvda/source/ui.py:201`), which runs
  *after* our `wx.CallAfter`, on the main thread, over the whole multi-MB HTML
  string. Because we already escape every line on the worker thread, we pass
  `sanitizeHtmlFunc=lambda s: s` (identity) so no heavy sanitization runs on the
  main thread. Our own escaping is the security boundary, not `nh3.clean`.
- **Never resolve a terminal line by counting** (CLAUDE.md): the jump back uses
  `resolve_line_by_content()`, not line arithmetic.
- **Mocked tests can pass while real NVDA misbehaves** (CLAUDE.md): browse-mode
  behaviour (does Escape close? does `H` navigate? does a 50k-line document
  stay responsive?) is NOT unit-testable. Verify in real NVDA at Task 3, before
  building the rest on top.
- **Punctuation named as words** (CLAUDE.md): all new guide text and UI labels.
- **Docs match code**: `tests/test_doc_gesture_consistency.py` will fail if the
  guide names a gesture that is not bound. Guide and bindings land together.

## Testing Strategy

- **unit tests**: required for every task, listed as separate checklist items
- **no e2e harness**: this project has no Playwright/Cypress layer. The
  equivalent is the real-NVDA manual protocol in
  `docs/testing/RELEASE_VERIFICATION.md`, which gains a section for this feature
  (Task 11). Treat that protocol as the e2e gate.
- **security tests are mandatory, not optional** (Task 2): terminal output is
  attacker-influenced. Test that markup a program prints cannot render.

## Progress Tracking

- mark completed items with `[x]` immediately when done
- add newly discovered tasks with ➕ prefix
- document issues/blockers with ⚠️ prefix
- update plan if implementation deviates from original scope

## What Goes Where

- **Implementation Steps** (`[ ]`): code, tests, documentation in this repo
- **Post-Completion** (no checkboxes): real-NVDA verification, release decisions

## Implementation Steps

The make-or-break unknown (can the add-on intercept activation inside the browse
window?) was already resolved during planning against the NVDA source: it
cannot, so the architecture is a read-only browse window plus a modal jump
dialog (see Overview). Task 3 remains a real-NVDA gate for the *reading*
assumptions (Escape, `H` nav, large-buffer responsiveness, sanitizer cost) that
the source cannot settle, before structure, tables, or links are built on top.

### Task 1: Buffer snapshot model

Separate "what we captured" from "how we render it", so rendering and jumping
are testable without a terminal.

**Files:**
- Create: `addon/lib/buffer_snapshot.py`
- Create: `tests/test_buffer_snapshot.py`

- [ ] create `BufferSnapshot` holding `lines`, `terminal_name`, `captured_at`,
      `total_lines`, `truncated` (bool), `first_line_num` (absolute)
- [ ] add `capture(terminal, lines, max_lines=MAX_SNAPSHOT_LINES)` classmethod
      keeping only the most recent `max_lines` and setting `truncated` /
      `first_line_num` so absolute line numbers stay correct
- [ ] add `MAX_SNAPSHOT_LINES` as a cap, with a comment that 50000 (matching
      `search.MAX_SEARCH_LINES`) is a CEILING to disprove at the Task 3 real-NVDA
      gate, not a default to ship; default it low and raise only to the measured
      responsive limit
- [ ] add `line_at(index)` returning the text for an absolute line number
- [ ] write tests for capture under the cap (not truncated, first_line_num 0)
- [ ] write tests for capture over the cap (truncated, absolute numbers preserved)
- [ ] write tests for empty and single-line buffers
- [ ] run tests - must pass before task 2

### Task 2: HTML escaping of untrusted terminal output

Deliberately before rendering: escaping is the security boundary and must exist
before anything builds HTML.

**Files:**
- Create: `addon/lib/buffer_html.py`
- Create: `tests/test_buffer_html.py`

- [ ] create `escape_line(text)` wrapping `html.escape(text, quote=True)`
- [ ] strip ANSI via the shared `_runtime.strip_ansi` before escaping, so colour
      codes do not appear as literal text
- [ ] strip control characters that survive ANSI stripping (NUL, BEL, backspace)
- [ ] strip Unicode bidi override characters (U+202A-U+202E, U+2066-U+2069) to
      prevent Trojan-Source-style visual spoofing in the rendered snapshot
- [ ] write tests that `<script>alert(1)</script>` in terminal output renders as
      inert text, not markup
- [ ] write tests that bidi override characters are removed
- [ ] write tests that `&`, `<`, `>`, `"`, `'` each escape correctly
- [ ] write tests that an unterminated ANSI sequence does not leak
- [ ] write tests that a line of 10,000 characters is handled without error
- [ ] run tests - must pass before task 3

### Task 3: Minimal window + REAL NVDA VERIFICATION GATE ⚠️

The smallest thing that proves the mechanism. Nothing else is built until the
assumptions below are confirmed in real NVDA.

**Files:**
- Modify: `addon/lib/buffer_html.py`
- Modify: `addon/globalPlugins/terminalAccess.py`
- Create: `tests/test_virtual_window.py`

- [ ] add `render_plain(snapshot)` producing escaped `<p>` per line, no headings
- [ ] add `window_title(snapshot)` (see Technical Details for exact wording)
- [ ] add `script_showBufferWindow` gated on `isTerminalApp()`, else `gesture.send()`
- [ ] read the buffer off the main thread; sanitize/escape on that worker thread,
      then `wx.CallAfter` to `ui.browseableMessage(html, title=..., isHtml=True,
      copyButton=True, sanitizeHtmlFunc=lambda s: s)` so no heavy sanitization
      runs on the main thread (see Development Approach)
- [ ] announce and return gracefully when the buffer is empty or unreadable
- [ ] bind `kb:NVDA+enter` in `_DEFAULT_GESTURES` and `kb:enter` in
      `_COMMAND_LAYER_MAP`
- [ ] add `kb:NVDA+enter` to `_CONFLICTING_GESTURES` with a comment naming
      NVDA's laptop-layout review-activate
- [ ] write tests that the script no-ops outside a terminal (gesture.send called)
- [ ] write tests that `browseableMessage` is called with `isHtml=True`, the
      expected title, and an identity `sanitizeHtmlFunc` (mock it)
- [ ] write tests that the read happens off the main thread
- [ ] run tests - must pass before task 4
- [ ] **VERIFY IN REAL NVDA before Task 4** and record findings in this plan:
  - [ ] Escape closes the window
  - [ ] arrow keys read line by line
  - [ ] `H` moves by heading (proves browse mode over our HTML behaves)
  - [ ] the title is announced and identifies the terminal
  - [ ] a large buffer opens without freezing; **measure and record the timing**
        at 5k, 20k, and 50k lines, since the sanitizer and MSHTML build are the
        suspect costs
  - [ ] NVDA+Enter still activates navigator objects *outside* terminals on the
        laptop layout
  - [ ] ⚠️ set `MAX_SNAPSHOT_LINES` from the measured ceiling (default it LOW,
        raise only to what stays responsive) and update Task 1 + the guide

### Task 4: Semantic headings from SectionTokenizer

**Files:**
- Modify: `addon/lib/buffer_html.py`
- Modify: `tests/test_buffer_html.py`

- [ ] add `render(snapshot, sections)` building on `SectionTokenizer.get_spans()`
- [ ] emit `<h1>` for the terminal, `<h2>` per `prompt` span, `<h3>` for `error`,
      `warning`, and `stack_trace` spans
- [ ] render `output`, `progress`, `timestamp` spans as plain `<p>` (NOT headings:
      a heading per output span is noise and would make `H` useless)
- [ ] give each heading a stable `id` carrying its absolute line number, for the
      Task 5 jump back
- [ ] write tests that a prompt span becomes an `<h2>`
- [ ] write tests that error/warning/stack_trace spans become `<h3>`
- [ ] write tests that output spans produce no heading
- [ ] write tests that heading text is escaped (a prompt containing `<b>`)
- [ ] write tests for a buffer with no prompts (no h2, still renders)
- [ ] run tests - must pass before task 5

### Task 5: Modal "jump to line" dialog

The jump-back path. A separate modal dialog, NOT interaction inside the browse
window (which the primitive cannot support, see Overview). This reuses the
shipped `listSections` / `BookmarkListDialog` pattern: a modal `wx` list whose
close returns focus to the terminal and fires `event_gainFocus`, which is what
makes `_searchJumpTarget` / `_reapplySearchJump` work.

**Files:**
- Modify: `addon/globalPlugins/terminalAccess.py`
- Modify: `addon/lib/list_dialogs.py` (reuse the browsable list dialog)
- Modify: `tests/test_virtual_window.py`

- [ ] build the list from the same tokenized snapshot: one entry per line, each
      showing its heading context (e.g. "line 812, under: npm run build") so the
      list is navigable by structure, not just line number
- [ ] add `script_jumpToBufferLine` on the command layer (`Shift+Enter`) and a
      direct gesture; open the modal list dialog
- [ ] on selection, close the dialog and resolve the target via
      `resolve_line_by_content()` (NEVER by counting lines)
- [ ] set `_searchJumpTarget` and reuse `_reapplySearchJump` so the review cursor
      survives the focus transition (see CLAUDE.md), exactly as the section list
      already does
- [ ] announce the landed line
- [ ] fall back with a spoken message when the line has scrolled out of history
      OR the terminal is no longer focused/alive
- [ ] write tests that selection resolves by content, not by line number
- [ ] write tests for the scrolled-out-of-history fallback
- [ ] write tests for the terminal-gone fallback
- [ ] write tests that the review cursor lands on the matched line text
- [ ] run tests - must pass before task 6

### Task 6: Open the browse window near the newest output

`browseableMessage` renders `message.html` from the top and takes no scroll or
fragment parameter (`nvda/source/ui.py:192-202`), so we cannot open the browse
window positioned at the review cursor. What we CAN do is order the snapshot so
the most useful content is reachable, and let the modal jump dialog (Task 5) be
the "go to a specific place" path.

**Files:**
- Modify: `addon/lib/buffer_html.py`
- Modify: `tests/test_buffer_html.py`

- [ ] add a short table-of-contents block at the top of the rendered HTML:
      links to each command (h2) and each error (h3), so `H` and the TOC both
      reach structure immediately without scrolling 50k lines
- [ ] confirm (real NVDA, folded into the Task 3 gate re-run) whether an
      `#fragment` in the initial HTML auto-scrolls; if it does, open at the
      newest prompt, and if it does not, the TOC covers the need
- [ ] write tests that the TOC lists every command and error heading
- [ ] write tests that the TOC entries are escaped
- [ ] write tests that a buffer with no headings still renders (no empty TOC)
- [ ] run tests - must pass before task 7

### Task 7: Real HTML tables for columnar output

**Files:**
- Modify: `addon/lib/buffer_html.py`
- Modify: `addon/lib/table_reader.py` (extract column detection if needed)
- Modify: `tests/test_buffer_html.py`

- [ ] reuse `table_reader`'s column detection over candidate spans
- [ ] render detected tables as `<table>` with `<th>` headers and `<td>` cells so
      NVDA's native table navigation works
- [ ] escape every cell
- [ ] fall back to `<p>` lines when detection is not confident (the heuristic is
      already marked experimental; a wrong table is worse than no table)
- [ ] write tests that `docker ps`-style output becomes a table with headers
- [ ] write tests that ambiguous output does NOT become a table
- [ ] write tests that cell content is escaped
- [ ] run tests - must pass before task 8

### Task 8: Real links for URLs

**Files:**
- Modify: `addon/lib/buffer_html.py`
- Modify: `tests/test_buffer_html.py`

- [ ] reuse `UrlExtractorManager`'s detection to wrap URLs in `<a href>`
- [ ] reuse the existing shared scheme check; refuse `file://`, `javascript:`,
      and `data:` exactly as the URL list already does
- [ ] escape the href attribute as well as the link text
- [ ] write tests that an http/https URL becomes a link
- [ ] write tests that `javascript:` and `data:` URLs do NOT become links
- [ ] write tests that a URL containing `"` cannot break out of the attribute
- [ ] run tests - must pass before task 9

### Task 9: Filtered views

A modeless browse window cannot be mutated or closed by the add-on, so there is
no in-window "refresh": re-opening simply captures a fresh snapshot (opening the
window again is the refresh). Filters are separate render modes, each opening
its own snapshot window.

**Files:**
- Modify: `addon/globalPlugins/terminalAccess.py`
- Modify: `addon/lib/buffer_html.py`
- Modify: `tests/test_virtual_window.py`

- [ ] add filtered renders: errors only, and commands only (prompt spans)
- [ ] add an "errors only" open command in the command layer; verify the binding
      is free before adding (`Shift+Enter` is taken by Task 5's jump dialog, so
      pick another free layer key and record it here)
- [ ] state the active filter in the window title
- [ ] state that re-opening captures a fresh snapshot (documented in Task 10, not
      a code behaviour to build)
- [ ] write tests that the errors-only view contains only error/warning spans
- [ ] write tests that the commands-only view contains only prompt spans
- [ ] write tests that a filter with no matches announces rather than opening empty
- [ ] run tests - must pass before task 10

### Task 10: User guide documentation

Extensive, per the request, and following the punctuation convention.

**Files:**
- Modify: `addon/doc/en/readme.md`
- Modify: `tests/test_doc_gesture_consistency.py` (only if new patterns appear)

- [ ] add a "Buffer Window" section after "Command Layer" covering: what it is,
      the key to open it, arrowing, `H` heading navigation, browse-mode find,
      copy, and Escape to close
- [ ] document the separate "jump to line" list dialog as the way to move the
      review cursor to a line found in the snapshot, and be explicit that the
      browse window itself is read-only (so users do not press Enter in it
      expecting to jump)
- [ ] document the heading structure (terminal / command / error) so users know
      what `H` will land on
- [ ] document the tables and links behaviour, marking column detection
      experimental (consistent with the existing table mode caveat)
- [ ] document filters and refresh
- [ ] **document the snapshot caveat honestly**: it is frozen at the moment you
      opened it, new output does not appear until refresh, and it shows the most
      recent N lines of what the terminal still holds
- [ ] **document the legacy-console limitation**: on the legacy console NVDA
      exposes only the visible window, so the buffer window shows only what is
      on screen there (this is the search exception, and users deserve to know)
- [ ] document the NVDA+Enter conflict on the laptop layout and how to rebind
- [ ] add the new commands to the command reference tables
- [ ] verify every gesture is written with punctuation as words (no bare symbols)
- [ ] run `py -m pytest tests/test_doc_gesture_consistency.py` - must pass
- [ ] run tests - must pass before task 11

### Task 11: Verify acceptance criteria
- [ ] verify all Overview acceptance criteria are implemented
- [ ] verify edge cases: empty buffer, single line, 50k lines, no prompts,
      buffer of only errors, terminal closed while window open
- [ ] add a Buffer Window section to `docs/testing/RELEASE_VERIFICATION.md`
      covering the real-NVDA checks (Escape, H nav, jump back lands correctly,
      large buffer responsiveness, laptop-layout conflict)
- [ ] run full test suite: `py -m pytest tests/ -q --no-cov --timeout=120`
- [ ] run `py validate.py`
- [ ] regenerate the translation template: `py -m SCons pot`, copy to
      `addon/locale/terminalAccess.pot`, confirm new strings carry translator
      comments
- [ ] build and verify the package contains the updated guide

### Task 12: [Final] Update documentation
- [ ] update `CLAUDE.md` Key Paths with `buffer_snapshot.py` / `buffer_html.py`
- [ ] update `CLAUDE.md` Gesture Mappings with NVDA+Enter and the layer key
- [ ] add a CHANGELOG `[Unreleased]` entry (feature + the laptop-layout conflict)
- [ ] update `buildVars.py` `addon_changelog` when this ships (it is the store's
      "What's new", shown verbatim, and has gone stale before)
- [ ] move this plan to `docs/plans/completed/`

## Technical Details

### Window title

Must identify the terminal AND make the frozen nature obvious, since a stale
snapshot silently presented as live is the worst failure mode. Proposed:

```
Windows Terminal buffer, snapshot of 1,432 lines - Terminal Access
```

Truncated and filtered variants append their state. The line count uses
locale-aware number formatting. Exact strings are translatable with translator
comments.

### Heading structure

| Element | Source | Level |
|---------|--------|-------|
| Terminal name | `BufferSnapshot.terminal_name` | h1 |
| Command / prompt | `SectionSpan(category="prompt")` | h2 |
| Error, warning, stack trace | those spans | h3 |
| Everything else | output, progress, timestamp | no heading |

For AI CLI profiles, `ai_turn_tokenizer` turns map to h2 instead of prompts.
Deferred until after Task 4 proves the structure works; noted here so the
renderer takes the tokenizer as a parameter rather than hard-coding one.

### Processing flow

**Open the browse window** (NVDA+Enter / layer Enter):
1. Script fires, confirms a supported terminal.
2. **Off the main thread**: read via `_getBufferLines()`, tokenize, escape and
   render HTML (including the sanitize step, so nothing heavy runs on the main
   thread).
3. `wx.CallAfter`: `ui.browseableMessage(html, title, isHtml=True,
   copyButton=True, sanitizeHtmlFunc=lambda s: s)`.
4. Escape closes. The window is read-only; no add-on code runs while it is open.

**Jump to a line** (layer Shift+Enter, separate modal dialog):
1. Capture the tokenized snapshot, build a structured line list.
2. Open the modal `wx` list dialog.
3. On selection: set `_searchJumpTarget`, close the dialog. Its close returns
   focus to the terminal, firing `event_gainFocus`, which re-applies the review
   position via `_reapplySearchJump` (the shipped pattern). The target line is
   resolved by `resolve_line_by_content()`, never by counting.

### Security

Terminal output is attacker-influenced: a program can print anything. Every line
is ANSI-stripped, control-stripped, bidi-override-stripped, and `html.escape`d
on the worker thread before rendering. Because we escape ourselves and pass an
identity `sanitizeHtmlFunc` (to keep `nh3.clean` off the main thread), our
escaping is the sole boundary and must be complete; the tests in Task 2 are the
gate. Link hrefs reuse the existing scheme check. This continues the posture
already established for the issue report and the URL list.

## Post-Completion

*Items requiring manual intervention or external systems*

**Manual verification** (real NVDA, cannot be unit tested):
- The Task 3 gate: Escape, arrowing, title, large-buffer responsiveness.
- Heading navigation with `H` lands on commands and errors as documented.
- Jump back lands on the right line, including after the terminal has scrolled.
- Native table navigation works on a rendered table.
- Laptop-layout users retain NVDA+Enter review-activate outside terminals.
- Legacy console: confirm the visible-only limitation matches what the guide says.

**Release**:
- Version bump and changelog fold happen only when explicitly asked.
- Refresh `addon_changelog` in `buildVars.py` (store "What's new", verbatim).
- Verify the published asset, not the local build.
