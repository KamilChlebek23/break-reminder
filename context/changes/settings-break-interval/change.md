---
id: settings-break-interval
type: slice
roadmap_ref: S-01
status: implementing
created: 2026-05-25
updated: 2026-05-25
prd_refs: [FR-005, FR-006]
---

# settings-break-interval

Roadmap slice **S-01: settings-window-break-interval-only** from `context/foundation/roadmap.md`.

Replace the `QMessageBox` placeholder at `BreakReminderApp._on_open_settings()` with a real `SettingsDialog(QDialog)` that lets the user view and edit the break interval inside a real settings window. Smallest user-visible flow that closes FR-005 + FR-006 and unlocks the rest of v0.2.x.

- **Plan brief:** `plan-brief.md`
- **Full plan:** `plan.md`
- **Roadmap entry:** `context/foundation/roadmap.md` § S-01
