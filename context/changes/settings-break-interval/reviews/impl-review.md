<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: settings-break-interval (S-01)

- **Plan**: `context/changes/settings-break-interval/plan.md`
- **Scope**: Both phases (full plan)
- **Date**: 2026-05-25
- **Verdict**: NEEDS ATTENTION (all 6 findings FIXED in same session)
- **Findings**: 1 critical · 3 warnings · 2 observations
- **Triage outcome**: 6 fixed, 0 skipped, 0 deferred. Final automated gate green: 160/160 tests, ruff clean, pyright 0/0.

## Verdicts

| Dimension           | Verdict |
| ------------------- | ------- |
| Plan Adherence      | WARNING |
| Scope Discipline    | WARNING |
| Safety & Quality    | FAIL    |
| Architecture        | PASS    |
| Pattern Consistency | PASS    |
| Success Criteria    | WARNING |

All findings cluster on the un-planned validation-feedback feature added in Phase 2. The feature itself is a sensible response to the user's manual-smoke flag, but it landed without a plan addendum and shipped with a real bug that the manual smoke didn't catch. The fix is small.

## Findings

### F1 — Validation tooltip fires on every commit, not just clamps

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `break_reminder/ui/settings_dialog.py:135-136`
- **Detail**: The slot compares `line_edit.text()` (`"60 min"`) against `str(self._break_interval_spinbox.value())` (`"60"`). Because `setSuffix(" min")` is in effect, lineEdit.text() includes the suffix while str(value) does not. The strings never match — so `typed != actual` is always true, and `QToolTip.showText` fires on every commit including valid edits like "30". Verified empirically (`value()=60`, `lineEdit.text()='60 min'`, `str(value())='60'`).
- **Fix**: Use `cleanText()` instead of `lineEdit.text()` — cleanText strips the prefix/suffix and is exactly the API for this comparison.
  - Strength: One-line fix; documented Qt API; round-trips cleanly with str(value()) for in-range values.
  - Tradeoff: None significant. cleanText is a public Qt API designed for exactly this case.
  - Confidence: HIGH — verified by the empirical probe.
  - Blind spot: None significant.
- **Empirical correction during triage**: A real keystroke probe (QTest) showed `cleanText()` reflects the post-fixup value, not the typed value — so the proposed one-line fix would have introduced false negatives on out-of-range typing. Real Qt behavior: `0` reverts to the previous value, `500` truncates to `50`. The user's typed intent is gone by `editingFinished`. Replaced with: capture raw typed text via `lineEdit.textEdited` (fires before fixup), then check bounds against the typed value at `editingFinished`. This also folded in F4 by dropping the rect arg.
- **Decision**: FIXED (corrected approach — textEdited capture)

### F2 — Tooltip feature added beyond plan scope (no plan addendum)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence + Scope Discipline
- **Location**: `break_reminder/ui/settings_dialog.py:29, 36-44, 116-148`
- **Detail**: The plan explicitly stated "the validation question dissolved at the widget level" (plan.md:67) and "no try/except needed in the save path" (plan.md:28). The implementation reopens that question by adding setToolTip + an editingFinished slot + QToolTip.showText feedback + 3 module-level constants + a QToolTip import. Rationale lives in a code comment at settings_dialog.py:108-112 and in commit e3c16d2's body, but not in the plan, plan-brief, or any roadmap update. The user prompted the addition during manual smoke, so it isn't unauthorized — but the plan-as-record-of-truth is now stale.
- **Fix A ⭐ Recommended**: Keep the feature, backfill plan + brief
  - Strength: Preserves the actual UX improvement and updates the source of truth so archive + future S-02..S-05 planning starts from accurate ground.
  - Tradeoff: Plan body is conventionally read-only mid-implementation, but this is a post-implementation addendum — explicit, dated, owned.
  - Confidence: HIGH — addendum-after-implementation is the cleanest pattern when the plan diverged with user consent.
  - Blind spot: None significant.
