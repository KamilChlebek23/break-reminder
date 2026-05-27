# Reminders List View Implementation Plan

## Overview

Add a fourth "Reminders" tab to `SettingsDialog` that reads `ReminderStore.list_all()` once at construction and renders each reminder as `"<name>  —  <next firing | (expired)>"` in a `QListWidget`, sorted chronologically (soonest first, expired last, tiebreak by name). When the store is empty, the list is replaced by a centered placeholder `QLabel`. Below the list, three buttons — `Add…`, `Edit…`, `Delete` — are visible but disabled with a "coming in a future update" tooltip; Edit/Delete additionally gate on `currentRow() >= 0` so the select-to-enable wiring is in place for S-07.

This is the first slice of roadmap Stream B (custom reminders). Persistence and recurrence are already done in v0.1.0 (`storage/reminders.py`, `scheduler.next_firing_after`); this slice opens the in-app surface FR-012 calls "list" and resolves Open Roadmap Question #6 in favour of next-firing time over raw RRULE strings.

## Current State Analysis

- **`SettingsDialog`** is a `QTabWidget` with three tabs constructed in `break_reminder/ui/settings_dialog.py:259-271`: Scheduling (FR-006 / FR-010), Notifications (FR-007), Lifecycle (FR-003). The dialog is constructed fresh on every "Open settings…" click — `BreakReminderApp._on_open_settings()` at `break_reminder/app.py:313-327` — so no long-lived dialog state survives between opens.
- **`ReminderStore`** is the read API for `reminders.json`. `list_all()` (`break_reminder/storage/reminders.py:77-80`) is thread-safe, returns `list[Reminder]`, and a missing or corrupt file degrades to `[]` (lines 103-114). Each `Reminder` carries `id`, `name`, `start_at: datetime`, optional `rrule_str: str | None`, optional `end_at: datetime | None` (lines 27-35).
- **`next_firing_after(reminder, now)`** in `break_reminder/scheduler.py:297-322` is a pure function that returns the next firing strictly after `now`, or `None` if the series is exhausted. It handles RRULE parsing internally and swallows invalid-RRULE exceptions (logs + returns `None`). Naive datetimes are coerced to UTC (`_ensure_aware`, lines 325-329).
- **App-side construction.** `BreakReminderApp.__init__` already builds a `ReminderStore` (`break_reminder/app.py:97`) and hands it to `ReminderScheduler`. It does NOT currently pass it to `SettingsDialog` — that's the missing wire.
- **AGENTS.md** "What this scaffold does not yet implement" (lines 184-185) lists the custom-reminder surface as a known TODO. The first bullet ("Custom-reminder editor surfaces inside the settings window") is exactly what S-05..S-08 are progressively dissolving.
- **Roadmap entry S-05** (`context/foundation/roadmap.md:134-145`) is the spec verbatim: read-only list, buttons present but disabled, single Open Question (#6) about display format. The roadmap entry says the slice is `proposed`; this plan moves it to `planned`.
- **Test patterns** are well-established by `tests/test_settings_dialog.py` (1475 lines, fixtures at lines 56-85): tmp-path-bound `Settings`, `StubVoiceNotifier`, `qtbot.addWidget` for teardown. This slice extends that fixture set with a tmp-path-bound `ReminderStore`.

## Desired End State

Four tabs in the Settings dialog (Scheduling, Notifications, Lifecycle, **Reminders**). The Reminders tab renders one of two states deterministically:

1. **Non-empty (`reminders.json` has entries):** a `QListWidget` lists every reminder, one item per row, with text `"<name>  —  <next firing | (expired)>"`. Rows are sorted: future firings first, ascending by firing time; expired (`next_firing_after` returns `None`) last; alphabetical name as tiebreak in both buckets. Below the list, three buttons (`Add…`, `Edit…`, `Delete`) are visible but disabled with tooltip `"Coming in a future update"`. Edit and Delete additionally gate on `currentRow() >= 0` so picking a row enables them (the click handlers themselves remain no-ops in this slice).
2. **Empty (`reminders.json` absent or contains `[]`):** the list widget is replaced by a centered `QLabel` reading `"No reminders yet — click Add to create one."`; the three buttons are still rendered and still disabled.

The `ReminderStore` instance the app already owns is threaded through `_on_open_settings()` into `SettingsDialog(..., reminder_store=...)`. The dialog reads `list_all()` exactly once during `__init__`; no signal subscriptions, no reload on tab switch, no live refresh while open.

`AGENTS.md` no longer flags "Custom-reminder editor surfaces inside the settings window" as a TODO. `roadmap.md` shows S-05 as `done` and Open Roadmap Question #6 as resolved.

### Verification:

- `uv run pytest tests/test_settings_dialog.py` passes including the new test class for the Reminders tab.
- `uv run pytest tests/test_app.py` still passes after the `_on_open_settings` change (the existing app-level tests do not exercise the dialog interior, so this is a smoke gate).
- A real Windows session: open Settings → Reminders with empty `reminders.json` shows the placeholder; seeding two hand-written entries (one one-shot, one weekly RRULE) and re-opening shows them in the expected order, with one rendering `"(expired)"` if its `start_at` is in the past and it has no RRULE.

### Key Discoveries:

- `ReminderStore.list_all()` is already lock-safe and degrades gracefully on a corrupt file (`storage/reminders.py:103-114`) — the dialog does not need a try/except around it.
- `next_firing_after` (`scheduler.py:297-322`) already handles both branches needed by the row composer: future-firing returns a UTC `datetime`; exhausted series returns `None`. No new helper in `scheduler.py` is needed.
- Naive `start_at` on disk is treated as UTC by `_ensure_aware` (`scheduler.py:325-329`) — meaning the user's hand-edited JSON with a naive ISO timestamp is *not* in their local time. This is a pre-existing quirk; the list view inherits it. Surface in the manual smoke step so the writer formats the seed entries correctly.
- The S-04 slice (`context/changes/settings-voice-toggle/plan.md`) is the freshest pattern for: required keyword-only `__init__` parameter, fresh-per-open construction, and module-level pure helpers. Mimicking it keeps the dialog's surface uniform.
- The S-02 slice's atomic-save invariant ("OK saves everything or nothing") is **out of scope here** — the Reminders tab does not write anything. There is no `accept()` path for this tab to participate in.

## What We're NOT Doing

- **No Add / Edit / Delete click handlers.** The buttons are deliberately dead in this slice. S-06 wires Add; S-07 wires Edit + Delete. Adding any of them now bleeds scope and re-opens the questions S-06/S-07 will answer with full context.
- **No recurrence editor.** S-08 owns the RRULE-construction UI; this slice only *reads* the RRULE strings.
- **No live refresh of the list.** No `ReminderStore.changed` signal, no `currentChanged` tab-switch reload, no `QFileSystemWatcher`. The dialog is a snapshot for its lifetime.
- **No new modules.** Everything new lives in `break_reminder/ui/settings_dialog.py` as additions to the existing class plus three module-level helpers.
- **No changes to `storage/reminders.py`, `scheduler.py`, `activity.py`, `notifications/`.** The slice is a pure read-side consumer.
- **No localization / i18n framework.** Day-name comes from `strftime("%a")`'s locale-aware output; no `QTranslator` plumbing.
- **No keyboard shortcut for Add (no Ctrl+N).** Will land with the actual Add handler in S-06.
- **No multi-select, no drag/drop, no in-place editing, no column sort headers.** All out of FR-012's "list" scope.
- **No empty-state hint that changes wording when S-06 ships.** The placeholder text "click Add to create one" is intentionally already accurate for the post-S-06 world — no edit needed when Add lights up.
- **No NSIS, PyInstaller, or release-workflow changes.** This is a pure dialog change.

## Implementation Approach

The slice is shaped as a single dialog-construction change behind one new `ReminderStore` parameter. The flow:

1. **Inject** `ReminderStore` through `SettingsDialog.__init__` as a required keyword-only parameter (mirrors `voice`). Update the single call site in `app.py:_on_open_settings()` to pass `self._reminder_store`.
2. **Add three module-level pure helpers** to `settings_dialog.py`: `_format_firing`, `_sort_key`, `_compose_row`. They live at module scope so the test suite can call them directly with hand-built `Reminder` instances and a fixed `now`, without instantiating a Qt widget.
3. **Add `_build_reminders_tab()` method** on `SettingsDialog`. Inside it: read the store once, branch on empty/non-empty, build either the placeholder label or the `QListWidget`, append the disabled button row, return the tab `QWidget`.
4. **Wire the constructor** to call `_build_reminders_tab()` after the Lifecycle tab (4th tab).
5. **Add Edit/Delete select-gating**: connect `QListWidget.currentRowChanged` to a slot that sets `Edit…` and `Delete` `setEnabled(currentRow() >= 0)`. The `Add…` button stays unconditionally disabled.
6. **Test thoroughly** with a tmp-path-bound `ReminderStore` fixture mirroring the existing `ini_path`/`settings` fixtures: empty-state placeholder presence, list rendering with three reminders covering all three branches (future one-shot, recurring RRULE, expired one-shot), sort order, button initial state, button select-gating, single-call-to-`list_all` invariant.
7. **Update docs**: drop the first custom-reminder bullet from `AGENTS.md` "What this scaffold does NOT yet implement"; flip the `change.md` and roadmap S-05 entries to `done`; resolve Open Roadmap Question #6 in `roadmap.md`.

## Critical Implementation Details

- **`next_firing_after` time domain.** The helper returns tz-aware UTC datetimes (via `_ensure_aware`, `scheduler.py:325-329`). The user expects local time. The renderer must call `.astimezone()` (no argument) to convert before `strftime` — otherwise UTC is displayed and the user sees a timestamp that's off by their tz offset. The unit test must pin this with at least one non-UTC verification (either via `freezegun`-equivalent monkeypatching or by asserting that the rendered string starts with the local-tz day-name of the converted instant, NOT the UTC day-name).

- **Sort-key tuple shape.** The expired-last invariant is encoded as the first tuple element: `(0, fire_at, name_lower)` for future firings and `(1, name_lower)` for expired. Python's tuple comparison is by-element with short-circuit on the first; the two tuple shapes never need to compare past element 0 (the `0` group always sorts before the `1` group). **Do not** try to unify the two tuple shapes with a sentinel `datetime.max` for expired — `datetime.max` is naive and would `TypeError` when compared against the tz-aware `fire_at` values.

- **Single `list_all` call.** The dialog must call `reminder_store.list_all()` exactly once in `_build_reminders_tab()`. A unit test pins this with a spy (`list_all` wrapped in a counter); regressing to "reload on tab switch" or "reload on currentRowChanged" silently doubles the file I/O without anyone noticing.

- **Tooltips on disabled buttons.** Qt 6's documented behaviour: "disabled widgets do not receive mouse events." This means `setToolTip(...)` + `setEnabled(False)` on the same `QPushButton` produces a button whose tooltip is set as a property but never shows on hover — the unit test passes (property check), the user sees nothing. The workaround used here: each disabled `QPushButton` lives inside a one-widget `QHBoxLayout(contentsMargins=0)` wrapper that owns the tooltip and stays enabled. Hover events hit the wrapper (which is enabled, so they're delivered), the wrapper's tooltip fires, and the inner button stays visually + functionally disabled. The test assertion shifts from `button.toolTip()` to `button.parentWidget().toolTip()`. **Do not** call `setToolTip` directly on the `QPushButton`; the tooltip belongs to the wrapper exclusively, otherwise the empty inner tooltip might race-suppress the wrapper's text on hover.

