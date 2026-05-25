# Settings Window — Break Interval Editor Implementation Plan

## Overview

Replace the placeholder `QMessageBox` at `break_reminder/app.py:278-288` with a real `SettingsDialog(QDialog)` that lets the user view and edit the break interval (FR-006) inside a real settings window (FR-005). Use a `QTabWidget` from day one (single "Scheduling" tab today) so S-02..S-05 can land additional fields without re-organizing layout. New module under `break_reminder/ui/settings_dialog.py`. The dialog uses `QSpinBox(min=1, max=240)` so out-of-range entries are physically impossible at the widget level, persists via the existing `Settings.break_interval_min` setter on OK, and discards on Cancel. This slice is the load-bearing scaffold every other v0.2.x settings slice (S-02..S-08) hangs off.

## Current State Analysis

**What exists today (v0.1.0, post-release):**

- `BreakReminderApp._on_open_settings()` at `break_reminder/app.py:278-288` shows a `QMessageBox.information` placeholder telling the user the settings window isn't implemented yet and instructing them to edit the INI file by hand. The slot is wired to two entry points: the tray context menu's "Open settings…" `QAction` (`app.py:208-210`) and a left-click on the tray icon (`app.py:248-252`).
- `Settings.break_interval_min` is fully functional: getter clamps to `[1, 240]` (`storage/settings.py:108-111`), setter raises `ValueError` outside `[1, 240]` (`storage/settings.py:113-117`). Persistence is via `QSettings` IniFormat at `%APPDATA%\BreakReminder\BreakReminder.ini`. Settings already ships with a `Settings(ini_path=…)` injection seam used by every test.
- `BreakScheduler._tick()` reads `Settings.snapshot()` on every tick (`scheduler.py:160`). A mid-cycle interval change is therefore picked up automatically on the next tick — no re-arm signal, no special-case wiring.
- `notifications/reminder_dialog.py` (50 lines) is the closest existing `QDialog` template: `QVBoxLayout` + a `QLabel` + `QDialogButtonBox`, with `setWindowTitle` and a top-stays-on-top hint. The `SettingsDialog` follows the same idiom plus a `QTabWidget` and a `QSpinBox`.
- `tests/test_app.py` already exercises tray-menu wiring (`TestTrayMenuWiring`). The `qapp` fixture from `tests/conftest.py` is the standard way to acquire a `QApplication` for dialog tests.
- `tests/test_settings.py` is the round-trip pattern for INI files under `tmp_path`. It also documents that a setter call followed by `_qs.sync()` materializes the INI on disk (`test_settings.py:101-112`) — useful for any test that wants to read the file back.
- `AGENTS.md` directory layout (`AGENTS.md:22-42`) lists `notifications/` and `storage/` as the only sub-packages today. A new `ui/` sub-package fits parallel to them.

**What's missing:**

- A real settings UI surface — there is no `QDialog` subclass for application configuration today, only the popup-style dialogs in `notifications/`.
- The placeholder text in `_on_open_settings` instructs hand-editing the INI; this is what the slice eliminates.
- The roadmap's S-01 unknown asks whether the dialog should be tab-based or single-pane. The user decision in this planning session: **tab-based** (`QTabWidget` with one "Scheduling" tab today; more tabs land in S-02..S-05).
- Roadmap Q5 ("Settings-dialog layout") is **dissolved** by this plan; mark it resolved in the roadmap when the change archives.

**Key constraints discovered during planning:**

- `QSpinBox.setMinimum(1)` / `setMaximum(240)` are widget-level invariants — the user cannot type a value the `Settings` setter would reject. Validation is therefore pre-empted, no try/except needed in the save path.
- Concurrent `break_due` during `SettingsDialog.exec()` is benign: the break dialog is `.show()`-modeless with `Qt.WindowStaysOnTopHint`, so it appears on top of the modal settings dialog. No special-casing needed in this slice; out-of-scope behavior call left to organic v0.2.x.

## Desired End State

