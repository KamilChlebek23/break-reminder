<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Top-three e2e flows

- **Plan**: `context/changes/testing-top-three-e2e-flows/plan.md`
- **Mode**: Deep
- **Date**: 2026-06-02
- **Verdict**: REVISE → SOUND after triage (all 7 findings FIXED)
- **Findings**: 3 critical, 1 warning, 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | PASS |
| Blind Spots | FAIL |
| Plan Completeness | WARNING |

## Grounding

10/10 paths OK, 4/5 symbols OK (1 stale: `_StubSignal` line ref), brief↔plan OK.

## Findings

### F1 — Wrong attribute path for `_last_input_at` (P3 step 7, P4 step 5)

- **Severity**: CRITICAL
- **Impact**: HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots
- **Location**: Phase 3 step 7, Phase 4 step 5
- **Detail**: Plan recipe writes `activity._last_input_at = clock()` (P3) and `app._break_scheduler._activity._last_input_at = clock()` (P4), but `_last_input_at` lives on `BreakScheduler` (`scheduler.py:89`, `:204`, `:219`), not on `ActivityMonitor` (`activity.py:30-78` only has `_kb_listener`/`_mouse_listener`). Python silently creates a dead attribute on the activity object that `_tick()` never reads. The scheduler's own `_last_input_at` is seeded once at construction and never refreshed in the test loop — after ~60 ticks `idle >= idle_threshold_sec`, the `_active_seconds` counter freezes, and the timing-window oracle never fires.
- **Fix A ⭐ Recommended**: Drive via the real signal — `activity.activity_detected.emit(clock())` before each `_tick()`
  - Strength: Exercises the real cross-thread signal bridge (FR-008 Qt AutoConnection); also tests `_on_activity` end-to-end; matches the e2e contract of "real signal across real connect".
  - Tradeoff: One extra slot hop per iteration vs. direct attribute write.
  - Confidence: HIGH — `scheduler.py:94` connects `_on_activity` at ctor.
  - Blind spot: None significant; this is the production input path.
- **Fix B**: Directly mutate `break_scheduler._last_input_at = clock()` before each `_tick()`
  - Strength: One-line, no signal plumbing.
  - Tradeoff: Bypasses the `activity_detected → _on_activity` bridge that Fix A exercises; subtly less "e2e".
  - Confidence: HIGH — direct attribute on the scheduler instance.
  - Blind spot: Future code that mediates `_last_input_at` writes (clamping, logging) would not be exercised.
