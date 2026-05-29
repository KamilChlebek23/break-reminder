# Single-instance guard (S-10) — Plan Brief

> Full plan: `context/changes/bugfix-single-instance-guard/plan.md`

## What & Why

Launching BreakReminder while another copy is already running silently spawns N independent instances — N tray icons, N pynput listener pairs, N schedulers racing each other to fire break dialogs, and N concurrent writers to `events.log` and `reminders.json`. Beyond the cosmetic three-icons symptom, this is a correctness bug: storage writes can interleave or clobber each other. The fix is a single `QLockFile` acquired at the top of `break_reminder.app:main()`; the second instance shows a brief message box and exits cleanly.

## Starting Point

`break_reminder/app.py:main()` (lines 477-499) constructs `QApplication`, sets the application name, runs the tray-availability check, and unconditionally builds `BreakReminderApp` + `app.start()`. There is no single-instance check anywhere in the codebase (grep'd for `QLockFile` / `QSharedMemory` / `QLocalSocket` / `mutex` — zero hits). The most common real-world trigger is FR-003 autostart-on-Windows-login + a manual desktop-shortcut launch by a user who can't see the small tray icon and assumes the app isn't running.

## Desired End State

Launching a second copy of BreakReminder shows `QMessageBox.information("BreakReminder is already running. Look for the clock icon in the system tray.")`; the user clicks OK and the second process exits with code 0. The first instance is unaffected. Hard-killed prior instances (Task Manager → End Task) are recovered automatically by `QLockFile`'s built-in PID-liveness check on the next launch — no manual lockfile cleanup ever required.

## Key Decisions Made

| Decision                       | Choice                                                                                       | Why (1 sentence)                                                                                                                                | Source |
| ------------------------------ | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| UX on contention               | Brief `QMessageBox.information` then exit                                                    | Silent exit was rejected as confusing; activate-existing-instance via `QLocalSocket` was rejected as scope-creep under `low-complexity`.        | Plan   |
| Message text                   | "BreakReminder is already running. Look for the clock icon in the system tray."              | Points the user to the tray icon so they understand why the launch was a no-op.                                                                 | Plan   |
| Icon variant                   | `QMessageBox.information` (i icon)                                                           | Matches the existing About dialog in `_on_check_for_updates`; the launch was rejected by design, not by user error.                             | Plan   |
| Failure-mode handling          | Single message regardless of `lock.error()` cause                                            | A `%APPDATA%` access failure breaks the rest of the app anyway; differentiating adds code surface for a path the user is unlikely to hit.       | Plan   |
| Dev escape hatch               | None (no `--allow-multiple` flag, no env var)                                                | Keep the surface small; a developer can rename `%APPDATA%\BreakReminder\app.lock` if they need a second copy.                                   | Plan   |
| Lock primitive                 | `QLockFile` (Qt cross-platform)                                                              | Already in deps via PySide6; cross-cuts dev runs and PyInstaller bundles identically; built-in PID-liveness check handles crashed prior runs.   | Plan   |
| Lock location                  | `%APPDATA%\BreakReminder\app.lock` via new `app_lock_path()` in `storage/paths.py`           | Mirrors the four existing path helpers; keeps the maintenance surface in one module.                                                            | Plan   |
| Stale-lock-time configuration  | Default 30000ms (untouched)                                                                  | The PID-liveness check is the primary recovery mechanism; tweaking the timer has no observable effect for this app.                             | Plan   |
| `--self-test` interaction      | Naturally bypasses the lock                                                                  | The `main.py:_run` short-circuit returns before `app.main()` is called; CI must run the smoke test against the same `.exe` the installer ships. | Plan   |

## Scope

**In scope:**
- New `app_lock_path()` helper in `break_reminder/storage/paths.py`
- New `_acquire_single_instance_lock(path)` helper in `break_reminder/app.py`
- `main()` wiring: lock acquisition between `setQuitOnLastWindowClosed(False)` and the tray-availability check; message box + exit 0 on contention
- New `TestSingleInstanceLock` class in `tests/test_app.py` (4 tests)
- `change.md` status flip + roadmap S-10 row

**Out of scope:**
- `QLocalSocket`-based "activate-existing-instance" wiring
- Windows-specific named-mutex via `pywin32`
- CLI flag or environment variable to bypass the lock
- Event-log entry for "rejected second instance"
- Retroactive fix for v0.1.x..v0.6.x users (forward-only)
- PyInstaller / NSIS / `release.yml` changes

## Architecture / Approach

A single function-call site change: `main()` gets a 6-line block that acquires a `QLockFile`, shows a message box and exits 0 on contention, and binds the lock to a local for the lifetime of `qt_app.exec()`. The `_acquire_single_instance_lock(path)` helper is parameterized on `path` so unit tests inject `tmp_path` and exercise both branches without subprocess machinery (Qt's OS-level file lock makes same-process contention observable). `main.py` stays Qt-free per its existing doctrine — the bootstrap-panic and single-instance concerns are fully orthogonal.

## Phases at a Glance

| Phase             | What it delivers                                                                  | Key risk                                                                                                                       |
| ----------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 1. Implementation | Lock helper + `main()` wiring + 4-test class; green CI gate                       | Forgetting to bind the `QLockFile` return value to a local — would let it GC immediately and the next launch wouldn't detect us as running. |
| 2. Bookkeeping    | `change.md` `status: implemented` + roadmap S-10 row                              | None — pure docs.                                                                                                              |

**Prerequisites:** none — S-01..S-09 all shipped; this is independent of the settings/reminders flows.
**Estimated effort:** ~1 evening (mirrors S-09's footprint exactly).

## Open Risks & Assumptions

- **Assumption: Qt's PID-liveness check is reliable on Windows 11.** Documented behavior of `QLockFile` since Qt 5.1; well-tested upstream. Risk: PID reuse between a crashed BreakReminder instance and an unrelated process within the 30s stale-time window; in practice, Windows PID reuse is slow enough that this is essentially impossible for a personal-use tray app.
- **Assumption: `LockFileEx`-based file locking interacts cleanly with NSIS uninstall.** The uninstaller doesn't touch `%APPDATA%`, so the lockfile survives uninstall — harmless to v0.6.x and earlier (which don't read it) and reclaimed automatically by the next v0.7.x launch.

## Success Criteria (Summary)

- Launching a second copy of BreakReminder while a first is running shows the message box and exits 0; the first instance is undisturbed.
- Hard-killing the first instance via Task Manager and relaunching produces a normal startup with no message box and no manual cleanup.
- `events.log` and `reminders.json` no longer have a multi-writer corruption surface in real-world autostart + manual-launch scenarios.
