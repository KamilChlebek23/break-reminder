<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Reminders Recurrence Editor (S-08)

- **Plan**: `context/changes/reminders-recurrence-editor/plan.md`
- **Mode**: Deep
- **Date**: 2026-05-28
- **Verdict**: REVISE → SOUND (after triage; all 7 findings fixed)
- **Findings**: 2 critical, 3 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | FAIL |
| Lean Execution | WARNING |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

5/5 paths ✓, 4/4 symbols ✓, brief↔plan ✓.

Verified: `reminder_form_dialog.py:481-500` matches the plan's "existing past-time gate" description; `tests/test_settings_dialog.py:1900-1920` already covers the recurring-RRULE rendering precedent; `AGENTS.md:184` contains the FR-014 bullet exactly as quoted; `next_firing_after` is NOT currently imported in `reminder_form_dialog.py` (not in runtime, not in TYPE_CHECKING) — Phase 1 #5's "promote" wording is technically a new import.

## Findings

### F1 — Custom-locked cascade silently drops end_at on save

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: End-State Alignment
- **Location**: Phase 1 #3 (`_on_recurrence_changed` cascade) + Phase 1 #2 line 179 (initial cascade call)
- **Detail**: The cascade slot's `is_recurring = choice != "None" AND choice != "(custom)"` predicate (Phase 1 #3 step 1) means `(custom)` enters the False branch and `setChecked(False)` (step 2). The cascade is called once at the end of `__init__` (Phase 1 #2 line 179), AFTER Edit-mode pre-fill ticks the checkbox for a loaded `end_at`. So a custom-locked reminder with `end_at` set has its checkbox immediately unchecked; on save (even with no other edits), `end_at_proposed=None != self._editing.end_at`, the Edit-mode 3-field skip fails, the recurring branch saves with `end_at=None`. User's original end-date is silently dropped — violates PRD guardrail "Settings persist across reboots and updates" and contradicts the Q5-confirmed design intent ("user can still edit name / datetime / lead / end-date" while custom-locked).
- **Fix A ⭐ Recommended**: Treat `(custom)` as recurring for the cascade
  - Approach: Change `is_recurring` predicate to `choice != "None"` (drop the `!= "(custom)"` clause). Custom-locked then enables both end-date checkbox and field exactly like Daily/Weekly/Monthly. End_at pre-fill sticks; user can edit end-date even on custom-locked reminders.
  - Strength: One-token edit; preserves end_at on no-op save; honors the user-confirmed design intent; the recurring-branch gate already correctly handles `rrule_str_proposed` from `_original_custom_rrule`.
  - Tradeoff: The Monthly-day-31 tooltip logic must remain scoped to `choice == "Monthly"` (not `is_recurring`) — small explicit guard.
  - Confidence: HIGH — the gate's recurring branch already takes `rrule_str_proposed` regardless of how it was set.
  - Blind spot: A user explicitly clearing the end-date by un-ticking the checkbox on a custom-locked reminder loses end_at — but that's deliberate edit, not silent loss. Test for both directions.
- **Fix B**: Drop only the `setChecked(False)` on the False branch
  - Approach: Cascade still disables the checkbox + field for `None` / `(custom)`, but doesn't forcibly uncheck. Pre-fill's ticked state survives.
  - Strength: Minimal behavioral change; `(custom)` end-date row stays disabled (read-only).
  - Tradeoff: Disabled-but-checked is a confusing visual state; user can't edit the end-date on a custom-locked reminder at all — contradicts the Q5 answer.
  - Confidence: MED — visual + contract issues outweigh the smaller diff.
  - Blind spot: Doesn't address whether the cascade for `None` should also preserve check state on no-op transitions.
- **Decision**: FIXED via Fix A — cascade predicate dropped the `!= _CUSTOM` clause; added two tests (`test_custom_locked_with_end_at_preserves_end_at_on_no_op_save`, `test_custom_locked_end_date_field_remains_enabled`).

