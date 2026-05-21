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


if __name__ == "__main__":
    pytest.main([__file__])
