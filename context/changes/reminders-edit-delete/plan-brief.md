# Reminders Edit / Delete — Plan Brief

> Full plan: `context/changes/reminders-edit-delete/plan.md`

## What & Why

S-07 fills the two remaining no-op buttons in the Reminders tab — `Edit…` and `Delete` — by reusing the S-06 `ReminderFormDialog` (extended with an optional `reminder` parameter) for editing and a `QMessageBox` Yes/No confirmation for deletion. Closes the FR-012 list/edit/delete CRUD surface; with this slice S-08's recurrence editor becomes the last remaining Stream B item. The `ReminderFormDialog` docstring authored the reuse contract back in S-06 explicitly so this slice could land without restructuring.

## Starting Point

S-06 shipped the Add sub-dialog and established the "open form → validate → store mutation → scheduler reload → emit signal → refresh tab" pattern. The Edit and Delete buttons exist as no-op scaffolding inside the S-05 button row (disabled, wrapped in tooltip containers reading "Coming in a future update"). The `currentRowChanged → _on_reminders_selection_changed` wiring is already in place with a `pass` body; the S-05 plan documents the exact S-07 hand-off shape. `ReminderStore.update(reminder)` and `ReminderStore.delete(reminder_id)` are atomic and lock-protected — no new storage code.

## Desired End State

Selecting any row enables Edit and Delete. Edit opens the form pre-filled (name, event-time-converted-to-local datetime, lead spinbox) with the title flipped to "Edit Reminder"; OK persists via `store.update`, re-arms the scheduler, and the tab rebuilds in place. Delete opens a `QMessageBox` confirmation (default button: No) — Yes removes via `store.delete`, re-arms, refreshes; No / Esc / Enter does nothing. Both flows leave the running session correctly armed against the modified store, including the case of deleting a reminder that was about to fire.

## Key Decisions Made

| Decision                          | Choice                                                                                  | Why (1 sentence)                                                                                            |
| --------------------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Form reuse strategy               | Reuse `ReminderFormDialog` with optional `reminder: Reminder \| None = None` parameter   | Matches the docstring's explicit promise (S-06's `reminder_form_dialog` module name was chosen for this).   |
| Signal shape                      | Add `reminder_updated = Signal(Reminder)` alongside `reminder_added` (non-breaking)     | Existing tests pinning `reminder_added` stay valid; the signal name documents which mode ran.               |
| Delete confirmation UX            | Modal `QMessageBox.question` Yes/No with `No` as the default button                     | Matches the `app.py` QMessageBox precedent; default-No prevents accidental-Enter destruction.               |
| Past-time gate in Edit mode       | Skip when `start_at_utc_current == self._editing.start_at` (firing time unchanged)      | Lets the user rename / re-lead an expired reminder without rescheduling; FR-011 future-event intent kept.   |
| Multi-select                      | Single-select only (S-05 default)                                                       | The persona's ≤10 reminders make batch-delete UX cost unjustified; modifier-key UX adds surface area.       |
| Phase shape                       | Two phases (Phase 1: code + automated; Phase 2: manual smoke + bookkeeping)             | Mirrors S-02..S-06 cadence; clean pause point between green CI and the human smoke step.                    |

## Scope

**In scope:**
- Extend `ReminderFormDialog`: optional `reminder` constructor param; new `reminder_updated` signal; Edit-mode pre-fill (name + datetime as event time + lead); past-time gate skip when firing time unchanged; `store.update` (not `store.add`) in Edit mode.
- `SettingsDialog`: cache sorted reminders list (`self._reminders_sorted`); fill `_on_reminders_selection_changed` body (enable Edit/Delete on selection); restructure `_build_reminders_button_row` to drop Edit/Delete wrappers + start disabled + wire to new slots; remove dead `_REMINDERS_BUTTONS_DISABLED_TOOLTIP` constant.
- Two new slots: `_on_reminders_edit_clicked` (open form with `reminder=` kwarg + `WA_DeleteOnClose`) and `_on_reminders_delete_clicked` (`QMessageBox.question` → store.delete → reload → refresh).
- Extend `tests/test_reminder_form_dialog.py` with `TestReminderFormDialogEditMode` (14 tests).
- Extend `tests/test_settings_dialog.py` with `TestRemindersEditButton` + `TestRemindersDeleteButton`; rewrite the S-05 wrapper-tooltip test for Edit/Delete to assert no-wrapper.
- Narrow the `AGENTS.md` "Custom-reminder Edit / Delete dialog wiring" bullet to the remaining S-08 recurrence editor.

**Out of scope:**
- Recurrence editor / RRULE field (S-08 owns).
- Multi-select / batch delete; drag-and-drop reorder; double-click to Edit; Delete key shortcut.
- Optimistic UI / undo affordance; new `Settings` keys ("skip delete confirm" toggle).
- New `reminder_deleted` signal (Delete is fully synchronous inside `SettingsDialog`); event-log integration for Edit/Delete events.
- NSIS / PyInstaller / release-workflow / autostart / pause / voice / tray changes.

## Architecture / Approach

