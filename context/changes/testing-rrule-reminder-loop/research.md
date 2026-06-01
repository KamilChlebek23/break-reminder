---
date: 2026-06-01T20:09:00+02:00
researcher: Chlebek, Kamil
git_commit: 275bf032eec140fa4a21956b4c6ba76b5c69fc2f
branch: test/testing-rrule-reminder-loop
repository: break-reminder
topic: "Ground rollout Phase 1 of context/foundation/test-plan.md (R-1 recurring-reminder re-arm loop)"
tags: [research, scheduler, reminder, rrule, dst, fr-014, r-1]
status: complete
last_updated: 2026-06-01
last_updated_by: Chlebek, Kamil
---

# Research: Ground rollout Phase 1 of `context/foundation/test-plan.md` (R-1 recurring-reminder re-arm loop)

**Date**: 2026-06-01T20:09:00+02:00
**Researcher**: Chlebek, Kamil
**Git Commit**: `275bf032eec140fa4a21956b4c6ba76b5c69fc2f`
**Branch**: `test/testing-rrule-reminder-loop`
**Repository**: `break-reminder`

## Research Question

Ground rollout Phase 1 of `context/foundation/test-plan.md` — the "Integration-test foundation + recurring-reminder loop" phase whose primary risk is **R-1**:

> A recurring reminder (daily / weekly / monthly RRULE) fires once and silently misses the next occurrence — the second firing never appears even though the configured time arrived. The 24h `QTimer.singleShot` cap or a DST transition silently drifts the next-firing time.

Following the test plan's §2 Risk Response Guidance row R-1:

- **What would prove protection:** a daily reminder fires today AND tomorrow on a fast-forwarded virtual clock; weekly/monthly reminders fire on the correct subsequent occurrence across a simulated DST boundary; the 24h `QTimer.singleShot` cap re-enters correctly when the next firing is > 24h out.
- **Must challenge:** "Re-arm is just `QTimer.singleShot(ms, _fire_reminder)`" — verify whether the firing callback recomputes `next_firing_after(now)` and re-arms, and whether the 24h cap branch is re-entered when the original gap was > 24h.
- **Anti-pattern to avoid:** mocking `QTimer.singleShot` and asserting it was called with X ms — implementation mirror / oracle problem. The oracle must come from the RRULE specification, not from re-reading the scheduler implementation.

## Summary

R-1's grounding splits cleanly into three sub-risks. Two are pure test-coverage gaps; the third is a real production defect this grounding surfaced.

- **R-1a (re-arm regression) — coverage gap, NOT a code defect.** `_on_timer` correctly fires THEN re-arms via `reload()` in the same call. The existing test `test_on_timer_fires_when_clock_caught_up` exercises the first firing only; it never advances the clock further and asserts the second firing of a recurring reminder.
- **R-1c (24h `QTimer.singleShot` cap re-entry) — coverage gap, NOT a code defect.** `reload()` caps the timer at `min(ms, 24*60*60*1000)` on every call. The existing test `test_reload_caps_timer_at_24h_for_far_future_reminder` (the retrospective F1 retrofit) pins the cap for a far-future **one-shot**; no test exercises a **recurring** reminder whose next occurrence requires the cap to re-enter via the early-wakeup branch across multiple wakeups.
- **R-1b (DST drift) — REAL production defect surfaced by this grounding.** All reminder `start_at` values are stored as tz-aware UTC (storage invariant + form save-time conversion); RRULE arithmetic runs `rrulestr(rule, dtstart=start_at_utc).after(now)` in UTC space; therefore a "daily at 9:00 local" reminder stored on a CET day drifts to "10:00 local" after spring-forward. The S-08 plan-brief documented DST-correctness for the `end_at` conversion but never raised the firing-time-across-DST scenario. **This is exactly the "next-firing time silently drifts" failure mode R-1 worried about.**

Implication for `/10x-plan`: R-1a and R-1c are pure test additions in the existing `pytest-qt` + `Clock` idiom (small surface, no code change). R-1b is a discovery — the rollout can either add a failing test pinning the defect and open a separate bugfix change, or defer with documented evidence. See Open Questions.

## Detailed Findings

### § R-1a — Re-arm after fire (coverage gap)

