# Reminders Edit / Delete Implementation Plan

## Overview

Wire the previously-disabled `Edit…` and `Delete` buttons in the Reminders tab (shipped by S-05) to act on the currently-selected row. **Edit** opens the existing S-06 `ReminderFormDialog` pre-filled with the selected reminder's values (the dialog gains an optional `reminder: Reminder | None = None` constructor parameter, mode-switching the title, fill, save path, and emitted signal). **Delete** opens a modal `QMessageBox` Yes/No confirmation, then removes the entry via `ReminderStore.delete()` if confirmed. Both flows route through the existing `_refresh_reminders_tab` so the list updates in place, and through `ReminderScheduler.reload()` so the running session re-arms against the modified store.

This is the third slice of roadmap Stream B (custom reminders), unblocking on S-06. It closes the FR-012 list/edit/delete CRUD surface and dissolves the second `Custom-reminder Edit / Delete dialog wiring` TODO from `AGENTS.md`. S-08's recurrence editor is the last pending Stream B item after this slice lands.

## Current State Analysis

- **Storage CRUD is complete.** `ReminderStore.update(reminder)` (`storage/reminders.py:148-152`) replaces the entry whose `id` matches (no-op when absent); `ReminderStore.delete(reminder_id)` (`storage/reminders.py:154-158`) drops by `id`. Both share the existing `threading.Lock` and tmp+rename atomic-write path (`storage/reminders.py:175-183`). **No new storage code.**
- **The form module was designed for reuse.** Its docstring at `break_reminder/ui/reminder_form_dialog.py:17-24` explicitly says: *"The form is generic by name so S-07's Edit dialog can reuse the same class with a pre-populated `Reminder` argument. The module is `reminder_form_dialog` (not `add_reminder_dialog`) precisely so that reuse doesn't require a file rename or a sibling clone. S-07 can reconstruct `event_at` from a loaded `Reminder` via `start_at + timedelta(minutes=lead_minutes)`."* This slice cashes that promise in.
- **Edit / Delete buttons and selection wiring already exist as no-op scaffolding** (`break_reminder/ui/settings_dialog.py:747-768`). Both buttons are constructed `setEnabled(False)` and wrapped in tooltip-bearing containers carrying `_REMINDERS_BUTTONS_DISABLED_TOOLTIP = "Coming in a future update."`. The `QListWidget.currentRowChanged` signal is connected to `_on_reminders_selection_changed` (`:707`), whose body is `pass`. The S-05 plan documents the S-07 hand-off shape explicitly: *"S-07 will replace the body with `self._reminders_edit_button.setEnabled(current_row >= 0); self._reminders_delete_button.setEnabled(current_row >= 0)`."*
- **List rows are sorted via `_sort_key` once per build.** `_build_reminders_tab` (`settings_dialog.py:643-712`) sorts the `list_all()` result and constructs one `QListWidgetItem` per reminder in that order. The sort order is not currently stored anywhere — Edit / Delete handlers need to map `currentRow()` back to the original `Reminder` instance, so a cached sorted list is required.
- **`reminder_added` signal precedent.** `ReminderFormDialog.reminder_added = Signal(Reminder)` (`reminder_form_dialog.py:226`) emits from `accept()` immediately **before** `super().accept()`. The "emit-before-super-accept" ordering is load-bearing and pinned by `test_save_emits_reminder_added_before_super_accept`. The S-07 `reminder_updated` signal must follow the same ordering.
- **`QMessageBox` is already in use** (`break_reminder/app.py:357-367` for the version check; `:456` for the tray-missing fatal). The AGENTS-level "no `QMessageBox` for validation" rule still holds — but Delete confirm is a **confirmation**, not validation, so this is on-pattern. The `Yes/No` shape with `No` as the default button maps to `QMessageBox.question(parent, title, text, Yes|No, defaultButton=No)`.
- **Past-time gate is unconditional today** (`reminder_form_dialog.py:395-402`). The gate computes `start_at_utc = event_at_utc - timedelta(minutes=lead_minutes)`, rejects when `start_at_utc <= self._clock()`, and surfaces a lead-aware tooltip. In Edit mode, the gate must skip when the user hasn't touched the firing time — otherwise renaming an expired reminder requires also rescheduling it.
- **Sub-dialog ownership pattern.** S-06's retrospective F6 fix added `Qt.WidgetAttribute.WA_DeleteOnClose` to the sub-dialog construction (`settings_dialog.py:807-813`) so repeated Add cycles don't accumulate ghost dialogs. The Edit-side construction must apply the same attribute.
- **Test stub pattern.** `_StubFormDialog` instances in `tests/test_settings_dialog.py:2244, :2310` already have a `setAttribute` no-op (S-06 retrospective). Edit-side tests can reuse the same shape, extended to capture the new `reminder` constructor kwarg.

## Desired End State

The S-05 Reminders tab gains working Edit and Delete buttons:

1. **Edit / Delete buttons start disabled** (no selection on a freshly-opened tab); they enable the moment the user selects any row (`currentRow >= 0`) and disable again when the selection clears.
2. **Clicking Edit opens the modal `ReminderFormDialog` pre-filled** with the selected row's values:
   - Name field: `reminder.name`.
   - Date/time field: the **event time** (`reminder.start_at + timedelta(minutes=reminder.lead_minutes)`), converted UTC → system local → stripped to naive for the widget.
   - Lead spinbox: `reminder.lead_minutes`.
   - Window title: `"Edit Reminder"` (vs `"Add Reminder"` for the existing Add flow).
3. **OK in Edit mode validates and saves:**
   - Name validation: unchanged from Add (non-empty after strip).
   - Past-time validation: **skipped** when the firing time hasn't moved (`start_at_utc_current == self._editing.start_at`); otherwise applied with the same lead-aware tooltip wording as Add.
   - Persist via `self._store.update(reminder)` — the new `Reminder` instance carries the **same `id`** as the loaded one so `update` finds and replaces it.
   - Call `self._scheduler.reload()` — re-arms the running session against the (possibly retimed) reminder.
   - Emit `self.reminder_updated.emit(reminder)` — same emit-before-super-accept ordering as `reminder_added`.
   - Call `super().accept()` — closes the sub-dialog with `QDialog.Accepted`.
4. **Cancel in Edit mode** closes with `QDialog.Rejected`; nothing persisted, nothing armed.
5. **Clicking Delete opens a modal `QMessageBox`** with text `f'Delete reminder "{name}"?'`, informative text `"This cannot be undone."`, Yes / No buttons, `No` as the default. Yes → `self._reminder_store.delete(reminder.id)` → `self._reminder_scheduler.reload()` → `self._refresh_reminders_tab()`. No / Esc → no-op.
6. **After Edit save or Delete confirm**, the Reminders tab rebuilds in place (same path Add uses), the selection clears (so Edit/Delete go back to disabled until the user selects again), and `_reminders_sorted` is refreshed so the next Edit/Delete addresses the new list state.
7. **AGENTS.md** no longer lists "Custom-reminder Edit / Delete dialog wiring" as a TODO; the bullet either narrows to the remaining S-08 recurrence editor or is removed in favor of S-08's own bullet (see #11 below).
8. **`roadmap.md` S-07 row + body** flip from `proposed` to `done`.

