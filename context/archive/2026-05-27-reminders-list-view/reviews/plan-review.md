<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Reminders List View Implementation Plan

- **Plan**: `context/changes/reminders-list-view/plan.md`
- **Mode**: Deep
- **Date**: 2026-05-27
- **Verdict**: REVISE → SOUND (all 7 findings triaged and applied)
- **Findings**: 1 critical · 4 warnings · 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | FAIL → PASS after fixes (F1, F2, F5) |
| Plan Completeness | WARNING → PASS after fixes (F3, F4, F6, F7) |

## Grounding

12/12 paths ✓, 4/4 symbols ✓, brief↔plan ✓. Verified `SettingsDialog` callsites (1 in `app.py`, 12 in `tests/test_settings_dialog.py`), imports currently absent (`datetime`, `tzinfo`, `next_firing_after`, `Reminder`, `ReminderStore`, `QLabel`, `QListWidget`, `QListWidgetItem`), existing tab-storage rule, and the Qt-6 disabled-button-tooltip behaviour (via doc.qt.io/qt-6 + qtbase source).

## Findings

### F1 — "Coming in a future update." tooltip will not show on disabled buttons

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 §3 (button row) + Phase 1 Manual Verification line 218 + Phase 1 §10 test "Buttons carry the 'coming soon' tooltip"
- **Detail**: Qt 6's documented behaviour: "disabled widgets do not receive mouse events." Verified against doc.qt.io/qt-6 and qtbase source. The plan calls `setEnabled(False)` AND `setToolTip(...)` on every button, but Qt swallows the hover event before the tooltip ever shows. The unit test `add.toolTip() == _REMINDERS_BUTTONS_DISABLED_TOOLTIP` passes (the property is set), but the manual-verification step "hovering each button shows the tooltip" silently fails — the first-run user gets no signal what these grey buttons are for.
- **Fix A ⭐ Recommended**: Wrap each button in a tooltip-bearing `QWidget` container
  - Strength: The wrapper QWidget stays enabled, so it receives hover events and shows the tooltip. Zero event-loop wiring; pure composition.
  - Tradeoff: Three trivial wrapper QWidgets; test changes from `add.toolTip()` to `add.parentWidget().toolTip()`.
  - Confidence: HIGH — standard Qt idiom for this exact problem; no platform differences.
  - Blind spot: Wrapper layout must zero contentsMargins or button alignment shifts.
- **Fix B**: Install a per-button `QEvent.ToolTip` event filter
  - Strength: No wrapper widgets.
  - Tradeoff: Adds an event-filter paradigm the dialog doesn't use; harder to test.
  - Confidence: MEDIUM — works, but introduces a one-off paradigm.
  - Blind spot: Event filter lifecycle on dialog GC.
- **Decision**: FIXED via Fix A — wrapper widget pattern applied in §3 Contract; §10 test updated to assert `add.parentWidget().toolTip()`; Critical Implementation Details gained a "Tooltips on disabled buttons" entry.

### F2 — "no live reload" manual-verification step is a tautology

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 Manual Verification line 221 + Testing Strategy → Manual Testing Steps #5 line 350
- **Detail**: `ReminderStore.list_all()` is read-only — file mtime moves only on write. The mtime check will always pass even if the dialog reloads every second. The unit-test spy already pins the no-reload invariant correctly; only the manual-step copy gives false confidence.
- **Fix**: Replace mtime check with a visual no-flicker check; note that the strict invariant is the unit-test spy's responsibility.
- **Decision**: FIXED — Manual Verification line 221, Testing Strategy Manual Step #5, and Progress item 1.11 all updated to the visual-check form.

### F3 — Author "thinking aloud" left in §4 (selection-changed slot)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §4 lines 113 and 117
- **Detail**: The Intent paragraph contained a mid-sentence "wait —" reversal and an italicized "Re-read after writing" self-note — author-process artifacts the implementer would read as instructions.
- **Fix**: Replace §4 Intent with the settled spec; delete the italicized re-read note.
- **Decision**: FIXED — §4 Intent rewritten; italicized note deleted; Contract now shows the S-07 hand-off body as a fenced Python block.

### F4 — Misreads existing tab-storage rule (§1)

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §1 line 91
- **Detail**: Plan said `self._reminders_tab` should be stored for "four parallel attributes" symmetry; existing rule (documented in code comments at `settings_dialog.py:263-264` and `268-270`) is "store only when `accept()` needs to switch to it on validation failure". `_scheduling_tab` is not stored.
- **Fix**: Drop `self._reminders_tab`; inline into `addTab(...)`.
- **Decision**: FIXED — §1 Contract rewritten to inline `self._tabs.addTab(self._build_reminders_tab(), self.REMINDERS_TAB_LABEL)` and explicitly call out the existing rule + its codebase reference.

### F5 — Local-time test passes trivially on a UTC CI runner

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 §10 line 195 + Testing Strategy line 310
- **Detail**: `_format_firing` always calls `.astimezone()`. On the `windows-latest` runner (UTC by default), `<utc>.astimezone() == <utc>`, so the test passes even if a future refactor REMOVES the `.astimezone()` call. The Critical Implementation Details box flags the risk but the test design doesn't catch it.
- **Fix A ⭐ Recommended**: Refactor `_format_firing` to accept optional `tz` parameter; test injects a fixed offset.
  - Strength: Pure-function test, no monkeypatching; conversion behaviour observable on any runner.
  - Tradeoff: One extra parameter on the helper.
  - Confidence: HIGH.
  - Blind spot: None significant.
- **Fix B**: Monkeypatch `break_reminder.ui.settings_dialog.datetime`.
  - Strength: No API change.
  - Tradeoff: Brittle; couples test to import path.
  - Confidence: MEDIUM.
  - Blind spot: Breaks if S-06+ changes the import.
- **Decision**: FIXED via Fix A — `_format_firing(fire_at, *, tz=None)` signature; `_compose_row` threads `tz` through; §10 test now does both the tz-injection assertion AND the tautology-pinning system-local default; Testing Strategy entry updated; new imports include `timedelta`, `timezone`, `tzinfo`.

### F6 — Test-fixture sweep is larger than the plan acknowledges

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §9 line 163
- **Detail**: 12 direct `SettingsDialog(...)` constructions in `tests/test_settings_dialog.py` (lines 83, 108, 213, 234, 250, 504, 525, 592, 616, 992, 1072, 1106). Plan said "Sweep all of them" without quantifying.
- **Fix**: Add exact line numbers and mention the smaller-diff helper-factory alternative.
- **Decision**: FIXED — §9 Intent now lists all 12 lines and the `_make_dialog(...)` helper alternative; verification grep command appended.

### F7 — Imports list is incomplete

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 §5 line 125 + §6 line 133
- **Detail**: Plan flagged `datetime` as "(add if not)" but didn't list the full new-import set.
- **Fix**: Add an "Imports added" subsection with all four import lines verbatim.
- **Decision**: FIXED — new §4a "Imports added to `settings_dialog.py`" inserted between §4 and §5; lists `datetime`/`UTC`/`timedelta`/`timezone`/`tzinfo` from datetime, `next_firing_after` from scheduler, `Reminder`+`ReminderStore` from storage.reminders, and `QLabel`/`QListWidget`/`QListWidgetItem` added to PySide6.QtWidgets.