After this plan lands, a user right-clicks the BreakReminder tray icon, clicks "Open settings…", and a real `QDialog` titled "Settings" appears with a `QTabWidget` whose first tab ("Scheduling") shows a `QSpinBox` labeled "Break interval (minutes)" pre-filled with the current `Settings.break_interval_min` value. They edit the value (range physically constrained to 1–240 by the spinbox), click **OK**, and the dialog closes. On the next `BreakScheduler` tick (≤1s later), the new interval is honored — the tray tooltip's countdown reflects it. They reopen settings, edit again, click **Cancel**, and the dialog closes without persisting. They quit and restart the app; the last saved value reloads correctly.

The placeholder `QMessageBox` is gone, the AGENTS.md directory layout includes `ui/`, and `tests/test_settings_dialog.py` plus an additional case in `tests/test_app.py` provide regression coverage.

### Key Discoveries:

- `app.py:278-288` is the literal placeholder slot — that body is what gets replaced in Phase 2.
- `notifications/reminder_dialog.py:24-55` is the byte-for-byte structural template for the new dialog.
- `Settings.break_interval_min` getter/setter already enforce FR-006 — `storage/settings.py:108-117`.
- `BreakScheduler._tick` reads `Settings.snapshot()` every tick — `scheduler.py:160` — so live interval edits Just Work.
- The `qapp` fixture in `tests/conftest.py` and the `TestTrayMenuWiring._find_action` helper at `tests/test_app.py:208-215` are reusable.
- `tests/test_settings.py:101-112` demonstrates the `_qs.sync()` flush pattern for tests that need to read the INI file directly.

## What We're NOT Doing

- **No other settings fields.** Only the break interval. Snooze duration / max snoozes (S-03), voice toggle / phrase (S-04), autostart toggle (S-02) all stay out of this slice — even though their `Settings` getters/setters already exist. The user explicitly chose `low-complexity` and S-01 closes one decision pair (FR-005 + FR-006).
- **No tab beyond "Scheduling".** A single tab today; "Notifications" / "Reminders" tabs land in S-04 / S-05 respectively.
- **No re-arm signal from `Settings` to `BreakScheduler`.** The scheduler already reads `Settings.snapshot()` every tick; mid-cycle changes are honored automatically.
- **No live-reload preview.** Saving applies on the next scheduler tick — there is no in-dialog "preview" of how the change affects the next break.
- **No settings-while-break-dialog handling.** If a `break_due` fires while the user has settings open, both dialogs render (settings is modal, break is modeless-stay-on-top). Concrete UX impact deferred to organic v0.2.x discovery.
- **No dialog parent.** The dialog is constructed with `parent=None` so it has its own top-level window in the taskbar — same pattern as `BreakDialog` and `ReminderDialog`. Consequence: `Esc` closes via the standard `QDialog` reject path (acceptable for settings; the FR-009 "no Esc" hardening is intentionally only on the break dialog).
- **No telemetry / event-log row** for "settings opened" or "break interval changed". The PRD's FR-015 enumerates the events that get logged (BREAK / REMINDER), and "settings edited" isn't among them.
- **No registry / autostart write.** That's S-02. This slice writes only to `BreakReminder.ini`.

## Implementation Approach

Two phases. Phase 1 builds the dialog in isolation behind a unit-test contract; the running app cannot reach it yet, so there's no manual checkpoint. Phase 2 wires the slot, retires the placeholder, and gets the manual smoke. Splitting at this seam means Phase 1 lands as agent-only work and Phase 2 is the small visible change the user actually verifies.

The dialog is created fresh on every `_on_open_settings()` call (no long-lived member). This matches the `ReminderDialog` instantiation pattern in `app.py:315` and means the dialog never holds stale state across opens. The `Settings` instance, however, is the one already injected into `BreakReminderApp` (`app.py:85`) — passing it through to the dialog avoids any duplicate `QSettings` handles on the same INI file.

The save path calls `self._settings.break_interval_min = self._spinbox.value()` and lets `QSettings` handle persistence. Tests that need to assert the INI file is materialized call `settings._qs.sync()` themselves, exactly as `tests/test_settings.py` already does.

## Critical Implementation Details

(Omitted — nothing about this slice needs constraints, gotchas, or ordering callouts beyond what the file paths and Intent statements convey. The mid-cycle re-arm question dissolved during research; the validation question dissolved at the widget level.)

