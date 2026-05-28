# Reminders Recurrence Editor — Plan Brief

> Full plan: `context/changes/reminders-recurrence-editor/plan.md`

## What & Why

S-08 (FR-014). Extend the existing `ReminderFormDialog` (S-06 / S-06b / S-07) with a recurrence picker — None / Daily / Weekly / Monthly — and an optional "End on:" date. Translate the picker to RFC 5545 RRULE strings on save and pre-fill from `rrule_str` on Edit. Without this, the custom-reminders feature is half-baked: the most natural reminders for a programmer (daily standup, weekly retro, monthly bills — all PRD examples) all need recurrence, and today the user has to hand-edit `reminders.json` to set them.

## Starting Point

Storage and scheduler already support recurrence end-to-end. `Reminder.rrule_str: str | None` and `Reminder.end_at: datetime | None` round-trip verbatim through `storage/reminders.py`; the scheduler's `next_firing_after` parses `rrulestr(reminder.rrule_str, dtstart=reminder.start_at)` and is covered by 5 unit tests in `tests/test_scheduler.py`. What's missing is the UI surface — the form dialog has Name + Date/time + Notify-N-min today; this slice adds two more rows.

## Desired End State

The Reminders Add / Edit form has two new rows: a `Recurrence:` QComboBox (None / Daily / Weekly / Monthly) and an `End on:` checkbox + QDateEdit pair. A "Daily standup" reminder created today shows up in the Reminders list as `Daily standup  —  Wed 2026-05-28 09:00 (daily)` and re-fires every day until either deleted or the optional end-date is hit. Edit-mode pre-fills the picker from the loaded `rrule_str`; hand-edited advanced RRULE strings (e.g. `FREQ=WEEKLY;BYDAY=MO,WE,FR`) show as a disabled `(custom)` selector with a Reset button that lets the user override after a confirmation.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| Frequency option set | None / Daily / Weekly / Monthly only (single QComboBox) | PRD-aligned with FR-014's exact wording; smallest closing surface; advanced RRULEs (BYDAY, INTERVAL) deferred to a later S-99 | Plan |
| End condition UX | Optional "End on:" QCheckBox + QDateEdit (date-only) | Matches PRD's "end date optional"; `Reminder.end_at: datetime` already supports it; no `COUNT=` complexity | Plan |
| Past-time gate semantics for recurring | Use `next_firing_after` to require ≥ 1 future occurrence | Lets user create "every Monday" on a Tuesday without rescheduling; reuses the engine that already authorities the answer | Plan |
| Reminders list row indicator | Append `(daily)` / `(weekly)` / `(monthly)` / `(custom)` suffix | Visual differentiation between recurring and one-shot rows; ~10 chars; dialog already 520 px wide | Plan |
| Edit-mode unparseable RRULE | Show `(custom)` disabled + Reset button with confirm | Honors FR-015 hand-edit contract; doesn't silently destroy user intent on save | Plan |
| Weekly / Monthly anchoring | Plain `FREQ=WEEKLY` / `FREQ=MONTHLY` anchored on `dtstart` (no BYDAY / BYMONTHDAY) | dateutil resolves identically; matches "every Monday = start it on Monday" mental model; Feb-31 skip handled via passive tooltip | Plan |
| End-date interpretation | 23:59:59 in system-local on the picked date → UTC | Matches "end on July 31" mental model; symmetric with form's existing local→UTC conversion for datetime | Plan |

## Scope

**In scope:**

- Recurrence QComboBox (None / Daily / Weekly / Monthly) on `ReminderFormDialog`
- Optional "End on:" QCheckBox + QDateEdit pair, gated by recurrence picker state
- Forward translation: picker + end-date → `rrule_str` + `end_at` on save
- Reverse translation: `rrule_str` + `end_at` → picker + end-date on Edit pre-fill
- `(custom)` locked-state with Reset button + confirmation for unparseable RRULEs
- Recurrence-aware past-time gate (one-shot unchanged, recurring uses `next_firing_after`)
- `_compose_row` recurrence suffix (`(daily)` / `(weekly)` / `(monthly)` / `(custom)`)
- Monthly-day-31 passive tooltip ("Months without that day are skipped")
- Test coverage across 6 new test classes in `test_reminder_form_dialog.py` + 1 in `test_settings_dialog.py`
- `AGENTS.md` FR-014 bullet removal

