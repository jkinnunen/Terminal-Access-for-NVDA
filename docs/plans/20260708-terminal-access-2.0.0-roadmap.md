# Roadmap to Terminal Access 2.0.0 Final

## Status as of 2026-07-12 (beta.15)

- **Milestone 1 (native/helper):** resolved beyond the plan. Hardening (beta.3) was not enough; field diagnostics showed the helper itself was the liability, so the entire native layer was removed. The add-on is pure Python as of beta.15 (reads in-process, stdlib Unicode width fallback, no toggle, no binaries, ARM64 capable).
- **Milestone 2 (claim-vs-reality):** done. Doc-vs-code gesture test, release verification protocol (updated for the pure-Python architecture and the search-jump regression), guide corrections.
- **Milestone 3 (overlay migration):** done, phases A through E shipped; the overlay delegates terminal events to the plugin.
- **Milestone 4 (version/changelog story):** done; betas roll up under the 2.0.0 line. Consolidated release notes draft: `docs/plans/20260712-2.0.0-release-notes-draft.md`.
- **Milestone 5 (stabilize):** done. Experimental labels, issue-report command (Shift+I), plus the beta.8 to beta.14 search-result cursor fix arc.
- **Milestone 6 (community/store):** open. Beta cohort, Add-on Store submission, translation refresh.
- **Released:** 2.0.0 final was cut on 2026-07-12 after the owner verified beta.15 on real hardware. Remaining post-release work is Milestone 6 (beta cohort feedback channel, NVDA Add-on Store submission).

The sections below are the original plan, kept as the record of intent; where reality diverged (Milestone 1), the status above wins.

## Overview

2.0.0 is the destination. The `2.0.0-beta`, `-beta.2`, `-beta.3` pre-releases are milestones on the way there, not separate products. This plan turns the six post-freeze-fix recommendations into ordered milestones and marks what is being implemented now versus planned for later betas.

The guiding principle: **for a screen-reader add-on, trust is set by the worst bug, not the longest feature list.** The machine-freezing find bug (fixed in `beta.3`) is the proof. Reliability and honesty-of-documentation come before new features.

## Context (from discovery)

- Native/helper layer: `native/crates/termaccess-helper/` (Rust UIA reader), `addon/native/helper_process.py` (IPC), `addon/native/termaccess_bridge.py` (FFI + helper accessors). Just hardened (MTA, watchdog, non-blocking start, toggle) but still bespoke systems-level code with no CI coverage.
- Event architecture: `addon/globalPlugins/terminalAccess.py` intercepts `event_caret`/`event_textChange` at the GlobalPlugin level. `CLAUDE.md` documents the intended `chooseNVDAObjectOverlayClasses()` overlay migration.
- Docs: `addon/doc/en/readme.md` is the shipped guide (now the single source). `docs/user/*` point to it.
- Version story: `CHANGELOG.md` had `[2.0.0] - 2026-03-27` mislabeled below the July betas; no `v2.0.0` tag exists. Tags: `v2.0.0-beta`, `v2.0.0-beta.2`, `v2.0.0-beta.3`.
- Tests: 1931 Python + 125 Rust. `wx` and the native layer are mocked in CI, so dialogs, event handlers, and UIA reads are the least-covered, highest-risk surfaces.

## Development Approach

- **Testing:** TDD (red/green/refactor) for all code changes, per project convention. Every code task ships tests.
- Small, focused changes; full suite green before moving on.
- Betas roll up into 2.0.0. Every user-facing change is recorded under the 2.0.0 line in `CHANGELOG.md`.
- Native COM/UIA behavior and wx dialogs are not unit-testable in CI; those are covered by the manual verification protocol (Milestone 2), not by pretending unit tests suffice.

## Milestones

Legend: **[NOW]** implemented in this pass · **[NEXT]** next beta · **[LATER]** post-2.0.0 or large spike.

---

### Milestone 1 — Native/helper layer: harden or step back

**Task 1.1 — Codify the main-thread safety rule [NOW]**

**Files:**
- Modify: `CLAUDE.md`

- [ ] Add a Conventions rule: add-on code must never block NVDA's main thread on an uninterruptible native, IPC, or COM/UIA call; prefer graceful degradation to the in-process path.
- [ ] Reference the `beta.3` freeze as the cautionary example.

**Task 1.2 — Native-vs-Python benchmark harness [NOW]**

**Files:**
- Create: `native/bench/README.md` (how to run and interpret)
- Create: `tests/test_native_benchmark.py` (opt-in, skipped without native)

- [ ] Add a script/test that times `strip_ansi` and `search_text` on representative buffer sizes, native vs pure-Python, printing a ratio.
- [ ] Mark it opt-in (skip when native absent) so it never blocks CI.
- [ ] Write a test that the harness runs and returns timings for both paths.

**Task 1.3 — Helper soak/fuzz harness [NEXT]**

- Drive `read_text`/`search_text` against a live terminal with large, truncated, and adversarial buffers in a loop; assert no hang and bounded latency. Requires a real Windows + terminal host, so it lives as a manual/optional harness, not CI.

