<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Top-three e2e flows

- **Plan**: context/changes/testing-top-three-e2e-flows/plan.md
- **Scope**: Full plan (Phases 1-5)
- **Date**: 2026-06-02
- **Verdict**: APPROVED
- **Findings**: 0 critical, 1 warning, 2 observations (all FIXED during triage)

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING (1 observation — F3, fixed) |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | WARNING (1 warning + 1 observation — F1, F2, both fixed) |
| Success Criteria | PASS (566 tests · ruff clean · pyright 0 errors · pip-audit clean · CI green on PR) |

## Rollout shape

- **16/16 planned items realized** across Phases 1–5 (one commit per phase: `8c8e9c5` → `ada56ce` → `afd72be` → `a420407` → `d7cb18f`).
- **3 documented adaptations** honored intent over literal:
  - `pyproject.toml` uses `[tool.pytest]` (pytest 9.0 native) instead of `[tool.pytest.ini_options]` — the legacy table silently drops `--strict-markers` from `addopts`. Inline comment + commit `8c8e9c5` document this.
  - Flow B uses a hybrid wired-app design (mirrors the on-demand `break_interval_changed` connect locally because `_on_open_settings` blocks via `dialog.exec()`) — documented in the test's module docstring AND codified in the new `lessons.md` entry.
  - Flow D adds a `_timer.isActive()` precondition (mutation-test discovery at Progress 4.10 found the direct `_tick()` loop bypassed the timer-arm contract at `app.py:471`) — documented inline in the test.
- **2 EXTRA commits, both documented**:
  - `4ea2811` `fix(ci): correct release.yml branch trigger to master (default branch)` — pre-existing miswiring surfaced when verifying 5.15 on the PR; independent fix.
  - `c7666bc` `chore(deps): bump pyright 1.1.409 → 1.1.410` — clears the upstream-update warning; bumps `pyproject.toml`, `uv.lock`, and `test-plan.md §4`.

## Findings

### F1 — BreakDialog not registered with qtbot for teardown

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/test_save_settings_interval_e2e.py:211-216
- **Detail**: Flow B asserts `BreakDialog.isVisible()` but never registers the dialog with `qtbot.addWidget(...)` for teardown. FR-009's non-dismissable guards in `break_reminder/notifications/break_dialog.py` intentionally swallow programmatic `close()`, so the dialog can leak into the next test's modal state. The sister Flow D test handles this correctly at `tests/test_tray_reset_e2e.py:286-291`.
- **Fix**: Added `qtbot.addWidget(break_reminder_app._active_break_dialog)` after the final `.isVisible()` assertion, with a comment naming the FR-009 rationale and pointing at the Flow D mirror.
- **Decision**: FIXED

### F2 — ReminderDialog not registered with qtbot for teardown

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/test_add_reminder_e2e.py:157-165
- **Detail**: Same teardown-hygiene pattern as F1 but lower-urgency: FR-013 makes `ReminderDialog` dismissable, so programmatic `close()` works and pytest-qt's auto-teardown is less likely to be defeated. Brings all three e2e files onto a uniform shape.
- **Fix**: Added `qtbot.addWidget(reminder_dialog)` after the final `.isVisible()` assertion, with a comment contrasting the FR-013/FR-009 ownership difference.
- **Decision**: FIXED

### F3 — self._clock not assigned in BreakReminderApp.__init__

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: break_reminder/app.py:108-110
- **Detail**: Plan §"Phase 1 → Contract for app.py" said: "Store as `self._clock`." Implementation correctly propagated the kwarg to both schedulers at `app.py:111-114` (the load-bearing behavior the pin test `test_clock_kwarg_propagates_to_both_schedulers` verifies), but never assigned `self._clock = clock` on the app instance. Zero functional impact — no production consumer of the missing attribute — but it was a literal contract drift not noted in the Phase 1 Progress section.
- **Fix**: Added `self._clock = clock` next to the four existing collaborator stores (after `self._voice = ...`), preserving the documented init order.
- **Decision**: FIXED

## Post-triage verification

- `uv run pytest` — 566 passed (no regression from the three fixes).
- `uv run ruff check` — All checks passed.
- `uv run ruff format --check` — 3 files already formatted.
- `uv run pyright` — 0 errors, 0 warnings, 0 informations.

## Summary

| Decision | Findings |
|---|---|
| FIXED | F1, F2, F3 (3) |
| SKIPPED | — |
| ACCEPTED | — |
| RULE | — |
