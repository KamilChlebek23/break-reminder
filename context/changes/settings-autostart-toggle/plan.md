# Settings Autostart Toggle Implementation Plan

## Overview

Wire the FR-003 Windows-autostart toggle end-to-end so it actually fires the per-user Run-key registry write that v0.1.0 left as a stub. The user opens Settings, switches to a new "Lifecycle" tab, ticks "Launch BreakReminder at Windows login", clicks OK; the dialog issues an idempotent write to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\BreakReminder` whose data is the quoted absolute path to `sys.executable`. On next Windows login, BreakReminder appears in the tray without manual launch. Unticking + OK deletes the same value. On winreg failure the dialog surfaces a transient `QToolTip` on the checkbox and blocks the entire save (extending the S-03 impl-review F2 atomic-save invariant to a fourth field). Last slice of Stream A on the roadmap.

## Current State Analysis

The persistence layer is half-wired today; the effect layer is empty.

**Wired (do not duplicate):**

- `DEFAULT_AUTOSTART = False` — `break_reminder/storage/settings.py:52`
- `_Keys.AUTOSTART = "lifecycle/autostart"` — `break_reminder/storage/settings.py:65`
- `Snapshot.autostart: bool` — `break_reminder/storage/settings.py:79`
- `Settings.autostart` getter (read-only) — `break_reminder/storage/settings.py:274-277`

**Missing:**

- `Settings.autostart` setter — every other persisted field has one (`voice_enabled.setter`, `voice_phrase.setter`, `paused.setter`, `break_interval_min.setter`, `snooze_duration_min.setter`, `max_snoozes.setter`); autostart is the only one without.
- Any `winreg` import or Run-key code anywhere in `break_reminder/` (verified via grep).
- Any UI affordance — `SettingsDialog` has two tabs (Scheduling, Notifications); no "Lifecycle" surface yet.
- The line "Autostart toggle (FR-003). The settings key is wired; the registry write is not." in `context/foundation/tech-stack.md:91` and the matching line in `AGENTS.md:186`.

**Constraints discovered:**

- Per-user Run-key writes don't need elevation, so no UAC prompt — matches the FR-003 "user opts in via the settings panel" wording.
- The NSIS installer deliberately does **not** write a Run-key (`installer/break-reminder.nsi`, documented in `tech-stack.md:71`: "No Run-key (autostart is opt-in per FR-003)"). This invariant must hold.
- PRD "Update safety" NFR (line 146): "An in-place update of BreakReminder preserves all user state and does not silently change any user-configured value (... autostart toggle)". Because the NSIS per-user install puts the binary at a stable per-user path, `sys.executable` survives in-place upgrades — the Run-key value remains valid without rewriting.
- The entire app is Windows-only by design (FR-001), so `import winreg` at module top is safe; no platform guard needed.

## Desired End State

A user who has never opened the dialog sees autostart unchecked (default `False`). A user who ticks the new checkbox and clicks OK:

1. Sees the Run-key entry appear in `regedit` at `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` with value name `BreakReminder` and string data `"<sys.executable>"`.
2. After logging out and back in, sees the BreakReminder tray icon appear without manual launch.
3. Reopens Settings → Lifecycle tab and sees the checkbox still ticked (loaded from INI; INI-as-intent invariant).

A user who unticks + OK sees the Run-key value disappear; the next login does not auto-launch the app. A user on a locked-down machine where the registry write fails sees a transient `QToolTip` on the autostart checkbox ("Could not update Windows autostart — try running BreakReminder once as your normal user.") and the dialog stays open with all fields untouched (atomic save).

`tech-stack.md` and `AGENTS.md` no longer list autostart in their "Known stubs" sections; `README.md`'s Settings-dialog bullet mentions the autostart affordance.

### Key Discoveries:

- `Settings.autostart` getter exists with no setter (`break_reminder/storage/settings.py:274-277`); this is the only persisted field in the class without a setter. Adding one mirrors `voice_enabled.setter` exactly (`break_reminder/storage/settings.py:230-240`).
- The dialog's existing builder pattern is `_build_<tab-name>_tab() -> QWidget` returning a `QWidget` populated with a `QFormLayout` (`break_reminder/ui/settings_dialog.py:177-200` for `_build_scheduling_tab`). A new `_build_lifecycle_tab()` of the same shape adds the third tab in one constructor line.
- The S-04 voice-empty-phrase atomic-save tripwire lives at `tests/test_settings_dialog.py::TestNotificationsTabValidation::test_voice_on_blank_phrase_blocks_save` and was extended in S-03 impl-review F2 to assert that `break_interval_min`, `snooze_duration_min`, and `max_snoozes` are all unchanged when validation trips. Extending it to assert `autostart` is also unchanged keeps the invariant complete.
- The S-04 transient-tooltip pattern (`QToolTip.showText` anchored on a widget) is at `break_reminder/ui/settings_dialog.py` in `accept()` for the voice-empty-phrase gate. Reusing the same `_anchor_tooltip_below(widget, message)` helper (or pattern) is the clean precedent.

## What We're NOT Doing

- **No `AutostartManager` module / no `lifecycle/` Python package**. The two thin module-level helpers live in `settings_dialog.py`. If a second autostart caller ever appears (e.g., a startup self-heal reconciler, or a cross-platform port), extracting them into `break_reminder/lifecycle/autostart.py` is a clean future move — but YAGNI today. (Decision: encapsulation question, round 1.)
- **No NSIS installer changes**. The installer continues to NOT write a Run-key — autostart must be opt-in per FR-003. Tech-stack.md's "No Run-key" invariant stands. (Confirms: tech-stack.md:71.)
- **No Run-key reconciliation at app startup**. The INI is the user's intent; the registry is OS state. If a user manually deletes the Run-key in `regedit`, the next OK in Settings re-issues it idempotently; the app does not self-heal at boot. (Decision: drift-policy question, round 2.)
- **No source-run autostart support**. `sys.executable` for a `uv run break_reminder.app` invocation points at the python interpreter, which would launch into a REPL on login, not the app. Source-run dev workflow doesn't need autostart; production is the PyInstaller-frozen binary at a stable per-user install path. (Decision: runkey-value question, round 2.)
- **No reading from the registry for the initial checkbox state**. The dialog populates from `Settings.autostart` (INI), not by querying the registry. Inverting the storage model for one field would clash with the INI-is-source-of-truth invariant the codebase has held since `tech-stack.md:67`.
- **No CLI flags for the launched binary**. The Run-key value is just `"<sys.executable>"` with no arguments — the app already starts minimized to tray and presents no visible UI on launch, so a `--start-minimized` flag is unnecessary. Adding one would create a v0.5.0 → v0.6.0 backward-compat surface that's not earning its keep.
- **No DI / `RunKeyWriter` Protocol**. The chosen encapsulation (round 1) and testing approach (round 2) keep the surface to two module-level helpers monkeypatched in tests. No constructor parameter is added to `SettingsDialog`.
- **No "show this PC's startup folder in Explorer" affordance**. The PRD spec is a checkbox, not a power-user discoverability tool.
- **No unit-test coverage for the actual real-world Windows-login boot of the app**. That requires logout/login by a human and lives in the manual-smoke checklist (Phase 2).

## Implementation Approach

The slice is shaped like S-04 (voice toggle) — a checkbox that triggers a side-effect against an external system (voice synthesizer ↔ Windows registry). One source file gains a setter (`storage/settings.py`); one gains a new tab + two helpers + four lines in `accept()` (`ui/settings_dialog.py`); two test files gain new classes. No new modules, no new packages.

The sequence in `SettingsDialog.accept()` becomes:

1. **Validation first** (existing voice-empty-phrase gate — unchanged).
2. **Side-effect second** — read the autostart checkbox; call `_write_autostart_runkey(quoted_command)` if checked, `_delete_autostart_runkey()` if unchecked. Wrap in `try/except OSError` (catches `PermissionError`, `FileNotFoundError`, generic `OSError`). On exception, anchor a `QToolTip` on the autostart checkbox and `return` without calling any setter — atomic save.
3. **Persist third** — write all four field setters (`break_interval_min`, `snooze_duration_min`, `max_snoozes`, `voice_enabled`/`voice_phrase`, `autostart`). Order doesn't matter at this point because the side-effect already succeeded.
4. **`super().accept()`** — close the dialog.

The "side-effect before INI write" ordering is deliberate: if the registry write fails, we want zero state changes (atomic). If we wrote the INI first and then the registry failed, the user would reopen the dialog to find autostart="True" but no actual autostart. With this ordering, both INI and registry stay synchronized at every successful save.

The two helpers are stateless and idempotent:

- `_write_autostart_runkey(command: str) -> None` — opens the Run subkey under HKCU with `KEY_SET_VALUE`, calls `winreg.SetValueEx(key, "BreakReminder", 0, winreg.REG_SZ, command)`, closes. Re-issuing with the same command is a no-op for the OS.
- `_delete_autostart_runkey() -> None` — opens with `KEY_SET_VALUE`, calls `winreg.DeleteValue(key, "BreakReminder")`, catches `FileNotFoundError` (the value doesn't exist) and treats it as success. Closes the key in a `finally`.

Tests monkeypatch these two helpers at module scope to assert the dialog calls them with the right arguments without poking the real registry. A small separate test class monkeypatches `winreg.OpenKey` / `SetValueEx` / `DeleteValue` to verify the helpers themselves.

## Critical Implementation Details

- **Run-key value name & subkey** — the value name is `BreakReminder` (matches the existing `APPLICATION_NAME` constant); the subkey is the per-user `Software\Microsoft\Windows\CurrentVersion\Run` under `HKEY_CURRENT_USER`. The per-machine equivalent (`HKLM`) is deliberately NOT used — that requires elevation and would break the FR-003 "user opts in via the settings panel" UX.
- **Run-key value data must be quoted** — `command = f'"{sys.executable}"'`. Without the surrounding double quotes, `%LOCALAPPDATA%\Programs\BreakReminder\BreakReminder.exe` (the production install path) survives because there's no space in `Programs`, but `%LOCALAPPDATA%\Programs\Break Reminder\...` (or any future path with spaces) would break Windows' shell parsing of the Run value. Quoting now is cheap insurance.
- **Atomic save ordering** — call the winreg helper BEFORE writing any INI value. If the helper raises `OSError`, no INI is written. If the helper succeeds, all four INI fields write. This preserves the S-03 impl-review F2 invariant ("OK saves everything or nothing") across the new field.
- **Idempotent delete** — `_delete_autostart_runkey()` MUST catch `FileNotFoundError` and return silently. Without this, an untick-then-ok on a system that never had the Run-key entry (e.g., fresh install, never autostarted) would raise. The corresponding test asserts the `FileNotFoundError` path returns normally.
- **Helper-level `try/finally`** — `winreg.OpenKey` returns a handle that must be closed even on exception. Use `with winreg.OpenKey(...) as key:` (the handle is a context manager since Python 3.6).

## Phase 1: Implementation

### Overview

Add the `Settings.autostart` setter, build the new "Lifecycle" tab with its single autostart checkbox, drop the two thin winreg helpers into `settings_dialog.py`, wire `accept()` for the atomic side-effect-then-persist flow, and ship full unit-test coverage. Single commit. No user-visible UX change beyond the new tab + checkbox + working autostart.

### Changes Required:

#### 1. Persistence-layer setter

**File**: `break_reminder/storage/settings.py`

**Intent**: Add the missing `Settings.autostart` setter so the dialog's `accept()` can persist the checkbox state through the same idiom every other field uses. Keeps the persistence layer's invariant that all persisted fields go through getter+setter pairs (no `_qs.setValue` poking from the UI layer).

**Contract**: `@autostart.setter def autostart(self, value: bool) -> None` immediately below the existing `autostart` getter (line 274-277). Coerce via `bool(value)` for symmetry with the other bool setters (`voice_enabled`, `paused`). Google-style docstring per `context/foundation/lessons.md`. No `ValueError` branch — booleans don't have a "corrupt input" mode the way ints do, so the setter is unconditional like `voice_enabled.setter`.

#### 2. Lifecycle tab + checkbox in the dialog

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Add a third tab labeled "Lifecycle" containing a single `QCheckBox` for autostart. The tab is built by a new `_build_lifecycle_tab() -> QWidget` method following the same `_build_<name>_tab()` pattern as `_build_scheduling_tab()` and `_build_notifications_tab()`. Pre-populate the checkbox state from `self._settings.autostart`. Add a `LIFECYCLE_TAB_LABEL = "Lifecycle"` class-level constant alongside `SCHEDULING_TAB_LABEL` and `NOTIFICATIONS_TAB_LABEL` for consistency.

**Contract**: New method `_build_lifecycle_tab(self) -> QWidget`. New attribute `self._autostart_checkbox: QCheckBox`. New constant `LIFECYCLE_TAB_LABEL`. Constructor's tab-construction block adds one line: `self._tabs.addTab(self._build_lifecycle_tab(), self.LIFECYCLE_TAB_LABEL)`. Checkbox text: `"Launch BreakReminder at Windows login"` (matches roadmap S-02 wording verbatim).

#### 3. winreg helpers (module-level)

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Encapsulate the two registry side-effects as module-level functions (not methods) so tests can `monkeypatch.setattr("break_reminder.ui.settings_dialog._write_autostart_runkey", stub)` and capture call args without touching `winreg`. Keeps OS I/O at the dialog-module boundary (per the chosen "inline winreg in dialog" encapsulation) without scattering it through `accept()`.

**Contract**: Two module-level functions and three module-level constants:

```python
_AUTOSTART_RUNKEY_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_VALUE_NAME = "BreakReminder"
_AUTOSTART_FAILURE_MESSAGE = "Could not update Windows autostart — try running BreakReminder as your normal user."

