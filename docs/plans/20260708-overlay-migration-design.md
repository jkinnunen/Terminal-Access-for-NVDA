# Design Spike: Complete the Overlay-Class Migration

## Status of the record

`CLAUDE.md` says the overlay architecture is a "not yet created" experiment. That is out of date. The overlay **already exists and is live**:

- `addon/lib/terminal_overlay.py` defines `TerminalAccessTerminal`, an NVDAObject overlay.
- `GlobalPlugin.chooseNVDAObjectOverlayClasses` ([terminalAccess.py:973](../../addon/globalPlugins/terminalAccess.py)) inserts it at position 0 for supported terminals.
- The overlay already owns `_reportNewLines` (coalescing, blank suppression, error/warning cues, bulk "N new lines") and its own `event_textChange` (quiet mode, activity tones, monitor-thread wake).

So this is not a greenfield migration. It is a **half-finished** one, and the half-finished state is itself a problem.

## The actual problem: a dual event system

Terminal event handling currently lives in two places at once:

| Event | Overlay (`TerminalAccessTerminal`) | GlobalPlugin (global handler) |
|-------|-----------------------------------|-------------------------------|
| New output (`_reportNewLines`) | Yes | No |
| `event_textChange` | Yes | **Also yes** ([:1544](../../addon/globalPlugins/terminalAccess.py)) |
| `event_caret` | No | Yes ([:1488](../../addon/globalPlugins/terminalAccess.py)) |
| `event_typedCharacter` | No | Yes ([:1384](../../addon/globalPlugins/terminalAccess.py)) |

NVDA dispatches an event to both the object's class chain and any global plugin handler. With `event_textChange` implemented in both the overlay and the GlobalPlugin, the logic (quiet mode, activity tones) is duplicated and can run twice or interact unpredictably. Meanwhile `event_caret` and `event_typedCharacter` are still intercepted globally with `nextHandler` skipping, which is the exact "fights NVDA's event chain" pattern the overlay was meant to end.

The overlay also depends on the GlobalPlugin pushing config into it: `self._configManager` is documented as "Set by GlobalPlugin on gainFocus." That coupling is fragile.

## Target end state

All per-terminal event handling lives in the overlay. The GlobalPlugin owns only what is genuinely global: the command layer, scripts, gesture bindings, settings, and profile management. Specifically:

- The overlay owns `event_textChange`, `event_caret`, `event_typedCharacter`, `_reportNewLines`, activity tones, error cues, quiet-mode suppression, and typed-character echo.
- The GlobalPlugin no longer defines `event_textChange` / `event_caret` / `event_typedCharacter`.
- The overlay reads configuration directly (via `config.conf["terminalAccess"]` or a shared `ConfigManager`), not by having the GlobalPlugin poke `_configManager` into it.

## What this fixes

- **"blank" after Enter**: handling new output at `_reportNewLines` (already in the overlay) is the correct layer to apply the stabilization delay; finishing the migration lets that logic own the path end to end instead of racing the global `event_caret`.
- **Activity tones only on caret, not textChange**: the overlay's `event_textChange` already plays them; removing the global caret-based tone logic removes the inconsistency.
- **Quiet-mode complexity**: quiet mode is currently decided in three handlers. Consolidating into the overlay makes it one decision at the output source (don't wake the monitor thread).
- **Duplicate/racy handling**: one `event_textChange`, not two.

## Phased, reversible plan

Each phase is independently shippable and verified against real NVDA (see below). The overlay is already inserted, so every phase is a small move of logic, not a big-bang switch.

**Phase A - De-duplicate `event_textChange`.** Confirm by testing which handler currently fires (object vs global). Move any logic that only exists in the GlobalPlugin's `event_textChange` into the overlay's, then delete the GlobalPlugin's `event_textChange`. Verify activity tones and quiet mode still behave.

**Phase B - Move caret handling into the overlay.** Add `event_caret` to `TerminalAccessTerminal`, porting the activity-tone and error-cue-on-caret logic and the quiet-mode caret suppression from GlobalPlugin `event_caret`. Delete the GlobalPlugin `event_caret`. This is the riskiest phase (caret drives most speech); verify line/word/char reading and cursor tracking carefully.

**Phase C - Move typed-character handling.** Port `event_typedCharacter` (key echo, quiet-mode suppression, the `_lastTypedCharTime` guard the overlay already tracks) into the overlay. Delete the GlobalPlugin handler.

**Phase D - Decouple config.** Give the overlay its own config access so the GlobalPlugin no longer sets `_configManager`. The overlay's `initOverlayClass` reads `config.conf["terminalAccess"]` directly. Keep the review-cursor and profile state the GlobalPlugin genuinely owns accessible via a narrow interface.

**Phase E - Remove the scaffolding.** Delete any now-unused GlobalPlugin event glue and the `_configManager` push. Update `CLAUDE.md` to describe the overlay as the architecture, not an experiment.

## Specific NVDA APIs

- `chooseNVDAObjectOverlayClasses(obj, clsList)` - already used; the insertion point.
- `NVDAObjects.behaviors.LiveText` - the base whose `_reportNewLines`, `event_textChange`, monitor thread (`_event`, `startMonitoring`/`stopMonitoring`), and `_getTextLines`/diff we are overriding. Reference: `nvda/source/NVDAObjects/behaviors.py` (LiveText, roughly lines 371-619).
- `initOverlayClass` - overlay init hook (already implemented).
- `event_caret`, `event_textChange`, `event_typedCharacter` - the object-level handlers to own.
- `makeTextInfo(POSITION_CARET)` + `UNIT_LINE` - already used by `_checkErrorAudioCue`.

## Risks

- **Untestable in CI.** `wx` and the NVDA event/monitor machinery are mocked in the test suite, so the integration (event dispatch order, monitor-thread wake, real speech) cannot be verified here. The overlay *methods* are unit-testable in isolation (`terminal_overlay.py` is written to construct standalone; see `tests/test_terminal_overlay.py`), but the wiring is not. Every phase needs real-NVDA testing.
- **Event dispatch ordering.** Global-plugin handlers and object handlers coexist; removing a global handler changes what runs. Phase A must establish the current behavior empirically before deleting anything.
- **Terminal variety.** Windows Terminal uses UIA text-change notifications; conhost/others use the diff monitor. The overlay must work for both paths; verify across terminals.
- **Regression surface.** Caret handling (Phase B) touches nearly all reading. Keep phases small and behind the existing (already-live) overlay so a bad phase is a one-commit revert.

## Verification plan

Run `docs/testing/RELEASE_VERIFICATION.md` after each phase on Windows 10 and 11, across Windows Terminal, a conhost host, and one third-party emulator, with native acceleration both on and off. Pay special attention per phase to: activity tones and quiet mode (A), line/word/char reading and cursor tracking (B), key echo (C). Do not merge a phase whose verification regresses speech.

## Unit-test coverage to add per phase

Because the overlay class is standalone-constructible, add `tests/test_terminal_overlay.py` cases as logic moves in:

- Phase A: `event_textChange` quiet vs normal, activity-tone debounce, typed-character guard.
- Phase B: `event_caret` quiet-mode suppression, error-cue-on-caret gating, activity tone.
- Phase C: `event_typedCharacter` echo on/off, quiet-mode suppression.

These cannot prove the NVDA wiring, but they lock the decision logic so only the integration needs manual checking.

## Not in scope here

This is a design spike, not an implementation. No runtime behavior changes with this document. Implementation should proceed phase by phase, each with real-NVDA verification, and is gated behind a maintainer who can run NVDA.
