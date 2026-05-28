# Reminders Recurrence Editor Implementation Plan

## Overview

Extend the existing `ReminderFormDialog` (S-06 / S-06b / S-07) with a recurrence picker — None / Daily / Weekly / Monthly — and an optional "End on:" QCheckBox + QDateEdit pair. Translate the picker to RFC 5545 RRULE strings on save (`FREQ=DAILY` / `FREQ=WEEKLY` / `FREQ=MONTHLY`); reverse-translate on Edit pre-fill, falling back to a disabled "(custom)" selector when the loaded `rrule_str` isn't one of the four picker-generated strings (so a hand-edited `reminders.json` round-trip preserves the rule). Replace the unconditional past-time gate with a recurrence-aware one: one-shot still requires `start_at > now`; recurring requires at least one future occurrence (using the existing `next_firing_after` engine). Surface recurrence in the Reminders list as a short suffix on each row. Storage (`Reminder.rrule_str` / `Reminder.end_at`) and the scheduler RRULE engine are unchanged — both have shipped end-to-end and are covered by `tests/test_reminders.py` and `tests/test_scheduler.py`.

This is the last pending Stream B (custom reminders) surface and dissolves FR-014. It also retires the `AGENTS.md` "Custom-reminder recurrence editor (FR-014)" TODO bullet entirely.

## Current State Analysis

- **Storage already supports recurrence end-to-end.** `Reminder.rrule_str: str | None` and `Reminder.end_at: datetime | None` exist on the dataclass (`break_reminder/storage/reminders.py:114-179`). `_coerce_aware_utc` already normalizes hand-edited tz-naive `end_at` values back to UTC-aware. `tests/test_reminders.py:140-167, :245-252, :465-485` pin verbatim round-trip of arbitrary RRULE strings + end_at. **No storage changes.**
- **Scheduler RRULE engine is shipped.** `next_firing_after(reminder, now)` (`scheduler.py:323-348`) parses with `rrulestr(reminder.rrule_str, dtstart=reminder.start_at)`, advances via `rule.after(now, inc=False)`, honors `end_at`, and degrades a corrupt RRULE to `None`. `tests/test_scheduler.py:40-77` covers daily / weekly-BYDAY / monthly-BYMONTHDAY / end-truncation / invalid-RRULE. `tests/test_settings_dialog.py:1900-1920` proves an active recurring reminder whose `start_at` is in the past still computes a future firing through `_compose_row`. **No scheduler changes.**
- **The form is already extension-friendly.** `ReminderFormDialog.__init__` (`break_reminder/ui/reminder_form_dialog.py:272-376`) builds a `QFormLayout` with three rows today (Name / Date+time / Notify-N-min); the load-bearing `accept()` order has explicit numbered steps (validate → construct → persist → reload → emit → super().accept()); S-07's dual-mode pattern (Add when `reminder=None`, Edit when a `Reminder` is passed) is in place.
- **The past-time gate is `start_at_utc <= self._clock()` with an Edit-mode equality skip.** `accept()` lines 481-500. Today the gate is unconditional on whether the reminder is recurring — a recurring reminder whose `start_at` is in the past would be rejected even when its next occurrence is in the future. This is the only behavioral correction this slice makes to the existing gate.
- **`_compose_row` does not announce recurrence.** `break_reminder/ui/settings_dialog.py:289-332` renders `<name>  —  <next firing>` (or with lead, `<name>  —  <event time>  (fires N min before)`). A daily standup reminder is visually identical to a one-shot at the same firing time. The only callers are `_build_reminders_tab` and `tests/test_settings_dialog.py:1850-2020`.
- **AGENTS.md flags FR-014 as the last Stream B TODO.** `AGENTS.md:184` reads: `Custom-reminder recurrence editor (FR-014). The read-only Reminders tab shipped in S-05; Add / Edit / Delete CRUD shipped in S-06 / S-07; the daily / weekly / monthly RRULE picker is the last pending Stream B surface (S-08).`
- **Validation pattern is the `QToolTip.showText` anchored-to-field idiom.** `_show_tooltip` helper at `reminder_form_dialog.py:401-412`. First-failing-field-wins. Never `QMessageBox` for validation (Delete confirm is a destructive-action confirmation, not validation — different surface).
- **Test file conventions are settled.** `tests/test_reminder_form_dialog.py` uses a `Clock` fixture (lines 66-79, 1509 lines total today), tmp-path `ReminderStore`, a `StubScheduler` counting `reload` calls, and module-level constants imported directly from the production module (lines 44-59). New test classes mirror existing shapes (`TestReminderFormDialogDefaults`, `TestReminderFormDialogValidation`, etc.).

## Desired End State

The Reminders form gains a recurrence row + an end-date row, both Add and Edit modes:

1. **Recurrence row** — `QFormLayout` row labeled `Recurrence:`, value is a `QComboBox` with four items: `None` (default in Add mode), `Daily`, `Weekly`, `Monthly`. When the loaded `rrule_str` doesn't map to any of these four, the picker shows a fifth item `(custom)`, is `setEnabled(False)`, and exposes a `Reset…` `QPushButton` next to it that on click raises a `QMessageBox.question` confirm — Yes enables the picker (defaulting to `None`), No leaves everything as it was.
2. **End-date row** — `QFormLayout` row labeled `End on:`, value is a `QHBoxLayout` containing a `QCheckBox` (unticked by default) and a `QDateEdit` (`setCalendarPopup(True)`, default = today + 30 days). The QDateEdit is `setEnabled(False)` until the checkbox is ticked. The entire row's checkbox is `setEnabled(False)` while the recurrence picker is `None` (an end-date is meaningless for one-shot).
3. **Forward translation (save)**: picker `None` → `rrule_str=None, end_at=None`; picker `Daily` → `rrule_str="FREQ=DAILY"`; picker `Weekly` → `rrule_str="FREQ=WEEKLY"`; picker `Monthly` → `rrule_str="FREQ=MONTHLY"`. When the end-date checkbox is ticked, the picked QDateEdit value (system-local naive date) is composed with `time(23, 59, 59)`, attached to the system local zone, and converted to tz-aware UTC, then stored as `end_at`. When the checkbox is unticked, `end_at=None`.
4. **Reverse translation (Edit pre-fill)**: `rrule_str=None` → picker `None`; exact match `"FREQ=DAILY"` / `"FREQ=WEEKLY"` / `"FREQ=MONTHLY"` → corresponding picker; anything else → picker `(custom)` + disabled + Reset button visible. `end_at` (tz-aware UTC) → checkbox ticked + QDateEdit shows the date in system-local zone (the inverse of the save-side conversion: `end_at.astimezone().date()`).
5. **Past-time gate becomes recurrence-aware** — for one-shot (`rrule_str=None` after translation), gate is unchanged: `start_at_utc <= clock()` with the Edit-mode equality skip. For recurring (`rrule_str` non-None), the gate becomes "tentative reminder must have at least one future occurrence": construct a tentative `Reminder` with the just-computed `start_at` / `rrule_str` / `end_at`, call `next_firing_after(tentative, clock())`, reject when the result is `None`. Same Edit-mode equality skip applies (when `start_at_utc == self._editing.start_at` AND the recurrence + end_at are unchanged from the loaded reminder, skip the gate).
6. **Reminders list row** gains a recurrence suffix. `_compose_row` returns:
   - One-shot active, lead=0: `<name>  —  <next firing>` (unchanged).
   - One-shot active, lead>0: `<name>  —  <event time>  (fires N min before)` (unchanged).
   - Recurring active, lead=0: `<name>  —  <next firing> (<freq>)` where `<freq>` is `daily` / `weekly` / `monthly` / `custom`.
   - Recurring active, lead>0: `<name>  —  <event time>  (fires N min before, <freq>)`.
   - Expired (any kind): `<name>  —  (expired)` (unchanged — no recurrence suffix on expired rows; same logic that suppresses the lead annotation on expired).
7. **AGENTS.md** — the FR-014 bullet at `AGENTS.md:184` is removed entirely (no more pending Stream B surfaces).
8. **`roadmap.md` S-08 row + body** flip from `proposed` to `done`. The Streams-B chain comment becomes `S-05 → S-06 → S-06b / S-07 / S-08 (all done)`.

