# Testing R-1 Recurring-Reminder Re-arm Loop Implementation Plan

## Overview

Phase 1 of the `context/foundation/test-plan.md` rollout — pin R-1's recurring-reminder *fire → re-arm → fire-again* loop and the 24h `QTimer.singleShot` cap re-entry across firings. Pure test additions plus one prerequisite refactor (extract the duplicated `Clock` test helper to `tests/conftest.py`). The R-1b DST-drift defect surfaced by `/10x-research` is documented in a `TODO(R-1b)` block and deferred to a separate `/10x-shape` cycle as `bugfix-reminder-dst-drift`.

## Current State Analysis

- `tests/conftest.py` exists but only holds the session-scoped `_qt_app` autouse fixture. The `Clock` helper class is **duplicated verbatim across three files**: `tests/test_break_scheduler.py:35-48`, `tests/test_reminder_scheduler.py:27-40`, and `tests/test_reminder_form_dialog.py:82-95`. The scheduler files pin their local `clock` fixture at `2026-05-20 06:00 UTC`; the form-dialog file pins at `2026-05-20 17:23:45 UTC` via a `frozen_utc` fixture (deliberately offset from a quarter-hour boundary for the form's +1h rounding tests). Conftest extraction targets the `Clock` *class* only — per-file `clock` fixtures stay local because each file's epoch encodes test-specific intent.
- `tests/test_reminder_scheduler.py:215-245` (`test_on_timer_fires_when_clock_caught_up`) pins the **first** firing of a one-shot reminder. It never advances the clock further and asserts the **second** firing of a recurring reminder — exactly the R-1a gap.
- `tests/test_reminder_scheduler.py:130-150` (`test_reload_caps_timer_at_24h_for_far_future_reminder` — the F1 retrofit) pins the 24h cap for a one-shot 30 days out. `tests/test_reminder_scheduler.py:185-213` (`test_on_timer_early_wakeup_rearms_via_clock`) pins the early-wakeup re-arm branch for a one-shot. **Neither test crosses a `_fire` boundary**, so a regression that broke the cap re-entry after the first fire of a recurring reminder would not fail any existing test — R-1c gap.
- Production code (`break_reminder/scheduler.py:297-319`) is **correct** for R-1a and R-1c per research; both are pure coverage gaps, not code defects. R-1b (DST drift in recurring firings) is a real production defect requiring a `Reminder` invariant change — explicitly out of scope for this rollout phase per the user's "defer with TODO" decision.
- `context/foundation/test-plan.md` §3 row 1 status reads `change opened`; the orchestrator (`/10x-test-plan` re-run) needs the cell flipped to `complete` once this change lands, plus the §6 Cookbook row for "Recurring-reminder re-arm loop" replaced from TBD to the landed pattern.

## Desired End State

- `tests/conftest.py` owns the `Clock` class + `clock` pytest fixture. Both existing scheduler test files (`test_break_scheduler.py`, `test_reminder_scheduler.py`) consume the shared definitions via pytest's auto-discovery; existing tests still pass with byte-identical behaviour (collected count unchanged vs HEAD baseline).
- `tests/test_recurring_reminder_integration.py` exists with a single `TestRecurringReminderReArm` class containing four new tests (daily, weekly-13-days-out, monthly, lead-minutes × daily across two firings). The weekly test doubles as R-1c (the 13-day `start_at` forces cap re-entry across a `_fire` boundary). Module docstring names R-1 and links to test-plan §2 + research.md. A module-level `TODO(R-1b)` comment block names the open question and points to research.md Open Questions #1 / #2.
- `context/foundation/test-plan.md` frontmatter has `rollout_phases_complete: 1`; §3 row 1 status reads `complete`; §6 Cookbook row "Recurring-reminder re-arm loop" replaces the TBD with the landed pattern shape; §7 Negative space adds a one-bullet R-1b deferral note carrying the bugfix-change breadcrumb.

**How to verify**: `uv run pytest` reports the HEAD test count + 4 all green; `uv run ruff check` is green (pydocstyle D rule satisfied on all four new test methods); `uv run pyright` is green; `git diff` shows the conftest extraction is delete-only on the two existing test files; the test-plan §6 Cookbook row no longer contains "TBD"; the §7 Negative space contains the R-1b deferral bullet.

### Key Discoveries:

- `Clock` is duplicated verbatim across **three** files: `tests/test_break_scheduler.py:35-48`, `tests/test_reminder_scheduler.py:27-40`, and `tests/test_reminder_form_dialog.py:82-95`. The two scheduler files share epoch `2026-05-20 06:00 UTC`; the form-dialog file uses `2026-05-20 17:23:45 UTC` to exercise +1h rounding-boundary behaviour. Conftest extraction is class-only — divergent epochs stay encoded in each file's local `clock` fixture.
- `_on_timer` post-fire re-arm runs the **full** `reload()` → `_compute_next()` pipeline (the `self.reload()` call at the end of `_on_timer`) — stronger than the test-plan prompt assumed; a stale `_next` cannot survive a fire. This is what the integration test pins.
- A weekly reminder with `start_at` set well past the 24h cap (the test picks 13 days out — a Tuesday on `2026-06-02`) forces the cap re-entry path because the first occurrence is > 24h away — a single test exercises both R-1a (re-arm after fire) and R-1c (cap re-entry across the fire boundary) economically.
- `next_firing_after` uses `rule.after(now, inc=False)` (`scheduler.py:367`); the oracle for "next firing after N days" is `dtstart + N*period`, derived from the RRULE spec — NOT from re-reading scheduler internals. This satisfies the test-plan §2 R-1 "Anti-pattern to avoid" rule.
- Every existing scheduler test datetime uses `tzinfo=UTC` (UTC has no DST), which is why R-1b never surfaced in the existing test suite.

## What We're NOT Doing

- **Fixing R-1b (DST drift in recurring firings).** That requires changing the `Reminder.start_at` invariant from UTC to a zone-aware IANA timezone, touching the dataclass, storage round-trip (`from_dict` / `to_dict`), form save/load, and every test that constructs a `Reminder`. Open a separate `/10x-shape` cycle (`bugfix-reminder-dst-drift`) — research.md Open Question #2 names the candidate fix shapes.
- **Writing an xfail test for R-1b.** User picked "defer with TODO". The `TODO(R-1b)` module comment block is the regression trail; research.md is the record. No `pytest.mark.xfail` noise in CI.
- **Introducing `@pytest.mark.integration` or registering it in `pyproject.toml`.** Deferred to Phase 4 of the rollout (the CI-tier-split phase, see test-plan §3 row 4). The file-name convention `test_*_integration.py` is Phase 4's breadcrumb.
- **Researching R-2 / R-3 / R-4.** Those are Phase 2 / Phase 3 / Phase 4's research scope. Research.md Open Question #4 already flagged that R-2 anchors live in the dialog layer, not `scheduler.py`.
- **Heavyweight pytest-qt wiring (`qtbot`, `waitSignal`).** The existing direct `_on_timer()` + recording-slot idiom is sufficient — no real Qt event-loop wait needed; tests stay sub-50ms each.
- **Backporting any of the new tests onto `test_reminder_scheduler.py`.** Integration tests live in their own file by file-name convention; the existing file stays unit-scoped.

## Implementation Approach

Two phases. Phase 1 is a pure refactor (move `Clock` + `clock` fixture to conftest, delete duplicates, verify existing tests still pass with collected count unchanged vs HEAD baseline). Phase 2 adds the four net-new integration tests and the test-plan doc refresh. The split lets manual verification at Phase 1's end be "all existing tests still pass" before any new tests land — clean diff for code review, clean rollback boundary if Phase 1 surprises.

## Critical Implementation Details

- **Conftest auto-discovery semantics.** pytest auto-loads fixtures defined in `tests/conftest.py` for every test file in `tests/` — no `import` statement needed in `test_break_scheduler.py` / `test_reminder_scheduler.py` for the `clock` fixture to resolve. The `Clock` **class** is referenced only as a type annotation in fixture signatures; tests that type-annotate `clock: Clock` need `from tests.conftest import Clock`, but tests that omit the annotation don't. Verify by running the suite after deletion; pyright will catch unresolved annotations.
- **Oracle source rule.** Every assertion on `event_at` or `fire_at` in the new tests must compute the expected value **from the RRULE specification** (e.g. `start_at + timedelta(days=1)` for `FREQ=DAILY`), NOT by re-reading `next_firing_after` and mirroring its arithmetic. This is the test-plan §2 R-1 anti-pattern. If a future RRULE bug changes `next_firing_after`'s output, the test must FAIL — not silently agree with the regression.

## Phase 1: Extract shared `Clock` test helper to conftest

### Overview

Move the duplicated `Clock` class out of the three test files (`test_break_scheduler.py`, `test_reminder_scheduler.py`, `test_reminder_form_dialog.py`) into `tests/conftest.py`. Each file keeps its local `clock` fixture (epochs diverge: schedulers at `2026-05-20 06:00 UTC`, form-dialog at `2026-05-20 17:23:45 UTC` for rounding-boundary tests). The new Phase 2 file declares its own local `clock` fixture at the scheduler epoch and imports `Clock` from conftest. No new tests in this phase; the win is "existing tests still pass with the duplication removed (collected count unchanged vs HEAD baseline)", and the rollout's future phases (2-4) get a single canonical `Clock` class to extend.

### Changes Required:

#### 1. Conftest extraction

**File**: `tests/conftest.py`

**Intent**: Add the `Clock` class (mutable callable time source pinned at a fixed epoch and advanced via `.advance(seconds)`) to the shared conftest so every test file in `tests/` consumes a single canonical implementation. **No `clock` fixture is added to conftest** — each consuming file keeps its own local `clock` fixture because epochs diverge (schedulers vs form-dialog rounding boundary). Keep the existing `_qt_app` session-scoped autouse fixture untouched and at the top of the file.

**Contract**: `Clock` exported at module top with three public members preserved exactly: `__init__(start: datetime)`, `__call__() -> datetime`, `advance(seconds: float) -> None`. All public methods carry Google-style docstrings per `context/foundation/lessons.md` (ruff D rule). The file imports `datetime, timedelta, UTC` from the stdlib `datetime` module. No new fixtures.

#### 2. Remove duplicate from break-scheduler tests

**File**: `tests/test_break_scheduler.py`

**Intent**: Delete the local `Clock` class definition (lines 35-48). Keep the local `clock` fixture (lines 67-70) — its `2026-05-20 06:00 UTC` epoch is the file's invariant. Add `from tests.conftest import Clock` at the top of the imports block (~20+ test method signatures plus the `clock` and `scheduler` fixtures annotate the parameter as `Clock`, so the import is mandatory, not optional).

**Contract**: After the edit, the file has no local `Clock` class; the local `clock` fixture is unchanged in shape and epoch; every existing test in the file still passes with byte-identical observable behaviour.

#### 3. Remove duplicate from reminder-scheduler tests

**File**: `tests/test_reminder_scheduler.py`

**Intent**: Delete the local `Clock` class definition (lines 27-40). Keep the local `clock` fixture (lines 43-51) — its `2026-05-20 06:00 UTC` epoch matches `test_break_scheduler.py`'s; both stay local because the new Phase 2 file uses the same epoch and we don't want the scheduler-specific epoch leaking into a shared conftest where the form-dialog file would inherit it by name collision. Add `from tests.conftest import Clock` at the top of the imports block (every test method signature in `TestClockInjection` and adjacent classes annotates `clock: Clock`).

**Contract**: After the edit, the file has no local `Clock` class; the local `clock` fixture is unchanged in shape and epoch; every existing test in the file still passes with byte-identical observable behaviour.

#### 4. Remove duplicate from reminder-form-dialog tests

**File**: `tests/test_reminder_form_dialog.py`

**Intent**: Delete the local `Clock` class definition (lines 82-95). Keep both the `frozen_utc` fixture (lines 99-106) and the local `clock` fixture (lines 109-112) — `frozen_utc` pins `2026-05-20 17:23:45 UTC` deliberately off a quarter-hour boundary for the form's `_compute_default_datetime` +1h rounding tests, and the local `clock` fixture is wired to it. Add `from tests.conftest import Clock` at the top of the imports block (~80+ test method signatures annotate `clock: Clock`).

**Contract**: After the edit, the file has no local `Clock` class; the `frozen_utc` + local `clock` fixtures are unchanged in shape and epoch; every existing test in the file still passes with byte-identical observable behaviour.

### Success Criteria:

#### Automated Verification:

- All existing tests pass: `uv run pytest` — collected count unchanged vs HEAD baseline (capture `uv run pytest --collect-only -q | Select-Object -Last 1` before and after to compare)
- Ruff lint passes (pydocstyle D rule on the moved `Clock` class + `clock` fixture): `uv run ruff check tests/`
- Pyright type check passes (resolves the `Clock` import / annotation correctly): `uv run pyright`

#### Manual Verification:

- `git diff tests/test_break_scheduler.py tests/test_reminder_scheduler.py tests/test_reminder_form_dialog.py` shows only one deletion block per file (the `Clock` class) plus one added import line per file; no test-body changes, no fixture changes
- `git diff tests/conftest.py` shows additions only (the existing `_qt_app` fixture is untouched and stays first); no new `clock` fixture is added — only the `Clock` class
- Running the three affected test files (`uv run pytest tests/test_break_scheduler.py tests/test_reminder_scheduler.py tests/test_reminder_form_dialog.py`) reports the same combined count as the pre-extraction HEAD baseline

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual verification was successful before proceeding to Phase 2.

---

## Phase 2: Add recurring-reminder integration tests + refresh test-plan docs

### Overview

Create `tests/test_recurring_reminder_integration.py` with four new tests pinning R-1a (re-arm across daily / weekly / monthly RRULEs) and R-1c (24h cap re-entry across the fire boundary via the weekly test). Add a dedicated lead-minutes × recurrence test that pins the S-06b `event_at = fire_at + lead_minutes` contract across two firings. Then refresh `context/foundation/test-plan.md` to flip the §3 status cell, populate the §6 Cookbook entry, and add R-1b to §7 Negative space.

### Changes Required:

> **Atomicity note**: Phase 2's two changes are an **atomic unit** — do not commit only one. If the new test file lands without the test-plan.md refresh, the rollout-state cells (`rollout_phases_complete: 0`, §3 row 1 status `change opened`) stay stale on disk while integration tests already exist, and `/10x-test-plan` re-runs misroute back to Phase 1 instead of advancing to Phase 2. Change #1 (docs) lands first because it's the orchestrator's state-machine update; #2 (tests) lands second as the artifact the docs now describe.

#### 1. Test plan status + Cookbook + Negative space refresh

**File**: `context/foundation/test-plan.md`

**Intent**: Flip the orchestrator's state-machine cells in §3 so the next `/10x-test-plan` re-run routes to Phase 2 (R-2 modal stacking). Replace the §6 Cookbook TBD for "Recurring-reminder re-arm loop" with the landed pattern shape (the file the next change introduces). Add R-1b to §7 Negative space as a deferred discovery, carrying the bugfix-change breadcrumb.

**Contract**:

- Frontmatter line `rollout_phases_complete: 0` → `rollout_phases_complete: 1`.
- §3 row 1 (`Integration-test foundation + recurring-reminder loop`): the `Status` cell `change opened` → `complete`. No other cells in that row change. No other rows in §3 change.
- §6 Cookbook row "Recurring-reminder re-arm loop": replace the TBD prose with — *`tests/test_recurring_reminder_integration.py::TestRecurringReminderReArm` — seed `Reminder(start_at, rrule_str)` → `reload` → connect recording slot to `reminder_due` → advance `Clock` past first `fire_at` → call `_on_timer()` → assert first signal → advance `Clock` past next RRULE step → call `_on_timer()` → assert second signal with `event_at = dtstart + period` (oracle from RRULE spec, NEVER from scheduler internals). Weekly with `start_at` set well past the 24h cap (the test uses 13 days out) doubles as the cap-re-entry exercise.*
- §7 Negative space: append a new bullet after the existing list — **"No DST-drift fix for recurring firings.** Phase 1 research surfaced that recurring reminders silently drift ±1h across DST transitions because RRULE math runs in UTC space against a UTC-invariant storage layer (see `context/changes/testing-rrule-reminder-loop/research.md` §R-1b). The fix changes the `Reminder.start_at` invariant from UTC to IANA-tz-aware; it warrants its own `/10x-shape` cycle as `bugfix-reminder-dst-drift`. The `TODO(R-1b)` comment block in `tests/test_recurring_reminder_integration.py` carries the breadcrumb. Re-evaluate this entry when the bugfix change opens." No other §7 bullets change.

#### 2. New integration test file

**File**: `tests/test_recurring_reminder_integration.py`

**Intent**: First integration test file in the rollout — crosses the `_fire` boundary and re-asserts on the post-fire `_next` state, which the existing per-method unit tests in `test_reminder_scheduler.py` deliberately don't do. Pins R-1a (re-arm after fire) for daily, weekly, and monthly RRULEs; pins R-1c (24h cap re-entry across the fire boundary) via the weekly test whose `start_at` is 13 days out. Adds a dedicated lead-minutes × recurrence test pinning the S-06b signal contract across two firings (the existing one-shot test at `tests/test_reminder_scheduler.py:247-276` covers only the first firing). Module docstring names R-1 and the test-plan §2 row; module-level `TODO(R-1b)` comment block carries the DST-drift breadcrumb to research.md.

**Contract**: One `TestRecurringReminderReArm` class containing exactly four test methods. The file declares **local** `clock`, `store_path`, `store`, `scheduler` pytest fixtures (mirroring `tests/test_reminder_scheduler.py`'s shape — conftest does not provide a shared `clock` fixture because epochs diverge across consumers). The local `clock` fixture uses the same `2026-05-20 06:00 UTC` epoch as the scheduler test files. The file imports `Clock` from `tests.conftest` and `Reminder, ReminderStore` from `break_reminder.storage.reminders` and `ReminderScheduler` from `break_reminder.scheduler`. Each method:

1. Builds a `Reminder(name=..., start_at=clock() + offset, rrule_str="FREQ=...")` (and `lead_minutes=N` for the lead test only).
2. Calls `store.add(...)` then `scheduler.reload()`.
3. Connects a recording slot `def _capture(name: str, event_at: datetime) -> None: received.append((name, event_at))` to `scheduler.reminder_due`.
4. Drives the *advance clock past first `fire_at` → call `_on_timer()` → assert first signal received → advance clock past next RRULE step → call `_on_timer()` → assert second signal received with the oracle-computed `event_at`* loop.
5. Asserts the oracle for the second firing's `event_at` is computed from the RRULE spec (`start_at + 1*period`), **NEVER** from re-reading `scheduler.py`.

The four test methods (titles are stable — do not rename):

- `test_daily_reminder_fires_today_and_tomorrow` — `FREQ=DAILY`, `start_at = clock() + 10min`; asserts `received[0] == (name, start_at)` after first fire and `received[1] == (name, start_at + timedelta(days=1))` after second fire.
- `test_weekly_reminder_fires_first_occurrence_after_cap_reentry` — `FREQ=WEEKLY;BYDAY=TU`, `start_at = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)` — a Tuesday 13 days after the scheduler-file epoch (`2026-05-20 06:00 UTC` is a Wednesday); the first `BYDAY=TU` occurrence is `start_at` itself and is well past the 24h cap. Drives `_on_timer()` once with the clock unchanged to exercise the cap re-entry early-wakeup branch (`scheduler.py:314-317`), THEN advances clock past first `fire_at` and `_on_timer()` again (fire + reload), then advances another 7 days and `_on_timer()` again. Oracles: first firing's `event_at == datetime(2026, 6, 2, 9, 0, tzinfo=UTC)`; second firing's `event_at == datetime(2026, 6, 9, 9, 0, tzinfo=UTC)`. Double-purpose: R-1a + R-1c.
- `test_monthly_reminder_fires_this_month_and_next` — `FREQ=MONTHLY;BYMONTHDAY=15`, `start_at = 2026-06-15 09:00 UTC` (after the conftest epoch). First fire at `start_at`, second at `2026-07-15 09:00 UTC` — oracle derived from RRULE spec, NOT from `dateutil.relativedelta` re-implementation.
- `test_recurring_with_lead_minutes_offsets_each_event_at` — `FREQ=DAILY`, `lead_minutes=15`, `start_at = clock() + 10min`; asserts `received[0][1] == start_at + timedelta(minutes=15)` AND `received[1][1] == start_at + timedelta(days=1, minutes=15)` — the S-06b contract holds across two firings, not just the first.

Module-level `TODO(R-1b)` block (placed at the top of the file, after the module docstring and imports, before the test class):

```python
# TODO(R-1b): A failing test pinning the DST-drift defect surfaced by
# `/10x-research` is intentionally NOT in this file — the fix requires a
# Reminder.start_at invariant change (UTC -> IANA-tz-aware) and warrants
# its own `/10x-shape` cycle as `bugfix-reminder-dst-drift`. See:
#   context/changes/testing-rrule-reminder-loop/research.md  (section R-1b)
#   context/changes/testing-rrule-reminder-loop/research.md  Open Questions #1, #2
# When the bugfix change opens, the failing test belongs in
# tests/test_scheduler.py (next_firing_after RRULE arithmetic across DST),
# NOT here — DST is a pure-helper concern, not an integration concern.
```

### Success Criteria:

#### Automated Verification:

- New + existing tests all pass: `uv run pytest` — collected count is HEAD baseline + exactly 4
- Ruff lint passes (Google-style docstrings on all four new test methods + module docstring per `context/foundation/lessons.md`): `uv run ruff check`
- Pyright type check passes: `uv run pyright`
- Pip-audit clean (no new runtime / dev deps were added): `uv run pip-audit`

#### Manual Verification:

- Run a single new test in isolation to confirm the recording-slot pattern wires up as expected: `uv run pytest tests/test_recurring_reminder_integration.py::TestRecurringReminderReArm::test_daily_reminder_fires_today_and_tomorrow -v`
- Inspect a deliberate-regression failure mode: temporarily comment out the **post-fire `self.reload()` call at the end of `_on_timer`** in `break_reminder/scheduler.py` (the only `reload()` call inside `_on_timer` that follows `self._fire(...)`), re-run the daily test, confirm it fails with a clear mismatch on the second-firing assertion (received only the first firing, not both). Revert the comment.
- Confirm `context/foundation/test-plan.md` §3 row 1 status cell reads `complete` and §6 Cookbook row "Recurring-reminder re-arm loop" no longer contains "TBD".
- Confirm `tests/test_recurring_reminder_integration.py` carries the `TODO(R-1b)` module comment block and that it references both `context/changes/testing-rrule-reminder-loop/research.md` §R-1b and the research.md Open Questions section.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual verification was successful. Once green, the rollout-phase-1 change is ready to commit and the `/10x-test-plan` re-run will route the user to Phase 2 (R-2 modal stacking).

---

## Testing Strategy

### Unit Tests:

- No new pure-unit tests in this rollout phase. The pure RRULE arithmetic is already covered for one-shots in `tests/test_scheduler.py` and `tests/test_reminder_scheduler.py`; the gap was integration, not unit. The R-1b DST-drift unit test belongs in `tests/test_scheduler.py` and lands with the future `bugfix-reminder-dst-drift` change.

### Integration Tests:

- The four new tests **are** the integration tests for R-1. They cross the `_fire` boundary and re-assert on the post-fire `_next` state — the qualifying distinction from per-method unit tests. They re-use the conftest `Clock` injection rather than `qtbot.waitSignal`, keeping runtime sub-50ms per test.

### Manual Testing Steps:

1. Pull the branch on a fresh Windows 11 dev environment, run `uv sync && uv run pytest` — confirm the collected count increases by exactly 4 vs the pre-merge HEAD baseline with no failures.
2. Deliberate-regression smoke: comment out the post-fire `self.reload()` call at the end of `_on_timer` in `break_reminder/scheduler.py`, re-run the daily test, confirm clear failure on the second-firing assertion. Revert.
3. Read the refreshed test-plan §6 Cookbook row and confirm it gives a future `/10x-tdd` run enough scaffolding to write a Phase 2 modal-stacking test without re-reading research.md.

## Performance Considerations

- The four new tests use direct `_on_timer()` calls against the conftest `Clock`; no real-time waits, no `QTimer` event-loop spin. Each test should run < 50ms. Total suite runtime impact < 250ms — invisible against the existing ~few-second suite.

## Migration Notes

- None. The conftest extraction is a refactor with zero production-code touch; the new test file is purely additive.

## References

- Related research: `context/changes/testing-rrule-reminder-loop/research.md` (§R-1a, §R-1c, §R-1b, Open Questions #1–#2, #4)
- Test-plan rollout state: `context/foundation/test-plan.md` §2 R-1, §3 row 1, §6 Cookbook row 1, §7 Negative space
- Test idiom anchors: `tests/test_reminder_scheduler.py:27-40` (Clock helper to extract), `tests/test_reminder_scheduler.py:215-245` (recording-slot pattern to mirror), `tests/test_break_scheduler.py:35-48` (parallel duplication being removed)
- Production code being asserted on (read-only — no change): `break_reminder/scheduler.py:297-306` (cap), `break_reminder/scheduler.py:310-319` (re-arm), `break_reminder/scheduler.py:348-373` (`next_firing_after` — oracle reference, not oracle source)
- Historical context: `context/archive/2026-05-27-reminders-add-form/reviews/retrospective-impl-review.md:54-71` (F1 24h-cap retrofit this rollout extends)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Extract shared `Clock` test helper to conftest

#### Automated

- [x] 1.1 All existing tests pass (collected count unchanged vs HEAD baseline): `uv run pytest`
- [x] 1.2 Ruff lint passes on the moved Clock class + clock fixture: `uv run ruff check tests/`
- [x] 1.3 Pyright type check passes: `uv run pyright`

#### Manual

- [x] 1.4 `git diff` on the two existing test files shows only deletions (plus optionally one import line each)
- [x] 1.5 `git diff tests/conftest.py` shows additions only (existing `_qt_app` fixture untouched)
- [x] 1.6 Running the two existing scheduler test files in isolation reports 41 tests passing

### Phase 2: Add recurring-reminder integration tests + refresh test-plan docs

#### Automated

- [ ] 2.1 New + existing tests all pass (collected count = HEAD baseline + exactly 4): `uv run pytest`
- [ ] 2.2 Ruff lint passes (Google-style docstrings on 4 new test methods + module docstring): `uv run ruff check`
- [ ] 2.3 Pyright type check passes: `uv run pyright`
- [ ] 2.4 Pip-audit clean (no new deps): `uv run pip-audit`

#### Manual

- [ ] 2.5 Single new test runs green in isolation: `uv run pytest tests/test_recurring_reminder_integration.py::TestRecurringReminderReArm::test_daily_reminder_fires_today_and_tomorrow -v`
- [ ] 2.6 Deliberate-regression smoke (comment out the post-fire `self.reload()` at end of `_on_timer` in `scheduler.py`, re-run daily test, confirm clear failure, revert)
- [ ] 2.7 `context/foundation/test-plan.md` §3 row 1 status reads `complete` and §6 Cookbook row no longer contains "TBD"
- [ ] 2.8 `TODO(R-1b)` module comment block present in new test file and references research.md §R-1b + Open Questions
