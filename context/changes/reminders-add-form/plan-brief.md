# Reminders Add Form — Plan Brief

> Full plan: `context/changes/reminders-add-form/plan.md`

## What & Why

S-06 wires the previously-disabled "Add…" button in the Reminders tab to a new modal sub-dialog that collects a name + future date/time, persists a one-shot `Reminder` to disk, arms the running session, and refreshes the list. Closes the FR-011 "User can add a custom reminder" surface and the first half of FR-013 (popup fires at the chosen instant via the existing `app.py` wiring). The roadmap flagged the "ensure the added reminder is armed in the running session" path as S-06's only real risk — this slice closes it explicitly via `ReminderScheduler.reload()`.

## Starting Point

S-05 shipped the read-only Reminders tab in `SettingsDialog` with three disabled buttons (Add / Edit / Delete) wrapped in tooltip-bearing containers; the list loads `ReminderStore.list_all()` exactly once at construction and is pinned by a spy test. The storage layer (`ReminderStore.add()`) and the scheduler arm hook (`ReminderScheduler.reload()`) already exist; what's missing is a UI to invoke them, plus a deterministic-clock test surface for the scheduler.

## Desired End State

Clicking Add opens a small modal sub-dialog (Name + QDateTimeEdit + OK/Cancel). OK validates (non-empty name, fire_at strictly in the future), saves a one-shot `Reminder` via the existing store, calls `ReminderScheduler.reload()` to arm the running session, emits `reminder_added`, and closes. The Reminders tab rebuilds in place so the new row appears immediately; at the chosen instant, the existing dismissable `ReminderDialog` popup fires.

## Key Decisions Made

| Decision                          | Choice                                                                                  | Why (1 sentence)                                                                                            |
| --------------------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Sub-dialog file structure         | New file `break_reminder/ui/reminder_form_dialog.py` (generic, S-07 reuses)              | Name reflects intent; S-07's edit form trivially reuses the class with a pre-populated Reminder arg.        |
| Clock-injection refactor scope    | Fold into S-06 (constructor signature + 3 call-site updates in `ReminderScheduler`)     | Mirrors existing `BreakScheduler` pattern; enables deterministic "add → fire" tests for ~6 lines of code.   |
| List refresh strategy             | Rebuild Reminders tab in place after successful save                                    | Re-uses `_build_reminders_tab` verbatim; S-05's "list_all called exactly once" invariant evolves cleanly.   |
| `reload()` invocation site        | Inside the sub-dialog's `accept()` (inject `ReminderScheduler` into the sub-dialog)     | Mirrors `SettingsDialog` convention (dialog owns its own save path); store + reload stay atomically grouped. |
| Past `fire_at` policy             | Reject with validation tooltip ("Time must be in the future")                            | Matches FR-011 intent (creating a *future* reminder); avoids "I just added something that immediately expired" UX. |
| Date/time widget shape            | Single `QDateTimeEdit` with `setCalendarPopup(True)`                                    | Most ergonomic for date selection; time stays spinbox-quick; one widget = simplest layout.                  |
| Timezone strategy                 | User types local wall-clock; save as tz-aware UTC datetime                              | Matches established test-suite convention (every Reminder uses `tzinfo=UTC`); robust to DST + machine moves. |
| Phase shape                       | Two phases (Phase 1: all code + automated; Phase 2: manual smoke + bookkeeping)         | Mirrors the S-02 / S-03 / S-04 / S-05 cadence; clean pause point between green CI and the human smoke step. |

## Scope

**In scope:**
- New `ReminderFormDialog` class in `break_reminder/ui/reminder_form_dialog.py` (Name + Date/time + OK/Cancel + validation gates + save path).
- Inject `clock: Callable[[], datetime] | None = None` into `ReminderScheduler.__init__`, replacing 3 hardcoded `datetime.now(UTC)` sites.
- Inject `reminder_scheduler` into `SettingsDialog.__init__`; store the Reminders tab on `self`; enable Add button; wire click → sub-dialog → rebuild-on-signal.
- New test files: `tests/test_reminder_scheduler.py`, `tests/test_reminder_form_dialog.py`.
- Extend `tests/test_settings_dialog.py` with `TestRemindersAddButton` + update the S-05 `list_all` spy test.
- Tighten the AGENTS.md "Custom-reminder editor dialog" bullet to reflect Add is shipped.

