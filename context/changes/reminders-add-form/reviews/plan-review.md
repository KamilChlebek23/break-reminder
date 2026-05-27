<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Reminders Add Form

- **Plan**: `context/changes/reminders-add-form/plan.md`
- **Mode**: Deep
- **Date**: 2026-05-27
- **Verdict**: REVISE → SOUND (after fixes applied)
- **Findings**: 1 critical, 3 warnings, 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | WARNING |
| Plan Completeness | WARNING |

## Grounding

10/10 paths ✓, 3/3 new paths absent ✓, 19 `SettingsDialog(` callsites ✓ (matches plan claim), `contract-surfaces.md` absent (skip), brief↔plan ✓

## Findings

### F1 — Phase 2 Progress section drifts from Success Criteria

- **Severity**: ❌ CRITICAL
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Success Criteria + Progress section
- **Detail**: Phase 2 Manual body had 4 bullets but Progress 2.6 ("validation tooltips fire as expected") didn't map to any Success Criteria bullet, while body #1 ("empty `reminders.json` → Add enabled, sub-dialog opens") had no Progress entry. `/10x-implement` parses Progress mechanically so this needed fixing per the skill's progress-format contract.
- **Fix**: Added validation-tooltips as a 5th body bullet and renumbered Progress to 2.4–2.8 (now matched 1:1 to the 5 body bullets).
- **Decision**: FIXED

### F2 — Phase 1 #12 mis-states current AGENTS.md text

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1, Change #12 — AGENTS.md tightening
- **Detail**: Plan claimed AGENTS.md:184 currently reads `"Custom-reminder editor dialog (FR-011 / FR-012 CRUD)."` Actual current text is much longer (already mentions Add/Edit/Delete wiring + a descriptive S-05/S-06/S-07 clause that's itself slightly inaccurate — only `_on_reminders_selection_changed` is wired today, not the click signals). Phase 2.1 grep `git grep 'Custom-reminder editor dialog'` would still match a corrected bullet that keeps the prefix.
- **Fix**: Rewrote Phase 1 #12 contract against the actual current text with explicit before/after; new bullet narrows to "Custom-reminder Edit / Delete dialog wiring (FR-012)..."; Phase 2.1 grep now anchors on the phrase fragment "Custom-reminder editor dialog" which the new bullet doesn't have, and Phase 2 #4 was updated to also grep for the positive presence of the new bullet text.
- **Decision**: FIXED

### F3 — Default datetime: UTC↔local conversion is unresolved

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Desired End State #2; Phase 1 #2 (Contract); Phase 1 #10 (TestReminderFormDialogDefaults)
- **Detail**: The dialog reads `self._clock()` which returns UTC-aware (via `_utcnow` default), but `QDateTimeEdit` displays and round-trips naive local. The plan described the default in three inconsistent ways across three locations; the test as-written would have failed on any non-UTC runner because it compared tz-aware UTC to naive-local.
- **Fix**: Pinned the seeding flow as concrete code in Phase 1 #2 Contract (`utc → astimezone() → +1h → round-up → replace(tzinfo=None) → setDateTime`). Updated the test in Phase 1 #10 to compute the expected naive-local value from the injected frozen UTC clock (not hardcoded), so it works on any CI runner regardless of system zone. Updated Desired End State #2 to reference the Phase 1 #2 Contract for the exact computation.
- **Decision**: FIXED

### F4 — `test_save_emits_reminder_added_before_super_accept` uses fragile `monkeypatch QDialog.accept` technique

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 1 #10 — TestReminderFormDialogSave
- **Detail**: Plan said "monkeypatch QDialog.accept to record the order". Monkeypatching the parent class affects every QDialog in the process and is brittle. The invariant (emit happens before super().accept()) IS load-bearing per Critical Implementation Details, but can be tested more cleanly via `QDialog.result()`, which super().accept() flips from Rejected to Accepted.
- **Fix**: Replaced the technique with: connect a recording slot to `reminder_added` that captures `dialog.result()` at emit time; call `dialog.accept()` directly; assert the captured result was `Rejected` (super().accept() hadn't yet fired when the signal emitted); after return, assert `dialog.result() == Accepted`.
- **Decision**: FIXED

### F5 — Phase 2 #3 contract glosses over second S-06 table row at roadmap.md:193

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Plan Completeness
- **Location**: Phase 2 #3 — Update roadmap.md
- **Detail**: "Three substitutions" covers lines 37 + 158 + new `## Done` entry. But roadmap.md:193 has another S-06 row in a different table (no status column — "no" is the blocked-flag column). Doesn't need updating, but plan should explicitly say so to prevent the implementer from worrying about it.
- **Fix**: Added a sentence to Phase 2 #3 Contract noting that the second roadmap.md table at line 193 has no status column and does not need updating; clarified that the "no" in that row is the blocked-flag column, not a status.
- **Decision**: FIXED

### F6 — `test_add_button_has_no_wrapper_tooltip` suggests two assertion methods, second is wrong

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Plan Completeness
- **Location**: Phase 1 #11 — TestRemindersAddButton contract
- **Detail**: The "check parent has more than one child widget" assertion is a tautology — the row layout has 4 items (stretch + 3 buttons-or-wrappers) whether Add is wrapped or not. Only the "parent's tooltip is empty" check is meaningful.
- **Fix**: Dropped the second assertion suggestion from the contract. The test now pins solely on `parentWidget().toolTip() == ""` with an inline comment explaining why the alternative was a tautology (so the next reviewer doesn't reintroduce it).
- **Decision**: FIXED

### F7 — `_refresh_reminders_tab` leaves orphan tab widgets parented to SettingsDialog

- **Severity**: 💡 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Blind Spots
- **Location**: Phase 1 #7 — _refresh_reminders_tab Contract
- **Detail**: `QTabWidget.removeTab()` removes the page but does NOT delete the QWidget — it remains parented to SettingsDialog and leaks per Add click until Settings closes. For the persona (open Settings rarely, add a handful per session) bounded growth is acceptable, but the plan didn't acknowledge it.
- **Fix**: Rewrote Phase 1 #7 Contract as a 6-step ordered list with `old_tab = self._reminders_tab` capture + `old_tab.deleteLater()` after `removeTab()`. The order is now load-bearing and documented as such.
- **Decision**: FIXED
