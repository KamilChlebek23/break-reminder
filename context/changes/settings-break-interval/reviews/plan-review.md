<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Settings Window — Break Interval Editor (S-01)

- **Plan**: `context/changes/settings-break-interval/plan.md`
- **Mode**: Deep (retrospective)
- **Date**: 2026-05-27
- **Verdict**: REVISE
- **Findings**: 0 critical · 2 warnings · 2 observations
- **Note**: This is a **retrospective** review. The slice was already
  `status: impl_reviewed` (shipped 2026-05-25, commits `eaa1b69` Phase 1
  + `e3c16d2` Phase 2) when the review ran. All 4 findings WOULD have
  been catchable pre-implementation; F1 + F2 + F3 were in fact surfaced
  later — F1 by impl-review F5 (bounds-constants promotion), F2 by the
  Phase 2 manual-smoke Addenda (silent-clamping UX), F3 by impl-review F6
  (`qtbot.addWidget` convention). F4 is a plan-prose ambiguity that
  didn't bite implementation. All 4 were FIXED as retroactive plan
  amendments. `change.md` status is **NOT** flipped back to
  `plan_reviewed`; the slice remains `impl_reviewed`.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING (F1 — bounds duplicated across persistence + widget layers) |
| Blind Spots | WARNING (F2 — silent clamping UX never enumerated; only persistence validation considered) |
| Plan Completeness | WARNING (F3 + F4 — qtbot convention not specified; _settings_path removal conditional contradicts itself) |

## Grounding

9/9 paths verified · 6/6 symbols confirmed (`_on_open_settings`, `break_interval_min`, `BREAK_INTERVAL_MIN_MINUTES`, `BREAK_INTERVAL_MAX_MINUTES`, `DEFAULT_BREAK_INTERVAL_MIN`, `_settings_path`) · brief↔plan consistent · `## Progress` block well-formed (1 block, 2 phases, 6 P1 + 13 P2 boxes mapped 1:1 to Success Criteria, all `[x]` with SHA backrefs).

## Findings

### F1 — Bounds [1, 240] duplicated across persistence and widget layers

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architectural Fitness
- **Location**: Phase 1 #2 (L96) — "setMinimum(1) and setMaximum(240)"; Current State Analysis (L12) — `Settings.break_interval_min` clamps to [1, 240] in `storage/settings.py:108-117`
- **Detail**: The plan declares the FR-006 range as literals `1` and `240` inside the SettingsDialog spinbox setup AND relies on the same numeric bounds already encoded in `Settings.break_interval_min` getter/setter (`storage/settings.py:111,116`), plus 5 prose mentions of `[1, 240]` across the document. A future loosening (e.g., to 480 min) requires coordinated edits across `storage/` and `ui/` with the risk of forgetting one — and the `(TestLoad) spinbox.minimum()/maximum() == 1/240` tripwire test becomes a regression magnet when persistence and UI diverge. Confirmed real: impl-review F5 raised exactly this and shipped the fix — `BREAK_INTERVAL_MIN_MINUTES` / `BREAK_INTERVAL_MAX_MINUTES` promoted to public constants in `storage.settings`, imported by `settings_dialog.py` for both `setMinimum/setMaximum` and the bounds-check string.
- **Fix**: Add a Phase 1 #2 contract line: "Spinbox bounds imported from `BREAK_INTERVAL_MIN_MINUTES` / `BREAK_INTERVAL_MAX_MINUTES` constants in `storage.settings` (added by this slice to centralize the FR-006 single source of truth — no literal `1`/`240` in the dialog module)."
- **Decision**: FIXED — applied as retroactive in-place amendment to plan.md L96; both spinbox bounds and storage-side constant promotion now documented as part of Phase 1 #2 scope.

