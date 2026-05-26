---
change_id: settings-autostart-toggle
title: Wire FR-003 autostart toggle to per-user Run registry key
status: implemented
created: 2026-05-26
updated: 2026-05-26
archived_at: null
---

## Notes

Roadmap slice **S-02: settings-autostart-toggle** (`context/foundation/roadmap.md`).

User opens Settings → new "Lifecycle" tab, ticks "Launch BreakReminder at Windows login", clicks OK; the per-user Run-key registry write fires (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run\BreakReminder` with the value `"<sys.executable>"`); on next Windows login, BreakReminder appears in the tray without manual launch. Unticking + OK removes the Run-key entry. On winreg failure (`PermissionError`, `OSError`, etc.) the dialog surfaces a transient `QToolTip` anchored on the checkbox and blocks the entire save (atomic-save invariant from S-03 impl-review F2 extends to a fourth field).

Closes the v0.1.0 "Known stubs" line from `tech-stack.md` and `AGENTS.md` ("Autostart toggle (FR-003) — settings key wired; registry write not"). Final slice of Stream A (settings panel) on the roadmap; afterward the dialog has all four FR-003/FR-006/FR-007/FR-010 user-configurable surfaces.

## Post-merge fixes

**2026-05-26 — autostart helpers crash on machines without a pre-existing `HKCU\...\Run` subkey.** The v0.5.0 release pipeline surfaced an 11-test CI failure (0 local) traced to `winreg.OpenKey` raising `FileNotFoundError [WinError 2]` against the `runneradmin` profile on `windows-latest`, whose Run subkey didn't exist at all. The exception escaped `_delete_autostart_runkey` (which only caught `FileNotFoundError` from the inner `DeleteValue` call, not the outer `OpenKey`), tripped `accept()`'s atomic-save tooltip, and blocked every persistence assertion downstream. Phase 1 review missed this because no test stubbed `OpenKey` raising — only `DeleteValue` was covered, which silently relies on the subkey existing.

Fix:

- `_write_autostart_runkey`: `winreg.OpenKey` → `winreg.CreateKeyEx` (opens-or-creates idiom — same fix prevents the symmetric production bug where ticking + OK on a fresh user profile would also fail).
- `_delete_autostart_runkey`: outer `try/except FileNotFoundError` around the entire `with` block — both "subkey absent" and "value absent" now map to the same "already-deleted" success semantic.
- Tests: scaffold extended to patch `winreg.CreateKeyEx`; three new regression tests (`test_write_helper_succeeds_when_subkey_missing`, `test_delete_helper_swallows_filenotfounderror_when_subkey_missing`, `test_delete_helper_propagates_oserror_from_openkey`) pin both the subkey-missing-success and the symmetric `PermissionError`-propagation paths so the gap can't reopen.

Slice status remains `implemented`; this is a CI-hardening hotfix landing under the v0.5.0 tag.