def _write_autostart_runkey(command: str) -> None: ...
def _delete_autostart_runkey() -> None: ...
```

`_write_autostart_runkey` opens `HKCU\<subkey>` with `winreg.KEY_SET_VALUE`, calls `winreg.SetValueEx(key, _AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, command)`. `_delete_autostart_runkey` opens with the same access, calls `winreg.DeleteValue(key, _AUTOSTART_VALUE_NAME)`, catches `FileNotFoundError` and returns silently (idempotent). Both use `with winreg.OpenKey(...)` for handle cleanup. Both let `OSError` / `PermissionError` propagate to the caller (the dialog's `accept()` catches them).

#### 4. accept() wiring (atomic side-effect → INI write)

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: After the existing voice-empty-phrase validation gate (which already returns early without saving), compute `command = f'"{sys.executable}"'` and call `_write_autostart_runkey(command)` or `_delete_autostart_runkey()` based on `self._autostart_checkbox.isChecked()`. Wrap in `try/except OSError`; on exception anchor a `QToolTip` on `self._autostart_checkbox` with `_AUTOSTART_FAILURE_MESSAGE`, switch to the Lifecycle tab so the tooltip is visible, and `return` without writing any setter. On success, fall through to the existing block that writes break-interval / snooze / voice setters, and add `self._settings.autostart = self._autostart_checkbox.isChecked()` alongside them.

**Contract**: One added `import sys` at module top. `accept()`'s docstring extended to mention the new gate. The order in `accept()` is fixed: voice-empty validation → autostart side-effect → INI writes → `super().accept()`. Switching the tab on failure (via `self._tabs.setCurrentWidget(self._lifecycle_tab)`) mirrors the S-04 pattern of switching to the Notifications tab before anchoring the voice-empty tooltip (see `context/changes/settings-voice-toggle/reviews/impl-review.md` F1 fix).

#### 5. Persistence-layer tests — new classes

**File**: `tests/test_settings.py`

**Intent**: Cover the new setter with the same shape as `TestSnoozeSettersRoundTrip` and `TestSnoozeValidation` — round-trip, default, persistence-across-instances. Bool setters don't need the `ValueError` validation tests that int setters need.

**Contract**: New class `TestAutostartSetterRoundTrip` with three tests:

- `test_setter_persists_true_round_trip`
- `test_setter_persists_false_round_trip`
- `test_setter_coerces_truthy_input` (asserts a non-bool input writes the canonical `bool` to INI, mirroring `voice_enabled.setter`'s `bool(value)` coercion)

#### 6. Dialog tests — Lifecycle tab structure

**File**: `tests/test_settings_dialog.py`

**Intent**: Assert the Lifecycle tab exists, has the right label, contains the autostart checkbox with the expected text, and pre-populates from `Settings.autostart`. Mirrors the existing `TestLayout` and `TestLoad` patterns.

**Contract**: Extend `TestLayout` with one test asserting the dialog has three tabs and the third one is labeled `"Lifecycle"`. Extend `TestLoad` with three tests:

- `test_autostart_checkbox_unchecked_when_setting_false`
- `test_autostart_checkbox_checked_when_setting_true`
- `test_autostart_checkbox_label_matches_roadmap_wording` (asserts the checkbox text is exactly `"Launch BreakReminder at Windows login"`).

#### 7. Dialog tests — save flow with mocked helpers

**File**: `tests/test_settings_dialog.py`

**Intent**: Verify the dialog's `accept()` invokes the right helper with the right argument, persists the INI value, and switches the tab on failure. Tests monkeypatch `_write_autostart_runkey` and `_delete_autostart_runkey` to a capture-stub instead of the real winreg.

**Contract**: New test class `TestAutostartTabSave` with five tests:

- `test_check_and_ok_writes_runkey_with_quoted_executable` — asserts `_write_autostart_runkey` was called once with `f'"{sys.executable}"'` and `Settings.autostart` is now `True` after `accept()`.
- `test_uncheck_and_ok_deletes_runkey` — asserts `_delete_autostart_runkey` was called once and `Settings.autostart` is now `False`.
- `test_no_change_still_idempotently_re_issues` — asserts that opening the dialog with autostart=True and clicking OK without changing the checkbox still calls `_write_autostart_runkey` (idempotent re-issue per the no-reconciliation policy).
- `test_runkey_helper_oserror_blocks_save_and_anchors_tooltip` — monkeypatches the helper to raise `OSError`; asserts no INI fields were modified, the dialog stayed open, and the active tab switched to Lifecycle. Use `qtbot.waitSignal` patterns from existing tests.
- `test_runkey_helper_permissionerror_also_blocks_save` — same as above with `PermissionError` (subclass of `OSError`); asserts the same atomic-save behavior.

#### 8. Dialog tests — winreg helper internals

**File**: `tests/test_settings_dialog.py`

**Intent**: Cover the two helpers themselves by monkeypatching `winreg.OpenKey` / `SetValueEx` / `DeleteValue`. These tests don't go through the dialog at all — they import the helpers directly.

**Contract**: New test class `TestRunkeyHelpers` with four tests:

- `test_write_helper_calls_set_value_ex_with_correct_args` — monkeypatches `winreg.OpenKey` to return a fake key handle and `winreg.SetValueEx` to capture; asserts the call was `(key, "BreakReminder", 0, winreg.REG_SZ, command)`.
- `test_write_helper_uses_hkcu_run_subkey` — asserts the open call was against `winreg.HKEY_CURRENT_USER` and the documented subkey path.
- `test_delete_helper_calls_delete_value` — asserts `winreg.DeleteValue` was called with the right value name.
- `test_delete_helper_swallows_filenotfounderror` — monkeypatches `winreg.DeleteValue` to raise `FileNotFoundError`; asserts the helper returns normally (no re-raise).

#### 9. Atomic-save tripwire — extend voice-empty test

**File**: `tests/test_settings_dialog.py`

**Intent**: The existing `test_voice_on_blank_phrase_blocks_save` (extended in S-03 impl-review F2 to cover all three Scheduling fields) gets one more assertion: `autostart` is also unchanged when the voice gate trips. This locks the atomic-save invariant across all four user-configurable fields.

**Contract**: Add a single assertion `assert settings.autostart == initial_autostart_value` to the existing test in `TestNotificationsTabValidation::test_voice_on_blank_phrase_blocks_save`. Update the test's docstring to mention the four fields. No new test class.

#### 10. Documentation — drop the autostart stub line

**File**: `context/foundation/tech-stack.md`

**Intent**: Remove the line "Autostart toggle (FR-003). The settings key is wired; the registry write is not." from the "Known stubs" section now that the registry write actually fires.

**Contract**: Single-line deletion at `context/foundation/tech-stack.md:91`. The surrounding bullets are unaffected.

#### 11. Documentation — drop the autostart stub line (AGENTS.md)

**File**: `AGENTS.md`

**Intent**: Same deletion as above for the matching pending list line.

**Contract**: Single-line deletion at `AGENTS.md:186` ("Autostart toggle (FR-003) — reads from settings but the registry write is stubbed."). Update the surrounding paragraph if it now reads awkwardly.

#### 12. README — Settings dialog bullet

**File**: `README.md`

**Intent**: Add a brief mention of the autostart affordance in the Settings dialog feature bullet (or wherever the Scheduling/Notifications tabs are listed) so users discover the feature without reading the PRD.

**Contract**: One-sentence amendment to the existing Settings-dialog bullet describing the Lifecycle tab and its autostart checkbox. Wording aligned with FR-003: "tick to launch BreakReminder automatically at Windows login (default off)."

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest`
- Type checking passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Formatting passes: `uv run ruff format --check`

