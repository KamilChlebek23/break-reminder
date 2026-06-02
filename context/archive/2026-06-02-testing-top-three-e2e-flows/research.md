---
date: 2026-06-02T14:26:35+00:00
researcher: composer-2.5-fast (10x-research)
git_commit: fcf7329c42f3a938f9305cade66854034f31c7d7
branch: master
repository: KamilChlebek23/break-reminder
topic: "Phase 4 e2e tier — top-three (four candidate) user-visible flows"
tags: [research, codebase, integration-tests, pytest-qt, R-4, FR-004, FR-008, FR-014, e2e]
status: complete
last_updated: 2026-06-02
last_updated_by: composer-2.5-fast (10x-research)
---

# Research: Phase 4 e2e tier — top-three (four candidate) user-visible flows

**Date**: 2026-06-02T14:26:35+00:00
**Researcher**: composer-2.5-fast (10x-research)
**Git Commit**: `fcf7329` (`master`)
**Branch**: `master`
**Repository**: `KamilChlebek23/break-reminder`

## Research Question

Phase 4 of the test rollout (`testing-top-three-e2e-flows`) ships one end-to-end test per top-three user-visible flow, behind a pytest marker, on a CI job split from the existing unit tier. Four candidate flows are in scope per user decision (see `change.md`):

- **Flow A** — Add Reminder via form → `ReminderScheduler` arms it → it fires at the scheduled time.
- **Flow B** — Save Settings interval change → `BreakScheduler` resets → next `break_due` fires on the new threshold → `BreakDialog` appears.
- **Flow C** — Pause → Resume → post-resume tick honors the new interval → `BreakDialog` appears.
- **Flow D** — Tray "Reset" → `_apply_break_taken` → cycle re-arms + TAKEN row in `events.log`.

For each flow: ground the entry → cross-module hops → observable outcome against live code; cross-walk existing per-module coverage to identify the exact R-4 signal-connection-only gap; audit the Phase 1/2 harness for fixture reuse; recommend a marker + CI split; surface structural blockers (Phase 3-style findings).

## Summary

1. **All four flows terminate at one of two dialog `.show()` callsites** — `BreakDialog.show()` at `app.py:413` (B/C/D) or `ReminderDialog.show()` at `app.py:398` (A) — so a single "wait for a top-level dialog of type X" oracle covers every flow's user-visible outcome without per-flow duplication.

2. **Three load-bearing signal connections in `app.py` are structurally pinned today but never traversed end-to-end in one assertion** — this is the R-4 anti-pattern Phase 4 closes:
   - `app.py:277` `break_scheduler.break_due.connect(_on_break_due)` — emit-tested in `test_break_scheduler.py` but never observed-end-to-end into a `BreakDialog` (gap for B/C/D).
   - `app.py:278` `reminder_scheduler.reminder_due.connect(_on_reminder_due)` — **`_on_reminder_due` has zero coverage** by ripgrep (the single biggest invisible hop in the codebase; gap for A).
   - `app.py:349` `dialog.break_interval_changed.connect(_on_break_interval_changed)` — `test_app.py:285-314` is a `_StubSignal`-shimmed test that **calls the captured slot by hand** instead of emitting the real signal (gap for B).

3. **Flow D's tray-Reset chain is the only one already partially end-to-end today** — `tests/test_app.py:358-371` `test_reset_triggers_apply_break_taken` drives the `QAction.trigger()` through `_apply_break_taken` and asserts on the TAKEN CSV row in one pass. It stops short of advancing the clock to verify the next `break_due` fires on the re-armed timer. Use it as the shape for the other three flows.

4. **The harness is in good shape** — both `BreakScheduler` and `ReminderScheduler` accept a `clock=` callable at construction (`scheduler.py:66, 262`). The Phase 1 `Clock` class (`tests/conftest.py:37-75`) is sufficient for all four flows; tests bypass real `QTimer`s by calling `_tick()` / `_on_timer()` directly (the established pattern, also explicitly endorsed by test-plan §7 "No deep Qt-internals mocking"). **Six fixtures should be lifted from the Phase 1/2 integration files into `tests/conftest.py`**, plus four net-new fixtures (~38 LoC pure lift, zero behavior change).

5. **One structural blocker worth shipping a fix for in Phase 4** — `BreakReminderApp.__init__` (`app.py:60-104`) accepts injectable `settings`, `event_log`, `reminder_store`, `voice` but **has no `clock=` kwarg**, so schedulers constructed inside the wired app run on real wall-clock. Recommended fix (~3 LoC) lets Flow D and any future wired-app e2e drive virtual time deterministically. **If deferred**, Flow D ships safely against the clock-independent TAKEN-row oracle; B and C bypass `BreakReminderApp` entirely (construct `BreakScheduler` directly) and are unblocked either way.

6. **CI split lands with a 2-step `release.yml` change + a 4-line `pyproject.toml` change** — declare `e2e` under `[tool.pytest.ini_options].markers`, add `--strict-markers` to `addopts`, and replace the single `uv run pytest` step (`release.yml:58-59`) with `pytest -m "not e2e"` + `pytest -m e2e` in the same `build` job (matrix expansion is ruled out by PRD § Non-Goals). Marker name **`e2e`** (not `integration`) preserves granularity vs the existing two `*_integration.py` files which are narrow risk pins (R-1, R-2), not the Phase 4 user-visible-flow tier.