### Verification:

- `uv run pytest tests/test_reminder_form_dialog.py` passes — extended with `TestRecurrencePicker`, `TestRecurrenceEndDate`, `TestRecurrenceSave`, `TestRecurrenceEditMode`, `TestRecurrenceCustomLocked`, `TestRecurrencePastTimeGate`.
- `uv run pytest tests/test_settings_dialog.py` passes — extended with `TestComposeRowRecurrence` covering the new suffix on `_compose_row`.
- `uv run pytest` passes (full suite — no regressions in S-06 / S-06b / S-07 surfaces).
- `uv run pyright`, `uv run ruff check`, `uv run ruff format --check`, `uv run pip-audit`, `uv run pip-licenses --fail-on="AGPL"` all green.
- Real Windows session: open Settings → Reminders → Add; create "Daily standup" with time = today 09:00 + Recurrence=Daily, save. Row shows `Daily standup  —  <next firing> (daily)`. Edit it → picker pre-fills to `Daily`; tick "End on:" + pick a date 7 days out; OK; row updates to show end_at honored (after that date the row goes `(expired)`). Delete it. Repeat for Weekly + Monthly. Hand-edit `reminders.json` to set `rrule_str: "FREQ=WEEKLY;BYDAY=MO,WE,FR"`; reopen Edit; picker shows `(custom)` + disabled, `Reset…` button visible; click Reset → No → state preserved → save → file unchanged.

### Key Discoveries:

- **Storage and scheduler are zero-touch.** Both surfaces have shipped and are covered. `_coerce_aware_utc` defends `end_at` from hand-edits.
- **The exact-string match for reverse-translation is robust enough.** The four picker outputs are byte-for-byte stable (`"FREQ=DAILY"`, etc.); a semantic-equivalent parser would be over-engineering and adds a failure mode (parsing a corrupt RRULE inside the form when the scheduler already handles that in `next_firing_after` with a logged exception).
- **The past-time gate generalization preserves the Edit-mode skip.** Equality on tz-aware UTC `start_at` is still the right "firing time unchanged" detector for recurring (because the series anchor is `start_at`, and `next_firing_after` uses `dtstart=start_at`); the gate skip applies regardless of recurrence type.
- **Lead minutes interaction with recurrence is automatic.** S-06b's `_fire` (`scheduler.py:296-309`) computes `event_at = self._next.fire_at + timedelta(minutes=reminder.lead_minutes)` per occurrence, not at series creation. A "fires 15 min before each daily standup" reminder works without further changes; the `_compose_row` `(fires N min before, daily)` ordering is the only new surface.
- **Monthly-on-the-31st is the only sharp edge.** `dateutil`'s `FREQ=MONTHLY` with `dtstart` on Jan 31 naturally skips Feb / Apr / Jun / Sep / Nov (no day 31). Surface this with a passive tooltip on the picker when Monthly is selected and the start date's day is > 28; do not silently rewrite the start date (would violate the FR-015 hand-edit invariant).

## What We're NOT Doing

- **No BYDAY checkboxes.** "Every Mon/Wed/Fri" is the natural ask; it's deferred to a later S-99-style enhancement. Today's hand-editable `reminders.json` already supports it; the picker just doesn't surface it.
- **No interval picker.** "Every 2 weeks" / "Every 3 months" requires `INTERVAL=N` and a numeric input. Out of scope.
- **No COUNT-based ending.** "Daily for 14 occurrences" requires `COUNT=N` and a different end-condition radio. Out of scope; the PRD specifies "end date optional", not "occurrence count".
- **No timezone selector for end-date.** The end-date is always interpreted as 23:59:59 in system-local time on the picked date. Cross-zone scenarios (DST, traveling user) are accepted as a small hand-edit / Edit-and-resave surface.
- **No recurrence preview.** "Next 5 firings: Mon 9am, Tue 9am, ..." would help validate the user's choice but is a meaningful UI investment; the row's `<next firing>` already gives them a single-occurrence preview.
- **No double-click in the list to open Edit.** Same exclusion as S-07.
- **No new `Settings` keys.** The end-date default offset (30 days) and the picker's default (`None`) are hardcoded constants.
- **No NSIS / PyInstaller / release-workflow changes.** Pure code change inside the existing module set.
- **No changes to `notifications/reminder_dialog.py`.** Recurring popups fire through the same dismissable popup as one-shots — FR-013 contract is unchanged.
- **No changes to `event_log.py`.** Per-occurrence firings already log through the existing path; recurrence doesn't add new event types.
- **No localization.** All new strings are English literals — same convention as every other surface.

## Implementation Approach

Single-phase code change inside `break_reminder/ui/reminder_form_dialog.py` and `break_reminder/ui/settings_dialog.py`, plus extensions to two existing test files. Implementer's natural order:

