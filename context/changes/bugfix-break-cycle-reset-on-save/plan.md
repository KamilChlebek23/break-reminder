# Break-cycle reset on settings save (S-09) Implementation Plan

## Overview

When the user saves a new break interval from the Scheduling tab of `SettingsDialog`, `BreakScheduler._active_seconds` is not reset, leaving the tray-tooltip countdown showing a stale sub-minute offset and the next break firing up to 59 seconds early or late relative to the new threshold. This plan adds a `BreakScheduler.reset_cycle()` primitive (mirroring the existing `on_break_taken()` body), has `SettingsDialog` emit a new `break_interval_changed(int)` signal in `accept()` only when the persisted value actually differs from the loaded one, and wires that signal in `BreakReminderApp._on_open_settings()` to a slot that calls `reset_cycle()` + `_refresh_tooltip()`. Tests pin the reset payload, the conditional emission, and the end-to-end path.

## Current State Analysis

- **The bug.** [break_reminder/scheduler.py](break_reminder/scheduler.py) `BreakScheduler._active_seconds` is reset only in three places: construction (`__init__`, line 88), `on_break_taken()` (line 162-166), and `on_break_snoozed()` (line 174 — set to threshold, not zero). Settings writes do not flow through any of them.
- **The math behind the symptom.** `seconds_until_break` (line 117-118) computes `max(0, threshold − self._active_seconds)` where `threshold = self._settings.break_interval_min * 60`. For any pair (old, new) of break intervals, both thresholds are multiples of 60, so `(threshold − _active_seconds) % 60` reduces to `(−_active_seconds) % 60` — independent of the threshold. The tray tooltip's seconds digit therefore appears frozen across an interval change.
- **The single write-path.** [break_reminder/ui/settings_dialog.py](break_reminder/ui/settings_dialog.py) `SettingsDialog.accept()` (line 1183-1281) is the only place `Settings.break_interval_min` is written from the GUI. It currently emits no signal and has no awareness of either scheduler. Compare with the `ReminderFormDialog.reminder_added` / `reminder_updated` signal pattern wired through `SettingsDialog._on_reminders_add_clicked` / `_on_reminders_edit_clicked` to refresh the Reminders tab — the same shape works for the new path, just one level higher.
- **App-level wiring precedent.** [break_reminder/app.py](break_reminder/app.py) `_apply_break_taken` (lines 413-427) is the model for an app-level slot that mutates the scheduler and then refreshes the tooltip in the same step. The new slot is simpler — no event-log row, no scheduler.start() (the per-second tick is already running) — but the shape (`scheduler.<reset>(); self._refresh_tooltip()`) is the same.
- **Test conventions.** [tests/test_break_scheduler.py](tests/test_break_scheduler.py) `TestOnBreakTaken` (lines 425-468) pins the existing reset semantics on three observable assertions (`_active_seconds == 0`, `_snoozes_used == 0`, `_snooze_until is None`) plus a "second cycle starts fresh" integration assertion. The new `TestResetCycle` mirrors those four assertions verbatim. [tests/test_app.py](tests/test_app.py) `TestApplyBreakTaken` (lines 98-167) demonstrates the app-level slot test pattern; the new `TestOnBreakIntervalChanged` mirrors it. [tests/test_settings_dialog.py](tests/test_settings_dialog.py) does not yet contain any signal-emission tests because today's `SettingsDialog` emits no signals — this slice introduces the first.
- **No `Settings`-layer change needed.** `Settings.break_interval_min` is a getter/setter pair (`break_reminder/storage/settings.py`) with widget-bounded values; the dialog already validates inputs upstream. The reset-on-save logic lives entirely in the dialog and the scheduler.
- **Lessons.md prior.** [context/foundation/lessons.md](context/foundation/lessons.md) has one rule today: every public Python function gets a Google-style docstring. The new `reset_cycle()` method and `_on_break_interval_changed` slot are public-API additions and need docstrings.

## Desired End State

When the user opens Settings, changes only the break interval (e.g., 5 → 7 minutes), and clicks OK, the tray tooltip immediately re-reads as `BreakReminder — next break in 7m 00s` (then ticks down on the next 5-second `_tooltip_timer` refresh), regardless of how far through the prior cycle they were at Save time. The next break fires exactly `7 × 60` active seconds after that moment. Changing snooze duration or max snoozes alone (without touching the break interval) does NOT reset the cycle — the prior accumulator is preserved and the countdown continues from where it was. Snooze-in-flight at Save time gets cleared (`_snooze_until = None`, `_snoozes_used = 0`) when (and only when) the break interval changed.