#### Manual Verification:

(Phase 2 owns these — Phase 1 is complete when all automated gates above are green.)

**Implementation Note**: After Phase 1 lands, pause for manual confirmation that the smoke checklist in Phase 2 is green before flipping `change.md` status to `implemented`. Phase blocks use plain bullets; the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Manual smoke + bookkeeping

### Overview

Run the manual smoke checklist on the actual Windows machine (Phase 1 only proves the code paths in tests; this phase proves them on a real OS), then update the cross-references that point at this slice — `change.md`, the roadmap, and tick the Progress section.

### Changes Required:

#### 1. Manual smoke (no code changes; verification only)

**Intent**: Prove the slice on a real Windows install. Each step below MUST be observed with eyes-on-screen — no code can verify these.

**Contract**: Run the Manual Verification checklist below. If any step fails, return to Phase 1 with a fix; do not flip `change.md` to `implemented`.

#### 2. Slice metadata — flip status

**File**: `context/changes/settings-autostart-toggle/change.md`

**Intent**: Mark the slice as shipped end-to-end (code + smoke).

**Contract**: Change `status: planned` → `status: implemented`. Bump `updated:` to today.

#### 3. Roadmap — flip S-02 to done

**File**: `context/foundation/roadmap.md`

**Intent**: Reflect that S-02 is shipped and Stream A is now complete. Update the "At a glance" table, the S-02 detail block, the Backlog Handoff row, and the Stream A summary.

