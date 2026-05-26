# Settings — Snooze Configuration Implementation Plan

## Overview

Expose the FR-010 snooze parameters — `snooze_duration_min` (1–30) and `max_snoozes` (0–5) — as user-editable spinboxes in the existing **Scheduling** tab of `SettingsDialog`. Today both values have getters in `Settings` but no setters and no UI affordance; the user can only change them by hand-editing `BreakReminder.ini`. After this slice the next break dialog respects the new values on the very next tick (the scheduler reads both keys per-tick already), and PRD Open Question #1 dissolves because the user picks their own duration.

**Scope addendum (2026-05-26)**: While Phase 1 was in flight, the user requested that the tray-icon tooltip switch from `BreakReminder — next break in Xm YYs` to `BreakReminder — snooze time left Xm YYs` while a snooze window is open. This is a small adjacent surface (one new property on `BreakScheduler`, one extra branch in `BreakReminderApp._refresh_tooltip`) that keeps the user informed during the snooze the new spinbox lets them configure. Folded into this slice rather than spun out as a sibling because it's the same conceptual feature ("snooze is a thing the user can see and control") and the added test coverage is small.

## Current State Analysis

- `Settings.snooze_duration_min` (`break_reminder/storage/settings.py:153-156`) and `Settings.max_snoozes` (`break_reminder/storage/settings.py:158-161`) are **getter-only**. No `@…setter`. The clamp inside the getter is the only validation today.
- Bounds are inconsistent with the established pattern. `break_interval_min` exposes them via top-level constants (`BREAK_INTERVAL_MIN_MINUTES = 1`, `BREAK_INTERVAL_MAX_MINUTES = 240`, `break_reminder/storage/settings.py:28-29`); `max_snoozes` hard-codes `0` and `5` inline; `snooze_duration_min` has only a `max(1, …)` floor and **no upper cap defined anywhere** — the roadmap-stated 30-minute ceiling is currently unenforced in the persistence layer.
- Defaults already exist (`DEFAULT_SNOOZE_DURATION_MIN = 5`, `DEFAULT_MAX_SNOOZES = 1`, `break_reminder/storage/settings.py:35-36`) and the QSettings keys are wired (`scheduling/snooze_duration_min`, `scheduling/max_snoozes`, `break_reminder/storage/settings.py:48-49`).
- `Snapshot` includes both fields (`break_reminder/storage/settings.py:62-63`) and the scheduler reads them every tick: `BreakScheduler.on_snoozed` reads `snooze_duration_min` (`break_reminder/scheduler.py:145`) and `BreakScheduler._tick` computes `snooze_remaining = max(0, snap.max_snoozes - self._snoozes_used)` (`break_reminder/scheduler.py:174`). No long-lived snapshot — saved values are observable on the very next tick.
- `SettingsDialog` already has a 2-tab layout (Scheduling + Notifications, `break_reminder/ui/settings_dialog.py:143-150`). The Scheduling tab today carries one row (the break-interval spinbox). Adding two more rows fits the existing `QFormLayout` (`break_reminder/ui/settings_dialog.py:194-195`) without touching the Notifications tab.
- The break-interval validation feedback (`_on_break_interval_text_edited` + `_on_break_interval_edited`, `break_reminder/ui/settings_dialog.py:262-303`) — the typed-out-of-range tooltip — is intentionally NOT replicated for snooze fields per the design questioning. The 1–30 / 0–5 ranges are small enough that the spinbox's silent fixup is adequate; adding the keystroke-capture pair would duplicate ~40 lines for no observable user benefit.
- Test patterns to mirror: `TestValidation` in `tests/test_settings.py:115-160` (break-interval setter validation + getter clamp on corrupt INI), `TestVoiceSettersRoundTrip` in `tests/test_settings.py:163-…` (cross-instance persistence). Dialog-side patterns: `TestLoad` / `TestSave` / `TestLayout` for break-interval (`tests/test_settings_dialog.py:89,148,221`).
- **Tray tooltip surface (scope addendum)**: `BreakReminderApp._refresh_tooltip` (`break_reminder/app.py:233-241`) drives `QSystemTrayIcon.setToolTip` from `BreakScheduler.seconds_until_break` and `BreakScheduler.is_paused`. Today it has two branches: paused (`BreakReminder — paused`) and the regular countdown (`BreakReminder — next break in Xm YYs`). It's invoked on a 5-second `QTimer` tick (`break_reminder/app.py:105-107`) plus eagerly on every state-changing user action (`pause/resume`, `_apply_break_taken`, `_apply_break_snoozed` — see `break_reminder/app.py:284, 385, 398`). The eager call after `_apply_break_snoozed` means the tooltip flips to the snooze-aware text the instant the user clicks Snooze; the 5-second timer is steady-state refresh only. The scheduler holds snooze state in `_snooze_until: datetime | None` (`break_reminder/scheduler.py:90`); no public accessor for "seconds remaining in the snooze window" exists yet, so we add one mirroring the shape of `seconds_until_break`.