### Key Discoveries:

- The reset payload exactly matches `on_break_taken()`'s — refactoring `on_break_taken` to delegate to a new `reset_cycle()` is a zero-behavior-change extraction. Pinned by the existing `TestOnBreakTaken` continuing to pass.
- `SettingsDialog.accept()` reads the OLD `break_interval_min` from `self._settings` for free until the very moment it writes the new one (line 1275). No extra `__init__`-time capture is needed; capture the old value as a local variable just before the writes.
- The signal must be emitted BEFORE `super().accept()` so the slot runs while the dialog is still "open" (`result()` still `Rejected`). This mirrors the established `reminder_added` ordering documented in [tests/test_reminder_form_dialog.py](tests/test_reminder_form_dialog.py) `test_save_emits_reminder_added_before_super_accept`.
- The wiring in `_on_open_settings` connects the signal **before** `dialog.exec()`. The connection is automatically dropped when the dialog is GC'd post-`exec()`, matching the per-open-fresh-instance pattern documented at [break_reminder/app.py:314-340](break_reminder/app.py).

## What We're NOT Doing

- **No reset on snooze-duration or max-snoozes changes.** Per design decision: the user explicitly chose "only when `break_interval_min` actually changed". A snooze-duration tweak mid-cycle continues the prior accumulator; a max-snoozes lowering doesn't clamp `_snoozes_used`. (Self-heals on next `on_break_taken()`.)
- **No new `Settings` keys.** No persistence change; the bug lives in in-memory scheduler state, not in saved config.
- **No tray-icon change.** The tooltip refresh is via the existing `_refresh_tooltip()` path; no new tray surface.
- **No event-log entry.** A break-interval change is not a `BREAK / TAKEN` event for FR-015 purposes — counting it as such would inflate the Primary Success Criterion ratio (≥80% breaks taken in 7d). The new slot deliberately does NOT call `_event_log.record(...)`.
- **No restart of the per-second tick.** Unlike `_apply_break_taken` (which calls `_break_scheduler.start()` after `break_due` stopped the timer), the timer was never stopped here — the user merely pressed OK in Settings. The new slot only resets state and refreshes the tooltip.
- **No change to AGENTS.md.** The new signal-from-`SettingsDialog` shape is structurally identical to the existing `ReminderFormDialog.reminder_added` → `SettingsDialog._refresh_reminders_tab` pattern documented in AGENTS.md "FR-004 — tray quick-menu" / FR-011/012 sections; one more dialog emitting a signal does not introduce a new load-bearing pattern. (Verified during plan write: no AGENTS.md section claims `BreakScheduler` resets on settings save.)
- **No PyInstaller / NSIS / release-workflow changes.** Pure code change.
- **No new dependencies.** Uses existing `PySide6.QtCore.Signal`.

## Implementation Approach

Single-phase code change touching three production files and three test files. Implementer's natural order is bottom-up:

1. **Extract `reset_cycle()` in `BreakScheduler`** (`break_reminder/scheduler.py`). Add the new method (body = current `on_break_taken` body), refactor `on_break_taken` to delegate via `self.reset_cycle()`. Zero behavior change to existing callers.
2. **Add the signal to `SettingsDialog`** (`break_reminder/ui/settings_dialog.py`). Class-level `break_interval_changed = Signal(int)`. In `accept()`, capture `old_interval = self._settings.break_interval_min` as a local just before the persistence block (line 1275); after the persistence block, before `super().accept()`, compare and emit when the value differs.
3. **Wire the slot in `BreakReminderApp`** (`break_reminder/app.py`). In `_on_open_settings()`, connect `dialog.break_interval_changed` to a new private slot `_on_break_interval_changed(self, new_interval: int)` BEFORE `dialog.exec()`. The slot calls `self._break_scheduler.reset_cycle()` then `self._refresh_tooltip()`.
4. **Tests, three classes.** `TestResetCycle` in `tests/test_break_scheduler.py` (mirrors `TestOnBreakTaken`'s four assertions plus an `on_break_taken still works` smoke). `TestBreakIntervalChangedSignal` in `tests/test_settings_dialog.py` (emits-on-change, no-emit-on-no-change, emits-before-super-accept, payload-is-new-value). `TestOnBreakIntervalChanged` in `tests/test_app.py` (slot resets `_active_seconds`, slot clears `_snoozes_used` and `_snooze_until`, slot triggers `_refresh_tooltip()`, end-to-end via stubbed `SettingsDialog`).

## Critical Implementation Details

- **Signal emission ordering**. The `break_interval_changed.emit(...)` call must run BEFORE `super().accept()` for the same reason `ReminderFormDialog.reminder_added.emit(...)` does (see [tests/test_reminder_form_dialog.py](tests/test_reminder_form_dialog.py) `test_save_emits_reminder_added_before_super_accept`): connected slots execute synchronously, and they must see `self.result() == Rejected` so a slot that inspects dialog state during the emission gets a coherent view. After `super().accept()` flips the result, `exec()` returns and the dialog object may be slated for destruction.

- **`_on_open_settings` must connect BEFORE `dialog.exec()`**. `exec()` blocks until the dialog closes; the signal fires inside `accept()`, which runs DURING `exec()`. Connecting after `exec()` returns is too late — the signal already fired and the dialog is mid-destruction.

## Phase 1: Implementation

### Overview

Production code change + automated test coverage for the new reset path. This phase ends with a green CI gate (pytest, pyright, ruff, pip-audit, pip-licenses) but BEFORE the manual smoke test on real Windows.

### Changes Required:

#### 1. `BreakScheduler.reset_cycle()`

**File**: `break_reminder/scheduler.py`

**Intent**: Extract the three-field reset (`_active_seconds = 0`, `_snoozes_used = 0`, `_snooze_until = None`) currently inlined in `on_break_taken()` into a public method named `reset_cycle()`. Refactor `on_break_taken()` to be a one-liner that calls `self.reset_cycle()`. Zero behavior change for existing callers; the new public method is the entry point the settings-save path uses.

**Contract**: New public method `BreakScheduler.reset_cycle(self) -> None` with a Google-style docstring explaining it returns the scheduler to a clean cycle state and naming both call sites (the dialog flow via `on_break_taken`, and the new settings-save flow). `on_break_taken` retains its existing docstring; its body becomes `self.reset_cycle()`.

#### 2. `SettingsDialog.break_interval_changed` signal

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Emit a class-level `break_interval_changed = Signal(int)` from `accept()` if and only if the value actually changed since the dialog was opened. The payload is the new (post-save) interval in minutes — observers may want to use it for logging or display refresh that doesn't require re-reading `Settings`.

**Contract**: Class-level `break_interval_changed = Signal(int)` declared near other class attributes (mirrors `reminder_added = Signal(Reminder)` placement in `ReminderFormDialog`). In `accept()`, capture `old_interval = self._settings.break_interval_min` as a local immediately BEFORE the existing `self._settings.break_interval_min = self._break_interval_spinbox.value()` write (line 1275). After all setters run and before `super().accept()`, compare `new_interval = self._break_interval_spinbox.value()` with `old_interval` and call `self.break_interval_changed.emit(new_interval)` only when they differ.

#### 3. `BreakReminderApp._on_break_interval_changed` slot + wiring

**File**: `break_reminder/app.py`

**Intent**: New private slot `_on_break_interval_changed(self, new_interval: int) -> None` that calls `self._break_scheduler.reset_cycle()` then `self._refresh_tooltip()`. In `_on_open_settings()`, capture the dialog instance, connect `dialog.break_interval_changed` to the new slot BEFORE calling `dialog.exec()`.

**Contract**: New slot signature `_on_break_interval_changed(self, new_interval: int) -> None`; the `new_interval` parameter is currently unused (the scheduler reads the new threshold via `self._settings.break_interval_min` on the next tick) but the signal carries it for future observers and tooltip-display debugging. Add a Google-style docstring naming the contract: "called when SettingsDialog persists a non-no-op break-interval change; resets the active-time accumulator and snooze state, then refreshes the tray tooltip immediately so the user sees the new countdown without waiting for the next 5-second `_tooltip_timer` tick". Modify `_on_open_settings()` to bind the dialog to a local variable, connect the signal, then `dialog.exec()`.

#### 4. `TestResetCycle` in `tests/test_break_scheduler.py`

**File**: `tests/test_break_scheduler.py`

**Intent**: Mirror the existing `TestOnBreakTaken` class (lines 425-468) for the new `reset_cycle()` method. Pin the same four contracts: resets `_active_seconds`, clears `_snoozes_used`, clears `_snooze_until`, and a "second cycle starts fresh" integration test. Add one regression test that `on_break_taken()` still works (delegates to `reset_cycle()`).

**Contract**: New test class `TestResetCycle` with at least the four mirrored tests from `TestOnBreakTaken` plus a `test_on_break_taken_delegates_to_reset_cycle` smoke. Reuses the existing `Clock` / `scheduler` fixtures from the file.

#### 5. `TestBreakIntervalChangedSignal` in `tests/test_settings_dialog.py`

**File**: `tests/test_settings_dialog.py`

**Intent**: Pin the new emit-only-on-actual-change contract for `SettingsDialog.break_interval_changed`. Cover four cases: the signal fires when the spinbox value differs from the stored value, the signal does NOT fire when the value matches, the payload is the new value (not the old), and the emission happens before `super().accept()` (i.e., during the connected slot the dialog's `result()` is still `Rejected`).

**Contract**: New test class `TestBreakIntervalChangedSignal` using a `QSignalSpy`-or-list-recorder pattern (a `signals_received: list[int]` populated by a lambda connected to `break_interval_changed`). Use the existing `dialog` / `settings` fixtures. Pinning the result-still-Rejected ordering uses the same shape as `tests/test_reminder_form_dialog.py:test_save_emits_reminder_added_before_super_accept`.

#### 6. `TestOnBreakIntervalChanged` in `tests/test_app.py`

**File**: `tests/test_app.py`

**Intent**: Pin the slot's three observable effects (active-seconds reset, snooze state cleared, tooltip refreshed) plus an end-to-end test that opening a stubbed `SettingsDialog`, mutating `break_interval_min`, and accepting actually drives the slot.

**Contract**: New test class `TestOnBreakIntervalChanged` mirroring the structure of `TestApplyBreakTaken` (lines 98-167). Tests: `test_clears_active_seconds_counter`, `test_clears_snooze_state`, `test_refreshes_tooltip_immediately`, `test_does_not_change_pause_state`, `test_does_not_record_event_log_row`, `test_end_to_end_via_settings_dialog_stub`. The end-to-end test reuses the existing `_StubSettingsDialog` pattern in `tests/test_app.py:294-320` — extend that stub with a `break_interval_changed` attribute (a small inline `_StubSignal` class exposing `.connect(slot)` that records into a `connected_slots` list). The `connected_slots` list doubles as both the wiring assertion (`TestOpenSettingsAction` can assert the slot was connected) and the manual-trigger surface for the new end-to-end test (call the recorded slot to drive `_on_break_interval_changed` without spinning up a real `SettingsDialog`). Without this extension, every existing `TestOpenSettingsAction` test fails with `AttributeError` once `_on_open_settings` does `dialog.break_interval_changed.connect(...)` before `dialog.exec()`.

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_break_scheduler.py -v` (includes new `TestResetCycle`)
- Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestBreakIntervalChangedSignal`)
- Unit tests pass: `uv run pytest tests/test_app.py -v` (includes new `TestOnBreakIntervalChanged`)
- Full suite passes: `uv run pytest`
- Type check passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Format check passes: `uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual Verification:

- Real Windows: open Settings, change break interval from current value (e.g., 5 → 7 min), click OK; tray tooltip immediately reads `BreakReminder — next break in 7m 00s` (then ticks down on the next 5-second `_tooltip_timer` refresh).
- Real Windows: open Settings without changing break interval (e.g., toggle voice checkbox or change snooze duration only), click OK; tray tooltip continues counting down from where it was, NOT reset.
- Real Windows: with a snooze in-flight (click Snooze in the break dialog, then immediately open Settings), change the break interval, click OK; the snooze-time-left tooltip flips back to the regular countdown (snooze cleared) and starts fresh.
- Real Windows: pause via tray, open Settings, change break interval, click OK; tray tooltip stays `BreakReminder — paused` (pause wins over countdown — verified by the existing `_refresh_tooltip` priority order; the reset still happens but isn't visible until Resume).
- Real Windows: existing flows (Take break now, Reset, regular break-due dialog, custom reminders) continue to work.

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Bookkeeping

### Overview

Lightweight follow-up: flip the change folder's `change.md` status from `planned` to `implemented`, update its `updated:` date, verify roadmap S-09 is in a coherent state. No code edits.

### Changes Required:

#### 1. `change.md` status flip

**File**: `context/changes/bugfix-break-cycle-reset-on-save/change.md`

**Intent**: Reflect the implemented state for `/10x-archive`'s soft-warning gate ("Status is X; expected implemented or impl_reviewed").

**Contract**: Frontmatter `status: planned` → `status: implemented`; `updated: <today>`.

### Success Criteria:

#### Automated Verification:

- `git grep -nE 'status: implemented' context/changes/bugfix-break-cycle-reset-on-save/change.md` returns exactly one match.

> Note: Roadmap S-09 row in `## At a glance` (line 41 of `context/foundation/roadmap.md`) stays at `proposed` until the archive step — the implementation phase does not flip it.

---

## Testing Strategy

### Unit Tests:

- **`reset_cycle()` payload** — three observable fields cleared (`_active_seconds == 0`, `_snoozes_used == 0`, `_snooze_until is None`) plus a "second cycle requires fresh threshold" integration test. (TestResetCycle.)
- **`on_break_taken` delegation** — calling `on_break_taken` after the refactor produces the same observable state as before. (Smoke in TestResetCycle.)
- **Signal emission contract** — emits exactly once when value changed, never when unchanged, payload is the new value, emission ordered before `super().accept()`. (TestBreakIntervalChangedSignal.)
- **App-level slot effects** — slot resets active-seconds + snooze state, refreshes tooltip immediately, does NOT change pause state, does NOT write an event-log row. (TestOnBreakIntervalChanged.)

### Integration Tests:

- **End-to-end**: stubbed `SettingsDialog` invoked from `_on_open_settings`, user changes break_interval_min via a manual setter, dialog accepts; the app's `_break_scheduler._active_seconds` is `0` afterwards. Reuses the existing `_StubSettingsDialog` pattern in `tests/test_app.py`.

### Manual Testing Steps:

The Phase 1 Manual Verification list IS the manual testing surface; Phase 2 has no new manual surface.

## Performance Considerations

- **`reset_cycle()` cost** — three attribute writes; sub-microsecond. Fired at most once per Settings → OK click.
- **Signal emission cost** — one Qt direct-connect dispatch; sub-microsecond. Fired at most once per Settings → OK click, and only when the value actually changed.
- **`_refresh_tooltip()` cost** — one `setToolTip(...)` call plus a few attribute reads; the existing 5-second `_tooltip_timer` already drives this exact path so it is well-trodden.
- **No new IO, no new persistence.**

## Migration Notes

No data migration. No `Settings` schema change. Existing `BreakReminder.ini` files load and behave identically; the only new behavior is at-the-moment-of-save reset.

## References

- Roadmap entry: `context/foundation/roadmap.md` § S-09 (line 41 + line 198 + line 225).
- Bug analysis: see chat dialogue 2026-05-28 (root cause: `_active_seconds` not reset on settings save; symptom: tray tooltip seconds digit frozen across interval changes).
- Existing `on_break_taken` — `break_reminder/scheduler.py:162-166` (the body the new `reset_cycle` extracts).
- Existing app slot pattern — `break_reminder/app.py:413-427` (`_apply_break_taken`).
- Existing signal-from-dialog pattern — `break_reminder/ui/reminder_form_dialog.py` (`reminder_added` signal + emit-before-super-accept).
- Existing app-level signal-wiring precedent — `break_reminder/ui/settings_dialog.py:932` (`sub_dialog.reminder_added.connect(...)`).
- Test mirror — `tests/test_break_scheduler.py:425-468` (`TestOnBreakTaken`) for the new `TestResetCycle`.
- Test mirror — `tests/test_app.py:98-167` (`TestApplyBreakTaken`) for the new `TestOnBreakIntervalChanged`.
- Storage layer (unchanged) — `break_reminder/storage/settings.py` (`break_interval_min` getter/setter).

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Implementation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_break_scheduler.py -v` (includes new `TestResetCycle`)
- [x] 1.2 Unit tests pass: `uv run pytest tests/test_settings_dialog.py -v` (includes new `TestBreakIntervalChangedSignal`)
- [x] 1.3 Unit tests pass: `uv run pytest tests/test_app.py -v` (includes new `TestOnBreakIntervalChanged`)
- [x] 1.4 Full suite passes: `uv run pytest`
- [x] 1.5 Type check passes: `uv run pyright`
- [x] 1.6 Linting passes: `uv run ruff check`
- [x] 1.7 Format check passes: `uv run ruff format --check`
- [x] 1.8 Security audit passes: `uv run pip-audit`
- [x] 1.9 License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual

- [x] 1.10 Real Windows: change break interval, tooltip reads `Nm 00s` immediately
- [x] 1.11 Real Windows: open Settings without changing break interval, tooltip continues unchanged
- [x] 1.12 Real Windows: change break interval mid-snooze, snooze cleared, fresh countdown
- [x] 1.13 Real Windows: pause + change break interval, tooltip stays `paused` (priority preserved)
- [x] 1.14 Real Windows: existing flows (Take break now, Reset, break-due dialog, custom reminders) all still work

### Phase 2: Bookkeeping

#### Automated

- [ ] 2.1 `git grep -nE 'status: implemented' context/changes/bugfix-break-cycle-reset-on-save/change.md` returns exactly one match