### F2 — Silent clamping UX never enumerated; only persistence validation considered

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Plan L28 — "Validation is therefore pre-empted, no try/except needed in the save path"; Plan L67 — "Critical Implementation Details (Omitted — … the validation question dissolved at the widget level)"
- **Detail**: The plan dissolves validation at the **persistence** layer correctly — `QSpinBox(1, 240)` makes the setter's `ValueError` branch unreachable. But it doesn't enumerate what the user *sees* when they type 0 or 999: Qt's QSpinBox silently substitutes (clamps below-min, truncates above-max) with no visible feedback. "Validation is pre-empted" conflates two different questions — "can persistence corruption happen?" (no) and "does the user know their input was rejected?" (no, and the plan didn't ask). This is precisely the gap the Phase 2 manual smoke surfaced (Addenda L274) and which triggered the un-planned validation-feedback feature, then needed empirical correction via impl-review F1+F2+F4 because the first attempt used `lineEdit.text()` against `str(value())` and the `setSuffix(" min")` made the strings never match.
- **Fix A ⭐ Recommended**: Add a one-line decision to Critical Implementation Details: "Silent clamping is accepted UX for FR-006; if feedback is later requested, the Qt-correct path is `lineEdit.textEdited` capture (pre-fixup) + `editingFinished` check — `editingFinished` alone sees only the post-fixup `lineEdit.text()` value, and the `setSuffix(" min")` cosmetic makes `lineEdit.text()` return `"60 min"` rather than `"60"` so string comparisons against `str(value())` will never match."
  - Strength: Records the decision either way; if user later asks for feedback during smoke, the next implementer has the Qt gotcha pre-mapped instead of discovering it the hard way.
  - Tradeoff: Adds 2-3 lines to a plan that's currently tight.
  - Confidence: HIGH — the exact Qt gotcha tripped impl-review F1.
  - Blind spot: None significant.
- **Fix B**: Ship the validation-feedback feature in-plan rather than as a Phase 2 smoke addendum.
  - Strength: No mid-implementation scope drift; testing covered up-front.
  - Tradeoff: Inflates the "low-complexity" scaffold slice with UX work the user didn't request before smoke.
  - Confidence: MEDIUM — uncertain whether the silent clamp was actually going to bother the user; over-engineering risk.
  - Blind spot: Doesn't help future slices that face the same Qt gotcha.
- **Decision**: FIXED via Fix A — `## Critical Implementation Details` rewritten to record the silent-clamping decision and pre-map the Qt gotcha (lineEdit/textEdited/cleanText/setSuffix interactions) for future implementers.

### F3 — qtbot.addWidget cleanup pattern not specified for dialog tests

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 #3 (L117) — "Reuse the `qapp` conftest fixture"
- **Detail**: Plan only mentions `qapp`. Doesn't mention `qtbot` (pytest-qt's other fixture) or the existing convention in `tests/test_break_dialog.py` of calling `qtbot.addWidget(dialog)` after construction so pytest-qt cleans up the widget at test-end. Impl-review F6 caught one test (`test_reject_does_not_persist`) that landed without this call — passes today but breaks the file-local convention.
- **Fix**: Replace the L117 sentence with "Reuse the `qapp` and `qtbot` conftest fixtures; call `qtbot.addWidget(dialog)` after every manual `SettingsDialog` construction for pytest-qt cleanup — existing convention from `tests/test_break_dialog.py`."
- **Decision**: FIXED — applied as retroactive in-place amendment to plan.md L117.

### F4 — _settings_path removal predicated on a check the planner didn't do

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 #1 (L165) — "Remove the unused private helper `_settings_path()` at lines 374-377 **if no other call site references it** (it is currently only used by the placeholder)"
- **Detail**: The "if no other call site references it" + "(it is currently only used by the placeholder)" combo is self-contradictory — either the planner verified there's exactly one caller (so the conditional is dead) or didn't (so the conditional is a real to-do). Implementer has to re-verify. Adds ambiguity for zero cost.
- **Fix**: Drop the conditional. Make it "Remove the now-unused `_settings_path()` helper at lines 374-377 (verified single call site is the `QMessageBox` placeholder being replaced)."
- **Decision**: FIXED — applied as retroactive in-place amendment to plan.md L165.

## Lessons-learned for future plans

The recurring lesson across F1 + F2 (both WARNING) is **enumerate the UX side of every validation decision separately from the persistence side**. The plan correctly dissolved persistence-layer validation but treated UX feedback as out-of-scope by silence, leading to a mid-implementation pivot during Phase 2 smoke when the user reported the silent-clamp UX. Future plans that touch user-input widgets should:

1. State explicitly what the user sees on invalid input (silent substitution, error tooltip, status-bar message, modal popup, or nothing) — even when the persistence layer is bulletproof.
2. Promote shared-domain constants (range bounds, time intervals, retry counts) to a single source of truth in the persistence module on first use across two layers — don't wait for impl-review to retrofit it.
3. List the file-local test-pattern conventions (here: `qtbot.addWidget`) when prescribing test scaffolding — `qapp` alone is necessary but not sufficient.

These three rules are candidates for `context/foundation/lessons.md` if the pattern recurs in a future slice (S-06+ reminders work touches a date-time picker, which has similar UX-vs-persistence validation surfaces).
