<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Bugfix Reminder DST Drift

- **Plan**: `context/changes/bugfix-reminder-dst-drift/plan.md`
- **Scope**: Full plan (P1–P4)
- **Date**: 2026-06-02
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical | 2 warnings | 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

All 24 progress rows complete with SHA suffixes. Full suite 586 passed; pyright + ruff clean; the two Phase 4 grep SCs return expected matches. Both warnings are LOW-impact one-line fixes following the same pattern (widen the exception catch around `ZoneInfo(...)` / `tzlocal.get_localzone_name()` to match the storage-side defensive idiom that plan-review F1/F3 established).

## Findings

### F1 — Form's tzlocal call lacks defensive try/except (asymmetric with storage)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality (Reliability)
- **Location**: `break_reminder/ui/reminder_form_dialog.py:873`
- **Detail**: `accept()` calls `tzlocal.get_localzone_name() or "UTC"` with no try/except. The storage-side sibling `_coerce_tz` (`storage/reminders.py:182-186`) wraps the identical call in `try: ... except ZoneInfoNotFoundError: return "UTC"`. On Windows, tzlocal reads the Registry (`TimeZoneKeyName`) — a corrupted/missing registry key can raise. If it does mid-save, the dialog propagates to the Qt event loop instead of degrading gracefully.
- **Fix**: Wrap in try/except matching the storage sibling.
  ```python
  try:
      current_tz = tzlocal.get_localzone_name() or "UTC"
  except ZoneInfoNotFoundError:
      current_tz = "UTC"
  ```
  - Strength: Mirrors `_coerce_tz`'s exception handling; degrades to UTC rather than crashing the save dialog.
  - Tradeoff: Minor — adds 3 lines + a `from zoneinfo import ZoneInfoNotFoundError` import (or factor a shared `_current_os_local_tz()` helper used by both sites).
  - Confidence: HIGH — identical pattern already used in storage.
  - Blind spot: None significant.
- **Decision**: FIXED (Fix now). Wrapped the `tzlocal.get_localzone_name() or "UTC"` call in `try/except ZoneInfoNotFoundError` matching the storage sibling; added `from zoneinfo import ZoneInfoNotFoundError` to the stdlib import group. Comment block above the call was extended to document why both the `or "UTC"` and the `try/except` exist (empty-string return vs raise).

### F2 — `_resolve_zone` doesn't catch ValueError (asymmetric with `_coerce_tz`)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `break_reminder/scheduler.py:414-418`
- **Detail**: Plan-review F1 widened `_coerce_tz` to catch `(ZoneInfoNotFoundError, ValueError)` because `ZoneInfo("")` and `ZoneInfo("../etc/passwd")` raise `ValueError`, not `ZoneInfoNotFoundError`. The sibling `_resolve_zone` in `scheduler.py` catches only `ZoneInfoNotFoundError`. Its own docstring acknowledges the in-memory bypass paths ("test fixtures and the form-dialog save path before its own coercion runs") — exactly the surface where a malformed tz can reach the scheduler. A `tz=""` here leaks `ValueError` past the defensive wrapper.
- **Fix**: Widen the except clause.
  ```python
  except (ZoneInfoNotFoundError, ValueError):
      logger.warning("invalid IANA timezone %r; falling back to UTC", name)
      return ZoneInfo("UTC")
  ```
  - Strength: Aligns with the plan-review F1 lesson applied to `_coerce_tz`; closes the bypass surface the docstring already identifies.
  - Tradeoff: None — strictly a defensive widening.
  - Confidence: HIGH — identical pattern in `_coerce_tz`.
  - Blind spot: None significant.
- **Decision**: FIXED (Fix now). Widened the `except` clause to `(ZoneInfoNotFoundError, ValueError)`; updated the WARNING message from "unknown IANA timezone" to "invalid IANA timezone" to cover both failure modes; extended the docstring to explain the parallel with `_coerce_tz` and cite impl-review F2 as the rationale.