**Contract**: Three locations in `context/foundation/roadmap.md`:

- "At a glance" table row for S-02: status `proposed` → `done`.
- S-02 detail block: `Status: proposed` → `Status: done`. Outcome line gets a brief "Shipped 2026-05-26 — see context/changes/settings-autostart-toggle/" annotation, matching the S-03 pattern at line 110.
- Backlog Handoff row for S-02: `Ready for /10x-plan: no` → `Ready for /10x-plan: yes`. Notes column updated to "Planned + shipped 2026-05-26", matching the S-03/S-04 row format.
- Front-matter `updated:` bumped to today.

#### 4. Progress checkboxes

**File**: `context/changes/settings-autostart-toggle/plan.md`

**Intent**: Tick each row in the `## Progress` section as the corresponding step lands. Append the commit SHA to each ticked row per the convention.

**Contract**: Per `context/changes/settings-snooze-config/plan.md`'s pattern — `- [x] 1.1 <title> — <short-sha>`. Phase 1's checkboxes get the Phase 1 commit SHA; Phase 2's checkboxes get the Phase 2 commit SHA. Do not rename the step titles.

### Success Criteria:

#### Automated Verification:

- All Phase 1 automated gates remain green: `uv run pytest && uv run pyright && uv run ruff check && uv run ruff format --check`.
- `git status` is clean after the bookkeeping commit.

