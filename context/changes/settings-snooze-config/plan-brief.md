# Settings — Snooze Configuration — Plan Brief

> Full plan: `context/changes/settings-snooze-config/plan.md`

## What & Why

Expose the FR-010 snooze parameters — snooze duration (1–30 min) and max snoozes per cycle (0–5) — as user-editable spinboxes in the existing Scheduling tab of `SettingsDialog`. Today both values have getters but no setters and no UI; the only way to change them is hand-editing `BreakReminder.ini`. After this slice the user picks their own values from the GUI and the running scheduler picks them up on the very next tick. PRD Open Question #1 dissolves (user picks duration rather than us committing to 5 vs 10).

**Scope addendum (2026-05-26, mid-Phase-1)**: The user asked that the tray-icon tooltip switch from `BreakReminder — next break in Xm YYs` to `BreakReminder — snooze time left Xm YYs` while a snooze is active. Folded into this slice (one new property on `BreakScheduler`, one new branch in `BreakReminderApp._refresh_tooltip`, one README sentence) because it's the same conceptual feature surface as the new spinbox: "snooze is a thing the user can see and control."

## Starting Point

Roadmap slice **S-03: settings-snooze-config**, prerequisites already shipped (S-01 dialog scaffold, S-04 voice tab). `Settings.snooze_duration_min` and `Settings.max_snoozes` are getter-only (`break_reminder/storage/settings.py:153-161`); ranges are inconsistent (break-interval has top-level constants; max-snoozes hard-codes 0/5 inline; snooze-duration has only a `max(1, …)` floor and **no upper cap defined anywhere**). The scheduler already reads both keys per-tick (`break_reminder/scheduler.py:145, 174`) so no plumbing change is needed downstream.

## Desired End State

The Scheduling tab shows three rows: "Break interval (minutes):" (existing), "Snooze duration (minutes):" (new), "Max snoozes per cycle:" (new). Each pre-populated from `Settings`, each clamped to its FR-010 range at the widget level. The max-snoozes spinbox carries a tooltip explaining the zero state. OK persists; the next break dialog respects the new values; Cancel discards. Roadmap S-03 flips `proposed → done`; PRD Open Question #1 annotated as dissolved.

## Key Decisions Made

| Decision                                                       | Choice                                                                | Why (1 sentence)                                                                            |
| -------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| UI placement                                                   | Add to existing Scheduling tab                                        | Snooze IS scheduling; no new surface; matches the way the tab is named today.               |
| Typed-out-of-range tooltip parity with break-interval spinbox  | Skip                                                                  | 1–30 / 0–5 are small enough that spinbox fixup is enough; would duplicate ~40 lines.        |
| Setter validation style                                        | Tight (`ValueError` on out-of-range)                                  | Matches `break_interval_min` setter; numeric ranges deserve loud failures.                  |
| `max_snoozes = 0` UX                                           | Allow zero + tooltip explaining "no snoozes; take or miss"            | Existing scheduler already handles zero correctly; the user-discoverability gap is the hint. |
| Default snooze duration in code                                | Keep at `DEFAULT_SNOOZE_DURATION_MIN = 5`                             | The user picks via UI; the constant only controls first-run / fresh-install state.          |

## Scope

**In scope:**

- 4 new top-level constants: `SNOOZE_DURATION_MIN_MINUTES`, `SNOOZE_DURATION_MAX_MINUTES`, `MAX_SNOOZES_MIN`, `MAX_SNOOZES_MAX`.
- `snooze_duration_min` getter clamp tightened to two-sided; new `@…setter` with `ValueError`.
- `max_snoozes` getter clamp uses the new constants; new `@…setter` with `ValueError`.
- Two new `QSpinBox` rows in `_build_scheduling_tab`, both wired into `accept()`.
- Tooltip on the max-snoozes spinbox covering the zero-state UX.
- New tests: `TestSnoozeSettersRoundTrip` (4 tests), `TestSnoozeValidation` (9 tests), 5 new `TestLoad` tests, 3 new `TestSave` tests, 1 new `TestLayout` test.
- **Scope addendum**: `BreakScheduler.seconds_until_snooze_end` property + snooze-aware branch in `BreakReminderApp._refresh_tooltip` + README sentence + 4 new `TestSecondsUntilSnoozeEnd` tests + 3 new `TestRefreshTooltipDuringSnooze` tests.
- Roadmap status flip + Open Question #1 dissolution + backlog handoff update.

