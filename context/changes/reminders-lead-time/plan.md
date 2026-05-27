# Reminders Lead-Time Option Implementation Plan

## Overview

Add a "Notify N min before event" option to the Add Reminder form so users can be notified some time *before* the event itself rather than at the event instant. UX is a `QSpinBox` (0-60, step 1, default 0) inserted into the existing `ReminderFormDialog`. Storage gets one new field on `Reminder` (`lead_minutes: int = 0`) carried as round-trip metadata; the existing `start_at` semantic continues to mean "when the reminder fires" (Model A — backward-compatible with all existing `reminders.json` entries and the S-06 add path).

This is the next slice of roadmap Stream B (custom reminders), inserted as **S-06b** between the freshly-shipped S-06 (`reminders-add-form`) and the still-pending S-07 (`reminders-edit-delete`). No ID shifts; S-07 / S-08 keep their numbers and prerequisites.

## Current State Analysis

- **`Reminder` dataclass** (`break_reminder/storage/reminders.py:27-61`) is a five-field record: `name`, `start_at`, `rrule_str=None`, `end_at=None`, `id` (auto-generated). `start_at` is the **firing time** — when the popup appears — not the event time. `to_dict()` (`:37-42`) emits the field set verbatim via `dataclasses.asdict`; `from_dict()` (`:44-61`) reconstructs with explicit per-field reads, using `data.get("rrule_str")` / `data.get("end_at")` to tolerate missing keys. **No new storage code needed beyond a single field + backward-compat read.**
- **`ReminderFormDialog.accept()`** (`break_reminder/ui/reminder_form_dialog.py:271-349`) currently treats the datetime widget as `fire_at`: reads naive local → converts to tz-aware UTC → validates `fire_at_utc > self._clock()` → constructs `Reminder(name=..., start_at=fire_at_utc)`. The validation message `_PAST_TIME_MESSAGE = "Time must be in the future"` (`:91`) is a module-level constant. The form layout uses a `QFormLayout` (`:218-220`) with two rows; adding a third row is a one-line addition.
- **`_compose_row`** (`break_reminder/ui/settings_dialog.py:268-287`) is the only row-building function and is pure (`Reminder` + `datetime` + optional `tzinfo` → `str`). It calls `_format_firing(next_firing_after(reminder, now), tz=tz)` to render the time half of `"<name>  —  <next firing>"`. Adding a `(fires N min before)` suffix is one branch on `reminder.lead_minutes > 0`. The function is exercised by `TestComposeRow` in `tests/test_settings_dialog.py` (search to confirm).
- **Validation pattern is established and uniform.** The form uses `QToolTip.showText` anchored to the failing field's `mapToGlobal(...)` via `_show_tooltip` (`:258-269`). Don't introduce `QMessageBox`; don't change the gating order (name first, datetime second, then OSError-on-save).
- **JSON backward-compat is built-in.** `Reminder.from_dict` uses `data.get(...)` for optional fields; adding `lead_minutes` as `data.get("lead_minutes", 0)` matches the existing pattern. Existing `reminders.json` files without the key load with `lead_minutes=0` — same firing behavior as today.
- **Scheduler unchanged.** `ReminderScheduler.reload()` arms on `start_at` (via `next_firing_after`). Because Model A keeps `start_at` = firing time, the scheduler needs **no changes** — it continues to fire at the same instant whether `lead_minutes` is 0 or 60.
- **Roadmap convention for sub-slices.** Existing roadmap entries are S-01 through S-08 with no sub-letters. Adding `S-06b` introduces a new convention. The historical pattern for inserting between existing IDs (rather than shifting) is the right call here — shifting would invalidate every reference to S-07 / S-08 in archived plan files, change.md files, commit messages, and the foundation docs.

## Desired End State

The Add Reminder form gains a working lead-time spinbox:

1. **A new `QSpinBox` row** labelled "Notify (minutes before event):" appears between the "Date/time:" row and the OK/Cancel button box. Range 0-60, single-step 1, default 0, suffix " min".
2. **When `lead_minutes == 0`** (the default), the form behaves identically to S-06: the datetime field IS the firing time; `start_at` saved as `event_at` (no offset); validation rejects past `start_at` with "Event must be in the future"; the list row renders unchanged.
3. **When `lead_minutes > 0`**, the form interprets the datetime field as the **event time**:
   - Computes `start_at = event_at - timedelta(minutes=lead_minutes)` at save.
   - Validates `start_at > now()` (equivalent to "event_at > now + lead_minutes"); rejection tooltip reads "Event must be at least N minutes in the future" where N is the current spinbox value.
   - Saves `Reminder(name=..., start_at=start_at, lead_minutes=lead_minutes)`.
   - List row renders as `"<name>  —  <event time>  (fires N min before)"` instead of just `"<name>  —  <firing time>"`. The displayed time switches from `start_at` to `event_at = start_at + timedelta(minutes=lead_minutes)`.