**Out of scope:**
- Edit / Delete handlers (S-07 owns).
- Recurrence editor / RRULE field (S-08 owns).
- `end_at` field, reminder editing via list double-click, multi-select.
- `ReminderStore.changed` signal, `QFileSystemWatcher`, live refresh on tab switch.
- History view, log integration changes, NSIS / PyInstaller / release-workflow changes.
- New `Settings` keys, localization, posture/eye-tracking inputs.

## Architecture / Approach

The slice threads one new dependency (`ReminderScheduler`) into `SettingsDialog` and adds one new UI module. Data flow on save:

```
[Add button click] → SettingsDialog._on_reminders_add_clicked()
   → ReminderFormDialog(store, scheduler, parent=self).exec()
      → user fills fields → OK
         → validate name (non-empty after strip) → tooltip-and-return on fail
         → validate fire_at (strictly > now) → tooltip-and-return on fail
         → Reminder(name, start_at=local→UTC) → reminder_store.add(reminder)
            → on OSError: tooltip-and-return, dialog stays open
         → reminder_scheduler.reload()  ← THIS is what arms the running session
         → self.reminder_added.emit(reminder)
         → super().accept()  ← ordering load-bearing: emit BEFORE accept
      → exec() returns Accepted
   → connected slot: SettingsDialog._refresh_reminders_tab()
      → removeTab(idx) + insertTab(idx, _build_reminders_tab(), label)
```

The "reload before emit before super().accept()" ordering is the single load-bearing detail (pinned by `test_save_emits_reminder_added_before_super_accept`). Everything else is conventional Qt signal-slot wiring layered on top of the existing S-05 / S-04 patterns.

## Phases at a Glance

| Phase                            | What it delivers                                                                                                  | Key risk                                                                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1. Implementation                | Scheduler clock-injection; `ReminderFormDialog` class; SettingsDialog wiring; 2 new test files + 1 extended.       | Wrong `accept()` ordering (`super().accept()` before `emit`) would silently drop the refresh slot — pinned by a unit test. |
| 2. Manual smoke + bookkeeping    | Real-Windows verification of add→fire flow; change.md / roadmap.md / AGENTS.md updates; Progress section ticked.   | Manual smoke skips OSError path (covered by unit test only); pause integration with scheduler not exercised (out of scope). |

**Prerequisites:** S-05 (Reminders tab) shipped + archived; the v0.1.0 `ReminderStore` / `ReminderScheduler` / `ReminderDialog` triad in place.
**Estimated effort:** ~1-2 sessions across 2 phases. Most of the surface is well-paved by S-04 / S-05; the genuinely new pieces are `ReminderFormDialog` + `tests/test_reminder_scheduler.py`.

## Open Risks & Assumptions

- **System-local timezone capture.** The dialog uses `datetime.now().astimezone().tzinfo` to capture the user's local zone for the local→UTC conversion. On a system with no local zone configured (rare on Windows), this may fall back to UTC and silently make the user's "10 AM tomorrow" mean "10 AM UTC tomorrow". Acceptable for v1; surface as a known limitation if anyone hits it.
- **Sub-dialog parent ownership.** Parenting `ReminderFormDialog` to `SettingsDialog` is standard but means closing Settings closes the sub-dialog. Tested implicitly via the `_refresh_reminders_tab` flow; no separate test.
- **Pause does NOT gate custom reminders.** `ReminderScheduler` has no pause concept today (out of scope for FR-016 per the PRD); a reminder saved with `fire_at = now + 30s` fires regardless of whether the user paused breaks. Consistent with FR-013's "lightweight, dismissable" intent.
- **The S-05 `list_all`-spy test changes shape.** Strictly speaking this is a test contract change, not a regression — but anyone reading the test diff in isolation might mistake the new "per-build" assertion for a weakened invariant. The plan amendment explains why.

## Success Criteria (Summary)

- User can open Settings → Reminders → Add, enter a name + future date/time, click OK, and see the popup fire at the chosen instant.
- All automated gates pass (pytest / pyright / ruff / pip-audit / pip-licenses) with no regressions in the S-04 / S-05 test surface.
- The roadmap S-06 row flips to `done`; AGENTS.md narrows the pending custom-reminder bullet to Edit/Delete only.