**Production code is correct.** [`break_reminder/scheduler.py:310-319`](break_reminder/scheduler.py):

```310:319:break_reminder/scheduler.py
    def _on_timer(self) -> None:
        if self._next is None:
            return
        now = self._clock()
        if now < self._next.fire_at:
            # Daily-wakeup case: not actually due yet, just rearm.
            self.reload()
            return
        self._fire(self._next.reminder_id)
        self.reload()
```

The post-fire `self.reload()` call (line 319) is the load-bearing re-arm. `reload()` ([`scheduler.py:297-306`](break_reminder/scheduler.py)) calls `self._compute_next()` which calls `next_firing_after(reminder, self._clock())` for every reminder — `inc=False` semantics on `rule.after(now)` ([`scheduler.py:367`](break_reminder/scheduler.py)) guarantee the next occurrence is strictly after the current clock, so for a recurring reminder the next firing instant lands at the next valid RRULE step. **Challenge from the test plan resolved:** the re-arm is not "just `QTimer.singleShot(ms, _fire_reminder)`" — it's `reload()` which re-runs the entire candidate-selection pipeline. That's stronger than the prompt assumed (and means a stale `_next` cannot survive a fire).

**Test coverage gap.** [`tests/test_reminder_scheduler.py:215-245`](tests/test_reminder_scheduler.py) (`test_on_timer_fires_when_clock_caught_up`):

```215:245:tests/test_reminder_scheduler.py
    def test_on_timer_fires_when_clock_caught_up(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """When the injected clock has reached ``_next.fire_at``, the slot emits."""
        future = clock() + timedelta(minutes=10)
        store.add(Reminder(name="aware", start_at=future))

        scheduler.reload()
        received: list[tuple[str, datetime]] = []

        def _capture(name: str, event_at: datetime) -> None:
            received.append((name, event_at))

        scheduler.reminder_due.connect(_capture)

        # Advance clock past the firing instant, then fire the slot.
        clock.advance(601)
        scheduler._on_timer()

        # With lead_minutes=0, event_at == fire_at == the original start_at.
        assert received == [("aware", future)]
```

The reminder is a **one-shot** (no `rrule_str`), so after firing `_compute_next()` returns `None` and `_next` becomes `None` — there's nothing further to test. A re-arm regression that broke ONLY the second occurrence of a recurring reminder (e.g., a future refactor that drops the `self.reload()` call on line 319) would pass this test.

**Gap to close in Phase 1:** an integration test that seeds a `FREQ=DAILY` reminder, fires it once via `_on_timer()` + advanced clock, then advances the clock by another 24h and fires `_on_timer()` again, asserting the second firing's `event_at` equals `start_at + timedelta(days=1)`. The oracle is `dtstart + 1 day` derived from the RRULE, NOT from re-reading `scheduler.py`.

### § R-1c — 24h `QTimer.singleShot` cap re-entry (coverage gap)

**Production code is correct.** [`break_reminder/scheduler.py:297-306`](break_reminder/scheduler.py):

```297:306:break_reminder/scheduler.py
    def reload(self) -> None:
        """Recompute next firing across all reminders. Call on add/edit/delete."""
        self._timer.stop()
        self._next = self._compute_next()
        if self._next is None:
            return
        ms = max(0, int((self._next.fire_at - self._clock()).total_seconds() * 1000))
        # QTimer.start has a 32-bit ms limit (~24.8 days). Reminders further
        # out than that get a daily wakeup that re-checks.
        self._timer.start(min(ms, 24 * 60 * 60 * 1000))
```

Every `reload()` call applies the cap. `_on_timer` ([`scheduler.py:310-319`](break_reminder/scheduler.py)) handles the early-wakeup case (clock not yet past `fire_at`) by calling `self.reload()` again — and `reload` will re-apply the cap. So a reminder armed 7 days out gets a daily wakeup → reload → 24h cap → daily wakeup → reload → 24h cap → ... until the final wakeup lands `now >= _next.fire_at` and `_fire` runs.

