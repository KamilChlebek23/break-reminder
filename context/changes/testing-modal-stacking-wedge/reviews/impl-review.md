<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: testing-modal-stacking-wedge

- **Plan**: `context/changes/testing-modal-stacking-wedge/plan.md`
- **Scope**: Full plan (Phases 1-3 of 3)
- **Date**: 2026-06-02
- **Verdict**: APPROVED
- **Findings**: 0 critical, 1 warning, 2 observations
- **Commits reviewed**: `b140bf7` (p1 RED test) → `863dfd9` (p2 Fix A) → `78643c5` (p3 docs sync)

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Success-criteria re-verification (2026-06-02)

- `uv run pytest tests/test_modal_stacking_integration.py tests/test_break_dialog.py` → **22 passed** (2 modal-stacking + 20 FR-009 hardening)
- `uv run pytest` (full suite) → **all green**
- `uv run ruff check` → All checks passed
- `uv run pyright` → 0 errors, 0 warnings, 0 informations

## Findings

### F1 — Markdown typo: `BreakDialog.__init__` rendered as `__init_`

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `context/foundation/test-plan.md:157`
- **Detail**: In §6 cookbook row "Modal-stacking / wedge survival", the fix-location reference is `` `BreakDialog.__init_`_ `` — closing backtick is one position too early. Rendered markdown shows "BreakDialog.__init_" with an orphan underscore outside the code span instead of the canonical Python dunder "BreakDialog.__init__". Plan contract (`plan.md:21,:129,:212`) consistently uses `__init__` with two trailing underscores inside the backticks; the other 4 references in `plan.md` are correct. Transcription drift introduced during the Phase 3 StrReplace into `test-plan.md`.
- **Fix**: change `` `BreakDialog.__init_`_ `` to `` `BreakDialog.__init__` `` (move the closing backtick one position right).
- **Decision**: FIXED

### F2 — `FakeVoice` "mirror" docstring overstates the relationship

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_modal_stacking_integration.py:72-79`
- **Detail**: New `FakeVoice` claims to be a "mirror of `test_break_dialog.FakeVoice`", but the two stubs diverge in shape: the new one lacks the `stop_calls` counter and adds a `speak()` method. The drift is intentional (different consumers: `SettingsDialog` accepts a full `VoiceNotifier` whose Test-voice button calls `speak()`; `BreakDialog` only needs `stop()` via the `_VoiceController` Protocol), but "mirror" is misleading. A future refactor that extracts to `tests/_fakes.py` would need to reconcile the two shapes.
- **Fix**: reword the docstring to "sibling stub for SettingsDialog's VoiceNotifier param" (or similar), or leave as-is and accept the imprecise wording until/unless a third consumer appears.
- **Decision**: FIXED

### F3 — Pre-archive doc path placeholders need `/10x-archive` sweep

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence (deliberate per plan contract)
- **Location**: `AGENTS.md:72`; `context/foundation/test-plan.md:45,:157`
- **Detail**: Three Phase 3 doc edits reference paths that will become stale when `/10x-archive` runs:
  - `AGENTS.md:72` contains the literal placeholder `context/archive/<archive-date>-testing-modal-stacking-wedge/`
  - `test-plan.md:45` (§2 R-2 cell) references `context/changes/testing-modal-stacking-wedge/research.md`
  - `test-plan.md:157` (§6 row) references the same `changes/...` research path

  All three were written intentionally per the plan contract — the placeholder is deliberate; the `changes/` paths anticipated archive would resolve them. The `/10x-archive` skill as written does NOT sweep these references; they'll need a post-archive manual fix (or a skill extension) to point at `context/archive/2026-06-02-testing-modal-stacking-wedge/`.
- **Fix**: after `/10x-archive` runs, find-replace `context/changes/testing-modal-stacking-wedge` → `context/archive/2026-06-02-testing-modal-stacking-wedge` in `AGENTS.md` + `test-plan.md` (3 hits total). Could also be baked into a future `/10x-archive` enhancement.
- **Triage note**: Triage caught a 4th hit Agent 2 missed: `tests/test_modal_stacking_integration.py:16` (module docstring referencing research.md §1, §3, §4.b). Pre-baked alongside the other 3 because `change.md.created` (which determines the archive folder name) is stable at `2026-06-02`.
- **Decision**: FIXED (pre-baked archive path in 3 files: `AGENTS.md`, `context/foundation/test-plan.md`, `tests/test_modal_stacking_integration.py`)
