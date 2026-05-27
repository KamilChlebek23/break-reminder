---
change_id: reminders-list-view
title: Reminders tab with read-only list bound to reminders.json
status: impl_reviewed
created: 2026-05-27
updated: 2026-05-27
archived_at: null
prd_refs: [FR-005, FR-012]
roadmap_ref: S-05
---

## Notes

Roadmap slice **S-05: reminders-list-view** (`context/foundation/roadmap.md`).

User opens Settings → new "Reminders" tab and sees a read-only list of every custom reminder saved in `%APPDATA%\BreakReminder\reminders.json`. Each row reads `"<name> — <next firing | (expired)>"`, sorted chronologically (soonest first; expired sink to bottom; tiebreak by name). When the store is empty, the list is replaced by a centered placeholder label hinting at the (still-disabled) Add button. Add / Edit / Delete buttons are present below the list but disabled with a "coming in a future update" tooltip; Edit/Delete additionally only enable when a row is selected, so the click-to-enable wiring is in place when S-07 lights the click handlers up.

Closes FR-012's *list* surface (edit/delete land in S-07; add in S-06) and resolves Open Roadmap Question #6 ("rule string or next-firing?") in favour of next-firing. First slice of Stream B (custom reminders); piggybacks on the `SettingsDialog` tab pattern established by S-01..S-04.

- **Plan brief:** `plan-brief.md`
- **Full plan:** `plan.md`
- **Roadmap entry:** `context/foundation/roadmap.md` § S-05