### F2 — Three-way contradiction on `_recurrence_label("FREQ=...;BYDAY=...")`

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Critical Implementation Details (line 104) vs Phase 1 #6 (helper) vs Phase 1 #9 (test)
- **Detail**: Three places in the plan disagree on what `_recurrence_label` returns for an unmapped `rrule_str`: CID line 104 says `""` (suppress); Phase 1 #6 helper returns `_RECURRENCE_SUFFIX_CUSTOM = "custom"`; Phase 1 #9's `test_active_recurring_custom_appends_custom_suffix` AND Manual Verification line 436 expect the `(custom)` suffix to appear. Implementer would have to guess.
- **Fix**: Pick the show-`(custom)` behavior (matches the user-facing test + manual smoke). Update Critical Implementation Details line 104 to read: "`_compose_row` recurrence suffix is empty for one-shot (`rrule_str=None`) only; unmapped rrule_str gets `(custom)` so the user can identify hand-edited rows at a glance."
- **Decision**: FIXED — Critical Implementation Details bullet rewritten to align with the Phase 1 #6 helper and the Phase 1 #9 test.

### F3 — Suffix constants in form module are dead code (+ tripwire pins nothing real)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Lean Execution
- **Location**: Phase 1 #1 (line 128) + Phase 1 #6 + Phase 1 #9 tripwire test
- **Detail**: Phase 1 #1 puts `_RECURRENCE_SUFFIX_DAILY/WEEKLY/MONTHLY` in `reminder_form_dialog.py`; Phase 1 #6 puts the same plus `_CUSTOM` in `settings_dialog.py`; Phase 1 #9 adds a tripwire asserting byte equality. But the form module never uses these constants — they only feed `_compose_row`'s display rendering in settings_dialog. The form module's contract with the suffixes is on `rrule_str` strings (`"FREQ=DAILY"`), not display labels (`"daily"`). The "no cross-import" justification (line 128) doesn't apply: `settings_dialog` already imports from `reminder_form_dialog`, so a one-way import would be fine — but isn't even needed since the form doesn't consume the constants.
- **Fix A ⭐ Recommended**: Define suffixes only in `settings_dialog.py`; drop tripwire
  - Approach: Phase 1 #1 drops the `_RECURRENCE_SUFFIX_*` block. Phase 1 #9 drops `test_recurrence_suffix_constants_match_form_dialog`. Phase 1 #6 keeps all four. Net: 3 fewer constants, 1 fewer test, 0 cross-module coupling.
  - Strength: Single source of truth; matches codebase pattern (`_FIRING_FORMAT` lives only in `settings_dialog.py`).
  - Tradeoff: None significant.
  - Confidence: HIGH — codebase precedent is unambiguous.
  - Blind spot: None.
- **Fix B**: Keep duplication, fix the constant set + tripwire scope (companion to F4)
  - Approach: Add `_RECURRENCE_SUFFIX_CUSTOM` to the form module's Phase 1 #1 constant block; tripwire compares all four.
  - Strength: Preserves "no cross-module imports" stance.
  - Tradeoff: Form module stays bloated with 4 constants it doesn't use; tripwire exists only to enforce the duplication it created.
  - Confidence: HIGH — works, just isn't lean.
  - Blind spot: Future contributors will ask "why are these here?" and need a comment.
- **Decision**: FIXED via Fix A — form-side constants removed; tripwire test removed; suffixes live only in `settings_dialog.py` per the `_FIRING_FORMAT` precedent. Also resolves F4.

### F4 — `_RECURRENCE_SUFFIX_CUSTOM` missing from form module's constant block

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 #1 (line 128) vs Phase 1 #9 (tripwire)
- **Detail**: Phase 1 #1 lists three suffix constants for the form module (DAILY/WEEKLY/MONTHLY) but omits `_CUSTOM`. Phase 1 #6 lists four in `settings_dialog.py`. Phase 1 #9's tripwire claims to assert "the four suffix strings are byte-for-byte equal to the four in `reminder_form_dialog.py`" — but only three exist there per the plan. The test fails to import or silently compares only 3 of 4.
- **Fix**: Resolved automatically by F3 Fix A (drop the form-side constants entirely). If F3 takes Fix B, add `_RECURRENCE_SUFFIX_CUSTOM = "custom"` to Phase 1 #1's form-module block.
- **Decision**: FIXED — resolved by F3 Fix A.