### Verification:

- `uv run pytest tests/test_reminder_form_dialog.py` passes — extended to cover Edit mode pre-fill, save path, signal emission, past-time gate skip / apply, name validation, cancel, OSError.
- `uv run pytest tests/test_settings_dialog.py` passes — extended with `TestRemindersEditButton` and `TestRemindersDeleteButton` covering selection-gates-enable, click handlers, QMessageBox confirmation behavior, refresh-on-success.
- `uv run pytest` passes (full suite, no regressions in S-04 / S-05 / S-06 / S-06b surfaces).
- `uv run pyright`, `uv run ruff check`, `uv run ruff format --check`, `uv run pip-audit`, `uv run pip-licenses --fail-on="AGPL"` all green.
- Real Windows session: open Settings → Reminders → select an existing reminder → Edit → change the name → Save; row updates in place. Re-open Edit → change time → Save; the popup fires at the new instant. Select a row → Delete → confirm Yes; row disappears. Delete → No; row stays. Delete with a reminder ~30s out → row gone, popup never fires.

### Key Discoveries:

- **`ReminderStore.update()` and `ReminderStore.delete()` are the only public APIs needed** (`storage/reminders.py:148-158`). Same `threading.Lock` + atomic-rename pattern as `add`; no new storage code.
- **The `reminder_form_dialog` docstring authored the reuse contract** (`reminder_form_dialog.py:17-24`). The implementation pre-anticipated the optional `reminder` arg; this slice just adds it.
- **`_REMINDERS_BUTTONS_DISABLED_TOOLTIP` constant becomes dead code** after this slice (both wrapped buttons drop their wrappers, mirroring S-06's Add treatment). The constant and the S-05 test pinning the wrapper tooltip both come out.
- **The `_reminders_sorted` cache is required** to map `QListWidget.currentRow()` back to the right `Reminder` instance. Computing it once per `_build_reminders_tab` reuses the existing sort; pinning it on `self` lets click handlers index it directly.
- **The "firing time unchanged" condition for the past-time gate skip** reduces to `start_at_utc_current == self._editing.start_at`. Comparing the firing instant (rather than event_at + lead independently) is equivalent because `start_at = event_at - lead`, and is one comparison instead of two.

## What We're NOT Doing

- **No recurrence editor.** No RRULE field, no "Repeat weekly" picker, no end-date input. S-08 owns that.
- **No multi-select / batch delete.** Single-select only. Deleting two reminders is two interactions. Multi-select adds modifier-key UX, batch-confirm wording, and atomicity questions that aren't worth the surface area for the persona's ≤10 reminders.
- **No drag-and-drop reordering.** Sort order is computed (`_sort_key`); the user cannot manually reorder.
- **No double-click to Edit.** Edit is button-only; double-click on a row stays a no-op. Could be a one-liner addition later if the user asks.
- **No `Delete` keyboard shortcut.** The Delete button is mouse-click-only in this slice; binding `Qt.Key_Delete` to the list widget could come later.
- **No optimistic UI / undo.** Delete is immediate after confirm; no Gmail-style undo affordance. (The QMessageBox confirm IS the deliberate-action gate.)
- **No `reminder_deleted = Signal(str)` (or similar).** The Delete handler is fully synchronous inside `SettingsDialog` — store → reload → refresh — without bouncing through the form. No signal needed.
- **No new `Settings` keys.** Confirmation behavior is hardcoded; no "skip delete confirm" toggle.
- **No history / event-log integration changes.** The existing `event_log.py` is unchanged; Edit / Delete are not logged events (only firings are).
- **No localization.** All new strings (`"Edit Reminder"`, `'Delete reminder "<name>"?'`, `"This cannot be undone."`, `"Yes"`, `"No"`) are English literals — same convention as every other surface.

## Implementation Approach

The slice is shaped as: a constructor + signal addition on the existing form module, four new methods on `SettingsDialog` (one selection-changed body fill + one Edit slot + one Delete slot + one sorted-list cache), removal of two wrapper widgets and one now-dead constant, an extension of two existing test files, and the documentation tightening. The order matters because Edit / Delete tests depend on the form's new mode being in place; below is the implementer's natural order.

1. **Extend `ReminderFormDialog`** (`break_reminder/ui/reminder_form_dialog.py`):
   - Add `reminder: Reminder | None = None` to `__init__`; store as `self._editing`.
   - Capture the loaded firing instant for the past-time gate skip: `self._loaded_start_at_utc = reminder.start_at if reminder else None`.
   - Flip `setWindowTitle` based on mode: `"Edit Reminder"` (Edit) vs `"Add Reminder"` (Add).
   - Pre-fill all three fields when `self._editing is not None`:
     - Name: `self._name_field.setText(reminder.name)`.
     - Lead spinbox: `self._lead_minutes_field.setValue(reminder.lead_minutes)`.
     - Datetime: event time = `reminder.start_at + timedelta(minutes=reminder.lead_minutes)`, converted UTC → local → stripped to naive (mirrors `_compute_default_datetime`'s flow but using the loaded instant instead of `self._clock() + offset`).
   - Add class-level `reminder_updated = Signal(Reminder)` alongside the existing `reminder_added`.
   - Modify `accept()`:
     - Past-time gate: skip when `self._editing is not None and start_at_utc == self._editing.start_at` (firing time unchanged); otherwise apply unchanged.
     - Construct the `Reminder`: in Edit mode pass `id=self._editing.id` (so `store.update` finds the existing row); in Add mode the auto-generated `id` default fires unchanged.
     - Persist: `self._store.update(reminder)` (Edit) vs `self._store.add(reminder)` (Add).
     - Emit: `self.reminder_updated.emit(reminder)` (Edit) vs `self.reminder_added.emit(reminder)` (Add). Same emit-before-super-accept ordering.

2. **Cache the sorted Reminders list on `SettingsDialog`**:
   - Initialize `self._reminders_sorted: list[Reminder] = []` in `__init__`.
   - In `_build_reminders_tab`, after sorting: `self._reminders_sorted = sorted(reminders, key=lambda r: _sort_key(r, now))`. Iterate `self._reminders_sorted` when constructing list items so the cache and the widget agree by construction.
   - On empty branch: `self._reminders_sorted = []`.

3. **Fill `_on_reminders_selection_changed`** to enable/disable Edit and Delete based on whether a row is selected. Replace the `pass` body with the S-05-documented two lines:
   ```
   self._reminders_edit_button.setEnabled(current_row >= 0)
   self._reminders_delete_button.setEnabled(current_row >= 0)
   ```

4. **Restructure `_build_reminders_button_row`**:
   - Edit and Delete drop their tooltip-bearing wrappers (matches S-06's Add treatment). Both buttons become bare `QPushButton`s in the row layout.
   - Both buttons start `setEnabled(False)` (no selection yet); the selection-changed slot enables them on demand.
   - Wire `clicked` signals: `self._reminders_edit_button.clicked.connect(self._on_reminders_edit_clicked)` and `self._reminders_delete_button.clicked.connect(self._on_reminders_delete_clicked)`.
   - The wrapper-construction loop disappears; only the three bare buttons (Add, Edit, Delete) remain.

5. **Remove the now-dead `_REMINDERS_BUTTONS_DISABLED_TOOLTIP`** constant (`settings_dialog.py:206`) — no callers remain after step 4.

6. **Add `_on_reminders_edit_clicked` slot**: identify the selected `Reminder` via `self._reminders_sorted[current_row]`, construct `ReminderFormDialog(store=..., scheduler=..., parent=self, reminder=selected)` with `WA_DeleteOnClose`, connect `reminder_updated` to `self._refresh_reminders_tab`, call `dialog.exec()`. Mirrors `_on_reminders_add_clicked` structurally.

7. **Add `_on_reminders_delete_clicked` slot**: identify the selected `Reminder` same way; call `QMessageBox.question(self, "Delete reminder", f'Delete reminder "{selected.name}"?\nThis cannot be undone.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)`; on `Yes`: `self._reminder_store.delete(selected.id)`, `self._reminder_scheduler.reload()`, `self._refresh_reminders_tab()`. On `No`: no-op (early return).

8. **Extend `tests/test_reminder_form_dialog.py`** with `TestReminderFormDialogEditMode`:
   - Pre-fill: name, datetime (event time, not start_at), lead spinbox.
   - Window title: `"Edit Reminder"`.
   - Save path: calls `store.update` (not `store.add`); preserves `id`; emits `reminder_updated` (not `reminder_added`); same emit-before-super-accept ordering.
   - Past-time gate: skipped when datetime + lead unchanged (firing time identical to loaded); applied when datetime or lead changed.
   - Name validation: still applies.
   - Cancel: no store mutation, no scheduler reload, no signal.
   - OSError on `store.update`: dialog stays open, no signal, no reload, tooltip surfaces.

9. **Extend `tests/test_settings_dialog.py`** with `TestRemindersEditButton` and `TestRemindersDeleteButton`:
   - Edit button: disabled when no selection; enabled on `setCurrentRow(0)`; click constructs `ReminderFormDialog` with the right `reminder=` kwarg; `reminder_updated` triggers tab refresh; wrapper-tooltip test is **removed** (the wrapper is gone — replaced with a "no wrapper" assertion mirroring S-06's Add test).
   - Delete button: disabled when no selection; enabled on selection; click invokes `QMessageBox.question` with the right args (monkeypatched recorder); Yes path → `store.delete` called with the right id + tab refresh; No path → no store call, no refresh; default button is `No` (so Enter doesn't delete).
   - Update the existing S-05 wrapper-tooltip test (if any specifically pins the Edit/Delete wrappers) to assert the buttons now have no wrapper, parallel to the S-06 Add test.

10. **Update `app.py` if needed**. The `SettingsDialog` constructor signature is unchanged; the existing `SettingsDialog(settings=..., voice=..., reminder_store=..., reminder_scheduler=...)` call site keeps working. No app-side change anticipated.

11. **Update `AGENTS.md`** "What this scaffold does NOT yet implement". The current bullet (`AGENTS.md:184`) reads `"Custom-reminder Edit / Delete dialog wiring (FR-012). The read-only Reminders tab shipped in S-05; the `Add…` click handler shipped in S-06; `Edit…` / `Delete` are still wired no-op until S-07."` After S-07, the entire FR-012 CRUD surface is shipped. Replace the bullet with: `"Custom-reminder recurrence editor (FR-014). The read-only Reminders tab shipped in S-05; Add / Edit / Delete CRUD shipped in S-06 / S-07; the daily / weekly / monthly RRULE picker is the last pending Stream B surface (S-08)."` — the parent list keeps the same shape (every line documents what's still TODO), and S-08's eventual landing will remove this bullet entirely.

12. **Phase 2 bookkeeping** — `change.md` to `implemented`, `roadmap.md` S-07 to `done`, AGENTS.md verified, Progress section ticked.

## Critical Implementation Details

- **Past-time gate skip condition.** The cleanest detector for "firing time unchanged" is `start_at_utc == self._editing.start_at` — a single equality on tz-aware UTC datetimes. Comparing `event_at_local` and `lead_minutes` separately is equivalent (because `start_at = event_at - lead`, all three are coupled) but takes two comparisons and re-derives values the form already computed. Implement as a single guard at the top of the existing past-time branch:

```python
if start_at_utc <= self._clock():
    if self._editing is not None and start_at_utc == self._editing.start_at:
        # firing time unchanged from the loaded reminder; skip the
        # past-time gate so name-only / lead-only edits on an
        # already-expired reminder pass through.
        pass
    else:
        message = (...)
        self._show_tooltip(self._datetime_field, message)
        return
```

A test pins both halves: `test_edit_mode_unchanged_datetime_skips_past_time_gate` (loaded reminder is expired; user changes only name; save succeeds) AND `test_edit_mode_changed_datetime_to_past_blocks_save` (user touches the datetime widget OR the lead spinbox in a way that moves `start_at` to a new past instant; save is blocked with the standard tooltip).

- **Edit-mode `Reminder` construction must preserve the original `id`.** `ReminderStore.update(reminder)` is a no-op when `id` is not found, so a wrong-id Edit save would silently leave the original row in place AND not add the new one (because update doesn't insert). The `Reminder(..., id=self._editing.id)` keyword arg in Edit mode bypasses the dataclass default-factory `uuid.uuid4()`. A test pins this: `test_edit_mode_save_preserves_reminder_id`.

- **Selection → index → `Reminder` lookup via cached sort.** `QListWidget.currentRow()` returns a row index into the widget's items, which were inserted in `_sort_key` order. The click handler must resolve that index against the same sort. Caching the sorted list on `self._reminders_sorted` during `_build_reminders_tab` (after the existing sort runs) means the handler reads `self._reminders_sorted[current_row]` without any re-sort or re-read. **Do not re-call `_reminder_store.list_all()` in the click handler** — that would break the S-05 "list_all called exactly once per `_build_reminders_tab` invocation" invariant the spy test pins.

- **`QMessageBox.question` default button = `No`.** The default button is the one that activates when the user presses `Enter` with no explicit click. Setting it to `No` prevents an accidental Enter (e.g., still typing in the name field, Tab focuses Delete, Enter confirms deletion of the wrong row) from destroying data. The PyQt API for this is the 5th positional arg: `QMessageBox.question(parent, title, text, buttons, defaultButton)` — passing `QMessageBox.StandardButton.No` as `defaultButton`. A test pins this via the monkeypatched `QMessageBox.question` recorder.

- **`WA_DeleteOnClose` on the Edit sub-dialog construction.** Same fix as S-06 retrospective F6: the form is `parent=self` so Qt keeps it alive until SettingsDialog closes; without `WA_DeleteOnClose`, repeated Edit cycles leave ghost dialogs. The Edit slot must apply the attribute exactly like the Add slot does.

- **Connect only `reminder_updated` in the Edit slot** (not `reminder_added`). Edit-mode form never emits `reminder_added`; Add-mode form never emits `reminder_updated`. Connecting both signals from the Edit slot is harmless (no double-firing because the form only emits one), but the cleaner shape is to mirror the mode: Edit slot connects `reminder_updated`, Add slot connects `reminder_added`. A doc-comment explains the asymmetry.

- **Datetime pre-fill: UTC → local → naive direction is the inverse of S-06's save.** S-06's `accept()` does `naive.replace(tzinfo=local_tz).astimezone(UTC)` (the explicit `.replace` avoids the cross-version naive-`.astimezone()` issue). The Edit-mode pre-fill goes the other direction: `aware_utc.astimezone().replace(tzinfo=None)` is safe because `.astimezone()` on a tz-aware value is well-defined across all Python versions. One line; no special handling needed beyond what the existing `_qdatetime_from_naive_local` helper already does.

- **`_REMINDERS_BUTTONS_DISABLED_TOOLTIP` constant deletion.** After step 4 (both wrapped buttons drop their wrappers), the constant has no live callers. Delete the constant itself (`settings_dialog.py:206`) AND every test that asserts a wrapper tooltip on Edit / Delete (`tests/test_settings_dialog.py`). Tests that pinned "Edit/Delete are wrapped + disabled" become "Edit/Delete are disabled (no wrapper)" — mirrors the S-06 Add transition test.

## Phase 1: Implementation

### Overview

Land the entire user-visible change in one phase: the form's optional `reminder` parameter + Edit-mode branches, the `SettingsDialog` slot fills + cache + button restructure, the extended test files, the AGENTS.md narrowing. The phase exits when `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pip-audit`, and `uv run pip-licenses --fail-on="AGPL"` are all green.

### Changes Required:

#### 1. `ReminderFormDialog` — accept optional `reminder` and add `reminder_updated`

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Make the form dual-mode (Add / Edit). When `reminder=None` (default), the existing Add behavior is preserved bit-for-bit. When `reminder` is provided, the dialog pre-fills fields from it, flips the window title to `"Edit Reminder"`, and on save routes through `store.update` + `reminder_updated` instead of `store.add` + `reminder_added`. The past-time gate gains a single-line skip branch for "firing time unchanged".

**Contract**: New constructor signature `def __init__(self, *, store: ReminderStore, scheduler: ReminderScheduler, clock: Callable[[], datetime] | None = None, reminder: Reminder | None = None, parent: QWidget | None = None) -> None`. New stored attributes `self._editing: Reminder | None = reminder` and `self._loaded_start_at_utc: datetime | None = reminder.start_at if reminder else None`. New class-level signal `reminder_updated = Signal(Reminder)`. The default-seeding flow is gated by `if self._editing is None`; in Edit mode, the three fields are pre-populated from `self._editing.name`, `self._editing.lead_minutes`, and `self._editing.start_at + timedelta(minutes=self._editing.lead_minutes)` (event time, converted UTC → local → naive). `accept()` order is unchanged except for:

- The past-time gate gets an inner guard: when `self._editing is not None and start_at_utc == self._editing.start_at`, skip the tooltip + return path (the firing time hasn't moved; renaming / re-leading an expired reminder is allowed).
- The `Reminder(...)` constructor in Edit mode passes `id=self._editing.id` to preserve identity for `store.update`.
- The persistence call dispatches: `self._store.update(reminder)` (Edit) vs `self._store.add(reminder)` (Add).
- The signal dispatches: `self.reminder_updated.emit(reminder)` (Edit) vs `self.reminder_added.emit(reminder)` (Add). Both fire BEFORE `super().accept()`.

The module docstring updates: a new short paragraph documenting the Edit mode and the past-time gate skip behavior, with cross-references to the test names that pin the load-bearing pieces.

#### 2. `SettingsDialog._reminders_sorted` — cache the sort order

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Make the QListWidget's row indices mappable back to `Reminder` instances without re-reading the store. Mirrors the `self._reminders_list` / `self._reminders_placeholder` dual-state slots already in place: an empty list means the placeholder branch was taken; a non-empty list means the QListWidget was built.

**Contract**: New stored attribute `self._reminders_sorted: list[Reminder] = []` initialized in `__init__` (alongside `self._reminders_list` and `self._reminders_placeholder`). In `_build_reminders_tab`, after computing the sorted list, assign `self._reminders_sorted = sorted_list` and iterate that same list when constructing `QListWidgetItem` rows (one source of truth for the order). On the empty branch, reset to `[]`. The `_refresh_reminders_tab` flow already calls `_build_reminders_tab`, so the cache stays in lockstep with the widget across refreshes.

#### 3. `SettingsDialog._on_reminders_selection_changed` — fill the body

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Cash in the S-05 hand-off. The selection-changed slot is already wired to `QListWidget.currentRowChanged`; this slice replaces the `pass` body with the documented two-line enable/disable wiring.

**Contract**: Method body becomes `self._reminders_edit_button.setEnabled(current_row >= 0); self._reminders_delete_button.setEnabled(current_row >= 0)`. The `del current_row` placeholder line is removed (the arg is now used). The docstring's "S-07 will replace the body with..." comment becomes "Body shipped in S-07 — Edit and Delete enable on row selection, disable on clear."

#### 4. `SettingsDialog._build_reminders_button_row` — drop wrappers, enable buttons by selection

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Mirror S-06's Add-button treatment: Edit and Delete drop the tooltip-bearing wrapper containers (they're enabled-by-selection now, so Qt delivers hover events natively) and connect to their click handlers. Buttons start disabled (no row selected on a freshly-opened tab); the selection-changed slot from change #3 enables them on demand.

**Contract**: The wrapper-construction loop at the tail of `_build_reminders_button_row` disappears. Edit and Delete are constructed as bare `QPushButton`s with `setEnabled(False)`, parented to the row, and added directly to `row_layout`. New connections: `self._reminders_edit_button.clicked.connect(self._on_reminders_edit_clicked)` and `self._reminders_delete_button.clicked.connect(self._on_reminders_delete_clicked)`. The `_REMINDERS_BUTTONS_DISABLED_TOOLTIP` constant import / reference disappears.

#### 5. Remove the dead `_REMINDERS_BUTTONS_DISABLED_TOOLTIP` constant

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: With #4's wrapper-loop removal, the constant has no live callers. Delete it and its surrounding comment block (`settings_dialog.py:198-206`).

**Contract**: Constant definition deleted; no replacement.

#### 6. `SettingsDialog._on_reminders_edit_clicked` slot

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Open the Edit sub-dialog pre-filled with the currently-selected reminder, refresh the tab on success. Mirrors `_on_reminders_add_clicked` structurally; differs only in the `reminder=` kwarg passed to the form and the `reminder_updated` (vs `reminder_added`) signal connection.

**Contract**: Method signature `def _on_reminders_edit_clicked(self) -> None`. Body:

1. Begin with `assert self._reminders_list is not None, "_on_reminders_edit_clicked should only be reachable when a row is selected, which requires the list to exist"` — same narrowing-assert idiom as `settings_dialog.py:807` for `_reminders_tab`. The invariant holds because the button is only enabled while a row is selected, which requires the list to exist; the assert documents the invariant AND satisfies pyright (which otherwise flags `.currentRow()` on `QListWidget | None`).
2. Locate `selected = self._reminders_sorted[self._reminders_list.currentRow()]`.
3. Construct `sub_dialog = ReminderFormDialog(store=self._reminder_store, scheduler=self._reminder_scheduler, parent=self, reminder=selected)`.
4. Apply `sub_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)`.
5. Connect `sub_dialog.reminder_updated.connect(self._refresh_reminders_tab)`.
6. Call `sub_dialog.exec()`.

#### 7. `SettingsDialog._on_reminders_delete_clicked` slot

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Confirm intent via `QMessageBox.question` (default button `No`), then on Yes delete via store + reload scheduler + refresh tab. No sub-dialog needed; the entire flow is synchronous inside this slot.

**Contract**: Method signature `def _on_reminders_delete_clicked(self) -> None`. Body:

1. Begin with `assert self._reminders_list is not None, "_on_reminders_delete_clicked should only be reachable when a row is selected, which requires the list to exist"` (same narrowing-assert idiom as #6).
2. Locate `selected = self._reminders_sorted[self._reminders_list.currentRow()]`.
3. `reply = QMessageBox.question(self, "Delete reminder", f'Delete reminder "{selected.name}"?\nThis cannot be undone.', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)`.
4. Early return when `reply != QMessageBox.StandardButton.Yes`.
5. Wrap `self._reminder_store.delete(selected.id)` in `try / except OSError as exc`. On exception: `logger.exception("ReminderStore.delete failed")`, anchor a transient tooltip on `self._reminders_delete_button` via `_show_tooltip(self._reminders_delete_button, _DELETE_FAILED_FORMAT.format(error=exc.strerror or str(exc)))`, then early return (no scheduler reload, no tab refresh — atomic-save invariant: a failed delete leaves disk + UI in lockstep). Mirrors the form's `OSError` pattern (`reminder_form_dialog.py:411-421`).
6. On success: `self._reminder_scheduler.reload()`.
7. `self._refresh_reminders_tab()`.

Two module-level additions to `settings_dialog.py` accompany this slot:

- The `QMessageBox` import must be added to the existing PySide6 import block at the top of the file.
- A new module-level constant `_DELETE_FAILED_FORMAT = "Could not delete reminder: {error}"` lives next to the other UI-facing message constants (after `_REMINDERS_BUTTONS_DISABLED_TOOLTIP` in the existing order — though that line is deleted by Phase 1 #5, so adjacency is to whatever ends up there). The `{error}` placeholder is filled with `OSError.strerror` (or `str(exc)` when `strerror` is empty), mirroring the form's `_SAVE_FAILED_FORMAT` convention.

A small `_show_tooltip` helper exists on `SettingsDialog` (mirroring the form's) or this slot can inline the `QToolTip.showText` + `mapToGlobal` pattern used by `_on_break_interval_edited`. The form's helper is the cleanest reference; lift it if it doesn't already exist on `SettingsDialog`.

#### 8. New test class: `TestReminderFormDialogEditMode` in `tests/test_reminder_form_dialog.py`

**File**: `tests/test_reminder_form_dialog.py`

**Intent**: Pin every Edit-mode behavior parallel to the existing Add-mode classes. Mirror the fixture / helper conventions already established.

**Contract**: Module-level fixture `existing_reminder(clock)` returns a `Reminder(id="fixed-edit-id", name="Loaded name", start_at=clock() + timedelta(hours=3), lead_minutes=5)`. Test class `TestReminderFormDialogEditMode` with at minimum:

- `test_edit_mode_window_title_is_edit_reminder` — title flips to `"Edit Reminder"`.
- `test_edit_mode_pre_fills_name_field` — `dialog._name_field.text() == existing_reminder.name`.
- `test_edit_mode_pre_fills_lead_minutes_field` — `dialog._lead_minutes_field.value() == existing_reminder.lead_minutes`.
- `test_edit_mode_pre_fills_datetime_field_with_event_time` — widget's naive-local value equals `(existing_reminder.start_at + timedelta(minutes=existing_reminder.lead_minutes)).astimezone().replace(tzinfo=None)`.
- `test_edit_mode_save_calls_store_update_not_add` — monkeypatch `store.update` and `store.add` with recorders; assert update was called exactly once, add was not called.
- `test_edit_mode_save_preserves_reminder_id` — saved `Reminder.id == existing_reminder.id`.
- `test_edit_mode_save_emits_reminder_updated` — recording slot on `reminder_updated` fires once; `reminder_added` does not fire.
- `test_edit_mode_emit_before_super_accept_ordering` — `dialog.result() == Rejected` at emit time, `Accepted` after `accept()` returns (mirrors the Add-mode pin).
- `test_edit_mode_unchanged_firing_time_skips_past_time_gate` — pre-seed an expired reminder (`start_at = clock() - timedelta(hours=1)`); change only the name; save succeeds; `store.update` called.
- `test_edit_mode_changed_datetime_to_past_blocks_save` — pre-seed a future reminder; user dials datetime backward to past; save is blocked with the standard past-time tooltip; `store.update` NOT called; dialog stays Rejected.
- `test_edit_mode_changed_lead_into_past_blocks_save` — pre-seed event 5 min out with lead=0; user sets lead=30 (firing time = now - 25 min); save blocked.
- `test_edit_mode_name_validation_still_applies` — user clears the name; save blocked with the empty-name tooltip; `store.update` NOT called.
- `test_edit_mode_cancel_does_not_modify_store` — `reject()` → `store.update` not called, no signal, dialog Rejected.
- `test_edit_mode_oserror_on_store_update_blocks_dialog` — monkeypatch `store.update` to raise `PermissionError`; assert dialog stays open, no scheduler reload, no `reminder_updated` emit, OS-error tooltip surfaces.
- `test_add_mode_constructor_still_works_with_reminder_none` — sanity: explicitly passing `reminder=None` produces Add-mode behavior bit-for-bit (same window title, empty name, default datetime, `reminder_added` fires, `reminder_updated` does not).

#### 9. New test classes: `TestRemindersEditButton` and `TestRemindersDeleteButton` in `tests/test_settings_dialog.py`

**File**: `tests/test_settings_dialog.py`

**Intent**: Pin the selection-gates-enable wiring, the click → sub-dialog construction (Edit), the click → QMessageBox.question (Delete), the refresh-on-success flows, and the no-wrapper assertions. Reuse the existing `_StubFormDialog` patterns where applicable; extend with a `reminder=` kwarg capture.

**Contract**: `TestRemindersEditButton`:

- `test_edit_button_disabled_when_no_row_selected` — fresh dialog with reminders present; `dialog._reminders_edit_button.isEnabled() is False`.
- `test_edit_button_enabled_when_row_selected` — `dialog._reminders_list.setCurrentRow(0)` → button enables.
- `test_edit_button_disabled_when_selection_clears` — set row 0, then `setCurrentRow(-1)` → button disables.
- `test_edit_button_has_no_wrapper_tooltip` — `dialog._reminders_edit_button.parentWidget()` is the row container, not a wrapper (mirrors S-06's Add test).
- `test_edit_button_click_opens_sub_dialog_with_loaded_reminder` — monkeypatch `ReminderFormDialog` with `_StubFormDialog` (extended to capture `reminder=` kwarg); click Edit; assert the stub was constructed with `reminder=` matching the selected row's `Reminder`.
- `test_reminder_updated_signal_triggers_tab_refresh` — stub fires `reminder_updated` from `exec`; pre-seed two reminders; click Edit on row 0; assert `_reminders_tab` reference changed and the rebuilt list reflects the post-update state.
- `test_edit_button_disabled_after_refresh_clears_prior_selection` — `setCurrentRow(0)` so the button enables, call `dialog._refresh_reminders_tab()` directly, assert `dialog._reminders_edit_button.isEnabled() is False`. **Tripwire for the "rebuild reassigns the button attribute" invariant**: if a future refactor rebuilds the list without rebuilding the button row, the old enabled button would persist and `_reminders_sorted[currentRow()]` with `currentRow() == -1` would silently index the LAST element of the list, editing the wrong reminder.

`TestRemindersDeleteButton`:

- `test_delete_button_disabled_when_no_row_selected` — fresh dialog; button disabled.
- `test_delete_button_enabled_when_row_selected` — `setCurrentRow(0)` → button enables.
- `test_delete_button_disabled_when_selection_clears` — clear → button disables.
- `test_delete_button_has_no_wrapper_tooltip` — mirrors Edit.
- `test_delete_button_click_calls_qmessagebox_question_with_correct_args` — monkeypatch `QMessageBox.question` with a recorder that returns `No`; click Delete; assert the recorder received `(parent, title, text, Yes|No, defaultButton=No)` with `text` containing the reminder's name and the "cannot be undone" string.
- `test_delete_default_button_is_no` — same as above; assert the 5th positional arg is `QMessageBox.StandardButton.No`.
- `test_delete_confirm_no_does_not_modify_store` — recorder returns `No`; assert `store.delete` not called, `scheduler.reload` not called, list unchanged.
- `test_delete_confirm_yes_removes_reminder_and_refreshes` — recorder returns `Yes`; assert `store.delete(selected.id)` was called once, `scheduler.reload` called, `_reminders_tab` reference changed, the deleted row no longer appears in the rebuilt list.
- `test_delete_button_disabled_after_refresh_clears_prior_selection` — mirror the Edit-side post-refresh tripwire: `setCurrentRow(0)`, call `dialog._refresh_reminders_tab()`, assert `dialog._reminders_delete_button.isEnabled() is False`.
- `test_delete_oserror_on_store_delete_keeps_list_intact` — pre-seed two reminders; monkeypatch `store.delete` to raise `PermissionError("permission denied")`; monkeypatch `QMessageBox.question` recorder to return `Yes`; click Delete on row 0. Assert: `store.list_all()` still returns both reminders (atomic-save invariant — disk unchanged on failure), `scheduler.reload` NOT called, `_reminders_tab` reference unchanged (no rebuild), Delete button state unchanged. Mirrors `test_edit_mode_oserror_on_store_update_blocks_dialog`.

**Wrapper-tooltip cleanup (four artifacts in `tests/test_settings_dialog.py`):**

1. **Remove** `test_edit_delete_tooltip_lives_on_wrapper_not_on_button` (line 2004) — the wrapper contract it pins disappears with this slice.
2. **Remove** `test_edit_and_delete_buttons_remain_wrapped_and_disabled` (line 2217, inside `TestRemindersAddButton`) — same reason. The new `TestRemindersEditButton.test_edit_button_has_no_wrapper_tooltip` and `TestRemindersDeleteButton.test_delete_button_has_no_wrapper_tooltip` (mirroring S-06's `test_add_button_has_no_wrapper_tooltip`) replace its function.
3. **Update docstring only** on `test_empty_state_still_renders_button_row` (line 2147) — the existing test logic stays valid, but the docstring's final paragraph ("Edit/Delete stay disabled with the tooltip until S-07") becomes false. Rewrite to: "Edit/Delete stay disabled until a row is selected (no wrapper, no tooltip — they enable on selection per S-07)."
4. **Remove** the `_REMINDERS_BUTTONS_DISABLED_TOOLTIP` import on `tests/test_settings_dialog.py:45` — the constant goes away (Phase 1 #5) and no remaining tests reference it.

**QMessageBox monkeypatch convention.** The Delete tests above (`test_delete_button_click_calls_qmessagebox_question_with_correct_args`, `test_delete_default_button_is_no`, `test_delete_confirm_*`, `test_delete_oserror_*`) all rely on monkeypatching `QMessageBox.question`. Monkeypatch at the Qt-class level — `from PySide6.QtWidgets import QMessageBox` then `monkeypatch.setattr(QMessageBox, "question", recorder)` — matching the established convention in `tests/test_app.py:373-381` (which uses the same shape for `QMessageBox.information`). Do NOT monkeypatch at the import-site form (`monkeypatch.setattr("break_reminder.ui.settings_dialog.QMessageBox.question", ...)`); the Qt-class-level form survives module-import reorderings and reads cleaner.

#### 10. `AGENTS.md` — narrow the FR-012 bullet to the remaining S-08 surface

**File**: `AGENTS.md`

**Intent**: With Edit / Delete shipped, the entire FR-012 CRUD is complete. The bullet at `AGENTS.md:184` narrows to flag only the still-pending S-08 recurrence editor (FR-014).

**Contract**: Replace the bullet at `AGENTS.md:184` with:

```
- Custom-reminder recurrence editor (FR-014). The read-only Reminders tab shipped in S-05; Add / Edit / Delete CRUD shipped in S-06 / S-07; the daily / weekly / monthly RRULE picker is the last pending Stream B surface (S-08).
```

The phrase fragment `"Custom-reminder Edit / Delete dialog wiring"` no longer appears (Phase 2.1 grep verifies this).

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v` (includes new `TestReminderFormDialogEditMode`)
- Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestRemindersEditButton` + `TestRemindersDeleteButton`)
- Full suite passes: `uv run pytest`
- Type check passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Format check passes: `uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual Verification:

- Open Settings → Reminders with a populated `reminders.json`: Edit and Delete are visibly disabled; clicking either does nothing.
- Select any row: Edit and Delete enable; their disabled-tooltip from the old wrapper no longer appears (no wrapper).
- Click Edit on a future reminder: sub-dialog opens with name, datetime, and lead spinbox pre-filled; title reads "Edit Reminder".
- Change the name only, click OK: sub-dialog closes; row updates in the list; `reminders.json` shows the new name with the same `id`.
- Re-open Edit; change datetime to ~30 seconds from now; OK; wait 30 seconds; the popup fires showing the (possibly updated) name.
- Re-open Edit on an expired reminder; change only the name; OK; row's name updates without a past-time tooltip.
- Re-open Edit on an expired reminder; touch the datetime widget to a past value; OK; past-time tooltip appears; dialog stays open.
- Select a row and click Delete: a Yes/No QMessageBox appears; the default button is "No" (pressing Enter dismisses without deleting).
- Click No / press Enter / press Esc on the confirmation: list unchanged; `reminders.json` unchanged.
- Click Delete → Yes: row disappears from the list; `reminders.json` no longer contains the entry.
- Delete a reminder that was about to fire in ~30 seconds; wait 30+ seconds; the popup does NOT fire (proves the scheduler re-armed after delete).
- Edit / Delete remain disabled with no row selected after a refresh (each rebuild clears the QListWidget selection).
- Add a new reminder via the existing Add flow: works unchanged (Add mode is bit-for-bit preserved).
- Open Settings, close, re-open: state persists correctly through `reminders.json`.
- No regressions: Scheduling, Notifications, Lifecycle tabs continue to behave as before.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation that the manual checks above were successful before proceeding to Phase 2.

---

## Phase 2: Manual smoke + bookkeeping

### Overview

Move the slice from "implemented" to "shipped + traceable": confirm the select → Edit / Delete flows work under real Windows, then mark every document that tracks this slice's status. No code changes in this phase.

### Changes Required:

#### 1. Manual smoke run

**File**: n/a — operational step

**Intent**: With the new Edit / Delete handlers deployed locally (via `uv run python -m break_reminder`), perform the Phase-1 manual verification steps against a real Windows session.

**Contract**: Steps:
1. Stop any running BreakReminder.
2. Pre-seed `%APPDATA%\BreakReminder\reminders.json` with three reminders: one ~30s out, one ~5 min out, one expired (start_at = a known past instant).
3. Run `uv run python -m break_reminder`; open Settings → Reminders; verify all three rows render; Edit/Delete are disabled with no selection.
4. Select the ~5-min reminder; click Edit; change its name to "Edited"; OK; row updates with the new name and same firing time.
5. Re-select; click Edit; change the datetime to ~30s from now; OK; wait ~30s; the popup fires showing "Edited".
6. Select the expired reminder; click Edit; change only the name; OK; row's name updates with no past-time tooltip.
7. Re-select the same expired reminder; click Edit; touch the datetime widget to a past value; OK; past-time tooltip appears; Cancel out.
8. Select a row; click Delete; click No on the confirmation; list and disk unchanged.
9. Click Delete again; press Enter; list and disk unchanged (default button is No).
10. Click Delete; click Yes; row disappears; `reminders.json` reflects the deletion.
11. Delete the ~30-s reminder; wait 30+s; popup does NOT fire (scheduler re-armed).
12. Close Settings; re-open; confirm state persisted correctly.

#### 2. Update `change.md`

**File**: `context/changes/reminders-edit-delete/change.md`

**Intent**: Flip `status: planning` → `status: implemented`. Update `updated:` to today's date. Add a brief "Implementation note" subsection if anything notable surfaced in the smoke run.

**Contract**: YAML front-matter `status` value changes; `updated` date refreshes. Optional `## Notes` "Implementation note" sub-heading appended if needed.

#### 3. Update `roadmap.md`

**File**: `context/foundation/roadmap.md`

**Intent**: Flip the S-07 row in "At a glance" from `proposed` to `done`. Update the `### S-07` block: change `**Status:** proposed` to `**Status:** done`. Update the Backlog Handoff row.

**Contract**: Three substitutions in `roadmap.md`:
1. `| S-07 | reminders-edit-delete | ... | proposed |` (the "At a glance" table row) → `| S-07 | reminders-edit-delete | ... | done |`
2. `- **Status:** proposed` (inside `### S-07` body block) → `- **Status:** done`
3. The Backlog Handoff row for S-07 (column "Ready for `/10x-plan`": `no` → `yes`; Notes: append `Planned + shipped 2026-05-27`).

The `## Done` section entry will be appended at archive time (per the S-05 / S-06 / S-06b precedent — `/10x-archive` adds the entry when it moves the folder).

#### 4. Verify `AGENTS.md` update from Phase 1 #10 landed

**File**: `AGENTS.md`

**Intent**: Confirm the Phase-1 #10 bullet rewrite actually landed.

**Contract**: `git grep -nE 'Custom-reminder Edit / Delete dialog wiring' AGENTS.md` returns no matches. `git grep -nE 'Custom-reminder recurrence editor \(FR-014\)' AGENTS.md` returns exactly one match.

#### 5. Tick the Progress section

**File**: `context/changes/reminders-edit-delete/plan.md`

**Intent**: Mark every Phase 1 and Phase 2 progress item complete, with the merge commit SHA appended per `references/progress-format.md`.

**Contract**: `- [ ]` → `- [x] — <sha>` for each line in the Progress section below.

### Success Criteria:

#### Automated Verification:

- `git grep -nE 'Custom-reminder Edit / Delete dialog wiring' AGENTS.md` returns no matches.
- `git grep -nE 'Custom-reminder recurrence editor \(FR-014\)' AGENTS.md` returns exactly one match.
- `git grep -nE '^\| S-07 .*proposed' context/foundation/roadmap.md` returns no matches.
- `git diff context/changes/reminders-edit-delete/change.md` shows `status: implemented` and an updated `updated:` date.

#### Manual Verification:

- Real Windows: pre-seeded three-reminder state → Edit/Delete enable on selection (Phase 2.1 step 3).
- Real Windows: Edit name only on a future reminder → row updates (Phase 2.1 step 4).
- Real Windows: Edit datetime to near-future → popup fires at the new instant (Phase 2.1 step 5).
- Real Windows: Edit name only on an expired reminder → past-time gate skipped (Phase 2.1 step 6).
- Real Windows: Edit datetime to past on an expired reminder → past-time gate fires (Phase 2.1 step 7).
- Real Windows: Delete → No / Enter / Esc → no-op (Phase 2.1 steps 8-9).
- Real Windows: Delete → Yes → row gone, JSON updated (Phase 2.1 step 10).
- Real Windows: Delete reminder about to fire → popup does NOT fire (Phase 2.1 step 11).
- Real Windows: State persists across Settings open/close (Phase 2.1 step 12).

> Add-flow and Scheduling/Notifications/Lifecycle non-regression checks live in Phase 1 (items 1.18 and 1.19); they are not re-verified in Phase 2.

**Implementation Note**: After completing all checks above, the slice is done. The next slice in Stream B is S-08 (`reminders-recurrence-editor`), unblocked by S-06 (already shipped).

---

## Testing Strategy

### Unit Tests:

- **Form dialog (`tests/test_reminder_form_dialog.py`).** Extend with `TestReminderFormDialogEditMode` covering: window title flip; field pre-fill (name, datetime = event time, lead spinbox); save path (`store.update` not `store.add`; id preserved; `reminder_updated` not `reminder_added`); emit-before-super-accept ordering pin (same shape as Add); past-time gate skip when firing time unchanged + apply when changed (both halves); name validation still applies in Edit mode; cancel path; OSError on `store.update` blocks dialog. Plus a sanity test that `reminder=None` (Add-mode default) keeps Add behavior bit-for-bit.
- **Settings dialog (`tests/test_settings_dialog.py`).** Add `TestRemindersEditButton` and `TestRemindersDeleteButton` classes covering: button enable/disable on selection change; no-wrapper assertion (parallel to S-06's Add); Edit click constructs `ReminderFormDialog` with the right `reminder=` kwarg (via monkeypatched `_StubFormDialog`); Edit `reminder_updated` triggers tab refresh; Delete click invokes `QMessageBox.question` with correct args + `No` as default; Delete `Yes` removes from store + refreshes; Delete `No` does nothing. Update the existing S-05 wrapper-tooltip test for Edit/Delete to assert no-wrapper.

### Integration Tests:

- **`tests/test_app.py` smoke.** Existing app-level tests do not open Settings. No app-level surface changes in this slice. Tests must continue passing unchanged.
- **No new integration test file.** A full "select → Edit → Save → fire" or "select → Delete → no-fire" end-to-end would require timed waits; the unit-test coverage of each link in the chain (form save → store update/delete → scheduler reload → tab refresh) is sufficient and the manual smoke covers the wall-clock case.

### Manual Testing Steps:

The Phase 2.1 step list IS the manual testing surface; see Phase 2 above.

## Performance Considerations

- **`update()` and `delete()` cost.** Both are O(N) on the reminder list (linear scan inside the store). For the persona's ≤10 reminders, sub-millisecond. Called once per Edit-save or Delete-confirm — no concern.
- **`reload()` cost.** Same as S-06 — a single `list_all()` re-read + per-reminder `next_firing_after`. Sub-millisecond for ≤10 reminders.
- **Tab rebuild cost.** Same as S-06 — `removeTab` + `_build_reminders_tab` + `insertTab`. Sub-millisecond.
- **`_reminders_sorted` cache.** Stores up to ≤10 `Reminder` references; negligible memory cost. Refreshed on every `_build_reminders_tab` call so it never leaks stale state across refreshes.

## Migration Notes

- **No data migration.** `reminders.json` schema is unchanged (no new fields). Existing entries continue to work — Edit reads them, Delete removes them.
- **No setting migration.** No new `Settings` keys.
- **No installer / PyInstaller change.** Same release pipeline.

## References

- Roadmap entry: `context/foundation/roadmap.md` § S-07
- PRD: `context/foundation/prd.md` FR-012 (line 125)
- S-06 plan (closest pattern precedent — form sub-dialog + refresh-on-success): `context/archive/2026-05-27-reminders-add-form/plan.md`
- S-06 retrospective impl-review (F6: WA_DeleteOnClose, F2: atomic-save tripwire): `context/archive/2026-05-27-reminders-add-form/reviews/retrospective-impl-review.md`
- S-05 plan (pattern precedent — wrapper tooltip + currentRowChanged scaffold): `context/archive/2026-05-27-reminders-list-view/plan.md`
- Storage layer (CRUD primitives): `break_reminder/storage/reminders.py:148-158`
- Form module (reuse contract documented): `break_reminder/ui/reminder_form_dialog.py:17-24`
- Settings dialog (existing button row + selection slot): `break_reminder/ui/settings_dialog.py:643-791`
- App-level QMessageBox precedent: `break_reminder/app.py:357-367`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Implementation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v` (includes new `TestReminderFormDialogEditMode`) — a4daa43
- [x] 1.2 Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestRemindersEditButton` + `TestRemindersDeleteButton`) — a4daa43
- [x] 1.3 Full suite passes: `uv run pytest` — a4daa43
- [x] 1.4 Type check passes: `uv run pyright` — a4daa43
- [x] 1.5 Linting passes: `uv run ruff check` — a4daa43
- [x] 1.6 Format check passes: `uv run ruff format --check` — a4daa43
- [x] 1.7 Security audit passes: `uv run pip-audit` — a4daa43
- [x] 1.8 License gate passes: `uv run pip-licenses --fail-on="AGPL"` — a4daa43

#### Manual

- [x] 1.9 Edit/Delete disabled with no selection; enable on row select; disable on clear — a4daa43
- [x] 1.10 Edit click opens sub-dialog pre-filled (name + datetime as event time + lead spinbox); title "Edit Reminder" — a4daa43
- [x] 1.11 Edit name only on a future reminder → row updates with same firing time — a4daa43
- [x] 1.12 Edit datetime to ~30s from now → popup fires at the new instant — a4daa43
- [x] 1.13 Edit name only on an expired reminder → past-time gate skipped, row's name updates — a4daa43
- [x] 1.14 Edit datetime backward on an expired reminder → past-time tooltip appears, dialog stays open — a4daa43
- [x] 1.15 Delete → No / Enter / Esc → no-op (default button is No) — a4daa43
- [x] 1.16 Delete → Yes → row gone from list + JSON — a4daa43
- [x] 1.17 Delete a near-firing reminder → popup does NOT fire (scheduler re-armed) — a4daa43
- [x] 1.18 Add flow still works unchanged — a4daa43
- [x] 1.19 No regressions in Scheduling / Notifications / Lifecycle tabs — a4daa43

### Phase 2: Manual smoke + bookkeeping

#### Automated

- [x] 2.1 `git grep -nE 'Custom-reminder Edit / Delete dialog wiring' AGENTS.md` returns no matches — 2d39974
- [x] 2.2 `git grep -nE 'Custom-reminder recurrence editor \(FR-014\)' AGENTS.md` returns exactly one match — 2d39974
- [x] 2.3 `git grep -nE '^\| S-07 .*proposed' context/foundation/roadmap.md` returns no matches — 2d39974
- [x] 2.4 `git diff context/changes/reminders-edit-delete/change.md` shows `status: implemented` and updated `updated:` date — 2d39974

#### Manual

- [x] 2.5 Real Windows: pre-seeded three-reminder state → Edit/Delete enable on selection (Phase 2.1 step 3) — 2d39974
- [x] 2.6 Real Windows: Edit name only on a future reminder → row updates (Phase 2.1 step 4) — 2d39974
- [x] 2.7 Real Windows: Edit datetime to near-future → popup fires (Phase 2.1 step 5) — 2d39974
- [x] 2.8 Real Windows: Edit name only on expired → past-time gate skipped (Phase 2.1 step 6) — 2d39974
- [x] 2.9 Real Windows: Edit datetime to past on expired → past-time gate fires (Phase 2.1 step 7) — 2d39974
- [x] 2.10 Real Windows: Delete → No / Enter / Esc → no-op (Phase 2.1 steps 8-9) — 2d39974
- [x] 2.11 Real Windows: Delete → Yes → row gone, JSON updated (Phase 2.1 step 10) — 2d39974
- [x] 2.12 Real Windows: Delete near-firing reminder → no popup (Phase 2.1 step 11) — 2d39974
- [x] 2.13 Real Windows: state persists across Settings open/close (Phase 2.1 step 12) — 2d39974
