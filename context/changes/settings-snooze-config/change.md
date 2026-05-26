---
change_id: settings-snooze-config
title: Snooze duration and max snoozes editable from settings dialog
status: implemented
created: 2026-05-26
updated: 2026-05-26
archived_at: null
---

## Notes

Roadmap slice **S-03: settings-snooze-config** (`context/foundation/roadmap.md`).

User opens Settings → Scheduling tab, edits "Snooze duration (minutes)" (range 1–30) and "Max snoozes per cycle" (range 0–5), saves; the next break dialog respects the new values. Closes PRD Open Question #1 (snooze duration default value) by giving the user a UI to pick their own value rather than committing to 5 vs 10.

**Scope addendum (mid-Phase-1, 2026-05-26)**: While Phase 1 was in flight, the user asked for the tray-icon tooltip to switch from `BreakReminder — next break in Xm YYs` to `BreakReminder — snooze time left Xm YYs` while a snooze window is open. Folded into this slice because it's the same feature surface ("snooze is a thing the user can see and control") and the added test coverage was small (+7 tests). Plan + brief amended to reflect.

Completes Stream A (settings panel) of the roadmap once paired with already-shipped S-01 (break interval) and S-04 (voice toggle).
