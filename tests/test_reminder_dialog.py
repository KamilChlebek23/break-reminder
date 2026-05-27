"""Tests for ``ReminderDialog`` (FR-013 / S-06b).

The dialog itself is mostly a passive container — the load-bearing
piece is the body-text formatting. These tests pin:

- The pure ``_format_body`` helper across zones, day-of-week rollover,
  and zero-padding.
- The constructor wires ``event_at`` through to the body label.

We do not assert on the title label (the bold name) — that's a
trivial passthrough already exercised by S-06's manual smoke and not
worth re-pinning here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QLabel

from break_reminder.notifications.reminder_dialog import (
    _BODY_FORMAT,
    _BODY_TIME_FORMAT,
    ReminderDialog,
    _format_body,
)


class TestFormatBody:
    """Pure-function wording contract for the popup body."""

    def test_format_body_in_target_zone(self) -> None:
        """``tz`` shifts the rendered instant to the target zone.

        Mirrors the rationale in
        ``test_settings_dialog.TestRemindersHelpers.test_format_firing_with_tz_renders_in_target_zone``:
        on a UTC runner, ``<utc>.astimezone() == <utc>`` and a
        no-conversion implementation would still pass an
        implicit-default test. The explicit ``tz`` makes the
        conversion observable on every runner.
        """
        instant = datetime(2026, 6, 3, 22, 0, tzinfo=UTC)
        # -8 hours: 22:00 UTC → 14:00 Wed in the -8 zone.
        result = _format_body(instant, tz=timezone(timedelta(hours=-8)))
        assert result == "Time of event is Wed 14:00"

    def test_format_body_default_tz_matches_system_local(self) -> None:
        """``tz=None`` (the default) goes through ``.astimezone()`` with no arg.

        Pins the production behaviour without assuming what the runner's
        actual zone is — both sides go through the same conversion
        path, so the assertion holds on any host.
        """
        instant = datetime(2026, 6, 3, 22, 0, tzinfo=UTC)
        expected = _BODY_FORMAT.format(event=instant.astimezone().strftime(_BODY_TIME_FORMAT))
        assert _format_body(instant) == expected

    def test_format_body_zero_pads_minutes(self) -> None:
        """Single-digit minutes render as two-digit (``%M`` semantics)."""
        instant = datetime(2026, 6, 3, 14, 5, tzinfo=UTC)
        # Force UTC zone so the assertion is deterministic on any runner.
        result = _format_body(instant, tz=UTC)
        assert result == "Time of event is Wed 14:05"
        # Specifically NOT "14:5".
        assert "14:5" not in result.replace("14:05", "")

    def test_format_body_handles_day_rollover(self) -> None:
        """A 23:30 event the day before the popup fires correctly tags Wed.

        Validates the day-of-week tag earns its keep: with a 60-minute
        lead, a Wed-00:30 event would fire the popup at Tue-23:30.
        The body must read ``"Wed 00:30"`` so the user isn't confused.
        """
        # Event = Wed 2026-06-03 00:30 UTC; rendered in UTC for determinism.
        event = datetime(2026, 6, 3, 0, 30, tzinfo=UTC)
        assert _format_body(event, tz=UTC) == "Time of event is Wed 00:30"

    def test_format_body_uses_short_day_name(self) -> None:
        """The day-of-week is the 3-letter short form (``%a``), not full name."""
        # Pick a day per weekday slot so the assertion is unambiguous.
        instant = datetime(2026, 6, 1, 14, 30, tzinfo=UTC)  # Monday
        assert _format_body(instant, tz=UTC) == "Time of event is Mon 14:30"


class TestReminderDialogConstructor:
    """The constructor wires ``event_at`` through to the body label."""

    def test_dialog_window_title_is_reminder(self, qtbot) -> None:
        """The window title is the documented bare ``"Reminder"`` label."""
        d = ReminderDialog(
            name="anything",
            event_at=datetime(2026, 6, 3, 14, 30, tzinfo=UTC),
            tz=UTC,
        )
        qtbot.addWidget(d)
        assert d.windowTitle() == "Reminder"

    def test_dialog_carries_stays_on_top_hint(self, qtbot) -> None:
        """The popup is marked ``WindowStaysOnTopHint`` so it can't slip behind."""
        d = ReminderDialog(
            name="anything",
            event_at=datetime(2026, 6, 3, 14, 30, tzinfo=UTC),
            tz=UTC,
        )
        qtbot.addWidget(d)
        assert bool(d.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_body_label_renders_formatted_event_time(self, qtbot) -> None:
        """The body label text matches ``_format_body(event_at, tz=...)`` exactly.

        Walks the dialog's QLabel children and asserts that one of
        them carries the formatted body string. The reminder name
        label is checked separately so the test fails clearly when
        the body label specifically regresses.
        """
        event_at = datetime(2026, 6, 3, 22, 0, tzinfo=UTC)
        d = ReminderDialog(
            name="dentist",
            event_at=event_at,
            tz=timezone(timedelta(hours=-8)),  # -8 zone: 14:00 Wed
        )
        qtbot.addWidget(d)

        label_texts = {label.text() for label in d.findChildren(QLabel)}
        assert "Time of event is Wed 14:00" in label_texts
        # And the title (bold reminder name) is also present.
        assert "dentist" in label_texts
        # And the old hardcoded wording is gone for good.
        assert "This is a scheduled reminder." not in label_texts

    def test_dialog_has_ok_button(self, qtbot) -> None:
        """The dialog exposes a single OK button (no Cancel — FR-013)."""
        d = ReminderDialog(
            name="anything",
            event_at=datetime(2026, 6, 3, 14, 30, tzinfo=UTC),
            tz=UTC,
        )
        qtbot.addWidget(d)
        ok_buttons = d.findChildren(QDialogButtonBox)
        assert len(ok_buttons) == 1
        assert ok_buttons[0].button(QDialogButtonBox.StandardButton.Ok) is not None
        # And NOT a Cancel button (FR-013 popup has OK only).
        assert ok_buttons[0].button(QDialogButtonBox.StandardButton.Cancel) is None