1. **Add module-level constants + helpers to `reminder_form_dialog.py`** — picker labels, RRULE strings, end-date defaults, validation messages, and three pure helpers: `_picker_choice_to_rrule(choice) -> str | None`, `_rrule_to_picker_choice(rrule_str) -> str`, `_local_date_to_utc_end_of_day(picked) -> datetime`.
2. **Extend `ReminderFormDialog.__init__`** with the recurrence row (QComboBox + Reset button) and end-date row (QCheckBox + QDateEdit). Wire the picker's `currentTextChanged` and the checkbox's `toggled` signals to the enable/disable cascade slot, and the datetime field's `dateTimeChanged` to `_update_monthly_tooltip`. Pre-fill in Edit mode from `self._editing.rrule_str` + `self._editing.end_at`.
3. **Add `_on_recurrence_changed` slot** that applies the cascade: when picker is `None`, end-date row is disabled; otherwise the checkbox enables, and the QDateEdit follows the checkbox state. Also applies the Monthly-day-31 tooltip when relevant.
4. **Add `_on_recurrence_reset_clicked` slot** for the custom-locked override path: confirm via `QMessageBox.question`, on Yes set picker to `None`, enable the picker, hide the Reset button, clear the custom rule reference (so save translates from picker rather than preserving).
5. **Modify `accept()`**: between the existing datetime validation and the Reminder construction, compute `rrule_str` and `end_at_utc` from the picker + end-date row state (or preserve `self._editing.rrule_str` when locked-custom and Reset wasn't clicked). Replace the unconditional past-time gate with the recurrence-aware version: one-shot keeps `start_at_utc <= clock()` rejection; recurring rejects when `next_firing_after(tentative_reminder, clock())` returns `None`. Edit-mode skip applies in either branch when `start_at_utc + rrule_str + end_at_utc` are all unchanged from `self._editing`.
6. **Update `Reminder` construction** in both Add and Edit branches to pass `rrule_str=` and `end_at=`.
7. **Modify `_compose_row` in `settings_dialog.py`** to append the `(<freq>)` suffix for recurring active rows. Add a private helper `_recurrence_label(rrule_str)` returning `"daily"` / `"weekly"` / `"monthly"` / `"custom"` / `""` (empty for `None`).
8. **Extend `tests/test_reminder_form_dialog.py`** with six new test classes (see Phase 1 Change #8 for the exact list).
9. **Extend `tests/test_settings_dialog.py`** with `TestComposeRowRecurrence` covering the new suffix matrix.
10. **Update `AGENTS.md`** — remove the FR-014 bullet at `AGENTS.md:184` entirely.
11. **Phase 2 bookkeeping** — `change.md` to `implemented`, `roadmap.md` S-08 to `done`, AGENTS.md verified clean, Progress section ticked.

## Critical Implementation Details

- **End-date local-to-UTC conversion (load-bearing, mirrors S-06's save direction).** `QDateEdit.date().toPython()` returns a naive Python `date` (not `datetime`). Compose with `time(23, 59, 59)` into a naive `datetime`, then `naive_dt.astimezone(UTC)` — Python 3.6+ interprets naive `astimezone` as local-zone. This matches the form's existing datetime save path (`reminder_form_dialog.py:481`); the same DST-correctness rationale applies. The reverse on Edit pre-fill is `end_at.astimezone().date()` (tz-aware → system local → date-only). A test pins both directions on a frozen system zone.

- **Recurrence picker exact-string round-trip is byte-stable.** The three RRULE strings the picker produces (`"FREQ=DAILY"` / `"FREQ=WEEKLY"` / `"FREQ=MONTHLY"`) are exactly what `_rrule_to_picker_choice` exact-matches against on Edit pre-fill. A reminder created with the picker, saved, and re-opened in Edit must show the same picker selection — pinned by `test_recurrence_round_trips_through_storage`. Do NOT add normalization (e.g., uppercasing, stripping); the storage layer round-trips the string verbatim and any normalization would diverge from hand-edited inputs.

- **Past-time gate reordering matters.** The current gate (one inequality + one equality skip) becomes a two-branch construct. The Edit-mode equality skip widens to compare three fields (`start_at`, `rrule_str`, `end_at`) — when any of the three has changed, the gate applies. When all three are equal to `self._editing`, the gate skips. This preserves the S-07 "rename an expired reminder without rescheduling it" affordance for recurring reminders too. A test pins each combinatorial case (datetime-changed, rrule-changed, end-changed, all-three-changed, none-changed).

- **Tentative-reminder construction inside the gate.** The recurring gate calls `next_firing_after(tentative, clock())` BEFORE the real `Reminder` construction (which happens in step 3 of `accept()`). The tentative is built with the proposed `start_at_utc`, `rrule_str_proposed`, `end_at_utc_or_none`, and a placeholder name (the gate doesn't use the name). Constructing twice is the simplest correct shape — the `Reminder` dataclass is cheap (no IO, no validation). Pinned by a test that monkeypatches `next_firing_after` to a recorder and asserts the call signature.

- **Custom-locked Reset flow preserves rrule_str unless explicitly overridden.** When `self._editing` has an unparseable `rrule_str`, the dialog stores it on `self._original_custom_rrule = self._editing.rrule_str` at construction time. While the picker remains in `(custom)` state, `accept()` writes back this exact string (not whatever `_picker_choice_to_rrule` returns). When the user clicks `Reset…` and confirms Yes, `self._original_custom_rrule = None`, the picker is set to `None` and enabled, and from that point on `accept()` translates from the picker. A test pins both branches: save without Reset preserves the custom string; save after Reset writes the picker's translation.

- **Monthly-day-31 tooltip is informational, not a gate.** When the picker is set to Monthly AND the date in the QDateTimeEdit has `day > 28`, surface a passive tooltip on the picker (`"Months without that day are skipped"`) via `setToolTip` (NOT `QToolTip.showText` — the static tooltip is on-hover discoverable, not transient). The save still succeeds; the user sees the warning if they hover, and `dateutil`'s natural skip behavior takes over at firing time. No `QToolTip.showText` because we don't want to nag the user on save — the choice is legitimate, just noisy.

- **`QDateEdit` returns a naive `date`, not `datetime`.** `widget.date()` returns a `QDate`; `.toPython()` gives a Python `datetime.date` (no time, no tz). The save path must explicitly compose `datetime.combine(naive_date, time(23, 59, 59))` before the local→UTC dance.

- **Recurrence picker default in Add mode is `None`.** This preserves bit-for-bit behavior of the existing Add flow when the user doesn't engage with the new row — same as S-06b's lead spinbox default of 0. A test sanity-pins this: `dialog._recurrence_picker.currentText() == "None"` in Add mode with no `reminder=` kwarg.

- **`(custom)` is never user-selectable.** The QComboBox model has four entries by default; a fifth `(custom)` is `addItem`-ed only when needed (Edit mode with unparseable `rrule_str`). User-selecting it from the dropdown is impossible because the picker is `setEnabled(False)` during the custom-locked state. Adding the item conditionally avoids cluttering the dropdown for the common case.

- **`_compose_row` recurrence suffix is empty only for one-shot.** The helper `_recurrence_label` returns `""` only for `rrule_str=None` (one-shot); the four mapped strings return their corresponding `daily` / `weekly` / `monthly` labels; any other non-None string (e.g. a hand-edited `FREQ=WEEKLY;BYDAY=MO,WE,FR`) returns `custom`. So a recurring reminder with a hand-edited advanced rule shows `(custom)` both in the form's picker AND as a row suffix — symmetrical surfacing helps the user identify which row corresponds to the locked dialog state. Pinned by `test_active_recurring_custom_appends_custom_suffix` (Phase 1 #9) and Manual Verification line 436.

- **The `Reset…` button visibility is a load-bearing pin.** The button is `setVisible(False)` in Add mode and in Edit mode for known-mapping reminders. It is `setVisible(True)` only in Edit mode when the loaded `rrule_str` is non-None and not in the picker map. After a successful Reset (Yes confirm), the button hides itself. A test pins: `dialog._recurrence_reset_button.isVisible() is False` in Add mode and in Edit on a `FREQ=DAILY` reminder; `True` only on a custom-locked reminder; `False` again after Reset Yes.

## Phase 1: Implementation

### Overview

Land the entire user-visible change in one phase: the form module's recurrence + end-date rows, the bidirectional translation helpers, the past-time gate update, the `_compose_row` suffix, and the test extensions. The phase exits when `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pip-audit`, and `uv run pip-licenses --fail-on="AGPL"` are all green AND the manual verification at the end of this phase passes on a real Windows machine.

### Changes Required:

#### 1. Module-level constants + helpers in `reminder_form_dialog.py`

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Centralize the picker labels, RRULE strings, end-date defaults, and validation messages as named constants (mirrors the lead-time constant block from S-06b). Add three pure helpers: forward + reverse picker-RRULE translation, and the local-end-of-day → UTC conversion. Pure helpers are testable without spinning up the dialog.

**Contract**: New constants alongside the existing `_LEAD_*` block:

- Picker display labels: `_RECURRENCE_NONE_LABEL = "None"`, `_RECURRENCE_DAILY_LABEL = "Daily"`, `_RECURRENCE_WEEKLY_LABEL = "Weekly"`, `_RECURRENCE_MONTHLY_LABEL = "Monthly"`, `_RECURRENCE_CUSTOM_LABEL = "(custom)"`.
- RRULE strings: `_RRULE_DAILY = "FREQ=DAILY"`, `_RRULE_WEEKLY = "FREQ=WEEKLY"`, `_RRULE_MONTHLY = "FREQ=MONTHLY"`.
- Picker → RRULE map: `_PICKER_TO_RRULE: dict[str, str | None] = {_RECURRENCE_NONE_LABEL: None, _RECURRENCE_DAILY_LABEL: _RRULE_DAILY, _RECURRENCE_WEEKLY_LABEL: _RRULE_WEEKLY, _RECURRENCE_MONTHLY_LABEL: _RRULE_MONTHLY}`.
- End-date constants: `_END_DATE_CHECKBOX_LABEL = "End on:"`, `_END_DATE_DEFAULT_OFFSET_DAYS = 30`.
- Tooltips + messages: `_RECURRENCE_CUSTOM_TOOLTIP = "This reminder uses an advanced rule. Click Reset to replace it."`, `_RECURRENCE_RESET_BUTTON_LABEL = "Reset…"`, `_RECURRENCE_RESET_CONFIRM_TITLE = "Replace recurrence rule"`, `_RECURRENCE_RESET_CONFIRM_TEXT = "Replace the custom recurrence rule with one of the standard options?\nThis cannot be undone."`, `_MONTHLY_DAY31_TOOLTIP = "Months without that day are skipped (e.g. February)"`, `_NO_FUTURE_OCCURRENCES_MESSAGE = "Recurring reminder has no future firings"`, `_NO_FUTURE_OCCURRENCES_WITH_LEAD_FORMAT = "Recurring reminder has no future firings at least {lead} {unit} away"`.

(The list-row recurrence display labels — `"daily"` / `"weekly"` / `"monthly"` / `"custom"` — live only in `settings_dialog.py` per change #6 because that's the only module that consumes them; the form module produces `rrule_str` strings, not display labels. Matches the `_FIRING_FORMAT` precedent.)

Three new helpers (all pure, all module-level):

- `def _picker_choice_to_rrule(choice: str) -> str | None` — direct lookup in `_PICKER_TO_RRULE`. Raises `KeyError` for unknown choices (including `_RECURRENCE_CUSTOM_LABEL`); the caller never invokes this for the custom-locked path.
- `def _rrule_to_picker_choice(rrule_str: str | None) -> str` — exact-string reverse lookup. `None` → `_RECURRENCE_NONE_LABEL`; one of the three known strings → matching label; anything else → `_RECURRENCE_CUSTOM_LABEL`.
- `def _local_date_to_utc_end_of_day(picked: date) -> datetime` — composes `datetime.combine(picked, time(23, 59, 59)).astimezone(UTC)`. Returns tz-aware UTC. Pure function; no clock injection needed (the conversion is deterministic given the picked date and the system's current zone).

#### 2. `ReminderFormDialog.__init__` — add the recurrence + end-date rows

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Construct the four new widgets, parent them to the dialog, populate the picker, seed defaults (Add) or pre-fill from `self._editing` (Edit), wire signals, append to the existing `QFormLayout`. The `Reset…` button is a child of the recurrence row (sits next to the picker via a `QHBoxLayout`).

**Contract**: New stored attributes:

- `self._recurrence_picker: QComboBox`
- `self._recurrence_reset_button: QPushButton`
- `self._end_date_checkbox: QCheckBox`
- `self._end_date_field: QDateEdit`
- `self._original_custom_rrule: str | None = None` — set in Edit mode when the loaded `rrule_str` is unparseable; cleared on successful Reset.

The picker is constructed with the four standard items via `addItems([_RECURRENCE_NONE_LABEL, _RECURRENCE_DAILY_LABEL, _RECURRENCE_WEEKLY_LABEL, _RECURRENCE_MONTHLY_LABEL])`. The `(custom)` item is `addItem`-ed conditionally below.

The Reset button is `QPushButton(_RECURRENCE_RESET_BUTTON_LABEL, parent=self)` with `setVisible(False)` by default.

The recurrence row in the form is a `QHBoxLayout` containing the picker + the Reset button (the Reset button hides on default; the QHBoxLayout's hidden-widget behavior is acceptable — the button takes zero width when hidden).

The end-date row is a `QHBoxLayout` containing the QCheckBox (label `_END_DATE_CHECKBOX_LABEL`) + the QDateEdit (`setCalendarPopup(True)`, `setDisplayFormat("yyyy-MM-dd")`, default value = today + `_END_DATE_DEFAULT_OFFSET_DAYS` in system local). The QDateEdit is `setEnabled(False)` by default; the checkbox is `setEnabled(False)` by default (because the picker default is `None`).

Pre-fill block (added inside the existing `if self._editing is not None:` branch at lines 340-353):

- Compute `picker_choice = _rrule_to_picker_choice(self._editing.rrule_str)`.
- When `picker_choice == _RECURRENCE_CUSTOM_LABEL`: `self._original_custom_rrule = self._editing.rrule_str`; `addItem(_RECURRENCE_CUSTOM_LABEL)`; `setCurrentText(_RECURRENCE_CUSTOM_LABEL)`; `setEnabled(False)`; `setToolTip(_RECURRENCE_CUSTOM_TOOLTIP)`; `self._recurrence_reset_button.setVisible(True)`.
- Otherwise: `self._recurrence_picker.setCurrentText(picker_choice)`.
- When `self._editing.end_at is not None`: `local_date = self._editing.end_at.astimezone().date()`; `self._end_date_checkbox.setChecked(True)`; `self._end_date_field.setEnabled(True)`; `self._end_date_field.setDate(QDate(local_date.year, local_date.month, local_date.day))`.

Form layout additions:

```
form.addRow("Recurrence:", recurrence_row)
form.addRow("End on:", end_date_row)
```

Signal wiring:

- `self._recurrence_picker.currentTextChanged.connect(self._on_recurrence_changed)`.
- `self._recurrence_reset_button.clicked.connect(self._on_recurrence_reset_clicked)`.
- `self._end_date_checkbox.toggled.connect(self._end_date_field.setEnabled)`.
- `self._datetime_field.dateTimeChanged.connect(self._update_monthly_tooltip)` — keeps the Monthly-day-31 tooltip in sync when the user changes the datetime while the picker stays on Monthly.

Initial cascade application: after Edit-mode pre-fill (or in Add mode at the bottom of `__init__`), call `self._on_recurrence_changed(self._recurrence_picker.currentText())` once so the end-date row's enabled state matches the picker.

#### 3. `_on_recurrence_changed` slot

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Cascade the recurrence picker's state onto the end-date row + the Monthly-day-31 tooltip.

**Contract**: Method signature `def _on_recurrence_changed(self, choice: str) -> None`. Body:

1. Compute `is_recurring = choice != _RECURRENCE_NONE_LABEL`. The `(custom)` choice is treated as recurring for the cascade so a loaded custom-locked reminder's end-date row stays enabled and its `end_at` pre-fill is not silently cleared on no-op save. (The Monthly-day-31 tooltip in `_update_monthly_tooltip` has its own narrower guard on `choice == _RECURRENCE_MONTHLY_LABEL`, so a `(custom)` rule never triggers the Monthly tooltip.)
2. `self._end_date_checkbox.setEnabled(is_recurring)`. When `is_recurring is False`, also `self._end_date_checkbox.setChecked(False)` so the QDateEdit gets disabled too (`toggled` signal cascades).
3. Call `self._update_monthly_tooltip()` to apply the Monthly-day-31 tooltip rule (extracted into a separate method so the datetime-change path can reuse it — see below).

Note: this slot is also called once at the end of `__init__` (after pre-fill / default seeding) to apply the initial cascade, so the explicit-pre-fill path and the user-driven path share one piece of logic.

**Tooltip-only slot**: separate method `def _update_monthly_tooltip(self) -> None`. Body: when `self._recurrence_picker.currentText() == _RECURRENCE_MONTHLY_LABEL` AND the QDateTimeEdit's current `dateTime().toPython().day > 28`, `self._recurrence_picker.setToolTip(_MONTHLY_DAY31_TOOLTIP)`. Otherwise `self._recurrence_picker.setToolTip("")`. (The custom-locked tooltip `_RECURRENCE_CUSTOM_TOOLTIP` is set in `__init__` only and is unaffected by this method; while custom-locked the picker is disabled, so changing the datetime doesn't trigger this method to clobber the custom tooltip — but for safety the method early-returns when the picker is disabled.) This method is wired in Phase 1 #2 to BOTH the picker's `currentTextChanged` (via `_on_recurrence_changed` step 3) AND the datetime field's `dateTimeChanged`.

#### 4. `_on_recurrence_reset_clicked` slot

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Override the custom-locked picker via a `QMessageBox.question` confirm. Yes → drop the original RRULE reference, enable the picker, hide the Reset button, set picker to `None`. No → noop.

**Contract**: Method signature `def _on_recurrence_reset_clicked(self) -> None`. Body:

1. `reply = QMessageBox.question(self, _RECURRENCE_RESET_CONFIRM_TITLE, _RECURRENCE_RESET_CONFIRM_TEXT, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)`.
2. Early return when `reply != QMessageBox.StandardButton.Yes`.
3. `self._original_custom_rrule = None`.
4. Find the `(custom)` index via `self._recurrence_picker.findText(_RECURRENCE_CUSTOM_LABEL)`; when `>= 0`, `self._recurrence_picker.removeItem(idx)`.
5. `self._recurrence_picker.setCurrentText(_RECURRENCE_NONE_LABEL)`.
6. `self._recurrence_picker.setEnabled(True)`.
7. `self._recurrence_picker.setToolTip("")`.
8. `self._recurrence_reset_button.setVisible(False)`.
9. The `currentTextChanged` signal from #5 already fires `_on_recurrence_changed`, which cascades the end-date row off — no explicit call needed.

The `QMessageBox` import is added to the existing PySide6 import block at the top of `reminder_form_dialog.py` (alongside `QDateTimeEdit`, etc.). The pattern matches `settings_dialog.py:98` where `QMessageBox` is already imported for the Delete confirm.

#### 5. `accept()` — recurrence-aware past-time gate + RRULE construction

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Slot the recurrence translation between the existing datetime validation (which computes `start_at_utc`) and the existing `Reminder` construction. Replace the unconditional past-time gate with the recurrence-aware version. Pass `rrule_str` and `end_at` into the `Reminder` constructor in both Add and Edit branches.

**Contract**: After the existing line `start_at_utc = event_at_utc - timedelta(minutes=lead_minutes)` (currently `accept()` line 483) and BEFORE the current past-time gate (currently lines 484-500), insert recurrence translation:

1. Read picker state: `picker_choice = self._recurrence_picker.currentText()`.
2. Compute `rrule_str_proposed`:
   - When `picker_choice == _RECURRENCE_CUSTOM_LABEL` (custom-locked, Reset wasn't clicked): `rrule_str_proposed = self._original_custom_rrule`.
   - Otherwise: `rrule_str_proposed = _picker_choice_to_rrule(picker_choice)` (returns `None` for `None`).
3. Compute `end_at_proposed`:
   - When `rrule_str_proposed is None` (one-shot): `end_at_proposed = None` (irrespective of checkbox state — the checkbox should already be unchecked + disabled, but be defensive).
   - When `rrule_str_proposed is not None` AND `self._end_date_checkbox.isChecked()`: `end_at_proposed = _local_date_to_utc_end_of_day(self._end_date_field.date().toPython())`.
   - Otherwise: `end_at_proposed = None`.

Replace the existing past-time gate (lines 484-500) with a recurrence-aware version:

```python
firing_unchanged_in_edit = (
    self._editing is not None
    and start_at_utc == self._editing.start_at
    and rrule_str_proposed == self._editing.rrule_str
    and end_at_proposed == self._editing.end_at
)
if not firing_unchanged_in_edit:
    if rrule_str_proposed is None:
        # One-shot: must fire in the future (existing behavior)
        if start_at_utc <= self._clock():
            message = (
                _format_past_time_with_lead(lead_minutes)
                if lead_minutes > 0
                else _PAST_TIME_MESSAGE
            )
            self._show_tooltip(self._datetime_field, message)
            return
    else:
        # Recurring: must have at least one future occurrence
        tentative = Reminder(
            name="<tentative>",  # name is irrelevant for next_firing_after
            start_at=start_at_utc,
            rrule_str=rrule_str_proposed,
            end_at=end_at_proposed,
            lead_minutes=lead_minutes,
        )
        if next_firing_after(tentative, self._clock()) is None:
            message = (
                _format_no_future_occurrences_with_lead(lead_minutes)
                if lead_minutes > 0
                else _NO_FUTURE_OCCURRENCES_MESSAGE
            )
            self._show_tooltip(self._datetime_field, message)
            return
```

A new runtime import `from break_reminder.scheduler import next_firing_after` is added to the import block in `reminder_form_dialog.py` (the function is not currently referenced in this module — the `ReminderScheduler` import in `TYPE_CHECKING` covers a different symbol). A new helper `_format_no_future_occurrences_with_lead(lead: int) -> str` mirrors `_format_past_time_with_lead` (singular/plural minute handling).

In the `Reminder(...)` construction blocks (currently lines 506-518), add `rrule_str=rrule_str_proposed` and `end_at=end_at_proposed` as kwargs in both Add and Edit branches.

#### 6. `_compose_row` recurrence suffix in `settings_dialog.py`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Append a parenthesized recurrence label to active recurring rows so the user sees at a glance that a reminder is recurring. Matches the existing `(fires N min before)` suffix pattern.

**Contract**: Three new module-level constants alongside `_FIRING_FORMAT`:

- `_RECURRENCE_SUFFIX_DAILY = "daily"`
- `_RECURRENCE_SUFFIX_WEEKLY = "weekly"`
- `_RECURRENCE_SUFFIX_MONTHLY = "monthly"`
- `_RECURRENCE_SUFFIX_CUSTOM = "custom"`

A new private helper:

```python
def _recurrence_label(rrule_str: str | None) -> str:
    if rrule_str is None:
        return ""
    if rrule_str == "FREQ=DAILY":
        return _RECURRENCE_SUFFIX_DAILY
    if rrule_str == "FREQ=WEEKLY":
        return _RECURRENCE_SUFFIX_WEEKLY
    if rrule_str == "FREQ=MONTHLY":
        return _RECURRENCE_SUFFIX_MONTHLY
    return _RECURRENCE_SUFFIX_CUSTOM
```

`_compose_row` is extended:

- The expired branch (`fire_at is None`) is unchanged — no recurrence suffix on expired rows.
- The active branches gain a `recurrence_label = _recurrence_label(reminder.rrule_str)` lookup at the top.
- When `recurrence_label == ""` (one-shot): existing format strings unchanged.
- When `recurrence_label != ""` AND `lead_minutes == 0`: `f"{name}  —  {firing} ({recurrence_label})"`.
- When `recurrence_label != ""` AND `lead_minutes > 0`: `f"{name}  —  {event_time}  (fires {lead} min before, {recurrence_label})"`.

The four suffix constants live only in `settings_dialog.py` — single source of truth, matches the `_FIRING_FORMAT` precedent (which is also display-only and does not duplicate into the form module).

#### 7. New test class: `TestRecurrencePicker` in `tests/test_reminder_form_dialog.py`

**File**: `tests/test_reminder_form_dialog.py`

**Intent**: Pin the picker's structure and the recurrence-row enable/disable cascade. Mirrors `TestReminderFormDialogDefaults` in shape.

**Contract**: New test class with at least:

- `test_picker_has_four_default_items` — asserts items are `["None", "Daily", "Weekly", "Monthly"]` in Add mode.
- `test_picker_default_is_none_in_add_mode` — `currentText() == "None"`.
- `test_picker_is_enabled_in_add_mode` — `isEnabled() is True`.
- `test_reset_button_hidden_in_add_mode` — `isVisible() is False`.
- `test_end_date_checkbox_disabled_when_picker_is_none` — `isEnabled() is False`.
- `test_end_date_field_disabled_when_checkbox_unchecked` — `isEnabled() is False`.
- `test_end_date_checkbox_enables_when_picker_set_to_daily` — `setCurrentText("Daily")` → checkbox `isEnabled() is True`.
- `test_end_date_checkbox_enables_for_weekly_and_monthly_too` — parametrize over the three recurring choices.
- `test_end_date_field_enables_when_checkbox_ticked` — set picker to Daily, tick checkbox → field `isEnabled() is True`.
- `test_picker_back_to_none_disables_end_date_row` — set Daily + ticked end-date, then back to None → checkbox unchecked AND disabled, field disabled.
- `test_monthly_day31_tooltip_appears_when_start_day_above_28` — set datetime to a day-31, set picker to Monthly → `_recurrence_picker.toolTip() == _MONTHLY_DAY31_TOOLTIP`.
- `test_monthly_day28_or_below_does_not_show_tooltip` — same but day=15 → `toolTip() == ""`.
- `test_monthly_tooltip_clears_when_picker_changes_away_from_monthly` — set day-31 + Monthly (tooltip set), then set picker to Weekly → `toolTip() == ""`.
- `test_monthly_tooltip_appears_when_datetime_changes_to_day31_with_picker_on_monthly` — set picker to Monthly + day-15 (tooltip empty), then change datetime to day-31 → `toolTip() == _MONTHLY_DAY31_TOOLTIP`. Pins F5 fix: the tooltip rule is symmetric across both signal paths.
- `test_monthly_tooltip_clears_when_datetime_drops_below_day29_with_picker_on_monthly` — set picker to Monthly + day-31 (tooltip set), then change datetime to day-15 → `toolTip() == ""`.

#### 8. New test classes: `TestRecurrenceSave`, `TestRecurrenceEditMode`, `TestRecurrenceCustomLocked`, `TestRecurrencePastTimeGate`, `TestRecurrenceEndDate`

**File**: `tests/test_reminder_form_dialog.py`

**Intent**: Pin the forward + reverse RRULE translation, the custom-locked behavior, the recurrence-aware past-time gate, and the end-date round-trip across system zones.

**Contract**:

`TestRecurrenceSave` (forward translation, save path):

- `test_save_with_picker_none_persists_rrule_str_none` — picker `None` + checkbox unticked → saved `rrule_str is None`, `end_at is None`.
- `test_save_with_picker_daily_persists_freq_daily` — picker `Daily` → `rrule_str == "FREQ=DAILY"`.
- `test_save_with_picker_weekly_persists_freq_weekly`.
- `test_save_with_picker_monthly_persists_freq_monthly`.
- `test_save_with_end_date_unticked_persists_end_at_none` — picker `Daily`, checkbox unticked → `end_at is None`.
- `test_save_with_end_date_ticked_persists_end_at_at_local_eod_in_utc` — pick a date 7 days out, save, assert `saved.end_at.astimezone().date() == picked_date AND saved.end_at.astimezone().time() == time(23, 59, 59) AND saved.end_at.tzinfo == UTC`.
- `test_save_with_picker_none_ignores_end_date_state` — even if checkbox ends up checked (defensive — can't happen via UI but test the `accept()` branch), `end_at is None`.

`TestRecurrenceEditMode` (reverse translation, pre-fill):

- `test_edit_mode_pre_fills_picker_to_none_for_one_shot` — load a reminder with `rrule_str=None`; picker `currentText() == "None"`.
- `test_edit_mode_pre_fills_picker_to_daily_for_freq_daily` — `rrule_str="FREQ=DAILY"` → picker `"Daily"`.
- `test_edit_mode_pre_fills_picker_to_weekly_and_monthly` — parametrize.
- `test_edit_mode_pre_fills_end_date_checkbox_when_end_at_set` — load with `end_at = aware_utc_eod`; checkbox checked, field enabled, field `date().toPython() == aware_utc_eod.astimezone().date()`.
- `test_edit_mode_no_end_at_leaves_checkbox_unchecked` — load with `end_at=None`; checkbox unchecked, field disabled.
- `test_edit_mode_recurrence_round_trips_through_save_load_save` — end-to-end: create a Daily reminder with end-date in Add mode, persist, re-open in Edit, assert picker is Daily + end-date matches; re-save without changes; assert disk content unchanged.

`TestRecurrenceCustomLocked`:

- `test_custom_rrule_pre_fills_picker_to_custom` — `rrule_str="FREQ=WEEKLY;BYDAY=MO,WE,FR"` → picker `currentText() == "(custom)"`, `isEnabled() is False`, `toolTip() == _RECURRENCE_CUSTOM_TOOLTIP`.
- `test_custom_rrule_shows_reset_button` — same setup → Reset button `isVisible() is True`.
- `test_save_without_reset_preserves_custom_rrule_str` — load custom-locked, change name only, save → `saved.rrule_str == original_custom_rrule_str` (byte-equal).
- `test_save_after_reset_yes_uses_picker_translation` — load custom-locked, click Reset, monkeypatched `QMessageBox.question` returns Yes, `setCurrentText("Daily")`, save → `saved.rrule_str == "FREQ=DAILY"`.
- `test_reset_no_preserves_state` — Reset → No → picker still `(custom)`, still disabled, button still visible, `_original_custom_rrule` unchanged.
- `test_reset_yes_hides_button_and_enables_picker` — assert `_recurrence_reset_button.isVisible() is False` AND `_recurrence_picker.isEnabled() is True` after Reset Yes.
- `test_custom_locked_with_end_at_preserves_end_at_on_no_op_save` — load custom-locked reminder with `end_at` set; save without any other changes; assert `saved.end_at == loaded.end_at` (byte-equal). Pins F1 fix: cascade must NOT untick the end-date checkbox for `(custom)`.
- `test_custom_locked_end_date_field_remains_enabled` — load custom-locked reminder with `end_at` set; assert `_end_date_checkbox.isChecked() is True` AND `_end_date_checkbox.isEnabled() is True` AND `_end_date_field.isEnabled() is True` after `__init__` completes (the cascade has run).

`TestRecurrencePastTimeGate`:

- `test_recurring_with_past_start_but_future_occurrence_saves` — picker `Daily`, datetime 2 days in past, no end-date → save succeeds (next firing is +1 day from past_start, which is in the future).
- `test_recurring_with_past_end_at_blocks_save` — picker `Daily`, datetime in past, end-date 1 day in past → save blocked with `_NO_FUTURE_OCCURRENCES_MESSAGE` tooltip; nothing persisted.
- `test_one_shot_past_time_still_blocked_with_existing_message` — picker `None`, datetime 1 hour in past → existing `_PAST_TIME_MESSAGE` tooltip; nothing persisted.
- `test_edit_mode_skip_applies_when_all_three_unchanged` — load expired one-shot, change only the name, save succeeds (existing S-07 skip still works).
- `test_edit_mode_skip_does_not_apply_when_rrule_changed` — load Daily reminder with start_at in the future, save still succeeds; load same with start_at in the past, change picker to Weekly (same FREQ family but different rule string), gate now applies (must verify future occurrence under the new rule).
- `test_edit_mode_skip_does_not_apply_when_end_at_changed` — load Daily with end_at in 30 days, change end_at to yesterday; gate fires.
- `test_recurring_with_lead_no_future_uses_lead_aware_message` — picker `Daily`, datetime past, end_at past, lead=15 → tooltip uses `_NO_FUTURE_OCCURRENCES_WITH_LEAD_FORMAT`-formatted message (singular handled at lead=1).

`TestRecurrenceEndDate`:

- `test_end_date_field_default_offset_is_30_days` — Add mode → field's date `== (today + 30 days)` in system local.
- `test_end_date_local_to_utc_conversion` — pick date X, save, assert `saved.end_at == X.astimezone(UTC at 23:59:59 local)` computed manually so the test is correct on any CI runner zone.
- `test_end_date_round_trips_through_storage` — save with end-date, reopen Edit, assert checkbox + field match the original picked date (date-level equality after the local→UTC→local round-trip).

#### 9. New test class: `TestComposeRowRecurrence` in `tests/test_settings_dialog.py`

**File**: `tests/test_settings_dialog.py`

**Intent**: Pin the new recurrence suffix matrix on `_compose_row`. Mirrors the existing one-shot lead-time tests.

**Contract**:

- `test_active_one_shot_no_lead_unchanged` — sanity, `_compose_row(reminder=one_shot, ...)` matches the existing format.
- `test_active_recurring_daily_no_lead_appends_suffix` — `_compose_row` returns `f"{name}  —  {firing} (daily)"`.
- `test_active_recurring_weekly_no_lead_appends_suffix` — parametrize.
- `test_active_recurring_monthly_no_lead_appends_suffix`.
- `test_active_recurring_custom_appends_custom_suffix` — `rrule_str` outside the picker map → suffix `(custom)`.
- `test_active_recurring_with_lead_appends_combined_suffix` — `(fires 15 min before, daily)`.
- `test_expired_recurring_does_not_append_suffix` — past end_at → `<name>  —  (expired)` (no recurrence suffix).
- `test_compose_row_helper_recurrence_label_returns_empty_for_none` — `_recurrence_label(None) == ""`.
- `test_compose_row_helper_recurrence_label_returns_known_strings` — parametrize the four known + one custom.

#### 10. `AGENTS.md` — remove the FR-014 bullet

**File**: `AGENTS.md`

**Intent**: With S-08 shipped, no FR remains pending in the "What this scaffold does NOT yet implement" list for Stream B custom reminders. The bullet is removed entirely (not narrowed).

**Contract**: Delete the bullet at `AGENTS.md:184` reading `Custom-reminder recurrence editor (FR-014). The read-only Reminders tab shipped in S-05; Add / Edit / Delete CRUD shipped in S-06 / S-07; the daily / weekly / monthly RRULE picker is the last pending Stream B surface (S-08).` After the deletion, the parent list still contains the other pending items (Focus Assist + system-mute query, real tray-icon resources, snooze countdown UI affordance) — those are not S-08's territory.

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v` (includes new `TestRecurrencePicker` + `TestRecurrenceSave` + `TestRecurrenceEditMode` + `TestRecurrenceCustomLocked` + `TestRecurrencePastTimeGate` + `TestRecurrenceEndDate`)
- Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestComposeRowRecurrence`)
- Full suite passes: `uv run pytest`
- Type check passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Format check passes: `uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual Verification:

- Open Settings → Reminders → Add: dialog shows the new Recurrence row (picker = "None") and End on row (checkbox unchecked, date field disabled).
- Set picker to Daily: end-date checkbox enables; check it; date field enables; pick a date 30 days out (or accept default). Set name + datetime. OK. Row appears in list with `(daily)` suffix.
- Edit the same reminder: picker pre-fills to Daily; end-date checkbox checked + field shows the picked date. Cancel.
- Edit again: change picker to None; end-date checkbox disables and unticks. OK. Row no longer shows `(daily)` suffix.
- Add a Monthly reminder with date = 31st of next month; recurrence-picker tooltip shows `Months without that day are skipped (e.g. February)` on hover.
- Add a Weekly reminder with start_at 1 hour in the past: save succeeds (next occurrence is 7 days from start in the future); row appears with `(weekly)`.
- Add a Daily reminder with end-date in the past: save blocked with tooltip `Recurring reminder has no future firings`; nothing persisted.
- Hand-edit `%APPDATA%\BreakReminder\reminders.json` to set one entry's `rrule_str` to `"FREQ=WEEKLY;BYDAY=MO,WE,FR"`; reopen the app; open Settings → Reminders; the row shows `(custom)` suffix in the list. Edit the row: picker shows `(custom)`, disabled, with tooltip; Reset button visible. Click Reset, click No in the confirm: state preserved, OK with no other changes saves the entry with the original RRULE byte-for-byte.
- Open Edit again; click Reset, Yes; picker enables and resets to None; save: the entry's `rrule_str` becomes None (one-shot).
- Add a Daily reminder with lead-time 15 min: row shows `(fires 15 min before, daily)`.
- Add a Weekly reminder for ~30 seconds out (start_at = now + 30s, picker Weekly): wait 30 seconds; the popup fires (proves recurring also routes through `ReminderScheduler.reload()` and `next_firing_after`). Cancel out; wait until next minute; popup does not re-fire (next occurrence is +7 days, well outside the test window).
- Existing one-shot reminders created before this slice still load and display correctly (no recurrence suffix on one-shot rows, picker pre-fills to None on Edit).
- No regressions in Scheduling, Notifications, Lifecycle tabs.

**Implementation Note**: After completing this phase and all automated verification passes, pause for manual confirmation that the manual checks above were successful before proceeding to Phase 2.

---

## Phase 2: Manual smoke + bookkeeping

### Overview

Move the slice from "implemented" to "shipped + traceable": confirm the recurrence flows work under real Windows for the four picker choices and the custom-locked path, then mark every document that tracks this slice's status. No code changes in this phase.

### Changes Required:

#### 1. Manual smoke run

**File**: n/a — operational step

**Intent**: With the new recurrence editor deployed locally (via `uv run python -m break_reminder`), perform the Phase-1 manual verification steps against a real Windows session, plus the custom-locked hand-edit path.

**Contract**: Steps:

1. Stop any running BreakReminder.
2. Delete `%APPDATA%\BreakReminder\reminders.json`.
3. Run `uv run python -m break_reminder`.
4. Open Settings → Reminders → Add: create "Daily standup" with time = now + 30 seconds, picker = Daily, no end-date. OK. Wait 30 seconds: popup fires showing "Daily standup". Confirm row shows `(daily)` suffix in the list.
5. Edit "Daily standup": change picker to Weekly, save. Confirm row updates to `(weekly)`.
6. Edit again: change picker to Monthly, set date to 31st of next month. Confirm tooltip on picker shows `Months without that day are skipped (e.g. February)`. Save.
7. Edit again: tick "End on:", pick a date 7 days out, save. Confirm `reminders.json` shows `end_at` in ISO 8601 UTC; Edit re-opens with the same date pre-filled.
8. Add a new reminder with picker = Daily, date = today (1 hour ago for the wall-clock), no end-date. Confirm save succeeds (next occurrence is tomorrow).
9. Add a new reminder with picker = Daily, date = yesterday, end-date = yesterday. Confirm save is blocked with `Recurring reminder has no future firings` tooltip.
10. Stop the app. Hand-edit `reminders.json` and change one entry's `rrule_str` to `"FREQ=WEEKLY;BYDAY=MO,WE,FR"`. Restart the app. Open Settings → Reminders: the entry shows `(custom)` suffix. Edit it: picker shows `(custom)` + disabled + tooltip; Reset button visible. Click Reset, choose No: state preserved. Save (no changes): inspect `reminders.json` — the entry's `rrule_str` is byte-for-byte unchanged.
11. Edit the same entry again, click Reset, choose Yes: picker enables, defaults to None, Reset button hides. Save. Inspect `reminders.json`: `rrule_str` is now `null`.
12. No regressions: Scheduling / Notifications / Lifecycle tabs still functional. Existing one-shot reminders created in earlier sessions still load and Edit cleanly.

#### 2. Update `change.md`

**File**: `context/changes/reminders-recurrence-editor/change.md`

**Intent**: Flip `status: planned` → `status: implemented`. Update `updated:` to today's date.

**Contract**: YAML front-matter `status` value changes; `updated` date refreshes. Optional `## Notes` "Implementation note" sub-heading appended if anything notable surfaced in the smoke run.

#### 3. Update `roadmap.md`

**File**: `context/foundation/roadmap.md`

**Intent**: Flip the S-08 row in "At a glance" from `proposed` to `done`. Update the `### S-08` block. Update the Backlog Handoff row. Update the Streams comment.

**Contract**: Substitutions in `roadmap.md`:

1. `| S-08 | reminders-recurrence-editor | ... | proposed |` (the "At a glance" table row) → `| S-08 | reminders-recurrence-editor | ... | done |`.
2. `- **Status:** proposed` (inside `### S-08` body block) → `- **Status:** done`.
3. The Backlog Handoff row for S-08: column "Ready for `/10x-plan`": `no` → `yes`; Notes: append `Planned + shipped 2026-05-28`.
4. The Streams table B row's chain note: `S-05 → S-06 → S-06b / S-07 / S-08 (parallel after S-06)` is unchanged in the chain itself, but the parenthetical note can be tightened to `... (all done)`.

The `## Done` section entry will be appended at archive time (per the S-05 / S-06 / S-06b / S-07 precedent — `/10x-archive` adds the entry when it moves the folder).

#### 4. Verify `AGENTS.md` update from Phase 1 #10 landed

**File**: `AGENTS.md`

**Intent**: Confirm the Phase-1 #10 bullet deletion landed.

**Contract**: `git grep -nE 'Custom-reminder recurrence editor' AGENTS.md` returns no matches. `git grep -nE 'FR-014' AGENTS.md` returns no matches (the only FR-014 reference in AGENTS.md was inside the bullet that was deleted; if other references survive, leave them).

#### 5. Tick the Progress section

**File**: `context/changes/reminders-recurrence-editor/plan.md`

**Intent**: Mark every Phase 1 and Phase 2 progress item complete, with the merge commit SHA appended per `references/progress-format.md`.

**Contract**: `- [ ]` → `- [x] — <sha>` for each line in the Progress section below.

### Success Criteria:

#### Automated Verification:

- `git grep -nE 'Custom-reminder recurrence editor' AGENTS.md` returns no matches.
- `git grep -nE '^\| S-08 .*proposed' context/foundation/roadmap.md` returns no matches.
- `git diff context/changes/reminders-recurrence-editor/change.md` shows `status: implemented` and an updated `updated:` date.

#### Manual Verification:

- Real Windows: Daily 30-sec reminder fires + row shows `(daily)` (Phase 2.1 step 4).
- Real Windows: switch picker between Daily / Weekly / Monthly (Phase 2.1 steps 5-6); tooltip on Monthly day-31 (step 6).
- Real Windows: end-date round-trips through Edit (Phase 2.1 step 7).
- Real Windows: recurring with past start_at + future occurrence saves (step 8); recurring with past end_at blocks save (step 9).
- Real Windows: hand-edited custom RRULE preserves through Edit + save without Reset (step 10); Reset Yes overrides cleanly (step 11).
- Real Windows: no regressions, existing one-shot reminders still work (step 12).

**Implementation Note**: After completing all checks above, the slice is done. This is the final Stream B surface — `roadmap.md` shows all of S-01 through S-08 as `done` after this lands.

---

## Testing Strategy

### Unit Tests:

- **Form dialog (`tests/test_reminder_form_dialog.py`).** Six new test classes covering the picker structure + cascade, forward translation (save), reverse translation (Edit pre-fill), custom-locked pre-fill + Reset flow, the recurrence-aware past-time gate (one-shot branch unchanged, recurring branch via `next_firing_after`), and the end-date local→UTC round-trip on a frozen system zone.
- **Settings dialog (`tests/test_settings_dialog.py`).** One new test class `TestComposeRowRecurrence` covering the recurrence suffix matrix on `_compose_row` (one-shot unchanged, recurring + lead, expired suppression, custom suffix) and a tripwire that the form-dialog's recurrence-suffix constants are byte-equal to `settings_dialog`'s.
- **Storage (`tests/test_reminders.py`).** Existing tests already cover `rrule_str` + `end_at` round-trip; no extension needed.
- **Scheduler (`tests/test_scheduler.py`).** Existing tests already cover daily / weekly-BYDAY / monthly-BYMONTHDAY / end-truncation / invalid-RRULE; no extension needed for S-08's plain `FREQ=DAILY` / `FREQ=WEEKLY` / `FREQ=MONTHLY` (the scheduler doesn't care about the RRULE complexity — it delegates to `dateutil`).

### Integration Tests:

- **`tests/test_app.py` smoke.** No app-level surface changes. Tests must continue passing unchanged.
- **No new integration test file.** A "create recurring → wait → fire → wait → fire again" end-to-end would require timed waits across recurrence intervals (≥ 24 h for daily); the unit-test coverage of each link in the chain (form → store → scheduler → row display) is sufficient. Manual smoke covers a 30-second daily fire.

### Manual Testing Steps:

The Phase 2.1 step list IS the manual testing surface; see Phase 2 above.

## Performance Considerations

- **`next_firing_after` cost in the past-time gate.** Constructing a tentative `Reminder` and calling `next_firing_after` is one `rrulestr` parse + one `rule.after(now, inc=False)` call. Both are sub-millisecond for the four supported RRULE strings (`dateutil` is C-optimized). Called once per save attempt — no concern.
- **`_compose_row` recurrence-label lookup.** Four-element string-equality chain — sub-microsecond. Called once per row per `_build_reminders_tab` call (≤ 10 reminders for the persona).
- **No new persistent state.** The custom-locked override flow is in-memory (`self._original_custom_rrule`); resets to `None` on dialog close, no leak.
- **No new IO.** Storage layer is unchanged; the `reminders.json` file format is unchanged at the schema level (the same fields are populated).

## Migration Notes

- **No data migration.** `reminders.json` schema is unchanged. Existing entries (one-shot or hand-edited recurring) load and round-trip without touch. The picker's reverse-translation handles all four legitimate states (None, Daily, Weekly, Monthly) plus the catch-all custom-locked.
- **No setting migration.** No new `Settings` keys.
- **No installer / PyInstaller change.** Same release pipeline; `dateutil` is already in the dependency set (used by the scheduler since v0.1.0).

## References

- Roadmap entry: `context/foundation/roadmap.md` § S-08
- PRD: `context/foundation/prd.md` FR-014 (line 129)
- S-06 plan (form-dialog scaffold + reminder_added contract): `context/archive/2026-05-27-reminders-add-form/plan.md`
- S-06b plan (storage Model A + form-field extension precedent): `context/archive/2026-05-27-reminders-lead-time/plan.md`
- S-07 plan (dual-mode form + Edit-mode skip pattern): `context/archive/2026-05-27-reminders-edit-delete/plan.md`
- Storage layer: `break_reminder/storage/reminders.py:114-179` (`Reminder.rrule_str` + `Reminder.end_at` + `_coerce_aware_utc`)
- Scheduler RRULE engine: `break_reminder/scheduler.py:323-348` (`next_firing_after`)
- Existing form module: `break_reminder/ui/reminder_form_dialog.py:272-553` (`ReminderFormDialog`)
- List row composition: `break_reminder/ui/settings_dialog.py:289-332` (`_compose_row`)
- Scheduler tests: `tests/test_scheduler.py:40-77` (RRULE coverage)
- Storage tests: `tests/test_reminders.py:140-167, :245-252, :465-485` (round-trip coverage)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Implementation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v` (includes new `TestRecurrencePicker` + `TestRecurrenceSave` + `TestRecurrenceEditMode` + `TestRecurrenceCustomLocked` + `TestRecurrencePastTimeGate` + `TestRecurrenceEndDate`) — 3439eb3
- [x] 1.2 Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestComposeRowRecurrence`) — 3439eb3
- [x] 1.3 Full suite passes: `uv run pytest` — 3439eb3
- [x] 1.4 Type check passes: `uv run pyright` — 3439eb3
- [x] 1.5 Linting passes: `uv run ruff check` — 3439eb3
- [x] 1.6 Format check passes: `uv run ruff format --check` — 3439eb3
- [x] 1.7 Security audit passes: `uv run pip-audit` — 3439eb3
- [x] 1.8 License gate passes: `uv run pip-licenses --fail-on="AGPL"` — 3439eb3

#### Manual

- [x] 1.9 Add: dialog shows new Recurrence + End-on rows; default picker is None; end-date row disabled — 3439eb3
- [x] 1.10 Set picker to Daily: end-date checkbox enables; tick checkbox: field enables; defaults to today + 30 days; saved Daily reminder's row shows `(daily)` suffix — 3439eb3
- [x] 1.11 Edit on Daily reminder pre-fills picker to Daily and end-date if set — 3439eb3
- [x] 1.12 Switch to None: end-date row disables + unticks; row no longer shows `(daily)` suffix — 3439eb3
- [x] 1.13 Monthly + day-31 start: picker tooltip shows skip-months message — 3439eb3
- [x] 1.14 Recurring with past start_at + future occurrence: save succeeds; row shows `(weekly)` or similar — 3439eb3
- [x] 1.15 Recurring with past end_at: save blocked with `Recurring reminder has no future firings` tooltip — 3439eb3
- [x] 1.16 Hand-edited `FREQ=WEEKLY;BYDAY=MO,WE,FR`: picker shows `(custom)` + disabled + Reset button visible; Reset → No preserves state and rrule_str byte-for-byte on no-change save — 3439eb3
- [x] 1.17 Reset → Yes: picker enables + resets to None + Reset button hides — 3439eb3
- [x] 1.18 Daily + lead 15 min: row shows `(fires 15 min before, daily)` — 3439eb3
- [x] 1.19 Recurring near-future fires correctly through ReminderScheduler.reload() — 3439eb3
- [x] 1.20 Existing one-shot reminders still load + edit cleanly (no regressions) — 3439eb3
- [x] 1.21 No regressions in Scheduling / Notifications / Lifecycle tabs — 3439eb3

### Phase 2: Manual smoke + bookkeeping

#### Automated

- [x] 2.1 `git grep -nE 'Custom-reminder recurrence editor' AGENTS.md` returns no matches — 739cd1a
- [x] 2.2 `git grep -nE '^\| S-08 .*proposed' context/foundation/roadmap.md` returns no matches — 739cd1a
- [x] 2.3 `git diff context/changes/reminders-recurrence-editor/change.md` shows `status: implemented` and updated `updated:` date — a214189

#### Manual

- [x] 2.4 Real Windows: Daily 30-sec reminder fires + row shows `(daily)` — 739cd1a
- [x] 2.5 Real Windows: switch picker Daily → Weekly → Monthly with day-31 tooltip on Monthly — 739cd1a
- [x] 2.6 Real Windows: end-date round-trips through Edit — 739cd1a
- [x] 2.7 Real Windows: recurring with past start_at + future occurrence saves; recurring with past end_at blocks — 739cd1a
- [x] 2.8 Real Windows: hand-edited custom RRULE preserves through Edit + save without Reset; Reset Yes overrides cleanly — 739cd1a
- [x] 2.9 Real Windows: no regressions; existing one-shot reminders still work — 739cd1a