## Phase 1: Implementation

### Overview

Land the entire user-visible change in one phase: inject `ReminderStore` into the dialog, build the Reminders tab with both empty-state and populated states, wire the disabled button row with select-gating, and cover every branch with unit tests. The phase exits when `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, and `uv run pyright` are all green.

### Changes Required:

#### 1. `SettingsDialog` constructor — accept `ReminderStore`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Add a required keyword-only `reminder_store: ReminderStore` parameter to `SettingsDialog.__init__`, store it on `self._reminder_store`, and call a new `_build_reminders_tab()` after the existing three `addTab` calls (so Reminders is the fourth tab). Update the class docstring to mention the new tab.

**Contract**: New constructor signature is `def __init__(self, *, settings: Settings, voice: VoiceNotifier, reminder_store: ReminderStore, parent: QWidget | None = None) -> None`. The `reminder_store` parameter is required (no default) for the same reason `voice` is required (forces tests to inject a tmp-pathed store). New class attribute `REMINDERS_TAB_LABEL = "Reminders"`. New stored attribute `self._reminder_store`. The Reminders tab widget is **not** stored on `self` — the existing rule (documented in code at `settings_dialog.py:263-264` and `268-270`) is "store the tab on self only when `accept()` needs to switch to it on validation failure". `_scheduling_tab` is not stored for the same reason, and the Reminders tab has no `accept()` participation. The constructor calls `self._tabs.addTab(self._build_reminders_tab(), self.REMINDERS_TAB_LABEL)` directly, matching how Scheduling is added.

#### 2. `_build_reminders_tab()` method

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Construct the Reminders tab `QWidget`. Read `self._reminder_store.list_all()` exactly once; capture `datetime.now(UTC)` exactly once (pass the same `now` to every `_sort_key` / `_compose_row` call so two reminders with the same firing-second don't race). Branch: empty list → centered `QLabel` placeholder; non-empty → `QListWidget` populated from sorted rows. In both branches, append the disabled button row built by a sibling helper `_build_reminders_button_row()`. Store the `QListWidget` (or `None` in the empty branch) on `self._reminders_list` for the test suite and the select-gating slot.

**Contract**: Method signature `def _build_reminders_tab(self) -> QWidget`. Stored attributes after the call: `self._reminders_list: QListWidget | None`, `self._reminders_placeholder: QLabel | None` (exactly one is non-`None`), `self._reminders_add_button: QPushButton`, `self._reminders_edit_button: QPushButton`, `self._reminders_delete_button: QPushButton`. Placeholder text constant `_REMINDERS_EMPTY_MESSAGE = "No reminders yet — click Add to create one."`. Returned widget has a `QVBoxLayout` with two slots: list-or-placeholder on top, button row on bottom.

#### 3. `_build_reminders_button_row()` helper method

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Construct the three-button row at the bottom of the Reminders tab. Each button is `setEnabled(False)` and is wrapped in a tooltip-bearing `QWidget` container (see Critical Implementation Details — Qt swallows hover events on disabled widgets, so the tooltip MUST live on a parent that stays enabled). Add ellipsis to the two affordances that open sub-dialogs (`Add…`, `Edit…`) per Qt UI conventions; `Delete` gets none. Return the row `QWidget` so the caller can drop it into the tab's layout.

**Contract**: Method signature `def _build_reminders_button_row(self) -> QWidget`. New module-level constant `_REMINDERS_BUTTONS_DISABLED_TOOLTIP = "Coming in a future update."`. Button labels are `"Add…"`, `"Edit…"`, `"Delete"`. The three buttons are stored on `self._reminders_add_button`, `self._reminders_edit_button`, `self._reminders_delete_button` so the select-gating slot and the test suite can address them. Each button has a one-widget wrapper:

```
QWidget(tooltip=_REMINDERS_BUTTONS_DISABLED_TOOLTIP)   # the hover-target; stays enabled
└─ QHBoxLayout(contentsMargins=(0,0,0,0))              # zero margin so layout is unchanged
   └─ QPushButton(text="Add…", enabled=False)          # visually + functionally disabled
