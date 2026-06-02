# Top-three e2e flows — Plan Brief

> Full plan: `context/changes/testing-top-three-e2e-flows/plan.md`
> Research: `context/changes/testing-top-three-e2e-flows/research.md`

## What & Why

Phase 4 of the BreakReminder test rollout adds one end-to-end test per top-three user-visible flow (Add Reminder, Save Settings interval change, Tray Reset) behind a pytest `e2e` marker on a CI job split from the existing unit tier. The R-4 risk this closes is that three load-bearing signal connections in `break_reminder/app.py` (`:277` `break_due`, `:278` `reminder_due`, `:349` `break_interval_changed`) are structurally pinned today but never traversed end-to-end — a regression that silently broke any of these would pass every existing per-module test. The "signal-connection-only" anti-pattern is institutional in this codebase (four `_StubSignal` shims at `tests/test_app.py:431`, `tests/test_settings_dialog.py:2446`, `:2749`, `:2802`); Phase 4 is the regression net for it.

## Starting Point

Five existing integration tests today: 4 in `tests/test_recurring_reminder_integration.py` (Phase 1, R-1) + 1 in `tests/test_modal_stacking_integration.py` (Phase 2, R-2) — both are narrow risk pins, neither is a full user-visible flow. The `_on_reminder_due` slot in `app.py` has zero ripgrep matches in `tests/` — the single biggest invisible hop. The harness is in good shape: both `BreakScheduler` and `ReminderScheduler` already accept a `clock=` callable at construction, and tests bypass real `QTimer`s by calling `_tick()` / `_on_timer()` directly (the Phase 1 pattern explicitly endorsed by `test-plan.md §7`). One structural seam is missing: `BreakReminderApp.__init__` accepts injectable storage collaborators but no `clock=` kwarg, so schedulers inside the wired app run on real wall-clock.

## Desired End State

