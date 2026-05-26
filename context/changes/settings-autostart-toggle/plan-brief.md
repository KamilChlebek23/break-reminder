# Settings Autostart Toggle — Plan Brief

> Full plan: `context/changes/settings-autostart-toggle/plan.md`

## What & Why

Wire FR-003 end-to-end. v0.1.0 left "the settings key wired; the registry write is not" as a known stub (`tech-stack.md:91`); this slice closes it. User opens Settings → new "Lifecycle" tab → ticks "Launch BreakReminder at Windows login" → OK → next Windows login the app appears in the tray without manual launch. Untick + OK removes the autostart entry. Final slice of Stream A on the roadmap.

## Starting Point

The persistence layer is half-built today: `DEFAULT_AUTOSTART = False`, the `_Keys.AUTOSTART` constant, the `Snapshot.autostart` field, and the `Settings.autostart` getter all exist (`break_reminder/storage/settings.py:52-79, 274-277`). What's missing is the setter, any `winreg` code anywhere in the app, and any UI affordance — the dialog has Scheduling and Notifications tabs but no autostart surface.

## Desired End State

Three tabs in the Settings dialog (Scheduling, Notifications, Lifecycle), with the new Lifecycle tab housing a single autostart checkbox. Ticking + OK writes a `"<sys.executable>"` value to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\BreakReminder`; unticking + OK deletes it. Failures (registry locked-down, permission denied) surface as a transient `QToolTip` on the checkbox and block the entire save (atomic-save invariant). The "Known stubs" list in `tech-stack.md` and `AGENTS.md` no longer mentions autostart; the README's Settings-dialog bullet does.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) |
|---|---|---|
| UI placement | New "Lifecycle" tab | Maps to the existing `lifecycle/` namespace in `_Keys`; clean conceptual scope; future home for FR-016 controls. |
| winreg encapsulation | Inline (in `settings_dialog.py`, via two module-level helpers) | Smallest possible new surface; one place owns the OS I/O; no new module/package needed for one caller. |
| Save timing | Atomic on OK (registry write THEN INI writes) | Preserves the S-01/S-03/S-04 "OK saves everything or nothing" contract; keeps INI and registry synchronized after every successful save. |
| Run-key value | `f'"{sys.executable}"'` (quoted absolute path, no args) | PyInstaller-frozen `sys.executable` is the production exe at a stable per-user install path; quoting future-proofs spaces in the path; no CLI flags needed (app already starts minimized to tray). |
| Error handling | Tooltip on the checkbox + block save | Mirrors the S-04 voice-empty-phrase atomic-save tripwire; user sees the failure at the moment they tried to save; can untick and retry to escape. |
| Drift policy | None — INI is intent, last-save-wins | Idempotent registry write/delete on every OK; no startup reconciler; user who manually deletes the Run-key in `regedit` gets it back next OK. |
| Testing approach | Two thin module-level helpers (`_write_autostart_runkey`, `_delete_autostart_runkey`); monkeypatched in tests | Narrow, named patch surface; readable assertions ("helper called with this command"); helpers themselves test-covered via `winreg`-monkeypatched tests. |
| Atomic-save scope on failure | Block all four fields (interval, snooze, voice, autostart) | Extends the S-03 impl-review F2 invariant to a fourth field; one mental model, no partial saves. |

## Scope

**In scope:**

- New `Settings.autostart` setter (mirrors `voice_enabled.setter`).
- New "Lifecycle" tab + autostart checkbox in `SettingsDialog`.
- Two module-level winreg helpers in `settings_dialog.py`.
- `accept()` wiring for atomic registry-then-INI save with tooltip-on-failure.
- Unit tests covering the setter, the dialog flow (helper-mocked), the helpers themselves (winreg-mocked), and the extended atomic-save tripwire.
- Documentation updates: drop the autostart line from `tech-stack.md` and `AGENTS.md` "Known stubs"; mention the affordance in `README.md`.

**Out of scope:**

- No `AutostartManager` module / no `lifecycle/` Python package.
- No NSIS installer changes (the installer continues to NOT write a Run-key).
- No startup reconciliation — INI is intent, registry is OS state, and they're allowed to drift.
- No source-run autostart support (production = PyInstaller-frozen exe).
- No CLI flags on the launched binary.
- No DI / Protocol shapes for the helpers.

## Architecture / Approach

```
SettingsDialog.accept() flow:
  1. validate voice phrase (existing) → on fail: tooltip + return
  2. compute command = f'"{sys.executable}"'
  3. try:
       _write_autostart_runkey(command)  if checkbox.isChecked()
       _delete_autostart_runkey()        otherwise
     except OSError:
       switch to Lifecycle tab; tooltip on autostart checkbox; return
  4. write all INI setters (interval, snooze, voice, autostart)
  5. super().accept()
```

The two helpers wrap `winreg.SetValueEx` / `winreg.DeleteValue` against `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` for the value name `BreakReminder`. `_delete_autostart_runkey` swallows `FileNotFoundError` so unticking on a system that never had the entry is a no-op. Both let `OSError` / `PermissionError` propagate to the caller.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Implementation | Setter + Lifecycle tab + helpers + `accept()` wiring + full unit-test coverage; all automated gates green | Atomic-save ordering — must call the registry helper BEFORE any INI setter, else a registry failure leaves INI ahead of OS state. |
| 2. Manual smoke + bookkeeping | Real Windows logout/login proves the tray icon auto-launches; flip `change.md` to `implemented`, S-02 in roadmap to `done`, drop autostart from `tech-stack.md` + `AGENTS.md` "Known stubs"; tick Progress | Manual smoke must be run on a real machine — there's no automation for "log out and back in"; the locked-down-registry path is hard to reproduce on a typical dev machine. |

**Prerequisites:** S-01 shipped (the dialog scaffold). S-03 + S-04 already in place — this slice piggybacks on the dialog's existing tab + atomic-save patterns.
**Estimated effort:** ~1 session for Phase 1 (one-source-file persistence change + dialog work + ~12 new tests), ~30 minutes for Phase 2 smoke + bookkeeping.

## Open Risks & Assumptions

- **PyInstaller `sys.executable` resolves to the frozen exe.** Verified by PyInstaller bootstrap docs and the project's existing release pattern; manual smoke confirms.
- **NSIS per-user install path is stable across in-place upgrades.** Implies the Run-key value remains valid after upgrade. Verified manually as part of Phase 2.
- **Locked-down corporate machines that block per-user Run-key writes will hit the tooltip path** — acceptable; the tooltip says "try running BreakReminder as your normal user" which points the user at the diagnosis.
- **Future cross-platform port** would have to extract the helpers into a platform module; called out in "What We're NOT Doing" so the author's intent isn't ambiguous.

## Success Criteria (Summary)

- User can tick the autostart checkbox, click OK, log out and back in, and find BreakReminder running in the tray.
- User can untick + OK to remove autostart.
- The atomic-save invariant holds across all four persisted fields (interval, snooze, voice, autostart) — no partial saves on any validation or registry failure.