4. **Backward compatibility**: existing `reminders.json` files load with `lead_minutes=0`. Existing list rows render unchanged. Existing scheduler firings unchanged.
5. **`roadmap.md`** gains a new S-06b row in "At a glance", a new `### S-06b` body block between `### S-06` and `### S-07`, and a new Backlog Handoff row. S-07 / S-08 IDs and prerequisites unchanged.
6. **`change.md`** flips to `status: implemented` after Phase 2.

### Verification:

- `uv run pytest tests/test_reminders.py` passes — extended with cases for round-trip (`lead_minutes=0` default; `lead_minutes=15` non-default), backward-compat load (JSON missing `lead_minutes` key → 0).
- `uv run pytest tests/test_reminder_form_dialog.py` passes — extended with cases for spinbox default 0, spinbox value persisted into the saved `Reminder`, computed `start_at = event_at - lead`, validation tooltip wording flips based on lead, atomic-save tripwire still holds with the new field, OSError gate still works with non-zero lead.
- `uv run pytest tests/test_settings_dialog.py` passes — extended with a `_compose_row` case for `lead_minutes > 0` asserting the `(fires N min before)` suffix and the displayed-time switch from `start_at` to `event_at`.
- `uv run pyright`, `uv run ruff check`, `uv run ruff format --check`, `uv run pip-audit`, `uv run pip-licenses --fail-on="AGPL"` all green.
- Real Windows session: add a "Test" reminder with event = now + 3 min and lead = 2 min; row shows "(fires 2 min before)" with the event time; popup fires at now + 1 min (the firing time = event - lead).

### Key Discoveries:

- **`Reminder.from_dict` already tolerates missing optional keys** (`storage/reminders.py:55-61`). Adding `lead_minutes` follows the existing `data.get(key)` / `data.get(key, default)` pattern. No schema-version bump needed.
- **`_compose_row` is the single row-builder** (`ui/settings_dialog.py:268-287`). Both the populated and empty-state list paths flow through it. Updating it is the only display change needed — `_format_firing` (`:209-232`) doesn't need to know about `lead_minutes`.
- **Validation uses `start_at > now()` regardless of lead.** Whether the user-visible reasoning is "event in the future" or "fire time in the future", the predicate is the same (`event - lead > now` is equivalent to `start_at > now` since `start_at = event - lead`). Only the tooltip wording differs based on `lead_minutes`.
- **Storage Model A keeps the scheduler invariant.** `ReminderScheduler` arms on `start_at`; because Model A defines `start_at` as the firing time, the scheduler needs no changes and no tests. The risk surface that S-06 carried (scheduler-arm correctness) does not re-appear in this slice.

## What We're NOT Doing