## Desired End State

The Scheduling tab in `SettingsDialog` shows three rows in this order: "Break interval (minutes):" (existing), "Snooze duration (minutes):" (new), "Max snoozes per cycle:" (new). Each new row is a `QSpinBox` pre-populated from the matching `Settings` getter, with bounds matching the new top-level constants. The "Max snoozes per cycle" spinbox carries a tooltip explaining the zero case ("0 = no snoozes; the break must be taken or missed"). Clicking OK persists both values via the new setters; the existing scheduler picks up the new values on the next tick. Clicking Cancel discards. PRD Open Question #1 is annotated as dissolved by S-03 in the roadmap; S-03's roadmap status flips from `proposed` to `done`. The `change.md` status flips from `implementing` to `implemented`.

**Tray tooltip during snooze**: While a snooze window is open (`BreakScheduler._snooze_until is not None and not yet elapsed`), the tray-icon tooltip reads `BreakReminder — snooze time left Xm YYs`, where `Xm YYs` counts down to `_snooze_until`. The instant the user clicks "Snooze" on the break dialog the tooltip flips (because `_apply_break_snoozed` already calls `_refresh_tooltip` eagerly). The instant the snooze elapses or the user takes a break, the tooltip flips back to the regular `next break in Xm YYs` form. Pause continues to take precedence: pausing during a snooze still shows `BreakReminder — paused`.

### Key Discoveries

- The scheduler reads `Settings.snooze_duration_min` and `Settings.max_snoozes` directly, every tick — no plumbing change needed (`break_reminder/scheduler.py:145, 174`).
- `max_snoozes = 0` is already a working state: scheduler computes `snooze_remaining = 0` and the existing `BreakDialog` hides the snooze button. So the new spinbox merely makes that state user-reachable; no dialog code change required to support it.
- `DEFAULT_SNOOZE_DURATION_MIN = 5` is already labeled `# PRD Open Question #1` in the source (`break_reminder/storage/settings.py:35`). The slice keeps the in-code default at 5 and adds a UI to override; this is the semantic the roadmap S-03 unknown anticipated ("S-03 collapses the question by giving the user a UI to set their own value").
- `_apply_break_snoozed` and `_apply_break_taken` already call `_refresh_tooltip` eagerly (`break_reminder/app.py:385, 398`), so the new snooze-aware branch in `_refresh_tooltip` flips the tooltip immediately on user action — no extra wiring needed for the transition.
- The 5-second tooltip refresh cadence (`break_reminder/app.py:106`) is kept unchanged. The seconds field already ticks in chunks of ~5 in the regular countdown form; the snooze form inherits the same cadence and the user is already accustomed to it.

## What We're NOT Doing

- No new tab — fields land on the existing Scheduling tab.
- No typed-out-of-range tooltip pattern for the new spinboxes (asked + decided: spinbox visual fixup is sufficient for these narrow ranges).
- No change to the in-code default `DEFAULT_SNOOZE_DURATION_MIN = 5` — the user picks their own value via the UI; the default exists only for first-run / fresh-install state.
- No change to `BreakDialog`'s rendering — `max_snoozes = 0` already produces the correct "no snooze button" path through the existing `snooze_remaining = 0` check.
- No change to `Snapshot` (`scheduler.py` reads `_settings.snooze_duration_min` directly inside `on_break_snoozed`, not from a snapshot — no plumbing change needed) and no change to `_tick`'s snooze-window check.
- No change to the 5-second tooltip refresh cadence — the snooze form inherits the same per-tick granularity as the regular countdown form.
- No autostart, voice, custom-reminder, or break-interval work — strictly the snooze surface.

## Implementation Approach

