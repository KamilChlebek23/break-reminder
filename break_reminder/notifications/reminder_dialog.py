"""Custom-reminder popup (FR-013) — deliberately dismissable.

FR-013 splits notification severity by event type: break notifications use
the FR-009 non-dismissable design (the wedge); custom reminders use a
normal popup that respects every standard dismiss gesture. **Do not** copy
the ``break_dialog`` overrides over here — that would defeat the split.

Voice playback (if globally enabled) is fired-and-forgotten just before
the dialog is shown; the dialog itself doesn't manage the voice
lifecycle because dismissal is unconstrained.

S-06b: the body text shows the event time so the user knows what the
popup is about without having to recall the lead-time they configured.
The format is ``"Time of event is <ddd HH:mm>"`` (e.g., ``"Time of
event is Wed 14:30"``) — short day-of-week disambiguates the
day-rollover case where a 60-minute lead pushes a 00:30-tomorrow event
into a 23:30-today popup. Conversion to local zone is done at format
time; the caller supplies a tz-aware UTC ``event_at`` and an optional
``tz`` override (tests inject an explicit offset so the conversion is
observable on any CI runner).
"""

from __future__ import annotations

from datetime import datetime, tzinfo

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

# Body-text format. Matches the user-facing wording chosen in S-06b's
# scope expansion. ``%a`` = short day name (Mon, Tue, ...) and ``%H:%M``
# = 24-hour HH:mm. Date is implicitly today-or-near-today since the
# popup only fires within the lead window (0-60 min in S-06b; future
# slices may extend), so the day-of-week tag is enough to cover the
# midnight-rollover case without bloating the line.
_BODY_TIME_FORMAT = "%a %H:%M"
_BODY_FORMAT = "Time of event is {event}"


def _format_body(event_at: datetime, *, tz: tzinfo | None = None) -> str:
    """Render the popup body text from a tz-aware UTC ``event_at``.

    Pure helper so the wording is observable from a test without
    instantiating ``QApplication``. The ``tz`` injection mirrors the
    same pattern as ``settings_dialog._format_firing`` — without it,
    a UTC CI runner cannot distinguish a correct local-zone conversion
    from a buggy implementation that skipped ``.astimezone()`` entirely.

    Args:
        event_at: The event instant as a tz-aware ``datetime``. For
            reminders with ``lead_minutes > 0`` this is the event time
            (not the firing time); for ``lead_minutes == 0`` it's the
            firing instant (which equals the event time by definition).
        tz: Optional target timezone. ``None`` (the default) means
            ``.astimezone()`` with no argument, which resolves to the
            system local zone — production behaviour.

    Returns:
        The full body string, e.g. ``"Time of event is Wed 14:30"``.
    """
    local = event_at.astimezone(tz)
    return _BODY_FORMAT.format(event=local.strftime(_BODY_TIME_FORMAT))


class ReminderDialog(QDialog):
    """Lightweight dismissable popup for custom reminders (FR-013)."""

    def __init__(
        self,
        *,
        name: str,
        event_at: datetime,
        tz: tzinfo | None = None,
        parent=None,
    ) -> None:
        """Build the reminder popup.

        Args:
            name: Reminder name shown in the popup title row.
            event_at: The event instant (tz-aware UTC). For
                ``lead_minutes > 0`` this is the user-picked event
                time; for ``lead_minutes == 0`` it's the firing
                instant. Used to render the body line "Time of event
                is <ddd HH:mm>".
            tz: Optional target timezone for the body's time formatting.
                ``None`` (the default) renders in system local zone —
                production behaviour. Tests pass an explicit zone so
                the conversion is observable regardless of runner zone.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self.setWindowTitle("Reminder")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(name)
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        body = QLabel(_format_body(event_at, tz=tz))
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
