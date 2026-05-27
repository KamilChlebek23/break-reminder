# Reminders Add Form Implementation Plan

## Overview

Wire the S-05 "Add…" button to a new modal sub-dialog (`break_reminder/ui/reminder_form_dialog.py`) that collects a name + future date/time, validates both, persists a one-shot `Reminder` via the existing `ReminderStore.add()`, arms the running session via the existing `ReminderScheduler.reload()` hook, and rebuilds the Reminders tab in place so the new row shows immediately. A small pre-S-06 refactor injects a `clock` callable into `ReminderScheduler` (mirroring `BreakScheduler`) so the new "add → fire" tests are deterministic.

This is the second slice of roadmap Stream B (custom reminders), unblocking on S-05. It dissolves the FR-011 "User can add a custom reminder" surface and the first half of FR-013 "When a custom reminder's time arrives, BreakReminder fires a dismissable popup" (the wiring exists in `app.py` already; this slice ensures a user-created reminder reaches it).

## Current State Analysis

- **Storage layer is complete.** `Reminder` (`break_reminder/storage/reminders.py:27-61`) is a five-field dataclass with `id` auto-generated via `uuid.uuid4`, and `rrule_str` / `end_at` defaulting to `None` (which is precisely the one-shot encoding). `ReminderStore.add()` (`storage/reminders.py:82-87`) already does atomic tmp+rename writes (lines 116-124) under a `threading.Lock` (line 75). **No new storage code.**
- **Scheduler arm-on-add hook already exists.** `ReminderScheduler.reload()` at `break_reminder/scheduler.py:255-264` recomputes the next firing and rearms the single-shot `QTimer`. Its docstring literally says *"Call on add/edit/delete."* But there's **no store→scheduler signal** today (`storage/reminders.py:82-99` is silent), so the save path must invoke `reload()` explicitly.
- **`ReminderScheduler` hardcodes `datetime.now(UTC)`** at three sites (`scheduler.py:261`, `:271`, `:286`). `BreakScheduler` already takes `clock: Callable[[], datetime] | None = None` (`scheduler.py:60-86`) and uses module-level `_utcnow` (`scheduler.py:43-45`) as the default fallback. `tests/test_break_scheduler.py:35-48` has a `Clock` fixture that drives the scheduler deterministically. `tests/test_reminder_scheduler.py` does **not exist yet** — this slice is writing it from scratch.
- **S-05 Reminders tab.** Reads `ReminderStore.list_all()` exactly once in `_build_reminders_tab()` (`ui/settings_dialog.py:590-648`); placeholder branch or populated `QListWidget` is built once, then frozen. The three buttons (`Add…`, `Edit…`, `Delete`) live in `_build_reminders_button_row()` (`:650-697`); each is disabled with a tooltip on a one-widget wrapper (Qt 6 swallows hover events on disabled widgets — see "Critical Implementation Details" below). The `list_all()`-exactly-once invariant is pinned by a spy test (`tests/test_settings_dialog.py:1938-1980`). The Reminders tab widget is **not** stored on `self` (S-05 rule: "stored only when `accept()` needs to switch to it on validation failure").
- **Sub-dialog precedents.** `notifications/reminder_dialog.py:24-55` is the closest precedent for a small modal form (`QDialogButtonBox` OK-only, `QVBoxLayout(contentsMargins=(24,24,24,24), spacing=16)`), but it's `show()`-based in production — there is **no existing modal sub-dialog launched with `exec()` from inside another dialog** in the codebase. S-06 establishes that convention.
- **`QDateTimeEdit` is not imported anywhere.** No file imports `QDateTimeEdit`, `QDateEdit`, `QTimeEdit`, `QCalendarWidget`, or `QDateTime`. S-06 establishes the local date-picker convention.
- **Timezone convention.** Every `Reminder` in `tests/test_settings_dialog.py` and `tests/test_reminders.py` uses `tzinfo=UTC` (verified by grep). The display side (S-05's `_format_firing`, `ui/settings_dialog.py:204-227`) converts UTC → local via `.astimezone(tz)`. The dialog must symmetrically convert local → UTC at save time. `_ensure_aware` (`scheduler.py:325-329`) treats naive datetimes as UTC, so persisting tz-aware UTC is the safest and most explicit option.
- **Validation pattern is established.** Settings-dialog gates (`ui/settings_dialog.py:826-842` for voice-phrase-empty) use `QToolTip.showText` anchored to the failing field's `mapToGlobal(QPoint(...))`, then early return. No `QMessageBox` anywhere in the codebase for validation — don't introduce one.
- **App wiring.** `BreakReminderApp._on_open_settings()` (`app.py:313-334`) constructs a fresh `SettingsDialog` per open and ignores the return value. `ReminderScheduler` is constructed once at `app.py:102` and lives for the app's lifetime. The signal-slot wiring `ReminderScheduler.reminder_due → _on_reminder_due → ReminderDialog.show()` is at `app.py:373-380`.

## Desired End State

The S-05 Reminders tab gains a working Add button:

1. **Add button is enabled** (no longer wrapped in a "coming in a future update" tooltip). Edit and Delete remain disabled with the wrapper tooltip — S-07 enables those.
2. **Clicking Add opens a modal sub-dialog** (`ReminderFormDialog`) containing:
   - A `QLineEdit` labelled "Name" (placeholder: "e.g., Visit to dentist").
   - A `QDateTimeEdit` labelled "Date/time" with `setCalendarPopup(True)`, display format `"ddd yyyy-MM-dd HH:mm"`, default value = (system-local equivalent of `self._clock()`) + 1 hour, rounded up to the next quarter-hour (so the typical "I want a reminder in about an hour" path is one click + Save). See Phase 1 #2 Contract for the exact UTC→local→round computation.
   - A `QDialogButtonBox` with OK + Cancel.
3. **OK validates:**
   - Name stripped of leading/trailing whitespace must be non-empty; failure shows tooltip "Name cannot be empty" anchored to the name field and returns early.
   - `fire_at` (the QDateTimeEdit's value, converted to tz-aware UTC) must be **strictly greater than** `datetime.now(UTC)`; failure shows tooltip "Time must be in the future" anchored to the datetime field and returns early.
   - Validation order is name-first, datetime-second (single tooltip at a time; first failing field wins; mirrors voice-phrase pattern).
4. **On validation pass:**
   - Construct `Reminder(name=stripped_name, start_at=fire_at_utc)` — `id` auto-fills, `rrule_str` and `end_at` default `None` (one-shot encoding).
   - Call `reminder_store.add(reminder)` — if it raises `OSError` (permission denied / disk full), show tooltip "Could not save reminder: {e.strerror}" anchored to the OK button, keep the dialog open, return early.
   - Call `reminder_scheduler.reload()` — arms the running session.
   - Call `super().accept()` — closes the sub-dialog with `QDialog.Accepted`.
5. **Cancel closes the sub-dialog** with `QDialog.Rejected`; nothing persisted, nothing armed.
6. **After OK returns Accepted**, the Reminders tab rebuilds in place: `_tabs.removeTab(REMINDERS_INDEX)` + `_tabs.insertTab(REMINDERS_INDEX, self._build_reminders_tab(), REMINDERS_TAB_LABEL)`. The new row appears in the correct sort position (closest future first). Re-rebuilding also refreshes `_format_firing` on every existing row, so any rows that became expired during the dialog's open lifetime now correctly render `"(expired)"`.
7. **At the chosen `fire_at` instant**, the existing `ReminderScheduler` → `BreakReminderApp._on_reminder_due` → `ReminderDialog.show()` chain fires the dismissable popup with the reminder's name. No new firing wiring in this slice — the wiring already exists in `app.py:373-380`.
8. **AGENTS.md** no longer flags Custom-reminder Add as a known TODO (the second pending bullet narrows to "Edit / Delete dialog wiring" since Add is shipped).
9. **`roadmap.md` S-06 row + body** flip from `proposed` to `done`.

### Verification:

- `uv run pytest tests/test_reminder_form_dialog.py` (new file) passes — covers field defaults, validation gates, atomic-save tripwire, save path success, OSError handling, Cancel path.
- `uv run pytest tests/test_reminder_scheduler.py` (new file) passes — covers clock-injection default, `reload()` rearms after `store.add()` is called externally, far-future reminder gets the 24h cap.
- `uv run pytest tests/test_settings_dialog.py` passes — extended to cover Add button enabled (no wrapper), Add.click() opens sub-dialog (via monkeypatched class), tab rebuild on signal.
- `uv run pytest tests/test_app.py` passes — `_on_open_settings` constructor-arg addition does not break app boot.
- `uv run pyright`, `uv run ruff check`, `uv run ruff format --check`, `uv run pip-audit`, `uv run pip-licenses --fail-on="AGPL"` all green.
- Real Windows session: open Settings → Reminders → Add; set name "Test" + time = now + 30 seconds; Save; the new row appears in the list; quit the dialog; wait 30 seconds; the `ReminderDialog` popup fires showing "Test".

### Key Discoveries:

- **`ReminderScheduler.reload()` is the only public API needed for arming** (`scheduler.py:255-264`). Its docstring already documents "Call on add/edit/delete." — no scheduler-side API addition needed.
- **`BreakScheduler` is the clock-injection template** (`scheduler.py:60-86`). Replicating its `clock: Callable[[], datetime] | None = None` + `self._clock = clock or _utcnow` on `ReminderScheduler` is a 5-line change and reuses the existing module-level `_utcnow` helper at `scheduler.py:43-45`.
- **The Reminders tab's `list_all()`-exactly-once invariant** (S-05 plan line 75, test at `tests/test_settings_dialog.py:1938-1980`) evolves cleanly to "exactly once per `_build_reminders_tab()` call". The spy test must be updated to count calls per (re)build, not across the dialog's lifetime.
- **`ReminderStore.add()` is atomic** (`storage/reminders.py:82-87` + `:116-124`). No partial-write state to handle; the only error to gate is `OSError` (permission denied / disk full).
- **`QDateTimeEdit.dateTime().toPython()` returns a naive Python `datetime`.** Conversion to tz-aware UTC happens at the dialog layer: `naive.replace(tzinfo=datetime.now().astimezone().tzinfo).astimezone(UTC)` captures the system local zone and converts.
- **The wrapper-widget tooltip pattern (S-05) is sticky for Edit/Delete only.** The Add button drops its wrapper after this slice (or keeps an enabled wrapper with no tooltip — see "Critical Implementation Details" for the chosen approach).

## What We're NOT Doing

- **No Edit / Delete handlers.** Edit and Delete buttons stay disabled (with the existing wrapper tooltip). S-07 wires them.
- **No recurrence editor.** No RRULE field in the form, no "Repeat weekly" checkbox, no recurrence picker. S-08 owns that.
- **No `end_at` field.** One-shot only; `Reminder.end_at` defaults to `None` and stays there.
- **No `id` field surfaced to the user.** Auto-generated via `uuid.uuid4`.
- **No reminder editing via the Reminders tab list** (double-click, F2, etc.). Read-only list, same as S-05.
- **No `ReminderStore.changed` signal.** The refresh hook is the explicit `reminder_added` Qt signal emitted by `ReminderFormDialog` and connected by `SettingsDialog`. The store stays Qt-free.
- **No `QFileSystemWatcher` on `reminders.json`.** Hand-editing the JSON while the dialog is open is out of scope; the dialog is a snapshot.
- **No history view, no log integration.** Custom-reminder firings already emit `reminder_due` and `app.py` shows the popup; FR-015's CSV logging of custom-reminder events lives in `event_log.py` and is unchanged.
- **No NSIS, PyInstaller, or release-workflow changes.** Pure code change.
- **No autostart / pause / voice / tray changes.** Out of scope.
- **No new `Settings` keys.** The sub-dialog's defaults (e.g., "now + 1h rounded to next 15 min") are hardcoded constants; user customization of defaults is a hypothetical S-99 conversation, not a v1 need.
- **No localization / i18n.** Tooltip text, button labels, validation messages are all English literals — same as every other dialog.

## Implementation Approach

The slice is shaped as: a tiny scheduler-side refactor, a new UI module, two test files, an extension of the existing settings-dialog test file, and one bookkeeping doc edit. The order matters because tests in the new files depend on the production code being in place; below is the implementer's natural order.

1. **Scheduler clock-injection.** Add `clock: Callable[[], datetime] | None = None` to `ReminderScheduler.__init__`, store as `self._clock = clock or _utcnow`, replace `datetime.now(UTC)` at `scheduler.py:261, :271, :286` with `self._clock()`. App-side construction at `app.py:102` does not change (production keeps the default).
2. **Build `ReminderFormDialog`** in a new module `break_reminder/ui/reminder_form_dialog.py`. Constructor takes keyword-only `store: ReminderStore`, `scheduler: ReminderScheduler`, `clock: Callable[[], datetime] | None = None`, `parent: QWidget | None = None`. Class signal `reminder_added = Signal(Reminder)` emitted from `accept()` on successful save. The `clock` parameter is for tests (same pattern as `BreakScheduler`); production passes `None`.
3. **Extend `SettingsDialog`** (`break_reminder/ui/settings_dialog.py`):
   - Add `reminder_scheduler: ReminderScheduler` required keyword-only parameter (mirrors `reminder_store`).
   - Store `self._reminders_tab` so the rebuild handler can address it (the S-05 rule "store the tab on self only when `accept()` needs to switch to it" is amended; document the new reason in the constructor comment block).
   - Add `_REMINDERS_INDEX = 3` module-level constant (or `self._tabs.indexOf(self._reminders_tab)` looked up at refresh time — see "Critical Implementation Details").
   - Modify `_build_reminders_button_row()` so the Add button is enabled and its wrapper carries no tooltip (or no wrapper at all — see "Critical Implementation Details"). Wire `self._reminders_add_button.clicked.connect(self._on_reminders_add_clicked)`.
   - Add `_on_reminders_add_clicked()` slot: constructs `ReminderFormDialog(store=self._reminder_store, scheduler=self._reminder_scheduler, parent=self)`, connects its `reminder_added` signal to `self._refresh_reminders_tab`, calls `dialog.exec()`. (Connection happens before `exec()`; the signal fires inside `accept()` before `exec()` returns.)
   - Add `_refresh_reminders_tab()` slot: removes the Reminders tab, rebuilds via `_build_reminders_tab()`, inserts at the same index, restores `self._reminders_tab`.
4. **Update app wiring** at `app.py:313-334` to pass `reminder_scheduler=self._reminder_scheduler` into `SettingsDialog(...)`.
5. **Write `tests/test_reminder_scheduler.py`** (new file). Cover clock-default (production passes `None` → uses `_utcnow`); `reload()` rearms after `store.add()` is called between two `reload()` calls; far-future reminder gets the 24h cap (`QTimer.interval()` equals 24h).
6. **Write `tests/test_reminder_form_dialog.py`** (new file). Test classes mirror `TestRemindersTab` shape: `TestReminderFormDialogDefaults`, `TestReminderFormDialogValidation`, `TestReminderFormDialogSave`, `TestReminderFormDialogCancel`. Use a frozen-clock fixture so default-datetime tests are stable; use a tmp-path `ReminderStore` and a stub `ReminderScheduler` (a `MagicMock` with a `reload` attribute is acceptable here — the test asserts `reload` was called once on success, not called on validation failure or Cancel).
7. **Extend `tests/test_settings_dialog.py`**:
   - Add `reminder_scheduler` fixture (a stub scheduler — `ReminderScheduler(store=reminder_store)` works since `start()` isn't called in tests, but a `MagicMock` is faster).
   - Update the `dialog` fixture and every `SettingsDialog(...)` construction (19 callsites) to pass `reminder_scheduler=...`. Mirror the explicit-pass convention S-05 set; do **not** introduce a `_make_dialog` helper now (S-05 considered it and chose explicit-pass for readability).
   - Update the `TestRemindersTab::test_list_all_called_exactly_once` test (S-05 spy at `tests/test_settings_dialog.py:1938-1980`) to assert "exactly one call per `_build_reminders_tab()` call" rather than "exactly one call across the dialog's lifetime" — the new refresh flow legitimately calls it again on rebuild.
   - Add `TestRemindersAddButton` test class: Add button is enabled; Add button has no tooltip on its wrapper (or no wrapper); clicking Add invokes the slot; the slot constructs `ReminderFormDialog` with the right args; emitting `reminder_added` triggers `_refresh_reminders_tab`; after refresh, the new row appears at the expected sort position.
8. **Update `AGENTS.md`** "What this scaffold does NOT yet implement" — tighten the second pending bullet from "Custom-reminder editor dialog (FR-011 / FR-012 CRUD)" to "Custom-reminder Edit / Delete dialog wiring (FR-012)" since Add is shipped.
9. **Phase 2 bookkeeping** — `change.md` to `implemented`, `roadmap.md` S-06 to `done`, `AGENTS.md` updated, Progress section ticked.

## Critical Implementation Details

- **Local→UTC conversion at save time.** `QDateTimeEdit.dateTime().toPython()` returns a **naive** `datetime`. The dialog must capture the system local timezone and convert. Use: `local_tz = datetime.now().astimezone().tzinfo; fire_at_utc = naive_dt.replace(tzinfo=local_tz).astimezone(UTC)`. Do **not** call `naive_dt.astimezone(UTC)` directly — Python raises `ValueError` on naive datetimes for `.astimezone()` only on some versions, and silently treats them as local on others. The explicit `.replace(tzinfo=local_tz)` makes the conversion unambiguous. A test pins this: construct a known UTC instant, set the `QDateTimeEdit` value to the local wall-clock equivalent, call `accept()`, assert `reminder_store.list_all()[0].start_at == known_utc_instant` (tz-aware comparison).

- **Validation order and tooltip anchoring.** Name-first, datetime-second; first failing field wins; the second tooltip never appears in the same `accept()` call. Tooltip anchor is `field.mapToGlobal(QPoint(0, field.height()))` (just below the field, same as voice-phrase). Use `QToolTip.showText(anchor, message, field)` so Qt parents the tooltip to the right widget. The OK-button-OSError tooltip anchors to the OK button (`self._buttons.button(QDialogButtonBox.StandardButton.Ok).mapToGlobal(...)`).

- **Add-button wrapper after S-06.** S-05's pattern wraps every disabled button in a one-widget container so the tooltip survives Qt 6's hover-event-swallow-on-disabled behavior. Now that Add is enabled, two valid shapes:
  - **(a) Drop the Add wrapper entirely** — Add becomes a bare `QPushButton` in the row layout. The Edit/Delete wrappers stay. Layout spacing changes slightly because the wrapper had its own margins (0,0,0,0, so impact is minor).
  - **(b) Keep the wrapper with no tooltip** — `wrapper.setToolTip("")`. Layout stays identical to S-05. Cost: a one-widget wrapper around an enabled button serves no purpose.
  - **Pick (a).** A test asserts `dialog._reminders_add_button.parentWidget()` is the row container (not a wrapper). Layout drift between S-05 and S-06 is acceptable here because the row is functionally different (one of three buttons is now actionable).

- **Refresh hook timing.** The `reminder_added` signal must fire **before** `super().accept()` in `ReminderFormDialog.accept()` — otherwise `exec()` returns and the connected slot runs after the dialog has already been deleted. Production order: `validate → add → reload → emit reminder_added → super().accept()`. A test pins this by connecting a recording slot to `reminder_added` and asserting the slot ran while `dialog.isVisible() == True` (or simpler: assert the slot ran before `dialog.exec()` returned, which requires a non-modal test setup — easiest is to bypass `exec()` and call `accept()` directly, then assert the slot fired).

- **Tab-rebuild and stored references.** `_refresh_reminders_tab()` does `self._tabs.removeTab(idx)` + `self._tabs.insertTab(idx, self._build_reminders_tab(), REMINDERS_TAB_LABEL)`. The index is `self._tabs.indexOf(self._reminders_tab)` captured **before** `removeTab`. After `insertTab`, `self._reminders_tab` must be re-set to the new widget (the old one is owned by Qt and gets garbage-collected). `_build_reminders_tab()` itself doesn't store `self._reminders_tab` today (S-05 chose not to); S-06 adds that store line at the top of the method, right after `tab = QWidget(self._tabs)`.

- **Test stub for the sub-dialog.** Don't run `ReminderFormDialog.exec()` in `test_settings_dialog.py` tests (it would block the event loop). Instead: monkeypatch `break_reminder.ui.settings_dialog.ReminderFormDialog` with a recording stub that captures the constructor kwargs and exposes a `.reminder_added` signal the test can manually `emit()`. Tests for `ReminderFormDialog` itself (in `test_reminder_form_dialog.py`) construct it directly with `qtbot.addWidget(dialog)`, manipulate fields, call `dialog.accept()` directly.

- **Default fire_at computation.** "Now + 1 hour rounded up to the next quarter-hour" is **clock-dependent**, so the default-value tests must inject a frozen clock through the `clock` constructor parameter (mirrors `BreakScheduler` tests). The dialog reads `self._clock()` once in `__init__` to seed the `QDateTimeEdit` default, and a test asserts `widget.dateTime().toPython()` equals the expected derived instant.

- **`Reminder` import in `ui/settings_dialog.py` already exists** (per S-05 imports — `Reminder` is used by `_sort_key`, `_compose_row`). `ReminderScheduler` is a new import in `ui/settings_dialog.py` for the constructor type annotation.

## Phase 1: Implementation

### Overview

Land the entire user-visible change in one phase: the scheduler clock-injection refactor, the new `ReminderFormDialog` module, the settings-dialog extensions (constructor arg, tab storage, Add button enablement, slot wiring, refresh handler), the two new test files, the extension to `tests/test_settings_dialog.py`, and the AGENTS.md tightening. The phase exits when `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pip-audit`, and `uv run pip-licenses --fail-on="AGPL"` are all green.

### Changes Required:

#### 1. `ReminderScheduler` — accept a `clock` callable

**File**: `break_reminder/scheduler.py`

**Intent**: Mirror `BreakScheduler`'s clock-injection pattern so the new `tests/test_reminder_scheduler.py` can drive "add → reload → fire" deterministically without waiting for wall-clock seconds. Reuses the module-level `_utcnow` helper already at `scheduler.py:43-45`. App-side construction at `app.py:102` does not need to change — production keeps the default `None`.

**Contract**: New constructor signature `def __init__(self, *, store: ReminderStore, parent: QObject | None = None, clock: Callable[[], datetime] | None = None) -> None`. New stored attribute `self._clock = clock or _utcnow`. Replace `datetime.now(UTC)` at three sites with `self._clock()`:

```
scheduler.py:261  ms = max(0, int((self._next.fire_at - self._clock()).total_seconds() * 1000))
scheduler.py:271  now = self._clock()
scheduler.py:286  now = self._clock()
```

The docstring for `clock` mirrors `BreakScheduler`'s docstring at `scheduler.py:77-78`.

#### 2. `ReminderFormDialog` — new module

**File**: `break_reminder/ui/reminder_form_dialog.py` (NEW)

**Intent**: A modal sub-dialog launched by the Reminders tab's Add button. Contains a Name `QLineEdit` and a Date/time `QDateTimeEdit`, an OK/Cancel `QDialogButtonBox`, and validation gates that mirror the voice-phrase pattern. On successful save: persists via `ReminderStore.add()`, arms via `ReminderScheduler.reload()`, emits `reminder_added` with the saved `Reminder`, then `super().accept()`.

**Contract**: New module exposes one public class:

```python
class ReminderFormDialog(QDialog):
    reminder_added = Signal(Reminder)

    def __init__(
        self,
        *,
        store: ReminderStore,
        scheduler: ReminderScheduler,
        clock: Callable[[], datetime] | None = None,
        parent: QWidget | None = None,
    ) -> None: ...

    def accept(self) -> None: ...   # validates → add → reload → emit → super().accept()
```

Stored attributes after `__init__`: `self._store`, `self._scheduler`, `self._clock`, `self._name_field: QLineEdit`, `self._datetime_field: QDateTimeEdit`, `self._buttons: QDialogButtonBox`. Module-level constants: `_DEFAULT_OFFSET_HOURS = 1`, `_DEFAULT_ROUND_MINUTES = 15`, `_DATETIME_DISPLAY_FORMAT = "ddd yyyy-MM-dd HH:mm"`, `_NAME_PLACEHOLDER = "e.g., Visit to dentist"`, `_NAME_EMPTY_MESSAGE = "Name cannot be empty"`, `_PAST_TIME_MESSAGE = "Time must be in the future"`, `_SAVE_FAILED_FORMAT = "Could not save reminder: {error}"`. Minimum dialog width follows the visual proportion of `ReminderDialog` (no explicit floor unless the default is awkward — try without first).

**Default `fire_at` computation (load-bearing — clock returns UTC, widget displays local).** `self._clock()` returns a tz-aware UTC datetime via the `_utcnow` default. `QDateTimeEdit` displays and round-trips **naive local** values. The seeding flow must convert explicitly:

```
utc_now = self._clock()                                # tz-aware UTC
local_now = utc_now.astimezone()                        # tz-aware system local
local_plus_offset = local_now + timedelta(hours=_DEFAULT_OFFSET_HOURS)
# Round UP to the next _DEFAULT_ROUND_MINUTES boundary on the minute field
remainder = local_plus_offset.minute % _DEFAULT_ROUND_MINUTES
if remainder or local_plus_offset.second or local_plus_offset.microsecond:
    bump = _DEFAULT_ROUND_MINUTES - remainder
    local_rounded = (local_plus_offset + timedelta(minutes=bump)).replace(second=0, microsecond=0)
else:
    local_rounded = local_plus_offset.replace(second=0, microsecond=0)
naive_local = local_rounded.replace(tzinfo=None)        # widget wants naive
self._datetime_field.setDateTime(QDateTime(naive_local))
```

The widget thereafter returns `widget.dateTime().toPython()` as the same **naive-local** value. The local→UTC conversion at save time is the inverse (Critical Implementation Details: "Local→UTC conversion at save time").

`accept()` body order is load-bearing: validate-name → validate-datetime → construct Reminder → try store.add(): except OSError gate → scheduler.reload() → self.reminder_added.emit(reminder) → super().accept(). The emit-before-super-accept ordering is pinned in "Critical Implementation Details" (otherwise the connected slot runs after `exec()` has returned).

#### 3. `SettingsDialog.__init__` — accept `ReminderScheduler`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Add a required keyword-only `reminder_scheduler: ReminderScheduler` parameter to the constructor (mirrors `reminder_store`). Store on `self._reminder_scheduler`. Add `ReminderScheduler` to the imports.

**Contract**: New signature is `def __init__(self, *, settings: Settings, voice: VoiceNotifier, reminder_store: ReminderStore, reminder_scheduler: ReminderScheduler, parent: QWidget | None = None) -> None`. New import `from break_reminder.scheduler import ReminderScheduler` added to the existing scheduler-namespace import block at the top of the file (or merged with the existing `from break_reminder.scheduler import next_firing_after`). New stored attribute `self._reminder_scheduler`.

#### 4. `_build_reminders_tab()` — store the tab on `self`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Amend the S-05 rule that the Reminders tab is not stored on `self`. The rebuild handler needs to address the tab to call `self._tabs.indexOf(self._reminders_tab)`. Document the new reason in a comment.

**Contract**: At the top of `_build_reminders_tab()` (after `tab = QWidget(self._tabs)` at `ui/settings_dialog.py:594`), add `self._reminders_tab = tab`. Update the existing comment block at `ui/settings_dialog.py:442-446` (the "stored only when accept() needs it" rule) to note that the Reminders tab is also stored because the Add-save refresh handler needs to remove + re-insert it.

#### 5. `_build_reminders_button_row()` — enable the Add button

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Drop the disabled state, drop the wrapper, drop the tooltip on the Add button. Wire its `clicked` signal to the new `_on_reminders_add_clicked` slot. Edit and Delete buttons stay wrapped + disabled (per S-07 ownership).

**Contract**: The Add button no longer goes through the wrapper loop (`ui/settings_dialog.py:667-680`). Restructure that loop to apply only to Edit + Delete. Add button is added directly to `row_layout` (between `addStretch(1)` and the Edit/Delete wrappers). New connection `self._reminders_add_button.clicked.connect(self._on_reminders_add_clicked)`. The button label stays `"Add…"` (ellipsis convention for affordances that open sub-dialogs).

#### 6. `_on_reminders_add_clicked()` slot

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Construct a `ReminderFormDialog` with the injected store + scheduler, parent it to `self`, connect its `reminder_added` signal to `_refresh_reminders_tab`, and call `dialog.exec()` (modal). The connection must be established **before** `exec()` because the signal is emitted from inside `accept()`, which runs before `exec()` returns.

**Contract**: Method signature `def _on_reminders_add_clicked(self) -> None`. The signal connection uses a slot that discards the `Reminder` argument (the tab-refresh doesn't need it): `dialog.reminder_added.connect(lambda _reminder: self._refresh_reminders_tab())` (or define `_refresh_reminders_tab` to accept and ignore the arg). Picking the latter shape avoids the lambda — `def _refresh_reminders_tab(self, _reminder: Reminder | None = None) -> None`.

#### 7. `_refresh_reminders_tab()` slot

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Remove the current Reminders tab and reinsert a freshly-built one at the same index. Re-uses `_build_reminders_tab()` verbatim so the sort, compose, and empty→list transition all reuse the S-05 helpers.

**Contract**: Method signature `def _refresh_reminders_tab(self, _reminder: Reminder | None = None) -> None`. Body (order is load-bearing):

1. `idx = self._tabs.indexOf(self._reminders_tab)` — capture before any mutation.
2. `old_tab = self._reminders_tab` — capture the old widget reference so it can be scheduled for deletion.
3. `self._tabs.removeTab(idx)` — removes the page from the tab strip but does NOT delete the underlying QWidget (Qt keeps it parented to the SettingsDialog).
4. `old_tab.deleteLater()` — schedules the orphan tab for deletion on the next event-loop iteration so it doesn't leak across repeated Add clicks. Without this, every Add would parent a stale `QWidget` to `SettingsDialog` until the dialog closes; bounded for the persona's usage but tidier to release explicitly.
5. `self._build_reminders_tab()` — already assigns `self._reminders_tab` per change #4; no separate assignment needed.
6. `self._tabs.insertTab(idx, self._reminders_tab, self.REMINDERS_TAB_LABEL)` — uses the existing `SettingsDialog.REMINDERS_TAB_LABEL` constant from S-05.

The `_reminder` parameter exists only to absorb the signal payload — it's discarded.

#### 8. `app.py` — pass `reminder_scheduler` into `SettingsDialog`

**File**: `break_reminder/app.py`

**Intent**: Update the single construction site at `app.py:330-334` to pass `reminder_scheduler=self._reminder_scheduler`.

**Contract**: One-line addition to the kwargs block:

```python
SettingsDialog(
    settings=self._settings,
    voice=self._voice,
    reminder_store=self._reminder_store,
    reminder_scheduler=self._reminder_scheduler,
).exec()
```

#### 9. New test file: `tests/test_reminder_scheduler.py`

**File**: `tests/test_reminder_scheduler.py` (NEW)

**Intent**: Pin the clock-injection contract and the arm-on-reload behavior. Mirror `tests/test_break_scheduler.py`'s `Clock` fixture pattern at `tests/test_break_scheduler.py:35-48` for deterministic time control.

**Contract**: Test classes:
- `TestClockInjection`: production-default uses `_utcnow` (construct with `clock=None`, assert `_clock is _utcnow`); custom callable is honored.
- `TestReloadArmsNewReminder`: construct `ReminderScheduler` with a frozen clock, empty store; `reload()` → `_timer.isActive() is False`; `store.add(Reminder(name="X", start_at=frozen_now + 10s))`; `reload()` → `_timer.isActive() is True` and `_timer.interval()` is approximately 10000ms (tolerate ±100ms for the float arithmetic). This is the regression test for "save path called reload but reminder still doesn't fire".
- `TestReloadHandlesFarFuture`: reminder 30 days out; `reload()` arms the timer with `min(ms, 24h_ms)`. Asserts `_timer.interval() == 24*60*60*1000`.
- `TestReloadOnEmptyStore`: reload with no reminders leaves `_next is None` and `_timer.isActive() is False` (no crash).

#### 10. New test file: `tests/test_reminder_form_dialog.py`

**File**: `tests/test_reminder_form_dialog.py` (NEW)

**Intent**: Pin every `ReminderFormDialog` behavior. Test classes mirror `tests/test_settings_dialog.py`'s `TestRemindersTab` shape.

**Contract**: Fixtures: `qtbot` (pytest-qt), `tmp_path`, `reminder_store` (tmp-path-bound `ReminderStore`), `frozen_clock` (returns a fixed `datetime(2026, 6, 1, 10, 0, tzinfo=UTC)`), `scheduler_stub` (a `MagicMock` with `.reload` attribute; **not** a real `ReminderScheduler` — the dialog's contract with the scheduler is just `reload()` and `MagicMock` proves the call without booting Qt timers).

Test classes:
- `TestReminderFormDialogDefaults`:
  - `test_name_field_empty_at_construction`
  - `test_name_field_has_placeholder`
  - `test_datetime_field_defaults_to_frozen_now_plus_offset_rounded` — inject a frozen clock returning a known UTC instant; compute the expected **naive-local** value via `frozen_utc.astimezone() + timedelta(hours=1)`, then round up to the next 15-minute boundary, then `.replace(second=0, microsecond=0, tzinfo=None)`. Assert `widget.dateTime().toPython() == expected_naive_local`. The conversion must be computed by the test (not hardcoded) so it works on any CI runner regardless of its system zone. See Phase 1 #2 Contract for the exact seeding flow being verified.
  - `test_datetime_field_uses_calendar_popup` — `widget.calendarPopup() is True`.
  - `test_datetime_field_display_format` — `widget.displayFormat() == "ddd yyyy-MM-dd HH:mm"`.

- `TestReminderFormDialogValidation`:
  - `test_empty_name_blocks_save_and_shows_tooltip` — set name to `"   "`, set datetime to valid future, click OK (or call `accept()` directly), assert `dialog.isVisible()` stays True (or use the monkeypatched `QToolTip.showText` recorder to assert the message), assert `reminder_store.list_all() == []`, assert `scheduler_stub.reload.call_count == 0`.
  - `test_past_datetime_blocks_save_and_shows_tooltip` — set name to "X", set datetime to `frozen_now - 1h`, attempt save, assert nothing persisted + nothing reloaded + tooltip "Time must be in the future" was shown.
  - `test_name_validation_wins_over_datetime_validation` — set BOTH name empty AND datetime in the past; assert only the name tooltip fires (first-failing-field-wins; mirrors voice-phrase pattern).
  - `test_validation_failure_does_not_emit_reminder_added` — connect a recording slot to `reminder_added`, trigger a validation failure, assert slot was not called.

- `TestReminderFormDialogSave`:
  - `test_successful_save_persists_one_reminder_with_correct_fields` — set name "Visit to dentist", set datetime to a known local instant, accept(), assert `reminder_store.list_all()` has exactly one entry with `name == "Visit to dentist"`, `start_at == known_utc_equivalent` (tz-aware compare), `rrule_str is None`, `end_at is None`, `id` is a non-empty string.
  - `test_successful_save_strips_name_whitespace` — set name `"  Spaced name  "`, accept, assert stored `name == "Spaced name"`.
  - `test_successful_save_calls_scheduler_reload_exactly_once` — assert `scheduler_stub.reload.call_count == 1`.
  - `test_successful_save_emits_reminder_added_with_saved_reminder` — connect recorder, accept, assert one signal received, payload is the saved `Reminder`.
  - `test_save_emits_reminder_added_before_super_accept` — connect a recording slot to `reminder_added` that captures `dialog.result()` at emit time. Call `dialog.accept()` directly (no `exec()`). Assert the recorded `result` was `QDialog.DialogCode.Rejected` (the default state — `super().accept()` hadn't yet flipped it to `Accepted` when the signal fired, proving emit ran first). After `accept()` returns, assert `dialog.result() == QDialog.DialogCode.Accepted`. **This is the regression test for the load-bearing ordering in "Critical Implementation Details".** (Avoids monkeypatching `QDialog.accept` which would leak across every `QDialog` in the test process.)
  - `test_local_to_utc_conversion` — set the `QDateTimeEdit` to a known local wall-clock value, accept, assert `reminder_store.list_all()[0].start_at` equals the known UTC equivalent computed manually. Test runs on any CI runner regardless of system timezone.
  - `test_oserror_on_store_add_blocks_dialog_and_shows_tooltip` — monkeypatch `ReminderStore.add` to raise `OSError(13, "Permission denied")`, attempt save, assert dialog stays open (or, in non-exec setup: `super().accept()` was NOT called), assert `scheduler_stub.reload.call_count == 0`, assert tooltip shown with the message containing "Permission denied", assert `reminder_added` was NOT emitted.

- `TestReminderFormDialogCancel`:
  - `test_cancel_does_not_persist_or_reload` — set valid fields, call `reject()`, assert `reminder_store.list_all() == []` and `scheduler_stub.reload.call_count == 0`.
  - `test_cancel_does_not_emit_reminder_added` — connect recorder, reject, assert slot was not called.

- `TestReminderFormDialogAtomicSaveTripwire`:
  - `test_validation_failure_does_not_write_partial_state` — pre-seed `reminder_store` with one entry, attempt save with empty name, assert `reminder_store.list_all()` still has exactly the one pre-seeded entry (byte-identical). This is the parallel to `TestNotificationsTabValidation::test_voice_on_blank_phrase_blocks_save` for the new form. Pin both the name-empty branch and the past-time branch (two test methods).

#### 11. Extend `tests/test_settings_dialog.py`

**File**: `tests/test_settings_dialog.py`

**Intent**: Update fixtures + every `SettingsDialog(...)` construction (19 callsites) to pass `reminder_scheduler=`, extend the S-05 `TestRemindersTab` tests to cover the rebuild-friendly `list_all` invariant, add a new `TestRemindersAddButton` test class.

**Exact sweep scope** — 19 direct `SettingsDialog(...)` constructions to update (the count grew by 1 between S-05 and now). Run `rg -n 'SettingsDialog\(' tests/test_settings_dialog.py` after the sweep to confirm every match passes `reminder_scheduler=...` (or no longer constructs directly because it switched to the `dialog` fixture).

**Contract**:

New fixtures:
```python
@pytest.fixture
def reminder_scheduler(reminder_store: ReminderStore) -> ReminderScheduler:
    """A ReminderScheduler bound to the per-test reminder_store fixture."""
    return ReminderScheduler(store=reminder_store)
```

Updated `dialog` fixture signature includes `reminder_scheduler: ReminderScheduler` and threads it into `SettingsDialog(...)`.

Updated test in S-05's `TestRemindersTab`:
- `test_list_all_called_exactly_once` — assertion changes from "exactly 1 call across the dialog's lifetime" to "exactly 1 call per `_build_reminders_tab()` invocation". Concretely: spy on `list_all`, construct dialog (count=1), switch tabs back and forth (count stays at 1), explicitly call `dialog._refresh_reminders_tab()` (count=2). The "no live refresh on tab switch" invariant survives; the "refresh on add" invariant joins it.

New test class `TestRemindersAddButton`:
- `test_add_button_is_enabled` — `dialog._reminders_add_button.isEnabled() is True`.
- `test_add_button_has_no_wrapper_tooltip` — assert `dialog._reminders_add_button.parentWidget().toolTip() == ""`. The row container has no tooltip; a single-widget wrapper would have inherited `_REMINDERS_BUTTONS_DISABLED_TOOLTIP`. (The "count children" alternative is a tautology — the row layout has the same number of widgets whether Add is wrapped or bare — so it doesn't actually pin the invariant.)
- `test_edit_and_delete_buttons_remain_wrapped_and_disabled` — Edit and Delete are still inside wrappers; wrappers still carry `_REMINDERS_BUTTONS_DISABLED_TOOLTIP`.
- `test_add_button_click_opens_sub_dialog` — monkeypatch `break_reminder.ui.settings_dialog.ReminderFormDialog` with a recording stub class; `dialog._reminders_add_button.click()`; assert the stub was constructed once with `store=dialog._reminder_store, scheduler=dialog._reminder_scheduler, parent=dialog`. (The stub class's `exec` returns `QDialog.Rejected` immediately so the click handler returns cleanly.)
- `test_reminder_added_signal_triggers_tab_refresh` — monkeypatch `ReminderFormDialog` with a stub that exposes a `reminder_added` Signal and `exec` that emits the signal then returns `Accepted`; pre-seed the store with one reminder; click Add; assert the new `_reminders_tab` reference is different from the old one (i.e., `removeTab` + `insertTab` happened) AND the list contains the row from the emitted Reminder.
- `test_tab_index_preserved_across_refresh` — assert `dialog._tabs.indexOf(dialog._reminders_tab) == 3` both before and after a refresh (the Reminders tab stays in position 4).

#### 12. `AGENTS.md` — tighten the Custom-reminder bullet to reflect Add shipped

**File**: `AGENTS.md`

**Intent**: The current bullet at AGENTS.md:184 reads `"Custom-reminder editor dialog — Add / Edit / Delete wiring (FR-011 / FR-012 CRUD). The read-only Reminders tab inside the settings window shipped in S-05; the click handlers behind \`Add…\` / \`Edit…\` / \`Delete\` are wired but no-op until S-06 / S-07."` (the trailing clause is itself slightly inaccurate — only `_on_reminders_selection_changed` is wired today, not the click signals). After S-06, Add is fully wired and only Edit/Delete remain pending. Rewrite the bullet so its scope narrows correctly and its descriptive clause stays accurate.

**Contract**: Replace the entire bullet at AGENTS.md:184 with:

```
- Custom-reminder Edit / Delete dialog wiring (FR-012). The read-only Reminders tab shipped in S-05; the `Add…` click handler shipped in S-06; `Edit…` / `Delete` are still wired no-op until S-07.
```

The phrase fragment `"Custom-reminder editor dialog"` no longer appears — this is what the Phase 2.1 grep verifies (see below).

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v`
- Unit tests pass: `uv run pytest tests/test_reminder_scheduler.py -v`
- Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestRemindersAddButton` and updated `TestRemindersTab::test_list_all_called_exactly_once`)
- Full suite passes: `uv run pytest`
- Type check passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Format check passes: `uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual Verification:

- Open Settings → Reminders with an empty `reminders.json`: Add button is now enabled (no longer shows the "coming in a future update" tooltip); Edit and Delete still show the tooltip and are visibly disabled.
- Click Add: a small modal sub-dialog opens with a Name field (empty, placeholder "e.g., Visit to dentist") and a Date/time field (defaulted to roughly now + 1 hour, calendar dropdown works when clicked).
- Click OK with the name empty: tooltip "Name cannot be empty" appears below the name field; dialog stays open.
- Set name to "X", click the date/time field, dial it backward to 5 minutes ago, click OK: tooltip "Time must be in the future" appears below the datetime field; dialog stays open.
- Set name to "Test reminder", set time to ~30 seconds from now, click OK: sub-dialog closes; the new row appears in the Reminders list at the correct sort position; wait 30 seconds; the `ReminderDialog` popup fires showing "Test reminder".
- Click Add again, click Cancel: sub-dialog closes; the Reminders list is unchanged; `reminders.json` on disk is unchanged.
- Edge case: with the Reminders tab open and one reminder in the list, switch to Scheduling and back: rows are still rendered (the rebuild only happens on Add, not on tab switch).
- No regressions: Scheduling, Notifications, Lifecycle tabs continue to behave as before (spinboxes, voice toggle, autostart checkbox; OK still saves; Cancel still discards).

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation that the manual checks above were successful before proceeding to Phase 2.

---

## Phase 2: Manual smoke + bookkeeping

### Overview

Move the slice from "implemented" to "shipped + traceable": confirm the add-and-fire flow works under real Windows, then mark every document that tracks this slice's status. No code changes in this phase.

### Changes Required:

#### 1. Manual smoke run

**File**: n/a — operational step

**Intent**: With the new dialog deployed locally (via `uv run python -m break_reminder`), perform the manual verification steps from Phase 1 against a real Windows session. Document the run in the slice's `change.md` "Notes" section if anything unexpected surfaces; if smooth, no doc update needed.

**Contract**: Steps:
1. Stop any running BreakReminder.
2. Delete or empty `%APPDATA%\BreakReminder\reminders.json`.
3. Run `uv run python -m break_reminder`; open Settings → Reminders; confirm Add is enabled, Edit/Delete still disabled with tooltip.
4. Click Add; confirm sub-dialog opens; trigger name-empty validation (OK with empty name); trigger past-time validation (OK with past datetime); cancel out.
5. Click Add; name = "Smoke test", datetime = now + ~45 seconds; OK; confirm row appears in list.
6. Wait for the popup to fire; click OK on the popup.
7. Re-open Settings → Reminders; confirm "Smoke test" still shows in the list (the popup firing doesn't delete the reminder — that's S-09 territory, if ever; one-shot reminders simply become `(expired)` after firing).
8. Inspect `%APPDATA%\BreakReminder\reminders.json` directly in Notepad — confirm the saved entry is well-formed JSON with `start_at` in ISO 8601 UTC.

#### 2. Update `change.md`

**File**: `context/changes/reminders-add-form/change.md`

**Intent**: Flip `status: planned` → `status: implemented`. Update `updated:` to today's date. Add a brief "Implementation note" subsection if anything notable surfaced in the smoke run.

**Contract**: YAML front-matter `status` value changes; `updated` date refreshes. Optional `## Notes` subsection appended (already a Notes section in `change.md`; append a "Implementation note" sub-heading if needed).

#### 3. Update `roadmap.md`

**File**: `context/foundation/roadmap.md`

**Intent**: Flip the S-06 row in "At a glance" from `proposed` to `done`. Update the slice's `### S-06` block: change `**Status:** proposed` to `**Status:** done`; append a "Scope addendum shipped" line if anything diverged from the original outcome wording. Add a `## Done` entry capturing one lesson learned (or `Lesson: —.` if none).

**Contract**: Three substitutions in `roadmap.md`:
1. `| S-06 | reminders-add-form | ... | proposed |` (the "At a glance" table row at line 37) → `| S-06 | reminders-add-form | ... | done |`
2. `- **Status:** proposed` (inside `### S-06` body block at line 158) → `- **Status:** done`
3. New `### S-06` entry appended to the `## Done` section with a one-line lesson distilled from the implementation (e.g., "Lesson: a `reminder_added` signal must be emitted before `super().accept()` — connecting a slot after `exec()` returns is too late because the dialog is already destroyed."), or `Lesson: —.` if smooth.

The second roadmap.md table at line 193 (the "Up next" / similar checklist that lists S-06 with columns `id | change-id | summary | blocked | sequence`) has **no status column** — leave it unchanged. The "no" in that row is the blocked-flag column, not a status.

#### 4. Update `AGENTS.md`

**File**: `AGENTS.md`

**Intent**: Verify the change from Phase 1 #12 actually landed (the bullet rewrite to "Custom-reminder Edit / Delete dialog wiring"). No additional edit needed here unless Phase 1 missed it.

**Contract**: `git grep -nE 'Custom-reminder editor dialog' AGENTS.md` returns no matches (the old phrase fragment was eliminated). `git grep -nE 'Custom-reminder Edit / Delete dialog wiring' AGENTS.md` returns exactly one match (the new bullet).

#### 5. Tick the Progress section

**File**: `context/changes/reminders-add-form/plan.md`

**Intent**: Mark every Phase 1 and Phase 2 progress item complete, with the merge commit SHA appended per `references/progress-format.md`.

**Contract**: `- [ ]` → `- [x] — <sha>` for each line in the Progress section below.

### Success Criteria:

#### Automated Verification:

- `git grep -nE 'Custom-reminder editor dialog' AGENTS.md` returns no matches (the phrase fragment was eliminated by the Phase 1 #12 rewrite).
- `git grep -nE '^\| S-06 .*proposed' context/foundation/roadmap.md` returns no matches (status flipped). Use the row-anchored pattern (not just `S-06.*proposed`) to avoid false matches from S-07's "Prerequisites: S-06" mention.
- `git diff context/changes/reminders-add-form/change.md` shows `status: implemented` and an updated `updated:` date.

#### Manual Verification:

- Real Windows: empty `reminders.json` → Add enabled, sub-dialog opens (Phase 2.1 step 3).
- Real Windows: validation tooltips fire on empty-name OK and past-time OK; dialog stays open in both cases (Phase 2.1 step 4).
- Real Windows: Add a "Smoke test" reminder 45 seconds out → row appears → popup fires (Phase 2.1 step 5-6).
- `reminders.json` inspected in Notepad shows well-formed JSON with `start_at` in ISO 8601 UTC (Phase 2.1 step 8).
- No regression in Scheduling / Notifications / Lifecycle tabs.

**Implementation Note**: After completing all checks above, the slice is done. The next slice in Stream B is S-07 (`reminders-edit-delete`), unblocked by this slice landing.

---

## Testing Strategy

### Unit Tests:

- **Scheduler (`tests/test_reminder_scheduler.py` — NEW).** Pin the clock-injection contract; pin the arm-after-reload semantics for one-shot, recurring, and far-future reminders; pin the empty-store no-crash case. Uses a frozen clock fixture mirroring `tests/test_break_scheduler.py:35-48`.
- **Form dialog (`tests/test_reminder_form_dialog.py` — NEW).** Cover defaults (name empty, datetime = clock + offset rounded, calendar popup, display format); validation gates (name-empty, past-time, first-failing-field-wins); save path (persistence, scheduler reload, signal emit, local→UTC conversion); OSError gate (no persistence, no reload, no emit, tooltip shown, dialog stays open); cancel path (no side effects); atomic-save tripwire (validation failures leave the store byte-identical).
- **Settings dialog (`tests/test_settings_dialog.py`).** Extend with `TestRemindersAddButton` covering: Add button enabled, no wrapper tooltip, Edit/Delete still wrapped and disabled, click constructs the sub-dialog with the right args (via monkeypatched class), `reminder_added` signal triggers tab refresh, tab index preserved across refresh. Update the existing `test_list_all_called_exactly_once` to assert per-build invariance rather than lifetime invariance.

### Integration Tests:

- **`tests/test_app.py` smoke.** Existing app-level tests construct `BreakReminderApp` end-to-end but do not open Settings. They must continue to pass unchanged after the `_on_open_settings` constructor-arg addition (`reminder_scheduler=self._reminder_scheduler`).
- **No new integration test file.** A full "click Add → row appears → wait for popup" end-to-end test would require a real event loop with timed waits and is best left to the manual smoke run. The unit-test coverage of each link in the chain (form save → store.add → scheduler.reload → tab rebuild) is sufficient.

### Manual Testing Steps:

1. **Empty-store add path.** Stop app; delete `%APPDATA%\BreakReminder\reminders.json`; start app; Settings → Reminders; click Add; fill name + time = now + 45s; OK; confirm row appears; wait 45s; confirm popup fires.
2. **Validation paths.** From the same Reminders tab: click Add; OK with empty name (tooltip); set name "X", OK with datetime in the past (tooltip); Cancel.
3. **OSError handling (optional / skipped in normal smoke).** Hard to trigger naturally; covered by unit test only.
4. **Reload-on-add (the load-bearing piece).** The 45-second popup firing in step 1 IS the manual verification that `reminder_scheduler.reload()` was called — if it weren't, the popup would never fire because the scheduler was constructed before the reminder existed.
5. **List rebuild correctness.** From step 1's state, click Add again; add a second reminder with time = now + 2 minutes; OK; confirm both rows render in the correct sort order (closest future first).
6. **No-regression.** Edit the Scheduling tab's break interval; OK; confirm `BreakReminder.ini` updates. Re-open Settings; confirm the new interval persisted and the Reminders tab still shows the test reminder.

## Performance Considerations

- **`reload()` cost.** Re-reads `ReminderStore.list_all()` (a single JSON file read) and runs `next_firing_after` once per reminder. For the persona's expected ≤ 10 reminders, this is sub-millisecond. Called once per add — no concern.
- **Tab rebuild cost.** `removeTab` + `insertTab` + `_build_reminders_tab` (which itself does `list_all` + sort + N row constructions). For ≤ 10 reminders, sub-millisecond. The user perceives the rebuild as instant.
- **`QDateTimeEdit` calendar popup.** Native widget, no perf concern.
- **No async, no background thread.** Add save path is synchronous on the GUI thread.

## Migration Notes

- **No data migration.** `reminders.json` schema is unchanged. Existing entries hand-edited before S-06 continue to work — the schema already supported the fields S-06 populates.
- **No setting migration.** No new `Settings` keys.
- **No installer/PyInstaller change.** Same release pipeline; no `--add-data`, no `--hidden-import` deltas.

## References

- Roadmap entry: `context/foundation/roadmap.md` § S-06
- PRD: `context/foundation/prd.md` FR-011 (line 123), FR-013 (line 127), FR-005 (line 103)
- S-05 plan (pattern precedent for the Reminders tab + module-level helpers): `context/archive/2026-05-27-reminders-list-view/plan.md`
- S-04 plan (pattern precedent for atomic-save validation gate + tooltip anchoring): `context/archive/2026-05-25-settings-voice-toggle/`
- Storage layer: `break_reminder/storage/reminders.py:27-99` (`Reminder` + `ReminderStore.add`)
- Scheduler arm-on-add hook: `break_reminder/scheduler.py:255-264` (`ReminderScheduler.reload`)
- Scheduler clock-injection template: `break_reminder/scheduler.py:60-86` (`BreakScheduler.__init__`)
- Existing sub-dialog precedent (style, button layout): `break_reminder/notifications/reminder_dialog.py:24-55`
- Reminders tab (S-05): `break_reminder/ui/settings_dialog.py:590-720`
- App wiring: `break_reminder/app.py:102` (`ReminderScheduler` construction), `:330-334` (`SettingsDialog(...)` call)
- Existing clock fixture pattern: `tests/test_break_scheduler.py:35-48`
- Existing validation-gate test pattern (atomic-save tripwire): `tests/test_settings_dialog.py:757-840`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Implementation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v` — 33a665f
- [x] 1.2 Unit tests pass: `uv run pytest tests/test_reminder_scheduler.py -v` — 33a665f
- [x] 1.3 Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestRemindersAddButton` and updated `TestRemindersTab::test_list_all_called_exactly_once`) — 33a665f
- [x] 1.4 Full suite passes: `uv run pytest` — 33a665f
- [x] 1.5 Type check passes: `uv run pyright` — 33a665f
- [x] 1.6 Linting passes: `uv run ruff check` — 33a665f
- [x] 1.7 Format check passes: `uv run ruff format --check` — 33a665f
- [x] 1.8 Security audit passes: `uv run pip-audit` — 33a665f
- [x] 1.9 License gate passes: `uv run pip-licenses --fail-on="AGPL"` — 33a665f

#### Manual

- [x] 1.10 Add button is enabled (no wrapper tooltip); Edit/Delete still wrapped + disabled — 33a665f
- [x] 1.11 Click Add opens the sub-dialog with name field empty + datetime field defaulted to ~now+1h — 33a665f
- [x] 1.12 Empty-name OK shows tooltip; dialog stays open; nothing persisted — 33a665f
- [x] 1.13 Past-time OK shows tooltip; dialog stays open; nothing persisted — 33a665f
- [x] 1.14 Valid Add (~30s out) closes the sub-dialog; new row appears in list; popup fires at the chosen instant — 33a665f
- [x] 1.15 Cancel closes the sub-dialog with no side effects (list unchanged, `reminders.json` unchanged on disk) — 33a665f
- [x] 1.16 Tab-switch behavior unchanged: switching Scheduling↔Reminders does not refresh the list — 33a665f
- [x] 1.17 No regressions: Scheduling / Notifications / Lifecycle tabs still functional — 33a665f

### Phase 2: Manual smoke + bookkeeping

#### Automated

- [x] 2.1 `git grep -nE 'Custom-reminder editor dialog' AGENTS.md` returns no matches — beba743
- [x] 2.2 `git grep -nE '^\| S-06 .*proposed' context/foundation/roadmap.md` returns no matches — beba743
- [x] 2.3 `git diff context/changes/reminders-add-form/change.md` shows `status: implemented` and updated `updated:` date — beba743

> **Adaptation (matching S-05's Phase 2 precedent)**: Plan #3's bullet 3 called for appending a new `### S-06` entry to the `## Done` section now. Historical practice (commit `b19628a` for S-05) defers that to archive time (`/10x-archive` adds the entry when it moves the folder under `context/archive/`). Following the established convention; the Done entry will land with the archive commit, not the Phase 2 commit.

#### Manual

- [x] 2.4 Real Windows: empty `reminders.json` → Add enabled, sub-dialog opens (Phase 2.1 step 3) — beba743 (rolled forward from Phase 1 smoke 1.10, 1.11)
- [x] 2.5 Real Windows: validation tooltips fire on empty-name OK and past-time OK; dialog stays open in both cases (Phase 2.1 step 4) — beba743 (rolled forward from Phase 1 smoke 1.12, 1.13)
- [x] 2.6 Real Windows: Add an empty-store reminder ~45s out, row appears, popup fires (Phase 2.1 step 5-6) — beba743 (rolled forward from Phase 1 smoke 1.14)
- [x] 2.7 Real Windows: `reminders.json` in Notepad shows well-formed JSON with ISO 8601 UTC `start_at` (Phase 2.1 step 8) — beba743
- [x] 2.8 No regression in Scheduling / Notifications / Lifecycle tabs — beba743 (rolled forward from Phase 1 smoke 1.17)