#### Manual Verification:

- Open Settings → "Lifecycle" tab is visible as the third tab; contains a single checkbox labeled "Launch BreakReminder at Windows login"; checkbox starts unchecked on a fresh install.
- Tick the checkbox → click OK → reopen Settings → checkbox is still ticked (loaded from INI).
- Open `regedit` → `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` → confirm a `BreakReminder` value exists with data `"<full path to BreakReminder.exe or python interpreter>"` (double-quoted).
- Log out of Windows → log back in → BreakReminder tray icon appears within ~5 seconds without manual launch.
- Open Settings → untick the checkbox → click OK → confirm the `BreakReminder` value is gone from `regedit`.
- Log out → log back in → confirm BreakReminder does NOT auto-launch.
- (Drift policy check) Tick + OK → manually delete the `BreakReminder` value in `regedit` → reopen Settings → checkbox is still shown as ticked (per "no reconciliation: INI is intent") → click OK → confirm the value is restored in `regedit`.
- (Atomic save check) Tick the autostart checkbox AND clear the voice phrase while voice is enabled → click OK → confirm the dialog stays open (voice gate trips first), the autostart Run-key was NOT written, and the autostart INI value did NOT change.
- (Update safety NFR check) Verify in NSIS that an in-place upgrade does not modify the Run-key. Skip the full release-and-reinstall cycle if the next release isn't due; document that the path-based invariant is preserved (`sys.executable` resolves to the same per-user install path before and after upgrade).

