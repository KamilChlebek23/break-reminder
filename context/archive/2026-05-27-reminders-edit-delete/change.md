---
change_id: reminders-edit-delete
title: Edit and delete custom reminders from the Reminders list
status: archived
created: 2026-05-27
updated: 2026-05-27
archived_at: 2026-05-27T20:09:30Z
roadmap_ref: S-07
prd_refs: [FR-012]
---

## Notes

Roadmap slice **S-07: reminders-edit-delete** (`context/foundation/roadmap.md`).

User selects an existing reminder in the Reminders tab list (shipped by S-05) and either clicks **Edit…** (opens the S-06 `ReminderFormDialog` pre-filled with the selected row's values) or **Delete** (removes the reminder, with a confirmation). Changes are persisted via the existing `ReminderStore.update()` / `ReminderStore.delete()` CRUD primitives, the running session is re-armed via `ReminderScheduler.reload()`, and the Reminders list rebuilds in place to reflect the new state.

This slice closes the FR-012 list/edit/delete CRUD surface that S-05 (read-only list) and S-06 (Add) opened. The Edit/Delete buttons and the `currentRowChanged → _on_reminders_selection_changed` wiring already exist as no-op scaffolding from S-05; this slice fills the bodies in.
