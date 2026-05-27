<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Settings — Snooze Configuration (S-03)

- **Plan**: `context/changes/settings-snooze-config/plan.md`
- **Mode**: Deep (retrospective)
- **Date**: 2026-05-27
- **Verdict**: REVISE (functionally close to SOUND — both findings caught downstream at impl-review with no production impact)
- **Findings**: 0 critical, 1 warning, 1 observation
- **Slice commits**: `fc0f6b3` (Phase 1 + scope addendum), `9aa8273` (Phase 2), `5148ae7` (epilogue)
- **impl-review verdict**: APPROVED, 0 critical / 0 warnings / 3 observations (all FIXED in same session)

> **Retrospective context**: This is a retrospective plan-review run after the slice was already shipped and impl-reviewed (`status: impl_reviewed`). It's a lessons-learned exercise — the findings below mirror what `/10x-impl-review` found post-ship (impl-review F1 → plan-review F2; impl-review F2 → plan-review F1) and represent gaps that a pre-implementation plan-review would have caught at the planning layer instead of the implementation layer. The retroactive plan amendments applied below close the gap in the record-of-truth so the plan, as filed, would now produce the additional test coverage on a fresh implementation pass.

## Verdicts

| Dimension              | Verdict       |
| ---------------------- | ------------- |
| End-State Alignment    | PASS          |
| Lean Execution         | PASS          |
| Architectural Fitness  | PASS          |
| Blind Spots            | WARNING (F1)  |
| Plan Completeness      | WARNING (F2)  |

## Grounding

9/9 paths ✓, 12/12 symbols ✓, brief↔plan ✓. Progress↔Phase: 1 `## Progress` block ✓, every Phase 1 / Phase 2 Success Criteria bullet maps to a Progress checkbox 1:1 ✓ (Progress has 2 extra entries — 2.1 three-rows-order, 2.2 max-snoozes-tooltip — sourced from the richer Phase 2 #1 smoke checklist contract; allowed by the skill's one-way SC→Progress rule).

## What the plan got right

- **End-state coverage is complete**: every capability in Desired End State has a backing phase; the scope addendum (snooze-aware tray tooltip) is fully covered by Phase 1 #8, #9, #10 + its own test classes.
- **Scope addendum disclosure**: mid-flight requirement (user-requested snooze tooltip) is honestly disclosed in `change.md` (L16), `plan-brief.md` (L9), and `plan.md` (L7) — record-of-truth stays trustworthy.
- **Pattern mirroring is concrete**: every numbered change names the precedent it mirrors (`break_interval_min` setter pattern, `TestValidation` shape, `seconds_until_break` property shape). Implementer never has to guess at "what pattern".
- **Attention to subtle UX**: the `math.ceil()` rationale for `seconds_until_snooze_end` ("avoids a 1-second flicker through '0m 00s'", L172) is the kind of detail that usually appears as an impl-review observation after a user reports a flicker.
- **Constants centralization**: Phase 1 #1 captures the SSOT lesson learned from S-01 retrospective (constants for FR-006/010 bounds) and applies it preemptively.
- **Eager-refresh wiring is documented**: the `_apply_break_snoozed` eager `_refresh_tooltip` call (L31) is identified as the reason no extra wiring is needed for the tooltip flip — this kind of "why we don't need to do X" note is gold for the implementer.

## Findings

### F1 — Atomic-save tripwire extension not in plan

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 #7 dialog-layer tests (`plan.md` L145-162)
- **Detail**: Phase 1 #5 adds two new persisted writes (`snooze_duration_min`, `max_snoozes`) above `super().accept()` — inside the atomic-save invariant that S-04 impl-review F2 established (no INI write happens when the voice-phrase validation gate blocks save). The plan correctly places both writes inside the invariant but doesn't extend the existing tripwire test (`tests/test_settings_dialog.py::TestNotificationsTabValidation::test_voice_on_blank_phrase_blocks_save`) to assert they also respect it. A future refactor that accidentally moves either snooze write below the validation gate would silently leak — the existing tripwire pins only `break_interval_min`. Confirmed real by impl-review F2 (added the extension post-ship).
- **Fix**: Add a 4th sub-bullet to Phase 1 #7: "Extend `TestNotificationsTabValidation::test_voice_on_blank_phrase_blocks_save` (atomic-save tripwire from S-04 impl-review F2): pre-set + edit all three Scheduling-tab fields (break-interval, snooze-duration, max-snoozes) and assert each is unchanged on disk after the blocked-save attempt."
- **Decision**: FIXED — added the bullet to `plan.md` Phase 1 #7 retroactively. The plan as filed now names the atomic-save tripwire extension as part of the contract.

### F2 — TestSnoozeValidation contract under-mirrors the break-interval precedent

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 #6 Persistence-layer tests (`plan.md` L122-143) — `TestSnoozeValidation` contract (9 enumerated tests)
- **Detail**: The plan declares 9 tests for `TestSnoozeValidation` and explicitly names `TestValidation` (`tests/test_settings.py:115-160`) as the pattern-mirror. The break-interval precedent covers four failure classes per field — out-of-range setter (both sides), boundary-value setter acceptance, getter clamp on corrupt INI (both sides), and getter fallback on unparseable INI. The plan's snooze-validation list covers three classes for snooze duration and two for max-snoozes (low-clamp legitimately N/A for the latter since 0 is the legal floor). Missing from BOTH fields: getter-fallback-on-unparseable tests. Also missing for max-snoozes: low-clamp test (0 is the floor, but a corrupt `-10` should still clamp to 0). Confirmed real by impl-review F1, which added the three missing tripwires post-implementation (`test_snooze_duration_getter_falls_back_when_unparseable`, `test_max_snoozes_getter_falls_back_when_unparseable`, `test_max_snoozes_getter_clamps_corrupt_low_value`).
- **Fix**: Append three test names to the Phase 1 #6 `TestSnoozeValidation` bullet list mirroring the unparseable-string / low-clamp test shapes from the break-interval precedent.
- **Decision**: FIXED — appended all three test names to `plan.md` Phase 1 #6 retroactively. The plan as filed now enumerates 12 tests for `TestSnoozeValidation`, matching the actual implementation (13 — implementation added a defensive `test_snooze_duration_setter_rejects_negative` not enumerated in either plan or this fix; that surplus is fine).

## Verdict after fixes

REVISE → SOUND (both findings closed retroactively). The plan now fully mirrors the break-interval and S-04 precedents for both validation coverage and the cross-tab atomic-save invariant. Any future re-implementation from this plan would produce the test coverage that impl-review had to add post-ship.

## Lessons captured

- **Atomic-save tripwire extends across slices**: when a slice adds new persisted writes to `SettingsDialog.accept()`, the existing `test_voice_on_blank_phrase_blocks_save` tripwire must be extended to cover them. This is now visible in this plan and should appear in future settings-tab slices (custom-reminder CRUD etc.) — consider lifting to `lessons.md`.
- **Mirror precedent test classes completely**: when a plan names a precedent test class (e.g., `TestValidation`) as the pattern-mirror, enumerate ALL failure classes from the precedent, not just the obvious ones. The four classes are: out-of-range setter (both sides), boundary acceptance, getter clamp on corrupt high/low, getter fallback on unparseable. Easy to miss the unparseable-fallback case because it's covered transitively by `_get_int` — but a per-field tripwire is what catches future drift in that helper.
