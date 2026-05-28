---
change_id: bugfix-break-cycle-reset-on-save
title: BreakScheduler resets cycle when break interval is saved (S-09)
status: impl_reviewed
created: 2026-05-28
updated: 2026-05-28
archived_at: null
---

## Notes

Roadmap S-09 — bugfix slice. `BreakScheduler._active_seconds` (the tray-countdown's source of truth) is reset only by `on_break_taken()` / `on_break_snoozed()` / construction; nothing resets it when the user saves a new `break_interval_min` from `SettingsDialog`. Symptom: the tray tooltip's seconds digit stays frozen at the prior cycle's sub-minute offset (because both old and new thresholds are multiples of 60, so `(threshold − _active_seconds) % 60 = (−_active_seconds) % 60`, independent of the threshold change). Functional consequence: the next break fires up to 59 seconds early or late relative to the new threshold. Fix: add `BreakScheduler.reset_cycle()` (mirrors `on_break_taken`'s body), have `SettingsDialog.accept()` emit `break_interval_changed(int)` when the value actually changed, wire it from `BreakReminderApp._on_open_settings()` to a new slot that calls `reset_cycle()` + `_refresh_tooltip()`.
