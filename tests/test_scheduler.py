"""Unit tests for the FR-014 RRULE engine.

These tests deliberately avoid Qt: the recurrence rule is exercised via
the pure ``next_firing_after`` helper. The active-time counter (FR-008)
needs a Qt event loop to test meaningfully and is left for a follow-up
test pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from break_reminder.scheduler import next_firing_after
from break_reminder.storage.reminders import Reminder

UTC = UTC


def _reminder(start: datetime, rrule: str | None = None, end: datetime | None = None) -> Reminder:
    return Reminder(name="test", start_at=start, rrule_str=rrule, end_at=end)


class TestNextFiringAfter:
    """Cases for the pure ``next_firing_after`` helper (FR-014)."""

    def test_one_shot_in_future(self) -> None:
        """A one-shot reminder in the future returns its ``start_at``."""
        now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
        start = now + timedelta(hours=2)
        assert next_firing_after(_reminder(start), now) == start

    def test_one_shot_in_past_returns_none(self) -> None:
        """A one-shot reminder already past ``now`` is exhausted."""
        now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
        start = now - timedelta(hours=2)
        assert next_firing_after(_reminder(start), now) is None

    def test_daily_recurrence_finds_next_day(self) -> None:
        """A daily RRULE rolls forward to tomorrow's same-time firing."""
        start = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
        rule = "FREQ=DAILY"
        now = datetime(2026, 5, 19, 9, 30, tzinfo=UTC)  # past today's firing
        nxt = next_firing_after(_reminder(start, rule), now)
        assert nxt == datetime(2026, 5, 20, 9, 0, tzinfo=UTC)

    def test_weekly_recurrence_skips_to_next_match(self) -> None:
        """A weekly RRULE skips non-matching days and lands on the next match."""
        start = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)  # Tuesday
        rule = "FREQ=WEEKLY;BYDAY=TU"
        now = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)  # Wednesday
        nxt = next_firing_after(_reminder(start, rule), now)
        assert nxt == datetime(2026, 5, 26, 9, 0, tzinfo=UTC)

    def test_monthly_recurrence_handles_month_rollover(self) -> None:
        """A monthly RRULE rolls into the following month after the day passes."""
        start = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
        rule = "FREQ=MONTHLY;BYMONTHDAY=1"
        now = datetime(2026, 5, 15, 0, 0, tzinfo=UTC)
        nxt = next_firing_after(_reminder(start, rule), now)
        assert nxt == datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

    def test_end_at_truncates_recurrence(self) -> None:
        """An ``end_at`` past ``now`` ends the series; helper returns ``None``."""
        start = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
        rule = "FREQ=DAILY"
        end = datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
        now = datetime(2026, 5, 21, 0, 1, tzinfo=UTC)  # past end
        assert next_firing_after(_reminder(start, rule, end), now) is None

    def test_invalid_rrule_returns_none_not_raises(self) -> None:
        """A corrupt RRULE string degrades to ``None`` instead of crashing."""
        # Storage layer accepts any string; the scheduler must degrade gracefully.
        start = datetime(2026, 5, 19, 9, 0, tzinfo=UTC)
        now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
        assert next_firing_after(_reminder(start, "NOT_A_REAL_RRULE"), now) is None

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        """A naive ``start_at`` is interpreted as UTC, not local time."""
        start = datetime(2026, 5, 19, 9, 0)  # naive
        now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
        nxt = next_firing_after(_reminder(start), now)
        assert nxt == datetime(2026, 5, 19, 9, 0, tzinfo=UTC)