### F5 — Monthly-day-31 tooltip is wired only to picker change, not datetime change

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 #3 step 3 + Phase 1 #2 signal wiring (line 175)
- **Detail**: The Monthly-day-31 tooltip detection lives inside `_on_recurrence_changed`, wired only to the picker's `currentTextChanged`. User flow that breaks: pick Monthly + day-15 → no tooltip (correct); while picker stays Monthly, change datetime to day-31 via `QDateTimeEdit` → tooltip is NOT re-evaluated. Asymmetry: user setting datetime first then picker gets the tooltip; user setting picker first then datetime doesn't.
- **Fix A ⭐ Recommended**: Extract tooltip update into its own slot, wire to both signals
  - Approach: Add `def _update_monthly_tooltip(self) -> None` containing the day-31 detection. Wire to both `self._recurrence_picker.currentTextChanged` AND `self._datetime_field.dateTimeChanged`. Keep the cascade slot for enable/disable. Add one test `test_monthly_tooltip_appears_on_datetime_change_to_day31`.
  - Strength: Symmetric — tooltip reflects current state regardless of which input the user touches last.
  - Tradeoff: One extra slot + one extra signal connection.
  - Confidence: HIGH — Qt signal pattern is straightforward.
  - Blind spot: `dateTimeChanged` fires for every minute spinner click; tooltip will be re-set redundantly. Cheap operation.
- **Fix B**: Move detection into `accept()` as a pre-save warning instead
  - Approach: Drop the live tooltip; on save, when picker=Monthly AND day>28, show a transient `QToolTip.showText`.
  - Strength: No signal wiring; warning at commit moment.
  - Tradeoff: Adds friction to a legitimate save path; conflicts with the plan's "tooltip is informational, not a gate" decision (Critical IDs line 96).
  - Confidence: MED — re-litigates a plan decision.
  - Blind spot: Modal-on-save UX is distinctly different from passive hover.
- **Decision**: FIXED via Fix A — extracted `_update_monthly_tooltip()` slot, wired to both `currentTextChanged` and `dateTimeChanged`; added two tests pinning the symmetric behavior.

### F6 — Progress section count diverges from Phase 1 SC manual

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 SC Manual (lines 429-441) vs Progress 1.9-1.23
- **Detail**: SC Manual has 13 bullets; Progress 1.9-1.23 has 15 entries. Progress 1.11 ("Daily reminder created + row shows suffix") and 1.18 ("Reset → No: state preserved") are sub-items of larger SC bullets. Skill's mechanical contract wants 1:1 enumeration; static `/10x-implement` parsing may complain.
- **Fix**: Either consolidate Progress to 13 items (merge 1.11 into 1.10, 1.18 into 1.17) OR split the two compound SC bullets into separate lines. Consolidation has the smaller diff.
- **Decision**: FIXED — Progress section consolidated to 13 manual items (1.9-1.21); 1.11 merged into 1.10, old 1.18 merged into new 1.16.

### F7 — Minor wording inconsistencies in implementation approach vs contract

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Multiple
- **Detail**: Four small inconsistencies: (a) Line 73 says "currentIndexChanged / toggled" vs Line 175 "currentTextChanged" — Contract is correct. (b) Line 72 helper has `*, clock=None` vs Line 135 "no clock injection needed" — Contract is correct. (c) Line 271 says "promote `next_firing_after` to runtime" — verified NOT currently imported anywhere in the file; should read "add a new runtime import". (d) Line 164 pre-fill has placeholder pseudocode `QDate(... .year, ...month, ...day)` — should be actual `d.month`/`d.day` access.
- **Fix**: One pass through the four spots; each is a 1-2 word edit.
- **Decision**: FIXED — all four wording inconsistencies corrected: line 73 wired signals tightened, line 72 helper signature aligned with Contract, line 271 reworded to "new runtime import", line 164 placeholder replaced with concrete `local_date.year/month/day` access via an intermediate variable.