```

The wrapper widgets are NOT stored on `self` — only the inner `QPushButton`s are addressable. The row layout adds the three wrapper widgets, not the buttons directly. No `clicked` signals are connected in this slice.

#### 4. `_on_reminders_selection_changed()` slot

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Slot connected to `QListWidget.currentRowChanged` against the populated-list branch (the empty-state branch has no `QListWidget` to connect to). In this slice the body is `pass` — the signal is wired but no enabling happens. A unit test asserts the connection is in place so the wiring can't silently break before S-07 fills the body in.

**Contract**: Method signature `def _on_reminders_selection_changed(self, current_row: int) -> None`. Body is `pass` in this slice. S-07 will replace `pass` with:

```python
self._reminders_edit_button.setEnabled(current_row >= 0)
self._reminders_delete_button.setEnabled(current_row >= 0)
```

The connection itself (`self._reminders_list.currentRowChanged.connect(self._on_reminders_selection_changed)`) happens in `_build_reminders_tab()` only on the populated branch.

#### 4a. Imports added to `settings_dialog.py`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Document the full new-import set the helpers and tab construction need, so the implementer doesn't iterate through type errors discovering them.

**Contract**: Add the following lines to the top-of-file import block (existing imports at lines 57-87 verified on 2026-05-27 — `datetime`, `tzinfo`, `next_firing_after`, `Reminder`, `ReminderStore`, `QLabel`, `QListWidget`, `QListWidgetItem` are all currently absent):

```python
from datetime import UTC, datetime, timedelta, timezone, tzinfo

