<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Testing modal-stacking wedge (Phase 1 focus)

- **Plan**: `context/changes/testing-modal-stacking-wedge/plan.md`
- **Mode**: Deep
- **Date**: 2026-06-02
- **Verdict**: REVISE (pre-triage) → SOUND (post-triage; all findings applied)
- **Findings**: 0 critical, 2 warnings, 1 observation
- **Scope qualifier**: User invoked `/10x-plan-review testing-modal-stacking-wedge phase 1` — findings weighted toward Phase 1 (RED test), the phase about to be implemented next.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING (2 findings, both Phase 1) → resolved |
| Plan Completeness | WARNING (1 finding, brief inconsistency) → resolved |

## Grounding

Grounding: 5/5 paths verified (`tests/test_modal_stacking_integration.py` new — expected; `break_reminder/notifications/break_dialog.py`, `context/deployment/deploy-plan.md`, `context/foundation/test-plan.md`, `AGENTS.md` all exist), 4/4 symbols verified (`BreakDialog.__init__`, `SettingsDialog.__init__`, `ReminderFormDialog.__init__`, `Clock` from `tests/conftest.py`). `Settings(ini_path=Path|str|None)` and `VoiceNotifier()` no-arg constructors confirmed. **13 instances of `qtbot.waitExposed(dialog)`** found in `tests/test_break_dialog.py` — the established convention the plan should mirror (basis for F2). Zero current uses of `activeModalWidget` anywhere in tests — pioneering API use (basis for F1). `docs/reference/contract-surfaces.md` does not exist — contract-surfaces check skipped per skill convention.

Brief↔plan: WARNING — Phase 2 production-change size inconsistency (basis for F3).

## Findings

### F1 — Pre-action assertion on activeModalWidget is empirically unverified for setWindowModality + .show()

- **Severity**: WARNING
- **Impact**: MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 → Changes Required §1 (fixture contract)
- **Detail**: Plan added `assert QApplication.activeModalWidget() is blocking_modal` as a fixture pre-action guard. Agent C's research smoke (`research.md` §3) used the same fixture pattern but never asserted on `activeModalWidget()` — only proved that `QTest.mouseClick` bypassed modality. Whether `QApplication.activeModalWidget()` populates for a `setWindowModality + .show()` (non-`.exec()`) modal is an unverified Qt internal. Risk: if it returns `None`, the pre-action assertion fails at fixture setup, masking the structural-assertion failure on `breakDialog` — RED test reports "fixture broken" instead of "bug detected", and a hasty implementer "fixes" it by removing the assertion (also removing the real RED check).
- **Fix A ⭐ Recommended**: Drop the activeModalWidget pre-action check; keep only the windowModality pre-action check.
  - Strength: `windowModality()` getter is a stable PySide6 attribute read with no event-loop dependency; sufficient to prove the fixture configured modality correctly. Removes the unverified-API risk without losing the vacuous-pass guard.
  - Tradeoff: Slightly weaker fixture guarantee. Acceptable because the post-action assertion `QApplication.activeModalWidget() is breakDialog` IS the load-bearing check for the bug.
  - Confidence: HIGH — `windowModality()` getter is stable PySide6 API.
  - Blind spot: None significant.
- **Fix B**: Empirically verify activeModalWidget behavior in a 5-min spike before Phase 1.
  - Strength: Removes ambiguity by direct evidence; if assertion DOES populate, both pre-action checks stay.
  - Tradeoff: Adds research step before Phase 1.
  - Confidence: MEDIUM — spike could go either way.
- **Decision**: Fixed via Fix A. Plan section "Phase 1 → Changes Required #1 Contract" updated to drop activeModalWidget pre-check and document the rationale (cross-referencing F1). The post-action assertion on breakDialog activeModalWidget is preserved — it's the load-bearing behavioral guarantee Phase 2 must satisfy.

### F2 — qtbot.waitExposed() pattern missing from Phase 1 test contract

- **Severity**: WARNING
- **Impact**: MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 → Changes Required §1 (test code shape)
- **Detail**: 13 explicit instances of `with qtbot.waitExposed(dialog): dialog.show()` in `tests/test_break_dialog.py` — the established pattern across all 20 existing FR-009 tests. Phase 1 contract showed naked `.show()` + immediate assertion. Implementer might write the naive form, get flaky `activeModalWidget` asserts (Qt may not have flushed modal-grab installation), and reach for `time.sleep()` or worse.
- **Fix ⭐ Recommended**: Amend Phase 1 contract snippet to wrap each `.show()` in `with qtbot.waitExposed(dialog):` for BOTH the blocking_modal fixture setup AND the break_dialog construction in the test body.
  - Strength: Mirrors the established pattern across the 20 existing FR-009 tests; documented best practice from pytest-qt; eliminates a class of test flake at the source.
  - Tradeoff: Two additional lines per dialog (blocking_modal + break_dialog show wrappers).
  - Confidence: HIGH — pattern already proven across 13 instances in test_break_dialog.py.
  - Blind spot: None significant.
- **Decision**: Fixed via Fix in plan. Plan section "Phase 1 → Changes Required #1 Contract" amended to wrap `break_dialog.show()` in `with qtbot.waitExposed(break_dialog):` AND adds an explicit sentence requiring the blocking_modal fixture to do the same. Cross-references F2.

### F3 — plan-brief and plan disagree on Phase 2 production change size

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: plan-brief.md "Phases at a Glance / Estimated effort" vs plan.md Phase 2 §1
- **Detail**: plan-brief Estimated effort said "Phase 2 is 2 lines of production change + 1 paragraph of docstring"; plan body says single `setWindowModality` line. Plan is canonical; brief inconsistency could confuse a reader who reads brief first.
- **Fix**: Update plan-brief.md Estimated effort to "1 line of production change + 1 paragraph of docstring".
- **Decision**: Fixed via Fix in plan. plan-brief.md Estimated effort line updated from "2 lines" to "1 line".
