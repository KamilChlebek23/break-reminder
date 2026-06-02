# Top-three e2e flows — Implementation Plan

## Overview

Phase 4 of the BreakReminder test rollout closes coverage on three load-bearing R-4 signal connections in `break_reminder/app.py` (`:277` `break_due`, `:278` `reminder_due`, `:349` `break_interval_changed`) by adding one end-to-end test per top-three user-visible flow: **Flow A** (Add Reminder via form → arm → fire → `ReminderDialog`), **Flow B** (Save Settings interval change → reset cycle → next `break_due` fires on new threshold → `BreakDialog`), **Flow D** (Tray "Reset" → `_apply_break_taken` → cycle re-arms + TAKEN row in `events.log` → next `break_due` fires → `BreakDialog`). The phase also lands the pytest `e2e` marker tier with `--strict-markers`, a CI `release.yml` job split, a small structural fix to `BreakReminderApp.__init__` (add `clock=` kwarg, parallels Phase 3's `_read` precedent), and the supporting docs sync across `AGENTS.md`, `test-plan.md §6`, and `lessons.md`.

## Current State Analysis

- **Zero integration tests existed before this rollout**; Phase 1 shipped `tests/test_recurring_reminder_integration.py` (R-1; 4 tests) and Phase 2 shipped `tests/test_modal_stacking_integration.py` (R-2; 1 test). Phase 4 is the first phase to ship **end-to-end** user-flow tests on top of the per-module unit tier.
- **The R-4 anti-pattern is institutional in this codebase.** Four `_StubSignal` shims (`tests/test_app.py:431`, `tests/test_settings_dialog.py:2446`, `:2749`, `:2802`) capture connected slots and invoke them by hand. The "end-to-end" test at `tests/test_app.py:285-314` (`test_end_to_end_via_settings_dialog_stub`) is the canonical example — it invokes `slots[0](7)` instead of emitting the real `break_interval_changed` signal across the real `connect`.
- **`BreakScheduler` and `ReminderScheduler` both have clean `clock=` injection seams** (`break_reminder/scheduler.py:66`, `:262`). Tests bypass real `QTimer`s by calling `_tick()` / `_on_timer()` directly — this pattern is established by Phase 1 (`tests/test_recurring_reminder_integration.py:113, 117, 164`) and explicitly endorsed by `context/foundation/test-plan.md §7` ("No deep Qt-internals mocking").
- **`BreakReminderApp.__init__` (`break_reminder/app.py:60-113`) accepts injectable `settings`/`event_log`/`reminder_store`/`voice` but no `clock=` kwarg.** The schedulers constructed inside the wired app (`app.py:103-104`) fall through to real wall-clock `_utcnow`. This is a STRUCTURAL finding (research.md §F STRUCTURAL #1) that blocks any future wired-app e2e from driving virtual time deterministically.
- **`pyproject.toml:58-60` has no custom markers** (`[tool.pytest.ini_options]` declares only `testpaths` + `addopts = "-q"`). No `--strict-markers`. The two existing integration files do not carry any marker today.
- **`.github/workflows/release.yml:58-59` runs a single `Test` step** (`uv run pytest`) inside the only `build` job. `.pre-commit-config.yaml:11-25` runs `ruff` + `pyright` only — **no pytest hook**, so any test-tier change has zero dev impact.
- **The closest-to-e2e test today is `tests/test_app.py:358-371` `test_reset_triggers_apply_break_taken`** — it drives `QAction.trigger()` through `_apply_break_taken` and asserts on the TAKEN CSV row in one pass. It stops short of advancing the clock to verify the next `break_due` fires on the re-armed timer. Flow D extends this shape.
- **Six fixtures are duplicated across Phase 1/2 integration files** (`clock`, `store_path`, `store`, `settings`, `voice`+`FakeVoice` class, `reminder_scheduler`). Three more (`activity`, `break_scheduler`, `event_log`) live only in unit-test files (`tests/test_break_scheduler.py:46-61`, `tests/test_event_log.py`). One (`break_reminder_app`) does not exist anywhere.

## Desired End State

After this plan completes:

1. **Three e2e tests exist** — one per Flow A/B/D — each driving the user click through every cross-module hop to a `BreakDialog`/`ReminderDialog` appearing on `QApplication.topLevelWidgets()`. Each test exercises a real signal emit across a real `connect` (no `_StubSignal` shims, no slot-poking). The R-4 contract is now observed end-to-end for each load-bearing connection.
2. **The pytest `e2e` marker is declared and enforced** — `pyproject.toml` `[tool.pytest.ini_options].markers` includes `"e2e: end-to-end test of a top-three user-visible flow (Phase 4 tier)"`; `addopts` includes `--strict-markers`; `tests/test_add_reminder_e2e.py`, `tests/test_save_settings_interval_e2e.py`, `tests/test_tray_reset_e2e.py` carry `@pytest.mark.e2e`.
3. **CI is split into two sequential steps** in the existing `build` job — `Test (unit)` runs `uv run pytest -m "not e2e"` and `Test (e2e)` runs `uv run pytest -m e2e`. Both steps green on `windows-latest`.
4. **`BreakReminderApp.__init__` accepts a `clock=` kwarg** propagated to both `BreakScheduler` and `ReminderScheduler` constructions. One pin test asserts the injection works.
5. **`tests/conftest.py` exposes the shared harness** — `clock`, `store_path`, `store`, `settings`, `voice` (+ `FakeVoice` class), `reminder_scheduler`, `activity`, `break_scheduler`, `event_log`, `break_reminder_app` all as function-scoped fixtures. The two existing integration files drop their now-duplicate local fixtures.
6. **Docs reflect the new state** — `AGENTS.md § Threading rules` documents the "do not enter the event loop after `BreakScheduler.start()`" rule; `context/foundation/test-plan.md §6 Cookbook` "Cross-cutting end-to-end flows" row replaces TBD with the canonical recipe; `lessons.md` gains an entry on the `_StubSignal` R-4 anti-pattern.
7. **Test-plan state machine flips** — `rollout_phases_complete` advances `3 → 4`, `§3 row 4` status flips `change opened → complete`, change `status` flips `planned → implementing → implemented`.

### Key Discoveries

- **Three signal connections are the entire R-4 surface** for the four flows researched: `app.py:277` `break_due → _on_break_due`, `:278` `reminder_due → _on_reminder_due`, `:349` `break_interval_changed → _on_break_interval_changed`. All structurally pinned today; none traversed end-to-end (research.md §E).
- **`_on_reminder_due` has ZERO ripgrep matches in `tests/`** — the single biggest invisible hop in the codebase; a regression at `app.py:278` would silently ship "user adds a reminder, time comes, nothing pops up, nothing logs" (research.md §A).
- **`SettingsDialog.accept()` emits `break_interval_changed` at `settings_dialog.py:1313` BEFORE `super().accept()` at `:1315`** — this ordering is pinned by `tests/test_settings_dialog.py:434-484` and is what allows the synchronous-slot pattern in `app.py:_on_break_interval_changed`. Flow B's e2e must respect this ordering.
- **Pause/resume do NOT capture or replay any timestamp** — `scheduler.py:147-155` only flip `self._paused` + persist via `Settings`. Post-resume `_tick()` reads `self._clock()` fresh at `:210`. (Relevant to research; not used by ABD but worth noting in case Flow C is added later.)
- **Phase 1 + Phase 2 fixtures share the epoch `2026-05-20 06:00 UTC`** for the `clock` fixture (`tests/test_recurring_reminder_integration.py:47-57`, `tests/test_modal_stacking_integration.py:120-128`). The fixture lift preserves this epoch.
- **`EventLog.record` uses real wall-clock** at `event_log.py:66` (`datetime.now(UTC).isoformat(...)`) — no `clock=` kwarg. Flow D's TAKEN-row assertion must oracle on `(event_type, outcome, detail)` tuple, NOT on `timestamp_iso`. (STRUCTURAL #2; deferred.)
- **The lessons.md entry "Bundle /10x orchestration edits into the change's first phase commit"** (added during Phase 3 impl-review) applies here: the `test-plan.md` §3 row-4 status flip + Goal/Order cell rewrites already landed in this branch's working tree from the `/10x-test-plan` orchestration step. P1's commit bundles them.

## What We're NOT Doing

- **No Flow C (Pause → Resume → post-resume tick).** Its R-4 value (tray Pause `QAction` wiring + post-resume tick continuation) is real but smaller than ABD; its gap is dominated by the R-3 composite (pause + non-zero snooze + reset interactions) which is genuinely a different risk's territory. Flagged for a future R-3-focused rollout (see `context/foundation/test-plan.md §2` R-3 "Must challenge").
- **No real-event-loop tests.** All e2e tests call `_tick()` / `_on_timer()` directly with virtual `Clock`. `qtbot.wait()` and `qtbot.waitSignal()` are NOT used after any slot that calls `BreakScheduler.start()` (the STRUCTURAL #3 race rule documented in P5).
- **No `QTest.mouseClick` on `BreakDialog` action buttons.** This is the Phase 2 anti-pattern (`context/archive/2026-06-02-testing-modal-stacking-wedge/research.md §3`) — pytest-qt synthesizes input inside Qt's object model and bypasses OS modal grab. Assertions stay structural (`QApplication.topLevelWidgets()`, `(event_type, outcome, detail)` tuples).
- **No `_StubSignal` shims, no slot-poking ("captured slot invoked by hand").** That's the R-4 anti-pattern this phase closes. Every e2e test emits the real signal across the real `connect`.
- **No `_active_seconds == 0` / `_snooze_until is None` oracles.** Implementation mirrors (`test-plan.md §2 R-3 anti-pattern`). Assertions oracle on the observable: dialog presence, CSV row content, INI key value.
- **No `EventLog.clock=` kwarg fix in Phase 4** (STRUCTURAL #2). Flow D oracles on `(event_type, outcome)` not on `timestamp_iso`; the seam is non-blocking.
- **No multi-OS CI matrix expansion.** `test-plan.md §7` pins `windows-latest` only.
- **No installer / NSIS / build / release workflow changes** beyond the `Test` step split.
- **No `pytest-qt`/`pytest` version bumps.**
- **No Flow C-related fixture work** — `activity`/`break_scheduler` fixtures lifted in P1 are useful for any future flow but P1 ships them because B/D need them, not because C will.

## Implementation Approach

Five phases, one commit per phase, following Phase 3's "prep → vertical slices → docs/CI as closing ritual" pattern. P1 establishes the entire harness foundation (fixture lift + marker declaration + `BreakReminderApp.clock=` structural fix) in a single foundation commit so P2/P3/P4 each scope to exactly one new test file. P5 lands the workflow YAML split last so the empty-tier exit-code-5 trap (research.md §G risk #2) never fires — the marker is declared in P1 (zero impact, no usage) and applied per-flow in P2/P3/P4, so when P5 splits the workflow there are already three `@pytest.mark.e2e` tests for the e2e step to match.

Each flow phase (P2/P3/P4) follows the same shape: a single new file `tests/test_<flow_name>_e2e.py` containing one `TestX` class with one or two assertion-load-bearing methods, all marked `@pytest.mark.e2e`. The load-bearing assertion across all three flows is the same shape: poll `QApplication.topLevelWidgets()` for an instance of `BreakDialog` (or `ReminderDialog` for Flow A) after driving the user-click entry and advancing virtual time through the scheduler's `_tick()` / `_on_timer()` method.

## Critical Implementation Details

- **`SettingsDialog` signal-emit ordering** (P3). `SettingsDialog.accept()` emits `break_interval_changed` at `settings_dialog.py:1313` BEFORE calling `super().accept()` at `:1315`. The slot at `app.py:_on_break_interval_changed` runs synchronously (auto-connection on Qt main thread → direct call) inside the `accept()` call, before `exec()` returns. Flow B's e2e must construct `SettingsDialog`, connect `break_interval_changed` to the real `_on_break_interval_changed` slot (via `BreakReminderApp` wiring or a direct `.connect()`), then call `accept()` directly (NOT `exec()` — `exec()` blocks the test thread). The order pinned by `tests/test_settings_dialog.py:434-484 TestBreakIntervalChangedSignal` is the authoritative reference.
- **Do not enter the event loop after `BreakScheduler.start()`** (P3, P4, future). `scheduler.py:100-102` `start()` calls `self._timer.start()` (the 1000ms `QTimer` armed at `:96-98`). If a test then calls `qtbot.wait()` / `qtbot.waitSignal()` / `qt_app.exec()`, the real timer fires `_tick()` on real wall-clock seconds, racing the test's deterministic `_tick()` invocations. Established pattern in `tests/test_break_scheduler.py` is to never enter the event loop; Phase 4 e2e tests follow the same convention. P5's `AGENTS.md § Threading rules` addendum codifies this.
- **Flow D's `BreakReminderApp` construction** (P4). The `break_reminder_app` fixture (B4) constructs the wired app with the four injected collaborators (`settings`, `event_log`, `reminder_store`, `voice`) AND the new `clock=` kwarg from P1's structural fix. The fixture does NOT call `app.start()` — that would spin up pynput listeners and arm the 1Hz `QTimer`. Tests drive `_action_reset.trigger()` directly and call `_break_scheduler._tick()` for time advance.
- **The Phase 1/2 epoch `2026-05-20 06:00 UTC` is preserved in the lifted `clock` fixture** (P1). The two existing integration files used this epoch deliberately (`tests/test_recurring_reminder_integration.py:55` docstring) so cross-suite math stays comparable. The lifted conftest `clock` fixture defaults to the same epoch; per-suite overrides remain possible.

---

## Phase 1: Prep — Harness foundation + marker + structural seam

### Overview

Lift 10 fixtures from Phase 1/2 integration files into `tests/conftest.py`, drop the now-duplicate locals, add the `BreakReminderApp.clock=` kwarg (with one pin test), and declare the `e2e` marker + `--strict-markers` in `pyproject.toml`. Zero behavior change beyond the new kwarg; no workflow YAML edits.

### Changes Required:

#### 1. Conftest fixture lift

**File**: `tests/conftest.py`

**Intent**: Add the 10 shared fixtures (A1-A6 + B1-B4 from research.md §F) as function-scoped helpers so P2/P3/P4 e2e tests can compose them without per-file duplication.

**Contract**: Add the following function-scoped fixtures in this order (all bind to `tmp_path` where applicable):

- `clock` → `Clock(datetime(2026, 5, 20, 6, 0, tzinfo=UTC))`
- `store_path` → `tmp_path / "reminders.json"`
- `store` → `ReminderStore(path=store_path)`
- `settings` → `Settings(ini_path=tmp_path / "BreakReminder.ini")`
- `voice` → `FakeVoice()` (also lift `FakeVoice` class from `tests/test_modal_stacking_integration.py:71-93` to module scope with the same docstring)
- `reminder_scheduler` → `ReminderScheduler(store=store, clock=clock)` (rename from `scheduler` for disambiguation; the two existing integration files update their fixture references)
- `activity` → `ActivityMonitor()` (no `start()` called — listeners stay dormant)
- `break_scheduler` → `BreakScheduler(settings=settings, activity=activity, clock=clock)`
- `event_log` → `EventLog(path=tmp_path / "events.log")`
- `break_reminder_app` → `BreakReminderApp(qapp, settings=settings, event_log=event_log, reminder_store=store, voice=voice, clock=clock)` — does NOT call `app.start()`; teardown is a no-op (app holds no resources requiring shutdown when `start()` wasn't called)

The existing `_qt_app` autouse fixture at `tests/conftest.py:31-34` and the `Clock` class at `:37-75` stay as-is.

#### 2. Drop now-duplicate local fixtures from Phase 1/2 integration files

**Files**: `tests/test_recurring_reminder_integration.py`, `tests/test_modal_stacking_integration.py`

**Intent**: After lifting the fixtures, remove the local duplicates so the conftest versions are authoritative. Both files keep their `pytestmark` / class structure / `blocking_modal` parametrized fixture intact.

**Contract**: Delete the following local fixtures (they become conftest versions):

- `tests/test_recurring_reminder_integration.py:47-75` — `clock`, `store_path`, `store`, `scheduler` (rename references to `reminder_scheduler` inside the file's test methods)
- `tests/test_modal_stacking_integration.py:71-134` — `FakeVoice` class, `settings`, `voice`, `store_path`, `store`, `clock`, `scheduler` (rename references; `blocking_modal` at `:137-198` stays)

#### 3. `BreakReminderApp.clock=` structural fix

**File**: `break_reminder/app.py`

**Intent**: Add a `clock=` kwarg to `BreakReminderApp.__init__` (parallels the four existing injectable collaborator kwargs) and propagate to both internal scheduler constructions so future wired-app e2e tests can drive virtual time deterministically.

**Contract**: At `BreakReminderApp.__init__` (`app.py:60-113`): add `clock: Callable[[], datetime] | None = None` to the signature alongside `settings` / `event_log` / `reminder_store` / `voice`. Store as `self._clock = clock`. At the two scheduler constructions at `app.py:103-104`, pass `clock=clock` through to both `BreakScheduler(...)` and `ReminderScheduler(...)`. Default `None` preserves the existing production behavior (schedulers fall through to `_utcnow`). The Google-style docstring at `:60-87` documents the new kwarg with the same shape as the existing four.

#### 4. Pin test for the `clock=` kwarg

**File**: `tests/test_app.py`

**Intent**: One small unit test asserting the injected `clock` reaches both schedulers — prevents future regression of the propagation.

**Contract**: Add a single test method in the existing `TestBreakReminderApp` class (or nearest equivalent fixture grouping) named `test_clock_kwarg_propagates_to_both_schedulers`. Construct a `BreakReminderApp` with an explicit `clock=` callable (a sentinel `lambda: datetime(2030, 1, 1, tzinfo=UTC)`); assert `app._break_scheduler._clock is sentinel` and `app._reminder_scheduler._clock is sentinel`.

#### 5. Declare the `e2e` marker + `--strict-markers`

**File**: `pyproject.toml`

**Intent**: Declare the marker in advance of any test using it (zero impact at this commit — no `@pytest.mark.e2e` exists yet). Enable `--strict-markers` so future typos like `@pytest.mark.e2ee` become collection errors instead of silent skips.

**Contract**: Under `[tool.pytest.ini_options]` (currently at `pyproject.toml:58-60`): change `addopts = "-q"` to `addopts = "-q --strict-markers"`. Add a new `markers = [...]` list with exactly one entry: `"e2e: end-to-end test of a top-three user-visible flow (Phase 4 tier)"`. Do NOT add `[tool.pytest.ini_options].markers` references to any other config; do NOT touch the two existing `*_integration.py` files' marker state.

#### 6. Bundle the orchestration edit

**File**: `context/foundation/test-plan.md`

**Intent**: Bundle the dirty path from the `/10x-test-plan` orchestration step (status `not started → change opened`, change folder cell fill, Goal + Order rewrites) into P1's commit per the `lessons.md` "Bundle /10x orchestration edits into the change's first phase commit" rule.

**Contract**: Already in working tree (no new edit); just ensure these paths are included in P1's `git add` set. The commit body line: "Bundle /10x-test-plan orchestration: status, change-folder, Goal + Order cells for §3 row 4."

### Success Criteria:

#### Automated Verification:

- All 562 + 1 existing tests pass: `uv run pytest`
- Existing Phase 1/2 integration files green after fixture lift: `uv run pytest tests/test_recurring_reminder_integration.py tests/test_modal_stacking_integration.py`
- New `BreakReminderApp.clock=` pin test passes: `uv run pytest tests/test_app.py -k test_clock_kwarg_propagates_to_both_schedulers`
- Marker registration verified: `uv run pytest --markers | Select-String e2e` returns the registered marker (PowerShell; use `grep -i e2e` in Git Bash)
- `--strict-markers` enforcement: `uv run pytest -m undeclared_marker_name` fails at collection (not silently skips)
- Lint: `uv run ruff check`
- Format: `uv run ruff format --check`
- Type check: `uv run pyright`
- pip-audit: `uv run pip-audit`

#### Manual Verification:

- Read `tests/conftest.py` and confirm the 10 new fixtures match research.md §F lift table (A1-A6 + B1-B4) in name, scope, and contract
- Read `break_reminder/app.py:60-113` and confirm `clock=` kwarg appears alongside the four existing injectable collaborators, with Google-style docstring entry
- Read `break_reminder/app.py:103-104` and confirm `clock=clock` propagates to both `BreakScheduler` and `ReminderScheduler` constructions
- Read `pyproject.toml` `[tool.pytest.ini_options]` and confirm `markers` list contains `e2e` and `addopts` contains `--strict-markers`
- Confirm two existing integration files' test bodies pass after dropping local fixtures (no `NameError` / `fixture not found` on any test)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Flow A e2e — Add Reminder → arm → fire → ReminderDialog

### Overview

Add the first e2e test file `tests/test_add_reminder_e2e.py` covering Flow A end-to-end. Closes the `_on_reminder_due` zero-coverage gap (the single biggest invisible hop per research.md §E).

### Changes Required:

#### 1. New e2e test file for Flow A

**File**: `tests/test_add_reminder_e2e.py` (new)

**Intent**: One test class `TestAddReminderE2E` marked `@pytest.mark.e2e` containing one load-bearing test method that drives the full Add Reminder flow: user opens `ReminderFormDialog`, fills in name + start time + RRULE, clicks Save (`accept()` directly, NOT `exec()`), assertion that the `ReminderStore` round-trips the row, assertion that the real `ReminderScheduler.reload()` arms against the new reminder, virtual-clock fast-forward past the scheduled time, direct call to `_on_timer()`, assertion that real `reminder_due` signal fires across the real `connect` to real `_on_reminder_due`, and final assertion that a `ReminderDialog` instance appears on `QApplication.topLevelWidgets()`.

**Contract**: File-level `pytestmark = pytest.mark.e2e` so every test in the file is automatically marked. Module docstring cites research.md §A and §E as the gap source. Test class `TestAddReminderE2E` with class docstring naming the three R-4 hops it closes (`reminder_due` connection at `app.py:278`, `_on_reminder_due` slot at `app.py:389-398`, `ReminderDialog.show()` at `app.py:398`). One primary test method `test_add_reminder_through_form_arms_scheduler_and_fires_dialog` using the conftest `clock`, `store`, `reminder_scheduler` fixtures from P1 plus `qapp` from pytest-qt. The test:

1. Constructs `ReminderFormDialog(store=store, scheduler=reminder_scheduler, clock=clock, parent=None)` directly (no `BreakReminderApp` needed — Flow A's R-4 contract is the `reminder_scheduler → _on_reminder_due → ReminderDialog` triangle, which can be wired by the test without the full app). `clock=clock` is load-bearing: the form's past-time gate at `reminder_form_dialog.py:920` (and the no-future-occurrences gate at `:943`) reads `self._clock()`; without virtual-clock propagation, the gate compares the test's `clock()` (epoch `2026-05-20`) against real wall-clock and rejects the save as "in the past".
2. Sets dialog form fields programmatically to a reminder firing 5 minutes after `clock()` (no RRULE — one-shot is enough; the recurring case is already covered by Phase 1).
3. Wires a direct `reminder_scheduler.reminder_due.connect(lambda name, event_at: <track>)` (mirrors the production connection at `app.py:278`).
4. Calls `dialog.accept()` directly. Asserts `store.list_all()` contains the new reminder AND `reminder_scheduler._next.reminder_id == saved.id`.
5. Calls `clock.advance(seconds=301)`; calls `reminder_scheduler._on_timer()` directly. Asserts the `reminder_due` slot ran with the expected `(name, event_at)` payload.
6. Then for the load-bearing assertion: instead of asserting the lambda slot fired, replace step 3 with a real `_on_reminder_due`-equivalent slot that constructs a `ReminderDialog` and registers it on a test-tracked list; assert that after `_on_timer()` runs, the tracked dialog is non-None AND present in `QApplication.topLevelWidgets()`. (This step models what `BreakReminderApp._on_reminder_due` does at `app.py:397-398` without spinning up the full wired app.)

The single canonical assertion the test exists to make: **the connection at `app.py:278` is observable end-to-end** — emitting `reminder_due` across a real `connect` causes a `ReminderDialog` to appear on `QApplication.topLevelWidgets()`. No `_StubSignal`, no `.assert_called`, no slot mocking.

### Success Criteria:

#### Automated Verification:

- New test file passes: `uv run pytest tests/test_add_reminder_e2e.py -m e2e`
- Whole suite still green: `uv run pytest`
- Marker correctly applied: `uv run pytest -m e2e --collect-only` lists the new test
- Lint: `uv run ruff check tests/test_add_reminder_e2e.py`
- Format: `uv run ruff format --check tests/test_add_reminder_e2e.py`
- Type check: `uv run pyright`

#### Manual Verification:

- Read `tests/test_add_reminder_e2e.py` and confirm NO `_StubSignal`, NO `Mock()` of `_on_reminder_due`, NO slot capture-and-invoke pattern
- Read the load-bearing assertion and confirm it oracles on `QApplication.topLevelWidgets()` membership (or equivalent observable dialog presence), NOT on `slot.assert_called_with(...)`
- Confirm the test would fail if `app.py:278` connect line were commented out — i.e. the assertion truly depends on the real `connect` being live

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Flow B e2e — Save Settings interval → reset → break_due → BreakDialog

### Overview

Add `tests/test_save_settings_interval_e2e.py` covering Flow B end-to-end. Closes the four `_StubSignal` shim-shaped gaps (`tests/test_app.py:431`, `tests/test_settings_dialog.py:2446`, `:2749`, `:2802`) and the `break_due → _on_break_due → BreakDialog` connection at `app.py:277` for the interval-change scenario specifically.

### Changes Required:

#### 1. New e2e test file for Flow B

**File**: `tests/test_save_settings_interval_e2e.py` (new)

**Intent**: One test class `TestSaveSettingsIntervalE2E` marked `@pytest.mark.e2e` containing one load-bearing test method that drives the full Save Settings flow: user opens `SettingsDialog`, changes the break interval spinbox value, clicks Save (`accept()` directly), assertion that the real `break_interval_changed` signal emits across the real `connect` into the real `_on_break_interval_changed` slot, assertion that `BreakScheduler.reset_cycle()` runs, virtual-clock-driven `_tick()` loop until `_active_seconds * 60 >= new_threshold`, assertion that `break_due` fires AND a `BreakDialog` appears on `QApplication.topLevelWidgets()`.

**Contract**: File-level `pytestmark = pytest.mark.e2e`. Module docstring cites research.md §B and §E. Test class `TestSaveSettingsIntervalE2E` with class docstring naming the four R-4 hops closed (`break_interval_changed` connection at `app.py:349`, `_on_break_interval_changed` slot at `app.py:423-446`, `break_due` connection at `app.py:277`, `_on_break_due` slot at `app.py:384-387`). Primary test method `test_save_settings_new_interval_resets_cycle_and_fires_break_dialog_on_new_threshold`. Uses conftest fixtures `clock`, `settings`, `voice`, `store`, `reminder_scheduler`, `activity`, `break_scheduler`, plus `qapp`. The test:

1. Pre-seeds `settings.break_interval_min = 10` (old threshold).
2. Constructs `SettingsDialog(settings=settings, voice=voice, reminder_store=store, reminder_scheduler=reminder_scheduler, parent=None)` directly (NOT via `BreakReminderApp` — Flow B's R-4 contract is the dialog → settings → scheduler triangle plus the two app slots; the test wires the slots directly). Kwarg names match the production callsite at `app.py:343-348` and the ctor at `settings_dialog.py:512-520` — `reminder_store=` / `reminder_scheduler=`, NOT `store=` / `scheduler=`.
3. Wires a direct `dialog.break_interval_changed.connect(<real _on_break_interval_changed equivalent that calls break_scheduler.reset_cycle()>)` — mirrors the production connection at `app.py:349`.
4. Wires `break_scheduler.break_due.connect(<real _on_break_due equivalent that constructs a BreakDialog and registers it>)` — mirrors `app.py:277`.
5. Programmatically sets the dialog's `_break_interval_spinbox` value to `5` (new threshold).
6. Calls `dialog.accept()` directly. Asserts `settings.break_interval_min == 5` AND `break_scheduler._active_seconds == 0` (the reset took effect — implementation peek is acceptable here as a precondition, not the load-bearing oracle).
7. In a loop, calls `activity.activity_detected.emit(clock())` (real Qt signal across the real `connect` to `break_scheduler._on_activity` at `scheduler.py:94, 203-204` — refreshes `break_scheduler._last_input_at` via the production path, NOT a direct attribute write) then calls `break_scheduler._tick()`; advances `clock` by 1 second each iteration. After fewer than `5 * 60 = 300` iterations, the `BreakDialog` registered in step 4 must be non-None AND on `QApplication.topLevelWidgets()`. Crucially: it must NOT appear before iteration 300 (the OLD threshold of 600 would be wrong) — the test asserts both the appearance AND the timing window.

The single canonical assertion the test exists to make: **the chain at `app.py:349 → :423-446 → BreakScheduler.reset_cycle → tick → :277 → :384-387` is observable end-to-end on the NEW threshold**. No `_StubSignal`, no `slots[0](5)` invocation pattern.

### Success Criteria:

#### Automated Verification:

- New test file passes: `uv run pytest tests/test_save_settings_interval_e2e.py -m e2e`
- Whole suite still green: `uv run pytest`
- Marker correctly applied: `uv run pytest -m e2e --collect-only` lists both Flow A and Flow B tests
- Lint: `uv run ruff check tests/test_save_settings_interval_e2e.py`
- Format: `uv run ruff format --check tests/test_save_settings_interval_e2e.py`
- Type check: `uv run pyright`

#### Manual Verification:

- Read `tests/test_save_settings_interval_e2e.py` and confirm NO `_StubSignal` shim, NO `slots[0](5)`-style slot capture-and-invoke
- Confirm the test calls `dialog.accept()` directly (NOT `dialog.exec()` which blocks)
- Confirm the test uses `break_scheduler._tick()` directly (NOT `qtbot.wait()` or `qtbot.waitSignal()`)
- Confirm the test asserts the dialog DOES appear within 300 iterations AND DOES NOT appear before iteration ~295 (the timing window is the load-bearing R-3/R-4 oracle — "new threshold honored")
- Confirm the test would fail if either `app.py:349` or `app.py:277` connect lines were commented out

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Flow D e2e — Tray Reset → TAKEN logged + cycle re-arms → next break_due fires → BreakDialog

### Overview

Add `tests/test_tray_reset_e2e.py` covering Flow D end-to-end. Extends the existing `test_reset_triggers_apply_break_taken` (`tests/test_app.py:358-371`) shape with the "next break actually fires" tail — the only of the three flows that uses the full `break_reminder_app` fixture (B4) and exercises the `BreakReminderApp.clock=` kwarg from P1.

### Changes Required:

#### 1. New e2e test file for Flow D

**File**: `tests/test_tray_reset_e2e.py` (new)

**Intent**: One test class `TestTrayResetE2E` marked `@pytest.mark.e2e` containing one load-bearing test method that drives the full Tray Reset flow: user triggers the tray Reset `QAction`, assertion that the TAKEN CSV row appears in `events.log`, virtual-clock-driven `_tick()` loop until threshold elapses, assertion that `break_due` fires AND a `BreakDialog` appears on `QApplication.topLevelWidgets()` — proving the cycle is FULLY re-armed through the next user-visible event, not just internal counter resets.

**Contract**: File-level `pytestmark = pytest.mark.e2e`. Module docstring cites research.md §D and §E. Test class `TestTrayResetE2E` with class docstring naming the R-4 hops closed (tray `_action_reset.triggered` connection at `app.py:208-210`, `_on_reset` slot at `app.py:297-306`, `_apply_break_taken` backbone at `app.py:448-462`, `_break_scheduler.start()` re-arm at `:461`, `break_due → _on_break_due → BreakDialog` tail). Primary test method `test_tray_reset_logs_taken_and_rearms_cycle_to_fire_next_break_dialog`. Uses the `break_reminder_app` conftest fixture (B4) which constructs the full wired app with `clock=` kwarg from P1's structural fix; plus `clock`, `event_log` fixtures for direct assertions. The test:

1. Pre-seeds `settings.break_interval_min = 3` (small threshold for test speed); reconstructs `break_reminder_app` with this setting (or the fixture is parametrized to accept it).
2. Drives `app._break_scheduler._active_seconds = 120` (pretends 2 minutes of pre-existing accumulation) as a precondition — this is the "user has been active for a while before clicking Reset" setup. Note: the wired-app instance, NOT the standalone `break_scheduler` conftest fixture (they are different objects; the app builds its own at `app.py:103`).
3. Locates the Reset `QAction` via the existing helper pattern (`_find_action(app, "Reset")` from `tests/test_app.py:339-349`) and calls `.trigger()`. NOT `QTest.mouseClick`.
4. **First load-bearing assertion (existing-shape extension)**: read `event_log` CSV and assert exactly one new row with `(event_type, outcome) == (EventType.BREAK, Outcome.TAKEN)`. Assert `break_scheduler._active_seconds == 0` as a precondition for step 5 (not the load-bearing oracle).
5. In a loop, call `app._activity.activity_detected.emit(clock())` (real Qt signal into `app._break_scheduler._on_activity` — the wired app's own `ActivityMonitor` instance, NOT the standalone conftest `activity` fixture) then call `app._break_scheduler._tick()`; advance `clock` by 1 second each iteration. After fewer than `3 * 60 = 180` iterations, a `BreakDialog` must be present on `QApplication.topLevelWidgets()`. It must NOT be present before iteration ~175 (the timing-window oracle — the cycle is re-armed from the full new interval, not from `_active_seconds = 120` which would fire at iteration 60).

The single canonical assertion the test exists to make: **the chain at tray Reset → `_apply_break_taken` → `_break_scheduler.start()` re-arm → tick → `break_due` → `BreakDialog` is observable end-to-end**, AND the re-armed cycle starts from zero (not from the pre-Reset accumulator state).

### Success Criteria:

#### Automated Verification:

- New test file passes: `uv run pytest tests/test_tray_reset_e2e.py -m e2e`
- Whole suite still green: `uv run pytest`
- All three e2e tests visible together: `uv run pytest -m e2e --collect-only` lists Flow A, B, D test files
- Lint: `uv run ruff check tests/test_tray_reset_e2e.py`
- Format: `uv run ruff format --check tests/test_tray_reset_e2e.py`
- Type check: `uv run pyright`

#### Manual Verification:

- Read `tests/test_tray_reset_e2e.py` and confirm it uses `QAction.trigger()` (NOT `QTest.mouseClick`), uses `_tick()` directly (NOT `qtbot.wait()`), oracles on `(event_type, outcome)` tuple for the CSV row (NOT on `timestamp_iso`)
- Confirm the test uses the `break_reminder_app` fixture from conftest (proving the P1 `clock=` kwarg propagation is exercised)
- Confirm the test asserts the dialog DOES NOT appear at iteration ~60 (which it would if the re-arm started from the pre-Reset `_active_seconds = 120` instead of from 0) — the timing window is the load-bearing "cycle is truly re-armed" oracle
- Confirm the test would fail if `app.py:461` `_break_scheduler.start()` were removed (the timer wouldn't re-arm; the tick loop would never fire `break_due`)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 5: Docs + CI workflow split + status flip

### Overview

Land the CI `release.yml` job split (now safe — three `@pytest.mark.e2e` tests exist), the `AGENTS.md § Threading rules` addendum (STRUCTURAL #3 derivation), the `test-plan.md §6` cookbook entry replacing TBD, the `lessons.md` entry on the `_StubSignal` R-4 anti-pattern, and the test-plan state-machine flip (rollout_phases_complete 3→4, §3 row 4 status → complete). Closes the rollout phase.

### Changes Required:

#### 1. CI workflow split

**File**: `.github/workflows/release.yml`

**Intent**: Replace the single `Test` step at `release.yml:58-59` with two sequential steps in the same `build` job — `Test (unit)` running `pytest -m "not e2e"` and `Test (e2e)` running `pytest -m e2e`. Stays on `windows-latest`; shares the cached venv; gives two distinct red/green check marks per PR. Per research.md §G, matrix expansion is ruled out by PRD § Non-Goals.

**Contract**: Replace the single `- name: Test` + `run: uv run pytest` step with:

```yaml
      - name: Test (unit)
        run: uv run pytest -m "not e2e"

      - name: Test (e2e)
        run: uv run pytest -m e2e
```

No other workflow changes. The two existing `*_integration.py` files (Phase 1 + Phase 2) continue riding in the unit step (they don't carry `@pytest.mark.e2e`), preserving the granularity argued in research.md §G.

#### 2. `AGENTS.md § Threading rules` addendum

**File**: `AGENTS.md`

**Intent**: Document the "do not enter the event loop after `BreakScheduler.start()`" rule that STRUCTURAL #3 (research.md §F) derived. Future test authors hitting `qtbot.wait()` after a slot that calls `start()` will find the rule and the rationale here.

**Contract**: Append a new bullet to the existing `## Threading rules` section. The bullet names the rule, names the `scheduler.py:100-102` site, and explains why (`qtbot.wait()` after `start()` races real wall-clock seconds against deterministic `_tick()` invocations). One sentence cites `tests/test_break_scheduler.py` as the established pattern; one sentence points at the Phase 4 e2e files as additional examples.

#### 3. `test-plan.md §6` cookbook row

**File**: `context/foundation/test-plan.md`

**Intent**: Replace the "TBD" placeholder at §6 row "Cross-cutting end-to-end flows" with the canonical recipe shipped by P2/P3/P4. Matches Phase 1/2/3 discipline of per-phase cookbook updates.

**Contract**: At §6 line 159 (the "Cross-cutting end-to-end flows" row currently reading "TBD — Phase 4 will ship..."), replace with a detailed description naming the three test files (`tests/test_add_reminder_e2e.py`, `tests/test_save_settings_interval_e2e.py`, `tests/test_tray_reset_e2e.py`), the load-bearing assertion shape ("poll `QApplication.topLevelWidgets()` for `BreakDialog`/`ReminderDialog` after driving the user-click entry and advancing virtual time through `_tick()` / `_on_timer()`"), the three R-4 connections closed (`app.py:277`/`:278`/`:349`), the anti-patterns avoided (`_StubSignal`, `QTest.mouseClick`, slot mocking, `_active_seconds == 0` mirrors), and the conftest fixture set this depends on (the 10 fixtures lifted in P1). Match the verbosity of the §6 "Storage hand-edit robustness" row landed in Phase 3.

#### 4. `lessons.md` entry on the `_StubSignal` R-4 anti-pattern

**File**: `context/foundation/lessons.md`

**Intent**: Add a new append-only entry codifying the rule that signal-connection-only assertions hide cross-module wiring gaps. Future impl-reviews re-read `lessons.md` and will flag any new `_StubSignal`-shaped test.

**Contract**: Append a new `## Signal-connection assertions are not end-to-end coverage` (or equivalent title) section after the existing "Storage-boundary loaders need per-row containment + per-field coercion" entry. Include:

- **Context**: any cross-module signal connection in `break_reminder/app.py` (today: `:277` `break_due`, `:278` `reminder_due`, `:349` `break_interval_changed`) or analogous wiring sites in future modules.
- **Problem**: tests that capture the connected slot and invoke it by hand (e.g. the four `_StubSignal` shims at `tests/test_app.py:431`, `tests/test_settings_dialog.py:2446`, `:2749`, `:2802`, and tests using `slots[0](value)` invocation) pass while the actual signal-emit path is silently broken. A regression that removes the `connect()` call would not be caught.
- **Rule**: cross-module wiring contracts require an end-to-end test that emits the real signal across the real `connect` and observes the real downstream slot's user-visible effect (dialog appearance on `QApplication.topLevelWidgets()`, CSV row appended, INI key written). Slot capture-and-invoke is acceptable for unit-testing the slot in isolation but does NOT count as wiring coverage. Cross-cite the three Phase 4 e2e files as canonical examples.
- **Applies to**: plan, implement, impl-review

#### 5. Test-plan state-machine flip

**File**: `context/foundation/test-plan.md`

**Intent**: Advance the rollout state machine: frontmatter counter + §3 row 4 status. Mirrors Phase 3's closing edit.

**Contract**: Frontmatter: `rollout_phases_complete: 3` → `rollout_phases_complete: 4`. §3 row 4 (the `testing-top-three-e2e-flows` row) Status cell: `change opened` → `complete`. Other §3 cells unchanged.

#### 6. Change-status flip

**File**: `context/changes/testing-top-three-e2e-flows/change.md`

**Intent**: Advance the change-folder state machine: `planned` → `implementing` (set at P1 start) → `implemented` (set as part of P5 commit). `updated` field gets today's date.

**Contract**: At P5 commit time: `status: implementing` → `status: implemented`; `updated: <today>`.

### Success Criteria:

#### Automated Verification:

- `pytest -m "not e2e"` passes (matches the new unit step): `uv run pytest -m "not e2e"`
- `pytest -m e2e` passes (matches the new e2e step, now non-empty with 3 tests): `uv run pytest -m e2e`
- Whole suite still green: `uv run pytest`
- Lint: `uv run ruff check`
- Format: `uv run ruff format --check`
- Type check: `uv run pyright`
- pip-audit: `uv run pip-audit`
- `.github/workflows/release.yml` parses as valid YAML (CI itself will verify on push, but local sanity: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`)

#### Manual Verification:

- Read `.github/workflows/release.yml` and confirm the two sequential `run:` steps with the correct `-m` flags
- Read `AGENTS.md § Threading rules` and confirm the new bullet reads coherently with the existing bullets (no stylistic drift)
- Read `context/foundation/test-plan.md §6` row "Cross-cutting end-to-end flows" and confirm the new content matches the verbosity + structure of the Phase 3 "Storage hand-edit robustness" row
- Read `context/foundation/lessons.md` and confirm the new entry follows the existing 4-field convention (Context / Problem / Rule / Applies to)
- Read `context/foundation/test-plan.md` frontmatter and §3 row 4 and confirm both state-machine fields advance correctly
- Read `context/changes/testing-top-three-e2e-flows/change.md` and confirm `status: implemented` + `updated: <today>`
- Push the branch to a feature branch on GitHub and confirm the `build` job shows TWO test check marks (Test (unit) + Test (e2e)) in the CI summary

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful — this is the rollout-closing phase. After manual confirmation, the change is ready for `/10x-impl-review testing-top-three-e2e-flows` and subsequent `/10x-archive`.

---

## Testing Strategy

### Unit Tests:

- **`BreakReminderApp.clock=` kwarg propagation** — one new test in `tests/test_app.py` (P1) asserting both schedulers receive the injected clock callable.
- **No new unit tests beyond that.** The fixture lifts in P1 are pure renames; all existing 562 + 1 unit tests must remain green. The flow tests in P2/P3/P4 are integration/e2e tier, not unit tier.

### Integration Tests:

- **`tests/test_add_reminder_e2e.py`** (P2) — one test method covering Flow A end-to-end. Closes `app.py:278` R-4 wire.
- **`tests/test_save_settings_interval_e2e.py`** (P3) — one test method covering Flow B end-to-end. Closes `app.py:349` + `app.py:277` R-4 wires for the interval-change scenario.
- **`tests/test_tray_reset_e2e.py`** (P4) — one test method covering Flow D end-to-end. Closes the post-Reset re-arm tail of `app.py:277`.

All three follow the same shape: drive the user click entry → connect real slots via real `.connect()` → advance virtual `Clock` → call `_tick()` / `_on_timer()` directly → assert `BreakDialog`/`ReminderDialog` appears on `QApplication.topLevelWidgets()`. None use `qtbot.wait()` / `qtbot.waitSignal()` / `QTest.mouseClick` / `_StubSignal` / slot mocking.

### Manual Testing Steps:

For each phase, after automated verification passes:

1. Read each new/modified file and confirm the intent of the change matches the Contract.
2. Specifically for P2/P3/P4: read each e2e test and confirm zero anti-patterns from research.md §E ("Anti-patterns to avoid"). The five anti-patterns to scan for: `_StubSignal`, `Mock()` of any slot or signal, `QTest.mouseClick` on action buttons, `qtbot.wait()` after a `start()`-calling slot, `_active_seconds == 0`-style implementation mirrors.
3. Specifically for P5: push to a feature branch and confirm GitHub Actions shows TWO test check marks under the `build` job.

---

## References

- Related research: `context/changes/testing-top-three-e2e-flows/research.md` (especially §E ranked gaps, §F harness audit + STRUCTURAL findings, §G CI marker recommendation)
- Phase 1 historical precedent: `context/archive/2026-06-01-testing-rrule-reminder-loop/` (harness shape, virtual-clock pattern)
- Phase 2 historical precedent: `context/archive/2026-06-02-testing-modal-stacking-wedge/` (`FakeVoice` reuse pattern, `QTest.mouseClick` anti-pattern)
- Phase 3 historical precedent: `context/archive/2026-06-02-testing-storage-malformed-input/` (prep → RED → GREEN → docs phase structure; structural fix bundled into a test rollout; impl-review observation triage discipline)
- `context/foundation/test-plan.md §2 R-4` "Must challenge" cell + §3 row 4 Goal/Order rewrite + §6 cookbook target row + §7 negative space
- `context/foundation/lessons.md` "Bundle /10x orchestration edits into the change's first phase commit" + "Storage-boundary loaders need per-row containment + per-field coercion" + "Document every public Python function with a Google-style docstring"
- `AGENTS.md § Threading rules` + § "FR-008 — active-time accounting" + § "FR-014 — recurrence engine" + § "FR-004 — tray quick-menu"
- R-4 anti-pattern reference: `tests/test_app.py:285-314` (`test_end_to_end_via_settings_dialog_stub` — the canonical "slot captured and invoked by hand" example Phase 4 closes coverage on)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Prep — Harness foundation + marker + structural seam

#### Automated

- [x] 1.1 All 562 + 1 existing tests pass: `uv run pytest` — 8c8e9c5
- [x] 1.2 Existing Phase 1/2 integration files green after fixture lift: `uv run pytest tests/test_recurring_reminder_integration.py tests/test_modal_stacking_integration.py` — 8c8e9c5
- [x] 1.3 New `BreakReminderApp.clock=` pin test passes: `uv run pytest tests/test_app.py -k test_clock_kwarg_propagates_to_both_schedulers` — 8c8e9c5
- [x] 1.4 Marker registration verified: `uv run pytest --markers | Select-String e2e` returns the registered marker — 8c8e9c5
- [x] 1.5 `--strict-markers` enforcement: `uv run pytest -m undeclared_marker_name` fails at collection — 8c8e9c5
- [x] 1.6 Lint: `uv run ruff check` — 8c8e9c5
- [x] 1.7 Format: `uv run ruff format --check` — 8c8e9c5
- [x] 1.8 Type check: `uv run pyright` — 8c8e9c5
- [x] 1.9 pip-audit: `uv run pip-audit` — 8c8e9c5

#### Manual

- [x] 1.10 Read `tests/conftest.py` and confirm the 10 new fixtures match research.md §F lift table — 8c8e9c5
- [x] 1.11 Read `break_reminder/app.py:60-113` and confirm `clock=` kwarg alongside the four existing injectable collaborators — 8c8e9c5
- [x] 1.12 Read `break_reminder/app.py:103-104` and confirm `clock=clock` propagates to both scheduler constructions — 8c8e9c5
- [x] 1.13 Read `pyproject.toml` `[tool.pytest.ini_options]` and confirm `markers` list contains `e2e` and `addopts` contains `--strict-markers` — 8c8e9c5
- [x] 1.14 Confirm two existing integration files' tests pass after dropping local fixtures (no `NameError` / `fixture not found`) — 8c8e9c5

### Phase 2: Flow A e2e — Add Reminder → arm → fire → ReminderDialog

#### Automated

- [x] 2.1 New test file passes: `uv run pytest tests/test_add_reminder_e2e.py -m e2e` — ada56ce
- [x] 2.2 Whole suite still green: `uv run pytest` — ada56ce
- [x] 2.3 Marker correctly applied: `uv run pytest -m e2e --collect-only` lists the new test — ada56ce
- [x] 2.4 Lint: `uv run ruff check tests/test_add_reminder_e2e.py` — ada56ce
- [x] 2.5 Format: `uv run ruff format --check tests/test_add_reminder_e2e.py` — ada56ce
- [x] 2.6 Type check: `uv run pyright` — ada56ce

#### Manual

- [x] 2.7 Read `tests/test_add_reminder_e2e.py` and confirm NO `_StubSignal`, NO `Mock()` of `_on_reminder_due`, NO slot capture-and-invoke — ada56ce
- [x] 2.8 Read the load-bearing assertion and confirm it oracles on `QApplication.topLevelWidgets()` membership, NOT on `slot.assert_called_with(...)` — ada56ce
- [x] 2.9 Confirm the test would fail if `app.py:278` connect line were commented out — ada56ce

### Phase 3: Flow B e2e — Save Settings interval → reset → break_due → BreakDialog

#### Automated

- [x] 3.1 New test file passes: `uv run pytest tests/test_save_settings_interval_e2e.py -m e2e`
- [x] 3.2 Whole suite still green: `uv run pytest`
- [x] 3.3 Marker correctly applied: `uv run pytest -m e2e --collect-only` lists both Flow A and Flow B tests
- [x] 3.4 Lint: `uv run ruff check tests/test_save_settings_interval_e2e.py`
- [x] 3.5 Format: `uv run ruff format --check tests/test_save_settings_interval_e2e.py`
- [x] 3.6 Type check: `uv run pyright`

#### Manual

- [x] 3.7 Read `tests/test_save_settings_interval_e2e.py` and confirm NO `_StubSignal` shim, NO `slots[0](5)`-style slot capture-and-invoke
- [x] 3.8 Confirm the test calls `dialog.accept()` directly (NOT `dialog.exec()`)
- [x] 3.9 Confirm the test uses `break_scheduler._tick()` directly (NOT `qtbot.wait()` / `qtbot.waitSignal()`)
- [x] 3.10 Confirm the test asserts the dialog DOES appear within 300 iterations AND DOES NOT appear before iteration ~295
- [x] 3.11 Confirm the test would fail if either `app.py:349` or `app.py:277` connect lines were commented out

**Phase 3 commit: `afd72be`**

### Phase 4: Flow D e2e — Tray Reset → TAKEN logged + cycle re-arms → next break_due fires → BreakDialog

#### Automated

- [x] 4.1 New test file passes: `uv run pytest tests/test_tray_reset_e2e.py -m e2e`
- [x] 4.2 Whole suite still green: `uv run pytest` (566 passed)
- [x] 4.3 All three e2e tests visible: `uv run pytest -m e2e --collect-only` lists Flow A/B/D files
- [x] 4.4 Lint: `uv run ruff check tests/test_tray_reset_e2e.py`
- [x] 4.5 Format: `uv run ruff format --check tests/test_tray_reset_e2e.py`
- [x] 4.6 Type check: `uv run pyright`

#### Manual

- [x] 4.7 Read `tests/test_tray_reset_e2e.py` and confirm it uses `QAction.trigger()` (NOT `QTest.mouseClick`), uses `_tick()` directly (NOT `qtbot.wait()`), oracles on `(event_type, outcome)` tuple (NOT on `timestamp_iso`)
- [x] 4.8 Confirm the test uses the `break_reminder_app` fixture from conftest (exercising P1 `clock=` kwarg propagation)
- [x] 4.9 Confirm the test asserts the dialog DOES NOT appear at iteration ~60 (would fire there if re-arm started from pre-Reset `_active_seconds = 120`) — also caught by `_active_seconds == 0` precondition; mutation tested
- [x] 4.10 Confirm the test would fail if `app.py:461` `_break_scheduler.start()` were removed — original design bypassed the timer via direct `_tick()`; FIXED by adding `_timer.isActive()` precondition; mutation tested (caught with targeted diagnostic)

### Phase 5: Docs + CI workflow split + status flip

#### Automated

- [ ] 5.1 `pytest -m "not e2e"` passes: `uv run pytest -m "not e2e"`
- [ ] 5.2 `pytest -m e2e` passes (3 tests now non-empty): `uv run pytest -m e2e`
- [ ] 5.3 Whole suite still green: `uv run pytest`
- [ ] 5.4 Lint: `uv run ruff check`
- [ ] 5.5 Format: `uv run ruff format --check`
- [ ] 5.6 Type check: `uv run pyright`
- [ ] 5.7 pip-audit: `uv run pip-audit`
- [ ] 5.8 `release.yml` parses as valid YAML

#### Manual

- [ ] 5.9 Read `.github/workflows/release.yml` and confirm two sequential `run:` steps with correct `-m` flags
- [ ] 5.10 Read `AGENTS.md § Threading rules` new bullet and confirm stylistic coherence with existing bullets
- [ ] 5.11 Read `context/foundation/test-plan.md §6` cookbook row and confirm it matches the verbosity + structure of the Phase 3 "Storage hand-edit robustness" row
- [ ] 5.12 Read `context/foundation/lessons.md` new entry and confirm it follows the 4-field convention (Context / Problem / Rule / Applies to)
- [ ] 5.13 Read `context/foundation/test-plan.md` frontmatter (rollout_phases_complete: 4) + §3 row 4 status (complete)
- [ ] 5.14 Read `context/changes/testing-top-three-e2e-flows/change.md` and confirm `status: implemented` + `updated: <today>`
- [ ] 5.15 Push branch to GitHub and confirm `build` job shows TWO test check marks (Test (unit) + Test (e2e))