- **Fix B**: Remove the feature, restore plan parity
  - Strength: Strict scope discipline; reverts the silent drift; the plan and code re-align.
  - Tradeoff: Loses real UX improvement that the user asked for. The "silent clamp" the user flagged returns.
  - Confidence: HIGH — the removal is well-bounded.
  - Blind spot: User would need to re-decide whether they want the feedback; risks a roundtrip already had.
- **Decision**: FIXED via Fix A — addendum added to `plan.md` ("Addenda — 2026-05-25") and the "Validation strategy" row in `plan-brief.md` updated. Documents the corrected (textEdited-tracking) implementation shape.

### F3 — No test class for the validation-feedback slot

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: `tests/test_settings_dialog.py` (no `TestValidationFeedback` class)
- **Detail**: The single test added (test_spinbox_tooltip_explains_range) only asserts the static setToolTip text. Nothing exercises the editingFinished slot or the typed-vs-actual comparison. This is exactly why F1 slipped through: there's no test that would have caught "tooltip fires for in-range values too".
- **Fix**: Add a `TestValidationFeedback` class with at least: (a) typing a clamped value (e.g., 0) → slot fires; (b) typing a valid value (e.g., 30) → slot does NOT fire the tooltip path.
- **Decision**: FIXED — added `TestValidationFeedback` class with 7 tests covering: text capture, in-range no-tooltip, below-min tooltip, above-max tooltip, no-textEdited no-op, capture reset, garbage input safety. All tests pass (21/21 in `test_settings_dialog.py`).

### F4 — QToolTip.showText rect arg hides tip aggressively

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `break_reminder/ui/settings_dialog.py:144`
- **Detail**: The 4-arg overload of `QToolTip.showText(pos, text, widget, rect)` hides the tooltip when the cursor leaves `rect`. After editingFinished fires (e.g., on Tab or focus loss), the cursor is typically already outside the spinbox rect, so Qt may hide the tip immediately. Combined with F1, the user would see the tooltip flash and disappear on every commit.
- **Fix**: Drop the rect argument — use the 3-arg overload `QToolTip.showText(pos, text, widget)` with msecShowTime appended. Or omit the rect, rely on default 10s display.
- **Decision**: FIXED — folded into F1's textEdited-tracking rewrite. The new slot calls `QToolTip.showText(pos, text, widget, msecShowTime=3000)` with no rect arg, so the tooltip no longer hides on cursor exit.

### F5 — Bounds [1, 240] duplicated across 3 locations

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architecture
- **Location**: `storage/settings.py:111,116` + `ui/settings_dialog.py:36-44` + `plan.md` repeatedly
- **Detail**: Three independent declarations of the FR-006 [1, 240] range: Settings.break_interval_min getter/setter clamp, the settings_dialog.py module constants, and the plan text. A future loosening (e.g., to [1, 480]) needs three coordinated edits — drift-prone.
- **Fix**: Promote `BREAK_INTERVAL_MIN_MINUTES` / `BREAK_INTERVAL_MAX_MINUTES` to public constants in `storage.settings` and import them from `settings_dialog.py`.
- **Decision**: FIXED — added public constants to `storage/settings.py` (with a header comment marking them as the single source of truth for FR-006 bounds). `Settings.break_interval_min` getter and setter now reference them directly. `settings_dialog.py` imports them from `storage.settings` and uses them for `setMinimum`/`setMaximum` and the bounds check; the `_BREAK_INTERVAL_RANGE_MESSAGE` string composes them into the user-facing wording. Plan.md range references in prose remain as documentation; they're no longer load-bearing.

### F6 — Missing qtbot.addWidget in test_reject_does_not_persist

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_settings_dialog.py:127-141`
- **Detail**: `test_reject_does_not_persist` constructs `d = SettingsDialog(...)` manually but doesn't call `qtbot.addWidget(d)`. Other tests in the same file consistently register dialogs for cleanup. The test passes today but breaks the established convention from `test_break_dialog.py`.
- **Fix**: Add `qtbot.addWidget(d)` after construction; pass `qtbot` as a fixture parameter.
- **Decision**: FIXED — `qtbot` added as a fixture parameter and `qtbot.addWidget(d)` called immediately after the manual `SettingsDialog(...)` construction. Test now matches the registration convention used by every other dialog test in the file.
