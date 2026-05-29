---
change_id: bugfix-single-instance-guard
title: Prevent multiple BreakReminder instances from running concurrently (S-10)
created: 2026-05-29
updated: 2026-05-29
status: implemented
archived_at: null
---

## Notes

Roadmap S-10 — bugfix slice. Discovered 2026-05-29 from real-world use: launching `BreakReminder.exe` (or `python -m break_reminder`) N times produces N independent tray icons, each with its own `QApplication`, `ActivityMonitor`, `BreakScheduler`, `ReminderScheduler`, and pynput listener pair. Beyond the cosmetic three-icons-in-tray symptom, this is a correctness bug: concurrent writers race on `events.log` (FR-015 append) and `reminders.json` (atomic-rename), and N schedulers fire N break dialogs at slightly offset intervals. The most common real-world trigger is autostart-on-login + a manual launch via desktop shortcut after Windows already started the app (FR-003 makes this path the default).

Fix shape: acquire a `QLockFile` on `%APPDATA%\BreakReminder\app.lock` at the top of `break_reminder.app:main()`, after `QApplication.setApplicationName(APPLICATION_NAME)` (so `QStandardPaths` resolves correctly) but before constructing `BreakReminderApp`. If `tryLock(0)` fails, show a single `QMessageBox.information("BreakReminder is already running.")` and `return 0` (clean exit, not an error code). `QLockFile` already handles stale-lock cleanup via PID liveness check, so a previously crashed instance does not require manual lockfile deletion.

UX decision (locked 2026-05-29 with the user): brief message box, then exit. Silent exit was rejected as confusing (user double-clicks .exe and "nothing happens"); activate-existing-instance via `QLocalSocket` was rejected as scope-creep under `low-complexity`.

PRD refs: FR-003 (autostart, the trigger path), FR-015 (event log integrity, the corruption surface), guardrail "Settings persist across reboots and updates" (the data-corruption guardrail this prevents from violating).