- **Decision**: FIXED via Fix A (real signal `activity.activity_detected.emit(clock())`; P4 disambiguated to `app._activity` for the wired-app instance, which also addresses F5's standalone-vs-wired ambiguity).

### F2 — Wrong `SettingsDialog` kwargs (P3 step 2)

- **Severity**: CRITICAL
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 3 step 2 + Critical Implementation Details
- **Detail**: Plan says `SettingsDialog(settings=settings, voice=voice, store=store, scheduler=reminder_scheduler, parent=None)`. Actual signature (`settings_dialog.py:512-520`) takes `reminder_store=` and `reminder_scheduler=` (not `store=`/`scheduler=`). Production callsite at `app.py:343-348` uses the correct names. `TypeError: unexpected keyword argument 'store'` at construction — the test can't even instantiate the dialog.
- **Fix**: Update P3 step 2 + Critical Implementation Details to `SettingsDialog(settings=settings, voice=voice, reminder_store=store, reminder_scheduler=reminder_scheduler, parent=None)`.
- **Decision**: FIXED (P3 step 2 updated; CID does not embed kwarg list so no further edit needed there).

### F4 — Missing `clock=` propagation to `ReminderFormDialog` (P2 step 1)

- **Severity**: CRITICAL
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Blind Spots
- **Location**: Phase 2 step 1
- **Detail**: Plan constructs `ReminderFormDialog(store=store, scheduler=reminder_scheduler, parent=None)` — kwargs correct, but omits `clock=clock`. The form's past-time gate at `reminder_form_dialog.py:920` reads `self._clock()`; the no-future-occurrences gate at `:943` does too; defaults seed at `:706`/`:569` likewise. Without `clock=`, `self._clock` falls through to real wall-clock `_utcnow` (`:106`). Conftest `clock` fixture epoch is `2026-05-20 06:00 UTC`; test sets `start_at = clock() + 5 min` (May 20, 2026); real-now is `2026-06-02` — gate rejects, `accept()` returns without persist, `store.list_all()` assertion fails before the load-bearing `reminder_due` assertion ever runs.
- **Fix**: P2 step 1 contract becomes `ReminderFormDialog(store=store, scheduler=reminder_scheduler, clock=clock, parent=None)`. The `clock=` kwarg already exists on the form's `__init__` (`reminder_form_dialog.py:471`); pure propagation, no code change required in production.
- **Decision**: FIXED (P2 step 1 updated with both the corrected kwarg and an inline rationale explaining why the propagation is load-bearing — citing the past-time gate at `:920` and the no-future-occurrences gate at `:943`).

### F3 — Stale `_StubSignal` line numbers + 2 missed shim sites

- **Severity**: WARNING
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis, Phase 3 overview, Phase 5 lessons.md contract, plan-brief.md "What & Why"
- **Detail**: Plan cites `tests/test_app.py:442` (actual `:431`, off by 11) and `tests/test_settings_dialog.py:2447` (actual `:2446`, off by 1). Additionally, `tests/test_settings_dialog.py` has THREE `_StubSignal` shims (`:2446`, `:2749`, `:2802`), not one. The plan, brief, research, and prescribed `lessons.md` entry (P5 step 4) all name only one site. Future impl-reviews armed with the `lessons.md` entry would miss the other two shim instances as anti-pattern hits.
- **Fix**: Update all citations to `test_app.py:431` and add the two missed shim sites (`test_settings_dialog.py:2749, 2802`) to plan-text and the prescribed lessons.md entry.
- **Decision**: FIXED (4 spots updated across plan.md + plan-brief.md; the prescribed lessons.md entry now references all four shim sites, so future impl-reviews using the entry will catch the full set; research.md left as-is since it's a historical artifact).

### F5 — `break_scheduler` vs `app._break_scheduler` ambiguity in P4

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 4 steps 2 + 5
- **Detail**: P4 step 2 says "Drives `break_scheduler._active_seconds = 120`" without specifying whether `break_scheduler` is the standalone B3 fixture or `app._break_scheduler`. They are NOT the same instance — the `break_reminder_app` fixture constructs the app, which builds its own internal scheduler from scratch. Step 5 then correctly writes `app._break_scheduler._tick()`. The mismatch could let the test author seed the wrong instance.
- **Fix**: Replace `break_scheduler` with `app._break_scheduler` in P4 step 2 prose. The wired-app's internal scheduler is the one whose `break_due` signal reaches the wired `_on_break_due` slot that shows the `BreakDialog`.
- **Decision**: FIXED (P4 step 2 updated with `app._break_scheduler._active_seconds` + a parenthetical noting the distinction from the standalone fixture; step 5 already disambiguated via F1).

### F6 — `app.py:60-104` constructor line range is slightly off

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis bullet 3, Phase 1 step 3, Manual Verification 1.11
- **Detail**: `BreakReminderApp.__init__` runs `:60-113` (signature `:60-68`, docstring `:69-87`, body `:88-113`). Plan cites `:60-104` — close enough to point at "the constructor" but the scheduler ctors at `:103-104` are at the tail of the body, not at line 104 of the signature.
- **Fix**: Update plan citations from `app.py:60-104` to `app.py:60-113` (constructor as a whole).
- **Decision**: FIXED (4 spots updated across plan.md; research.md left as-is per historical-artifact convention).

### F7 — `grep` assumed available in PowerShell verification commands

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 Success Criterion 1.4
- **Detail**: `uv run pytest --markers | grep -i e2e` assumes `grep` on PATH. Local dev is Windows / PowerShell (per AGENTS.md "Local dev requires Windows"). `grep` typically requires Git Bash; idiomatic PowerShell is `findstr e2e` or `Select-String e2e`.
- **Fix**: Reword as `uv run pytest --markers | Select-String e2e`.
- **Decision**: FIXED (Success Criteria + Progress section both updated; Git Bash alternative noted in the success criterion).