## Detailed Findings

### §A. Flow A — Add Reminder via form → ReminderScheduler arms → fires at scheduled time

**Entry point.** User clicks "Open settings…" in the tray (`app.py:218-220`) → `SettingsDialog` exec'd → user clicks "Add…" button (`break_reminder/ui/settings_dialog.py:883-885`) → `_on_reminders_add_clicked` (`settings_dialog.py:923`) constructs `ReminderFormDialog(store, scheduler)` (`settings_dialog.py:944-948`) and exec's it. User fills the form and clicks OK (`break_reminder/ui/reminder_form_dialog.py:660`) → `ReminderFormDialog.accept()` (`reminder_form_dialog.py:812`).

**Cross-module hops.**

1. `reminder_form_dialog.py:855-905` — name + datetime + recurrence validation gates.
2. `reminder_form_dialog.py:957-973` — `Reminder(...)` dataclass constructed (id auto-generated).
3. `reminder_form_dialog.py:977-981` — `self._store.add(reminder)` → `break_reminder/storage/reminders.py:211-216` `ReminderStore.add` (atomic tmp-file + rename at `:279-287`).
4. `reminder_form_dialog.py:996` — `self._scheduler.reload()` → `break_reminder/scheduler.py:297-306` `ReminderScheduler.reload`.
5. `scheduler.py:300` — `_compute_next()` (`:336-345`) walks `store.list_all()` + calls `next_firing_after()` (`:348-373`) — RRULE math via `dateutil.rrule.rrulestr`.
6. `scheduler.py:303-306` — `self._timer.start(ms)` arms single-shot `QTimer`, capped at 24h at `:306`.
7. `reminder_form_dialog.py:1002-1005` — `reminder_added.emit(reminder)` → `settings_dialog.py:1072-1140` `_refresh_reminders_tab` rebuilds the tab.
8. *(Later, at scheduled time)* `scheduler.py:285` `_timer.timeout` → `_on_timer` (`:310-319`) → `_fire(reminder_id)` (`:321-334`) → `reminder_due.emit(name, event_at)` at `:334`.
9. `app.py:278` `reminder_scheduler.reminder_due.connect(_on_reminder_due)` → `_on_reminder_due` (`app.py:389-398`) → `ReminderDialog(name, event_at).show()` at `:397-398`.

**Observable outcome.** A `ReminderDialog` becomes visible on `QApplication.topLevelWidgets()` at the scheduled (virtual) time. Intermediate readable junction: `reminder_due` signal at `scheduler.py:334`.

**Threading.** Entirely Qt main thread. `QTimer.singleShot` is bypassed in tests by calling `_on_timer()` directly (Phase 1 pattern at `tests/test_recurring_reminder_integration.py:113, 117, 164`).

**Per-hop coverage today.**

| Hop | Existing test | What it asserts |
|---|---|---|
| Hop 3 (form → store) | `tests/test_reminder_form_dialog.py:410-428` `test_successful_save_persists_to_store` | persistence after `accept()` |
| Hop 4 (form → scheduler reload) | `tests/test_reminder_form_dialog.py:457-468` `test_successful_save_calls_scheduler_reload` | uses `StubScheduler` (`test_reminder_form_dialog.py:112-127`) that only counts calls |
| Real scheduler arming | `tests/test_reminder_form_dialog.py:712-742` `test_save_arms_real_scheduler_against_new_reminder` | drives real `ReminderScheduler`, asserts `scheduler._next.reminder_id == saved.id` — **stops short of firing** |
| Hop 6 (arm timing) | `tests/test_reminder_scheduler.py:91-135` `test_reload_arms_qtimer_for_future_reminder` + cap re-entry | in isolation |
| Hop 8 (timer → reminder_due) | `tests/test_reminder_scheduler.py:200-261` + `tests/test_recurring_reminder_integration.py:89-258` | fire + re-arm loop pinned (R-1) |
| Hop 9 (reminder_due → ReminderDialog) | **NONE** | the connection at `app.py:278` is structurally present; `_on_reminder_due` has zero ripgrep matches in `tests/` |

**E2E gap.** No test chains `accept()` → real `add()` → real `reload()` → virtual-clock fast-forward → `_on_timer()` → `_on_reminder_due` runs → `ReminderDialog` becomes visible on `QApplication.topLevelWidgets()`. Hop 9 is the single biggest invisible hop in the codebase.

---

### §B. Flow B — Save Settings interval change → BreakScheduler resets → next break_due fires on new threshold

**Entry point.** User opens Settings (tray "Open settings…") → connects `dialog.break_interval_changed.connect(_on_break_interval_changed)` at `app.py:349` → user changes break interval in `_break_interval_spinbox` (`settings_dialog.py:638-652`) → clicks OK (`settings_dialog.py:613-617`) → `SettingsDialog.accept()` at `settings_dialog.py:1201`.

**Cross-module hops.**

