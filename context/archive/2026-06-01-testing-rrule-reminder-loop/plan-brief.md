# Testing R-1 Recurring-Reminder Re-arm Loop — Plan Brief

> Full plan: `context/changes/testing-rrule-reminder-loop/plan.md`
> Research: `context/changes/testing-rrule-reminder-loop/research.md`

## What & Why

Pin R-1 from the `context/foundation/test-plan.md` rollout — a recurring (daily / weekly / monthly RRULE) reminder firing once and silently missing the next occurrence. R-1 is the highest-impact lived worry on the risk map (double-cited from Q1 and Q3 in the interview) and Phase 1 also stands up the test-harness foundation that R-2 / R-3 / R-4 will reuse.

## Starting Point

Production code in `break_reminder/scheduler.py:297-319` is **correct** — `_on_timer` post-fire runs the full `reload()` → `_compute_next()` pipeline and `reload()` always applies the 24h `QTimer.singleShot` cap. The gap is integration coverage: no existing test crosses the `_fire` boundary and re-asserts on the post-fire `_next` state. The `Clock` test helper is also duplicated verbatim across **three** files: `tests/test_break_scheduler.py:35-48`, `tests/test_reminder_scheduler.py:27-40`, and `tests/test_reminder_form_dialog.py:82-95` (the third pins a different epoch for the form's rounding tests).

## Desired End State

Four new tests in `tests/test_recurring_reminder_integration.py` pin the *fire → reload → fire-again* loop for daily, weekly (`start_at` 13 days out — doubles as the 24h-cap re-entry exercise), and monthly RRULEs, plus the S-06b lead-minutes contract across two firings. The shared `Clock` *class* lives in `tests/conftest.py` (per-file `clock` fixtures stay local). The `context/foundation/test-plan.md` rollout state advances one slot (§3 row 1 → `complete`, §6 Cookbook entry populated, R-1b deferral added to §7 Negative space).

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| R-1b (DST drift) handling | Defer with `TODO(R-1b)` comment; open `bugfix-reminder-dst-drift` as a separate `/10x-shape` cycle | The fix requires a `Reminder.start_at` invariant change touching storage + form + scheduler + every test — too big for this rollout phase, and an xfail marker would be persistent CI noise. | Plan |
| Test file structure | New `tests/test_recurring_reminder_integration.py` + extract `Clock` *class only* to `tests/conftest.py` (per-file `clock` fixtures stay local because epochs diverge) | Removes the class-duplication fork-risk across three files (one uses a different epoch for rounding tests); gives Phases 2-4 of the rollout a single canonical `Clock` class. | Plan |
| RRULE cardinality | Daily + Weekly (`BYDAY=TU`, `start_at = 2026-06-02` — 13 days past scheduler-file epoch) + Monthly (`BYMONTHDAY=15`) | Matches the test-plan §2 R-1 prompt ("daily / weekly / monthly"); weekly doubles as R-1c via cap re-entry; monthly exercises the dateutil month-arithmetic path the S-08 editor added. | Plan |
| Lead-minutes × recurrence | One dedicated test on daily across two firings; other tests stay at `lead_minutes=0` | Pins the cross-cutting S-06b axis once; keeps R-1a / R-1c tests focused on what they're really testing. | Plan |
| `@pytest.mark.integration` marker | Defer to Phase 4; rely on file-name convention `test_*_integration.py` only | The marker discipline IS Phase 4's named scope ("CI tier split"); introducing it now pre-empts that phase's decision space. | Plan |
| R-1a / R-1c diagnosis | Pure coverage gaps in correct production code | Research traced both to specific test files that pin the first firing of a one-shot but never cross a `_fire` boundary. | Research |
| R-1b diagnosis | Real production defect (recurring firings drift ±1h across DST) | Research traced the firing-math chain end-to-end (`scheduler.py:367` runs RRULE in UTC space against a UTC-invariant storage layer); worked example in `Europe/Warsaw` reproduces. | Research |
| Test idiom | Direct `_on_timer()` + recording slot connected to `reminder_due`; no `qtbot.waitSignal` | Existing `test_on_timer_fires_when_clock_caught_up` already proves the shape works; no real Qt event-loop wait needed; keeps tests sub-50ms. | Research |

## Scope

**In scope:**
- Extract `Clock` *class only* to `tests/conftest.py` (per-file `clock` fixtures stay local across three files)
- Four new integration tests in `tests/test_recurring_reminder_integration.py` (daily, weekly-doubles-as-R-1c, monthly, lead × recurrence)
- `TODO(R-1b)` module comment block referencing research.md
- `context/foundation/test-plan.md` refresh: §3 status, §6 Cookbook, §7 Negative space, frontmatter `rollout_phases_complete: 1`

**Out of scope:**
- Fixing R-1b (DST drift) — separate `bugfix-reminder-dst-drift` change
- Any production code change (R-1a / R-1c are coverage gaps, not bugs)
- `@pytest.mark.integration` marker / `pyproject.toml` registration — Phase 4 of the rollout
- R-2 / R-3 / R-4 research and tests — Phases 2-4 of the rollout
- Heavyweight pytest-qt wiring (`qtbot`, `waitSignal`)

## Architecture / Approach

Two-phase split. Phase 1 is a pure refactor — move `Clock` *class* to conftest (per-file `clock` fixtures stay local across three files), delete the class duplicates, prove the collected test count is unchanged vs HEAD baseline. Phase 2 adds the four net-new tests in a single `TestRecurringReminderReArm` class plus the test-plan doc refresh. The split gives reviewers a clean diff boundary and a clean rollback point if the conftest extraction surprises.

The test shape is uniform across all four methods: seed `Reminder(start_at, rrule_str)` → `reload` → connect recording slot to `reminder_due` → advance `Clock` past first `fire_at` → call `_on_timer()` → assert first signal → advance past next RRULE step → call `_on_timer()` → assert second signal with `event_at = dtstart + period` (oracle derived from RRULE spec, **never** from re-reading scheduler internals).

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Extract `Clock` class to conftest | `tests/conftest.py` owns the shared `Clock` class; three test files (`test_break_scheduler.py`, `test_reminder_scheduler.py`, `test_reminder_form_dialog.py`) lose their local class duplicates and import `Clock` from conftest; per-file `clock` fixtures stay local; collected test count unchanged vs HEAD baseline | Pyright resolving the new `Clock` import across ~100+ annotated test signatures — mitigated by running `uv run pyright` as automated verification |
| 2. Integration tests + doc refresh | `tests/test_recurring_reminder_integration.py` with 4 tests; test-plan §3 / §6 / §7 refreshed; rollout state advances to phase 1 complete | Oracle drift — accidentally re-reading `scheduler.py` for the expected value instead of deriving from the RRULE spec; mitigated by explicit Anti-pattern note in the plan + deliberate-regression smoke step in manual verification |

**Prerequisites:** None beyond the existing `uv sync`'d dev environment. The change branch (`test/testing-rrule-reminder-loop`) is already open from the `/10x-research` step.
**Estimated effort:** ~1 focused session (≤2 hours) across 2 phases — Phase 1 is ~20min of mechanical refactor, Phase 2 is ~60-90min of integration-test authoring + doc refresh.

## Open Risks & Assumptions

- **Assumption:** pytest auto-discovery picks up the conftest `clock` fixture in both existing test files with zero import changes. If a test signature type-annotates `clock: Clock`, an `from tests.conftest import Clock` line is needed. The Phase 1 pyright check catches this.
- **Decision (no residual risk):** The weekly test uses a literal `start_at = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)` (a Tuesday 13 days after the scheduler-file epoch) so the test is self-contained — independent of whether any `clock` fixture epoch later changes. Second-firing oracle is the literal `datetime(2026, 6, 9, 9, 0, tzinfo=UTC)`.
- **Known follow-up (not a blocker for this plan):** R-1b DST-drift fix is queued as a separate `/10x-shape` cycle. The TODO comment block in the new test file is the persistent breadcrumb; research.md §R-1b is the record.

## Success Criteria (Summary)

- `uv run pytest` reports the HEAD baseline + exactly 4 tests all green — the four new integration tests pin R-1a + R-1c without touching production code.
- A future re-run of `/10x-test-plan` reads `context/foundation/test-plan.md` §3, sees row 1 status `complete`, and routes to Phase 2 (R-2 modal stacking).
- The §6 Cookbook entry gives a future `/10x-tdd` or `/10x-plan` run enough scaffolding to write a Phase 2 modal-stacking integration test without re-reading research.md.