- ~~**No popup-text change.**~~ **Scope addendum (mid-Phase-1):** the user smoke-tested Phase 1 and asked the popup body text to switch from the static "This is a scheduled reminder." to "Time of event is <ddd HH:mm>" so the popup itself tells you what the lead-time you configured was pointing at. This was originally out of scope; mid-flow we re-scoped it INTO Phase 1 (see Phase 1 § Change Site #8). The signal payload of `ReminderScheduler.reminder_due` widened from `Signal(str)` to `Signal(str, datetime)` to carry `event_at` alongside the name; `_on_reminder_due` and `ReminderDialog.__init__` grew matching `event_at` parameters; a new `tests/test_reminder_dialog.py` pins the body wording.
- **No Edit / Delete wiring.** S-07 owns those. The new `lead_minutes` field is recoverable from a saved `Reminder` (event_at = start_at + lead_minutes), so S-07's Edit form can faithfully roundtrip both fields — but actually wiring that is S-07's job.
- **No recurrence interaction.** S-08 owns the RRULE editor. When recurrence ships, `lead_minutes` should apply uniformly to every occurrence (fire N min before each event in the series). That's a one-line shift in the scheduler's per-occurrence firing computation, but it's a future slice's contract — S-06b touches only the single-shot path.
- **No `lead_seconds` precision.** The spinbox is minutes-only. The persona's archetypal use cases ("remind me 15 min before the dentist") are minute-resolution; second precision adds spinbox-UX complexity for negligible value.
- **No range expansion beyond 60 minutes.** "Notify 2 hours before my flight" is out of scope for this slice. A future enhancement can lift the cap to 180 or 1440 minutes once we have signal from real usage.
- **No model change.** Model A (start_at = firing time, lead_minutes = metadata) was chosen over Model B (start_at = event time, fire_at = derived) for this slice. If S-07's Edit UX exposes pain from this choice, revisit then — Model B is a one-slice migration.

## Implementation Approach

Six well-scoped change sites, all in the lower-risk "extend existing pattern" category:

1. **Storage**: add one field to `Reminder` + thread through `to_dict` / `from_dict` with `data.get("lead_minutes", 0)` for backward compat.
2. **Form dialog**: insert one `QSpinBox` row, read its value in `accept()`, compute `start_at = event_at - lead`, tighten the tooltip wording.
3. **List display**: branch `_compose_row` on `reminder.lead_minutes > 0`.
4. **Tests** across three files: storage round-trip + backward-compat, form spinbox behavior + computed save + tooltip + tripwire, row format with annotation.
5. **Roadmap bookkeeping**: insert S-06b row + body block + backlog handoff entry.
6. **No app.py / scheduler.py change** — Model A's scheduler invariance is the whole point.

Phase 1 lands the full implementation + automated verification + manual smoke. Phase 2 is bookkeeping only (status flip + roadmap + plan.md progress write-back), mirroring the S-06 ritual.

## Critical Implementation Details

### Tooltip wording switch in `accept()`

The wording flip is the only non-obvious piece — the predicate is the same in both branches. Pseudocode for the validation step:

```python
lead_minutes = self._lead_minutes_field.value()
start_at_utc = event_at_utc - timedelta(minutes=lead_minutes)
if start_at_utc <= self._clock():
    msg = (
        f"Event must be at least {lead_minutes} minutes in the future"
        if lead_minutes > 0
        else "Event must be in the future"
    )
    self._show_tooltip(self._datetime_field, msg)
    return
```

The two existing string constants (`_PAST_TIME_MESSAGE = "Time must be in the future"` at `reminder_form_dialog.py:91`) **must be updated** — the new wording switches "Time" to "Event" even in the zero-lead case, because the datetime field now consistently means "event time" regardless of lead. Update the constant; do not introduce a parallel "zero-lead message" constant. The test extension assertion targets the new wording.

### `_compose_row` annotation displays event_at, not start_at

When `lead_minutes > 0`, the displayed time changes from `start_at` (firing) to `event_at = start_at + timedelta(minutes=lead_minutes)`. The user is interested in **when the thing happens**, not when the popup will appear — the annotation provides the secondary "fires N min before" info. Pseudocode:

```python
def _compose_row(reminder, now, *, tz=None):
    fire_at = next_firing_after(reminder, now)
    if fire_at is None:
        return f"{reminder.name}  —  {_format_firing(None, tz=tz)}"
    if reminder.lead_minutes > 0:
        event_at = fire_at + timedelta(minutes=reminder.lead_minutes)
        return (
            f"{reminder.name}  —  {_format_firing(event_at, tz=tz)}"
            f"  (fires {reminder.lead_minutes} min before)"
        )
    return f"{reminder.name}  —  {_format_firing(fire_at, tz=tz)}"
```

The expired branch (fire_at is None) must NOT show the "fires N min before" suffix — once expired, the annotation is misleading (it didn't fire; it expired). The test must pin this.

---

## Phase 1: Implementation + automated verification + manual smoke

### Overview

Add the `lead_minutes` field end-to-end (storage → form → list display), thread it through three test files, and bookkeep the roadmap insertion. Single phase because the change set is small enough that splitting "storage first, UI second" would create a non-shippable intermediate state and a redundant test pass.

### Changes Required:

#### 1. `Reminder` dataclass — add `lead_minutes` field

**File**: `break_reminder/storage/reminders.py`

**Intent**: Add a new optional integer field (default 0) to record the user's "notify N min before event" preference as round-trip metadata. Backward-compatible: existing `reminders.json` entries lacking the key load with `lead_minutes=0`, producing identical firing behavior.

**Contract**:
- Add `lead_minutes: int = 0` to the `@dataclass Reminder` (`storage/reminders.py:27-35`). Place it **before** `id` (which has a `default_factory` and must remain last for dataclass field-ordering rules) and **after** `end_at`. The field order becomes: `name, start_at, rrule_str=None, end_at=None, lead_minutes=0, id=field(...)`.
- `to_dict()` already serializes every dataclass field via `asdict` — adding the field auto-includes it in the dict. No code change needed in `to_dict()`.
- `from_dict()` (`storage/reminders.py:44-61`) gets one new constructor arg: `lead_minutes=data.get("lead_minutes", 0)`. The `.get(..., 0)` form is load-bearing for backward compat with existing files.
- Update the `from_dict` docstring's `Args:` block to mention the new optional `lead_minutes` key. Keep the existing wording style.

#### 2. `ReminderFormDialog` — spinbox + validation + save computation

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Insert a third form row for the lead-minute spinbox, read it in `accept()`, compute `start_at = event_at - lead`, and switch the past-time tooltip wording based on lead.

**Contract**:
- Add `QSpinBox` to the `PySide6.QtWidgets` import block.
- Add three module-level constants near `_DEFAULT_OFFSET_HOURS` / `_DEFAULT_ROUND_MINUTES`:
  - `_LEAD_MIN_VALUE = 0`
  - `_LEAD_MAX_VALUE = 60`
  - `_LEAD_DEFAULT = 0`
  - `_LEAD_SUFFIX = " min"`
- Update `_PAST_TIME_MESSAGE = "Time must be in the future"` → `_PAST_TIME_MESSAGE = "Event must be in the future"` (lead=0 case).
- Add `_PAST_TIME_WITH_LEAD_FORMAT = "Event must be at least {lead} minutes in the future"` (lead>0 case).
- In `__init__` (`reminder_form_dialog.py:172-233`):
  - After `self._datetime_field.setDateTime(...)` and before `form = QFormLayout()`, construct `self._lead_minutes_field = QSpinBox(self)` with `setRange(_LEAD_MIN_VALUE, _LEAD_MAX_VALUE)`, `setSingleStep(1)`, `setSuffix(_LEAD_SUFFIX)`, `setValue(_LEAD_DEFAULT)`.
  - Add `form.addRow("Notify (minutes before event):", self._lead_minutes_field)` immediately after the existing `form.addRow("Date/time:", self._datetime_field)` line.
- In `accept()` (`reminder_form_dialog.py:271-349`):
  - After step 2's `fire_at_utc = naive_local.replace(...).astimezone(UTC)`, treat `fire_at_utc` as `event_at_utc` (the user picked the event time when lead > 0; equivalent when lead == 0).
  - Read `lead_minutes = self._lead_minutes_field.value()`.
  - Compute `start_at_utc = event_at_utc - timedelta(minutes=lead_minutes)`.
  - Replace the current `if fire_at_utc <= self._clock(): ... _PAST_TIME_MESSAGE ...` block with a `start_at_utc <= self._clock()` check that chooses between `_PAST_TIME_MESSAGE` (lead=0) and `_PAST_TIME_WITH_LEAD_FORMAT.format(lead=lead_minutes)` (lead>0).
  - Update step 3's `Reminder(name=stripped_name, start_at=fire_at_utc)` → `Reminder(name=stripped_name, start_at=start_at_utc, lead_minutes=lead_minutes)`.
- Update the class and `accept()` docstrings to reflect: datetime widget = event time; `start_at = event - lead`; lead is round-trip metadata.

#### 3. `_compose_row` — lead-time annotation

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: When `reminder.lead_minutes > 0` and the reminder is not expired, show the event time (not the firing time) with a "(fires N min before)" suffix. Expired and zero-lead rows render unchanged.

**Contract**:
- Import `timedelta` from `datetime` at module top if not already imported (it is — verify).
- Update `_compose_row` (`settings_dialog.py:268-287`) per the Critical Implementation Details pseudocode above.
- Update the docstring to document the lead-time annotation branch and the expired-row exception.

#### 4. Tests — storage round-trip + backward compat

**File**: `tests/test_reminders.py`

**Intent**: Pin the new field's JSON behavior across three cases: serialize with default lead, serialize with non-default lead, deserialize a dict missing the key.

**Contract**:
- Add `TestReminderLeadMinutes` (or extend the existing dataclass-roundtrip test class) with three tests:
  - `test_default_lead_minutes_is_zero`: construct `Reminder(name=..., start_at=...)`; assert `.lead_minutes == 0`.
  - `test_to_dict_roundtrip_preserves_lead_minutes`: construct with `lead_minutes=15`; `to_dict()` → `from_dict()`; assert preserved.
  - `test_from_dict_missing_key_defaults_to_zero`: build a dict without a `lead_minutes` key (mimicking a pre-S-06b file); `Reminder.from_dict(d)` → assert `.lead_minutes == 0`.
- If `tests/test_reminders.py` doesn't exist yet, create it (the existing reminders tests may live in `tests/test_reminder_*.py` only — check first; if absent, create a new module mirroring `tests/test_settings.py`'s structure).

#### 5. Tests — form spinbox behavior

**File**: `tests/test_reminder_form_dialog.py`

**Intent**: Pin the spinbox default, its persistence into the saved `Reminder`, the `start_at = event - lead` computation, the tooltip wording switch, and that the atomic-save tripwire from S-06 still holds with the new field.

**Contract**:
- Add `TestReminderFormDialogLeadMinutes` with at minimum these cases:
  - `test_spinbox_defaults_to_zero`: open dialog; assert `dialog._lead_minutes_field.value() == 0`.
  - `test_save_with_lead_zero_unchanged_from_s06`: existing S-06 path still works; saved `Reminder.lead_minutes == 0` and `start_at == event_at` (no offset applied).
  - `test_save_with_lead_nonzero_computes_start_at_from_event`: set lead = 10; pick event = now + 30 min; assert saved `Reminder.start_at == event_at - timedelta(minutes=10)` and `Reminder.lead_minutes == 10`.
  - `test_past_event_with_lead_zero_shows_event_in_future_tooltip`: lead = 0, event in past; monkeypatch `QToolTip.showText`; assert message == "Event must be in the future".
  - `test_past_event_with_lead_nonzero_shows_lead_specific_tooltip`: lead = 15, event = now + 5 min (so start_at = now - 10 min); assert message == "Event must be at least 15 minutes in the future".
  - `test_atomic_save_tripwire_holds_with_nonzero_lead`: validation failure with lead > 0 must not write to the store. Stub the store's `add` to track calls; trigger the past-time gate with lead = 15; assert `add` never called.
  - `test_signal_emits_with_lead_minutes_field_populated`: connected slot receives the `Reminder` with `lead_minutes == 15`.

#### 6. Tests — list display annotation

**File**: `tests/test_settings_dialog.py`

**Intent**: Pin `_compose_row`'s new annotation branch; pin that expired rows do NOT get the annotation; pin that zero-lead rows render exactly as today.

**Contract**:
- Extend the existing `TestComposeRow` (or equivalent) class with three tests:
  - `test_compose_row_with_lead_zero_unchanged`: existing assertion (no annotation, time = start_at).
  - `test_compose_row_with_lead_nonzero_shows_annotation_and_event_time`: build a `Reminder` with `start_at = some_utc` and `lead_minutes = 20`; pass a known `now` and `tz`; assert the formatted string contains `"(fires 20 min before)"` AND the displayed time matches `start_at + timedelta(minutes=20)` (the event time), NOT `start_at`.
  - `test_compose_row_expired_with_lead_nonzero_omits_annotation`: build an expired reminder (`start_at` far in the past; `next_firing_after` returns None) with `lead_minutes = 20`; assert the row is exactly `"<name>  —  (expired)"` with NO "fires" suffix.

#### 8. Popup body text — show event time (scope addendum)

**Files**: `break_reminder/notifications/reminder_dialog.py`, `break_reminder/scheduler.py`, `break_reminder/app.py`, `tests/test_reminder_scheduler.py`, `tests/test_reminder_dialog.py` (NEW)

**Intent**: Replace the static `"This is a scheduled reminder."` body label with `"Time of event is <ddd HH:mm>"` (e.g., `"Time of event is Wed 14:30"`) so the popup tells the user what their configured lead time was pointing at — without them having to remember it. Applies uniformly to `lead_minutes == 0` (where event == firing == now) and `lead_minutes > 0` (where event is up to 60 min after the popup fires).

**Contract**:
- `ReminderDialog.__init__` gains a required `event_at: datetime` kwarg and an optional `tz: tzinfo | None = None` kwarg. The body label is constructed via a new module-level `_format_body(event_at, tz=tz)` helper that wraps `event_at.astimezone(tz).strftime("%a %H:%M")` inside `"Time of event is {event}"`.
- New module-level constants in `reminder_dialog.py`: `_BODY_TIME_FORMAT = "%a %H:%M"` and `_BODY_FORMAT = "Time of event is {event}"`. Tests import them so a wording-format regression is loud and obvious.
- `ReminderScheduler.reminder_due` widens from `Signal(str)` to `Signal(str, datetime)`. `_fire()` emits `(reminder.name, self._next.fire_at + timedelta(minutes=reminder.lead_minutes))`. Using `self._next.fire_at` (not `reminder.start_at`) is forward-compatible with S-08 recurring reminders where the next occurrence ≠ the series start.
- `BreakReminderApp._on_reminder_due` slot signature widens from `(self, name: str)` to `(self, name: str, event_at: datetime)`. The slot passes `event_at` through to `ReminderDialog(name=name, event_at=event_at)`.
- `app.py` gains `from datetime import datetime` at the import block.
- `tests/test_reminder_scheduler.py::TestReminderDueSignal::test_on_timer_fires_when_clock_caught_up` is updated to assert the 2-tuple payload `(name, event_at)`; a new sibling test `test_on_timer_fires_with_event_at_offset_by_lead_minutes` pins that non-zero lead shifts `event_at` correctly.
- `tests/test_reminder_dialog.py` is created (NEW) with: 5 `_format_body` cases (zone conversion, system-local default, minute zero-padding, day-of-week rollover, short day-name format) and 4 `ReminderDialog` constructor cases (window title, stays-on-top flag, body label content, OK-only button box).

#### 7. Roadmap — insert S-06b

**File**: `context/foundation/roadmap.md`

**Intent**: Insert the new slice between S-06 and S-07 in three places (At-a-glance table, body blocks, Backlog Handoff table) without shifting any existing IDs. The new ID is `S-06b`; rationale matches the historical norm (don't break references in archived plans / commit messages).

**Contract**:
- In the "At a glance" table (around line 37-39), insert a new row between S-06 and S-07: `| S-06b | reminders-lead-time | configure a reminder to fire N minutes before the event | S-06 | FR-011, FR-013 | proposed |`. Status will flip to `done` in Phase 2.
- In the body blocks (between `### S-06` and `### S-07`, around line 159), insert a new `### S-06b: reminders-lead-time` block with the same field set the other entries use: Outcome, Change ID, PRD refs, Prerequisites (S-06), Parallel with (S-02, S-03, S-04, S-07, S-08), Blockers (—), Unknowns (—), Risk (low — single field on `Reminder`, single spinbox on the form, single branch in `_compose_row`), Status (proposed; flips to done in Phase 2).
- In the Backlog Handoff table (around line 193-195), insert a new row between S-06 and S-07: `| S-06b | reminders-lead-time | Add "notify N min before event" lead-time spinbox to the add form | no | Run after S-06 |`. Phase 2 flips the `no` to `yes | Planned + shipped 2026-05-27`.
- In the Streams section (around line 48), update Stream B's chain notation from `S-05 → S-06 → S-07 / S-08` to `S-05 → S-06 → S-06b / S-07 / S-08 (parallel after S-06)` — S-06b is parallel with S-07/S-08, not their prerequisite (both S-07 and S-08 list `Prerequisites: S-06` in their body blocks).

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_reminders.py -v`
- Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v`
- Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v`
- Full suite passes: `uv run pytest`
- Type check passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Format check passes: `uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual Verification:

- Lead-minutes spinbox appears in the Add Reminder form between Date/time and the button box; default value is 0 with " min" suffix; range 0-60 with single-step 1.
- Save with lead=0 still works exactly like S-06 (firing time = datetime widget value).
- Save with lead=15: pick event ~30s out; popup fires ~15s ahead of the event time (i.e., immediately if event is < 15s away — the past-time guard rejects in that case).
- Past-event tooltip: with lead=0, "Event must be in the future"; with lead=15 and event < 15 min away, "Event must be at least 15 minutes in the future".
- Cancel still works with no side effects (no reminder saved, no scheduler reload).
- List row with lead=0 renders unchanged: `"<name>  —  <firing time>"`.
- List row with lead=20 renders: `"<name>  —  <event time>  (fires 20 min before)"`.
- Expired list row with lead=20 renders without the annotation: `"<name>  —  (expired)"`.
- `reminders.json` in Notepad after a lead>0 save shows a `"lead_minutes": <N>` field next to `start_at`; the file remains well-formed JSON.
- No regression in Scheduling / Notifications / Lifecycle tabs.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual smoke run succeeded before proceeding to Phase 2.

---

## Phase 2: Bookkeeping

### Overview

Lock in the docs: flip `change.md` to `implemented`, flip the S-06b roadmap entries from `proposed` to `done` (table row + body block + backlog handoff), and tick every Phase 1 / Phase 2 Progress row with the appropriate commit SHA. No code changes.

### Changes Required:

#### 1. `change.md` — flip status

**File**: `context/changes/reminders-lead-time/change.md`

**Intent**: Move the slice from "planned/implementing" to "implemented" once Phase 1's manual smoke passes.

**Contract**: Front-matter `status: planned` (or whatever Phase 1 left it as) → `status: implemented`. Refresh `updated:` to today.

#### 2. `roadmap.md` — flip S-06b to done

**File**: `context/foundation/roadmap.md`

**Intent**: Mirror the S-06 bookkeeping pattern (commit `beba743` for S-06; commit `b19628a` for S-05): flip the table row status, flip the body-block status, and update the Backlog Handoff entry.

**Contract**: Three substitutions:
1. At-a-glance table: `| S-06b | reminders-lead-time | ... | proposed |` → `| S-06b | reminders-lead-time | ... | done |`.
2. `### S-06b` body block: `**Status:** proposed` → `**Status:** done`.
3. Backlog Handoff row: `| S-06b | reminders-lead-time | ... | no | Run after S-06 |` → `| S-06b | reminders-lead-time | ... | yes | Planned + shipped 2026-05-27 |`.

The `## Done` entry insertion is **deferred to archive time** per the established convention (S-05 / S-06 historical pattern). This Phase 2 commit does NOT add a Done entry; `/10x-archive` will add one when it moves the change folder.

#### 3. Tick the Progress section

**File**: `context/changes/reminders-lead-time/plan.md`

**Intent**: Flip every Phase 1 + Phase 2 Progress row to `[x]` and annotate each with the commit SHA per `references/progress-format.md`. Phase 1 rows get the Phase 1 SHA; Phase 2 rows get the Phase 2 SHA (which can't reference itself — the SHA write-back lands in an epilogue commit, mirroring S-06's `4668903` pattern).

**Contract**: Mechanical `[ ]` → `[x] — <sha>` substitutions across the Progress section below. The epilogue commit also flips the Phase 2 SHA into the Phase 2 Progress rows.

### Success Criteria:

#### Automated Verification:

- `git grep -nE '^\| S-06b .*proposed' context/foundation/roadmap.md` returns no matches (status flipped). Use the row-anchored pattern (not just `S-06b.*proposed`) to avoid false matches.
- `git diff context/changes/reminders-lead-time/change.md` shows `status: implemented` and an updated `updated:` date.

#### Manual Verification:

- The Reminders tab opens to the same state as before (no behavior change from the bookkeeping commit alone).
- No regression in any tab.

**Implementation Note**: After completing this phase, the slice is done. The next slice in Stream B is S-07 (`reminders-edit-delete`), unblocked by S-06 (S-06b is parallel, not a prerequisite, since S-07 can ship without S-06b's lead-time and vice versa). When the user is ready, `/10x-archive` moves the folder to `context/archive/2026-05-27-reminders-lead-time/` and adds the `## Done` entry to roadmap.md.

---

## Testing Strategy

### Unit Tests:

- **Storage (`tests/test_reminders.py`).** Three new tests pin the dataclass field default, round-trip serialization, and backward-compat deserialization. Mirrors the existing dataclass-test patterns.
- **Form dialog (`tests/test_reminder_form_dialog.py`).** Seven new tests pin: spinbox default 0, zero-lead path unchanged from S-06, non-zero-lead path computes `start_at` correctly, tooltip wording flips on the past-time gate (both zero-lead and non-zero-lead variants), atomic-save tripwire still holds with non-zero lead, signal emits the new field populated.
- **List display (`tests/test_settings_dialog.py`).** Three new `_compose_row` cases pin: zero-lead unchanged, non-zero-lead shows annotation AND switches displayed time from `start_at` to `event_at`, expired-with-non-zero-lead omits the annotation.

### Integration Tests:

- **No new integration test file.** The new field is a value-passing change across three existing layers (storage → dataclass → form → display); each layer has dedicated unit tests. An end-to-end "Add with lead → row shows annotation → popup fires N min ahead" test would require a real event loop with timed waits and is best left to the manual smoke run.

### Manual Testing Steps:

1. **Spinbox visible and bounded.** Open Add form. Confirm spinbox appears, defaults to 0, suffix is " min", up-arrow lands at 1, down-arrow at 0 doesn't go below, typing 99 clamps to 60, typing -5 clamps to 0.
2. **Zero-lead regression check.** Save with lead=0; confirm a regular S-06 reminder lands (firing time = datetime widget value); list row renders unchanged.
3. **Non-zero-lead happy path.** Pick event = now + ~45s; lead = 0 first, OK, confirm popup fires at ~45s. Then add a second with event = now + 60s; lead = 30s — actually, lead is in minutes, so use event = now + 90s; lead = 1 min; OK; confirm popup fires at ~30s (event - 1 min).
4. **Past-time gates fire with correct wording.** Lead=0, event in past → "Event must be in the future". Lead=10, event = now + 5 min → "Event must be at least 10 minutes in the future".
5. **List annotation correctness.** With at least one zero-lead and one non-zero-lead reminder in the store, open the Reminders tab; confirm the zero-lead row has no "(fires N min before)" suffix, the non-zero-lead row does, and the non-zero-lead row's displayed time matches the event time (not the firing time).
6. **JSON file inspection.** Open `%APPDATA%\BreakReminder\reminders.json` in Notepad; confirm a `"lead_minutes": <N>` field appears next to `"start_at"`; confirm the file is still well-formed JSON.
7. **Backward-compat load.** Before installing this build: note a reminder created on the S-06 build (no `lead_minutes` key in the JSON). After installing this build: confirm the app loads the file without error and the row renders unchanged (lead defaults to 0).

## Performance Considerations

- **Spinbox is a native widget**; no perf concern.
- **`_compose_row`'s new branch** is one timedelta addition + one f-string; negligible vs the existing `next_firing_after` call.
- **JSON file size**: each reminder gains ~22 bytes (`"lead_minutes": 0,\n  `). For the persona's expected ≤ 10 reminders, this is < 250 bytes total. Irrelevant.

## Migration Notes

- **No data migration.** `Reminder.from_dict` uses `data.get("lead_minutes", 0)`; existing files load unchanged.
- **No setting migration.** No new `Settings` keys.
- **No installer / PyInstaller change.** Same release pipeline.
- **No scheduler change.** Existing reminders fire at the same instant on this build as on the S-06 build.

## References

- Roadmap entry (to be inserted): `context/foundation/roadmap.md` § S-06b
- PRD: `context/foundation/prd.md` FR-011 (line 123), FR-013 (line 127)
- Predecessor slice plan: `context/changes/reminders-add-form/plan.md` (S-06; shipped 2026-05-27 as `33a665f` + `beba743` + `4668903`)
- Form dialog: `break_reminder/ui/reminder_form_dialog.py:148-349`
- Reminder dataclass: `break_reminder/storage/reminders.py:27-61`
- `_compose_row`: `break_reminder/ui/settings_dialog.py:268-287`
- AGENTS.md threading rules (no change needed): `AGENTS.md` § Threading rules

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Implementation + automated verification + manual smoke

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_reminders.py -v` — d99f122
- [x] 1.2 Unit tests pass: `uv run pytest tests/test_reminder_form_dialog.py -v` (extended with `TestReminderFormDialogLeadMinutes`) — d99f122
- [x] 1.3 Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (extended `TestComposeRow` cases) — d99f122
- [x] 1.4 Full suite passes: `uv run pytest` — d99f122
- [x] 1.5 Type check passes: `uv run pyright` — d99f122
- [x] 1.6 Linting passes: `uv run ruff check` — d99f122
- [x] 1.7 Format check passes: `uv run ruff format --check` — d99f122
- [x] 1.8 Security audit passes: `uv run pip-audit` — d99f122
- [x] 1.9 License gate passes: `uv run pip-licenses --fail-on="AGPL"` — d99f122
- [x] 1.1a Unit tests pass: `uv run pytest tests/test_reminder_scheduler.py -v` (extended with the lead-time `event_at` payload test) — d99f122
- [x] 1.1b Unit tests pass: `uv run pytest tests/test_reminder_dialog.py -v` (NEW file; pins `_format_body` + `ReminderDialog` constructor wiring) — d99f122

#### Manual

- [x] 1.10 Spinbox visible: range 0-60, step 1, default 0, suffix " min" — d99f122
- [x] 1.11 Zero-lead save behaves identically to S-06 (no regression) — d99f122
- [x] 1.12 Non-zero-lead save: popup fires at (event - lead), not at event — d99f122
- [x] 1.13 Past-time tooltip wording correct in both zero-lead and non-zero-lead cases — d99f122
- [x] 1.14 List row with lead>0 shows event time + "(fires N min before)" suffix — d99f122
- [x] 1.15 List row with lead=0 renders unchanged from S-06 — d99f122
- [x] 1.16 Expired row with lead>0 shows "(expired)" without the "fires" suffix — d99f122
- [x] 1.17 `reminders.json` in Notepad shows `"lead_minutes": <N>` field; file is well-formed JSON — d99f122
- [x] 1.18 Backward-compat: a pre-S-06b reminders.json loads cleanly (lead defaults to 0) — d99f122
- [x] 1.19 No regression in Scheduling / Notifications / Lifecycle tabs — d99f122
- [x] 1.20 Popup body for a `lead=0` fire reads `"Time of event is <ddd HH:mm>"` (HH:mm ≈ now) — d99f122
- [x] 1.21 Popup body for a `lead>0` fire reads `"Time of event is <ddd HH:mm>"` where HH:mm = event time (later than now) — d99f122

### Phase 2: Bookkeeping

#### Automated

- [x] 2.1 `git grep -nE '^\| S-06b .*proposed' context/foundation/roadmap.md` returns no matches
- [x] 2.2 `git diff context/changes/reminders-lead-time/change.md` shows `status: implemented` and updated `updated:` date

#### Manual

- [x] 2.3 Reminders tab still functional after the bookkeeping commit (smoke check)
- [x] 2.4 No regression in any tab