1. `settings_dialog.py:1246-1262` — voice-phrase validation gate (early-return path).
2. `settings_dialog.py:1272-1291` — autostart Run-key side-effect gate.
3. `settings_dialog.py:1298-1306` — persistence: `self._settings.break_interval_min = new_break_interval` → `break_reminder/storage/settings.py:137-159` setter writes `scheduling/break_interval_min` to `QSettings`.
4. `settings_dialog.py:1312-1313` — **conditional** emit: `if new_break_interval != old_break_interval: self.break_interval_changed.emit(new_break_interval)` (signal declared at `settings_dialog.py:510`).
5. `app.py:423-446` — slot `_on_break_interval_changed(new_interval)` runs synchronously (still inside `accept()` before `super().accept()`):
   - `:445` `self._break_scheduler.reset_cycle()` → `scheduler.py:162-187` clears `_active_seconds`, `_snoozes_used`, `_snooze_until` (pause flag untouched).
   - `:446` `self._refresh_tooltip()`.
6. `settings_dialog.py:1315` — `super().accept()` returns from `exec()`.
7. *(Later, on each 1Hz tick)* `BreakScheduler._timer.timeout` → `_tick()` (`scheduler.py:206-230`).
8. `scheduler.py:211` — `snap = self._settings.snapshot()` re-reads `break_interval_min` (clamped getter `settings.py:131-135`) — **this is how the new threshold takes effect**.
9. `scheduler.py:219-226` — `_active_seconds` accumulates; once `>= snap.break_interval_min * 60`, emit `break_due` at `:226`.
10. `app.py:277` `break_scheduler.break_due.connect(_on_break_due)` → `_on_break_due(snooze_remaining)` (`app.py:384-387`) → `_show_break_dialog(snooze_remaining)` (`:400-414`) → `BreakDialog(...).show()` at `:413`.

**Observable outcome.** `BreakDialog` appears on `QApplication.topLevelWidgets()` after the new threshold elapses in virtual time. Intermediate readable junction: `break_due` signal at `scheduler.py:226`.

**Threading.** All Qt main thread. `ActivityMonitor.activity_detected` is normally bridged from a pynput listener thread but in tests is emitted directly from the test thread (pattern in `tests/test_break_scheduler.py:84-89`).

**Per-hop coverage today.**

| Hop | Existing test | What it asserts |
|---|---|---|
| Hop 3 (setter) | `tests/test_settings_dialog.py:290-323` `TestSave` | persisted across `Settings` instances |
| Hop 4 (signal emit) | `tests/test_settings_dialog.py:434-484` `TestBreakIntervalChangedSignal` | emit-on-change, no-emit-when-unchanged, payload, before-`super().accept()` ordering |
| Hop 5 (slot side-effect direct) | `tests/test_app.py:227-283` `TestOnBreakIntervalChanged` | calls `_on_break_interval_changed(7)` **directly** |
| Hop 5 wiring | `tests/test_app.py:285-314` `test_end_to_end_via_settings_dialog_stub` | **`_StubSignal` shim** — captures `slots[0]` and invokes it by hand; never emits the real signal across the real connect |
| Hop 9 (break_due on threshold) | `tests/test_break_scheduler.py:127-159` `test_break_due_fires_when_threshold_reached` | with a **fixed** interval, NOT after an interval change |
| Hop 10 (break_due → BreakDialog) | **NONE** | `app.py:277` connection structurally present; no test asserts that emitting `break_due` causes a `BreakDialog` to appear |

**E2E gap.** No test runs the full real-`SettingsDialog.accept()` → real setter → real `break_interval_changed.emit` over a real `connect` → real `_on_break_interval_changed` → real `reset_cycle` → virtual-clock fast-forward through `_tick()` until `break_due` fires on the **new** threshold → real `_on_break_due` constructs a `BreakDialog`. The `_StubSignal` shim at `test_app.py:442` is the R-4 canonical anti-pattern: signal-connection-only.

---

### §C. Flow C — Pause → Resume → post-resume tick honors the new interval

**Entry point.** Tray "Pause" `QAction` (`app.py:212-214`) `triggered` → `_on_toggle_pause` (`app.py:308-313`). The action label flips between "Pause"/"Resume" via `_refresh_tooltip` (`app.py:235-270`, label set at `:256`/`:258`).

**Cross-module hops.**

1. `app.py:309-312` — `if is_paused: self._break_scheduler.resume()` else `.pause()`.
2. `scheduler.py:147-150` — `pause()` sets `self._paused = True` AND persists `self._settings.paused = True` → `settings.py:308-321` setter writes `lifecycle/paused`.
3. `scheduler.py:152-155` — `resume()` mirror.
4. `app.py:313` — `_refresh_tooltip()`.
5. *(While paused)* `scheduler.py:206-208` — `_tick()` early-returns; counter freezes.
6. *(After resume)* `scheduler.py:210-230` — `_active_seconds` continues from where it froze (NOT reset). `seconds_until_break` getter at `:108-118` returns `threshold - _active_seconds`.
7. `scheduler.py:222-226` — once `_active_seconds >= snap.break_interval_min * 60`, `break_due.emit(snooze_remaining)`.
8. `app.py:277` → `_on_break_due` → `_show_break_dialog` → `BreakDialog.show()` at `:413`.

**Observable outcome.** `BreakDialog` appears after the post-resume cumulative active time crosses threshold. Tooltip flips `"BreakReminder — paused"` → `"BreakReminder — next break in Nm 00s"`. INI `lifecycle/paused` flips True/False.