---

## Phase 1: Build `SettingsDialog` in isolation

### Overview

Stand up the `break_reminder/ui/` sub-package, write the `SettingsDialog` class, and cover its load / save / cancel behavior with unit tests. The dialog is reachable only from tests at the end of this phase — `app.py` is unchanged, so the running app still shows the `QMessageBox` placeholder.

### Changes Required:

#### 1. New `ui/` sub-package

**File**: `break_reminder/ui/__init__.py`

**Intent**: Establish a new sub-package that houses non-notification UI surfaces (settings, reminder editors, future dialogs from S-05..S-08). Mirrors the role of `storage/` and `notifications/` — a thin namespace, no module-level logic.

**Contract**: Empty file (or a one-line module docstring) sufficient to make `break_reminder.ui` importable. No public surface yet.

#### 2. `SettingsDialog` class

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: A modal `QDialog` that loads the current break interval from an injected `Settings` instance, lets the user edit it via a bounded `QSpinBox`, and on OK persists the new value through the `Settings.break_interval_min` setter. Cancel discards. Layout: `QVBoxLayout` containing a `QTabWidget` with one tab ("Scheduling"); the tab's `QFormLayout` holds a single labelled `QSpinBox`. Buttons: standard `QDialogButtonBox(Ok | Cancel)`. Window title: "Settings".

**Contract**:

- Constructor signature: `SettingsDialog(*, settings: Settings, parent: QWidget | None = None) -> None`. Settings is keyword-only and required (matches the dependency-injection idiom used in `BreakReminderApp.__init__`).
- The `QSpinBox` bounds are `setMinimum(1)` and `setMaximum(240)` — physical FR-006 enforcement. `setSuffix(" min")` is a UX nicety; keep it. Initial value is `settings.break_interval_min` (read once at construction).
- `accept()` is overridden (or wired via `buttonBox.accepted.connect(...)`) to write `settings.break_interval_min = spinbox.value()` before the standard `QDialog.accept()` chain. `reject()` keeps the default behavior (no write).
- Module-level docstring explains the FR-005 / FR-006 mapping and references the slice (`context/changes/settings-break-interval/plan.md`).
- All public methods get Google-style docstrings per the team rule in `context/foundation/lessons.md`.
- No other settings fields, no autostart toggle, no voice options. Future tabs land in S-02..S-05.

#### 3. Unit tests

**File**: `tests/test_settings_dialog.py`

**Intent**: Cover the load / save / cancel contract in isolation, using the `qapp` fixture from `tests/conftest.py` and a `tmp_path`-bound `Settings` instance. Mirrors the structure of `tests/test_settings.py` (test classes grouping concerns).

**Contract**: Tests assert the following observable behaviors. Test class names parenthesized.

- (`TestLoad`) Spinbox initial value equals the constructor's `settings.break_interval_min`. Cover both default-value and pre-set-via-setter cases.
- (`TestLoad`) Spinbox `minimum()` is 1 and `maximum()` is 240 — tripwire if a future agent loosens the FR-006 bounds at the widget level.
- (`TestSave`) Calling `dialog.accept()` after editing the spinbox persists the new value through `settings.break_interval_min` (read back via the same `Settings` instance, then via a fresh `Settings(ini_path=…)` after `_qs.sync()`).
- (`TestSave`) Calling `dialog.reject()` after editing leaves `settings.break_interval_min` unchanged (read back returns the pre-edit value).
- (`TestSave`) The dialog can be constructed and discarded without showing — `dialog.show()` / `dialog.exec()` are NOT called in these tests; the contract is on the in-memory state transitions, not the QPA platform.
- (`TestLayout`) The dialog contains a `QTabWidget` with exactly one tab today, whose label is "Scheduling" — tripwire if a future slice silently flattens the layout.

Use `tmp_path / "BreakReminder.ini"` as the `ini_path` for every test, exactly as `tests/test_settings.py` does. Reuse the `qapp` conftest fixture; a `QApplication` must exist for any `QWidget` construction.

#### 4. Update AGENTS.md folder layout

**File**: `AGENTS.md`

