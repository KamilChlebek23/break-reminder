# Reminders Lead-Time Option — Plan Brief

> Full plan: `context/changes/reminders-lead-time/plan.md`

## What & Why

Add a "Notify N min before event" `QSpinBox` (0-60, step 1, default 0) to the freshly-shipped `ReminderFormDialog` so users can be notified some time *before* the event itself, not at the event instant. The dentist example from FR-011 is now fully usable: pick the appointment time as the event time, set lead to 15 minutes, and the popup fires 15 minutes ahead so you can grab your keys.

## Starting Point

S-06 (`reminders-add-form`) just shipped (commits `33a665f` + `beba743` + `4668903`). The Add form has two fields (`Name`, `Date/time`) and saves a one-shot `Reminder(name, start_at)` where `start_at` is the firing instant. The Reminders tab renders rows as `"<name>  —  <next firing>"`. Storage round-trips through `Reminder.from_dict` / `to_dict` with built-in tolerance for missing optional keys.

## Desired End State

The Add form gains a third row — a `QSpinBox` labelled "Notify (minutes before event):" with default 0. When the user sets a non-zero value, the datetime field is interpreted as the **event time**; the form computes `start_at = event_at - timedelta(minutes=lead)` at save, stores the lead as metadata on the `Reminder`, and the list row gains a "(fires N min before)" suffix showing the event time (not the firing time). When lead = 0, behavior is identical to S-06. Existing `reminders.json` files load with `lead = 0` — no migration.

## Key Decisions Made

| Decision                       | Choice            | Why (1 sentence)                                                                                                                                          | Source |
| ------------------------------ | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| UX shape                       | Always-visible spinbox (default 0) | Simplest UX with no toggle states; matches the "spinbox-with-suffix" pattern the codebase already uses for break interval / snooze duration.              | Plan   |
| Spinbox bounds                 | 0-60 min, step 1  | Matches the user's stated range and the typical "15 min before" / "30 min before" use cases.                                                              | Plan   |
| Storage model                  | Model A (lead as metadata; `start_at` stays = firing time) | Backward-compatible with existing reminders.json; no scheduler change; recoverable for S-07 Edit via `event_at = start_at + lead`.                        | Plan   |
| Validation rule                | Reject strict (`start_at > now`) with lead-aware tooltip | Keeps the existing predicate (`start_at > now`); only the message wording flips based on lead value.                                                      | Plan   |
| List display when lead > 0     | Show event time + "(fires N min before)" suffix | The user cares about *when the event happens*; the firing time is implementation detail of the lead-time choice.                                          | Plan   |
| Roadmap placement              | New S-06b (insert, don't shift) | Inserting between S-06 and S-07 avoids invalidating every reference to S-07/S-08 in archived plans, change.md files, and commit messages.                | Plan   |
| Phase breakdown                | Two phases (Implementation + Bookkeeping) | Mirrors the S-06 ritual the user just ran; small enough that no intermediate phase adds value.                                                            | Plan   |

## Scope

**In scope:**
- New `Reminder.lead_minutes: int = 0` field with JSON round-trip + backward-compat read.
- New `QSpinBox` in `ReminderFormDialog` (0-60, step 1, default 0, suffix " min").
- `start_at = event_at - lead` computation in `accept()`.
- Lead-aware past-time tooltip wording.
- "(fires N min before)" annotation on list rows when lead > 0; expired rows omit the annotation.
- Test extensions across `tests/test_reminders.py`, `tests/test_reminder_form_dialog.py`, `tests/test_settings_dialog.py`.
- Roadmap.md insertion of S-06b (At a glance table, body block, Backlog Handoff, Streams chain).

**Out of scope:**
- Popup-text changes (FR-013 popup keeps showing just the reminder name).
- S-07 Edit / Delete wiring.
- S-08 recurrence interaction (lead applies per-occurrence — future slice).
- Lead bounds beyond 60 min.
- Second-resolution lead (minutes only).
- Migration from Model A to Model B (re-evaluate after S-07 ships).

## Architecture / Approach

Six change sites, all "extend existing pattern":

1. **Storage** (`break_reminder/storage/reminders.py`) — add field; `.get(..., 0)` for backward compat.
2. **Form dialog** (`break_reminder/ui/reminder_form_dialog.py`) — insert spinbox row; compute `start_at` from event - lead; tighten tooltip.
3. **List display** (`break_reminder/ui/settings_dialog.py`) — branch `_compose_row` on `lead_minutes > 0`.
4. **Tests** — extend three existing files with the new behaviors.
5. **Roadmap** — insert S-06b in three places (no ID shifts).
6. **No app.py / scheduler.py changes** — scheduler invariance is the whole point of Model A.

## Phases at a Glance

| Phase     | What it delivers                                                                                                                                  | Key risk                                                                                                                                                                                       |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Implementation + automated verification + manual smoke | Six edits + extended tests + roadmap insert; full automated gate; manual smoke on Windows. | The display-time switch in `_compose_row` (showing `event_at` instead of `start_at` for non-zero lead) is the only place the user-visible behavior diverges from naive expectations — pin with tests. |
| 2. Bookkeeping | `change.md` flipped to `implemented`; roadmap S-06b flipped to `done`; Progress rows ticked with SHAs. | None — pure doc edits.                                                                                                                                                                         |

**Prerequisites:** S-06 (`reminders-add-form`) shipped — done as of `4668903`.

**Estimated effort:** ~1 session (Phase 1 + Phase 2). The change set is six small, well-scoped edits with strong test coverage.

## Open Risks & Assumptions

- **`tests/test_reminders.py` may not exist yet** — the existing reminder tests live under `tests/test_reminder_*.py` filenames. If the storage-test file doesn't exist, Phase 1 #4 creates it.
- **The S-06b ID convention is new.** No existing roadmap entry uses a letter suffix. If the user prefers re-numbering (S-07 → S-08, S-08 → S-09), that's a one-line plan revision before Phase 1 starts.
- **Model A means the displayed time in the list switches** when lead > 0 (from firing time to event time). If user feedback after this slice prefers "always show firing time, mention event in tooltip", that's a one-test revision plus a `_compose_row` tweak.

## Success Criteria (Summary)

- User can set a 0-60 min lead on any new reminder; default is 0 (no behavior change for users who don't touch the spinbox).
- Lead > 0: popup fires `lead` minutes before the chosen event time; list shows the event time + "(fires N min before)" suffix.
- Existing `reminders.json` files load with `lead_minutes = 0` and behave identically to S-06.
