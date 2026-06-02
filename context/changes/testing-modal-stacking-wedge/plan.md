# Testing modal-stacking wedge — Implementation Plan

## Overview

Close the R-2 modal-stacking wedge documented in `context/foundation/test-plan.md` §2 R-2 and reproduced by the user as the Q2 lived incident: when `SettingsDialog` (or `ReminderFormDialog`) is open as an application-modal `.exec()` loop and `BreakScheduler` fires, the break popup is painted on top but its action buttons cannot be clicked — input is routed to the modal Settings loop. The user is forced to close Settings before the break popup becomes actionable, directly violating US-02 acceptance.

This is a **test + fix** change. Phase 1 ships a failing parametrized integration test pinning the structural invariant Fix A requires (RED). Phase 2 ships the 1-line production fix that turns it GREEN. Phase 3 syncs the docs that the change has overturned (release-gate smoke, test-plan §2/§6/§3 cells, AGENTS.md FR-009 hardening section).

## Current State Analysis

- Every dialog in the codebase is constructed with `parent=None` (S-01's documented decision for taskbar-entry uniformity, `context/archive/2026-05-25-settings-break-interval/plan.md:53`). `SettingsDialog.exec()` therefore activates Qt's `ApplicationModal` scope **without a parent chain to scope it to**, so any subsequent sibling `.show()` is on top visually but its input is consumed by the modal Settings event loop.
- **Zero `setModal` / `setWindowModality` / `windowModality` references in `break_reminder/`**: modality today is purely a function of `.show()` (modeless) vs `.exec()` (`ApplicationModal`). Confirmed by grep over the full production tree.
- The Q2 lived incident (`context/changes/testing-modal-stacking-wedge/research.md` §4.a):
  > *"I noticed when popup is fired eg. one reminding about break, edition of settings becames impossible. To clear popup, settings must be closed before."*
- The single FR-009 release-gate smoke at `context/deployment/deploy-plan.md:131` exercises **one dialog in isolation** — never opens Settings or the reminder form before triggering the break dialog. This is the gap that let Q2 ship past verification.
- **Phase 1 of the test-plan rollout** (`context/archive/2026-06-01-testing-rrule-reminder-loop/`) has already landed the integration-test harness: session-scoped `QApplication` in `tests/conftest.py`, the canonical `Clock` helper, and the `*_integration.py` filename + `TestPascalCase` class convention demonstrated by `tests/test_recurring_reminder_integration.py`.

## Desired End State

- A new parametrized integration test, `tests/test_modal_stacking_integration.py::TestModalStackingWedge`, passes against `BreakDialog` while either `SettingsDialog` (unparented + `.exec()`) OR `ReminderFormDialog` (parented + `.exec()`) is the topmost dialog. Each parametrized run asserts the same two structural invariants: `BreakDialog.windowModality() == Qt.ApplicationModal` AND `QApplication.activeModalWidget() is breakDialog`.
- `break_reminder/notifications/break_dialog.py::BreakDialog.__init__` calls `self.setWindowModality(Qt.WindowModality.ApplicationModal)` once during construction. The module docstring notes this escalation alongside the existing dismiss-path overrides.
- The 20 existing `tests/test_break_dialog.py` FR-009 hardening tests continue to pass without modification.
- `context/deployment/deploy-plan.md:131`'s release-gate smoke instructs the maintainer to open Settings (and trigger the form) before exercising the break dialog.
- `context/foundation/test-plan.md` §2 R-2 anti-pattern entry warns future test authors about the `QTest.mouseClick` false-negative; §6 cookbook row 'Modal-stacking / wedge survival' names the shipped test; §3 row 2 status cell flips `change opened` → `complete`; frontmatter `rollout_phases_complete` flips `1` → `2`.
- `AGENTS.md`'s `notifications/break_dialog.py` documentation block lists ApplicationModal escalation as the fourth dismiss-path-class invariant.

### Key Discoveries

- **The R-2 regression test cannot be behavioral** (`research.md` §3). Agent C empirically proved that `QTest.mouseClick` on the BreakDialog's "I'll take a break" button while `SettingsDialog` is `ApplicationModal` STILL closes the popup — `QTest.mouseClick` synthesizes input inside Qt's object model and bypasses the platform-level modal grab that the real production bug routes through. Same outcome with `QAbstractButton.click()`. The test must assert **structural** invariants (`windowModality`, `activeModalWidget`), not behavioral click-honored.
- **The test fixture cannot use `.exec()` on the blocking dialog.** `.exec()` blocks the test thread, preventing the subsequent `BreakDialog` construction + assertion. Agent C's smoke pattern (`setModal(True) + setWindowModality(Qt.ApplicationModal) + .show()`) produces equivalent modality without blocking — this is the convention the plan locks in.
- **The 20 existing FR-009 hardening tests are safe with Fix A.** The 4 structural-assertion tests check `windowFlags / focusPolicy / WA_ShowWithoutActivating` — orthogonal to `windowModality`. The 12 behavioral tests use `QPushButton.click()` (Python-level signal trigger, same level as `QTest.mouseClick` per Agent C's diagnosis) — they continue to work even with ApplicationModal escalation. The plan's regression sweep is therefore a one-line `uv run pytest tests/test_break_dialog.py` verification.
- **Lessons-applied rule** (`context/foundation/lessons.md`): every new public function/class must carry a Google-style docstring (enforced by ruff `D` group). The new test class, every test method, and any new fixture must have one.

## What We're NOT Doing

- **No fix for the `ReminderDialog` singleton-guard gap** (R-2-adjacent, `research.md` Finding 2): `ReminderDialog` has no singleton guard at `app.py:397`, so two `reminder_due` signals close together would stack two popups. This is a different bug class (modeless+modeless) than R-2 (modal+modeless). Out of scope; file a separate `/10x-shape` cycle when prioritized.
- **No DST-drift fix for recurring firings** (R-1b): the `TODO(R-1b)` breadcrumb in `tests/test_recurring_reminder_integration.py` stays untouched; that fix requires a `Reminder.start_at` invariant change and its own change folder.
- **No re-parenting of any dialog.** The fix preserves `parent=None` across `BreakDialog`, `SettingsDialog`, `ReminderDialog` — S-01's taskbar-entry-uniformity decision stands.
- **No promotion of `ReminderDialog` (FR-013) to non-dismissable.** The FR-013 asymmetry is a PRD contract (`prd.md:127-128`); only the *break* popup gets modal escalation.
- **No app-wide dialog registry** (e.g. `_active_settings_dialog`, `_active_reminder_dialog`). Fix A doesn't need it — `setWindowModality(ApplicationModal)` self-claims the modal grab. Adding a registry is a Fix B/C concern; Fix A skips it.
- **No `QTest.mouseClick`-based behavioral assertion in the new test.** Agent C proved it gives a false negative. Plan-review must reject any drift that re-introduces the behavioral shape.

## Implementation Approach

Fix A (`setWindowModality(Qt.ApplicationModal)` on `BreakDialog`) was chosen because it has the smallest production diff (one line), preserves user data in any open Settings (Fix B closes Settings; Fix C queues the break indefinitely violating NFR-timing), and inverts the structural cause without touching the `parent=None` decision from S-01. Qt's modal grab nests: the most recently shown modal dialog claims the application-wide input grab, dominating any earlier `.exec()`-loop modal. This is independent of window activation, so it coexists with `WA_ShowWithoutActivating` + `Qt.NoFocus` (US-02's in-flight-keystroke invariant).

The three-phase RED → GREEN → docs ordering mirrors Phase 1 of the test-plan rollout (`testing-rrule-reminder-loop`) and keeps each commit's purpose surgically clear for impl-review.

## Critical Implementation Details

**Test fixture modality pattern (Phase 1).** The blocking-dialog fixture MUST construct the sibling dialog with `setModal(True) + setWindowModality(Qt.WindowModality.ApplicationModal) + .show()`, NOT `.exec()`. The two reasons matter and must be preserved through any refactor:

1. `.exec()` enters its own Qt event loop and blocks the calling thread until the dialog is dismissed — the subsequent `BreakDialog` construction and assertion never run.
2. The pair `setModal(True) + setWindowModality(ApplicationModal)` produces a structurally identical modal scope to a `.exec()` loop's automatically-installed `ApplicationModal` — `QApplication.activeModalWidget()` returns the dialog in both cases. This is Agent C's smoke pattern, documented at `research.md` §3.

**ApplicationModal + WA_ShowWithoutActivating + Qt.NoFocus interaction (Phase 2).** These three are orthogonal at the Qt level: `windowModality` controls which OTHER widgets receive input; `WA_ShowWithoutActivating` controls whether `show()` activates the window; `focusPolicy` controls whether the widget can accept keyboard focus when reached. Setting all three on `BreakDialog` means "claim the application-wide input grab, do not steal activation from the previously-focused app, never accept keyboard focus into me." This is exactly US-02's compound contract. The plan's manual-verification step explicitly re-verifies the in-flight-keystroke acceptance.

---

## Phase 1: Pin Fix A's invariant via failing test (RED)

### Overview

Add a new parametrized integration test that asserts the structural invariants Fix A requires, parametrized over both modality regimes (unparented + `.exec()` Settings; parented + `.exec()` ReminderFormDialog). On current code (Fix A not yet applied), every parametrized run FAILS at the `assert breakDialog.windowModality() == Qt.ApplicationModal` line — proving the test detects the bug.

### Changes Required

#### 1. New integration-test file

**File**: `tests/test_modal_stacking_integration.py`

**Intent**: Pin the structural invariants that Fix A requires, with the assertion parametrized over both blocking-dialog regimes from research §1 (unparented + `.exec()` and parented + `.exec()`). Mirror Phase 1 of the test-plan rollout's filename + class-naming convention (`*_integration.py`, `TestPascalCase`). The file's module docstring documents the R-2 oracle source rule (assertion derived from PRD FR-009 + US-02 contract, NEVER from re-reading `BreakDialog` source) and the no-`.exec()` fixture rule (with the Critical Implementation Details rationale).

**Contract**: One test class `TestModalStackingWedge` exposing one test method `test_break_dialog_dominates_modal_scope_when_sibling_modal_open`, parametrized via `@pytest.fixture(params=["settings", "reminder_form"])` on a `blocking_modal` fixture that yields either `SettingsDialog(...).setModal+show` or `ReminderFormDialog(...).setModal+show`. Shared `tmp_path`-backed fixtures construct `Settings(ini_path=...)`, `ReminderStore(path=...)`, `ReminderScheduler(store=store, clock=Clock(...))`, and a `FakeVoice` stub (mirroring `tests/test_break_dialog.py::FakeVoice`).

**Both `.show()` calls — the blocking modal in the fixture AND `BreakDialog.show()` in the test body — MUST be wrapped in `with qtbot.waitExposed(dialog):`.** This mirrors the convention used 13 times in `tests/test_break_dialog.py` and lets Qt process the show event (including modal-grab installation) before assertions run; without it `QApplication.activeModalWidget()` may return stale state and the test goes flaky (plan-review F2).

The two structural assertions per parametrized run:

```python
break_dialog = BreakDialog(snooze_remaining=1, voice_notifier=None)
qtbot.addWidget(break_dialog)
with qtbot.waitExposed(break_dialog):
    break_dialog.show()

# Both invariants are FAILED on current code; both PASS after Fix A.
assert break_dialog.windowModality() == Qt.WindowModality.ApplicationModal
assert QApplication.activeModalWidget() is break_dialog
```

A pre-action assertion confirms the fixture set up correctly: `assert blocking_modal.windowModality() == Qt.WindowModality.ApplicationModal` BEFORE constructing the break dialog. This guards against the fixture silently producing a non-modal sibling and turning the RED assertion into a vacuous pass. The pre-action does NOT also assert on `QApplication.activeModalWidget()` — whether that getter populates for a `setWindowModality + .show()` (non-`.exec()`) modal is an unverified Qt internal (plan-review F1). The load-bearing modal-grab check happens post-action against `break_dialog` where it must hold for Fix A to be correct.

Every public function/class/fixture gets a Google-style docstring per `lessons.md`.

### Success Criteria

#### Automated Verification

- New file exists at the planned path: `tests/test_modal_stacking_integration.py`
- pytest collects 2 parametrized test cases: `uv run pytest tests/test_modal_stacking_integration.py --collect-only -q` lists 2 items
- Tests FAIL on current code (RED confirmed): `uv run pytest tests/test_modal_stacking_integration.py` reports `2 failed`, with the failure line being one of the two structural assertions (not a fixture/import error)
- Existing FR-009 hardening tests unaffected: `uv run pytest tests/test_break_dialog.py` reports `20 passed`
- Lint passes on the new file: `uv run ruff check tests/test_modal_stacking_integration.py`
- Type check passes on the new file: `uv run pyright tests/test_modal_stacking_integration.py`
- Pre-commit passes against the staged file: `uv run pre-commit run --files tests/test_modal_stacking_integration.py`

#### Manual Verification

- The failure messages in the RED run are readable: a developer skimming the output can tell *which* parametrized run (`settings` vs `reminder_form`) failed and on *which* invariant (`windowModality` vs `activeModalWidget`).

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation that the RED failure messages are readable before proceeding to Phase 2. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Apply Fix A — escalate BreakDialog to Qt.ApplicationModal (GREEN)

### Overview

Add a single `self.setWindowModality(Qt.WindowModality.ApplicationModal)` call to `BreakDialog.__init__` and update the module docstring to record the escalation alongside the existing FR-009 hardening pattern. The Phase 1 tests must turn GREEN; the 20 existing `tests/test_break_dialog.py` tests must continue to pass (pre-verified during research — the 4 structural-assertion tests are orthogonal to `windowModality`; the 12 behavioral tests use `QPushButton.click()` which operates below the modal grab).

### Changes Required

#### 1. Escalate `BreakDialog` to ApplicationModal

**File**: `break_reminder/notifications/break_dialog.py`

**Intent**: Make `BreakDialog` claim the application-wide modal input grab on construction, so when `.show()` runs it dominates any prior `.exec()`-loop modal scope (Settings / ReminderFormDialog). This inverts R-2's structural cause without touching `parent=None`.

**Contract**: Add `self.setWindowModality(Qt.WindowModality.ApplicationModal)` to `BreakDialog.__init__` immediately AFTER the `setFocusPolicy(Qt.FocusPolicy.NoFocus)` line and BEFORE `self._build_ui(snooze_remaining)`. The position is load-bearing only for readability: it groups all window-attribute setup before the UI construction.

The call must coexist with the existing `WA_ShowWithoutActivating` + `Qt.NoFocus` (see Critical Implementation Details for why they're orthogonal). No other change to the dialog's setup.

#### 2. Document the escalation in the module docstring

**File**: `break_reminder/notifications/break_dialog.py` (module docstring at top of file)

**Intent**: Tell the next reader why `BreakDialog` is `ApplicationModal` despite being a `.show()`-modeless construction in the existing FR-009 narrative.

**Contract**: After the existing four-bullet "Every dismiss path is overridden" list (`keyPressEvent`, `closeEvent`, `WindowFlags`, `WA_ShowWithoutActivating`), add a fifth bullet:

> *`setWindowModality(Qt.ApplicationModal)` — claims the application-wide input grab on construction, so when a sibling dialog (Settings, ReminderFormDialog) is already `.exec()`'d, BreakDialog still receives mouse / keyboard events instead of being a Z-order-only overlay. Closes the R-2 modal-stacking wedge.*

Preserve the existing "If you add a new way to clear the dialog…" closing paragraph.

### Success Criteria

#### Automated Verification

- Phase 1 tests now PASS: `uv run pytest tests/test_modal_stacking_integration.py` reports `2 passed`
- Existing 20 BreakDialog tests STILL PASS: `uv run pytest tests/test_break_dialog.py` reports `20 passed`
- Full test suite passes — no regressions in any other test file: `uv run pytest`
- Lint passes: `uv run ruff check break_reminder/notifications/break_dialog.py`
- Type check passes on the full project: `uv run pyright`
- Pre-commit passes against the staged file: `uv run pre-commit run --files break_reminder/notifications/break_dialog.py`

#### Manual Verification

- **Q2 lived-incident fix**: launch the app (`uv run python -m break_reminder`), open Settings, then from the tray menu pick "Take break now"; verify the popup's "I'll take a break" button responds to a real mouse click while Settings is still on screen. Pre-fix this click was silently ignored.
- **ReminderFormDialog regime fix**: open Settings → Reminders tab → "Add reminder"; while the form is open, from the tray menu pick "Take break now"; verify the popup is clickable.
- **US-02 in-flight-keystroke regression check**: open a text editor (Notepad, IDE), start typing a sentence, then trigger "Take break now" from the tray; verify the in-flight keystroke continues to land in the editor (the popup did NOT steal activation despite the new ApplicationModal escalation). This is the load-bearing US-02 acceptance criterion the Critical Implementation Details flag.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation that the Q2 incident is fixed AND that US-02's in-flight-keystroke acceptance still holds before proceeding to Phase 3.

---

## Phase 3: Docs sync — close the change

### Overview

Land all the documentation updates that the change has overturned in a single atomic commit: the release-gate smoke step that originally let Q2 slip past, the test-plan §2 R-2 anti-pattern entry and §6 cookbook row and §3 status cell, and the AGENTS.md FR-009 hardening doc. No code changes in this phase.

### Changes Required

#### 1. Extend the release-gate smoke step

**File**: `context/deployment/deploy-plan.md` (around line 131)

**Intent**: Close the single-dialog-only gap that originally let Q2 ship past the FR-009 release-gate verification.

**Contract**: The existing numbered list item reads:

> *"Wait for or trigger a break dialog; verify Esc / Alt+F4 / click-outside / focus-loss do NOT dismiss it (FR-009 / US-02)."*

Insert a NEW numbered sub-bullet (or sibling bullet) immediately after it:

> *"Open Settings, then trigger 'Take break now' from the tray; verify the popup's 'I'll take a break' button is clickable WHILE Settings is still on screen. Then close the popup, open Settings → Reminders → 'Add reminder', trigger 'Take break now' again, verify the popup is clickable WHILE the reminder form is on screen (R-2 modal-stacking wedge)."*

The smoke step's numbering style and indentation match the existing list — no reformatting elsewhere.

#### 2. Update the test-plan §2 R-2 anti-pattern entry

**File**: `context/foundation/test-plan.md` (§2, "Risk Response Guidance" table, R-2 row, "Anti-pattern to avoid" column)

**Intent**: Warn future test authors about the `QTest.mouseClick` false-negative Agent C discovered, so the cookbook reader doesn't re-introduce a behavioral assertion that silently agrees with the bug.

**Contract**: The current cell reads:

> *"Asserting only on widget *visibility* — both dialogs are visible; the regression is that the click never reaches the popup. Must assert the click is *honored*."*

Replace with:

> *"Asserting only on widget *visibility* — both dialogs are visible; that's not the regression. ALSO an anti-pattern: asserting `QTest.mouseClick` on the popup button (or `QPushButton.click()`) is honored — pytest-qt synthesizes input INSIDE Qt's object model and bypasses the OS-level modal grab that the production bug routes through, so the assertion silently agrees with the bug (Agent C's reproduction smoke, documented at `context/changes/testing-modal-stacking-wedge/research.md` §3). Assert STRUCTURAL invariants instead: `BreakDialog.windowModality() == Qt.ApplicationModal` AND `QApplication.activeModalWidget() is breakDialog` after the fire path."*

#### 3. Fill the test-plan §6 cookbook row

**File**: `context/foundation/test-plan.md` (§6, "Cookbook" table, "Modal-stacking / wedge survival" row, "Pattern (TBD until phase ships)" column)

**Intent**: Per the §6 convention ("Per-area patterns. Populated as rollout phases land — each phase's final sub-phase updates the relevant cell."), record the shipped pattern so future `/10x-tdd` runs find it.

**Contract**: Replace the current `TBD — Phase 2 will ship…` text with:

> *"`tests/test_modal_stacking_integration.py::TestModalStackingWedge::test_break_dialog_dominates_modal_scope_when_sibling_modal_open` — parametrized over `SettingsDialog` (unparented + `.exec()` regime) AND `ReminderFormDialog` (parented + `.exec()` regime) as the blocking sibling. Construct the blocking modal with `setModal(True) + setWindowModality(Qt.ApplicationModal) + .show()` — NEVER `.exec()` (blocks the test thread). After `BreakDialog.show()`, assert `BreakDialog.windowModality() == Qt.ApplicationModal` AND `QApplication.activeModalWidget() is breakDialog`. Fix lives in `break_reminder/notifications/break_dialog.py::BreakDialog.__init__` (`setWindowModality(Qt.ApplicationModal)`). The behavioral shape (`QTest.mouseClick` on the popup button) is an anti-pattern — see §2 R-2."*

#### 4. Flip the test-plan §3 status cell and frontmatter

**File**: `context/foundation/test-plan.md` (frontmatter + §3, "Phased rollout" table, row 2)

**Intent**: Advance the orchestrator state machine. The next `/10x-test-plan` re-run reads §3 to find the first non-`complete` row and routes the next handoff.

**Contract**: In §3 row 2 ("FR-009 wedge: modal-stacking integration tests"), change the `Status` column from `change opened` to `complete`. In the frontmatter, change `rollout_phases_complete: 1` to `rollout_phases_complete: 2`. No other §3 cells change.

#### 5. Update AGENTS.md FR-009 hardening doc

**File**: `AGENTS.md`

**Intent**: Add ApplicationModal escalation to the documented FR-009 hardening pattern, so the next agent reading the conventions sees it as a fourth dismiss-path-class invariant alongside `keyPressEvent`, `closeEvent`, and window flags.

**Contract**: Find the "FR-009 — non-dismissable break popup (`notifications/break_dialog.py`)" subsection under "Load-bearing patterns". The current bullet list begins "The 'non-dismissable' property is implemented by overriding **every** dismiss path:" and enumerates `keyPressEvent`, `closeEvent`, `Window flags`, `Focus policy`. Append a fifth bullet AFTER the focus-policy bullet:

> *"Modality — `setWindowModality(Qt.ApplicationModal)` claims the application-wide input grab so a sibling `.exec()`-loop modal (Settings / ReminderFormDialog) cannot wedge input away from the popup. Closes R-2; see `context/archive/<archive-date>-testing-modal-stacking-wedge/`."*

The closing paragraph ("If you add a new way to dismiss the dialog…") remains unchanged.

### Success Criteria

#### Automated Verification

- All three files modified: `git diff --name-only` from the Phase 3 commit shows `context/deployment/deploy-plan.md`, `context/foundation/test-plan.md`, and `AGENTS.md`
- Sanity check that the docs commit didn't touch any code: `git diff --stat` shows zero `.py` diffs
- Full test suite still PASS: `uv run pytest` (no regressions)

#### Manual Verification

- Open `context/foundation/test-plan.md` §3 row 2: Status reads `complete`
- Open `context/foundation/test-plan.md` §6 row "Modal-stacking / wedge survival": text names `tests/test_modal_stacking_integration.py::TestModalStackingWedge` and the structural invariants
- Open `context/foundation/test-plan.md` §2 R-2 "Anti-pattern to avoid": text warns about the `QTest.mouseClick` false negative AND references `research.md` §3
- Open `context/deployment/deploy-plan.md` around line 131: the smoke step lists "Open Settings first, then trigger break dialog"
- Open `AGENTS.md` FR-009 section: fifth bullet mentions `setWindowModality(Qt.ApplicationModal)`

**Implementation Note**: After completing this phase, the change is implementation-complete and ready for `/10x-impl-review`. Archive is a separate step (`/10x-archive testing-modal-stacking-wedge`) typically run after impl-review approves.

---

## Testing Strategy

### Unit Tests

- N/A — Phase 2's fix is a single `setWindowModality` call. Its semantics are pinned by the Phase 1 integration test, not by a unit test (Qt-internal behavior, not a pure-function helper).

### Integration Tests

- `tests/test_modal_stacking_integration.py::TestModalStackingWedge::test_break_dialog_dominates_modal_scope_when_sibling_modal_open` — 2 parametrized cases (`blocking_modal=settings`, `blocking_modal=reminder_form`), each asserting `BreakDialog.windowModality() == Qt.ApplicationModal` AND `QApplication.activeModalWidget() is breakDialog` after the fire path.

### Manual Testing Steps

(Documented in each phase's Manual Verification section. Summary:)

1. Phase 2: Q2 lived-incident reproduction — launch app → open Settings → trigger break dialog from tray → click "I'll take a break" → verify popup closes.
2. Phase 2: ReminderFormDialog regime — open Settings → Reminders → "Add reminder" → trigger break dialog → click "I'll take a break".
3. Phase 2: US-02 in-flight-keystroke regression check — type in a text editor → trigger break dialog → verify the in-flight keystroke continues to land in the editor.
4. Phase 3: docs-only manual verification, listed per file in Phase 3 Manual Verification.

## Performance Considerations

None. The fix is a single Qt attribute write per `BreakDialog` construction (microseconds). `setWindowModality` does not allocate, does not lock, does not enter the event loop.

## Migration Notes

None. The fix is purely additive at the construction site. No persisted state, no schema, no migration.

## References

- Research: `context/changes/testing-modal-stacking-wedge/research.md` (full synthesis of the structural cause, Agent C's false-negative discovery, and the three fix-shape candidates).
- Test-plan rollout state: `context/foundation/test-plan.md` §2 R-2, §3 row 2, §6 "Modal-stacking / wedge survival" row.
- Phase 1 precedent: `tests/test_recurring_reminder_integration.py` (filename, class-naming, recording-slot pattern, `Clock` fixture import).
- S-01 deferred-decision artifact: `context/archive/2026-05-25-settings-break-interval/plan-brief.md:75` (the "organic v0.2.x discovery" Q2 surfaced).
- S-06 parented-modal precedent: `context/archive/2026-05-27-reminders-add-form/plan.md:15,:89,:222` (the `ReminderFormDialog(parent=self).exec()` regime).
- Q2 verbatim source: `context/changes/testing-modal-stacking-wedge/research.md` §4.a.
- PRD constraints the fix preserves: `context/foundation/prd.md:71-86` (US-02), `:114-115` (FR-009), `:127-128` (FR-013 asymmetry).
- Lessons-applied: `context/foundation/lessons.md` (Google-style docstrings on every new public function/method).

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Pin Fix A's invariant via failing test (RED)

#### Automated

- [x] 1.1 New file exists at the planned path: `tests/test_modal_stacking_integration.py` — b140bf7
- [x] 1.2 pytest collects 2 parametrized test cases: `uv run pytest tests/test_modal_stacking_integration.py --collect-only -q` lists 2 items — b140bf7
- [x] 1.3 Tests FAIL on current code (RED confirmed): `uv run pytest tests/test_modal_stacking_integration.py` reports `2 failed`, with the failure line being one of the two structural assertions (not a fixture/import error) — b140bf7
- [x] 1.4 Existing FR-009 hardening tests unaffected: `uv run pytest tests/test_break_dialog.py` reports `20 passed` — b140bf7
- [x] 1.5 Lint passes on the new file: `uv run ruff check tests/test_modal_stacking_integration.py` — b140bf7
- [x] 1.6 Type check passes on the new file: `uv run pyright tests/test_modal_stacking_integration.py` — b140bf7
- [x] 1.7 Pre-commit passes against the staged file: `uv run pre-commit run --files tests/test_modal_stacking_integration.py` — b140bf7

#### Manual

- [x] 1.8 The failure messages in the RED run are readable: a developer skimming the output can tell which parametrized run (`settings` vs `reminder_form`) failed and on which invariant (`windowModality` vs `activeModalWidget`) — b140bf7

### Phase 2: Apply Fix A — escalate BreakDialog to Qt.ApplicationModal (GREEN)

#### Automated

- [x] 2.1 Phase 1 tests now PASS: `uv run pytest tests/test_modal_stacking_integration.py` reports `2 passed`
- [x] 2.2 Existing 20 BreakDialog tests STILL PASS: `uv run pytest tests/test_break_dialog.py` reports `20 passed`
- [x] 2.3 Full test suite passes — no regressions in any other test file: `uv run pytest` (511 passed)
- [x] 2.4 Lint passes: `uv run ruff check break_reminder/notifications/break_dialog.py`
- [x] 2.5 Type check passes on the full project: `uv run pyright`
- [x] 2.6 Pre-commit passes against the staged file: `uv run pre-commit run --files break_reminder/notifications/break_dialog.py`

#### Manual

- [x] 2.7 Q2 lived-incident fix verified: launch app, open Settings, trigger 'Take break now' from tray, click 'I'll take a break' — popup closes
- [x] 2.8 ReminderFormDialog regime fix verified: open Settings → Reminders → 'Add reminder', trigger 'Take break now' from tray — popup clickable
- [x] 2.9 US-02 in-flight-keystroke regression check passes: type in an editor, trigger 'Take break now', in-flight keystroke continues to land in the editor (popup did NOT steal activation)

### Phase 3: Docs sync — close the change

#### Automated

- [ ] 3.1 All three files modified: `git diff --name-only` from the Phase 3 commit shows `context/deployment/deploy-plan.md`, `context/foundation/test-plan.md`, and `AGENTS.md`
- [ ] 3.2 Sanity check that the docs commit didn't touch any code: `git diff --stat` shows zero `.py` diffs
- [ ] 3.3 Full test suite still PASS: `uv run pytest`

#### Manual

- [ ] 3.4 `context/foundation/test-plan.md` §3 row 2 Status reads `complete`
- [ ] 3.5 `context/foundation/test-plan.md` §6 'Modal-stacking / wedge survival' row names `tests/test_modal_stacking_integration.py::TestModalStackingWedge` and the structural invariants
- [ ] 3.6 `context/foundation/test-plan.md` §2 R-2 'Anti-pattern to avoid' warns about the `QTest.mouseClick` false negative AND references `research.md` §3
- [ ] 3.7 `context/deployment/deploy-plan.md` around line 131 smoke step lists 'Open Settings first, then trigger break dialog'
- [ ] 3.8 `AGENTS.md` FR-009 section fifth bullet mentions `setWindowModality(Qt.ApplicationModal)`
