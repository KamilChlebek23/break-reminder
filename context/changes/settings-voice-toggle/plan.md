# Settings — Voice Toggle and Phrase Editor Implementation Plan

## Overview

Add a "Notifications" tab to the existing `SettingsDialog` with a voice on/off checkbox, an editable phrase line edit, and a "Test voice" button. Persist via two new setters on `Settings` (`voice_enabled`, `voice_phrase`). Block save when voice is enabled with a blank phrase, using the same transient-tooltip pattern S-01 established. The `VoiceNotifier` is injected into the dialog so the Test button can speak the unsaved current text. Closes FR-007's user-configurable voice surface and dissolves PRD Open Question #3.

## Current State Analysis

**What exists today (post v0.2.x S-01 release):**

- `SettingsDialog` (`break_reminder/ui/settings_dialog.py`) already hosts a `QTabWidget` with a single "Scheduling" tab. The tabbed layout was deliberately scaffolded in S-01 for exactly this case ("tabbed from day one" decision in `context/changes/settings-break-interval/plan-brief.md`). Adding a "Notifications" tab is a pure `addTab` call — no layout reshuffle.
- `Settings.voice_enabled` (getter at `storage/settings.py:148-151`) and `Settings.voice_phrase` (getter at `storage/settings.py:153-156`) are functional. **Neither has a setter today** — they read from `notifications/voice_enabled` / `notifications/voice_phrase` keys with defaults from `DEFAULT_VOICE_ENABLED = False` (FR-007 opt-in) and `DEFAULT_VOICE_PHRASE = "Time to take a break"`. This slice adds both setters following the `break_interval_min.setter` pattern.
- `BreakReminderApp._on_break_due` at `app.py:307-310` already gates voice on `self._settings.voice_enabled` and speaks `self._settings.voice_phrase`. `_on_reminder_due` at `app.py:312-315` uses the same global gate but speaks the reminder name. **Toggling the gate or editing the phrase from the dialog applies on the next event with no re-arm signal** — same dynamic as `break_interval_min` via `Settings.snapshot()`.
- `VoiceNotifier` (`break_reminder/notifications/voice.py`) exposes `speak(phrase)`, `stop()`, `is_blocked()`, `shutdown()`. `speak("")` returns early (`voice.py:42`). Failures inside `_say` are swallowed by `logger.exception` so a missing audio device or pyttsx3 hiccup cannot crash the dialog.
- `BreakReminderApp.__init__` already builds and owns `self._voice` (`app.py:91`). Wiring is one line: pass `voice=self._voice` to `SettingsDialog(...)` in `_on_open_settings`.
- The S-01 transient-tooltip pattern (`QToolTip.showText` anchored to a widget rect with `msecShowTime=3000`) is already established at `settings_dialog.py:186-192`. Reusing it for "phrase blank when voice enabled" feedback is purely additive — same anchor pattern, different message.
- `tests/test_settings.py` is the round-trip pattern for setters under `tmp_path`. `tests/test_settings_dialog.py` already has `TestLoad`, `TestSave`, `TestLayout`, `TestValidationFeedback` classes — the new `TestNotificationsTab*` classes drop in alongside.

**What's missing:**

- A UI surface to flip `voice_enabled` / edit `voice_phrase` (today only achievable via hand-editing `BreakReminder.ini`).
- Setters on `Settings` for both keys.
- A way to preview the spoken phrase before committing — today the user must wait for the next break event (1-60 min) to hear it.

**Key constraints discovered during planning:**

- The `voice_enabled` toggle is the **global** voice gate per FR-007 + FR-013 — it covers both break events and custom reminders. This slice doesn't change reminder-voice; it just gives the user a UI to flip the gate that already governs both. The label "Enable voice notification" matches that scope.
- A `voice_enabled=True, voice_phrase=""` state is observably indistinguishable from voice off, but persists as different INI bytes. The dialog blocks save in that combination (Q3 decision) to prevent the confused state from ever landing on disk.
- `QSpinBox`'s lineEdit-vs-fixup quirk (uncovered during S-01 review) does NOT apply here — `QLineEdit` doesn't have a fixup pipeline. The phrase field's `text()` returns exactly what the user typed, so validation in `accept()` is straightforward.