**Test coverage gap.** [`tests/test_reminder_scheduler.py:130-150`](tests/test_reminder_scheduler.py) (`test_reload_caps_timer_at_24h_for_far_future_reminder`) pins the cap for a **one-shot** reminder 30 days out — added as the retrospective F1 retrofit (see Historical Context). [`tests/test_reminder_scheduler.py:185-213`](tests/test_reminder_scheduler.py) (`test_on_timer_early_wakeup_rearms_via_clock`) tests the early-wakeup branch firing exactly once without advancing the clock. **Neither test crosses a `_fire` boundary**, so a regression that broke the cap re-entry after the first fire of a long-cadence recurring reminder (e.g., monthly) would not fail any existing test.

**Gap to close in Phase 1:** an integration test that seeds a `FREQ=WEEKLY;BYDAY=TU` reminder whose `start_at` is 8 days out (so the first occurrence is > 24h away, requiring at least one early-wakeup cap re-entry), drives `_on_timer()` once with the clock unchanged (cap re-entry path), advances the clock past `fire_at`, drives `_on_timer()` again (fire + reload), advances another 7 days, and asserts the second weekly firing happens.

### § R-1b — DST drift (REAL production defect)

The grounding traced the firing-time data flow end-to-end and surfaced a defect the S-08 recurrence-editor work missed.

**The UTC invariant chain.** All `Reminder.start_at` values flow as tz-aware UTC at the storage boundary. [`break_reminder/storage/reminders.py:114-128`](break_reminder/storage/reminders.py) — the `Reminder` dataclass docstring:

```114:128:break_reminder/storage/reminders.py
@dataclass
class Reminder:
    """A user-created custom reminder (FR-011).

    Invariant: ``start_at`` and ``end_at`` (when set) are always
    **tz-aware UTC** ``datetime`` instances. Every constructing code
    path — ``ReminderFormDialog.accept``, the scheduler's recurrence
    math, and the storage layer's ``from_dict`` — produces tz-aware
    UTC values. ...
    """
```

[`storage/reminders.py:75-111`](break_reminder/storage/reminders.py) (`_coerce_aware_utc`) and `from_dict` ([line 164](break_reminder/storage/reminders.py)) enforce the invariant on disk-load. [`break_reminder/ui/reminder_form_dialog.py:303-329`](break_reminder/ui/reminder_form_dialog.py) (`_local_date_to_utc_end_of_day`) and the `accept()` save path apply `naive_local.astimezone(UTC)` — DST-correct **for the wall-clock value at save time**.

**The defect in firing math.** [`break_reminder/scheduler.py:362, 367`](break_reminder/scheduler.py):

```361:367:break_reminder/scheduler.py
    try:
        rule = rrulestr(reminder.rrule_str, dtstart=start)
    except Exception:  # noqa: BLE001 — corrupt RRULE shouldn't crash the scheduler
        logger.exception("invalid RRULE for reminder %s", reminder.id)
        return None

    nxt = rule.after(now, inc=False)
```

`start` is tz-aware UTC. `dateutil.rrule.rrulestr` builds the rule with `dtstart=start_utc`, so `FREQ=DAILY` produces firings at `start_utc + N*timedelta(days=1)` in UTC space. Every firing is **the same UTC instant offset N days from `dtstart`** — which translates to **a different local time** across a DST transition.

**Worked example (Europe/Warsaw, March 28 → 29, 2026 spring-forward):**

| Day | Local picked / observed | UTC stored / fired |
|---|---|---|
| Mar 28 (Sat, CET, UTC+1) | User picks "Daily 9:00" → form saves | `08:00 UTC` |
| Mar 29 (Sun, CEST, UTC+2 from 02:00 local) | Daily RRULE fires at next `08:00 UTC` | `08:00 UTC` = **10:00 CEST local** — off by 1h |
| Mar 30 onward | Continues at `08:00 UTC` | All firings now at **10:00 CEST** local |

The user's reminder silently drifts one hour later for the entire summer, then back to 9:00 local on the autumn fall-back, then off again the next spring. **No test catches it; no log entry surfaces it; the only signal is the user noticing the wrong time.** This is the exact "silently drifts" failure mode R-1 prompts for, with a concrete reproduction surface.