**Implementation Note**: Once all manual checks above are green, commit the Phase 2 bookkeeping (status flip + roadmap update + Progress ticks) as a single small commit with subject like `chore(settings-autostart-toggle): mark S-02 done`. Then surface the slice for `/10x-impl-review`.

---

## Testing Strategy

### Unit Tests:

- **Persistence layer** (`tests/test_settings.py`):
  - Setter round-trips for `True` and `False`.
  - Setter coerces non-bool inputs via `bool(value)` (mirrors `voice_enabled.setter`).
  - Default returns `False` when no INI value exists (already covered by the existing `Snapshot` test; just confirm).

- **Dialog layout** (`tests/test_settings_dialog.py`):
  - Three tabs exist; third one is labeled "Lifecycle".
  - Lifecycle tab contains the autostart checkbox with the exact label "Launch BreakReminder at Windows login".

- **Dialog load** (`tests/test_settings_dialog.py`):
  - Checkbox unchecked when `Settings.autostart == False`.
  - Checkbox checked when `Settings.autostart == True`.

- **Dialog save** (`tests/test_settings_dialog.py`, helper-monkeypatched):
  - Tick + OK → `_write_autostart_runkey` called once with `f'"{sys.executable}"'` and `Settings.autostart == True`.
  - Untick + OK → `_delete_autostart_runkey` called once and `Settings.autostart == False`.
  - No-checkbox-change + OK → still re-issues the helper (idempotent).
  - Helper raises `OSError` → no INI fields modified, dialog stays open, active tab is Lifecycle.
  - Helper raises `PermissionError` → same atomic-save guarantee as `OSError`.

