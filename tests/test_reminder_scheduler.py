"""Tests for ``ReminderScheduler`` — the FR-014 RRULE engine.

Scope is the **clock-injection refactor** S-06 added: prove the scheduler
honors the injected clock for both ``reload()`` (recomputes the next
firing against ``self._clock()``) and the timer's "is it actually due
yet?" branch (``_on_timer`` re-arms when the wakeup landed early).
Tests bypass the real ``QTimer`` event-loop wait — we never sleep for
wall-clock seconds; instead we drive ``reload`` / ``_on_timer`` directly
and inspect the scheduler's internal state.

Mirrors the ``BreakScheduler`` test pattern in ``test_break_scheduler.py``
(``Clock`` helper, frozen ``start`` instant) so the test conventions for
the two engines stay aligned.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from break_reminder.scheduler import ReminderScheduler
from break_reminder.storage.reminders import Reminder, ReminderStore


class Clock:
    """Mutable, controllable time source — same shape as ``test_break_scheduler.Clock``."""

    def __init__(self, start: datetime) -> None:
        """Pin the clock at ``start``; later calls return the current ``_now``."""
        self._now = start

    def __call__(self) -> datetime:
        """Return the clock's current ``_now`` value."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Advance the clock forward by ``seconds`` real-time seconds."""
        self._now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> Clock:
    """A ``Clock`` pinned at 2026-05-20 06:00 UTC for deterministic time math.

    Same epoch the break-scheduler suite uses — keeps the two test files
    addressing the same instant when both schedulers are exercised in
    integration scenarios down the line.
    """
    return Clock(datetime(2026, 5, 20, 6, 0, tzinfo=UTC))


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Path to a per-test ``reminders.json`` file under ``tmp_path``."""
    return tmp_path / "reminders.json"


@pytest.fixture
def store(store_path: Path) -> ReminderStore:
    """A ``ReminderStore`` bound to the per-test ``store_path``."""
    return ReminderStore(path=store_path)


@pytest.fixture
def scheduler(store: ReminderStore, clock: Clock) -> ReminderScheduler:
    """A ``ReminderScheduler`` wired against the in-test store + injected clock."""
    return ReminderScheduler(store=store, clock=clock)


class TestClockInjection:
    """The clock parameter is honoured by ``reload()`` and ``_on_timer``."""

    def test_default_clock_is_used_when_not_injected(self, store: ReminderStore) -> None:
        """Omitting ``clock`` falls back to ``datetime.now(UTC)`` (production path).

        Tripwire for the refactor: if a future change drops the
        ``or _utcnow`` default, production callers (``app.py``) would
        crash on the first ``reload()`` because ``self._clock`` would
        be ``None``.
        """
        # No clock arg — the scheduler must work without one.
        s = ReminderScheduler(store=store)
        s.reload()  # must not raise
        # No reminders → no _next set → nothing to assert beyond no-raise.
        assert s._next is None

    def test_reload_uses_injected_clock_for_next_computation(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """``reload()`` computes ``ms`` from the injected clock, not wall-clock.

        Seeds a reminder 10 minutes in the future *as the injected clock
        sees it*. After ``reload()``, ``_next.fire_at`` matches the
        seeded start time. Wall clock is irrelevant.
        """
        future = clock() + timedelta(minutes=10)
        store.add(Reminder(name="future", start_at=future))

        scheduler.reload()

        assert scheduler._next is not None
        assert scheduler._next.fire_at == future

    def test_reload_arms_qtimer_for_future_reminder(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """A future reminder leaves the timer active after ``reload()``.

        Cross-validates the clock injection from a different angle:
        ``reload()`` doesn't just populate ``_next``, it also arms
        the underlying ``QTimer``. Demonstrating the timer is active
        after reload proves the ``ms`` computation
        (``self._next.fire_at - self._clock()``) produced a positive
        number that ``QTimer.start`` accepted.
        """
        future = clock() + timedelta(minutes=5)
        store.add(Reminder(name="future", start_at=future))

        scheduler.reload()

        assert scheduler._timer.isActive()
        # remainingTime is the residual ms; for a 5-minute future
        # firing it should be roughly 5*60*1000 = 300000, capped at
        # the 24-hour ceiling of 86_400_000. Loose bound — exact value
        # depends on Qt's internal clock resolution.
        assert 0 < scheduler._timer.remainingTime() <= 5 * 60 * 1000 + 1

    def test_reload_caps_timer_at_24h_for_far_future_reminder(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """Reminders >24h out arm the ``QTimer`` at the 24h cap (86_400_000 ms).

        Retrospective impl-review F1: pins the daily-wakeup ceiling that
        ``reload()`` enforces at ``scheduler.py`` (``min(ms, 24*60*60*1000)``).
        Without this assertion, a future change that dropped the cap (e.g.
        passing the full delta to ``QTimer.start`` for a reminder 30 days
        out) would not fail any test — ``QTimer.start`` has a ~24.8-day
        32-bit-ms ceiling, so an uncapped delta could either silently
        overflow on 32-bit platforms or skip the daily integrity-check
        rearm branch entirely on 64-bit.
        """
        far_future = clock() + timedelta(days=30)
        store.add(Reminder(name="far", start_at=far_future))

        scheduler.reload()

        assert scheduler._timer.isActive()
        assert scheduler._timer.interval() == 24 * 60 * 60 * 1000

    def test_compute_next_picks_soonest_future(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """When multiple reminders are future per the clock, the earliest wins."""
        far = clock() + timedelta(hours=2)
        soon = clock() + timedelta(minutes=10)
        store.add(Reminder(name="far", start_at=far))
        store.add(Reminder(name="soon", start_at=soon))

        scheduler.reload()

        assert scheduler._next is not None
        assert scheduler._next.fire_at == soon

    def test_compute_next_skips_expired_one_shots(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """One-shot reminders with ``start_at`` strictly before clock are skipped (per ``next_firing_after``).

        ``next_firing_after`` uses ``inc=False`` semantics, so a one-shot
        whose ``start_at`` exactly equals the clock returns ``None`` —
        which the scheduler must treat as "no candidate". Demonstrates
        the clock injection composes correctly with the RRULE-aware
        firing helper.
        """
        past = clock() - timedelta(hours=1)
        store.add(Reminder(name="past_one_shot", start_at=past))

        scheduler.reload()

        # The past one-shot produced no candidate; nothing to fire.
        assert scheduler._next is None

    def test_on_timer_early_wakeup_rearms_via_clock(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """The daily-wakeup branch in ``_on_timer`` consults the injected clock.

        Arm against a reminder more than 24 hours out — ``reload()``
        caps the wait at 24h so when the wakeup lands the reminder is
        not actually due yet. ``_on_timer`` consults ``self._clock()``
        to detect "not actually due yet" and rearms via ``reload``. We
        don't advance the clock between ``reload`` and ``_on_timer``,
        so the call is the no-op rearm branch. Without the clock
        injection, this branch would compare against wall-clock and
        the test would be non-deterministic.
        """
        far_future = clock() + timedelta(days=7)
        store.add(Reminder(name="weekly_out", start_at=far_future))

        scheduler.reload()
        assert scheduler._next is not None
        original_next = scheduler._next

        # Simulate the daily wakeup firing without advancing the clock.
        # The branch sees ``self._clock() < self._next.fire_at`` and
        # re-arms by calling ``reload`` again.
        scheduler._on_timer()

        # State: same _next (rearmed against the same reminder).
        assert scheduler._next is not None
        assert scheduler._next.fire_at == original_next.fire_at

    def test_on_timer_fires_when_clock_caught_up(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """When the injected clock has reached ``_next.fire_at``, the slot emits.

        Drive the reminder due by advancing the clock past ``fire_at``.
        ``_on_timer`` reads ``self._clock()`` and proceeds to fire.
        Connect a recording slot to ``reminder_due`` so the assertion
        doesn't need ``qtbot``.

        S-06b: the signal now carries ``(name, event_at)``. For a
        ``lead_minutes=0`` reminder, event_at == fire_at; the test
        pins both halves of the payload.
        """
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

    def test_on_timer_fires_with_event_at_offset_by_lead_minutes(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """S-06b: ``event_at`` in the signal payload = ``fire_at + lead_minutes``.

        With ``start_at`` 10 min out and ``lead_minutes=15``, the
        scheduler still arms on ``start_at`` (firing time, Model A)
        but the emitted ``event_at`` is 15 minutes later — exactly
        the user's original event time, reconstructed from the
        round-trip metadata. This is the load-bearing signal contract
        the popup body depends on.
        """
        fire_at = clock() + timedelta(minutes=10)
        store.add(Reminder(name="with-lead", start_at=fire_at, lead_minutes=15))

        scheduler.reload()
        received: list[tuple[str, datetime]] = []

        def _capture(name: str, event_at: datetime) -> None:
            received.append((name, event_at))

        scheduler.reminder_due.connect(_capture)

        clock.advance(601)
        scheduler._on_timer()

        # event_at = fire_at + 15 min; specifically NOT equal to fire_at.
        expected_event = fire_at + timedelta(minutes=15)
        assert received == [("with-lead", expected_event)]
        assert received[0][1] != fire_at  # tripwire: the lead actually shifts it


class TestReloadReentrancy:
    """``reload()`` can be called again safely without stale state."""

    def test_reload_replaces_next_after_store_mutation(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """Adding a sooner reminder + calling ``reload`` updates ``_next``.

        This is the exact production flow ``ReminderFormDialog.accept``
        triggers: persist via ``store.add``, then call
        ``scheduler.reload()`` so the running session knows about the
        new candidate before the dialog closes.
        """
        far = clock() + timedelta(hours=3)
        store.add(Reminder(name="far", start_at=far))
        scheduler.reload()
        assert scheduler._next is not None
        assert scheduler._next.fire_at == far

        # Now add a sooner one and reload — the production "Add" flow.
        sooner = clock() + timedelta(minutes=15)
        store.add(Reminder(name="sooner", start_at=sooner))
        scheduler.reload()

        assert scheduler._next is not None
        assert scheduler._next.fire_at == sooner

    def test_reload_clears_next_when_store_emptied(
        self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """If every reminder is deleted between reloads, ``_next`` becomes ``None``."""
        future = clock() + timedelta(minutes=10)
        reminder = Reminder(name="solo", start_at=future)
        store.add(reminder)
        scheduler.reload()
        assert scheduler._next is not None

        store.delete(reminder.id)
        scheduler.reload()

        assert scheduler._next is None