class TestDstDrift:
    """R-1b regression — daily Warsaw reminders must not drift across DST.

    Background (research.md R-1b + plan §1): when ``next_firing_after``
    passes a tz-aware UTC ``dtstart`` to ``dateutil.rrulestr``, RRULE's
    daily-cadence math operates in UTC fixed-offset land and inherits
    the UTC day-length (always 86_400 s). The user's intent — "9:00
    Warsaw daily" — is local-wall-clock-anchored; on the spring-forward
    Sunday (last Sunday of March in Europe/Warsaw) the local day is
    23h long, so a UTC-anchored next-day calculation lands at 10:00
    Warsaw (one hour late). The fix localizes ``dtstart`` and ``now``
    to ``reminder.tz`` before handing them to ``rrulestr``, so RRULE
    walks the IANA calendar and respects the DST jump.

    Worked oracle (derived from RRULE spec + the IANA Europe/Warsaw
    spring-forward rule, NOT from running the scheduler):

      start_at = 2026-03-28 08:00 UTC  = 9:00 Warsaw CET (UTC+1, pre-DST)
      now      = 2026-03-28 08:30 UTC  = just after the first firing
      expected = 2026-03-29 07:00 UTC  = 9:00 Warsaw CEST (UTC+2, post-DST)
      pre-fix  = 2026-03-29 08:00 UTC  = 10:00 Warsaw CEST (off by exactly the DST offset)

    The plan's original ``now = 2026-03-28 07:00 UTC`` value would
    return the first firing (03-28 08:00 UTC) under both code paths
    and never cross the DST boundary — an empirical check with the
    real dateutil rrule confirmed that the test needs ``now > start_at``
    to actually traverse spring-forward. The adaptation preserves the
    plan's expected return value and its R-1b intent; only the ``now``
    parameter was adjusted.
    """

    def test_dst_drift_does_not_occur_across_warsaw_spring_forward(self) -> None:
        """A daily 9:00 Warsaw reminder fires at 9:00 Warsaw post-DST, not 10:00."""
        reminder = Reminder(
            name="warsaw-daily",
            start_at=datetime(2026, 3, 28, 8, 0, tzinfo=UTC),
            rrule_str="FREQ=DAILY",
            tz="Europe/Warsaw",
        )
        now = datetime(2026, 3, 28, 8, 30, tzinfo=UTC)
        nxt = next_firing_after(reminder, now)
        assert nxt == datetime(2026, 3, 29, 7, 0, tzinfo=UTC)

    def test_daily_warsaw_reminder_no_drift_within_dst_window(self) -> None:
        """A daily 9:00 Warsaw reminder spaced 24h apart within CEST (no DST boundary).

        Counter-test to the spring-forward regression above. Mid-June
        2026 sits squarely inside CEST (DST window starts last Sunday
        of March, ends last Sunday of October), so two consecutive
        daily firings must be exactly 24 wall-clock hours apart =
        24 UTC hours apart. Oracle is the RRULE spec: each daily
        occurrence is one "calendar day" after the previous; with no
        DST boundary crossed, a calendar day == 86400 seconds.

        Guards against a future refactor that accidentally strips the
        ``astimezone(zone)`` calls — the spring-forward test alone
        could be satisfied by a wrong-but-coincidentally-right
        implementation, but the combination of (a) spring-forward
        correct AND (b) flat-window correct pins the localization
        contract more tightly.
        """
        reminder = Reminder(
            name="warsaw-summer",
            start_at=datetime(2026, 6, 15, 7, 0, tzinfo=UTC),  # 9:00 Warsaw CEST
            rrule_str="FREQ=DAILY",
            tz="Europe/Warsaw",
        )
        # First firing already fired at 07:00 UTC; ask for the next.
        now = datetime(2026, 6, 15, 7, 30, tzinfo=UTC)
        nxt = next_firing_after(reminder, now)
        assert nxt == datetime(2026, 6, 16, 7, 0, tzinfo=UTC)
        # And the one after that — pin two hops to lock in the cadence.
        assert nxt is not None
        nxt2 = next_firing_after(reminder, nxt)
        assert nxt2 is not None
        assert nxt2 - nxt == timedelta(hours=24)

    def test_utc_tz_is_identity_on_localization(self) -> None:
        """With ``tz="UTC"``, the localize-then-back-to-UTC round-trip is a no-op.

        Pins that the new code path doesn't introduce drift in the
        UTC-anchored case — the implementation routes through
        ``start.astimezone(ZoneInfo("UTC"))`` and ``nxt.astimezone(UTC)``,
        both of which must be identity transformations on tz-aware UTC
        datetimes. A future refactor that breaks the identity (e.g. by
        normalizing to a fixed offset that differs from ``UTC``) would
        trip here.
        """
        reminder = Reminder(
            name="utc-daily",
            start_at=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
            rrule_str="FREQ=DAILY",
            tz="UTC",
        )
        now = datetime(2026, 5, 19, 9, 30, tzinfo=UTC)
        nxt = next_firing_after(reminder, now)
        assert nxt == datetime(2026, 5, 20, 9, 0, tzinfo=UTC)


if __name__ == "__main__":
    pytest.main([__file__])