- **Helper internals** (`tests/test_settings_dialog.py`, winreg-monkeypatched):
  - `_write_autostart_runkey` calls `winreg.SetValueEx` with `(key, "BreakReminder", 0, REG_SZ, command)`.
  - Both helpers open against `HKCU` + the documented subkey path.
  - `_delete_autostart_runkey` calls `winreg.DeleteValue` with the right value name.
  - `_delete_autostart_runkey` swallows `FileNotFoundError`.

- **Atomic-save tripwire** (`tests/test_settings_dialog.py`):
  - Existing `test_voice_on_blank_phrase_blocks_save` extended: `autostart` is also unchanged when the voice gate trips.

### Integration Tests:

None new — the slice is fully covered by the unit-test surface above. The actual Windows-login boot of the app is verified manually in Phase 2.

### Manual Testing Steps:

See Phase 2's Manual Verification checklist — eight items covering happy path, untick path, drift-policy round-trip, atomic-save interaction with the voice gate, and the update-safety NFR.

## Performance Considerations

The winreg call is one open-set-close (or open-delete-close) round-trip on every OK click — submillisecond against the live registry. No caching, no batching, no concern. The dialog flow already does an INI write on every OK; adding a registry write is the same order of magnitude.

## Migration Notes

None — `Settings.autostart` already returns `False` for any user with no INI value (the default), so the world-state delta for existing users is zero until they explicitly tick the new checkbox. No migration script, no INI mutation on first launch.

