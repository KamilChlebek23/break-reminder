---
change_id: reminders-lead-time
title: Add "notify N min before event" lead-time option to reminders
status: impl_reviewed
created: 2026-05-27
updated: 2026-05-27
archived_at: null
roadmap_ref: S-06b
prd_refs: [FR-011, FR-013]
---

## Notes

New roadmap slice **S-06b: reminders-lead-time** — extends the freshly-shipped S-06 (`reminders-add-form`) so a user can configure a reminder to fire *before* the event itself, not at the event instant.

UX shape: a "Notify X min before event" `QSpinBox` (0-60, step 1, default 0) appears alongside the existing `Name` and `Date/time` fields in the `ReminderFormDialog`. When `lead_minutes > 0`, the datetime field is now interpreted as the **event time**; the form computes `start_at = event_at - timedelta(minutes=lead_minutes)` at save. When `lead_minutes == 0` (the default), the form behaves identically to S-06 (datetime = firing time).

Storage model A (chosen): `start_at` keeps its current meaning ("when the reminder fires"); a new `Reminder.lead_minutes: int = 0` field carries the offset as form-roundtrip metadata. Backward compatible — existing `reminders.json` entries load with `lead_minutes = 0`. S-07 Edit (future) can faithfully roundtrip both fields by computing `event_at = start_at + timedelta(minutes=lead_minutes)` on load.

Past-time validation tightens: instead of "fire_at > now", the form now rejects with "Event must be at least N minutes in the future" (specific wording with N=lead), falling back to "Event must be in the future" when `lead_minutes == 0`. Computation is the same — `start_at > now()` — only the error message differs based on lead_minutes.

List display in the Reminders tab gains a "(fires N min before)" annotation when `lead_minutes > 0`; rows with `lead_minutes == 0` render unchanged.

Out of scope: popup text changes (still shows just the reminder name — FR-013 unchanged), recurring reminders (S-08 territory), and Edit/Delete wiring (S-07 territory). This slice only touches the Add path.
