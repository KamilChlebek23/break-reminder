"""Tests for ``BreakScheduler`` — the FR-008 active-time engine.

Covers:
  * FR-008 — active-time accumulation (counter advances only while user
    is non-idle; ticks during idle don't add).
  * FR-010 — snooze (decrements remaining, blocks during snooze window,
    re-fires after expiry, surfaces ``snooze_remaining=0`` once cap hit).
  * FR-016 — pause / resume (counter freezes while paused, resumes after).

Time is controlled via a clock callable injected into the scheduler
(``BreakScheduler(..., clock=...)``) so we never wait for real seconds.
The 1-second ``QTimer`` is bypassed entirely — tests call ``_tick()``
directly. That isolates the FR-008 logic from Qt's event-loop scheduling
and keeps the suite < 0.1s.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from break_reminder.activity import ActivityMonitor
from break_reminder.scheduler import BreakScheduler
from break_reminder.storage.settings import Settings

# ``ActivityMonitor.__init__`` is side-effect-free — pynput listeners are
# only spun up by ``start()``, which we never call in tests. Using the
# real class (rather than a hand-rolled fake) keeps the signal contract
# in lockstep with production and means there's no second class to keep
# in sync when ActivityMonitor evolves.


class Clock:
    """Mutable, controllable time source."""

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
def settings(tmp_path: Path) -> Settings:
    """A ``Settings`` instance with a 1-minute break interval, under ``tmp_path``."""
    s = Settings(ini_path=tmp_path / "BreakReminder.ini")
    # 1-minute interval keeps the threshold at 60 seconds — small enough
    # that a test loop hits it without churning through hundreds of ticks.
    s.break_interval_min = 1
    return s


@pytest.fixture
def activity() -> ActivityMonitor:
    """A bare ``ActivityMonitor``; no ``start()`` is called so no listeners spin up."""
    return ActivityMonitor()


@pytest.fixture
def clock() -> Clock:
    """A ``Clock`` pinned at 2026-05-20 06:00 UTC for deterministic time math."""
    return Clock(datetime(2026, 5, 20, 6, 0, tzinfo=UTC))


@pytest.fixture
def scheduler(settings: Settings, activity: ActivityMonitor, clock: Clock) -> BreakScheduler:
    """A ``BreakScheduler`` wired against the in-test settings, activity, and clock."""
    return BreakScheduler(settings=settings, activity=activity, clock=clock)


def _capture_break_due(sched: BreakScheduler) -> list[int]:
    """Subscribe a list-appender to the ``break_due`` signal.

    Direct-connection slots fire synchronously on the same thread, so
    after we call ``_tick()`` the list contains every emission so far.
    Simpler than ``qtbot.waitSignal`` for non-async assertions.
    """
    received: list[int] = []
    sched.break_due.connect(lambda n: received.append(n))
    return received


# ---------------------------------------------------------------------------
# FR-008 — active-time accumulation
# ---------------------------------------------------------------------------


class TestActiveTimeAccumulation:
    """FR-008 — active-time counter advances only while user is non-idle."""

    def test_active_input_advances_counter(
        self, scheduler: BreakScheduler, activity: ActivityMonitor, clock: Clock
    ) -> None:
        """A non-idle user sees the counter advance one second per tick."""
        # User just typed.
        activity.activity_detected.emit(clock())
        for _ in range(3):
            clock.advance(1)
            scheduler._tick()
        assert scheduler._active_seconds == 3

    def test_idle_user_does_not_advance_counter(
        self, scheduler: BreakScheduler, activity: ActivityMonitor, clock: Clock
    ) -> None:
        """An idle user (>60s since last input) does not advance the counter."""
        # User typed once, then went away well past the idle threshold (60s default).
        activity.activity_detected.emit(clock())
        clock.advance(300)
        for _ in range(5):
            clock.advance(1)
            scheduler._tick()
        # 5+ minutes idle: every tick sees idle ≫ 60s, no accumulation.
        assert scheduler._active_seconds == 0

    def test_returning_user_resumes_accumulation(
        self, scheduler: BreakScheduler, activity: ActivityMonitor, clock: Clock
    ) -> None:
        """A returning user resumes accumulation from the post-idle counter value."""
        # Initial activity, then idle.
        activity.activity_detected.emit(clock())
        clock.advance(300)
        for _ in range(5):
            clock.advance(1)
            scheduler._tick()
        assert scheduler._active_seconds == 0

        # User returns and starts typing again.
        activity.activity_detected.emit(clock())
        for _ in range(4):
            clock.advance(1)
            scheduler._tick()
        assert scheduler._active_seconds == 4

    def test_break_due_fires_when_threshold_reached(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """Crossing ``break_interval_min * 60`` seconds emits ``break_due``."""
        received = _capture_break_due(scheduler)

        for _ in range(60):  # 60s of active time = the 1-minute threshold
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()

        # Default max_snoozes is 1 and no snoozes have been used yet,
        # so the first emission carries snooze_remaining = 1.
        assert received == [1]

    def test_break_due_does_not_fire_below_threshold(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """``break_due`` does NOT fire while the counter is one tick short of threshold."""
        received = _capture_break_due(scheduler)
        for _ in range(59):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert received == []
        assert scheduler._active_seconds == 59


# ---------------------------------------------------------------------------
# Tooltip helper used by the tray icon
# ---------------------------------------------------------------------------


class TestSecondsUntilBreak:
    """The ``seconds_until_break`` helper consumed by the tray-icon tooltip."""

    def test_returns_full_threshold_at_start(self, scheduler: BreakScheduler) -> None:
        """A fresh scheduler reports the full threshold (60s for 1-min interval)."""
        assert scheduler.seconds_until_break == 60

    def test_decreases_as_counter_advances(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """``seconds_until_break`` decreases by 1 for each non-idle tick."""
        for _ in range(20):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert scheduler.seconds_until_break == 40

    def test_returns_zero_when_paused(self, scheduler: BreakScheduler) -> None:
        """``seconds_until_break`` is 0 while the scheduler is paused (FR-016)."""
        scheduler.pause()
        assert scheduler.seconds_until_break == 0


class TestSecondsUntilSnoozeEnd:
    """The ``seconds_until_snooze_end`` helper consumed by the tray-icon tooltip.

    Drives the snooze-aware tooltip branch (FR-010): returns ``None`` when no
    snooze is active or the window has elapsed, otherwise the whole-seconds
    remaining (rounded up) until ``_snooze_until``.
    """

    def test_returns_none_when_no_snooze_active(self, scheduler: BreakScheduler) -> None:
        """A fresh scheduler reports ``None`` — no snooze in progress."""
        assert scheduler.seconds_until_snooze_end is None

    def test_returns_positive_seconds_during_snooze(self, scheduler: BreakScheduler) -> None:
        """Right after ``on_break_snoozed()`` returns the full snooze duration."""
        scheduler.on_break_snoozed()
        # Default snooze duration is 5 minutes = 300 seconds.
        assert scheduler.seconds_until_snooze_end == 300

    def test_decreases_as_clock_advances(self, scheduler: BreakScheduler, clock: Clock) -> None:
        """The value tracks the wall-clock countdown to ``_snooze_until``."""
        scheduler.on_break_snoozed()
        clock.advance(60)
        assert scheduler.seconds_until_snooze_end == 240

    def test_returns_none_at_or_after_snooze_end(
        self, scheduler: BreakScheduler, clock: Clock
    ) -> None:
        """Past ``_snooze_until`` returns ``None`` even before ``_tick`` clears the field.

        Guarantees the tooltip flips back to the regular countdown the
        moment the snooze elapses, without waiting up to one second for
        the next ``_tick()``.
        """
        scheduler.on_break_snoozed()
        clock.advance(5 * 60)  # exactly at _snooze_until
        assert scheduler.seconds_until_snooze_end is None
        # And well past:
        clock.advance(60)
        assert scheduler.seconds_until_snooze_end is None
        # _snooze_until is intentionally not cleared yet — that's _tick's job.
        assert scheduler._snooze_until is not None


# ---------------------------------------------------------------------------
# FR-016 — pause / resume
# ---------------------------------------------------------------------------


class TestPauseResume:
    """FR-016 — pause / resume freezes and restarts accumulation."""

    def test_pause_stops_accumulation(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """A paused scheduler ignores every tick — counter stays at 0."""
        scheduler.pause()
        for _ in range(10):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert scheduler._active_seconds == 0

    def test_resume_restarts_accumulation(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """``resume()`` re-enables accumulation; subsequent ticks count."""
        scheduler.pause()
        for _ in range(5):
            clock.advance(1)
            scheduler._tick()
        scheduler.resume()
        for _ in range(5):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert scheduler._active_seconds == 5

    def test_pause_persists_to_settings(
        self, scheduler: BreakScheduler, settings: Settings
    ) -> None:
        """``pause()`` writes the flag through to the settings store."""
        scheduler.pause()
        # Simulate a fresh process reading the same INI.
        settings._qs.sync()
        assert settings.paused is True

    def test_resume_clears_settings_paused(
        self, scheduler: BreakScheduler, settings: Settings
    ) -> None:
        """``resume()`` clears the persisted paused flag."""
        scheduler.pause()
        scheduler.resume()
        settings._qs.sync()
        assert settings.paused is False

    def test_is_paused_property(self, scheduler: BreakScheduler) -> None:
        """``is_paused`` flips with each call to ``pause()`` / ``resume()``."""
        assert scheduler.is_paused is False
        scheduler.pause()
        assert scheduler.is_paused is True
        scheduler.resume()
        assert scheduler.is_paused is False


# ---------------------------------------------------------------------------
# FR-010 — snooze
# ---------------------------------------------------------------------------


class TestSnooze:
    """FR-010 — snooze decrements the cap and blocks firing during the window."""

    def test_on_break_snoozed_increments_snooze_count(self, scheduler: BreakScheduler) -> None:
        """``on_break_snoozed()`` increments ``_snoozes_used`` by exactly 1."""
        scheduler.on_break_snoozed()
        assert scheduler._snoozes_used == 1

    def test_on_break_snoozed_sets_snooze_window(
        self, scheduler: BreakScheduler, clock: Clock
    ) -> None:
        """``on_break_snoozed()`` sets ``_snooze_until`` to ``now + 5 min``."""
        scheduler.on_break_snoozed()
        # Default snooze duration is 5 minutes; window ends 5 min from now.
        assert scheduler._snooze_until == clock() + timedelta(minutes=5)

    def test_tick_during_snooze_window_does_not_fire(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """Ticks inside the snooze window do NOT emit additional ``break_due``."""
        received = _capture_break_due(scheduler)

        # Drive to first break_due.
        for _ in range(60):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert received == [1]

        scheduler.on_break_snoozed()

        # Tick a few times still inside the 5-minute snooze window.
        for _ in range(10):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()

        # No additional emissions — snooze window blocks firing.
        assert received == [1]

    def test_tick_after_snooze_expires_fires_again(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """The first tick after the snooze window re-emits ``break_due``."""
        received = _capture_break_due(scheduler)

        for _ in range(60):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert received == [1]

        scheduler.on_break_snoozed()
        # Jump past the 5-minute snooze window.
        clock.advance(6 * 60)
        activity.activity_detected.emit(clock())
        scheduler._tick()

        # Counter was held at threshold by on_break_snoozed, so the very
        # next post-window tick re-fires. snooze_remaining is now 0
        # (default max_snoozes = 1, used 1).
        assert received == [1, 0]

    def test_snooze_remaining_decreases_each_use(
        self,
        scheduler: BreakScheduler,
        settings: Settings,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """Each successive snooze decrements the ``snooze_remaining`` payload by 1."""
        # Allow up to 3 snoozes for this test.
        settings._qs.setValue("scheduling/max_snoozes", 3)
        settings._qs.sync()
        received = _capture_break_due(scheduler)

        # Cycle: drive to threshold → snooze → advance past window → repeat.
        for _ in range(60):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        # First fire: 3 snoozes still available.
        assert received[-1] == 3

        for expected_remaining in (2, 1, 0):
            scheduler.on_break_snoozed()
            clock.advance(6 * 60)
            activity.activity_detected.emit(clock())
            scheduler._tick()
            assert received[-1] == expected_remaining


# ---------------------------------------------------------------------------
# Cycle resets — on_break_taken returns the scheduler to a clean state
# ---------------------------------------------------------------------------


class TestOnBreakTaken:
    """``on_break_taken()`` returns the scheduler to a clean cycle state."""

    def test_resets_active_seconds(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """``on_break_taken()`` resets ``_active_seconds`` to 0."""
        for _ in range(30):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert scheduler._active_seconds == 30

        scheduler.on_break_taken()
        assert scheduler._active_seconds == 0

    def test_resets_snooze_state(
        self,
        scheduler: BreakScheduler,
    ) -> None:
        """``on_break_taken()`` clears ``_snoozes_used`` and ``_snooze_until``."""
        scheduler.on_break_snoozed()
        scheduler.on_break_taken()
        assert scheduler._snoozes_used == 0
        assert scheduler._snooze_until is None

    def test_full_cycle_after_taken_starts_fresh(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """A second cycle after ``on_break_taken()`` requires a full fresh threshold."""
        received = _capture_break_due(scheduler)

        # First cycle reaches threshold.
        for _ in range(60):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        scheduler.on_break_taken()

        # Second cycle: counter starts at zero, must do another full 60.
        for _ in range(59):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert len(received) == 1  # not yet
        activity.activity_detected.emit(clock())
        clock.advance(1)
        scheduler._tick()
        assert len(received) == 2  # second cycle fires
        # Both fires saw the default fresh max_snoozes = 1.
        assert received == [1, 1]


# ---------------------------------------------------------------------------
# Cycle resets — reset_cycle is the public primitive for clearing the cycle
# ---------------------------------------------------------------------------


class TestResetCycle:
    """``reset_cycle()`` is the public reset primitive (S-09 bugfix path).

    Mirrors ``TestOnBreakTaken``'s four observable assertions: the
    extraction is meant to be zero-behavior-change for ``on_break_taken``
    callers while exposing the primitive to a second caller — the
    settings-save bugfix wired through
    ``BreakReminderApp._on_break_interval_changed`` (see
    ``tests/test_app.py::TestOnBreakIntervalChanged``).
    """

    def test_resets_active_seconds(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """``reset_cycle()`` resets ``_active_seconds`` to 0."""
        for _ in range(30):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert scheduler._active_seconds == 30

        scheduler.reset_cycle()
        assert scheduler._active_seconds == 0

    def test_resets_snooze_state(
        self,
        scheduler: BreakScheduler,
    ) -> None:
        """``reset_cycle()`` clears ``_snoozes_used`` and ``_snooze_until``."""
        scheduler.on_break_snoozed()
        scheduler.reset_cycle()
        assert scheduler._snoozes_used == 0
        assert scheduler._snooze_until is None

    def test_does_not_change_pause_state(
        self,
        scheduler: BreakScheduler,
    ) -> None:
        """FR-016: ``reset_cycle()`` MUST NOT flip the pause toggle.

        Pause is independent of the break cycle — a settings save
        while paused must reset the accumulator but leave the user's
        explicit pause choice intact.
        """
        scheduler.pause()
        assert scheduler.is_paused

        scheduler.reset_cycle()

        assert scheduler.is_paused

    def test_full_cycle_after_reset_starts_fresh(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """A second cycle after ``reset_cycle()`` requires a full fresh threshold."""
        received = _capture_break_due(scheduler)

        for _ in range(60):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert len(received) == 1
        scheduler.reset_cycle()

        for _ in range(59):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        assert len(received) == 1  # not yet
        activity.activity_detected.emit(clock())
        clock.advance(1)
        scheduler._tick()
        assert len(received) == 2  # second cycle fires

    def test_on_break_taken_delegates_to_reset_cycle(
        self,
        scheduler: BreakScheduler,
        activity: ActivityMonitor,
        clock: Clock,
    ) -> None:
        """``on_break_taken`` produces the same observable state as ``reset_cycle``.

        Pinning the refactor: ``on_break_taken``'s body is now
        ``self.reset_cycle()``. The two paths must be observationally
        indistinguishable so existing callers (the dialog flow and
        the tray Reset action) keep working bit-for-bit.
        """
        for _ in range(15):
            activity.activity_detected.emit(clock())
            clock.advance(1)
            scheduler._tick()
        scheduler.on_break_snoozed()

        scheduler.on_break_taken()

        assert scheduler._active_seconds == 0
        assert scheduler._snoozes_used == 0
        assert scheduler._snooze_until is None