## References

- Roadmap: `context/foundation/roadmap.md` (S-02 detail block, lines 96-106)
- PRD: `context/foundation/prd.md` (FR-003, line 95-96; "Update safety" NFR, line 146)
- Tech-stack baseline: `context/foundation/tech-stack.md` (line 67 for INI invariant; line 71 for "No Run-key" installer invariant; line 91 for the stub line being closed)
- AGENTS.md pending list: `AGENTS.md:186` (the matching stub line)
- Closest precedent: `context/changes/settings-voice-toggle/plan.md` (S-04 — checkbox + side-effect against external system; same atomic-save pattern)
- Atomic-save pattern: `context/changes/settings-snooze-config/reviews/impl-review.md` (F2 — extending `test_voice_on_blank_phrase_blocks_save` to all persisted fields)
- Persistence-layer setter idiom: `break_reminder/storage/settings.py:230-240` (`voice_enabled.setter`)
- Lessons file: `context/foundation/lessons.md` (Google-style docstrings)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Implementation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest`
- [x] 1.2 Type checking passes: `uv run pyright`
- [x] 1.3 Linting passes: `uv run ruff check`
- [x] 1.4 Formatting passes: `uv run ruff format --check`

### Phase 2: Manual smoke + bookkeeping

#### Automated

- [ ] 2.1 All Phase 1 automated gates remain green
- [ ] 2.2 `git status` is clean after the bookkeeping commit

#### Manual

- [ ] 2.3 Lifecycle tab visible with single autostart checkbox; default unchecked on fresh install
- [ ] 2.4 Tick + OK → reopen → checkbox still ticked
- [ ] 2.5 `regedit` confirms `BreakReminder` value with quoted executable path
- [ ] 2.6 Logout/login → tray icon appears without manual launch
- [ ] 2.7 Untick + OK → `BreakReminder` value gone from `regedit`
- [ ] 2.8 Logout/login → app does NOT auto-launch
- [ ] 2.9 Drift-policy round-trip: manual regedit delete → reopen Settings → still ticked → OK restores
- [ ] 2.10 Atomic save: voice-empty + autostart-tick on same OK → autostart INI unchanged, no Run-key write
- [ ] 2.11 Update-safety NFR confirmed (in-place install does not modify the Run-key)
