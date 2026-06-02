<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Bugfix Reminder DST Drift

- **Plan**: `context/changes/bugfix-reminder-dst-drift/plan.md`
- **Mode**: Deep
- **Date**: 2026-06-02
- **Verdict**: REVISE → SOUND (after triage)
- **Findings**: 1 critical, 3 warnings, 4 observations

## Verdicts

| Dimension | Verdict (before triage) | Verdict (after triage) |
|-----------|-------------------------|------------------------|
| End-State Alignment | PASS | PASS |
| Lean Execution | PASS | PASS |
| Architectural Fitness | WARNING | PASS |
| Blind Spots | WARNING | PASS |
| Plan Completeness | WARNING | PASS |

## Grounding

- 11/11 paths verified (Test-Path on `break_reminder/storage/reminders.py`, `scheduler.py`, `ui/reminder_form_dialog.py`, `tests/test_reminders.py`, `tests/test_scheduler.py`, `tests/test_recurring_reminder_integration.py`, `tests/test_reminder_form_dialog.py`, `AGENTS.md`, `pyproject.toml`, `context/foundation/test-plan.md`, `context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md`)
- 4/4 symbols verified (`_coerce_lead_minutes`, `_coerce_aware_utc`, `next_firing_after`, `_ensure_aware`)
- brief↔plan consistency: ✓
- Empirical verification: pre-fix bug reproduced (`08:00 UTC` = `10:00 CEST Warsaw`); post-fix correct (`07:00 UTC` = `9:00 CEST Warsaw`); `ZoneInfo("")` raises `ValueError` (not `ZoneInfoNotFoundError`); `tzlocal.get_localzone_name() == "Europe/Warsaw"` on this Windows-11 machine.
- Progress↔Phase mechanical contract: PASS (originally 32 items; after F4 added 1 automated item to Phase 1, now 33 items mapped 1:1 with SC bullets)

## Findings

### F1 — _coerce_tz exception handler too narrow; ZoneInfo("") raises ValueError

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 § 2 — `_coerce_tz` helper
- **Detail**: Plan spec said "raises `ZoneInfoNotFoundError`" → log + return OS-local. Empirically verified: `ZoneInfo("")` raises `ValueError` ("ZoneInfo keys must be normalized relative paths"), and `ZoneInfo("../etc/passwd")` also raises `ValueError`. Implementer following the literal spec would only `except ZoneInfoNotFoundError:`, propagating `ValueError` on empty-string input and violating the "must NEVER raise" contract. `_read`'s row-containment then drops the whole row instead of healing the field, contradicting Phase 1's own test #8.
- **Fix**: Broaden the exception tuple in spec to `(ZoneInfoNotFoundError, ValueError)`; add `_coerce_tz("")` and `_coerce_tz("../etc/passwd")` test cases pinning both exception classes.
- **Decision**: FIXED — applied to Phase 1 § 2 and Phase 1 § 6 tests.

### F2 — Refresh-on-edit silently rewrites tz when user edits while traveling

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots
- **Location**: Phase 3 § 1, Phase 3 § 2 (second test)
- **Detail**: Plan unconditionally passed `tz=tz_name` (current OS-local) to all three Reminder constructions including the Edit branch. A user creating "Daily 9:00 Warsaw" in Warsaw and renaming it during a Tokyo trip would have their tz silently flipped to `Asia/Tokyo`. Re-introduces the cross-DST drift the bugfix exists to prevent. The form already has `firing_unchanged_in_edit` (lines 912-917) computing exactly the right predicate.
- **Fix A ⭐ Recommended**: Preserve tz on edit; refresh only on Add or when firing-relevant fields changed.
  - Strength: Eliminates travel-and-rename regression; reuses existing `firing_unchanged_in_edit` predicate.
  - Tradeoff: One conditional in `accept()` differentiating Add vs Edit paths.
  - Confidence: HIGH — predicate already exists in codebase.
  - Blind spot: Pre-fix reminders with `tz=""` should refresh — covered post-F3 since invalid tz strings now drop the row at load.
- **Fix B**: Keep refresh-on-edit; document the cross-DST cost.
- **Decision**: FIXED via Fix A — applied to Phase 3 § 1 Contract, Phase 3 § 2 tests (three tests replacing two), Phase 3 success criteria, Progress 3.6, brief Open Risks.