**Out of scope:**

- BYDAY weekday checkboxes ("every Mon/Wed/Fri") — deferred to S-99
- INTERVAL picker ("every 2 weeks") — deferred
- COUNT-based ending ("daily for 14 occurrences") — deferred
- Recurrence preview ("Next 5 firings: ...") — deferred
- Timezone selector for end-date — system-local interpretation only
- Localization, double-click-to-Edit, new `Settings` keys, NSIS / PyInstaller / release-workflow changes

## Architecture / Approach

Single module change inside `break_reminder/ui/reminder_form_dialog.py` (add 2 new rows + 4 widgets + 3 helpers + 2 slots), one display-side change in `break_reminder/ui/settings_dialog.py` (`_compose_row` suffix + 1 helper), test extensions in `tests/test_reminder_form_dialog.py` and `tests/test_settings_dialog.py`, and one `AGENTS.md` line deletion. Storage and scheduler are zero-touch — they have shipped end-to-end and are covered. The `accept()` order remains load-bearing: validate name → validate datetime → compute (rrule_str, end_at) → recurrence-aware past-time gate → construct Reminder → store.add/update → scheduler.reload → emit signal → super().accept().

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Implementation | Form recurrence + end-date rows; bidirectional RRULE translation; custom-locked state; recurrence-aware past-time gate; list row suffix; tests | Edge cases in the past-time gate generalization (3-field unchanged-skip detector) and the custom-locked override flow |
| 2. Manual smoke + bookkeeping | Real-Windows verification of all four picker choices + custom-locked + end-date round-trip; status flips in `change.md` / `roadmap.md` / `AGENTS.md` | None — pure documentation step after the manual checks pass |

**Prerequisites:** S-06 (form scaffold), S-06b (lead-time), S-07 (Edit mode + dual-mode form) — all shipped 2026-05-27. Storage `Reminder.rrule_str` + `Reminder.end_at` + scheduler `next_firing_after` — all shipped in v0.1.0.

**Estimated effort:** 1 implementation session (~3-4 hours) + 1 review + smoke session.

## Open Risks & Assumptions

- **Assumption:** `dateutil`'s plain `FREQ=MONTHLY` skip-impossible-months behavior matches user expectations for the "monthly bills on the 31st" PRD example. The passive tooltip surfaces the behavior; if users find it surprising, S-99 can add `BYMONTHDAY=N` precision.
- **Assumption:** Exact-string RRULE matching is sufficient for reverse-translation. The four picker outputs are byte-for-byte stable; semantically-equivalent variants (`"FREQ=DAILY;INTERVAL=1"`) fall through to `(custom)` — acceptable since only hand-editors produce such variants.
- **Risk:** The custom-locked Reset flow is a small new UX surface (button + QMessageBox confirm). Test coverage pins both branches but real-Windows smoke must verify the dialog ergonomics.
- **Risk:** End-date local→UTC conversion across DST transitions may produce surprising stored values (e.g. picking July 31 in winter might store an August 1 UTC instant). The conversion uses `astimezone(UTC)` which is DST-correct per-instant; tests on a frozen system zone pin the round-trip.

## Success Criteria (Summary)

- User can create a Daily / Weekly / Monthly reminder via the picker; the row displays the recurrence suffix; the popup fires at each occurrence.
- User can set an optional end-date; the series stops firing after the end-date.
- Edit pre-fills the picker correctly for picker-generated RRULEs and shows `(custom)` for hand-edited advanced RRULEs without destroying them on save.
- All four roadmap S-08 acceptance criteria (PRD FR-014: pick frequency, sensible defaults, optional end-date, `next_firing_after` advances across firings) pass via the existing scheduler engine, with no scheduler-side changes.
