<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: reminders-lead-time (S-06b)

- **Plan**: `context/changes/reminders-lead-time/plan.md`
- **Scope**: Phase 1 of 2
- **Date**: 2026-05-27
- **Commit**: d99f122
- **Verdict**: APPROVED
- **Findings**: 0 critical, 0 warnings, 5 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Invariants Checked

All four plan invariants hold:

- **Storage Model A** (`start_at` = firing time; `lead_minutes` is metadata) — `scheduler.py:315, 328` use `reminder.start_at` directly via `next_firing_after`.
- **`_compose_row` uses `event_at` when `lead_minutes > 0`** — `settings_dialog.py` lead-aware branch.
- **Expired branch in `_compose_row` omits "(fires N min before)"** — early return on `fire_at is None`.
- **`_fire()` uses `self._next.fire_at + lead`** (not `reminder.start_at + lead`) — `scheduler.py:308`, forward-compatible with S-08 recurrence.

## Negative Confirmations

| Check | Count |
|---|---|
| Threading violations | 0 |
| Injection risks | 0 |
| Data-loss paths | 0 |
| Pattern non-compliance (worth flagging at WARNING+) | 0 |
| Missing planned changes | 0 |
| Unplanned (EXTRA) changes | 0 |
| Scope guardrail breaches | 0 |

All 15 files in `d99f122` map cleanly to plan sites #1–#8 + roadmap (#7) + 3 bootstrap files (change.md, plan.md, plan-brief.md). The popup-text re-scope is documented as a mid-phase scope addendum (struck-through "What We're NOT Doing" line with explanation), not a silent re-scope.

## Findings

### F1 — Stream B chain notation differs from plan

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `context/foundation/roadmap.md:49`
- **Detail**: Plan prescribed `S-05 → S-06 → S-06b → S-07 / S-08` (sequential). What landed: `S-05 → S-06 → S-06b / S-07 / S-08 (parallel after S-06)`. The shipped notation is semantically more accurate — the S-06b body block at `roadmap.md:167` declares `Parallel with: ... S-07, S-08`, and both S-07/S-08 list `Prerequisites: S-06` (not S-06b). The plan text would have implied a false dependency.
- **Fix**: Reconcile the plan's prescribed-notation line under Site #7 to match the shipped roadmap. One-line edit in `plan.md`.
- **Decision**: FIXED — updated `plan.md:237` to `S-05 → S-06 → S-06b / S-07 / S-08 (parallel after S-06)` with an inline justification about S-07/S-08 prerequisites.

### F2 — Pluralization nit in past-time-with-lead tooltip

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `break_reminder/ui/reminder_form_dialog.py:122`
- **Detail**: `_PAST_TIME_WITH_LEAD_FORMAT = "Event must be at least {lead} minutes in the future"` — when `lead_minutes == 1` the tooltip reads "at least 1 **minutes** in the future". Spinbox step is 1, so `lead=1` is reachable in the first stop above default.
- **Fix**: Switch to a pluralization-aware format, e.g. `f"Event must be at least {lead} minute{'s' if lead != 1 else ''} in the future"`, and add a `lead=1` tooltip-wording regression test.
- **Decision**: FIXED — added `_format_past_time_with_lead(lead)` helper in `reminder_form_dialog.py`; constant reshaped to `"Event must be at least {lead} {unit} in the future"` with `unit` computed by the helper; call site in `accept()` updated; 2 new regression tests (`test_past_event_with_lead_one_uses_singular_minute`, `test_format_past_time_with_lead_pluralizes`) + existing `lead=15` test updated to assert against the helper. All 13 lead tests pass; ruff/pyright clean.

### F3 — `assert self._next is not None` in `_fire()` breaks under `python -O`

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Reliability
- **Location**: `break_reminder/scheduler.py:305-308`
- **Detail**: Works today because `_on_timer()` guards on `self._next` before calling `_fire()`. The assertion exists for pyright narrowing. But `python -O` strips assertions; if the PyInstaller build ever flips to optimized bytecode, `self._next.fire_at` becomes an `AttributeError` on `None`. Low probability today but silent failure mode.
- **Fix**: Replace the assert with a runtime guard that's safe under `-O` and still narrows for pyright:

  ```python
  if self._next is None:
      return  # defensive: should be unreachable via _on_timer
  event_at = self._next.fire_at + timedelta(minutes=reminder.lead_minutes)
  ```

- **Decision**: SKIPPED — pipeline doesn't use `python -O` today; the assertion's narrowing intent is still served and the failure mode is gated behind a hypothetical config change.

### F4 — Unvalidated `lead_minutes` on disk read

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Data safety
- **Location**: `break_reminder/storage/reminders.py:70`
- **Detail**: `lead_minutes=data.get("lead_minutes", 0)` accepts whatever the JSON gives — a hand-edited file with `-5`, `9999`, or `"ten"` loads silently; the string case later crashes inside `timedelta(minutes=...)`. Consistent with the project's "trust the file in `%APPDATA%`" stance (FR-015 documents the file as Notepad-editable; `start_at` ISO parsing also doesn't range-check).
- **Fix**: Defer — consistent with project posture. Worth a follow-up if/when bulk-import or settings-sync features land. If picking up now: clamp to `[_LEAD_MIN_VALUE, _LEAD_MAX_VALUE]` and coerce via `int()` at the `from_dict` boundary.
- **Decision**: FIXED — added `_LEAD_MIN_VALUE` / `_LEAD_MAX_VALUE` constants (with cross-reference to the UI source of truth) + `_coerce_lead_minutes(raw)` helper to `storage/reminders.py`; `from_dict` now routes through the helper. New `TestCoerceLeadMinutes` class with 9 tests pinning the four invariants (int passthrough, type coercion, lower clamp, upper clamp) plus an end-to-end `from_dict` hostile-input case. All 30 storage tests pass; ruff/pyright clean.

### F5 — Fixture-reuse opportunity in `tests/test_reminder_dialog.py`

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_reminder_dialog.py:89-144`
- **Detail**: All four `TestReminderDialogConstructor` tests build a `ReminderDialog` with nearly-identical shape (`name`, `event_at`, `tz`). Sibling `tests/test_break_dialog.py` uses a `make_dialog` helper to dedupe similar construction.
- **Fix**: Extract a small `_make_dialog(qtbot, *, name="anything", event_at=None, tz=UTC)` factory. Cosmetic — test suite is fast (9 tests) and the duplication is small.
- **Decision**: FIXED — added `_DEFAULT_EVENT_AT` module constant + `_make_dialog(qtbot, *, name, event_at, tz)` factory mirroring the `make_dialog` helper in `tests/test_break_dialog.py`; refactored all 4 `TestReminderDialogConstructor` tests to use it. All 9 dialog tests pass; ruff/pyright clean.
