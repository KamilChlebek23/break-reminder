# Reminders List View — Plan Brief

> Full plan: `context/changes/reminders-list-view/plan.md`

## What & Why

Roadmap slice **S-05** — first slice of Stream B (custom reminders). The persistence side has been ready since v0.1.0 (`storage/reminders.py` + `scheduler.ReminderScheduler` already read and fire `reminders.json`), but the user has no in-app surface to even see what's stored. This slice adds a read-only "Reminders" tab to `SettingsDialog` so the user can confirm their reminders exist, and previews where Add / Edit / Delete will land in S-06..S-08.

## Starting Point

`SettingsDialog` is a `QTabWidget` with three tabs today (Scheduling, Notifications, Lifecycle — see `break_reminder/ui/settings_dialog.py:259-271`). `ReminderStore.list_all()` is the canonical read API and already returns a `list[Reminder]` with `name`, `start_at`, `rrule_str`, `end_at`, `id` (`break_reminder/storage/reminders.py:77-80`). `scheduler.next_firing_after(reminder, now)` is a pure RRULE-aware helper that returns the next firing as a tz-aware UTC `datetime` or `None` when the series is exhausted (`break_reminder/scheduler.py:297-322`). The app already constructs a `ReminderStore` in `app.py:97` but does NOT thread it into `SettingsDialog` — that's the wiring delta this slice opens with. Currently no UI references `reminders.json`; AGENTS.md "What this scaffold does not yet implement" still flags both items.

## Desired End State

Four tabs in the Settings dialog (Scheduling, Notifications, Lifecycle, **Reminders**). The Reminders tab shows one of two states:

- **Non-empty:** a `QListWidget` whose rows read `"<name>  —  <next firing>"` (e.g. `"Visit to dentist  —  Wed 2026-06-03 14:00"`) or `"<name>  —  (expired)"` for series whose `next_firing_after(now)` returns `None`. Rows are sorted chronologically (soonest first; expired rows last; tiebreak by name). Below the list, three buttons — `Add…`, `Edit…`, `Delete` — all disabled with tooltip `"Coming in a future update"`. Edit/Delete additionally gate on `currentRow() >= 0` so S-07 can drop in click handlers without touching the enable wiring.
- **Empty (`reminders.json` absent or `[]`):** the list is replaced by a centered `QLabel` reading `"No reminders yet — click Add to create one."`; the three buttons are still rendered and still disabled.

The dialog re-loads `reminders.json` exactly once per `Open settings…` click (the existing per-open construction lifetime). `AGENTS.md` "What this scaffold does NOT yet implement" loses the first custom-reminder bullet; the roadmap S-05 row flips to `done` and Open Roadmap Question #6 is marked resolved.

## Key Decisions Made

| Decision                              | Choice                                                                | Why (1 sentence)                                                                                                                                                                |
| ------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Row content                           | Name + next firing (uses `scheduler.next_firing_after`)               | Resolves Open Roadmap Question #6 in favour of the field the user actually cares about; reuses an already-tested pure function.                                                 |
| Widget                                | `QListWidget` with composed item text                                 | Smallest API surface that satisfies the read-only scope; matches the slice's "read-only this slice" wording verbatim; trivially asserted via `items()` + `text()`.              |
| Reload strategy                       | Load once at `__init__`; no live refresh while dialog is open         | Matches the dialog's existing per-open lifetime (`app.py:327` constructs fresh on every open); no signal wiring; no race with future Add dialog.                                |
| Empty-state UX                        | Swap `QListWidget` for centered placeholder `QLabel`                  | Tells first-run users what to do; preserves a single-source-of-truth "row count == reminder count" invariant for tests (no fake placeholder rows).                              |
| Disabled buttons                      | All three present + tooltip + Edit/Delete select-to-enable wiring     | Honors the roadmap's "Add / Edit / Delete are present but disabled" wording; previews the S-06/S-07 affordance; the select-to-enable wiring is exactly what S-07 needs anyway.  |
| Expired reminders                     | Show with `"(expired)"` instead of the date                           | List count matches file count (no UI lying about storage); user sees orphan one-shots so they can wait for S-07 delete; consistent read-only-list invariant.                    |
| Sort order                            | Chronological by next firing ascending; expired last; tiebreak name   | "What's next?" is the most useful at-a-glance ordering; expired rows naturally group at the bottom; tiebreak gives deterministic test output.                                   |
| Time rendering                        | `datetime.astimezone()` (system local) → `"%a %Y-%m-%d %H:%M"`        | The persona is a single-machine Windows user; UTC is alien noise; the format is wider than the European default but matches Python stdlib conventions and is unambiguous.       |
| Tab insertion position                | Appended after Lifecycle (4th tab)                                    | Reminders is the only tab not about breaks; placing it last separates the two product modes cleanly and matches the roadmap's Stream A → Stream B sequencing.                   |
| `ReminderStore` injection             | Threaded through `app.py:_on_open_settings` → `SettingsDialog.__init__` | Mirrors how `Settings` and `VoiceNotifier` are already injected; keeps the dialog testable with a tmp-pathed store; no global / no singleton.                                   |
| Presenter helpers                     | Module-level pure functions (`_compose_row`, `_sort_key`, `_format_firing`) | Matches the S-02 `_write_autostart_runkey` / `_delete_autostart_runkey` precedent — small named surface, monkeypatchable in tests, no need for a new presenter class.       |

## Scope

**In scope:**