from PySide6.QtWidgets import (
    # ... existing imports ...
    QLabel,
    QListWidget,
    QListWidgetItem,
)

from break_reminder.scheduler import next_firing_after
from break_reminder.storage.reminders import Reminder, ReminderStore
```

`timedelta` and `timezone` are needed by the test surface (Phase 1 §10 "Time conversion happens"); the helpers themselves use `tzinfo` for the optional `tz` parameter type. Sort the merged `PySide6.QtWidgets` import alphabetically per the existing style.

#### 5. Module-level helper: `_format_firing`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Render a `datetime | None` as a string for display. `None` → `"(expired)"`. Otherwise, convert to a target timezone via `.astimezone(tz)` and format with `"%a %Y-%m-%d %H:%M"`. The `tz` parameter is optional and defaults to `None` (which `astimezone()` interprets as the system local zone — production behaviour); tests pass an explicit `timezone(timedelta(hours=-8))` so the conversion behaviour is observable on any CI runner regardless of its system zone.

**Contract**: Function signature `def _format_firing(fire_at: datetime | None, *, tz: tzinfo | None = None) -> str`. Body:

```python
if fire_at is None:
    return _EXPIRED_LABEL
return fire_at.astimezone(tz).strftime(_FIRING_FORMAT)
```

Pure function — no I/O, no clock reads, no widget access. Module-level constants `_EXPIRED_LABEL = "(expired)"` and `_FIRING_FORMAT = "%a %Y-%m-%d %H:%M"`. The `tz=None` default exists precisely so tests can inject a fixed offset and assert the converted output differs from the UTC strftime — without the parameter, the test would compute `<utc>.astimezone() == <utc>` on a UTC runner and pass even if the implementation skipped the conversion entirely.

#### 6. Module-level helper: `_sort_key`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Compute the per-row sort key. Future firings sort before expired; within the future bucket, ascending by firing time; within both buckets, alphabetical case-insensitive name as tiebreak. The tuple shape difference (3-element for future, 2-element for expired) is intentional — see Critical Implementation Details.

**Contract**: Function signature `def _sort_key(reminder: Reminder, now: datetime) -> tuple`. Returns `(0, fire_at, reminder.name.lower())` when `next_firing_after(reminder, now)` returns a non-`None` datetime; returns `(1, reminder.name.lower())` otherwise. Imports `next_firing_after` from `break_reminder.scheduler` (a new cross-package import; document in the file's module docstring why ui depends on scheduler).

#### 7. Module-level helper: `_compose_row`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Build the display string for one list row. Combines name and formatted next-firing with an em-dash separator. Pure function. Threads the optional `tz` parameter through to `_format_firing` so tests can verify timezone conversion at the row-composition layer too.

**Contract**: Function signature `def _compose_row(reminder: Reminder, now: datetime, *, tz: tzinfo | None = None) -> str`. Returns `f"{reminder.name}  —  {_format_firing(next_firing_after(reminder, now), tz=tz)}"` (note: two spaces around the em-dash for readability — single space looks crowded; tests pin the exact string). Production code in `_build_reminders_tab()` calls `_compose_row(reminder, now)` (no `tz`); test code passes `tz=timezone(timedelta(hours=-8))` to verify the conversion happens.

#### 8. `app.py` — thread `ReminderStore` into the dialog

**File**: `break_reminder/app.py`

**Intent**: Update `BreakReminderApp._on_open_settings()` to pass the existing `self._reminder_store` into `SettingsDialog(...)`. Update the method's docstring to reflect that the Reminders tab now lives in the dialog and to drop the "S-05..S-08 lands as additional tabs" sentence (S-05 has landed; the others are still pending).

**Contract**: Single-line change to the `SettingsDialog(...)` call:
```python
SettingsDialog(
    settings=self._settings,
    voice=self._voice,
    reminder_store=self._reminder_store,
).exec()
```
Docstring updated to enumerate four tabs.

#### 9. Test fixture additions

**File**: `tests/test_settings_dialog.py`

**Intent**: Add two fixtures mirroring the existing `ini_path` / `settings` pair: `reminders_path` returns a tmp-path `Path`, `reminder_store` returns a `ReminderStore(path=reminders_path)`. Update the existing `dialog` fixture to inject the new `reminder_store` parameter; update every direct `SettingsDialog(...)` constructor call in the file to pass `reminder_store=...` (or to use the fixture).

**Exact sweep scope** — 12 direct `SettingsDialog(...)` constructions to update (verified via grep on 2026-05-27): `tests/test_settings_dialog.py` lines **83, 108, 213, 234, 250, 504, 525, 592, 616, 992, 1072, 1106**. Run `rg -n 'SettingsDialog\(' tests/test_settings_dialog.py` after the sweep to confirm every match passes `reminder_store=...` (or no longer constructs directly because it switched to the `dialog` fixture).

**Implementation note**: the simpler diff is to make the new `reminder_store` fixture have a sensible default (empty store under `tmp_path / "reminders.json"`) and have every direct construction call a tiny `_make_dialog(tmp_path, settings, voice, reminder_store=None)` helper. That keeps the 12 callsites short and only the helper definition learns about the new parameter. Decide between the helper approach and per-callsite explicit passing during implementation — both are valid; the helper wins on smaller diff, explicit-pass wins on test-by-test readability.

**Contract**: New fixtures:
```python
@pytest.fixture
def reminders_path(tmp_path: Path) -> Path:
    return tmp_path / "reminders.json"

