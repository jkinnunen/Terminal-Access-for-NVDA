# Release Verification Protocol

The unit tests mock `wx` and NVDA internals, so they cannot exercise the highest-risk surfaces: UI Automation reads, wx dialogs, review-cursor behavior across focus changes, and NVDA event handling. Run this manual protocol on real hardware before promoting any build toward 2.0.0. Two shipped bugs prove the point: the machine-freezing find bug (fixed in 2.0.0-beta.3) and the search-result review-cursor bug (fixed in 2.0.0-beta.14) both passed CI.

## Environments

Run the checklist on both, because UIA provider behavior differs by OS version:

- Windows 10 with Windows Terminal (the reported freeze environment)
- Windows 11 with Windows Terminal

Then spot-check at least two more terminals from different families: a console host (cmd or PowerShell in conhost), and one third-party emulator (for example mintty/Git Bash or PuTTY).

The add-on is pure Python (the native library and helper process were removed in 2.0.0); all terminal reads run in-process. One pass per environment is sufficient.

## Checklist

For each environment, confirm each item speaks correctly and nothing hangs.

### Startup
- [ ] Focus a supported terminal; hear "Terminal Access support active. Press NVDA+shift+f1 for help."
- [ ] NVDA+Shift+F1 opens the user guide.

### Reading and navigation
- [ ] Line, word, and character navigation (NVDA+U/I/O, J/K/L, M/,/.) read the expected text.
- [ ] Say all (NVDA+A) reads a screen of output without stalling.
- [ ] Command layer (NVDA+apostrophe) enters and exits with the expected tones.

### Find (the freeze regression case)
- [ ] Fill the terminal with a large scrollback (thousands of lines), then run find (NVDA+F). It returns results promptly and **does not freeze NVDA or the machine.**
- [ ] Find with no matches falls back to fuzzy matching without hanging.
- [ ] F3 / Shift+F3 move between matches; the results dialog opens and jumps correctly.

### Search-result jump (the review-cursor regression case)
- [ ] Activate a result in the search results dialog, then press review-current-line: it reads the **matched line**, not the command prompt, including a second or two after the dialog closes.
- [ ] After closing the results dialog, F3 / Shift+F3 still move through the remaining matches.

### Bookmarks, tabs, URLs
- [ ] Set (Shift+0-9) and jump (0-9) to bookmarks; the bookmark list dialog opens, jumps, and deletes.
- [ ] URL list (NVDA+Alt+U) opens; Open, Copy, and Move act correctly; an unsafe scheme is refused.

### Table mode
- [ ] On `docker ps` / `kubectl get` / `ls -l` output, table mode (NVDA+Alt+G) announces cells with headers; arrows, Home/End, Ctrl+Up, and Space behave; Escape exits.

### Buffer window
- [ ] NVDA+Enter (or Enter in the command layer) opens the snapshot; the title names the terminal and says "snapshot"; Escape closes and returns focus to the terminal.
- [ ] Arrow keys read line by line; blank rows occupy a line instead of vanishing.
- [ ] H moves by heading: level 2 lands on each command, level 3 on each error or stack trace start; an error and its trace are ONE heading stop.
- [ ] The table of contents at the top links to commands and errors; activating a link moves within the window.
- [ ] Columnar output (`docker ps`, `ls -l`) renders as a real table: NVDA table navigation works and announces headers; prose does NOT render as a table.
- [ ] An http/https URL in output is an activatable link; a `file://` or `javascript:` string is plain text.
- [ ] Shift+E / Shift+C (command layer) open errors-only / commands-only windows with the filter named in the title; with nothing matching, a message is spoken and no window opens.
- [ ] Jump to line (NVDA+Shift+Enter): filter narrows, Enter closes and the review cursor lands on the chosen line (verify with review-current-line a second or two after close).
- [ ] Jump to a line, clear the terminal (or exceed scrollback), jump again from a stale dialog: "Could not reach that line" is spoken.
- [ ] Laptop layout: outside a terminal, NVDA+Enter still activates the navigator object (the add-on must not swallow it there).
- [ ] A buffer at the terminal's scrollback limit (thousands of lines) opens without freezing NVDA; note the open time.
- [ ] Hostile output stays inert: `echo "<script>alert(1)</script>"` renders as text in the window, and `printf` with ANSI colour codes shows clean text.

### AI CLI (if testing an AI tool)
- [ ] Turn navigation (NVDA+Alt+T / NVDA+Alt+Shift+T) lands on turns and announces role and first line.
- [ ] Code block navigation (NVDA+Alt+B / NVDA+Alt+Shift+B) moves between blocks.

### Recovery
- [ ] After NVDA restarts (NVDA+Q, restart), the add-on re-announces support on terminal focus and search works immediately.

## Sign-off

Record the build, the environments tested, and any anomalies in the release notes or the pull request. Do not promote to final 2.0.0 until the find test passes on a real Windows 10 + Windows Terminal machine, ideally confirmed by a user who hit the original freeze.
