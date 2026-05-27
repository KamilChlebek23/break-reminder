<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Reminders Edit / Delete Implementation Plan

- **Plan**: `context/changes/reminders-edit-delete/plan.md`
- **Mode**: Deep
- **Date**: 2026-05-27
- **Verdict**: REVISE → SOUND (all 6 findings triaged + fixed)
- **Findings**: 1 critical, 3 warnings, 2 observations — **6/6 Fixed**

## Verdicts

| Dimension | Verdict (before fixes) | Verdict (after fixes) |
|-----------|------------------------|------------------------|
| End-State Alignment   | PASS    | PASS |
| Lean Execution        | PASS    | PASS |
| Architectural Fitness | PASS    | PASS |
| Blind Spots           | WARNING | PASS (F3 + F4 fixed) |
| Plan Completeness     | FAIL    | PASS (F1 + F2 + F5 + F6 fixed) |

## Grounding

Grounding: 8/8 paths ✓, 14/14 symbols ✓, brief↔plan ✓ (cosmetic: brief claims "14 tests" — plan now lists 17 with the post-refresh + Delete OSError additions; not flagged as a finding since the brief is an at-a-glance summary).

## Findings

### F1 — Phase 2 Progress section is missing 2 manual items

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 Success Criteria + Progress section
- **Detail**: Phase 2 "Manual Verification" listed 11 bullets but the corresponding Progress block had only 9 entries (2.5–2.13). The two extras ("Add flow still works unchanged" + "No regressions in Scheduling/Notifications/Lifecycle tabs") had no matching `- [ ]` line in Progress. Per `references/progress-format.md`, every Success Criteria bullet MUST have a Progress entry — `/10x-implement` parses the Progress section mechanically.
- **Fix**: Delete the last two bullets from Phase 2 Manual Verification. They duplicate Phase 1 items 1.18 and 1.19; Phase 2 doesn't independently re-verify Add or the unrelated tabs. A small clarifying note now points the reader to Phase 1 for those checks.
- **Decision**: Fixed via Fix (single option).

### F2 — Wrapper-tooltip cleanup vague ("if any") — 2 tests + 1 docstring + 1 import need explicit handling

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1, change #9
- **Detail**: Plan #9 said "the existing S-05 test pinning the Edit/Delete wrapper tooltip (if any) is removed or rewritten…" — but FOUR artifacts actually need touching:
  1. `test_edit_delete_tooltip_lives_on_wrapper_not_on_button` (line 2004) → REMOVE
  2. `test_edit_and_delete_buttons_remain_wrapped_and_disabled` (line 2217, inside `TestRemindersAddButton`) → REMOVE
  3. `test_empty_state_still_renders_button_row` docstring (line 2147) → UPDATE
  4. `_REMINDERS_BUTTONS_DISABLED_TOOLTIP` import on line 45 → REMOVE
- **Fix**: Rewrote Phase 1 #9's wrapper-cleanup paragraph as a numbered list of four artifacts with line numbers and explicit verbs (REMOVE / UPDATE).
- **Decision**: Fixed via Fix (single option).

### F3 — No test pins "Edit/Delete are disabled after refresh clears prior selection"

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 — `TestRemindersEditButton` / `TestRemindersDeleteButton`
- **Detail**: Desired End State #6 promises *"After Edit save or Delete confirm… the selection clears (so Edit/Delete go back to disabled until the user selects again)."* The mechanism is **implicit**: `_refresh_reminders_tab` → `_build_reminders_tab` → `_build_reminders_button_row` constructs fresh `QPushButton`s with `setEnabled(False)`, reassigning the attributes. The OLD buttons (stale "enabled" state) are detached. If a future refactor rebuilds JUST the list (not the buttons), `_reminders_sorted[currentRow() == -1]` would silently index the LAST element and Edit/Delete the wrong reminder. The risk is small but the failure mode is silent and destructive.
- **Fix**: Added `test_edit_button_disabled_after_refresh_clears_prior_selection` to `TestRemindersEditButton` and `test_delete_button_disabled_after_refresh_clears_prior_selection` to `TestRemindersDeleteButton`. Each: `setCurrentRow(0)` → button enables → call `dialog._refresh_reminders_tab()` → assert button is disabled. The Edit-side test docstring explicitly calls out the "rebuild reassigns the button attribute" invariant.
- **Decision**: Fixed via Fix (single option).

### F4 — Delete-path OSError handling asymmetric with Edit-path (no spec, no test)

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 — change #7 (`_on_reminders_delete_clicked`) + test #9 (`TestRemindersDeleteButton`)
- **Detail**: Edit-mode `store.update` had full OSError spec + test (`test_edit_mode_oserror_on_store_update_blocks_dialog`). `_on_reminders_delete_clicked` described only the happy path. `ReminderStore.delete` writes JSON atomically; on locked file / full disk / AV quarantine, it raises `OSError` — currently propagates as an unhandled traceback in the terminal, list stays stale, JSON unchanged, user retries with same crash. The Edit-side pattern (transient tooltip + early return + no refresh) is the established convention.
- **Fix**: Spec'd OSError handling on Delete in plan #7 (step 5: try/except OSError + `logger.exception` + transient tooltip on Delete button via new `_DELETE_FAILED_FORMAT` module constant + early return; no scheduler reload, no tab refresh). Added `test_delete_oserror_on_store_delete_keeps_list_intact` to `TestRemindersDeleteButton` (monkeypatch `store.delete` to raise PermissionError; assert atomic-save invariant: store unchanged, scheduler.reload not called, tab not rebuilt).
- **Decision**: Fixed via Fix (single option).

### F5 — Pyright narrowing for `_reminders_list.currentRow()` hedged ("if pyright needs it")

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — changes #6 and #7
- **Detail**: Plan #6 said "document with a narrowing assert if pyright needs it." Since `_reminders_list: QListWidget | None` (line 463 of settings_dialog.py), pyright WILL flag this. The hedge would cost the implementer a CI round-trip.
- **Fix**: Replaced the hedge with a concrete spec for both #6 and #7: each click handler's first executable line is `assert self._reminders_list is not None, "<handler> should only be reachable when a row is selected, which requires the list to exist"` — same idiom `settings_dialog.py:807` uses for `_reminders_tab`. Restructured both methods' Contract sections as numbered steps so the assert is clearly the first executable line.
- **Decision**: Fixed via Fix (single option).

### F6 — QMessageBox monkeypatch site for tests unspecified

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 — test #9 (Delete tests)
- **Detail**: Plan said "monkeypatch `QMessageBox.question` with a recorder" but didn't specify which call site. `tests/test_app.py:373-381` already establishes the Qt-class-level convention for app-level QMessageBox. The form-side could either follow that or use the import-site form (which S-06 used for `ReminderFormDialog`). Inconsistency is a code-review nit, not a runtime bug.
- **Fix**: Added a "QMessageBox monkeypatch convention" paragraph to Phase 1 #9 prescribing the Qt-class-level form (`monkeypatch.setattr(QMessageBox, "question", recorder)`) and citing the `tests/test_app.py:373-381` precedent. Explicitly forbids the import-site form for consistency.
- **Decision**: Fixed via Fix (single option).

## Triage Summary

| Outcome  | Findings              | Count |
|----------|-----------------------|-------|
| Fixed    | F1, F2, F3, F4, F5, F6 | 6 |
| Skipped  | —                     | 0 |
| Accepted | —                     | 0 |
| Dismissed| —                     | 0 |

**Verdict after fixes: REVISE → SOUND.** The plan is ready to feed `/10x-implement reminders-edit-delete phase 1`.