**Intent**: Add a `ui/` entry to the directory-layout block at `AGENTS.md:22-42` so future contributors know where settings / non-notification dialogs live. Keep the entry minimal and cross-reference the slice.

**Contract**: Insert a line under the `notifications/` block (parallel to `storage/`):

```
  ui/
    settings_dialog.py  # FR-005/006 settings window
```

Also add a short prose paragraph under `## Load-bearing patterns` that distinguishes `notifications/` ("popups that fire on events — break, custom reminder") from `ui/` ("user-initiated configuration surfaces — settings, reminder editors"). One sentence each. Resolves a roadmap-wide naming question for S-05..S-08.

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_settings_dialog.py`
- Full suite still passes: `uv run pytest`
- Type check passes: `uv run pyright break_reminder/ui/ tests/test_settings_dialog.py`
- Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/ui/ tests/test_settings_dialog.py`
- Format check passes: `uv run ruff format --check break_reminder/ui/ tests/test_settings_dialog.py`
- `python -c "from break_reminder.ui.settings_dialog import SettingsDialog"` does not raise.

#### Manual Verification:

- (None — Phase 1 leaves the running app unchanged. The dialog is reachable only via tests.)

**Implementation Note**: After completing this phase and all automated verification passes, proceed directly to Phase 2 — there is no manual user-facing surface to test yet.

---

## Phase 2: Wire the dialog into the tray menu

### Overview

Replace the body of `BreakReminderApp._on_open_settings()` to construct and `exec()` a `SettingsDialog` against the app's existing `Settings` instance. Update `tests/test_app.py` to assert the placeholder is gone and the new dialog is constructed when the slot fires. Run the manual smoke test against a built app to verify load / save / restart-persistence end-to-end.

### Changes Required:

#### 1. Replace `_on_open_settings` body

**File**: `break_reminder/app.py`

**Intent**: Swap the `QMessageBox.information(...)` block at lines 278-288 for `SettingsDialog(settings=self._settings).exec()`. Remove the `QMessageBox` import if it becomes unused at the module level (it is still used at line 393 for the no-tray-detected fatal — keep the import). Remove the unused private helper `_settings_path()` at lines 374-377 if no other call site references it (it is currently only used by the placeholder).

**Contract**:

