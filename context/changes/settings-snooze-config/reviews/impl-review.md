<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Settings — Snooze Configuration

- **Plan**: `context/changes/settings-snooze-config/plan.md`
- **Scope**: All phases (Phase 1 + Phase 2)
- **Date**: 2026-05-26
- **Verdict**: APPROVED
- **Findings**: 0 critical, 0 warnings, 3 observations
- **Slice commits**: `fc0f6b3` (p1 + scope addendum), `9aa8273` (p2), `5148ae7` (epilogue)

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Automated success criteria — re-run from current tip

| Gate | Result |
|---|---|
| `uv run pytest` | 235 passed in ~2s |
| `uv run pyright` (8 files) | 0 errors, 0 warnings, 0 informations |
| `uv run ruff check` (8 files) | All checks passed! |
| `uv run ruff format --check` (8 files) | 8 files already formatted |

## Plan-adherence summary

All 13 numbered plan items MATCH (Phase 1 #1–#10 + Phase 2 #1–#3). Every "What We're NOT Doing" guardrail respected. Scope addendum (snooze-aware tray tooltip, requested mid-Phase-1) is honestly disclosed in `plan.md`, `plan-brief.md`, and `change.md`. The only delta between the plan's enumerated test counts and the actual test counts is **additive defensive coverage**:
- `TestSnoozeValidation` has 10 tests instead of 9 (extra `test_snooze_duration_setter_rejects_negative` mirrors the break-interval precedent).
- `TestLoad` has 7 new tests instead of 5 (each spinbox's bounds split into separate `_minimum_is_*` and `_maximum_is_*` tests).

## Findings

### F1 — TestSnoozeValidation skips two tripwires that exist for the break-interval precedent

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_settings.py:268` (TestSnoozeValidation class)
- **Detail**: The break-interval precedent (`TestValidation`, ~line 115) tests both the unparseable-string getter fallback AND the low-side getter clamp on corrupt INI. The new `TestSnoozeValidation` only tests the high-side clamp (`test_*_getter_clamps_corrupt_high_value`) and the unparseable-string case isn't exercised on either snooze field. Both are covered transitively by the shared `_get_int` helper, but a snooze-side tripwire would catch future drift if that helper changes.
- **Fix**: Add three tests under `TestSnoozeValidation`:
  - `test_snooze_duration_getter_falls_back_when_unparseable`
  - `test_max_snoozes_getter_falls_back_when_unparseable`
  - `test_max_snoozes_getter_clamps_corrupt_low_value`
- **Decision**: FIXED — added all three tests under `TestSnoozeValidation` (`tests/test_settings.py:341-372`). Class now has 13 tests (up from 10). All pass. Note: during the fix it became clear that `test_snooze_duration_getter_clamps_corrupt_low_value` already existed (line 306) — the original review prompt over-counted; only `max_snoozes_*_low_value` was missing on the clamp side, and both unparseable-string tripwires were missing.

### F2 — Atomic-save tripwire doesn't cover the new snooze writes

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Test Quality
- **Location**: `tests/test_settings_dialog.py::TestNotificationsTabValidation::test_voice_on_blank_phrase_blocks_save`
- **Detail**: The existing tripwire pins atomic-save semantics for `break_interval_min` (no write happens when the voice-phrase validation gate blocks save). The new `snooze_duration_min` / `max_snoozes` writes are added at `settings_dialog.py:387-392` above `super().accept()`, so they land in the same atomic-save contract — but the existing tripwire doesn't assert it. If a future refactor accidentally moves either write below the validation gate, current tests won't catch the leak.
- **Fix**: Extend the existing tripwire (or add a sibling) to capture pre-edit values of `snooze_duration_min` and `max_snoozes` and assert they're unchanged after the blocked-save attempt.
- **Decision**: FIXED — extended `test_voice_on_blank_phrase_blocks_save` (`tests/test_settings_dialog.py:671-715`) to pre-set + edit all three Scheduling-tab fields (break-interval, snooze-duration, max-snoozes) and assert each one is unchanged on disk after the blocked save. The atomic-save tripwire now covers every persisted Scheduling-tab field, not just break-interval.

### F3 — "Re-tick note" in plan.md is stale historical context

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `context/changes/settings-snooze-config/plan.md:364`
- **Detail**: The note reads "Re-tick note (2026-05-26): 1.1 and 1.2 stayed green from the original Phase 1 commit; 1.3–1.8 were re-evaluated and re-ticked after the scope addendum landed." This was added when we anticipated a separate p1 commit landing before the addendum, but in practice all eight 1.x progress rows landed in a single commit (`fc0f6b3`). Every row now references the same SHA, so the note misrepresents history. Harmless but misleading for any future reader using the plan as record-of-truth.
- **Fix**: Either (a) delete the note since the SHA-uniformity on rows 1.1–1.8 already tells the true story, or (b) rewrite to: "Phase 1 originally planned without the snooze-tooltip surface; the user requested it mid-flight, and the entire Phase 1 work landed as a single commit `fc0f6b3` covering both."
- **Decision**: FIXED via option (a) — deleted the stale note. The SHA uniformity on progress rows 1.1–1.8 (all `fc0f6b3`) already conveys that the entire Phase 1 work landed atomically.