@pytest.fixture
def reminder_store(reminders_path: Path) -> ReminderStore:
    return ReminderStore(path=reminders_path)
```
Updated `dialog` fixture signature includes `reminder_store: ReminderStore`. Every other `SettingsDialog(settings=..., voice=...)` construction in the file gains `reminder_store=ReminderStore(path=tmp_path / "reminders.json")` or uses the new fixture.

#### 10. New test class: `TestRemindersTab`

**File**: `tests/test_settings_dialog.py`

**Intent**: Pin every Reminders-tab behavior with at least one test per branch. Pattern matches the existing `TestLoad`, `TestSave`, `TestCancel` classes in the file.

**Contract**: New `TestRemindersTab` class with tests covering:
- **Tab presence and label.** `assert dialog._tabs.tabText(3) == SettingsDialog.REMINDERS_TAB_LABEL`.
- **Empty-state placeholder shows when store is empty.** `dialog._reminders_list is None and dialog._reminders_placeholder is not None and dialog._reminders_placeholder.text() == _REMINDERS_EMPTY_MESSAGE`.
- **Populated-state list shows when store has reminders.** Seed three reminders via `reminder_store.add(...)` BEFORE constructing the dialog; assert `dialog._reminders_list is not None and dialog._reminders_list.count() == 3 and dialog._reminders_placeholder is None`.
- **One-shot future reminder renders with formatted date.** Single reminder with `start_at = now + 1 day`, no RRULE; assert row text starts with name and ends with a string matching the `_FIRING_FORMAT`.
- **Recurring RRULE reminder renders with formatted next-firing.** Single reminder with `start_at = now - 7 days`, `rrule_str = "FREQ=WEEKLY"`; assert row text contains a future date (the next weekly occurrence).
- **Expired one-shot renders with `(expired)`.** Single reminder with `start_at = now - 1 day`, no RRULE; assert row text endswith `"(expired)"`.
- **Sort order: future ascending, expired last, tiebreak by name.** Seed four reminders: two with the same `start_at + 1h` differing only by name ("B then A" insertion order), one expired ("Zebra"), one further future. Assert `[dialog._reminders_list.item(i).text() for i in range(4)]` matches the expected order: closest future first (with names alphabetized within the tie), further future second, expired last.
- **Buttons are visible and disabled by default.** Assert `add.isVisible() and not add.isEnabled()` for all three buttons (the dialog must be shown first; use `qtbot.add_widget` + `with qtbot.waitExposed(dialog)` if needed for `isVisible()` to be truthy — or test via `add.isEnabled()` alone, which doesn't require visibility).
- **Buttons carry the "coming soon" tooltip on the hover-bearing wrapper.** Per the Qt-disabled-tooltip workaround, the tooltip lives on each button's parent `QWidget`, not on the `QPushButton` itself. Assert `add.parentWidget().toolTip() == _REMINDERS_BUTTONS_DISABLED_TOOLTIP` for all three. The wrapper must also be `isEnabled() == True` so it receives the hover event Qt swallows on the disabled child.
- **Selection-changed slot is connected.** Spawn a non-empty list, programmatically call `dialog._reminders_list.setCurrentRow(0)`, assert the slot was invoked (verify by spying on the slot via a counter, or — simpler — verify the `currentRowChanged` signal is connected to a bound method matching `_on_reminders_selection_changed`).
- **`list_all` is called exactly once.** Spy on `reminder_store.list_all` (wrap with `functools.wraps`-style counter), construct the dialog, switch tabs, switch back; assert the counter is 1.
- **Time conversion happens (tz-injection test).** Call `_format_firing(datetime(2026, 6, 3, 22, 0, tzinfo=UTC), tz=timezone(timedelta(hours=-8)))` and assert the result is `"Wed 2026-06-03 14:00"` — the UTC instant converted to the -08:00 zone. Then assert that the same call WITHOUT the `tz=` argument matches `datetime(2026, 6, 3, 22, 0, tzinfo=UTC).astimezone().strftime(_FIRING_FORMAT)` (the system-local default behaviour). The tz-injected branch is the one that catches the regression "implementation skipped `.astimezone()`" — without it, the system-local branch is a tautology on a UTC runner.

Add a separate test class `TestRemindersHelpers` for pure-function tests on `_format_firing`, `_sort_key`, `_compose_row` — exercised without any `qtbot` involvement:
- `_format_firing(None) == "(expired)"`.
- `_format_firing(<known-utc>, tz=timezone(timedelta(hours=-8)))` produces the -08:00-shifted strftime (catches a regression where `.astimezone()` is removed — see Critical Implementation Details "tz-injection test").
- `_format_firing(<known-utc>)` (no `tz`) equals `<known-utc>.astimezone().strftime(_FIRING_FORMAT)` — pins the system-local default behaviour without depending on the runner's actual zone.
- `_sort_key` returns `(0, fire_at, name_lower)` for a future-firing reminder.
- `_sort_key` returns `(1, name_lower)` for an expired reminder.
- `_compose_row` produces the exact `"name  —  ..."` string for both future and expired branches.

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestRemindersTab` and `TestRemindersHelpers` classes)
- Full suite passes: `uv run pytest`
- Type check passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Format check passes: `uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual Verification:

- Open Settings → Reminders with an empty `reminders.json`: the centered placeholder "No reminders yet — click Add to create one." is visible; the three buttons below it are visible and visibly disabled; hovering each button shows the "Coming in a future update." tooltip.
- Manually populate `%APPDATA%\BreakReminder\reminders.json` with three entries — one one-shot in the future, one one-shot in the past, one with `FREQ=WEEKLY` RRULE — then open Settings → Reminders: all three rows render with the expected formatting; the past one-shot shows `"(expired)"`; the order is closest-future first, expired last.
- Click a list row: Edit/Delete buttons remain visibly disabled (the slot is wired but does nothing in this slice — S-07 will enable it).
- Switch to Scheduling tab, then back to Reminders: the rendered rows are visually unchanged — same order, same item text, no flicker (the unit-test spy on `list_all` is what pins the strict "exactly one read" contract; this manual step confirms the user-visible no-refresh experience).
- No regressions: the Scheduling, Notifications, and Lifecycle tabs continue to behave as before (spinboxes, voice toggle, autostart checkbox all functional; OK still saves; Cancel still discards).

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation that the manual checks above were successful before proceeding to Phase 2.

---

## Phase 2: Manual smoke + bookkeeping

### Overview

Move the slice from "implemented" to "shipped + traceable": confirm the dialog behaves correctly under real Windows with hand-seeded `reminders.json`, then mark every document that tracks this slice's status. No code changes in this phase.

### Changes Required:

#### 1. Manual smoke run

**File**: n/a — operational step

**Intent**: With the new dialog deployed locally (via `uv run python -m break_reminder`), perform the manual verification steps from Phase 1 against a real Windows session. Document the run in the slice's `change.md` "Notes" section if anything unexpected surfaces; if smooth, no doc update needed.

**Contract**: Steps:
1. Stop any running BreakReminder.
2. Delete or empty `%APPDATA%\BreakReminder\reminders.json`.
3. Run `uv run python -m break_reminder`; open Settings → Reminders; confirm placeholder.
4. Quit; hand-edit `reminders.json` with three entries (see "Manual Verification" above for the exact shape).
5. Re-run; open Settings → Reminders; confirm rows render, order is correct, expired shows `"(expired)"`.
6. Click a row; confirm buttons stay disabled.
7. Switch tabs and back; confirm no visible reload.

#### 2. Update `change.md`

**File**: `context/changes/reminders-list-view/change.md`

**Intent**: Flip `status: planned` → `status: implemented`. Update `updated:` to today's date. Add a brief "Implementation note" subsection if anything notable surfaced in the smoke run.

**Contract**: YAML front-matter `status` value changes; `updated` date refreshes. Optional `## Notes` subsection appended.