**Out of scope:**

- New tab (fields land on the existing Scheduling tab).
- Typed-out-of-range tooltip pattern for the new spinboxes.
- Change to `DEFAULT_SNOOZE_DURATION_MIN`.
- Change to `BreakDialog` (the `max_snoozes = 0` path is already correct via the existing `snooze_remaining = 0` check).
- Change to `Snapshot` or to `scheduler.py`'s `_tick` snooze gate (the new property reads existing state; `_tick` already clears the field correctly).
- Change to the 5-second tooltip refresh cadence — the snooze form inherits the same per-tick granularity as the existing countdown.
- Autostart, voice, custom-reminder, or break-interval work.

## Architecture / Approach

```
storage/settings.py   ──>   ui/settings_dialog.py   ──>   QSettings (INI)
   constants                  Scheduling tab adds
   tight setters              2 spinbox rows;
                              accept() persists both
                                       │
                                       ▼
                              break_reminder/scheduler.py
                              (no change — reads both
                               Settings keys every tick)
```

Two phases:

1. **Phase 1** lands all code (constants + setters + UI rows + tests). All gates automated.
2. **Phase 2** is human smoke + roadmap bookkeeping (flip change.md, flip roadmap S-03 to `done`, annotate Open Question #1).

## Phases at a Glance

| Phase                                                    | What it delivers                                                                                                | Key risk                                                                                            |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 1. Constants + setters + UI fields + automated coverage  | Snooze fields user-editable, persisted, scheduler picks them up next tick; full test net                        | Forgetting to update `_build_scheduling_tab` import list when adding the 4 new constants — caught by lint. |
| 2. Manual smoke + roadmap bookkeeping                    | Confirms end-to-end behavior on a real tray; flips `change.md`, roadmap status, and Open Question #1 annotation | None — bookkeeping; manual smoke is mechanical because the scheduler hop is already covered by existing tests. |

**Prerequisites:** S-01 (settings dialog scaffold) and S-04 (voice tab) are already shipped — both done as of v0.3.0 (2026-05-25/26). No new dependencies.

**Estimated effort:** ~1 evening; smaller than S-04 (no new tab, no new dependency injection, no new UX validation pattern).

## Open Risks & Assumptions

- Assumption: scheduler reads `Settings.snooze_duration_min` / `Settings.max_snoozes` directly per-tick. Verified at `break_reminder/scheduler.py:145` (snooze deferral) and `break_reminder/scheduler.py:174` (snooze cap subtraction).
- Assumption: existing `BreakDialog` already handles `snooze_remaining = 0` by hiding the snooze button. Documented in roadmap S-03 baseline; smoke step 5 in Phase 2 confirms.
- Risk: a future caller might pass a non-int (e.g., `1.5` from a CLI) to the new setters. Mitigation: setters do an `isinstance(int)` check via the comparison operator semantics (`<= minutes <= …` works for ints; floats would fail `isinstance` only if we add an explicit guard — out of scope; existing `break_interval_min` setter does not guard either).

## Success Criteria (Summary)

- User opens Settings → Scheduling tab and sees three rows: Break interval, Snooze duration, Max snoozes per cycle. Hover on Max snoozes shows the zero-state tooltip.
- Editing both fields and clicking OK persists the values; the next break dialog respects the new snooze duration on its "Snooze" button and the new max-snoozes cap on the snooze-button visibility.
- `max_snoozes = 0` is a working state; the snooze button is absent on the next break dialog.
- Roadmap S-03 row reads `done`; PRD Open Question #1 annotated as dissolved by S-03.