**Threading + clock.** All Qt main thread. **Pause/resume do NOT involve the clock at all** (`scheduler.py:147-155` only flip `_paused` + persist) — no timestamp captured at pause; no elapsed-time replay at resume. Post-resume `_tick()` reads `self._clock()` fresh at `:210`. This means Flow C's assertion is just: `pause()` → `clock.advance(N)` → `resume()` → `_tick()` → assert behavior matches the threshold.

**Per-hop coverage today.**

| Hop | Existing test | What it asserts |
|---|---|---|
| Hop 2-3 (scheduler setters) | `tests/test_break_scheduler.py:240-299` `TestPauseResume` | pause stops accumulation, resume restarts, INI persists |
| Hop 5-6 (tick during pause / resume restart) | `tests/test_break_scheduler.py:243-273` `test_resume_restarts_accumulation` | direct `_tick()` driving |
| Hop 1 (tray pause `QAction` → setter) | **NONE** | the tray Pause `QAction.triggered.connect(_on_toggle_pause)` wiring at `app.py:212-214` is signal-connection-only; no test asserts that triggering the `QAction` actually toggles `BreakScheduler._paused` |
| Hop 8 (break_due → BreakDialog) | **NONE** | same gap as Flow B |
| Composite (pause + resume + non-zero snooze + reset in one sequence) | **NONE** | the R-3 "Must challenge" cell at test-plan §2 explicitly calls this out as uncovered |

**E2E gap.** No test chains tray Pause `QAction.trigger()` → `_paused == True` → many no-op `_tick()` calls → tray Resume `QAction.trigger()` → `_paused == False` → continued `_tick()` accumulation crosses threshold → `BreakDialog` becomes visible. Both ends are gap-side.

---

### §D. Flow D — Tray "Reset" → `_apply_break_taken` → cycle re-arms + TAKEN logged

**Entry point.** Tray `QAction("Reset")` (`app.py:208-210`) `triggered` → `_on_reset` (`app.py:297-306`). Action position at index `take_break_idx + 1`, pinned by `tests/test_app.py:339-349`.

**Cross-module hops.**

1. `app.py:306` — `self._apply_break_taken()` (the **shared backbone** also used by the dialog flow at `app.py:418-419` `_on_break_outcome` → `_apply_break_taken`).
2. `app.py:448-462` `_apply_break_taken()`:
   - `:457` `self._break_scheduler.on_break_taken()` → `scheduler.py:189-191` → `reset_cycle()` (`:162-187`).
   - `:458` `self._event_log.record(EventType.BREAK, Outcome.TAKEN)` → `break_reminder/storage/event_log.py:63-74` appends CSV row `<iso>,break,taken,` under `threading.Lock` (`:55, 71`).
   - `:459` `self._active_break_dialog = None`.
   - `:461` `self._break_scheduler.start()` → `scheduler.py:100-102` re-arms the 1Hz `_timer`.
   - `:462` `self._refresh_tooltip()`.
3. *(Later)* `scheduler.py:206-230` `_tick()` re-accumulates → emits `break_due` again at `:226`.
4. `app.py:277` → `_on_break_due` → `_show_break_dialog` → `BreakDialog.show()`.

**Observable outcome.** `events.csv` gains exactly one row `<iso>,break,taken,`. `BreakScheduler._timer.isActive() == True`. Next `BreakDialog` appears `break_interval_min * 60` active seconds later. **Pause flag untouched** (FR-016).

**Multiple paths to same outcome.** "Take break now" tray action (`app.py:204-206`) ALSO routes through `_apply_break_taken` (via the BreakDialog `outcome_chosen` flow). The Flow D e2e must pin the **Reset** entry specifically (not the sibling path) — otherwise a regression silently routing Reset through the dialog would pass.

**Per-hop coverage today.**

| Hop | Existing test | What it asserts |
|---|---|---|
| Hop 2 (apply_break_taken) | `tests/test_app.py:96-168` `TestApplyBreakTaken` | all six side effects (counter, snooze cap, snooze window, event-log row, dialog clear, timer re-armed, pause untouched) |
| Hop 1 (tray action wiring) | `tests/test_app.py:358-371` `test_reset_triggers_apply_break_taken` | `_find_action(app, "Reset").trigger()` → asserts `_active_seconds == 0` + `_snoozes_used == 0` + CSV row — **the closest existing test to a true e2e**; stops at CSV row |
| Hop 3 (post-reset tick re-arms break_due) | **NONE** (in this chain) | the `start()` call at `app.py:461` + `app.py:277` `break_due → _on_break_due` connection are structurally pinned, never traversed in one assertion |
| Hop 4 (break_due → BreakDialog) | **NONE** | same gap as B/C |

**E2E gap.** Extend `test_reset_triggers_apply_break_taken` to advance virtual time for `break_interval_min * 60` seconds via the injected `Clock` + `_tick()`, then assert `break_due` fires AND a `BreakDialog` becomes visible — proving the cycle is **fully re-armed** through the next user-visible event.

---

### §E. Cross-flow patterns — the four R-4 gaps ranked by signal

**The single R-4 contract worth pinning.** Three signal connections in `app.py` are the entire R-4 surface for the four flows:

```277:279:break_reminder/app.py
        self._break_scheduler.break_due.connect(self._on_break_due)
        self._reminder_scheduler.reminder_due.connect(self._on_reminder_due)
```

