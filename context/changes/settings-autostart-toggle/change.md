---
change_id: settings-autostart-toggle
title: Wire FR-003 autostart toggle to per-user Run registry key
status: impl_reviewed
created: 2026-05-26
updated: 2026-05-26
archived_at: null
---

## Notes

Roadmap slice **S-02: settings-autostart-toggle** (`context/foundation/roadmap.md`).

User opens Settings → new "Lifecycle" tab, ticks "Launch BreakReminder at Windows login", clicks OK; the per-user Run-key registry write fires (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\BreakReminder` with the value `"<sys.executable>"`); on next Windows login, BreakReminder appears in the tray without manual launch. Unticking + OK removes the Run-key entry. On winreg failure (`PermissionError`, `OSError`, etc.) the dialog surfaces a transient `QToolTip` anchored on the checkbox and blocks the entire save (atomic-save invariant from S-03 impl-review F2 extends to a fourth field).

Closes the v0.1.0 "Known stubs" line from `tech-stack.md` and `AGENTS.md` ("Autostart toggle (FR-003) — settings key wired; registry write not"). Final slice of Stream A (settings panel) on the roadmap; afterward the dialog has all four FR-003/FR-006/FR-007/FR-010 user-configurable surfaces.