#### 3. Update `roadmap.md`

**File**: `context/foundation/roadmap.md`

**Intent**: Flip the S-05 row in "At a glance" from `proposed` to `done`. Update the slice's `### S-05` block: change `**Status:** proposed` to `**Status:** done`; append a "Scope addendum shipped" line if anything diverged from the original outcome wording. Mark Open Roadmap Question #6 as dissolved by S-05 with today's date (parallel to how OQ #1 and OQ #3 are marked).

**Contract**: Three substitutions in `roadmap.md`:
1. `| S-05 | reminders-list-view | ... | proposed |` → `| S-05 | reminders-list-view | ... | done |`
2. `- **Status:** proposed` (inside `### S-05`) → `- **Status:** done`
3. OQ #6 line gets `(dissolved by S-05 on 2026-05-27)` appended.

#### 4. Update `AGENTS.md`

**File**: `AGENTS.md`

**Intent**: Remove the first bullet from "What this scaffold does not yet implement" — the one that reads "Custom-reminder editor surfaces inside the settings window (FR-011 / FR-012)…". Leave the second bullet ("Custom-reminder editor dialog (FR-011 / FR-012 CRUD)") because S-06/S-07 still own that. Optionally tighten the second bullet's wording to say "Add / Edit / Delete dialog wiring" since the surface itself now exists.

**Contract**: Lines 184-185 of `AGENTS.md` reduce by one bullet. The "When you implement any of the above, remove the `TODO(FR-xxx)` and update this file" closing line stays.

#### 5. Tick the Progress section

**File**: `context/changes/reminders-list-view/plan.md`

**Intent**: Mark every Phase 1 and Phase 2 progress item complete, with the merge commit SHA appended per `references/progress-format.md`.

**Contract**: `- [ ]` → `- [x] — <sha>` for each line in the Progress section below.

### Success Criteria:

#### Automated Verification:

- `git grep -nE 'Custom-reminder editor surfaces inside the settings window' AGENTS.md` returns no matches (the bullet is gone).
- `git grep -nE 'S-05.*proposed' context/foundation/roadmap.md` returns no matches (status flipped).
- `git diff context/changes/reminders-list-view/change.md` shows `status: implemented` and an updated `updated:` date.

#### Manual Verification:

- Real Windows session: open Settings → Reminders with empty `reminders.json` shows the placeholder. (Phase 2.1 step 3.)
- Real Windows session: open Settings → Reminders with three seeded entries shows the expected ordering and `(expired)` handling. (Phase 2.1 step 5.)
- No regression in Scheduling / Notifications / Lifecycle tabs.

**Implementation Note**: After completing all checks above, the slice is done. The next slice in Stream B is S-06 (`reminders-add-form`), unblocked by this slice landing.

---

## Testing Strategy

### Unit Tests:

- **Pure helpers (`TestRemindersHelpers`).** Test `_format_firing`, `_sort_key`, `_compose_row` without `qtbot` — they are pure functions, must work without a Qt event loop. Cover both `None` and non-`None` `next_firing_after` outputs.
- **Dialog construction (`TestRemindersTab`).** Use the existing `dialog` fixture (with the new `reminder_store` parameter) to exercise empty-state and populated-state branches. Cover all the row-rendering cases in the Phase 1 "Changes Required" section #10.
- **Timezone-conversion test.** `_format_firing` accepts an optional `tz` keyword so tests can pass `tz=timezone(timedelta(hours=-8))` and assert the rendered string reflects the offset (not the UTC instant). Without this injection, a CI runner on UTC would let the test pass even if the implementation skipped `.astimezone()` entirely — `<utc>.astimezone() == <utc>` on a UTC system. See Phase 1 §5 Contract and Phase 1 §10 "Time conversion happens (tz-injection test)".
- **Single-`list_all`-call invariant.** A spy on `reminder_store.list_all` confirms the dialog reads the store exactly once across construction + tab switching. This pins the "no live reload" decision.
- **Button select-gating wiring.** Even though the slot body is `pass` in this slice, a test verifies the connection exists — so the test fails loudly if a future refactor removes the connection before S-07 ships the handler.

### Integration Tests:

- **`tests/test_app.py` smoke.** The existing app-level tests construct `BreakReminderApp` end-to-end but do not open the dialog. They must continue to pass unchanged after the `_on_open_settings` constructor-arg addition — a smoke gate that the wiring change didn't break the app boot path.

### Manual Testing Steps:

1. **Empty-state path.** Stop the app; delete `%APPDATA%\BreakReminder\reminders.json`; start the app; open Settings → Reminders; confirm the placeholder + disabled buttons.
2. **Populated-state path.** Quit the app; hand-edit `reminders.json` to contain three entries:
   ```json
   [
     {
       "id": "test-future-oneshot",
       "name": "Future one-shot",
       "start_at": "2026-12-01T10:00:00+00:00",
       "rrule_str": null,
       "end_at": null
     },
     {
       "id": "test-weekly-rrule",
       "name": "Weekly RRULE",
       "start_at": "2026-05-01T09:00:00+00:00",
       "rrule_str": "FREQ=WEEKLY",
       "end_at": null
     },
     {
       "id": "test-expired-oneshot",
       "name": "Expired",
       "start_at": "2025-01-01T10:00:00+00:00",
       "rrule_str": null,
       "end_at": null
     }
   ]
   ```
   Restart the app; open Settings → Reminders; confirm three rows render, "Expired" shows `"(expired)"`, and the order is `Weekly RRULE` first (next firing imminent) / `Future one-shot` second / `Expired` last.
3. **Select-gating.** Click each populated row in turn; confirm Edit/Delete buttons remain visibly disabled (the slot is wired but no-op in this slice).
4. **Tooltip.** Hover each button; confirm tooltip reads "Coming in a future update."
5. **No-reload invariant (visual).** Open Settings; observe the Reminders rows; switch to Scheduling and back to Reminders; the rendered rows are unchanged — same order, same item text, no flicker. (The strict "exactly one `list_all` call" contract is enforced by the unit-test spy at §10; this manual step only checks the user-visible part. Do NOT use file mtime as a proxy: `list_all` is read-only and never moves mtime regardless of how many times it's called.)
6. **No-regression.** Edit the Scheduling tab's break interval; click OK; confirm `BreakReminder.ini` updates. Re-open Settings; confirm the new interval persisted. (Confirms `accept()` still works after the Reminders tab landed.)

## Performance Considerations

- **`next_firing_after` per row.** Called once per reminder in `_sort_key` plus once more in `_compose_row` — two RRULE parses per row per dialog open. The persona's expected ≤ 10 reminders means worst case ~20 RRULE parses per open. Each parse is sub-millisecond on modern hardware. Negligible.
- **Memoize within a single dialog open?** Possible (call `next_firing_after` once per reminder and stash on a local dict keyed by `reminder.id`), but the constant-factor improvement isn't worth the readability cost at the persona's reminder count. If the slice grows past ~50 reminders, memoize then.
- **No async, no background thread.** The dialog construction is synchronous on the GUI thread, matching every other tab.

## Migration Notes

- **No data migration.** `reminders.json` schema is unchanged. A v0.1.0 install with no `reminders.json` falls into the empty-state branch with no errors; an install with hand-edited (S-04 era) entries renders them correctly via the existing `ReminderStore.list_all` and `next_firing_after` paths.
- **No setting migration.** No new `Settings` keys are added in this slice.
- **No installer/PyInstaller change.** Same release pipeline; no `--add-data`, no `--hidden-import` deltas.

## References

- Roadmap entry: `context/foundation/roadmap.md` § S-05 (lines 134-145)
- PRD: `context/foundation/prd.md` FR-005 (line 103), FR-012 (line 125)
- Similar implementation (dialog construction pattern): `context/changes/settings-voice-toggle/plan.md`
- Atomic-save / select-gating precedent (no atomic-save needed here — read-only): `context/changes/settings-autostart-toggle/plan.md`
- Storage layer: `break_reminder/storage/reminders.py:64-99` (`ReminderStore.list_all`)
- Next-firing helper: `break_reminder/scheduler.py:297-322` (`next_firing_after`)
- App wiring: `break_reminder/app.py:97` (`_reminder_store` construction), `:313-327` (`_on_open_settings`)
- Open Roadmap Question #6: `context/foundation/roadmap.md` line 203

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Implementation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestRemindersTab` and `TestRemindersHelpers` classes) — 5e0ab06
- [x] 1.2 Full suite passes: `uv run pytest` — 5e0ab06
- [x] 1.3 Type check passes: `uv run pyright` — 5e0ab06
- [x] 1.4 Linting passes: `uv run ruff check` — 5e0ab06
- [x] 1.5 Format check passes: `uv run ruff format --check` — 5e0ab06
- [x] 1.6 Security audit passes: `uv run pip-audit` — 5e0ab06
- [x] 1.7 License gate passes: `uv run pip-licenses --fail-on="AGPL"` — 5e0ab06

#### Manual

- [x] 1.8 Open Settings → Reminders with empty `reminders.json`: placeholder visible; three buttons visible + disabled; tooltip "Coming in a future update." on hover — 5e0ab06
- [x] 1.9 Populated `reminders.json` with three entries (future one-shot, past one-shot, weekly RRULE): all three rows render correctly; past one-shot shows `"(expired)"`; order is closest-future first, expired last — 5e0ab06
- [x] 1.10 Click a row: Edit/Delete buttons remain visibly disabled — 5e0ab06
- [x] 1.11 Switch tabs and back: rendered rows are visually unchanged (same order, same text, no flicker) — 5e0ab06
- [x] 1.12 Scheduling / Notifications / Lifecycle tabs continue to behave correctly (spinboxes, voice toggle, autostart checkbox; OK saves; Cancel discards) — 5e0ab06

### Phase 2: Manual smoke + bookkeeping

#### Automated

- [x] 2.1 `git grep -nE 'Custom-reminder editor surfaces inside the settings window' AGENTS.md` returns no matches
- [x] 2.2 `git grep -nE '^\| S-05 .*proposed' context/foundation/roadmap.md` returns no matches (tightened from `S-05.*proposed` during Phase 2 — the original was over-broad and matched S-06's "S-05" Prerequisites mention)
- [x] 2.3 `git diff context/changes/reminders-list-view/change.md` shows `status: implemented` and updated `updated:` date

#### Manual

- [x] 2.4 Real Windows: empty `reminders.json` shows placeholder (Phase 2.1 step 3)
- [x] 2.5 Real Windows: three seeded entries render in expected order with `(expired)` handling (Phase 2.1 step 5)
- [x] 2.6 No regression in Scheduling / Notifications / Lifecycle tabs