### F3 — _coerce_tz silently substitutes OS-local on hand-edit typos

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 § 2 — `_coerce_tz` helper
- **Detail**: Plan's `_coerce_tz` returned OS-local on every failure mode. A Tokyo user with hand-edited `"tz": "Europe/Warsaaw"` (typo) would silently get Asia/Tokyo — same harm class as F2. Deviates from R-5 row-containment philosophy (drop bad rows) and from `_coerce_lead_minutes` semantics (clamp = closest valid value; tz-substitute = different zone).
- **Fix A ⭐ Recommended**: Drop the row on invalid tz STRING (raise `InvalidTimezoneError(ValueError)`, `_read`'s existing tuple catches it). Keep None-branch (missing field) as OS-local substitution (legitimate lazy migration).
  - Strength: Aligns with lessons.md storage-boundary rule (b); user notices missing reminder, greps log, fixes typo.
  - Tradeoff: User loses one reminder until they fix the typo.
  - Confidence: HIGH — exact mirror of the documented row-level pattern.
  - Blind spot: Distinguishes `None` (older file) from `str` (user typed this).
- **Fix B**: Silent substitution + ERROR log + startup dialog.
- **Decision**: FIXED via Fix A — applied to Phase 1 § 2 (new contract + InvalidTimezoneError class), Phase 1 § 6 tests, Phase 1 manual SC + Progress, Migration Notes (new "Hand-edited files with INVALID tz" paragraph), Critical Implementation Details, Testing Strategy, brief Key Decisions (new row added).

### F4 — tzdata PyInstaller bundling not specified; release build may break

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 § 1, pyproject.toml comments (lines 91-92)
- **Detail**: Plan added `tzdata>=2024.1` runtime dep but did not update the PyInstaller invocation. `tzdata` is data-only; PyInstaller's auto-discovery may not pick up its `.zoneinfo` files. Empirically reproduced: `ZoneInfo("Europe/Warsaw")` fails with `ZoneInfoNotFoundError` when tzdata isn't installed. A bundled .exe missing tzdata data files would fail at runtime — every reminder load would hit the invalid-tz path and drop the row post-F3.
- **Fix**: Update the PyInstaller comment in pyproject.toml to add `--collect-data tzdata`; add a Phase 1 success criterion for a local PyInstaller smoke build verifying tzdata data files are bundled.
- **Decision**: FIXED — applied to Phase 1 § 1 Contract (PyInstaller command update instruction + `.github/workflows/release.yml` cross-grep note), Phase 1 automated SC (new bullet 1.8), Progress 1.8.

### F5 — Phase 3 field-ordering guidance is wrong

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3 § 1
- **Detail**: Plan said "place `tz=tz_name` alphabetically (after `start_at`, before `lead_minutes`)" but dataclass order is `name, start_at, rrule_str, end_at, lead_minutes, tz, id` — `tz` comes AFTER `lead_minutes`.
- **Fix**: "Match the dataclass field order (after `lead_minutes`, before `id`)".
- **Decision**: FIXED — applied automatically as part of F2's Phase 3 § 1 Contract rewrite.

### F6 — Phase 2 SC 2.5 grep predicate is non-mechanical

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 Success Criteria 2.5, Progress 2.5
- **Detail**: "Returns nothing related to R-1b" requires human judgment. Anchor on the test identifier instead.
- **Fix**: Replace with `grep -n "xfail" tests/test_scheduler.py | grep -i "dst"` returns nothing — the R-1b test name contains "dst".
- **Decision**: FIXED — applied to Phase 2 SC and Progress 2.5.

### F7 — Plan slightly overstates the archived impl-review's DST claim

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 4 § 2 — Archive annotation
- **Detail**: Plan framing called the archived "DST correctness" claim "over-broad", but the literal text at line 57 is explicitly scoped to `_local_date_to_utc_end_of_day`. Annotation is still useful (line 74's "DST round-trip" is genuinely ambiguous, and skimmers may over-read the bullet header) but the rationale was inaccurate.
- **Fix**: Rephrase Phase 4 § 2 Intent to acknowledge the scoping and pin the annotation's value to line 74's ambiguity and skim-risk.
- **Decision**: FIXED — applied to Phase 4 § 2 Intent.

### F8 — _resolve_zone in scheduler duplicates _coerce_tz's contract

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Lean Execution
- **Location**: Phase 2 § 2 — `_resolve_zone` helper
- **Detail**: `_resolve_zone` adds parallel validation duplicating `_coerce_tz`'s contract. Invariant enforcement now lives in two places with different policies (post-F3: storage strict, scheduler lenient). Alternative: lift to `Reminder.__post_init__`. Justified concern but the alternative has costs (new pattern in codebase; runs on 60 test constructions).
- **Fix**: Cross-reference the trade-off in plan's Critical Implementation Details so a future reader knows it was considered. Defer alternative to `/10x-impl-review` if `_resolve_zone` proves awkward.
- **Decision**: FIXED — added the rejected `__post_init__` alternative to the "Two-layer validation" bullet in Critical Implementation Details.