- New body of `_on_open_settings`: construct `SettingsDialog(settings=self._settings)`, call `.exec()`, return. The dialog is local to the slot so it's GC'd as soon as the modal loop exits — no `self._settings_dialog` member needed (settings doesn't have the asynchronous lifecycle that justifies keeping `self._reminder_dialog` alive at line 315).
- The `TODO(FR-005 / FR-006 / FR-011 / FR-012)` comment is updated: keep the `FR-011 / FR-012` portion (those land in S-05..S-08) and remove `FR-005 / FR-006` since this slice closes them. Replace with a forward-pointer to S-05.
- Module docstring at `app.py:1-12` is unchanged (still accurate).
- The `_settings_path` helper is removed if its only call site was the placeholder.

**Import delta**: add `from break_reminder.ui.settings_dialog import SettingsDialog` to the top-of-file imports. `QMessageBox` import stays (still used by the no-tray-detected branch at `app.py:393`).

#### 2. Update `tests/test_app.py`

**File**: `tests/test_app.py`

**Intent**: Add a test class `TestOpenSettingsAction` that exercises the new slot wiring. Use `monkeypatch` to swap `SettingsDialog.exec` with a no-op stub so the test doesn't actually pump a modal event loop. Assert that calling the action constructs a `SettingsDialog`. Existing `TestTrayMenuWiring` cases remain unchanged.

**Contract**:

- New test: `test_open_settings_action_constructs_settings_dialog` — monkeypatches `break_reminder.ui.settings_dialog.SettingsDialog.exec` to record the call and return `QDialog.DialogCode.Rejected`, triggers the "Open settings…" action via the existing `_find_action` helper, asserts the patched exec was called exactly once.
- New test: `test_open_settings_no_longer_shows_message_box` — monkeypatches `PySide6.QtWidgets.QMessageBox.information` to raise `AssertionError` (or sets a flag), triggers the action, asserts the placeholder path is dead.
- New test: `test_settings_dialog_receives_app_settings_instance` — monkeypatches the `SettingsDialog.__init__` to capture its `settings` kwarg, triggers the action, asserts the captured object is `app._settings` (identity check). Tripwire if a future refactor accidentally constructs a duplicate `Settings`.
- Reuse the existing `app` fixture from `tests/test_app.py:65-79` — already wired against `tmp_path`.

#### 3. Update PRD reference annotation (optional)

**File**: `context/foundation/prd.md`

**Intent**: If the PRD has a "Status by FR" or similar table tracking which FRs ship in which version, mark FR-005 and FR-006 as **shipped in v0.2.0**. Skip if no such table exists.

**Contract**: Conditional on PRD shape. If skipped, this is captured by the roadmap update in the closeout instead.

### Success Criteria:

#### Automated Verification:

- Updated tests pass: `uv run pytest tests/test_app.py`
- Full suite still passes: `uv run pytest`
- Type check passes: `uv run pyright break_reminder/app.py tests/test_app.py`
- Lint passes: `uv run ruff check break_reminder/app.py tests/test_app.py`
- Format check passes: `uv run ruff format --check break_reminder/app.py tests/test_app.py`

#### Manual Verification:

- The "Open settings…" tray menu item opens the new modal dialog (NOT the `QMessageBox` placeholder).
- A left-click on the tray icon also opens the new dialog (via `_on_tray_activated`).
- The spinbox is pre-populated with the current `break_interval_min` value (verify against `BreakReminder.ini` opened in Notepad).
- Editing the spinbox to a new value (e.g., 30) and clicking **OK** closes the dialog and persists the value to the INI on disk.
- Within ≤1 second of clicking OK, the tray tooltip's countdown reflects the new interval (because `BreakScheduler._tick` reads `Settings.snapshot()` every tick).
- Clicking **Cancel** after editing closes the dialog and leaves the INI value unchanged (verify by reopening settings — the original value is shown).
- Quitting the app and restarting persists the last saved value (the spinbox shows the saved value on the next "Open settings…" click).
- The spinbox does not allow values below 1 or above 240 (typing 0 / 999 is clamped at the widget level — the value never reaches the `Settings` setter).

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation that the smoke-test checklist above all passes before declaring the slice done. The slice is complete only after the manual smoke confirms; the roadmap entry then flips from `ready` → `done` and the change folder is eligible for `/10x-archive`.

---

## Testing Strategy

### Unit Tests:

- `SettingsDialog` load behavior — spinbox initial value, bounds, label text, tab structure.
- `SettingsDialog` save behavior — OK persists, Cancel discards, persistence is observable across fresh `Settings` instances.
- `_on_open_settings` slot wiring — the new dialog is constructed with the app's `Settings` instance; the placeholder code path is dead.
- Existing tray-menu wiring tests in `TestTrayMenuWiring` still pass unchanged (the action label "Open settings…" doesn't move).

### Integration Tests:

- (None added — the dialog is invoked synchronously from a Qt slot; no inter-process or inter-thread coordination needs end-to-end coverage. The unit tests + manual smoke covers the integration surface.)

### Manual Testing Steps:

1. Run the app from source: `uv run python -m break_reminder` (or run the installed `BreakReminder.exe` from the previous v0.1.0 install for a closer-to-production smoke).
2. Right-click the tray icon → "Open settings…". Confirm a real `QDialog` titled "Settings" opens (not the `QMessageBox` placeholder).
3. The dialog has a tab labelled "Scheduling" with a spinbox labelled "Break interval (minutes)" pre-filled with the current value.
4. Change the value to **2** (deliberately short for fast smoke). Click **OK**. The dialog closes.
5. Open `%APPDATA%\BreakReminder\BreakReminder.ini` in Notepad. Confirm the `break_interval_min=2` line is present under `[scheduling]`.
6. Watch the tray tooltip — within ~1 second the countdown reflects the new 2-minute interval. (May require focusing another window to trigger a tooltip refresh.)
7. Wait ≤2 minutes of active input → the break dialog fires per the new interval.
8. Click "Open settings…" again. Confirm the spinbox shows the persisted value (2).
9. Change to 60. Click **Cancel**. Confirm the INI still shows `2` and the next break still uses 2.
10. Click "Open settings…" again. Click **OK** without changing anything. Confirm the value is still 2 and no harm came of it.
11. Try the spinbox arrows: decrement past 1 — confirm it clamps at 1. Increment past 240 — confirm it clamps at 240. Type "0" — confirm it clamps to 1. Type "999" — confirm it clamps to 240.
12. Quit the app via the tray "Quit" item. Restart. Confirm the saved value persists (open settings → spinbox shows 2).
13. Restore the original interval (60) before ending the smoke.

## Performance Considerations

None. The dialog is a few `QWidget` instances and a single `QSettings.value()` read on construction; total cost under 1 ms. The save path is one `QSettings.setValue` and the existing `BreakScheduler._tick` already reads `Settings.snapshot()` every second, so the new value propagates without any added work.

## Migration Notes

None — no data migration. Existing `BreakReminder.ini` files from v0.1.0 are read unchanged by `Settings.break_interval_min`, since the key (`scheduling/break_interval_min`) is unchanged. Users with no INI file (e.g., first launch) get the `DEFAULT_BREAK_INTERVAL_MIN` value (60) shown in the spinbox, which matches v0.1.0's tooltip default — no observable behavior change at first open.

## References

- Roadmap entry: `context/foundation/roadmap.md` § S-01 (settings-window-break-interval-only)
- PRD: `context/foundation/prd.md` § FR-005, § FR-006
- Tech-stack notes: `context/foundation/tech-stack.md` "Known stubs" — settings dialog placeholder
- Lessons: `context/foundation/lessons.md` (Google-style docstrings rule applies to all new public functions in this slice)
- Code template (closest pattern): `break_reminder/notifications/reminder_dialog.py:24-55`
- Settings persistence layer: `break_reminder/storage/settings.py:108-117`
- Slot to replace: `break_reminder/app.py:278-288`
- Test conventions: `tests/test_settings.py` (round-trip patterns), `tests/test_app.py:208-215` (`_find_action` helper, `qapp` fixture usage)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See the skill's `references/progress-format.md`.

### Phase 1: Build SettingsDialog in isolation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_settings_dialog.py` — eaa1b69
- [x] 1.2 Full suite still passes: `uv run pytest` — eaa1b69
- [x] 1.3 Type check passes: `uv run pyright break_reminder/ui/ tests/test_settings_dialog.py` — eaa1b69
- [x] 1.4 Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/ui/ tests/test_settings_dialog.py` — eaa1b69
- [x] 1.5 Format check passes: `uv run ruff format --check break_reminder/ui/ tests/test_settings_dialog.py` — eaa1b69
- [x] 1.6 `python -c "from break_reminder.ui.settings_dialog import SettingsDialog"` does not raise. — eaa1b69

### Phase 2: Wire the dialog into the tray menu

#### Automated

- [x] 2.1 Updated tests pass: `uv run pytest tests/test_app.py`
- [x] 2.2 Full suite still passes: `uv run pytest`
- [x] 2.3 Type check passes: `uv run pyright break_reminder/app.py tests/test_app.py`
- [x] 2.4 Lint passes: `uv run ruff check break_reminder/app.py tests/test_app.py`
- [x] 2.5 Format check passes: `uv run ruff format --check break_reminder/app.py tests/test_app.py`

#### Manual

- [x] 2.6 The "Open settings…" tray menu item opens the new modal dialog (NOT the `QMessageBox` placeholder).
- [x] 2.7 A left-click on the tray icon also opens the new dialog.
- [x] 2.8 The spinbox is pre-populated with the current `break_interval_min` value (cross-checked against `BreakReminder.ini`).
- [x] 2.9 Editing the spinbox to a new value and clicking OK closes the dialog and persists the value to the INI.
- [x] 2.10 Within ≤1 second of clicking OK, the tray tooltip's countdown reflects the new interval.
- [x] 2.11 Clicking Cancel after editing closes the dialog and leaves the INI value unchanged.
- [x] 2.12 Quitting and restarting the app persists the last saved value.
- [x] 2.13 The spinbox does not allow values below 1 or above 240 at the widget level.