The slice threads zero new dependencies into `SettingsDialog` (`ReminderScheduler` was wired in S-06). Data flow on Edit:

```
[select row] → currentRowChanged → _on_reminders_selection_changed
   → edit/delete buttons enable
[click Edit] → SettingsDialog._on_reminders_edit_clicked()
   → ReminderFormDialog(store, scheduler, parent=self, reminder=selected).exec()
      → user edits fields → OK
         → validate name (strip + non-empty) → tooltip-and-return on fail
         → validate datetime (skip past-time gate iff firing time unchanged) → tooltip-and-return on fail
         → Reminder(name, start_at, lead_minutes, id=self._editing.id)
         → reminder_store.update(reminder)
            → on OSError: tooltip-and-return, dialog stays open
         → reminder_scheduler.reload()
         → self.reminder_updated.emit(reminder)
         → super().accept()
      → exec() returns Accepted
   → connected slot: SettingsDialog._refresh_reminders_tab()
      → removeTab + _build_reminders_tab (which refreshes _reminders_sorted) + insertTab
```

Data flow on Delete:

```
[click Delete] → SettingsDialog._on_reminders_delete_clicked()
   → QMessageBox.question(parent=self, title, text, Yes|No, defaultButton=No)
      → reply == Yes
         → reminder_store.delete(selected.id)
         → reminder_scheduler.reload()
         → self._refresh_reminders_tab()
      → reply != Yes → no-op
```

The load-bearing details mirror S-06's: emit BEFORE `super().accept()`, `WA_DeleteOnClose` on the sub-dialog, the same `_refresh_reminders_tab` hook. The one genuinely new pattern is the **past-time gate skip** (one extra branch in `accept()`, two tests pinning both halves).

## Phases at a Glance

| Phase                            | What it delivers                                                                                                  | Key risk                                                                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1. Implementation                | Form `reminder=` param + `reminder_updated`; SettingsDialog cache + slot fill + button restructure; QMessageBox confirm; 2 extended test files; AGENTS.md narrowing. | Past-time gate skip condition wrong (e.g., comparing event_at instead of start_at) would let a user accidentally save an unreachable firing time on Edit — pinned by two unit tests covering both halves. |
| 2. Manual smoke + bookkeeping    | Real-Windows verification of select → Edit / Delete flows + pre-seeded expired-reminder edge case; change.md / roadmap.md / AGENTS.md updates; Progress section ticked. | Manual smoke covers the wall-clock cases the unit tests skip (e.g., deleting a near-firing reminder and confirming no popup); skip would miss the scheduler-rearm assurance. |

**Prerequisites:** S-06 shipped + archived (`reminder_form_dialog` module with reuse contract); S-05 shipped + archived (Reminders tab + selection wiring scaffold); the v0.1.0 `ReminderStore` / `ReminderScheduler` / `ReminderDialog` triad in place.
**Estimated effort:** ~1 session across 2 phases. Most of the surface is well-paved by S-05 / S-06; the genuinely new pieces are the `TestReminderFormDialogEditMode` class (14 tests) and the QMessageBox-confirm wiring.

## Open Risks & Assumptions

- **Selection-to-Reminder mapping via `_reminders_sorted` cache.** The slice introduces a small piece of mutable state (`self._reminders_sorted: list[Reminder]`) that must stay in lockstep with the QListWidget items. The single source of truth is `_build_reminders_tab` (both the widget and the cache are built from the same sorted result in the same loop iteration), and `_refresh_reminders_tab` re-runs it, so the cache cannot drift. A test pins this by inspecting the cache after a refresh.
- **Past-time gate skip when only the name changes on an expired reminder.** The `start_at_utc == self._editing.start_at` comparison succeeds in this case (datetime widget value unchanged, lead unchanged → firing time unchanged). Acceptable per design; FR-011's "future event" intent is honored when the user IS changing the firing time.
- **QMessageBox styling differs slightly from QDialog.** The confirmation dialog inherits OS-native styling rather than the QDialog look the rest of the codebase uses. Acceptable — different semantic class (confirm vs. settings).
- **`store.update` no-op when `id` not found.** If somehow the loaded `Reminder.id` doesn't match any row (e.g., the user edits the JSON file manually between opening the form and clicking Save), the save silently no-ops and the list rebuilds without the edited row. Vanishingly rare for single-user single-machine; not worth detection logic in v1.
- **No event-log integration for Edit / Delete.** FR-015's event log captures firings (TAKEN / MISSED / REMINDER), not CRUD operations. Consistent with the existing surface — no slice adds CRUD events to the log.

## Success Criteria (Summary)

- User can open Settings → Reminders → select a row → Edit or Delete; both flows correctly update `reminders.json`, re-arm the running scheduler, and refresh the list in place.
- All automated gates pass (pytest / pyright / ruff / pip-audit / pip-licenses) with no regressions in the S-04 / S-05 / S-06 / S-06b test surfaces.
- The roadmap S-07 row flips to `done`; AGENTS.md narrows the pending Custom-reminder bullet to recurrence (S-08) only.