### F3 — Default-factory invokes tzlocal per Reminder construction

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — note only, no fix needed today
- **Dimension**: Performance
- **Location**: `break_reminder/storage/reminders.py:236`
- **Detail**: `tz: str = field(default_factory=lambda: _coerce_tz(None))` calls `tzlocal.get_localzone_name()` per construction on the default path. On Windows, this reads the Registry. Today the cost is negligible (hot paths are bounded: `store._read` once per `list_all()`; form once per save). If a future bulk-import surface appears, cache the OS-local name once per process via `functools.cache`.
- **Fix**: Leave as-is. If/when a bulk-construction surface appears, introduce a cached `_os_local_name()` resolver.
- **Decision**: SKIPPED. Accepted as-is per the OBSERVATION-tier recommendation; revisit if a bulk-construction surface appears.

### F4 — Documented adaptations (consolidated)

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — note only
- **Dimension**: Plan Adherence
- **Location**: Multiple — see detail
- **Detail**: Four small, documented deviations from the plan's letter; none affect intent.
  - **(a)** Forward-looking archive paths in `AGENTS.md:88`, `context/foundation/test-plan.md:174`, and the appended NOTE in the archived impl-review — all link to `context/archive/2026-06-02-bugfix-reminder-dst-drift/`. Deliberate; resolves correctly when `/10x-archive` runs (deterministic per the `change.md` `created:` date).
  - **(b)** Form variable names `current_tz`/`persisted_tz` instead of plan's `tz_name`/`tz_to_use`. Semantically identical.
  - **(c)** Test names slightly tweaked (e.g. `test_edit_preserves_tz_when_only_name_changed` vs plan's `test_edit_path_preserves_tz_when_only_name_changed`). Scenarios covered identically.
  - **(d)** R-1b regression test `now` adapted from plan's `2026-03-28 07:00 UTC` to `2026-03-28 08:30 UTC` because `07:00 UTC` returns the first firing on both code paths and never traverses the DST boundary — empirically verified. Adaptation is explained in the test class docstring with full justification.
  - **(e)** `tests/test_settings_dialog.py::test_active_recurring_custom_appends_custom_suffix` pinned to `tz="UTC"`. User-approved P2 adaptation ("pin_utc" decision) when the test inadvertently relied on pre-fix UTC-anchored behavior. Documented in the test docstring.
- **Fix**: No action needed. Each deviation has a documented rationale at the deviation site.
- **Decision**: SKIPPED. Accepted as-is; all five deviations carry documented rationale at their respective sites.

## Pattern observation

Both WARNINGs (F1, F2) are the same shape: plan-review F1 widened `_coerce_tz` to catch `(ZoneInfoNotFoundError, ValueError)` because `ZoneInfo(str)` can raise either, but the lesson didn't propagate to the two sibling surfaces that also call `ZoneInfo(...)` (`_resolve_zone`) or `tzlocal.get_localzone_name()` (`accept()`). Worth recording as a lesson: "**when widening defensive exception coverage on a helper, audit every other call site that touches the same underlying API**".

## What's clean

- All 24 progress rows complete with SHA suffixes (P1: 0cbfb4b; P2: 5360c11; P3: 8221bca; P4: 68ee93f, 5df33ed)
- Storage-boundary lesson (lessons.md L3) properly honored: per-field `_coerce_*` (`_coerce_tz` matches `_coerce_lead_minutes` / `_coerce_aware_utc` precedent) + per-row containment in `ReminderStore._read` (typo'd tz drops one row, siblings preserved)
- Google-style docstrings (lessons.md L1) on every new public surface (`InvalidTimezoneError`, `_coerce_tz`, `_resolve_zone`, `next_firing_after` rewrite, `Reminder.tz`)
- PyInstaller `--collect-data tzdata` consistent across `pyproject.toml` comment block AND `release.yml` workflow with matching rationale comments
- Threading clean: all new code on main thread; no pynput-listener or voice-worker reach
- Test oracles independent: RRULE spec + IANA Europe/Warsaw rule, not "run scheduler and snapshot"
- `firing_unchanged_in_edit` predicate reused as single source of truth for both past-time skip AND F2 tz preserve-vs-refresh (plan's stated intent)
- Two-layer defensive validation (storage-strict, scheduler-lenient) documented in plan §"Critical Implementation Details" and present in code
- 3 new TestDstDrift tests pin three angles (spring-forward correct, flat-window 24h cadence correct, UTC identity preserved) — a wrong-but-coincidentally-right implementation would trip on at least one