Plus one connection done on-demand inside `_on_open_settings`:

```349:349:break_reminder/app.py
            dialog.break_interval_changed.connect(self._on_break_interval_changed)
```

A regression that silently broke any of these three lines would pass every existing per-module test today — the slot bodies are tested in isolation; the signal emits are tested in isolation; the connect calls are tested structurally; **but no test emits the real signal across the real connect and observes the real slot's user-visible effect**.

**Gap ranking by signal (most-invisible first).**

| Rank | Flow | Gap | Why most invisible |
|---|---|---|---|
| 1 | A | `reminder_due → _on_reminder_due → ReminderDialog.show()` | `_on_reminder_due` has **zero ripgrep matches** in `tests/`. A regression that broke `app.py:278` would silently ship "user adds a reminder, time comes, nothing pops up, nothing logs". |
| 2 | B | `break_interval_changed → _on_break_interval_changed → reset_cycle → tick → break_due → BreakDialog.show()` | The `_StubSignal` shim at `tests/test_app.py:442` and the similar one at `test_settings_dialog.py:2447` make the seam *look* tested. The "end-to-end" test at `test_app.py:285-314` literally invokes the captured slot by hand. |
| 3 | C | tray Pause `QAction.trigger()` → setter + composite pause/resume/snooze/reset sequence | The tray Pause `QAction` wiring is signal-connection-only AND the R-3 "Must challenge" composite (pause + non-zero snooze + reset interactions) is uncovered. |
| 4 | D | post-Reset `_tick()` → `break_due` → `BreakDialog.show()` | Already partially covered to the CSV row by `test_reset_triggers_apply_break_taken`; the gap is just the "next break actually fires" extension. Lowest invisibility but highest residual-confidence-per-LoC. |

**Canonical e2e assertion shape (applies to all four).** Drive the user-visible click (`QAction.trigger()`, `QDialogButtonBox.accepted.emit()`, or `dialog.accept()` directly), advance the virtual `Clock`, call `_tick()` / `_on_timer()` directly (do NOT enter the event loop), assert the user-visible outcome reads true (`BreakDialog`/`ReminderDialog` present in `QApplication.topLevelWidgets()`, or CSV row appended). **Anti-patterns to avoid (from prior phase research):** `QTest.mouseClick` on the popup button (Phase 2 anti-pattern, bypasses OS modal grab); `_active_seconds == 0` as an oracle (implementation mirror per test-plan §2 R-3); mocking `QTimer.singleShot` (mirror); mocking `QDialog.exec` (mirror).

---

### §F. Harness audit — fixtures inventory + lift list + STRUCTURAL findings

**Virtual-clock seam audit.** Both schedulers are clean:

- `BreakScheduler` ctor `clock=` kwarg at `scheduler.py:66`, defaulted via `clock or _utcnow` at `:86`. All `self._clock()` call sites: `:89` (init `_last_input_at`), `:140` (`seconds_until_snooze_end`), `:196` (`on_break_snoozed`), `:210` (`_tick`).
- `ReminderScheduler` ctor `clock=` kwarg at `scheduler.py:262`, defaulted at `:282`. All `self._clock()` call sites: `:303` (`reload`), `:313` (`_on_timer`), `:337` (`_compute_next`).
- **No other time sources** anywhere in `scheduler.py` (no `time.monotonic`, `datetime.now`, or `QDateTime.currentDateTime`). The 1-second `QTimer` at `:96-98` runs in real wall-clock but tests bypass by calling `_tick()` directly.
- **A single `Clock` instance can be passed to both schedulers** — they share no state and read each other independently. None of the four flows need this, but it's free for future flows.

**Existing fixtures inventory.**

| Fixture | Scope | File:line | Used by which of A/B/C/D |
|---|---|---|---|
| `_qt_app` | session (autouse) | `tests/conftest.py:31-34` | A, B, C, D (mandatory) |
| `Clock` (class, not fixture) | — | `tests/conftest.py:37-75` | A, B, C, D (deterministic time) |
| `clock` (function fixture, epoch `2026-05-20 06:00 UTC`) | function | duplicated at `tests/test_recurring_reminder_integration.py:47-57` AND `tests/test_modal_stacking_integration.py:120-128` | A, B, C, D |
| `store_path`, `store` | function | duplicated in both Phase 1/2 files | A directly; B/D need them as kwargs |
| `settings` | function | `tests/test_modal_stacking_integration.py:96-99` only | B (target), C, D |
| `voice` (`FakeVoice` class) | function | `tests/test_modal_stacking_integration.py:71-93` + `:102-105` | B, D (avoid spinning up `pyttsx3`) |
| `scheduler` (= `ReminderScheduler`) | function | duplicated in both Phase 1/2 files | A directly; SettingsDialog needs it as a kwarg in B |
| `blocking_modal` (parametrized) | function | `tests/test_modal_stacking_integration.py:137-198` | not directly applicable to A/B/C/D |

**Net-new fixtures missing from conftest.** `BreakScheduler` (lives only in `test_break_scheduler.py:58-61`), `EventLog` (lives only in `test_event_log.py`), `ActivityMonitor`-with-no-`start()`, and a `BreakReminderApp` factory — none exist at conftest scope today.

**Recommended fixture lifts** (function-scoped, since they all bind to `tmp_path`; ~38 LoC total, zero behavior change):