Two phases mirror the S-04 shape exactly: Phase 1 adds the persistence-layer constants + setters and the dialog-layer fields + tests; Phase 2 is human smoke + roadmap bookkeeping.

The persistence-layer changes mirror the established `break_interval_min` setter pattern verbatim — top-level range constants, a tight setter that raises `ValueError` on out-of-range input, and a `@property` getter that already clamps for hand-edited corrupt INI values. The bounds inside the existing `snooze_duration_min` and `max_snoozes` getters are tightened to read from the new constants (single source of truth).

The dialog-layer changes extend `_build_scheduling_tab` with two more `QFormLayout` rows. Each spinbox carries a `setSuffix` for unit clarity ("min" for duration, none for max-count). The new `accept()` lines persist both values via the new setters; the spinbox-level `setMinimum` / `setMaximum` calls guarantee the setter's `ValueError` branch is unreachable from the dialog (same invariant the break-interval row relies on).

Tests mirror two existing surfaces:
- `tests/test_settings.py` gets a new `TestSnoozeSettersRoundTrip` class (round-trip + cross-instance persistence) and `TestSnoozeValidation` class (boundary values + `ValueError` on out-of-range + getter clamp on corrupt INI).
- `tests/test_settings_dialog.py` gets new tests under the existing `TestLoad`, `TestSave`, `TestLayout` classes covering the two new spinboxes (initial value, bounds, save round-trip).

## Phase 1: Constants + setters + UI fields + automated coverage

### Overview

All code changes land here. After Phase 1: snooze duration and max snoozes are user-editable in the Scheduling tab, persist correctly, the scheduler picks them up on the next tick, and a regression net catches future breakage of the persistence-layer ranges.

### Changes Required:

#### 1. Top-level range constants in `Settings`

**File**: `break_reminder/storage/settings.py`

**Intent**: Expose snooze ranges as top-level constants so the persistence-layer clamp, the setter validation, and the dialog-layer spinbox bounds all read from a single source of truth — the same pattern `BREAK_INTERVAL_*_MINUTES` already establishes.

**Contract**:
- New `SNOOZE_DURATION_MIN_MINUTES = 1` and `SNOOZE_DURATION_MAX_MINUTES = 30` near the existing `BREAK_INTERVAL_*` pair (under the `# --- Bounds (FR-006) ---` comment block, with the comment header expanded to mention FR-010 since the new constants serve it).
- New `MAX_SNOOZES_MIN = 0` and `MAX_SNOOZES_MAX = 5` in the same block.
- Per-constant inline comment naming the FR-010 bound and pointing the reader at the setter (mirrors the existing `BREAK_INTERVAL_*_MINUTES` comment shape on lines 23-27).

#### 2. `snooze_duration_min` getter clamp + new setter

**File**: `break_reminder/storage/settings.py`

