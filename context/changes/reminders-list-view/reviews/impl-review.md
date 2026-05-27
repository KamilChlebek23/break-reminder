<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Reminders List View (S-05)

- **Plan**: `context/changes/reminders-list-view/plan.md`
- **Scope**: Full plan (Phase 1 + Phase 2)
- **Date**: 2026-05-27
- **Verdict**: APPROVED
- **Findings**: 0 critical | 0 warnings | 3 observations
- **Commits in scope**:
  - `5e0ab06` feat(reminders-list-view): add read-only Reminders tab (p1)
  - `b19628a` chore(reminders-list-view): manual smoke + bookkeeping (p2)
  - `b68ec85` chore(reminders-list-view): close out plan (epilogue)

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Critical Implementation Details — all verified in code

- Tooltip on wrapper `QWidget`, not the disabled `QPushButton` (`settings_dialog.py:690-695`)
- `_sort_key` returns 2-tuple expired / 3-tuple future, no `datetime.max` unification (`settings_dialog.py:258-260`)
- `_format_firing` calls `.astimezone(tz)` before `strftime` (`settings_dialog.py:227`)
- `reminder_store.list_all()` called exactly once per dialog construction (`settings_dialog.py:628`)

## Findings

### F1 — `QWidget()` missing parent argument in `_build_reminders_button_row`

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `break_reminder/ui/settings_dialog.py:673`
- **Detail**: `row = QWidget()` was built without a parent argument while every sibling `QWidget()` construction in the same file passes one (`wrapper = QWidget(row)` at line 690, `tab = QWidget(self._tabs)` at line 621). Qt re-parents on `layout.addWidget(...)`, so functionally fine — but inconsistent with the established convention.
- **Fix**: Change `row = QWidget()` to `row = QWidget(self)`.
- **Decision**: FIXED — changed `row = QWidget()` → `row = QWidget(self)` at `settings_dialog.py:673`. Test suite still passes (99/99 in `tests/test_settings_dialog.py`).

### F2 — `datetime.now(UTC)` computed before empty-store branch

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Performance
- **Location**: `break_reminder/ui/settings_dialog.py:627`
- **Detail**: `now = datetime.now(UTC)` runs unconditionally before the `if not reminders:` branch at line 634; on the empty path the value is never read. Microscopic cost (~1 µs). Current placement keeps the "single shared now" rationale comment colocated with the assignment.
- **Fix**: Leave as-is — cost is negligible, comment placement is better where it is. Only consider relocating if profiling ever flags it (it won't).
- **Decision**: SKIPPED — accepted as documented placement trade-off; cost is genuinely negligible.

### F3 — `_on_reminders_selection_changed` body uses `del current_row` not `pass`

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `break_reminder/ui/settings_dialog.py:721`
- **Detail**: Plan §4 Contract said "Body is `pass` in this slice." Implementation uses `del current_row  # S-05 placeholder; S-07 uses this to gate enable state.` instead. Functionally identical no-op; the `del` suppresses the "unused argument" lint that bare `pass` would otherwise trigger.
- **Fix**: Leave as-is — the variant is strictly better than the plan's bare `pass`, and the inline comment carries S-07 hand-off documentation the plan would otherwise lose.
- **Decision**: SKIPPED — accepted as a strict improvement over the literal plan text; deliberately not amending the plan because the divergence is too small to warrant a follow-up.

## Notes worth recording

- **Lessons rule observed**: every new `_`-prefixed helper carries a Google-style docstring even though private helpers are exempt by default — they all encode non-obvious behavior (tuple-shape sort key, tz injection, tooltip-wrapper workaround), so the docstrings are warranted per the `context/foundation/lessons.md` exception clause.
- **`timedelta` / `timezone` were correctly NOT added to `settings_dialog.py` imports** — the plan §4a listed them but they're only used in tests. The implementation is tighter than the plan called for.
- **All three pre-disclosed adaptations** landed in the files the user said they would:
  1. 520-px `_DIALOG_MINIMUM_WIDTH` + tripwire test `test_dialog_enforces_minimum_width` (manual-verification driven)
  2. S-05 Backlog Handoff row updated to match the S-02..S-04 convention (consistency with existing pattern)
  3. Phase 2 success-criterion 2.2 grep tightened from `S-05.*proposed` to `^| S-05 .*proposed` (avoids S-06's "S-05" Prerequisites false-positive)

## Triage summary

- Fixed:   F1               (1)
- Skipped: F2, F3           (2)