**Task 1.4 — Decide native opt-in default [NEXT]**

- Using 1.2 data and `beta.3` field reports, decide whether native acceleration stays default-on or becomes opt-in. Product decision; do not flip the default without the maintainer's call.
- ⚠️ First measurement (`native/bench/benchmark.py`): for ANSI stripping and search, the native FFI path is roughly **10x slower** than pure Python across 100 to 50,000 lines (FFI marshaling and JSON overhead dominate; Python's `re`/`str` are already C-speed). The native layer's remaining justification is off-main-thread buffer reading in the helper, which is exactly the surface that deadlocked. This is strong evidence for making native acceleration opt-in, or dropping the FFI strip/search path and keeping only the helper read behind the toggle. Confirm on the target hardware, then decide.

---

### Milestone 2 — Close the claim-vs-reality gap

**Task 2.1 — Doc-vs-code gesture consistency test [NOW]**

**Files:**
- Create: `tests/test_doc_gesture_consistency.py`

- [ ] Extract every bound gesture from the code (`_DEFAULT_GESTURES` and the command-layer maps) and assert each maps to a `script_*`/handler that exists on `GlobalPlugin`.
- [ ] Extract direct-gesture tokens (`NVDA+...`) from the shipped guide's reference tables and assert each is a real binding in the code.
- [ ] Write tests for both directions (code→script, doc→code) including a negative fixture.
- [ ] Run tests — must pass before next task.

**Task 2.2 — Real-NVDA verification protocol [NOW]**

**Files:**
- Create: `docs/testing/RELEASE_VERIFICATION.md`

- [ ] A pre-release checklist: for the top terminals on Windows 10 and 11, exercise find, bookmarks, table mode, AI navigation, and confirm no freeze and correct speech.
- [ ] Explicit "find on Windows Terminal, large scrollback" step (the `beta.3` regression case).

**Task 2.3 — Windows/NVDA smoke CI [LATER]**

- A Windows CI job that loads NVDA headless with a scripted terminal and asserts the plugin activates and a few commands speak. Needs infrastructure; scoped as a later spike.

---

### Milestone 3 — Complete the overlay-class migration [design done; phased impl LATER]

- The overlay already exists and is live (`TerminalAccessTerminal` in `addon/lib/terminal_overlay.py`, inserted via `chooseNVDAObjectOverlayClasses`). The migration is roughly half done: the overlay owns new-output handling, but the GlobalPlugin still intercepts `event_caret`/`event_textChange`/`event_typedCharacter` globally, so the two systems overlap.
- Design spike written: [20260708-overlay-migration-design.md](20260708-overlay-migration-design.md). It maps the dual-system state and lays out a five-phase plan (A: de-duplicate `event_textChange`; B: move caret handling; C: move typed-character handling; D: decouple config; E: remove scaffolding), each verified against real NVDA.
- Implementation is phased and gated behind a maintainer who can run NVDA (the wiring is untestable in CI). Fixes blank-after-Enter, activity-tone inconsistency, and quiet-mode duplication.

---

### Milestone 4 — Reconcile the version/changelog story [NOW]

**Files:**
- Modify: `CHANGELOG.md`

- [ ] Relabel `## [2.0.0] - 2026-03-27` to `## [2.0.0-beta] - 2026-07-08` (matches the actual `v2.0.0-beta` tag/release).
- [ ] Add a header note that 2.0.0 is being developed and released through the beta series.
- [ ] Add an `## [Unreleased]` section that accumulates the reliability/process work as it heads to 2.0.0.
- [ ] Leave the final `## [2.0.0]` heading to be created (by consolidating the betas) only when final ships.

---

### Milestone 5 — Stabilize before broadening

**Task 5.1 — Mark experimental features [NOW]**

**Files:**
- Modify: `addon/doc/en/readme.md`

- [ ] Label table-mode column detection and AI turn detection as experimental in the guide, with a one-line "how to report a miss."

**Task 5.2 — Failure-reporting affordance [NEXT]**

- A lightweight command/log affordance to capture "this terminal/table read wrong" with the buffer sample, so field reports are actionable. Feeds Milestones 1.3 and 5.1.

---

### Milestone 6 — Community and Add-on Store [LATER]

- Recruit a small beta cohort of blind users across Windows 10/11 and the common terminals (the freeze only reproduces on real setups).
- Formalize the NVDA Add-on Store submission and its review requirements. The existing 17 translations are an asset; keep the `.pot`/`.po` pipeline current per release.

---

## Progress Tracking

- Mark `[x]` when done; `➕` for newly discovered tasks; `⚠️` for blockers.
- Keep this plan in sync; move to `docs/plans/completed/` when the **[NOW]** set lands and the remaining milestones are scheduled.

## Post-Completion

**Manual verification (Milestone 2.2):** run the release verification protocol on a real Windows 10 + Windows Terminal machine, ideally with an affected user, and confirm the `beta.3` freeze is gone before promoting to final 2.0.0.

**Product decisions (owner):** native opt-in default (1.4); when to cut final 2.0.0 (Milestone 4); scope/timing of the overlay migration (Milestone 3).