**Why the existing tests miss it.** [`tests/test_scheduler.py:79-84`](tests/test_scheduler.py) (`test_naive_datetime_is_treated_as_utc`) confirms naive datetimes are interpreted as UTC, which entrenches the UTC invariant rather than testing across DST. Every datetime in [`tests/test_scheduler.py`](tests/test_scheduler.py) and [`tests/test_reminder_scheduler.py`](tests/test_reminder_scheduler.py) uses `tzinfo=UTC` (UTC has no DST), so the firing arithmetic is never exercised across a transition.

**Why the S-08 recurrence editor work missed it.** [`context/archive/2026-05-28-reminders-recurrence-editor/plan-brief.md:73`](context/archive/2026-05-28-reminders-recurrence-editor/plan-brief.md) explicitly considered DST — but only for the `end_at` local-to-UTC conversion ("End-date local→UTC conversion across DST transitions may produce surprising stored values"). [`context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md:56-58`](context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md) claims "DST correctness" — but scoped to `_local_date_to_utc_end_of_day`, NOT to the recurring firing path. The firing-time-across-DST scenario was never raised because the S-08 work focused on save-time UI; the per-firing recurrence math was already shipped in S-06 and treated as out of scope.

**Fix is out of scope for this rollout phase.** The fix requires either (a) storing `Reminder.start_at` with a zone-aware IANA timezone (e.g., `Europe/Warsaw`) instead of UTC, then `rrulestr(rule, dtstart=start_with_iana_tz)` will respect local-time-across-DST automatically; or (b) storing a separate `tz: str` field alongside a naive local datetime, then constructing a zone-aware datetime on load. Either change is a Reminder-dataclass invariant change touching the storage round-trip, the form save/load paths, and every test that constructs a `Reminder`. Worth its own `/10x-shape` cycle.

## Code References

Sortable list for `/10x-plan` consumption.

### Production code (the failure-anchor and re-arm surface)