## Desired End State

After this plan lands, a user right-clicks the BreakReminder tray icon, clicks "Open settings…", and the existing modal `QDialog` titled "Settings" opens with **two** tabs: "Scheduling" (unchanged from S-01) and a new "Notifications" tab. The Notifications tab shows:

- An "Enable voice notification" checkbox (unchecked by default, with a tooltip on hover explaining "Voice plays alongside the break popup, not instead of it.").
- A "Voice phrase" line edit pre-filled with the current `Settings.voice_phrase` value (always editable, regardless of the checkbox state).
- A "Test voice" button to the right of the phrase that calls `VoiceNotifier.speak(line_edit.text())` — speaks whatever is currently typed, even unsaved.

The user ticks the checkbox, edits the phrase, clicks **Test voice** to hear it, clicks **OK**. The dialog closes and persists both keys to `BreakReminder.ini`. On the next break event, both the popup AND voice fire (popup is mandatory per FR-007). Reopening settings shows the persisted values. Restarting the app preserves them.

If the user clicks **OK** with the checkbox ticked but the phrase blank/whitespace, a transient tooltip appears below the phrase field reading "Voice phrase cannot be empty when voice is enabled." and the dialog stays open.

The placeholder QMessageBox is gone (S-01 did that). The `voice_enabled` / `voice_phrase` setter pair is documented in `Settings`. The roadmap's S-04 entry flips `proposed` → `done`. PRD Open Question #3 is annotated as dissolved by S-04.

### Key Discoveries:

- `storage/settings.py:148-156` is exactly where the new setters land — the getter pattern is already in place.
- `ui/settings_dialog.py:101-115` is the constructor block that adds tabs. The new `addTab(self._build_notifications_tab(), self.NOTIFICATIONS_TAB_LABEL)` call slots in after the existing Scheduling tab `addTab` line.
- `ui/settings_dialog.py:186-192` is the QToolTip anchor pattern reused for the empty-phrase feedback.
- `app.py:91` shows the existing `self._voice` instance the dialog needs to receive via constructor injection.
- `tests/test_settings_dialog.py` `TestValidationFeedback` (lines 211+) is the closest pattern for testing the empty-phrase block; tooltip stub via `monkeypatch.setattr("break_reminder.ui.settings_dialog.QToolTip.showText", _stub)`.
- `tests/test_app.py` already has the precedent for asserting injection identity (`test_dialog_receives_app_settings_instance`); the new test mirrors it for `_voice`.

## What We're NOT Doing