**Intent**: Replace the single-sided `max(1, …)` floor with a two-sided clamp using the new constants (matches `break_interval_min`'s `max(LOWER, min(UPPER, raw))` shape) and add a tight setter that raises `ValueError` on out-of-range input.

**Contract**:
- Getter (`break_reminder/storage/settings.py:153-156`) updated: replace `max(1, …)` with `max(SNOOZE_DURATION_MIN_MINUTES, min(SNOOZE_DURATION_MAX_MINUTES, raw))`.
- New setter on the same property; raises `ValueError` with a message naming the FR-010 range; calls `self._qs.setValue(_Keys.SNOOZE_DURATION_MIN, minutes)` on success. Google-style docstring with `Args:` and `Raises:` sections per `context/foundation/lessons.md`.

#### 3. `max_snoozes` getter clamp using constants + new setter

**File**: `break_reminder/storage/settings.py`

**Intent**: Replace the inline `max(0, min(5, …))` literals with the new constants and add the matching tight setter.

**Contract**:
- Getter (`break_reminder/storage/settings.py:158-161`) updated to use `MAX_SNOOZES_MIN` / `MAX_SNOOZES_MAX`.
- New setter; raises `ValueError` on out-of-range; persists via `self._qs.setValue(_Keys.MAX_SNOOZES, value)`. Google-style docstring.

#### 4. Snooze rows in `_build_scheduling_tab`

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Add the two spinboxes to the existing Scheduling tab so the user can edit both values. Order: break interval (existing) → snooze duration → max snoozes. Group them visually under one tab (no section heading needed; `QFormLayout` row labels provide enough structure).

**Contract**:
- Import the four new constants (`SNOOZE_DURATION_MIN_MINUTES`, `SNOOZE_DURATION_MAX_MINUTES`, `MAX_SNOOZES_MIN`, `MAX_SNOOZES_MAX`) alongside the existing `BREAK_INTERVAL_*_MINUTES` import.
- Two new instance attributes: `self._snooze_duration_spinbox: QSpinBox` and `self._max_snoozes_spinbox: QSpinBox`. Both pre-populated from the matching `Settings` getter, both with `setMinimum` / `setMaximum` matching the new constants. The duration spinbox carries `setSuffix(" min")`; the max-snoozes spinbox does not (it's a count, not a duration).
- The max-snoozes spinbox carries a tooltip: `"0 = no snoozes; the break must be taken or missed."` Surfaces the non-obvious zero-state UX without needing a dialog redesign.
- Both rows added to the existing `QFormLayout` via `form.addRow("Snooze duration (minutes):", …)` and `form.addRow("Max snoozes per cycle:", …)` after the existing break-interval row.
- No new validation feedback signals (no `textEdited` / `editingFinished` connections on the new spinboxes — see "What We're NOT Doing").

#### 5. `accept()` persists both new values

**File**: `break_reminder/ui/settings_dialog.py`

**Intent**: Wire the new spinboxes into the save path so OK actually writes them.

**Contract**:
- After the existing `self._settings.break_interval_min = …` line and before `super().accept()`, add:
  - `self._settings.snooze_duration_min = self._snooze_duration_spinbox.value()`
  - `self._settings.max_snoozes = self._max_snoozes_spinbox.value()`
- Order matches the visual order of the spinboxes in the tab.
- No new validation gate — the spinbox `setMinimum` / `setMaximum` calls guarantee in-range values, so the new setters' `ValueError` branches are unreachable from this dialog (same invariant the existing break-interval line relies on).
- Update the `accept` docstring to mention the two new fields.

#### 6. Persistence-layer tests

**File**: `tests/test_settings.py`

**Intent**: Pin the new setters' contracts (round-trip, cross-instance persistence, range validation, getter clamp on corrupt INI) so regressions surface in CI.

**Contract**:
- New `TestSnoozeSettersRoundTrip` class mirroring `TestVoiceSettersRoundTrip`. Tests:
  - `test_snooze_duration_setter_writes_value` — set 10, getter returns 10.
  - `test_snooze_duration_persists_across_instances` — write through one `Settings`, read through a fresh one bound to the same INI path.
  - `test_max_snoozes_setter_writes_value` — same shape for max snoozes.
  - `test_max_snoozes_persists_across_instances` — same shape.
- New `TestSnoozeValidation` class mirroring the break-interval `TestValidation` shape. Tests:
  - `test_snooze_duration_setter_rejects_zero` — expects `ValueError` matching `r"\[1, 30\]"`.
  - `test_snooze_duration_setter_rejects_above_30` — expects `ValueError`.
  - `test_snooze_duration_setter_accepts_boundary_values` — 1 and 30 round-trip.
  - `test_snooze_duration_getter_clamps_corrupt_high_value` — INI with 9999 reads back as 30.
  - `test_snooze_duration_getter_clamps_corrupt_low_value` — INI with -50 reads back as 1.
  - `test_max_snoozes_setter_rejects_negative` — expects `ValueError` matching `r"\[0, 5\]"`.
  - `test_max_snoozes_setter_rejects_above_5` — expects `ValueError`.
  - `test_max_snoozes_setter_accepts_boundary_values` — 0 and 5 round-trip (zero is intentional).
  - `test_max_snoozes_getter_clamps_corrupt_high_value` — INI with 99 reads back as 5.

#### 7. Dialog-layer tests

**File**: `tests/test_settings_dialog.py`

**Intent**: Pin the new spinboxes' contracts in the dialog (initial value matches Settings getter, bounds match constants, save round-trips through Settings).

**Contract**:
- Extend `TestLoad` (around `tests/test_settings_dialog.py:89-138`):
  - `test_snooze_duration_spinbox_initial_value` — fresh dialog reads `DEFAULT_SNOOZE_DURATION_MIN`.
  - `test_snooze_duration_spinbox_bounds` — `.minimum() == 1`, `.maximum() == 30`.
  - `test_max_snoozes_spinbox_initial_value` — reads `DEFAULT_MAX_SNOOZES`.
  - `test_max_snoozes_spinbox_bounds` — `.minimum() == 0`, `.maximum() == 5`.
  - `test_max_snoozes_spinbox_zero_tooltip_present` — spinbox tooltip contains the string `"0 = no snoozes"`.
- Extend `TestSave` (around `tests/test_settings_dialog.py:148-218`):
  - `test_snooze_duration_save_round_trip` — set spinbox to 10, click OK, fresh `Settings` reads 10.
  - `test_max_snoozes_save_round_trip` — set spinbox to 3, click OK, fresh `Settings` reads 3.
  - `test_max_snoozes_save_zero_round_trip` — explicit zero coverage; set 0, click OK, reads 0.
- Extend `TestLayout` (around `tests/test_settings_dialog.py:221-`): assert the Scheduling tab's `QFormLayout` row count grew by 2 and the new row labels are present.

#### 8. `BreakScheduler.seconds_until_snooze_end` property (scope addendum)

**File**: `break_reminder/scheduler.py`

**Intent**: Expose "seconds remaining in the active snooze window, or `None` if no snooze is active" so `_refresh_tooltip` can decide whether to render the snooze form. Mirrors the shape of the existing `seconds_until_break` property and lives next to it in the file.

**Contract**:
- New `@property seconds_until_snooze_end(self) -> int | None:` placed immediately below `seconds_until_break` (`break_reminder/scheduler.py:107-117`) so the two tooltip-feeding properties sit together.
- Returns `None` when `self._snooze_until is None`. Returns `None` when the snooze window has elapsed (`now >= _snooze_until`) — guarantees `_refresh_tooltip` flips back to the regular countdown the moment the window expires, even before the next 1-second `_tick()` clears `_snooze_until`. Otherwise returns `math.ceil((self._snooze_until - now).total_seconds())` so a fractional 0.4s remaining still displays as "0m 01s" (avoids a 1-second flicker through "0m 00s" before the property returns `None`).
- Uses `self._clock()` for "now" so tests with the existing `Clock` fixture drive it deterministically (same pattern as `_tick`).
- Google-style docstring with a one-line summary, an explanation of the `None` semantics, and a "Used by …" pointer back to the tray-icon tooltip — matches the docstring shape on `seconds_until_break` (`break_reminder/scheduler.py:108-113`).
- Add `import math` at the top of the file. No other change.

#### 9. Snooze-aware branch in `BreakReminderApp._refresh_tooltip` (scope addendum)

**File**: `break_reminder/app.py`

**Intent**: While a snooze window is open, render `BreakReminder — snooze time left Xm YYs` instead of the regular `next break in Xm YYs`. Pause continues to take precedence.

**Contract**:
- Insert a new branch between the existing paused-branch and the regular-countdown branch in `_refresh_tooltip` (`break_reminder/app.py:233-241`):
  ```python
  snooze_seconds = self._break_scheduler.seconds_until_snooze_end
  if snooze_seconds is not None:
      minutes, seconds = divmod(snooze_seconds, 60)
      self._tray.setToolTip(f"{APPLICATION_NAME} — snooze time left {minutes:d}m {seconds:02d}s")
      return
  ```
- Keep the `self._action_pause.setText("Pause")` line above this branch so the menu label stays consistent during snooze (snooze is not pause; the user can still pause from the menu).
- No new imports needed (the formatter / `divmod` / `setToolTip` are all already in scope).
- Add a Google-style docstring to `_refresh_tooltip` describing the three branches in priority order (paused → snoozing → regular countdown). The function is currently undocumented (`break_reminder/app.py:233`) so this also closes a small docstring gap.

#### 10. README — document the snooze tooltip variant (scope addendum)

**File**: `README.md`

**Intent**: Keep the user-facing docs in lockstep with the new tooltip behavior so users hovering the icon during a snooze aren't surprised.

**Contract**:
- The "Hover the icon" bullet under "### The tray icon" (`README.md:136-138`) gets a new sentence: `While a snooze is active, the tooltip reads BreakReminder — snooze time left Xm YYs.`
- No change to the rest of that section.

### Success Criteria:

#### Automated Verification:

- Persistence tests pass: `uv run pytest tests/test_settings.py::TestSnoozeSettersRoundTrip tests/test_settings.py::TestSnoozeValidation`
- Dialog tests pass: `uv run pytest tests/test_settings_dialog.py`
- Scheduler tests pass (incl. new `TestSecondsUntilSnoozeEnd`): `uv run pytest tests/test_break_scheduler.py`
- App tests pass (incl. new `TestRefreshTooltipDuringSnooze`): `uv run pytest tests/test_app.py`
- Full suite still passes: `uv run pytest`
- Type check passes: `uv run pyright break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/scheduler.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_break_scheduler.py tests/test_app.py`
- Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/scheduler.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_break_scheduler.py tests/test_app.py`
- Format check passes: `uv run ruff format --check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/scheduler.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_break_scheduler.py tests/test_app.py`

#### Manual Verification:

(Deferred to Phase 2 — keeps Phase 1 a clean automated gate.)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 2. The corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Manual smoke + roadmap bookkeeping

### Overview

Verify the dialog renders the new fields, edits persist, the running scheduler picks them up on the very next tick, and the `max_snoozes = 0` corner produces the no-snooze-button path on the next break dialog. Flip `change.md` from `implementing` to `implemented`. Flip the roadmap S-03 row to `done`, update the backlog handoff, annotate PRD Open Question #1 as dissolved.

### Changes Required:

#### 1. Manual smoke checklist

**File**: human verification (no code change)

**Intent**: Confirm end-to-end behavior on a real running tray + break dialog before declaring the slice done.

**Contract**:
- Run from source: `uv run python main.py` (faster than building the installer).
- Right-click tray → "Open settings…" → Scheduling tab.
- Verify three rows in order: Break interval, Snooze duration, Max snoozes per cycle.
- Hover the Max snoozes spinbox — tooltip shows the zero-state explanation.
- Set Snooze duration to 2 min and Max snoozes to 2; click OK.
- Re-open settings — both values are persisted.
- Wait for / force a break (set break interval to 1 min temporarily). When the break dialog fires, click "Snooze" — **immediately hover the tray icon**: tooltip reads `BreakReminder — snooze time left Xm YYs` (counts down toward 0). Verify the next break fires ~2 min later (the new snooze duration). Click "Snooze" again — tooltip flips back to snooze-time-left for another ~2 min — and verify the snooze button is then hidden / disabled (max 2 reached, 2 used).
- After a snooze elapses (or after clicking "I'll take a break"), hover the tray icon — tooltip is back to the regular `BreakReminder — next break in Xm YYs` form.
- Pause the app while a snooze is active (right-click → Pause) — tooltip flips to `BreakReminder — paused`. Resume — tooltip flips back to the snooze-time-left form (the snooze window is still open).
- Re-open settings, set Max snoozes to 0, save. On the next break, the snooze button should be hidden / disabled — the user must take or miss the break.
- Hand-edit `BreakReminder.ini` to put `snooze_duration_min=99` (above range), restart the app — getter clamps to 30; settings dialog shows 30 in the spinbox.

#### 2. `change.md` status flip

**File**: `context/changes/settings-snooze-config/change.md`

**Intent**: Reflect that the slice has shipped.

**Contract**: Set `status: implemented` and `updated: <today>`.

#### 3. Roadmap update

**File**: `context/foundation/roadmap.md`

**Intent**: Reflect that S-03 has shipped, dissolve PRD Open Question #1, update the backlog handoff so a future reader sees S-03 as done rather than queued.

**Contract**:
- "At a glance" table row for S-03: `Status` column flips from `proposed` to `done`.
- `### S-03: settings-snooze-config` block: `Status` line flips to `done`. The `Unknowns:` bullet about PRD Open Question #1 gets a parenthetical "(dissolved by S-03 on 2026-05-26)" appended (mirroring how S-04 dissolved Open Question #3 on 2026-05-25).
- `## Open Roadmap Questions` item 1 ("Snooze duration default value"): append "(dissolved by S-03 on 2026-05-26)" to the line.
- `## Backlog Handoff` table row for S-03: update `Notes` column from "Run after S-01" to "Planned + shipped 2026-05-26"; flip `Ready for /10x-plan` from `no` to `yes` (mirrors how S-04's row was updated post-ship — present-tense factual reflection of the shipped state).

### Success Criteria:

#### Automated Verification:

- (None — Phase 2 is human-driven.)

#### Manual Verification:

- Snooze duration spinbox saves; next break dialog's "Snooze" defers by the new minutes.
- Max snoozes spinbox saves; the existing snooze cap honors the new value.
- `max_snoozes = 0` produces the no-snooze-button path on the next break.
- Tray tooltip reads `BreakReminder — snooze time left Xm YYs` immediately after clicking Snooze, and flips back to `next break in Xm YYs` once the snooze elapses or a break is taken. (Scope addendum.)
- Pause during snooze still shows `BreakReminder — paused` (paused branch wins). (Scope addendum.)
- Hand-edited corrupt INI (out-of-range value) is clamped silently by the getter when the dialog re-opens.
- `change.md` flipped from `implementing` to `implemented`.
- Roadmap S-03 row reflects `done`; backlog handoff updated; PRD Open Question #1 annotated.

---

## Testing Strategy

### Unit Tests

- 4 new tests in `TestSnoozeSettersRoundTrip` (round-trip + cross-instance for both fields).
- 9 new tests in `TestSnoozeValidation` (boundary, out-of-range `ValueError`, getter clamp on corrupt INI for both fields; explicit zero acceptance for `max_snoozes`).
- 5 new tests under `TestLoad` (initial values, bounds, tooltip presence).
- 3 new tests under `TestSave` (round-trip, including the explicit zero case for `max_snoozes`).
- 1 new test under `TestLayout` (row count + label presence on the Scheduling tab).
- **Scope addendum** — 4 new tests in `TestSecondsUntilSnoozeEnd` (`tests/test_break_scheduler.py`):
  - `test_returns_none_when_no_snooze_active` — fresh scheduler returns `None`.
  - `test_returns_positive_seconds_during_snooze` — after `on_break_snoozed()` with a 5-min default and clock unmoved, returns 300.
  - `test_decreases_as_clock_advances` — advance the clock 60s, returns 240.
  - `test_returns_none_at_or_after_snooze_end` — advance the clock past `_snooze_until`, returns `None` (even before `_tick` clears the field).
- **Scope addendum** — 3 new tests in `TestRefreshTooltipDuringSnooze` (`tests/test_app.py`):
  - `test_tooltip_during_snooze_shows_snooze_form` — after `_apply_break_snoozed`, `tray.toolTip()` matches `r"^BreakReminder — snooze time left \d+m \d{2}s$"`.
  - `test_paused_takes_precedence_over_snooze` — pause + snooze → tooltip is `BreakReminder — paused`.
  - `test_falls_back_to_regular_countdown_when_snooze_clears` — `_apply_break_snoozed` then `_apply_break_taken` → tooltip is the regular `next break in Xm YYs` form.

### Integration Tests

- None — the slice is behaviorally a UI-fields-plus-setters add plus a scheduler accessor + tooltip branch. The scheduler integration is already covered by existing `tests/test_break_scheduler.py` (which reads `Settings.snooze_duration_min` / `Settings.max_snoozes` via the same path the production scheduler uses).

### Manual Testing Steps

1. Run `uv run python main.py`. Right-click tray → Open settings → Scheduling tab. Confirm three rows in order: Break interval, Snooze duration, Max snoozes per cycle.
2. Hover the Max snoozes spinbox; tooltip reads "0 = no snoozes; the break must be taken or missed."
3. Set Break interval = 1, Snooze duration = 2, Max snoozes = 2. Save.
4. Wait for the break dialog. Click "Snooze" → immediately hover the tray icon: tooltip reads `BreakReminder — snooze time left Xm YYs`. Verify next fire ~2 min later. Click "Snooze" again → tooltip flips to a fresh ~2-min snooze-time-left countdown; verify the second click consumes the cap; the next break has no snooze button.
5. After the snooze elapses (or after clicking "I'll take a break"), hover the tray icon — tooltip is back to `BreakReminder — next break in Xm YYs`.
6. While a snooze is active, right-click → Pause. Tooltip flips to `BreakReminder — paused`. Resume — tooltip flips back to the snooze-time-left form.
7. Re-open settings. Set Max snoozes = 0. Save. On the next break, verify the snooze button is absent/disabled — the user must Take Break.
8. Quit the app. Edit `%APPDATA%\BreakReminder\BreakReminder.ini` and write `snooze_duration_min=999` under `[scheduling]`. Restart. Re-open settings; spinbox displays 30 (the getter clamps).

## Performance Considerations

None. Two new spinboxes in an existing `QFormLayout` row; one extra `Settings.value` read per tab open. Negligible.

## Migration Notes

None. Existing INI files without these keys fall through to the defaults the getters already returned (no-op for upgrading users). Users who hand-edited values outside the new ranges get clamped on next read — same behavior the break-interval getter already exhibits for FR-006.

## References

- Roadmap slice: [context/foundation/roadmap.md S-03](../../foundation/roadmap.md)
- Bootstrap notes: `context/changes/settings-snooze-config/change.md`
- Pattern: break-interval setter — [break_reminder/storage/settings.py:124-146](../../../break_reminder/storage/settings.py)
- Pattern: voice-setter round-trip tests — [tests/test_settings.py:163](../../../tests/test_settings.py)
- Pattern: break-interval validation tests — [tests/test_settings.py:115-160](../../../tests/test_settings.py)
- Pattern: dialog tab build — [break_reminder/ui/settings_dialog.py:165-197](../../../break_reminder/ui/settings_dialog.py)
- Scheduler integration points: [break_reminder/scheduler.py:145, 174](../../../break_reminder/scheduler.py)
- Project lessons (Google-style docstrings on every public function): [context/foundation/lessons.md](../../foundation/lessons.md)
- Sibling slice (parallel under Stream A): `context/changes/settings-voice-toggle/plan.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Constants + setters + UI fields + automated coverage

#### Automated

- [x] 1.1 Persistence tests pass: `uv run pytest tests/test_settings.py::TestSnoozeSettersRoundTrip tests/test_settings.py::TestSnoozeValidation` — fc0f6b3
- [x] 1.2 Dialog tests pass: `uv run pytest tests/test_settings_dialog.py` — fc0f6b3
- [x] 1.3 Scheduler tests pass (incl. new `TestSecondsUntilSnoozeEnd`): `uv run pytest tests/test_break_scheduler.py` — fc0f6b3
- [x] 1.4 App tests pass (incl. new `TestRefreshTooltipDuringSnooze`): `uv run pytest tests/test_app.py` — fc0f6b3
- [x] 1.5 Full suite still passes: `uv run pytest` (235 passed) — fc0f6b3
- [x] 1.6 Type check passes: `uv run pyright break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/scheduler.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_break_scheduler.py tests/test_app.py` — fc0f6b3
- [x] 1.7 Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/scheduler.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_break_scheduler.py tests/test_app.py` — fc0f6b3
- [x] 1.8 Format check passes: `uv run ruff format --check break_reminder/storage/settings.py break_reminder/ui/settings_dialog.py break_reminder/scheduler.py break_reminder/app.py tests/test_settings.py tests/test_settings_dialog.py tests/test_break_scheduler.py tests/test_app.py` — fc0f6b3

> **Re-tick note (2026-05-26)**: 1.1 and 1.2 stayed green from the original Phase 1 commit; 1.3–1.8 were re-evaluated and re-ticked after the scope addendum landed (snooze-aware tooltip).

### Phase 2: Manual smoke + roadmap bookkeeping

#### Manual

- [x] 2.1 Three rows on Scheduling tab in order: Break interval, Snooze duration, Max snoozes — 9aa8273
- [x] 2.2 Max snoozes spinbox tooltip shows the zero-state explanation — 9aa8273
- [x] 2.3 Snooze duration save round-trips; next break's Snooze defers by the new minutes — 9aa8273
- [x] 2.4 Max snoozes save round-trips; cap behavior honors the new value — 9aa8273
- [x] 2.5 max_snoozes = 0 hides the snooze button on the next break dialog — 9aa8273
- [x] 2.6 Tray tooltip reads `BreakReminder — snooze time left Xm YYs` immediately after Snooze, then flips back to the regular countdown when the snooze elapses or the user takes a break — 9aa8273
- [x] 2.7 Pause during snooze shows `BreakReminder — paused`; resume returns to the snooze-time-left form — 9aa8273
- [x] 2.8 Corrupt INI value (e.g., 999) is clamped silently when the dialog re-opens — 9aa8273
- [x] 2.9 change.md flipped from `implementing` to `implemented` — 9aa8273
- [x] 2.10 Roadmap S-03 status flipped from `proposed` to `done`; backlog handoff updated; PRD Open Question #1 annotated as dissolved — 9aa8273