Three new e2e test files (`tests/test_add_reminder_e2e.py`, `tests/test_save_settings_interval_e2e.py`, `tests/test_tray_reset_e2e.py`) each drive the user click through every cross-module hop to a `BreakDialog`/`ReminderDialog` appearing on `QApplication.topLevelWidgets()`, without using `_StubSignal` shims or `QTest.mouseClick`. The `e2e` marker is declared in `pyproject.toml` with `--strict-markers`; CI `release.yml` runs `pytest -m "not e2e"` then `pytest -m e2e` as two sequential steps. `tests/conftest.py` exposes the shared harness (10 lifted/new fixtures). `BreakReminderApp.__init__` accepts `clock=` (~3 LoC); `AGENTS.md § Threading rules`, `test-plan.md §6` cookbook, and `lessons.md` each gain entries reflecting the new state. Test-plan rollout counter advances `3 → 4`; §3 row 4 status flips `change opened → complete`.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Which flows ship | A + B + D (Add Reminder, Save Settings, Tray Reset) | Each closes a distinct R-4 wire in `app.py`; Flow C's value is dominated by an R-3 composite genuinely owned by a different risk. | Plan |
| STRUCTURAL #1 (`BreakReminderApp.clock=`) | Ship the fix in Phase 4 (~3 LoC) | Parallels Phase 3's `_read` precedent; unblocks every future wired-app e2e; the fix is small enough that deferring creates more orchestration overhead than shipping it. | Plan |
| Fixture lift scope | Full lift in P1 prep commit (~38 LoC, 10 fixtures: A1-A6 + B1-B4) | Establishes the harness once (Phase 1 pattern); subsequent phases scope to one new test file each; future rollouts inherit the conftest. | Plan |
| Sub-phase structure | 5 phases (Prep / Flow A / Flow B / Flow D / Docs+CI) | Each phase = one logical commit; preserves Phase 3's "docs/CI as closing ritual" pattern; clean per-flow attribution and rollback. | Plan |
| Marker landing order | Declare marker + `--strict-markers` in P1; workflow YAML split in P5 | Avoids the empty-tier exit-code-5 trap (research §G risk #2); CI stays green through every phase; workflow split lands after 3 `@pytest.mark.e2e` tests exist. | Plan |
| Marker name | `e2e` (not `integration`) | The §3 row 4 cell explicitly frames Phase 4 as "end-to-end test per top-three user-visible flow"; the existing two `*_integration.py` files are narrow risk pins, not user-flows — lumping erases granularity. | Research |
| Docs scope in P5 | All three (AGENTS.md threading addendum + test-plan §6 cookbook + lessons.md `_StubSignal` entry) | Lessons.md is re-read every `/10x` command, making the anti-pattern enforceable in future impl-reviews; cookbook matches per-phase discipline; AGENTS.md prevents future authors re-discovering STRUCTURAL #3 via flakes. | Plan |
| Test file organization | One file per flow (`test_<flow_name>_e2e.py`) | Matches Phase 1/2 convention (one file per integration concern: `*_integration.py`); each file is one R-4 contract. | Plan |

## Scope

**In scope:**

- 3 new e2e test files (Flow A, B, D); each with one load-bearing test method, `@pytest.mark.e2e`
- 10 fixtures lifted/added in `tests/conftest.py` (A1-A6 from Phase 1/2 + B1-B4 net-new including `break_reminder_app`)
- `BreakReminderApp.__init__` gains `clock=` kwarg + propagation to both schedulers (~3 LoC + 1 pin test)
- `pyproject.toml`: declare `e2e` marker + add `--strict-markers` to `addopts`
- `.github/workflows/release.yml`: replace single `Test` step with two sequential `pytest -m "not e2e"` / `pytest -m e2e` steps in the same `build` job
- `AGENTS.md § Threading rules`: addendum on "do not enter event loop after `BreakScheduler.start()`"
- `context/foundation/test-plan.md §6` cookbook "Cross-cutting end-to-end flows" row: TBD → canonical recipe
- `context/foundation/lessons.md`: new entry on `_StubSignal` R-4 anti-pattern
- Test-plan state-machine flip (`rollout_phases_complete: 3 → 4`; §3 row 4 status → complete)
- Change-folder status flip (`planned → implementing → implemented`)

**Out of scope:**

- Flow C (Pause → Resume → tick) — deferred to a future R-3-focused rollout (its gap is dominated by the R-3 pause+snooze+reset composite)
- Real-event-loop tests (`qtbot.wait()`, `qtbot.waitSignal()`, `qt_app.exec()` after a `start()`-calling slot — STRUCTURAL #3 race)
- `QTest.mouseClick` on dialog action buttons (Phase 2 anti-pattern)
- `_StubSignal` shims, slot mocking, slot-poking ("captured slot invoked by hand")
- `_active_seconds == 0` / `_snooze_until is None` oracles (implementation mirrors)
- `EventLog.clock=` kwarg (STRUCTURAL #2 — deferred; Flow D oracles on `(event_type, outcome)` not on `timestamp_iso`)
- Multi-OS CI matrix expansion (`windows-latest` only per PRD § Non-Goals)
- Installer/NSIS/build/release workflow changes beyond the `Test` step split
- `pytest-qt` / `pytest` version bumps

## Architecture / Approach

Three e2e tests + shared conftest harness + pytest marker tier + CI workflow split, in five phases:

```
P1 Prep              → conftest fixtures (10) + BreakReminderApp.clock= + marker decl
   ↓
P2 Flow A e2e        → tests/test_add_reminder_e2e.py        (closes app.py:278)
   ↓
P3 Flow B e2e        → tests/test_save_settings_interval_e2e.py (closes app.py:349 + :277)
   ↓
P4 Flow D e2e        → tests/test_tray_reset_e2e.py           (closes :277 post-Reset re-arm)
   ↓
P5 Docs + CI split   → release.yml + AGENTS.md + test-plan §6 + lessons.md + state flip
```

Each flow phase ships exactly one new test file; the test drives the user-click entry → real signal emit across real `connect` → virtual `Clock` advance + direct `_tick()` / `_on_timer()` → assert dialog appears on `QApplication.topLevelWidgets()`. The single oracle shape works for all three flows. No `_StubSignal`, no `QTest.mouseClick`, no `qtbot.wait()` after `start()`.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| **1. Prep** | Conftest fixture lift (10 fixtures, ~38 LoC); `BreakReminderApp.clock=` kwarg + pin test; `pyproject.toml` marker + `--strict-markers` | Fixture rename ripple — two existing integration files must stay green after dropping local fixtures |
| **2. Flow A e2e** | `tests/test_add_reminder_e2e.py` (one class, one test, `@pytest.mark.e2e`) | Accidental slot mocking / `_StubSignal` reuse — the load-bearing assertion must oracle on `QApplication.topLevelWidgets()` |
| **3. Flow B e2e** | `tests/test_save_settings_interval_e2e.py` (one class, one test) | Timing window oracle — must assert dialog DOES appear within 300 ticks AND DOES NOT appear before ~295 (proves new threshold honored, not old) |
| **4. Flow D e2e** | `tests/test_tray_reset_e2e.py` (one class, one test) — exercises P1 `break_reminder_app` fixture | Re-arm-from-zero oracle — must assert dialog DOES NOT fire at iteration ~60 (would if re-arm used pre-Reset accumulator) |
| **5. Docs + CI** | `release.yml` 2-step split; `AGENTS.md` threading addendum; test-plan §6 cookbook; `lessons.md` entry; state-machine flip | Empty-tier exit-code-5 trap — workflow YAML cannot land before P2/P3/P4 tests carry `@pytest.mark.e2e` |

**Prerequisites:** Phase 1, 2, 3 of the rollout complete (they are: `testing-rrule-reminder-loop`, `testing-modal-stacking-wedge`, `testing-storage-malformed-input` all archived). `change.md` at `status: preparing` (already set). `research.md` present (just written).

**Estimated effort:** ~3-4 implementation sessions across 5 phases. P1 is the heaviest (fixture lift + structural fix + marker decl); P2/P3/P4 are each ~1 test class, ~50-100 LoC; P5 is docs + 4-line YAML edit + state flips.

## Open Risks & Assumptions

- **Risk:** Lifting the `clock` fixture preserves the Phase 1/2 epoch `2026-05-20 06:00 UTC` — if the form-dialog suite's different epoch (`17:23:45 UTC`, per the conftest docstring rationale) starts to cause conflicts, per-suite override remains possible without re-spawning a new fixture.
- **Risk:** The `break_reminder_app` fixture (B4) does NOT call `app.start()` to avoid spinning up pynput listeners and the real 1Hz `QTimer`. If Flow D's load-bearing assertion needs `start()` to be live, P4 must call `start()` immediately after `_action_reset.trigger()` then call `_break_scheduler._tick()` directly without entering the event loop. This is the STRUCTURAL #3 "do not enter event loop after `start()`" rule operationalized.
- **Assumption:** The `voice_phrase` validation gate at `settings_dialog.py:1246-1262` and the autostart Run-key gate at `:1272-1291` don't trip on the test's spinbox-only mutations (the test changes only `_break_interval_spinbox`; voice phrase and autostart fields stay at their default values). If a Settings field default trips a validation gate, the test sets the field explicitly to a known-safe value as a precondition.
- **Assumption:** `EventLog.record` uses real wall-clock at `event_log.py:66` (STRUCTURAL #2 deferred); Flow D's TAKEN-row oracle must read `(event_type, outcome, detail)` tuple, NOT `timestamp_iso`. If a future regression introduces a non-trivial `timestamp_iso` dependency, the deferred `EventLog.clock=` kwarg becomes mandatory.

## Success Criteria (Summary)

- `pytest -m "not e2e"` passes (562 + 1 unit tests + 5 prior integration tests).
- `pytest -m e2e` passes (3 new tests, one per flow).
- All three e2e tests would fail if any of `app.py:277`, `:278`, or `:349` connect lines were commented out — proving the R-4 contract is actually observed.
- GitHub Actions `build` job shows two test check marks (Test (unit) + Test (e2e)) on `windows-latest`.
- `test-plan.md` rollout state: `rollout_phases_complete: 4`; §3 row 4 status `complete`.
- The next-iteration `/10x-impl-review testing-top-three-e2e-flows` finds zero signal-connection-only anti-patterns in the new e2e files (research has named the five anti-patterns to scan for).