| # | Lift to `tests/conftest.py` | Provides |
|---|---|---|
| A1 | `clock` | `Clock(datetime(2026, 5, 20, 6, 0, tzinfo=UTC))` |
| A2 | `store_path` | `tmp_path / "reminders.json"` |
| A3 | `store` | `ReminderStore(path=store_path)` |
| A4 | `settings` | `Settings(ini_path=tmp_path / "BreakReminder.ini")` |
| A5 | `voice` + `FakeVoice` class | no-op `speak()`/`stop()` |
| A6 | `reminder_scheduler` (rename from `scheduler` for disambiguation) | `ReminderScheduler(store, clock=clock)` |
| B1 | `activity` | `ActivityMonitor()` — listeners stay dormant (no `start()` call) |
| B2 | `break_scheduler` | `BreakScheduler(settings, activity, clock=clock)` |
| B3 | `event_log` | `EventLog(path=tmp_path / "events.log")` |
| B4 | `break_reminder_app` | `BreakReminderApp(qapp, settings, event_log, store, voice)` — Flow D primarily; depends on STRUCTURAL #1 decision below |

**[STRUCTURAL] findings — Phase 3-style harness blockers.**

**#1 — `BreakReminderApp.__init__` has no `clock=` injection seam.** `app.py:60-104` accepts `settings`, `event_log`, `reminder_store`, `voice` as kwargs but no `clock`. At `:103-104` both `BreakScheduler` and `ReminderScheduler` are constructed without `clock=` — they fall through to real wall-clock `_utcnow`. **Impact:** any e2e that uses the wired app cannot drive virtual time through its internal schedulers. **Recommendation:** **ship the fix in Phase 4** (~3 LoC: add `clock=None` kwarg, propagate to both `__init__` lines). Parallels Phase 3's `_read` row-containment fix. **If deferred:** Flow D's TAKEN-row oracle is clock-independent and ships safely; B and C bypass `BreakReminderApp` entirely (construct `BreakScheduler` directly via fixture B2) and are unblocked either way.

**#2 — `EventLog.record` uses real wall-clock, not the injected scheduler clock.** `event_log.py:63-74`, specifically `:66` `datetime.now(UTC).isoformat(...)`. No `clock=` kwarg on `EventLog.__init__` (`:47-56`). **Impact:** Flow D's TAKEN-row `timestamp_iso` column is non-deterministic. **Mitigation:** **defer.** Assert on the `(event_type, outcome, detail)` tuple read back from CSV (the existing `tests/test_event_log.py` pattern), not on the timestamp.

**#3 — `BreakScheduler.start()` arms a real `QTimer`; latent race with virtual `_tick()`.** `scheduler.py:100-102` `start()` calls `self._timer.start()` (the 1000ms tick timer at `:96-98`). Flows B/D both route through `_apply_break_taken` which calls `start()` at `app.py:461`. **Impact:** if the test then enters the event loop (`qtbot.wait()` / `qtbot.waitSignal()`), the real timer fires `_tick()` on real wall-clock seconds, racing the test's deterministic invocations. **Mitigation:** **defer + document.** Established pattern in `test_break_scheduler.py` is to never enter the event loop after a slot that calls `BreakScheduler.start()`. Document this in §6 cookbook when Phase 4 ships.

**#4 — No `BreakReminderApp` test fixture exists today.** Every test that wants one must wire ≥4 injected collaborators. Under pytest-qt, `QApplication.setApplicationName(APPLICATION_NAME)` is NOT called (only `app.main()` at `app.py:524` does), so default `QStandardPaths` resolves to the test-runner exe name — partly protective but still writes *somewhere*. **Mitigation:** ship fixture B4 (~10 LoC).

---

### §G. CI tier + pytest marker recommendation

**Today's state.**

- `pyproject.toml:58-60`: `[tool.pytest.ini_options]` has only `testpaths = ["tests"]` and `addopts = "-q"`. **No custom markers**, no `--strict-markers`, no `-m` in addopts.
- `tests/`: zero custom marker usage anywhere. Only built-in `@pytest.mark.parametrize` is used. Neither integration file (`test_recurring_reminder_integration.py`, `test_modal_stacking_integration.py`) carries any marker.
- `.github/workflows/release.yml:58-59`: single step `- name: Test` `run: uv run pytest`. Only one workflow file exists in `.github/workflows/`.
- `.pre-commit-config.yaml:11-25`: runs `ruff --fix` + `uv run pyright`. **No pytest hook** — pre-commit does not invoke pytest at all.

**Marker name recommendation: `e2e`** (not `integration`). Three reasons:

1. The §3 row 4 cell explicitly frames Phase 4 as an "end-to-end test per top-three user-visible flow" — the marker should mirror the contract.
2. The two existing `*_integration.py` files are narrow risk pins (R-1 RRULE re-arm; R-2 modal-stacking), not user-visible flows. Lumping them under the same marker as a tray-click → break-dialog → snooze → event-log flow erases real granularity.
3. Pytest community convention pairs `e2e` and `integration` as distinct tiers when both are used; Phase 4 is the upper tier.

**File-vs-marker split: marker.** `-k integration` couples the CI split to filename suffix, which makes file renames into pipeline changes. `-m e2e` decouples.