- **No additional voice controls.** No volume slider, no rate slider, no system-voice picker, no per-event phrase override. The roadmap S-04 outcome is exactly two fields (toggle + phrase); anything else is scope creep.
- **No separate gate for reminder-voice.** `voice_enabled` already governs both break events and custom reminders globally per FR-007 + FR-013. This slice doesn't decouple them.
- **No re-arm signal.** `_on_break_due` and `_on_reminder_due` read `Settings.voice_enabled` / `voice_phrase` on every event — live changes apply automatically on the next event.
- **No persistence-layer validation of `voice_phrase`.** The `Settings.voice_phrase` setter accepts any string (including empty/whitespace). Validation is at the dialog layer only — a future caller writing directly via the setter is responsible for whatever string it passes.
- **No FR-007 wiring changes.** The integration at `app.py:307-315` is unchanged. This slice just gives the user a UI to flip the existing wires.
- **No telemetry / event-log row** for "voice enabled" / "phrase changed". The PRD's FR-015 enumerates loggable events (BREAK / REMINDER); settings edits aren't among them.
- **No async/threaded preview.** `VoiceNotifier.speak` is already async (single-worker thread pool); the Test button calls it and returns immediately. The dialog doesn't wait for speech to complete.
- **No keyboard shortcut for "Test voice"** (e.g., Ctrl+T). Pure mouse interaction is sufficient for v0.2.x; mnemonic shortcuts can land later if user demand emerges.
- **No phrase length cap.** `pyttsx3` handles arbitrary lengths and the user can self-regulate. A 5000-char phrase blocks the speech worker for ~30s, which the user will discover the first time they Test it.
- **No Focus Assist / system-mute UI hint.** Both are stubs in `voice.py:88-101` returning False; surfacing a "voice may be suppressed" banner would be dishonest until those gates are real.
- **No registry / autostart write** (that's S-02), no other `Settings` setters (snooze is S-03).

## Implementation Approach

Two phases. Phase 1 lands the entire code change in one agent push: the two setters, the new Notifications tab with all three widgets, the validation branch in `accept()`, the one-line wiring in `app.py`, and the corresponding automated tests. The dialog is reachable via the running app the moment Phase 1 lands, so there's no agent-only window like S-01 had — which is fine because the new tab is purely additive (the existing Scheduling flow is unchanged).

Phase 2 is human verification: the manual smoke (which requires audio output and a real break event) and the roadmap/PRD bookkeeping that closes out the slice.

The dialog gets a new required keyword-only `voice: VoiceNotifier` parameter. App.py passes its existing `self._voice`. Tests inject a stub via either `Mock(spec=VoiceNotifier)` or a tiny `class _StubVoice` with a no-op `speak`. Defaulting `voice` to `None` and lazily creating one is rejected — that path would bind pyttsx3's speech engine in test runs and hurts CI predictability.

The validation branch in `accept()` is intentionally minimal: one `if` checking the (checkbox, stripped phrase) tuple, the same `QToolTip.showText` shape as S-01's range tooltip, and an early `return` (no `super().accept()`). The setters fire only when validation passes, so a partial save (voice flipped but phrase rejected) cannot land on disk.

## Critical Implementation Details

### VoiceNotifier injection contract

`SettingsDialog.__init__` MUST require `voice: VoiceNotifier` as a keyword-only parameter (no default). Defaulting to a fresh `VoiceNotifier()` is tempting but creates a real `pyttsx3` worker pool every time a test constructs the dialog without passing a stub — which the existing `TestLoad` / `TestSave` / `TestLayout` / `TestValidationFeedback` tests do dozens of times. Forcing all callers to pass a stub keeps tests fast and free of audio-device assumptions. The single production caller (`app.py:_on_open_settings`) already owns `self._voice`, so the cost at the call site is one new kwarg.

---

## Phase 1: Notifications tab + voice setters + automated coverage

### Overview

Land the full code change behind automated tests. Adds two `Settings` setters, a new "Notifications" tab to `SettingsDialog`, validation in `accept()`, one-line wiring in `app.py`, and the matching test classes. After this phase, the running app shows the new tab and persists changes; manual smoke (requires audio + a break event) is gated behind Phase 2.

### Changes Required:

#### 1. Add setters to `Settings`

**File**: `break_reminder/storage/settings.py`

**Intent**: Add `@voice_enabled.setter` and `@voice_phrase.setter` so the dialog can write the values back. Mirrors the `break_interval_min.setter` shape but without range validation — `voice_enabled` is a bool (no values to reject), and `voice_phrase` accepts any string (the dialog enforces non-empty-when-enabled, not the persistence layer).

**Contract**:

- `voice_enabled.setter(self, value: bool) -> None`: writes `bool(value)` to `_Keys.VOICE_ENABLED`. No validation (`bool` is total over the setter's input domain).
- `voice_phrase.setter(self, phrase: str) -> None`: writes the string to `_Keys.VOICE_PHRASE`. No validation. The dialog blocks empty-when-enabled at its own layer; the setter is permissive so future callers (e.g., a future "reset to defaults" feature) don't fight it.
- Both setters get Google-style docstrings per `context/foundation/lessons.md`. The `voice_phrase` docstring explicitly notes that empty strings are accepted at the persistence layer and the dialog enforces the non-empty contract when voice is enabled.

#### 2. Add Notifications tab to `SettingsDialog`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Add a second tab labelled "Notifications" containing the voice toggle, phrase editor, and Test button. Extend `accept()` to validate the (checkbox, phrase) combination before persisting and to surface the existing transient-tooltip pattern when the combination is invalid. Wire `VoiceNotifier` through the constructor as a required keyword-only dependency.

**Contract**:

- Constructor signature becomes `SettingsDialog(*, settings: Settings, voice: VoiceNotifier, parent: QWidget | None = None) -> None`. `voice` is required (no default) per Critical Implementation Details.
- New class constant `NOTIFICATIONS_TAB_LABEL = "Notifications"` alongside the existing `SCHEDULING_TAB_LABEL`.
- New private builder `_build_notifications_tab(self) -> QWidget` returning a `QWidget` with a `QFormLayout` that contains:
  - `QCheckBox("Enable voice notification")` stored on `self._voice_enabled_checkbox`. Initial state from `self._settings.voice_enabled`. Tooltip set to `"Voice plays alongside the break popup, not instead of it."` (Q4 commitment).
  - `QLineEdit` stored on `self._voice_phrase_edit`. Pre-filled with `self._settings.voice_phrase`. Always enabled regardless of checkbox state (Q2 commitment).
  - `QPushButton("Test voice")` stored on `self._voice_test_button` whose `clicked` signal connects to a new `_on_test_voice_clicked` slot.
  - Layout: the checkbox sits on its own form row; the phrase + Test button share a row via a small `QHBoxLayout` (line edit on the left, button on the right). Form row label: `"Voice phrase:"`.
- New slot `_on_test_voice_clicked(self) -> None`: calls `self._voice.speak(self._voice_phrase_edit.text())`. No state change, no save side-effect — the button speaks whatever is currently typed, even unsaved.
- Module-level constant `_VOICE_PHRASE_REQUIRED_MESSAGE = "Voice phrase cannot be empty when voice is enabled."` for the Q3 validation feedback.
- `accept()` is extended (do NOT replace the existing break-interval persistence): before any setter writes, check `if self._voice_enabled_checkbox.isChecked() and not self._voice_phrase_edit.text().strip()`. If true, fire `QToolTip.showText` anchored to `self._voice_phrase_edit.mapToGlobal(self._voice_phrase_edit.rect().bottomLeft())` with `_VOICE_PHRASE_REQUIRED_MESSAGE` and `msecShowTime=3000`, then `return` (skipping both the setters and `super().accept()`). Otherwise, persist `voice_enabled = self._voice_enabled_checkbox.isChecked()` and `voice_phrase = self._voice_phrase_edit.text()` AFTER the existing `break_interval_min` write, then chain to `super().accept()`.
- Module docstring is extended with a short paragraph describing the Notifications tab and its validation contract (mirroring the existing Scheduling tab paragraph).
- All new public methods get Google-style docstrings per `context/foundation/lessons.md`.

#### 3. Wire `VoiceNotifier` through `BreakReminderApp._on_open_settings`

**File**: `break_reminder/app.py`

**Intent**: Pass the existing `self._voice` to `SettingsDialog` so the Test button has a real notifier to speak through.

**Contract**: One-line edit inside `_on_open_settings`: `SettingsDialog(settings=self._settings, voice=self._voice).exec()`. No other change to `app.py`.

#### 4. Setter round-trip tests

**File**: `tests/test_settings.py`

**Intent**: Cover the new setters end-to-end with the same `tmp_path`-bound `Settings` pattern existing tests use.

**Contract**: New test class `TestVoiceSettersRoundTrip` (or named-pair tests added to an existing class) covering:

- `voice_enabled` setter writes True → getter returns True; writes False → getter returns False.
- `voice_phrase` setter writes a custom phrase → getter returns it; setter accepts empty string (persistence-layer permissiveness — dialog enforcement is tested separately).
- After setter + `_qs.sync()`, a freshly-constructed `Settings(ini_path=…)` reads the persisted values.

#### 5. Notifications-tab dialog tests

**File**: `tests/test_settings_dialog.py`

**Intent**: Cover load / save / validation / Test-button / layout for the new tab. Mirror the structural pattern of `TestLoad` / `TestSave` / `TestLayout` / `TestValidationFeedback` from S-01.

**Contract**: All new tests inject a stub voice notifier (a tiny class with a no-op `speak`, or `Mock(spec=VoiceNotifier)`). The existing `dialog` fixture is updated to pass `voice=stub`; existing tests continue to pass with the stub. New test classes:

- `TestNotificationsTabLoad`: checkbox default unchecked; checkbox reflects `Settings.voice_enabled = True` when pre-set; phrase field shows `DEFAULT_VOICE_PHRASE`; phrase field reflects pre-set value; checkbox tooltip mentions "alongside" (Q4 commitment); phrase field is enabled when checkbox unchecked AND when checked (Q2 commitment).
- `TestNotificationsTabSave`: `accept()` persists checkbox-true → `Settings.voice_enabled == True`; persists phrase change; persists across fresh `Settings` instances (after `_qs.sync()`); `reject()` discards both; `accept()` persists the existing `break_interval_min` AND the new voice fields in the same call (no regression of S-01).
- `TestNotificationsTabValidation`: voice checked + empty phrase → `accept()` returns without writing AND without calling `super().accept()` (dialog stays open); voice checked + whitespace-only phrase → same; voice checked + non-empty phrase → save proceeds; voice unchecked + empty phrase → save proceeds (the empty phrase persists silently). Use the `monkeypatch.setattr("break_reminder.ui.settings_dialog.QToolTip.showText", ...)` stub pattern from S-01's `TestValidationFeedback._patch_show_text`.
- `TestNotificationsTabTestButton`: clicking the button calls `voice.speak` exactly once; the speak call receives the line edit's CURRENT text (not the persisted value); editing the phrase + clicking Test before save → speak receives the unsaved text; clicking Test does not write to settings.
- `TestNotificationsTabLayout`: dialog now has 2 tabs; second tab label is "Notifications"; tab contains a `QCheckBox`, a `QLineEdit`, and a `QPushButton`.

#### 6. App-test for voice injection

**File**: `tests/test_app.py`

**Intent**: Pin the `_voice` injection identity contract so a future refactor can't accidentally construct a duplicate `VoiceNotifier` for the dialog.

**Contract**: Mirroring `test_dialog_receives_app_settings_instance`, add `test_dialog_receives_app_voice_instance`: monkeypatch `SettingsDialog.__init__` to capture the `voice` kwarg, trigger the "Open settings…" action, assert the captured object is `app._voice` (identity check).

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py`
- Full suite still passes: `uv run pytest`
- Type check passes: `uv run pyright break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py`
- Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py`
- Format check passes: `uv run ruff format --check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py`
- `python -c "from break_reminder.ui.settings_dialog import SettingsDialog"` does not raise.

#### Manual Verification:

- (None — Phase 1 is agent-only. Manual smoke is Phase 2.)

**Implementation Note**: After completing this phase and all automated verification passes, proceed directly to Phase 2 — the new tab is reachable from the running app immediately, but the manual smoke requires audio output + a real break event, which warrants its own pause point.

---

## Phase 2: Manual smoke + roadmap bookkeeping

### Overview

Verify the new tab end-to-end on a machine with audio. Confirm voice fires on a real break event, persistence round-trips through an app restart, and the empty-phrase block surfaces the tooltip. After smoke passes, update `roadmap.md` (S-04 → done, Open Question #3 → dissolved) and `change.md` (status → implemented).

### Changes Required:

#### 1. Roadmap update

**File**: `context/foundation/roadmap.md`

**Intent**: Flip S-04 status to `done`, mark PRD Open Question #3 as dissolved by S-04, and bump the Backlog Handoff "Ready for `/10x-plan`" cell. Mirrors how S-01's archive flipped the table.

**Contract**: Two cell edits and one annotation:

- "At a glance" table row for S-04: status cell `proposed` → `done`.
- Backlog Handoff table row for S-04: "Ready for `/10x-plan`" cell `no` → (leave as `yes` since the slice has been planned and shipped, OR remove the row entirely after archive — match the convention used by S-01 once it archives).
- "Open Roadmap Questions" item #3 (Voice notification content): append `(dissolved by S-04 on 2026-05-25)` to the existing entry.

#### 2. change.md status update

**File**: `context/changes/settings-voice-toggle/change.md`

**Intent**: Move the change through the standard lifecycle states.

**Contract**: `status: planned` → `status: implementing` (when /10x-implement starts) → `status: implemented` (after manual smoke confirms). `updated:` reflects each transition.

### Success Criteria:

#### Automated Verification:

- (None — Phase 2 is human-verification only. The Phase 1 automated gate already proved the code is correct.)

#### Manual Verification:

- The "Open settings…" tray menu item opens the modal dialog and the Notifications tab is visible alongside Scheduling.
- The voice checkbox is unchecked by default; the phrase field shows "Time to take a break".
- Hovering the checkbox surfaces the alongside-not-instead tooltip.
- Typing a custom phrase and clicking **Test voice** speaks the typed (unsaved) phrase through the system audio.
- Ticking the checkbox, editing the phrase, clicking **OK** closes the dialog and persists both keys to `%APPDATA%\BreakReminder\BreakReminder.ini` (verify in Notepad: `voice_enabled=true` and `voice_phrase=<typed>` under `[notifications]`).
- On the next break event (configurable via the Scheduling tab to a short interval for the smoke), both the popup AND voice fire.
- Reopening settings shows the persisted values; clicking **Cancel** after editing leaves the INI unchanged.
- Editing the phrase to blank with the checkbox still ticked, clicking **OK** → a transient tooltip appears below the phrase field with the "Voice phrase cannot be empty when voice is enabled." message; the dialog stays open (does not close).
- Unchecking the checkbox with any (or empty) phrase, clicking **OK** → save proceeds; next break = popup only, no voice.
- Quitting and restarting the app preserves the last saved values.
- Restoring settings to defaults (uncheck voice, restore phrase) before ending the smoke.

**Implementation Note**: After Phase 2's smoke checklist all passes, the slice is complete — flip change.md to `status: implemented`. The roadmap update flips S-04 to `done` and the Open Question #3 annotation lands. The change folder is then eligible for `/10x-archive`.

---

## Testing Strategy

### Unit Tests:

- `Settings.voice_enabled` and `Settings.voice_phrase` setter round-trip — same `tmp_path`-bound pattern as the existing `break_interval_min` tests.
- `SettingsDialog` Notifications-tab load — checkbox + phrase show injected `Settings` values; tooltip text on the checkbox; phrase always editable.
- `SettingsDialog` Notifications-tab save — OK persists, Cancel discards, observable across fresh `Settings` instances.
- `SettingsDialog` Notifications-tab validation — voice-on + empty phrase blocks save and surfaces the tooltip; voice-off + empty phrase saves cleanly.
- `SettingsDialog` Test-voice button — calls injected `voice.speak(unsaved_text)` exactly once; does not touch settings.
- `BreakReminderApp` slot wiring — the dialog receives the app's `_voice` instance (identity check).
- Existing `TestLoad` / `TestSave` / `TestLayout` / `TestValidationFeedback` tests still pass — the constructor's new `voice` kwarg is wired through the existing `dialog` fixture using a stub.

### Integration Tests:

- (None added — the dialog is invoked synchronously from a Qt slot; the unit tests + manual smoke cover the integration surface.)

### Manual Testing Steps:

1. Run the app from source: `uv run python -m break_reminder` (or run the installed `BreakReminder.exe` for a closer-to-production smoke).
2. Right-click tray → "Open settings…". Confirm two tabs visible: "Scheduling" and "Notifications".
3. Switch to Notifications. Confirm checkbox unchecked, phrase = "Time to take a break", Test button visible.
4. Hover the checkbox → tooltip appears explaining alongside-not-instead.
5. Type a recognizable test phrase (e.g., "Plan smoke working") and click **Test voice** → speaker plays the typed phrase.
6. Tick the checkbox. Click **OK**. Open `%APPDATA%\BreakReminder\BreakReminder.ini` in Notepad → confirm `voice_enabled=true` and `voice_phrase=Plan smoke working` under `[notifications]`.
7. Open Scheduling tab, set Break interval to 2 minutes for fast smoke. Click OK.
8. Wait 2 minutes of active input → the break popup appears AND the voice plays the test phrase.
9. Reopen settings → Notifications tab shows persisted values (checkbox ticked, phrase = "Plan smoke working").
10. Clear the phrase field (leave checkbox ticked). Click **OK** → tooltip appears below the phrase field; dialog stays open.
11. Untick the checkbox (leave phrase blank). Click **OK** → dialog closes. Wait 2 minutes → next break = popup only.
12. Quit via tray "Quit". Restart. Open settings → confirm last-saved state persists.
13. Restore: tick voice, set phrase back to "Time to take a break", set break interval back to 60 minutes, click **OK**.

## Performance Considerations

None. The new tab is a few `QWidget` instances and two `QSettings.value()` reads on construction; total cost under 1 ms. The save path is two `QSettings.setValue` calls. The Test button calls `VoiceNotifier.speak` which already runs on a single-worker `ThreadPoolExecutor` — the GUI thread doesn't block.

## Migration Notes

None. Existing `BreakReminder.ini` files from v0.1.0 / v0.2.x already have or will create the `notifications/voice_enabled` and `notifications/voice_phrase` keys with the documented defaults via the existing getters. No data migration; no key renames.

## References

- Roadmap entry: `context/foundation/roadmap.md` § S-04 (settings-voice-toggle)
- PRD: `context/foundation/prd.md` § FR-005, § FR-007, Open Question #3
- Sibling slice (closest pattern): `context/changes/settings-break-interval/plan.md` (S-01 — same dialog, same persistence layer, same QToolTip feedback pattern)
- Voice consumer: `break_reminder/app.py:307-315` (`_on_break_due`, `_on_reminder_due`)
- Voice notifier: `break_reminder/notifications/voice.py`
- Settings getters this slice complements: `break_reminder/storage/settings.py:148-156`
- Existing dialog scaffold: `break_reminder/ui/settings_dialog.py`
- Test conventions: `tests/test_settings.py` (round-trip), `tests/test_settings_dialog.py` (load/save/layout/validation patterns), `tests/test_app.py` (injection identity)
- Lessons: `context/foundation/lessons.md` (Google-style docstrings rule applies to all new public functions)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See the skill's `references/progress-format.md`.

### Phase 1: Notifications tab + voice setters + automated coverage

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py` — 7b3a8f8
- [x] 1.2 Full suite still passes: `uv run pytest` — 7b3a8f8
- [x] 1.3 Type check passes: `uv run pyright break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py` — 7b3a8f8
- [x] 1.4 Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py` — 7b3a8f8
- [x] 1.5 Format check passes: `uv run ruff format --check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_app.py` — 7b3a8f8
- [x] 1.6 `python -c "from break_reminder.ui.settings_dialog import SettingsDialog"` does not raise. — 7b3a8f8

### Phase 2: Manual smoke + roadmap bookkeeping

#### Manual

- [x] 2.1 Settings dialog opens with two tabs (Scheduling + Notifications). — d6be26c
- [x] 2.2 Voice checkbox default unchecked; phrase shows "Time to take a break"; tooltip explains alongside-not-instead. — d6be26c
- [x] 2.3 Test voice button speaks the typed (unsaved) phrase through system audio. — d6be26c
- [x] 2.4 OK persists both keys to BreakReminder.ini under `[notifications]`. — d6be26c
- [x] 2.5 On next break event, popup AND voice fire (popup mandatory, voice opt-in additional). — d6be26c
- [x] 2.6 Reopening settings shows persisted values; Cancel discards changes. — d6be26c
- [x] 2.7 Voice on + blank phrase + OK → tooltip appears; dialog stays open. — d6be26c
- [x] 2.8 Voice off + blank phrase + OK → save proceeds; next break = popup only. — d6be26c
- [x] 2.9 Quit + restart preserves last-saved values. — d6be26c
- [x] 2.10 Roadmap S-04 status flipped `proposed` → `done`; Open Question #3 annotated as dissolved. — d6be26c
- [x] 2.11 change.md status flipped through `implementing` → `implemented`. — d6be26c
