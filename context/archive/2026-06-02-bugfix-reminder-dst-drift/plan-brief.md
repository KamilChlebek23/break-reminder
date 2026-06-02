# Bugfix Reminder DST Drift — Plan Brief

> Full plan: `context/changes/bugfix-reminder-dst-drift/plan.md`
> Research: `context/changes/bugfix-reminder-dst-drift/research.md`

## What & Why

Fix the R-1b DST-drift defect: recurring reminders like "Daily 9:00 Europe/Warsaw" silently shift by an hour after DST transitions because `dateutil.rrule.rrulestr(rule, dtstart=start_utc).after(now)` does RRULE arithmetic in UTC space (where DST doesn't exist). RRULE handles DST correctly only when `dtstart` carries a named IANA timezone — not when it carries `tzinfo=UTC`. The user-visible failure: a daily 9:00 reminder fires at 10:00 wall-clock on the first post-DST day.

## Starting Point

The codebase has zero IANA timezone infrastructure beyond `datetime.UTC` — no `zoneinfo`, no `dateutil.tz`, no Settings tz key, no UI tz picker. The form's save path uses one DST-correct idiom (`naive_local.astimezone(UTC)` at `reminder_form_dialog.py:879`) but it collapses the user's local-time intent before storage. The scheduler then runs RRULE math on a UTC `dtstart`, which silently drifts. Defect lines (`scheduler.py:362` + `:367`) are unchanged byte-for-byte from when R-1b was identified during the testing-rrule-reminder-loop rollout.

## Desired End State

A "Daily 9:00 Europe/Warsaw" recurring reminder fires at exactly 9:00 wall-clock every day, including across spring-forward and fall-back transitions. Existing `reminders.json` files load without migration (missing `tz` defaults to OS-local at load time via the F3 storage-boundary idiom). The AGENTS.md DST claim is correctly scoped to "when `dtstart` carries an IANA name". A failing-then-passing test in `tests/test_scheduler.py` pins the regression.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Fix shape | (c) UTC `start_at` UNCHANGED + scheduler-only optional `tz: str` field with default factory | Smallest blast radius (~5 sites vs ~60 for options a/b); preserves the storage invariant `_coerce_aware_utc` chokepoint; existing tests need no changes. | Plan |
| TZ source | System-local at SAVE time, captured via `tzlocal.get_localzone_name()` in the form's `accept()` | No UI work needed; matches calendar conventions (reminder created in Warsaw stays Warsaw-anchored even if user travels); deferrable per-reminder picker to a future change. | Plan |
| Runtime library | Stdlib `zoneinfo.ZoneInfo` + `tzdata` PyPI dep (+ `tzlocal>=5.0` for OS→IANA) | Modern stdlib API; explicit `ZoneInfoNotFoundError` avoids the `dateutil.tz.gettz` silent-`None` gotcha that motivated the defensive `_coerce_tz` shape. | Plan |
| Backward compat for existing files | Default missing `tz` to OS-local at load time (lessons.md F3 pattern); lazy persistence on next user edit | Matches existing `_coerce_lead_minutes` / `_coerce_aware_utc` precedent; no surprising disk writes on app boot; mathematically correct for existing data since users created reminders in their current OS tz. | Plan |
| Handling of invalid hand-edited `tz` strings (typo, empty, path-traversal) | Drop the row via `InvalidTimezoneError(ValueError)`; preserve well-formed siblings; lazy-migration (missing field) still substitutes OS-local | Aligns with lessons.md storage-boundary rule (b) row-containment; user sees missing reminder and grep'd WARNING with row index; avoids silently swapping user-typed Warsaw for OS-local Tokyo and firing at wrong wall-clock. | Plan |
| Test approach | TDD via `/10x-tdd` skill: failing test under `xfail(strict=True)` → implement fix → remove xfail in the same commit | The bug has a precise reproduction; test infrastructure (clock injection, scheduler unit tests) is mature; `tests/test_recurring_reminder_integration.py:33-41` already breadcrumbs a deferred failing test for this change. | Plan |
| Archived impl-review handling | Append 1-line correction note at bottom of archived `2026-05-28-reminders-recurrence-editor/reviews/impl-review.md` | Preserves archive integrity; future agents grepping "DST" find both the over-broad original claim AND the correction. | Plan |
| Defect confirmation | R-1b reproducible at HEAD on commit `cd24605a`; blast radius = 5 prod + 55 test + 7 dict + 0 fixtures; zero whole-instance Reminder equality assertions | Migration is mechanical (no implicit "expected tz" per assertion to re-decide); makes option (c) cleanly viable. | Research |

## Scope

**In scope:**
- Add `tz: str` field to `Reminder` dataclass with OS-local default factory
- Add `_coerce_tz` helper in `storage/reminders.py` (always-returns-valid-IANA contract)
- Wire `from_dict` / `to_dict` round-trip
- Modify `next_firing_after` to localize `dtstart` + `now` to `reminder.tz` before RRULE math
- Capture `tzlocal.get_localzone_name()` in form's `accept()` and pass to all 3 Reminder constructions
- Add `tzdata` + `tzlocal` runtime dependencies
- Failing-then-passing R-1b regression test + non-DST counter-test
- Correct AGENTS.md DST claim
- Annotate archived impl-review.md with 1-line correction
- Update test-plan.md §7 parked-entry as resolved
- Remove `TODO(R-1b)` breadcrumb from integration tests

**Out of scope:**
- UI timezone picker (digital-nomad per-reminder tz selection) — separable UX slice
- One-shot migration of existing `reminders.json` files — lazy persistence is sufficient
- Storage-invariant change on `start_at` (options a/b) — option (c) wins on blast radius
- Settings key for default tz — form captures directly via `tzlocal`
- `dateutil.tz` adoption — `zoneinfo` chosen for explicit error class
- Lessons.md update — defer to `/10x-impl-review` to decide

## Architecture / Approach

Four phases, each commit-shaped, with phase ordering driven by dependencies:

```
Phase 1 (data model)        Phase 2 (TDD fix)            Phase 3 (UI)             Phase 4 (docs)
─────────────────────       ────────────────────         ─────────────────        ──────────────
pyproject.toml +deps        RED test (xfail strict)      form accept() capture    AGENTS.md fix
Reminder.tz field           GREEN scheduler.py change    test_form integration    archive annotate
_coerce_tz helper           remove xfail mark            (lazy persistence        test-plan §7
from_dict wires it          counter-test (non-DST)        is automatic via         change.md status
storage tests               remove TODO(R-1b)             Phase 1 to_dict)
```

The scheduler's public return contract stays tz-aware UTC — `next_firing_after` localizes internally to `reminder.tz` for RRULE math, then converts back to UTC before returning so `_compute_next`'s tz-aware-UTC comparisons against `self._clock()` work unchanged.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Storage foundation | `tz: str` field on `Reminder` + `_coerce_tz` + runtime deps; field unused by scheduler | Default factory or coercion edge case loads existing files with wrong tz silently |
| 2. Scheduler fix (TDD) | The actual bugfix in `next_firing_after`; R-1b regression test + non-DST counter-test | Forgetting to convert back to UTC before return; xfail-strict ordering across commits |
| 3. Form integration | New reminders persist explicit OS-local tz at save | `tzlocal` returning `None` on edge-case OS configurations; the edit-flow refresh-on-save semantics are debatable |
| 4. Docs + archive cleanup | AGENTS.md DST claim corrected; archive annotated; §7 unparked; breadcrumb removed | Pure docs — no risk, only attention to detail |

**Prerequisites:** Research artifact `research.md` complete (done); `change.md` initialized (done, status `preparing`); no other concurrent changes touching `scheduler.py` / `storage/reminders.py` / `reminder_form_dialog.py`.

**Estimated effort:** ~1–2 sessions across 4 phases. Phases 1+2 are the bulk (data model + TDD'd fix). Phases 3+4 are mechanical wiring + docs.

## Open Risks & Assumptions

- **Assumption: `tzlocal.get_localzone_name()` returns a stable IANA name on Windows 11** without bundling additional registry-translation logic. Verified by `tzlocal` docs but not tested on CI in this repo; Phase 1 validates via `uv run pip-audit` + `uv run pytest tests/test_reminders.py` on `windows-latest`.
- **Risk: a user on a non-standard OS tz** (e.g. machine misconfigured to `"Etc/GMT+1"` instead of `"Europe/Warsaw"`) gets reminders fired in the wrong wall-clock zone. Mitigated by the F3 default being a faithful read of OS state — wrong only if the OS is already wrong.
- **Assumption: `_coerce_tz` is appropriate as a swallow-all-errors load helper.** Departs slightly from the row-containment pattern (which raises and lets `_read` drop the row). Justification: tz is metadata, not identity — a row with a typo'd tz should still load with the user's reminder content intact; only the tz semantics are silently substituted.
- **Decision (was Open Risk, resolved during plan-review F2): Edit-flow preserves the loaded reminder's tz on pure name / lead_minutes edits.** Refreshes to current OS-local only when the user changes a firing-relevant field (start_at, rrule_str, end_at). Reuses the existing `firing_unchanged_in_edit` predicate at `reminder_form_dialog.py:912-917`. Eliminates the travel-and-rename cross-DST regression (a user renaming their Warsaw reminder while in Tokyo no longer silently flips its tz). Escape valve for users who DO want to refresh tz: change the datetime field then change it back, save.

## Success Criteria (Summary)

- A "Daily 9:00 Europe/Warsaw" reminder fires at 9:00 wall-clock every day across the 2026-03-28→29 spring-forward boundary (verified by the R-1b regression test).
- All existing tests still pass — the data model change is additive with sensible defaults; no test sites need updating.
- `AGENTS.md` no longer claims RRULE handles DST correctly on a UTC `dtstart`; the IANA-name caveat is explicit.