**CI YAML change (minimal).** Replace the single `Test` step at `release.yml:58-59` with:

```yaml
      - name: Test (unit)
        run: uv run pytest -m "not e2e"

      - name: Test (e2e)
        run: uv run pytest -m e2e
```

Pair with `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"
markers = [
    "e2e: end-to-end test of a top-three user-visible flow (Phase 4 tier)",
]
```

`--strict-markers` turns a typo (`@pytest.mark.e2ee`) into a collection error instead of a silent skip.

**Runtime impact.** Both existing integration files are virtual-clocked (zero `time.sleep`). They contribute 5 test functions at ~5-10 ms each. 3-4 new e2e tests at similar shape add **~30-100 ms wall time**, well under the 3-5 s baseline. Pre-commit doesn't run pytest, so dev impact is zero.

**Three risks worth pinning in the plan.**

1. **Strict-markers + declaration drift.** If `--strict-markers` lands without a `markers = [...]` declaration, the entire suite fails to collect. **Land both in the same commit.**
2. **Empty-tier exit-code 5.** `pytest -m e2e` with no matching tests exits with code 5 ("no tests ran"), which CI reports as a failure. **Either land the first e2e test in the same PR as the workflow split, or pass `--exit-code-on-no-tests-collected=0` on the e2e step until content lands.**
3. **Integration-files-vs-marker semantics.** The two existing `*_integration.py` files don't get `@pytest.mark.e2e` (they're narrower); they ride in the default/unit lane. **Document this in `AGENTS.md` § Build & release** to prevent a future inversion (`-m unit`) from silently dropping them from both lanes.

---

## Code References

**Load-bearing R-4 connections (the three lines Phase 4 closes coverage on):**

- `break_reminder/app.py:277` — `self._break_scheduler.break_due.connect(self._on_break_due)` (Flows B, C, D terminal hop)
- `break_reminder/app.py:278` — `self._reminder_scheduler.reminder_due.connect(self._on_reminder_due)` (Flow A terminal hop; **zero coverage today**)
- `break_reminder/app.py:349` — `dialog.break_interval_changed.connect(self._on_break_interval_changed)` (Flow B entry-to-scheduler hop)

**Virtual-clock injection seams:**

- `break_reminder/scheduler.py:66, 86, 210` — `BreakScheduler` ctor `clock=` + `_tick()` read site
- `break_reminder/scheduler.py:262, 282, 313, 337` — `ReminderScheduler` ctor `clock=` + `_on_timer()` + `_compute_next()` read sites

**Closest-to-e2e existing test (use as shape):**

- `tests/test_app.py:358-371` — `test_reset_triggers_apply_break_taken` (drives `QAction.trigger()` through `_apply_break_taken` to CSV row in one pass)

**R-4 anti-pattern (signal-connection-only "end-to-end"):**

- `tests/test_app.py:285-314` — `test_end_to_end_via_settings_dialog_stub` (captures `slots[0]`, invokes by hand)
- `tests/test_app.py:442` — `_StubSignal` shim definition
- `tests/test_settings_dialog.py:2447` — second `_StubSignal` shim

**Existing harness to extend:**

- `tests/conftest.py:31-34` — session-scoped `_qt_app` autouse
- `tests/conftest.py:37-75` — `Clock` class (the only time source needed)
- `tests/test_recurring_reminder_integration.py:47-75` — Phase 1 `clock` + `store_path` + `store` + `scheduler` fixtures (lift candidates)
- `tests/test_modal_stacking_integration.py:71-134` — Phase 2 `FakeVoice` + `settings` + `voice` + `store_path` + `store` + `clock` + `scheduler` fixtures (lift candidates)

**STRUCTURAL #1 target (recommended Phase 4 fix):**

- `break_reminder/app.py:60-104` — `BreakReminderApp.__init__` (add `clock=None` kwarg)
- `break_reminder/app.py:103-104` — propagate `clock=clock` into both scheduler constructions

**CI / marker landing sites:**

- `pyproject.toml:58-60` — `[tool.pytest.ini_options]` (add `markers` list + `--strict-markers`)
- `.github/workflows/release.yml:58-59` — single `Test` step (replace with two `run:` lines)
- `.pre-commit-config.yaml:11-25` — no pytest hook (zero dev impact)

## Architecture Insights

1. **Two convergent dialog `.show()` callsites are the entire user-visible-outcome surface for all four flows.** `BreakDialog.show()` at `app.py:413` covers B/C/D; `ReminderDialog.show()` at `app.py:398` covers A. A single fixture that polls `QApplication.topLevelWidgets()` for a dialog of type `X` (with a short qtbot wait) covers every flow's oracle without per-flow assertion bespoke shapes.

2. **Both schedulers are correctly designed for virtual-clock testing** — clean `clock=` injection seam, no hidden time sources, `_tick()` / `_on_timer()` directly callable from tests. The fact that `BreakReminderApp` doesn't expose the same kwarg (STRUCTURAL #1) is the only seam friction in the whole stack.

3. **`reset_cycle` and `pause`/`resume` are orthogonal** by design (FR-016) — `reset_cycle` (`scheduler.py:162-187`) doesn't touch `_paused`; pause/resume (`:147-155`) don't capture timestamps or replay elapsed time. This orthogonality is what makes Flow C's R-3 composite ("pause + resume + non-zero snooze + reset" in one sequence) cheap to test — each operation is a pure attribute flip, the composite is just sequencing.