- New "Reminders" tab in `SettingsDialog` (4th tab, after Lifecycle).
- `ReminderStore` parameter on `SettingsDialog.__init__` (required keyword-only, same shape as `voice`).
- `app.py:_on_open_settings()` updated to pass `self._reminder_store`.
- Three module-level helpers in `settings_dialog.py`: `_format_firing(dt: datetime | None) -> str`, `_sort_key(reminder, now)`, `_compose_row(reminder, now)`.
- Empty-state placeholder label; swap layout when `list_all() == []`.
- Disabled `Add…` / `Edit…` / `Delete` button row with the "coming soon" tooltip; Edit/Delete additionally subscribe to `currentRowChanged` so the enabled state follows the selection (even though click handlers are still no-op).
- Unit tests covering: tab construction + label, list rendering with mixed RRULE/one-shot/expired, sort order, empty-state placeholder, button disabled-by-default + select-to-enable wiring, `ReminderStore` injection (the dialog reads `list_all` once, not on tab switch).
- Documentation updates: drop the first custom-reminder bullet from `AGENTS.md` "What this scaffold does NOT yet implement"; flip `roadmap.md` S-05 row to `done` and dissolve Open Roadmap Question #6.

**Out of scope:**

- No Add / Edit / Delete click handlers (S-06 and S-07).
- No recurrence-editor UI (S-08).
- No live refresh of the list while the dialog is open (no `ReminderStore.changed` signal).
- No multi-select, no drag/drop, no inline editing, no column sort headers.
- No keyboard shortcut wiring beyond Qt's default focus traversal.
- No changes to `storage/reminders.py`, `scheduler.py`, or any other module — read-only consumers only.
- No changes to NSIS, PyInstaller, or release workflow.

## Architecture / Approach

```
app.py
  BreakReminderApp._on_open_settings()
    └─ SettingsDialog(settings=..., voice=..., reminder_store=self._reminder_store).exec()

ui/settings_dialog.py
  SettingsDialog.__init__
    ├─ build Scheduling tab        (unchanged)
    ├─ build Notifications tab     (unchanged)
    ├─ build Lifecycle tab         (unchanged)
    └─ build Reminders tab         (NEW)
         ├─ now = datetime.now(UTC)
         ├─ reminders = reminder_store.list_all()
         ├─ if not reminders:
         │      → centered QLabel("No reminders yet — click Add to create one.")
         │      + disabled button row
         └─ else:
                rows = sorted(reminders, key=lambda r: _sort_key(r, now))
                → QListWidget with one item per row, text = _compose_row(r, now)
                + disabled button row (Edit/Delete additionally select-gated)

Module-level helpers:
  _format_firing(fire_at: datetime | None) -> str
      → "(expired)" if None
      → fire_at.astimezone().strftime("%a %Y-%m-%d %H:%M") otherwise

  _sort_key(reminder, now) -> tuple
      next_at = next_firing_after(reminder, now)
      → (1, reminder.name.lower())              if next_at is None     # expired sink
      → (0, next_at, reminder.name.lower())     otherwise              # chronological + tiebreak

  _compose_row(reminder, now) -> str
      → f"{reminder.name}  —  {_format_firing(next_firing_after(reminder, now))}"
```

The Reminders tab does not subscribe to any signal. It does not call `ReminderStore.list_all()` more than once. It does not import anything from `scheduler.py` except `next_firing_after` — the `ReminderScheduler` class stays out of `ui/`. `app.py` already owns the `ReminderStore` instance (`app.py:97`); this slice just threads it one level deeper into the dialog.

## Phases at a Glance

| Phase                                | What it delivers                                                                                                                  | Key risk                                                                                                                                                                              |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Implementation                    | `SettingsDialog` Reminders tab + presenter helpers + injection wiring + ~12 unit tests; all automated gates green                 | The `_sort_key` / `_format_firing` helpers cross from naive-UTC to local time — tests must pin both branches or a future timezone bug ships silently.                                 |
| 2. Manual smoke + bookkeeping        | Real Windows smoke with seeded `reminders.json`; flip `change.md` + roadmap to `done`; drop the AGENTS.md TODO; resolve OQ #6     | Manual smoke requires hand-editing `reminders.json` (no in-app Add yet); the writer has to format the JSON correctly or the dialog falls back to the empty-state path silently.       |

**Prerequisites:** S-01 shipped (the dialog scaffold). S-02/S-03/S-04 already in place — this slice piggybacks on the dialog's existing tab + injection patterns.
**Estimated effort:** ~1 session for Phase 1 (one-file dialog change + ~12 new tests + one-line `app.py` plumbing), ~20 minutes for Phase 2 smoke + bookkeeping.

## Open Risks & Assumptions

- **`next_firing_after` is cheap enough to call per row on every dialog open.** The function parses RRULE once and calls `.after(now)` — sub-millisecond per reminder. With the persona's expected ≤ 10 reminders, the dialog open stays well under any perceptible delay.
- **`datetime.astimezone()` (no argument) resolves to the system local zone.** Standard Python stdlib semantic; verified across CPython 3.12 docs.
- **The user does not modify `reminders.json` while the dialog is open.** The "load once at construction" decision assumes this; the persona is a single-user, single-machine workflow. If a future v2 syncs reminders cross-device, this assumption gets revisited.
- **Localized day-name in the format string.** `strftime("%a")` honors the current locale; on a Polish-locale system the output reads `"śr 2026-06-03 14:00"`. Acceptable — matches the rest of the OS chrome the user already sees.

## Success Criteria (Summary)

- User opens Settings → Reminders and sees their custom reminders listed with name and next firing.
- An empty `reminders.json` shows the placeholder text + the disabled Add button.
- A weekly RRULE reminder and a future one-shot reminder both render with a real date; a past one-shot reminder renders with `"(expired)"`.
- Three buttons (Add… / Edit… / Delete) are visible and disabled with tooltip; clicking a row enables Edit/Delete (but the click handlers do nothing — that's S-06/S-07).
- The "What this scaffold does not yet implement" list in AGENTS.md no longer mentions "Custom-reminder editor surfaces inside the settings window".