- `break_reminder/scheduler.py:297-306` — `ReminderScheduler.reload()`; the 24h cap branch (line 306).
- `break_reminder/scheduler.py:310-319` — `_on_timer`; the early-wakeup re-arm branch (lines 314-317) and the post-fire re-arm (line 319). The load-bearing R-1a surface.
- `break_reminder/scheduler.py:321-334` — `_fire`; emits `reminder_due(name, event_at)` per S-06b lead-time contract.
- `break_reminder/scheduler.py:336-345` — `_compute_next`; iterates `store.list_all()` and picks the earliest future firing.
- `break_reminder/scheduler.py:348-373` — `next_firing_after(reminder, now)`; the pure RRULE helper. `rule.after(now, inc=False)` on line 367 is the firing-instant math; `_ensure_aware` (line 376-380) entrenches the UTC default.
- `break_reminder/storage/reminders.py:114-128` — `Reminder` dataclass invariant: `start_at`/`end_at` are tz-aware UTC.
- `break_reminder/storage/reminders.py:75-111` — `_coerce_aware_utc`; normalizes hand-edited naive datetimes to UTC.
- `break_reminder/storage/reminders.py:164` — `from_dict` enforces UTC on disk-read.
- `break_reminder/ui/reminder_form_dialog.py:303-329` — `_local_date_to_utc_end_of_day`; per-instant DST-correct **at save time** (different problem from R-1b).
- `break_reminder/ui/reminder_form_dialog.py:566-590` — `_compute_default_datetime` + `accept()` UTC ↔ local dance (the save-time conversion that loses the user's local-time intent).

### Existing test coverage (the gaps to close in Phase 1)

- `tests/test_reminder_scheduler.py:27-40` — `Clock` helper; the load-bearing test idiom Phase 1's integration harness will extend.
- `tests/test_reminder_scheduler.py:130-150` — `test_reload_caps_timer_at_24h_for_far_future_reminder`; pins the 24h cap for a one-shot. **R-1c gap**: no equivalent for a recurring reminder requiring multi-day cap re-entry.
- `tests/test_reminder_scheduler.py:185-213` — `test_on_timer_early_wakeup_rearms_via_clock`; pins the cap re-entry path for a one-shot. **R-1c gap**: no equivalent across a `_fire` boundary.
- `tests/test_reminder_scheduler.py:215-245` — `test_on_timer_fires_when_clock_caught_up`; pins the first firing of a one-shot. **R-1a gap**: no follow-up assertion on the second firing of a recurring reminder.
- `tests/test_reminder_scheduler.py:247-276` — `test_on_timer_fires_with_event_at_offset_by_lead_minutes`; S-06b lead-time contract. Lead interacts with recurrence per [`context/archive/2026-05-28-reminders-recurrence-editor/plan.md:51`](context/archive/2026-05-28-reminders-recurrence-editor/plan.md) — Phase 1 tests should cover lead+recurrence + DST as a combinatorial.
- `tests/test_scheduler.py:25-85` — pure `next_firing_after` arithmetic. **R-1b gap**: every test uses `tzinfo=UTC` (no DST). A new parametrized test class would seed a zone-aware datetime in `Europe/Warsaw` and assert the firing across spring-forward — and the test would **FAIL** today, pinning R-1b.

### Wiring (cross-module flow context for Phase 4, not Phase 1)

- `break_reminder/app.py:104, 123, 131, 278, 332-347` — `ReminderScheduler` instantiation, start/stop, signal-to-popup wiring, and threading into `SettingsDialog`.
- `break_reminder/ui/reminder_form_dialog.py:843-996` — Add/Edit save flow: `validate → store.add/update → scheduler.reload → emit → accept`.

## Architecture Insights

Three patterns the Phase 1 integration harness must respect.

1. **Clock injection is the universal scheduler-test pattern.** Both `BreakScheduler` ([`scheduler.py:66-78`](break_reminder/scheduler.py)) and `ReminderScheduler` ([`scheduler.py:262-282`](break_reminder/scheduler.py)) accept `clock: Callable[[], datetime] | None`. The existing `Clock` helper in [`tests/test_reminder_scheduler.py:27-40`](tests/test_reminder_scheduler.py) (mutable `_now` advanced via `advance(seconds: float)`) is the load-bearing idiom. Phase 1's integration tests must extend this exact helper, not invent a new one. The two scheduler test files (`test_break_scheduler.py`, `test_reminder_scheduler.py`) already share the same `Clock` shape and epoch (`2026-05-20 06:00 UTC`); the harness should keep that alignment.

2. **UTC-only datetime invariant at the storage boundary makes integration tests deterministic but masks DST scenarios.** Every `Reminder` constructed by the form, the storage layer, or a test fixture is tz-aware UTC. R-1a and R-1c tests can stay UTC and remain trivially deterministic. R-1b tests must **deliberately reach across** the invariant — constructing a `Reminder` directly with a `dateutil.tz.gettz("Europe/Warsaw")` datetime, bypassing the form/storage normalization — to surface the defect. This is the only honest way to pin R-1b without changing production code.

3. **`_on_timer` always recomputes via `reload()` → `_compute_next()` after firing.** The post-fire re-arm path is exercisable by advancing `Clock` past `fire_at` and calling `_on_timer()` directly — no `qtbot.waitSignal`, no real-time wait, no Qt event-loop spin required. The existing test `test_on_timer_fires_when_clock_caught_up` ([`tests/test_reminder_scheduler.py:215-245`](tests/test_reminder_scheduler.py)) demonstrates this. Phase 1's integration tests for R-1a/R-1c follow the same shape: add reminder → reload → assert `_next.fire_at` matches RRULE expected → advance Clock → `_on_timer()` → assert signal received → advance Clock → `_on_timer()` → assert next signal received with the next expected `fire_at`. The "integration" qualifier the test plan envisioned distinguishes this from existing tests by crossing the `_fire` boundary and re-asserting on the post-fire `_next` state, not by adding a heavier test framework.

## Historical Context (from prior changes)

- [`context/archive/2026-05-27-reminders-add-form/reviews/retrospective-impl-review.md:54-71`](context/archive/2026-05-27-reminders-add-form/reviews/retrospective-impl-review.md) — **F1 retrofit landed the 24h-cap assertion.** The original S-06 plan named four scheduler test classes; the impl collapsed them to two and dropped the cap assertion. The retrospective review caught it and added `test_reload_caps_timer_at_24h_for_far_future_reminder` (the one-shot 30-day-out test). Scope was one-shot only; the recurring-reminder cap re-entry was never added. **R-1c is the natural extension of this F1 work.**

- [`context/archive/2026-05-28-reminders-recurrence-editor/plan-brief.md:73`](context/archive/2026-05-28-reminders-recurrence-editor/plan-brief.md) — **DST was considered for end-date conversion only.** Verbatim: "End-date local→UTC conversion across DST transitions may produce surprising stored values (e.g. picking July 31 in winter might store an August 1 UTC instant). The conversion uses `astimezone(UTC)` which is DST-correct per-instant; tests on a frozen system zone pin the round-trip." Firing-time DST was not raised.

- [`context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md:56-58`](context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md) — **"DST correctness" claim is scoped to `_local_date_to_utc_end_of_day`.** Verbatim: "DST correctness. `_local_date_to_utc_end_of_day` uses `datetime.combine(picked, time(23, 59, 59)).astimezone(UTC)` (line 328-329) — the same per-instant DST-correct idiom the form's existing datetime save path uses." The claim does not extend to the recurring firing path, but reads as if it does — which likely contributed to the defect going unnoticed.

- [`context/archive/2026-05-28-reminders-recurrence-editor/plan.md:5-15`](context/archive/2026-05-28-reminders-recurrence-editor/plan.md) — **S-08 explicitly left the scheduler engine "unchanged".** Verbatim: "Storage (`Reminder.rrule_str` / `Reminder.end_at`) and the scheduler RRULE engine are unchanged — both have shipped end-to-end and are covered by `tests/test_reminders.py` and `tests/test_scheduler.py`." The "covered by" claim is true for the RRULE arithmetic axes the existing tests check (daily/weekly/monthly forward steps in UTC space) but not for DST.

## Related Research

None yet — this is the first research artifact under `context/changes/` (the prior `context/archive/**/plan-brief.md` files served the same role pre-S-09).

## Open Questions

1. **R-1b fix scope.** Does the test-plan rollout (a) add a failing test (`pytest.mark.xfail`) pinning the DST defect in Phase 1, open a separate bugfix change like `bugfix-reminder-dst-drift` immediately, and let the rollout phase land with a known-failing test; or (b) defer with a TODO comment in Phase 1's tests and a documented note that the bugfix is a separate cycle? Option (a) gives the user a regression signal the moment the bug is fixed; option (b) keeps the test suite green. **Owner: user. Block: `/10x-plan`.**

2. **Storage tzinfo carriage to fix R-1b.** The simplest fix is changing `Reminder.start_at` to carry an IANA timezone (e.g., `Europe/Warsaw`) rather than UTC, so `rrulestr(rule, dtstart=start_with_iana_tz)` does DST-aware math automatically. That invariant change touches the dataclass, the storage round-trip (`from_dict` / `to_dict`), every constructing call site (form save/load, scheduler internals), and every test that builds a `Reminder`. Alternative: keep `start_at` naive local + add a `tz: str` IANA-name field, reconstruct on load. Either way it's a meaningful change. **Probably warrants its own `/10x-shape` cycle before any code lands.** Owner: user. Block: a future `bugfix-reminder-dst-drift` change, not this phase.

3. **GitHub permalinks.** Current HEAD `275bf032eec140fa4a21956b4c6ba76b5c69fc2f` is the `docs(test-plan): add phased rollout closing zero-integration-tests gap` commit just made; it is NOT pushed to `origin/master`. The branch `test/testing-rrule-reminder-loop` is also local-only. SKILL.md step 8 says to use GitHub permalinks when on main or pushed; neither holds today. This research file uses local `path:line` references only. A follow-up edit can swap to permalinks once the branch is pushed and the commit is reachable.

4. **Was R-2 (modal-stacking wedge degradation) primed by anything in `scheduler.py` reading?** No — the scheduler is signal-emit-only ([`scheduler.py:255-256`](break_reminder/scheduler.py): `reminder_due = Signal(str, datetime)`); it doesn't construct dialogs. R-2's anchors live in the dialog layer (`break_reminder/notifications/break_dialog.py`, `break_reminder/notifications/reminder_dialog.py`, `break_reminder/ui/settings_dialog.py`) and are properly Phase 2's research scope, not Phase 1's. Flagging here so the Phase 2 research has a clean starting point.
