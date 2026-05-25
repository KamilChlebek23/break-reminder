# Settings Window — Break Interval Editor — Plan Brief

> Full plan: `context/changes/settings-break-interval/plan.md`
> Roadmap entry: `context/foundation/roadmap.md` § S-01

## What & Why

Replace the `QMessageBox` placeholder at `BreakReminderApp._on_open_settings()` with a real `SettingsDialog(QDialog)` that lets the user edit the break interval inside a real settings window. Closes FR-005 + FR-006 — the two must-have requirements that were `wired but stub` in v0.1.0 — and stands up the load-bearing UI scaffold that S-02..S-08 hang off.

## Starting Point

v0.1.0 ships with `Settings.break_interval_min` getter/setter fully working under `QSettings` IniFormat at `%APPDATA%\BreakReminder\BreakReminder.ini`, and `BreakScheduler._tick` reads `Settings.snapshot()` every tick — so live interval edits already propagate without re-arm machinery. What's missing is a UI surface: today the "Open settings…" tray action shows a `QMessageBox` telling the user to hand-edit the INI.

## Desired End State

A user right-clicks the tray icon, clicks "Open settings…", and a real modal `QDialog` opens with a "Scheduling" tab containing a spinbox bounded to 1–240 minutes pre-filled with the current value. They edit, click OK, and within ≤1 second the tray tooltip's countdown reflects the new interval. They edit, click Cancel, and nothing changes. They restart the app, and the saved value persists.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Layout for settings dialog | Tabbed (`QTabWidget`, one "Scheduling" tab today) | Pre-empts the same layout question for S-02..S-05 — each future field lands in either the existing tab or a new one without re-organizing layout. | Plan |
| Module location for the dialog | New `break_reminder/ui/` package; `break_reminder/ui/settings_dialog.py` | Settings is not a notification — `notifications/` would become a misnomer the moment S-05 adds the reminders editor; new `ui/` is the obvious home for S-05..S-08 dialogs. | Plan |
| Validation strategy | `QSpinBox.setMinimum(1)` / `setMaximum(240)` — widget-level | Out-of-range values are physically impossible, so the `Settings` setter's `ValueError` path is unreachable from the dialog — no try/except needed. | Plan (dissolved during research) |
| Mid-cycle interval change | No re-arm signal | `BreakScheduler._tick` already reads `Settings.snapshot()` every tick — the new value propagates on the next tick automatically. | Plan (dissolved during research) |
| Modality | Modal (`QDialog.exec()`) with `parent=None` | Standard settings-dialog UX; `parent=None` matches `BreakDialog` / `ReminderDialog` so the dialog gets its own taskbar entry. | Plan |
| Dialog lifetime | Fresh on every "Open settings…" click | No stale state across opens; mirrors the `ReminderDialog` instantiation pattern in `app.py:315`. | Plan |

## Scope

**In scope:**

- New `break_reminder/ui/__init__.py` and `break_reminder/ui/settings_dialog.py` containing `SettingsDialog`.
- Replace the body of `BreakReminderApp._on_open_settings()` to construct and `exec()` the new dialog; remove the now-unused `_settings_path()` helper.
- Add `import` for `SettingsDialog` to `app.py` (keep `QMessageBox` for the no-tray-detected path).
- New `tests/test_settings_dialog.py` covering load / save / cancel.
- New test class in `tests/test_app.py` covering the slot wiring.
- AGENTS.md folder-layout block gets a `ui/` entry; one-sentence prose paragraph distinguishing `notifications/` from `ui/`.

**Out of scope:**

- All other settings fields (autostart S-02, snooze S-03, voice S-04, reminders CRUD S-05..S-08).
- Live preview, telemetry, autostart registry write, second tab.
- Concurrent break_due-during-settings.exec() UX special-casing.

## Architecture / Approach

```
[tray menu "Open settings…"] → BreakReminderApp._on_open_settings()
        → SettingsDialog(settings=self._settings).exec()
              ↓ (on OK)
              self._settings.break_interval_min = spinbox.value()
              ↓
              QSettings → %APPDATA%\BreakReminder\BreakReminder.ini
              ↓ (next tick, ≤1s later)
              BreakScheduler._tick reads Settings.snapshot() → countdown updates
```

Single-file dialog, single edit to the wiring slot, no scheduler / activity / event-log changes.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Build `SettingsDialog` in isolation | New `ui/` package, the dialog class, unit tests for load/save/cancel — no app.py edits | Picking the wrong tab/layout idiom and having to redo it on S-02; mitigated by the `QTabWidget`-from-day-one decision. |
| 2. Wire the dialog into the tray menu | Replace placeholder body in `app.py`, update `tests/test_app.py`, run manual smoke | Stale `_settings_path` reference or `QMessageBox` import leaving lint-fail crumbs; manual smoke catches behavior regressions. |

**Prerequisites:** None. v0.1.0 release infrastructure (PyInstaller + NSIS + GitHub Actions) is intact. `Settings.break_interval_min` is shipping. `qapp` fixture in `tests/conftest.py` is available for dialog tests.
**Estimated effort:** ~1 evening across both phases. Phase 1 is ~80-150 lines of new code + 6-8 tests; Phase 2 is a 3-line slot body change + 3 new tests + manual smoke.

## Open Risks & Assumptions

- Assumption: the `qapp` fixture in `tests/conftest.py` is sufficient for `QDialog` construction without showing. (Verified by `tests/test_break_dialog.py` already using this pattern.)
- Risk: a future agent decides to keep a long-lived `self._settings_dialog` member to remember "last position" — would conflict with the "fresh on every open" design decision documented in the plan. Mitigation: the test in Phase 2 (`test_settings_dialog_receives_app_settings_instance`) acts as a tripwire if the lifetime ever changes.
- Risk: if `break_due` fires while settings is `.exec()`'d, the user sees both dialogs. Documented under "What we're NOT doing"; left to organic v0.2.x discovery if it surfaces as a real-world annoyance.

## Success Criteria (Summary)

- The "Open settings…" tray action opens a real `QDialog` (not a `QMessageBox`); editing the break interval and clicking OK persists immediately to the INI and is honored by the running scheduler within ≤1 second.
- Cancel discards changes; restart preserves saved values; spinbox bounds physically prevent FR-006 violations.
- All automated checks pass (pytest, pyright, ruff including the `D` docstring rules); manual smoke checklist in Phase 2 passes end-to-end.