4. **The "deliberately redundant" tray actions (FR-004)** mean Flow D's e2e MUST pin the **Reset** entry specifically. Both "Take break now" (`app.py:204-206` → BreakDialog → `outcome_chosen` → `_on_break_outcome` → `_apply_break_taken`) and "Reset" (`app.py:208-210` → `_on_reset` → `_apply_break_taken`) reach the same `_apply_break_taken` backbone. A regression that silently routed Reset through the dialog path would pass a vacuous "TAKEN row was written" assertion if the test entered via either action.

5. **`_StubSignal` shims are the codebase's institutional R-4 anti-pattern.** Two shims exist (`test_app.py:442`, `test_settings_dialog.py:2447`). Both capture connected slots and invoke them by hand. They produce green tests for `connect` calls without ever traversing the real signal-emit path — the exact regression class Phase 4 closes. Worth flagging in the cookbook entry that lands with the phase.

## Historical Context (from prior changes)

- **`context/archive/2026-06-01-testing-rrule-reminder-loop/research.md`** — Phase 1 (R-1) research that designed the virtual-clock + pytest-qt harness Phase 4 reuses. The `Clock` class in `tests/conftest.py:37-75` and the `_on_timer()`-directly-callable pattern come from this phase. §R-1a documents the "fire → reload → re-arm" contract Flow A inherits.

- **`context/archive/2026-06-02-testing-modal-stacking-wedge/research.md`** — Phase 2 (R-2) research that established the structural-assertion anti-pattern (`QTest.mouseClick` on the popup button is unsafe because pytest-qt synthesizes input inside Qt's object model and bypasses the OS modal grab). Flow B's `BreakDialog` assertion must not regress to clicking the popup button — assert on `QApplication.topLevelWidgets()` membership / dialog type instead. The Phase 2 `FakeVoice` class (`test_modal_stacking_integration.py:71-93`) is the recommended voice stub for Flow B/D.

- **`context/archive/2026-06-02-testing-storage-malformed-input/research.md`** — Phase 3 (R-5) research that found the `_read` row-containment structural defect via RED tests. Phase 4's STRUCTURAL #1 (`BreakReminderApp` missing `clock=` kwarg) is the analogous Phase 4 finding — recommend the same RED→GREEN treatment if it's bundled into the rollout.

- **`context/foundation/lessons.md`** — "Bundle /10x orchestration edits into the change's first phase commit" (added during the Phase 3 impl-review) applies to this rollout too: the `test-plan.md` §3 row-4 status flip + Goal/Order rewrite already landed in this branch's working tree; the first phase commit should bundle them.

## Related Research

- `context/archive/2026-06-01-testing-rrule-reminder-loop/research.md` — Phase 1 R-1 harness research
- `context/archive/2026-06-02-testing-modal-stacking-wedge/research.md` — Phase 2 R-2 modality-fix research
- `context/archive/2026-06-02-testing-storage-malformed-input/research.md` — Phase 3 R-5 row-containment research
- `context/foundation/test-plan.md` — §2 R-4 "Must challenge" + §3 row 4 Goal/Order rationale + §6 cookbook target row
- `AGENTS.md` — § "Threading rules", § "FR-008 — active-time accounting", § "FR-014 — recurrence engine", § "FR-004 — tray quick-menu"

## Open Questions

1. **STRUCTURAL #1 — ship the `BreakReminderApp.clock=` kwarg in Phase 4, or defer?** Recommendation: ship. ~3 LoC, parallels Phase 3's `_read` precedent, unblocks any future wired-app e2e. **Defer alternative:** Flow D still ships safely against the clock-independent TAKEN-row oracle; B/C bypass `BreakReminderApp` entirely. Pick at `/10x-plan` time.

2. **Three flows or four?** User scoping decision was "research both ambiguous candidates and let /10x-plan pick the top three from {A, B, C, D}". Recommendation for /10x-plan: ship A + B + D as the top three (each closes a distinct R-4 wire — `reminder_due`, `break_interval_changed`, `break_due` via tray-Reset). C is valuable but its e2e gap is dominated by the R-3 "Must challenge" composite which is genuinely a different risk; consider whether C ships as a 4th in this phase or moves to a future R-3 rollout. **Open for /10x-plan.**

3. **`AGENTS.md` cookbook delta — single entry or two?** Phase 4 will ship one §6 cookbook row covering "Cross-cutting end-to-end flows" (already a placeholder at test-plan §6 line 159). Open: also update `AGENTS.md` § "Threading rules" to document the "do not enter the event loop after `BreakScheduler.start()`" rule that STRUCTURAL #3 derives? Recommendation: yes, one paragraph addition.

4. **Marker landing order — declare-then-add, or add-with-defer?** Risk #2 (empty-tier exit-code 5) means the CI YAML change cannot land before the first e2e test. Open: should the plan bundle marker declaration + `--strict-markers` + the workflow split + the first e2e test into a single commit, or split into "declare marker" (zero-impact) + "land first e2e test + workflow split" (atomic)? Recommendation: split — declare + strict-markers in the prep commit (with fixture lifts), then each flow's e2e ships as its own commit, and the workflow split lands with the first flow.
