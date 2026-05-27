---
change_id: reminders-add-form
title: Add custom reminder form (name + future date/time) wired through scheduler
status: archived
created: 2026-05-27
updated: 2026-05-27
archived_at: 2026-05-27T10:50:33Z
roadmap_ref: S-06
prd_refs: [FR-011, FR-013]
---

## Notes

Roadmap slice **S-06: reminders-add-form** (`context/foundation/roadmap.md`).

User clicks the previously-disabled "Add…" button in the Reminders tab (shipped by S-05); a modal sub-dialog opens with two fields — `Name` and `Date/time` — and OK/Cancel buttons. OK validates (non-empty name; `fire_at` strictly in the future), persists a one-shot `Reminder` via `ReminderStore.add()`, arms the running session via `ReminderScheduler.reload()`, and the Reminders list rebuilds in place to show the new row. At the chosen instant, the existing dismissable `notifications/reminder_dialog.py` popup fires (FR-013).

Establishes three new conventions the codebase doesn't have yet:

- First modal sub-dialog launched with `QDialog.exec()` from inside another dialog.
- First `QDateTimeEdit` usage (calendar-popup variant).
- First explicit `store.add() → scheduler.reload()` save path; this is the integration surface the roadmap flagged as S-06's only real risk.

Folds a small pre-S-06 refactor: inject a `clock: Callable[[], datetime] | None = None` parameter into `ReminderScheduler.__init__`, mirroring the existing `BreakScheduler` pattern, so the new `tests/test_reminder_scheduler.py` can drive "add → fire" deterministically.

No recurrence in this slice — S-08 owns the RRULE editor. No Edit / Delete wiring — S-07 owns those. The Reminders tab keeps the wrapper-tooltip pattern S-05 established for the still-disabled Edit/Delete buttons; only the Add button drops its wrapper after this slice.
