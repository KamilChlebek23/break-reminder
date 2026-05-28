---
change_id: reminders-recurrence-editor
title: Reminders recurrence editor (S-08)
status: implemented
created: 2026-05-28
updated: 2026-05-28
archived_at: null
---

## Notes

Roadmap S-08 — the last pending Stream B (custom reminders) surface. Extends the existing `ReminderFormDialog` (S-06 / S-06b / S-07) with a recurrence picker (None / Daily / Weekly / Monthly) and an optional "End on:" date, translating the picker to RFC 5545 RRULE strings on save and reverse-parsing them on Edit. Storage layer (`Reminder.rrule_str` + `Reminder.end_at`) and the scheduler RRULE engine (`next_firing_after`) are already shipped — this slice is concentrated in the form dialog, the Reminders list row indicator, and tests.
