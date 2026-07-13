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

### AI CLI (if testing an AI tool)
- [ ] Turn navigation (NVDA+Alt+T / NVDA+Alt+Shift+T) lands on turns and announces role and first line.
- [ ] Code block navigation (NVDA+Alt+B / NVDA+Alt+Shift+B) moves between blocks.

### Recovery
- [ ] After NVDA restarts (NVDA+Q, restart), the add-on re-announces support on terminal focus and search works immediately.

## Sign-off

Record the build, the environments tested, and any anomalies in the release notes or the pull request. Do not promote to final 2.0.0 until the find test passes on a real Windows 10 + Windows Terminal machine, ideally confirmed by a user who hit the original freeze.
