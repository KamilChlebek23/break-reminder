"""Integration tests for the FR-014 recurring-reminder fire-then-re-arm loop (R-1).

Scope: cross the ``ReminderScheduler._fire`` boundary and re-assert on
the post-fire ``_next`` state — the qualifying distinction from the
per-method unit tests in ``tests/test_reminder_scheduler.py``. Pins:

- **R-1a** (re-arm after fire) for daily, weekly, and monthly RRULEs.
- **R-1c** (24h ``QTimer.singleShot`` cap re-entry across the fire
  boundary) via the weekly test whose ``start_at`` is 13 days out.
- **S-06b signal contract** (``event_at = fire_at + lead_minutes``)
  across two firings of a recurring reminder, not just the first.

See ``context/foundation/test-plan.md`` §2 R-1 ("Risk map") and
``context/changes/testing-rrule-reminder-loop/research.md`` (§R-1a,
§R-1c) for the threat model these tests close.

Oracle source rule (test-plan §2 R-1 "Anti-pattern to avoid"): every
``event_at`` assertion derives its expected value from the RRULE spec
(e.g. ``start_at + timedelta(days=1)`` for ``FREQ=DAILY``), NEVER from
re-reading ``scheduler.next_firing_after``. If a future RRULE bug
changes the scheduler output, these tests must FAIL — not silently
agree with the regression.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from break_reminder.scheduler import ReminderScheduler
from break_reminder.storage.reminders import Reminder, ReminderStore
from tests.conftest import Clock

# TODO(R-1b): A failing test pinning the DST-drift defect surfaced by
# `/10x-research` is intentionally NOT in this file — the fix requires a
# Reminder.start_at invariant change (UTC -> IANA-tz-aware) and warrants
# its own `/10x-shape` cycle as `bugfix-reminder-dst-drift`. See:
#   context/changes/testing-rrule-reminder-loop/research.md  (section R-1b)
#   context/changes/testing-rrule-reminder-loop/research.md  Open Questions #1, #2
# When the bugfix change opens, the failing test belongs in
# tests/test_scheduler.py (next_firing_after RRULE arithmetic across DST),
# NOT here — DST is a pure-helper concern, not an integration concern.
#
# Phase 4 (R-4) note: `clock`, `store_path`, `store`, and (renamed)
# `reminder_scheduler` previously lived as local fixtures here; they
# were lifted to `tests/conftest.py` as part of the R-4 e2e harness
# foundation. This file consumes them by name; the conftest fixture
# `reminder_scheduler` provides the previous `scheduler` parameter.


class TestRecurringReminderReArm:
    """Recurring reminders fire once, re-arm, then fire the next occurrence.

    Crosses the ``ReminderScheduler._fire`` boundary — direct test of
    the R-1 "fires once and silently misses the next occurrence"
    scenario. Each test drives the *advance clock → call ``_on_timer`` →
    assert signal → advance again → call ``_on_timer`` → assert second
    signal* loop, with the second-firing oracle computed from the RRULE
    spec rather than re-reading scheduler internals.
    """

    def test_daily_reminder_fires_today_and_tomorrow(
        self, reminder_scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """A ``FREQ=DAILY`` reminder fires both its first AND second occurrence.

        R-1a coverage for the daily cadence. The first firing is what
        the existing per-method unit test already pins for one-shots;
        the *second* firing is the gap this test closes. Without the
        post-fire ``self.reload()`` call at the end of ``_on_timer``,
        ``_next`` would stay pointed at the just-fired occurrence and
        the second (tomorrow) firing would never arrive.
        """
        start_at = clock() + timedelta(minutes=10)
        store.add(Reminder(name="daily", start_at=start_at, rrule_str="FREQ=DAILY"))
        reminder_scheduler.reload()

        received: list[tuple[str, datetime]] = []

        def _capture(name: str, event_at: datetime) -> None:
            received.append((name, event_at))

        reminder_scheduler.reminder_due.connect(_capture)

        clock.advance(601)
        reminder_scheduler._on_timer()
        assert received == [("daily", start_at)]

        clock.advance(24 * 60 * 60)
        reminder_scheduler._on_timer()
        # Oracle from RRULE spec: FREQ=DAILY ⇒ period = 1 day.
        assert received == [
            ("daily", start_at),
            ("daily", start_at + timedelta(days=1)),
        ]

    def test_weekly_reminder_fires_first_occurrence_after_cap_reentry(
        self, reminder_scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """A ``FREQ=WEEKLY;BYDAY=TU`` reminder past the 24h cap fires twice.

        Double-purpose test:

        - **R-1a**: re-arm after the first fire produces a second fire.
        - **R-1c**: the 24h ``QTimer.singleShot`` cap is exercised across
          the ``_fire`` boundary. ``start_at`` is 13 days after the
          conftest clock epoch (the chosen Tuesday is well past the
          24h cap), and after the first fire the next occurrence is
          ~7 days out — also past the cap.

        The cap re-entry assertion is explicit: the very first
        ``_on_timer()`` call (without advancing the clock) MUST re-arm
        without firing, because ``now < self._next.fire_at``. A
        regression that dropped the daily-wakeup branch in ``_on_timer``
        would fire prematurely here and the ``received == []`` assertion
        would fail loudly.
        """
        # 2026-06-02 is a Tuesday, 13 days after the conftest clock epoch
        # (2026-05-20 is a Wednesday). 13 days >> 24h cap.
        start_at = datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
        store.add(Reminder(name="weekly", start_at=start_at, rrule_str="FREQ=WEEKLY;BYDAY=TU"))
        reminder_scheduler.reload()

        received: list[tuple[str, datetime]] = []

        def _capture(name: str, event_at: datetime) -> None:
            received.append((name, event_at))

        reminder_scheduler.reminder_due.connect(_capture)

        reminder_scheduler._on_timer()
        assert received == []

        clock.advance((start_at - clock()).total_seconds() + 1)
        reminder_scheduler._on_timer()
        assert received == [("weekly", start_at)]

        clock.advance(7 * 24 * 60 * 60)
        reminder_scheduler._on_timer()
        # Oracle from RRULE spec: FREQ=WEEKLY ⇒ period = 7 days.
        assert received == [
            ("weekly", start_at),
            ("weekly", start_at + timedelta(days=7)),
        ]

    def test_monthly_reminder_fires_this_month_and_next(
        self, reminder_scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """A ``FREQ=MONTHLY;BYMONTHDAY=15`` reminder fires June 15 AND July 15.

        R-1a coverage for the monthly cadence. The oracle is derived
        directly from the RRULE spec (``BYMONTHDAY=15`` ⇒ the 15th of
        each month), NEVER from re-implementing the scheduler's
        ``dateutil.relativedelta`` arithmetic in the test body. A
        regression in month-arithmetic (e.g. dropping to "31 days
        later") would fail this test cleanly.
        """
        start_at = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
        store.add(
            Reminder(
                name="monthly",
                start_at=start_at,
                rrule_str="FREQ=MONTHLY;BYMONTHDAY=15",
            )
        )
        reminder_scheduler.reload()

        received: list[tuple[str, datetime]] = []

        def _capture(name: str, event_at: datetime) -> None:
            received.append((name, event_at))

        reminder_scheduler.reminder_due.connect(_capture)

        clock.advance((start_at - clock()).total_seconds() + 1)
        reminder_scheduler._on_timer()
        assert received == [("monthly", start_at)]

        second_at = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
        clock.advance((second_at - clock()).total_seconds() + 1)
        reminder_scheduler._on_timer()
        # Oracle from RRULE spec: BYMONTHDAY=15 ⇒ same day-of-month next month.
        assert received == [
            ("monthly", start_at),
            ("monthly", second_at),
        ]

    def test_recurring_with_lead_minutes_offsets_each_event_at(
        self, reminder_scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
    ) -> None:
        """S-06b ``event_at = fire_at + lead_minutes`` holds across both firings.

        The existing one-shot lead-minutes test pins the offset on the
        first firing only. This test extends the contract across two
        firings of a daily reminder. A regression that broke per-
        occurrence ``event_at`` re-derivation in the recurring re-arm
        path (e.g. accidentally pinning ``event_at`` to
        ``reminder.start_at`` rather than ``self._next.fire_at``) would
        miss the second-firing offset and fail this test.
        """
        start_at = clock() + timedelta(minutes=10)
        store.add(
            Reminder(
                name="daily-with-lead",
                start_at=start_at,
                rrule_str="FREQ=DAILY",
                lead_minutes=15,
            )
        )
        reminder_scheduler.reload()

        received: list[tuple[str, datetime]] = []

        def _capture(name: str, event_at: datetime) -> None:
            received.append((name, event_at))

        reminder_scheduler.reminder_due.connect(_capture)

        clock.advance(601)
        reminder_scheduler._on_timer()
        assert received == [("daily-with-lead", start_at + timedelta(minutes=15))]

        clock.advance(24 * 60 * 60)
        reminder_scheduler._on_timer()
        # Oracle: event_at offset is +15min on every firing, not just first.
        assert received == [
            ("daily-with-lead", start_at + timedelta(minutes=15)),
            ("daily-with-lead", start_at + timedelta(days=1, minutes=15)),
        ]
