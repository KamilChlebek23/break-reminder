"""Add Reminder form dialog (FR-011 / S-06 / S-06b).

Modal sub-dialog launched from the Reminders tab's Add button. Collects a
name, future date/time, and a 0-60 minute lead time, validates all three,
persists a one-shot ``Reminder`` via the injected ``ReminderStore``, and
arms the running session via the injected ``ReminderScheduler``. Emits
``reminder_added`` on success so ``SettingsDialog`` can rebuild the
Reminders tab in place.

S-06b note: when ``lead_minutes > 0``, the datetime widget is the
**event time** and the saved ``start_at`` is ``event_at - lead_minutes``.
When ``lead_minutes == 0`` (the default), the form behaves identically
to S-06 (datetime widget IS the firing time). Storage Model A: lead is
round-trip metadata on ``Reminder`` and the scheduler still arms on
``start_at`` — no scheduler change was required.

Design notes for future Stream B slices:

- The form is **generic by name** so S-07's Edit dialog can reuse the
  same class with a pre-populated ``Reminder`` argument. The module is
  ``reminder_form_dialog`` (not ``add_reminder_dialog``) precisely so
  that reuse doesn't require a file rename or a sibling clone. S-07
  can reconstruct ``event_at`` from a loaded ``Reminder`` via
  ``start_at + timedelta(minutes=lead_minutes)``.
- The dialog reads ``self._clock()`` exactly once at construction to
  seed the date/time field's default value. The clock returns
  tz-aware UTC; the widget displays naive local. See ``__init__``'s
  default-seeding flow for the explicit UTC → local → +1h → round-up
  → strip-tzinfo conversion.
- ``accept()`` order is load-bearing: validate name → validate datetime
  (with lead-aware tooltip wording) → construct Reminder → store.add
  (with ``OSError`` gate) → scheduler.reload → emit ``reminder_added``
  → super().accept(). The emit-before-super-accept ordering matters
  because connected slots on ``reminder_added`` need to see the dialog
  as still-open (``result`` still ``Rejected``) — running them after
  ``exec()`` has returned is too late since the dialog may already be
  slated for destruction.
- Validation uses the same ``QToolTip.showText`` anchored-to-field
  pattern the ``SettingsDialog`` voice-phrase gate uses
  (``ui/settings_dialog.py`` ``accept()``). Do **not** introduce
  ``QMessageBox`` here — the codebase has no validation ``QMessageBox``
  precedents and the tooltip pattern is the established convention.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QDate, QDateTime, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from break_reminder.storage.reminders import Reminder, ReminderStore

if TYPE_CHECKING:
    from break_reminder.scheduler import ReminderScheduler

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Default clock — tz-aware UTC now. Mirrors ``scheduler._utcnow``."""
    return datetime.now(UTC)


# Default ``fire_at`` seed offset: one hour ahead of "now", rounded up
# to the next 15-minute boundary. The persona's archetypal use is "I
# want a reminder in about an hour" (FR-011 dentist example) — making
# that the one-click default trades a small amount of UI surprise for
# typical-path speed. Round-up to a quarter-hour keeps the displayed
# string tidy on the spinbox.
_DEFAULT_OFFSET_HOURS = 1
_DEFAULT_ROUND_MINUTES = 15

# ``QDateTimeEdit`` format string. Mirrors the ``_FIRING_FORMAT`` from
# ``settings_dialog`` (``"%a %Y-%m-%d %H:%M"``) but in Qt's format-spec
# syntax (``ddd`` = short day name; ``yyyy`` = 4-digit year; ``HH`` =
# 24-hour). Display consistency between the form input and the list
# view that lands the saved reminder is intentional — the user types
# in the same shape they see the row render.
_DATETIME_DISPLAY_FORMAT = "ddd yyyy-MM-dd HH:mm"

# Name field placeholder. The dentist example is verbatim from FR-011
# so the surface and the spec stay aligned.
_NAME_PLACEHOLDER = "e.g., Visit to dentist"

# S-06b lead-time spinbox bounds. 0-60 minutes, single-step 1, default
# 0. Suffix " min" displays inline so the unit is obvious without a
# secondary label. The 60-minute cap is deliberately conservative —
# "remind me 2h before my flight" is a separate future enhancement
# (see plan-brief.md § Scope, Out of scope).
_LEAD_MIN_VALUE = 0
_LEAD_MAX_VALUE = 60
_LEAD_DEFAULT = 0
_LEAD_SUFFIX = " min"

# Validation messages. Anchored on the failing field via
# ``QToolTip.showText`` and paired with an early ``return`` so the
# dialog stays open and nothing persists.
_NAME_EMPTY_MESSAGE = "Name cannot be empty"
# S-06b: with the spinbox always present, the datetime widget
# consistently means "event time" (lead=0 is the degenerate case where
# event time IS the firing time). The wording switches from "Time" to
# "Event" to match.
_PAST_TIME_MESSAGE = "Event must be in the future"
# S-06b: when ``lead_minutes > 0``, the past-time tooltip explains
# how-much-in-the-future is needed so the user can either push the
# event later or reduce the lead. ``{lead}`` is the current spinbox
# value at the time of the failed save; ``{unit}`` is computed by
# ``_format_past_time_with_lead`` so the singular ``lead == 1`` case
# reads "at least 1 minute" rather than "at least 1 minutes".
_PAST_TIME_WITH_LEAD_FORMAT = "Event must be at least {lead} {unit} in the future"
# ``{error}`` is filled with ``OSError.strerror`` (or ``str(error)``
# when ``strerror`` is empty) so the user sees the OS-level reason for
# the save failure (permission denied, disk full, etc.).
_SAVE_FAILED_FORMAT = "Could not save reminder: {error}"


def _qdatetime_from_naive_local(naive_local: datetime) -> QDateTime:
    """Build a ``QDateTime`` from a naive-local Python ``datetime``.

    The PySide6 stubs don't accept ``QDateTime(datetime)`` even though
    the runtime does. Splitting into ``QDate`` + ``QTime`` constructors
    sidesteps the stub gap without a ``type: ignore`` on every call site
    and produces an identical ``QDateTime`` value (no tz info, no
    millisecond precision — which is what the widget displays).

    Args:
        naive_local: A tz-naive datetime in the display zone (typically
            system local). Tz-aware inputs are silently coerced by
            dropping the tzinfo on the way through ``QDate`` / ``QTime``.

    Returns:
        A ``QDateTime`` ready for ``QDateTimeEdit.setDateTime``.
    """
    return QDateTime(
        QDate(naive_local.year, naive_local.month, naive_local.day),
        QTime(naive_local.hour, naive_local.minute, naive_local.second),
    )


def _format_past_time_with_lead(lead: int) -> str:
    """Render the past-time tooltip for a non-zero ``lead`` with correct plurality.

    Pure helper so the wording is observable from a test without spinning
    up the dialog. Mirrors the ``_format_body`` / ``_format_firing``
    pattern elsewhere in the codebase: keep the format constant simple,
    push the small conditional into a named helper so the call site
    stays a one-liner and ``lead == 1`` doesn't read "1 minutes".

    Args:
        lead: The current spinbox value at the time of the failed save.
            Expected to be ``>= 1`` (callers should use
            ``_PAST_TIME_MESSAGE`` for ``lead == 0``).

    Returns:
        The formatted tooltip string, e.g. ``"Event must be at least
        1 minute in the future"`` for ``lead=1`` or ``"... 15 minutes
        ..."`` for any other positive value.
    """
    unit = "minute" if lead == 1 else "minutes"
    return _PAST_TIME_WITH_LEAD_FORMAT.format(lead=lead, unit=unit)


def _round_up_to_minutes(local_dt: datetime, granularity_minutes: int) -> datetime:
    """Round ``local_dt`` up to the next multiple of ``granularity_minutes``.

    Returns the same instant when ``local_dt`` already sits exactly on a
    boundary AND has zero seconds/microseconds; otherwise rounds strictly
    forward. Strips seconds + microseconds either way so the widget's
    minute-resolution display matches the stored value.

    Args:
        local_dt: A naive or aware datetime expressed in the target
            display zone (typically system local). Tz-awareness is
            preserved.
        granularity_minutes: Bucket width in minutes (e.g. 15 for the
            quarter-hour default).

    Returns:
        The rounded datetime with ``second=0, microsecond=0``.
    """
    remainder = local_dt.minute % granularity_minutes
    needs_bump = remainder != 0 or local_dt.second != 0 or local_dt.microsecond != 0
    if needs_bump:
        bump = granularity_minutes - remainder
        bumped = local_dt + timedelta(minutes=bump)
        return bumped.replace(second=0, microsecond=0)
    return local_dt.replace(second=0, microsecond=0)


class ReminderFormDialog(QDialog):
    """Modal sub-dialog for adding a one-shot custom reminder (FR-011).

    Constructed by ``SettingsDialog._on_reminders_add_clicked`` with the
    app's injected ``ReminderStore`` and ``ReminderScheduler``. Emits
    ``reminder_added`` with the persisted ``Reminder`` on a successful
    save; the connected slot is responsible for refreshing the
    Reminders tab.

    The dialog deliberately uses ``QDialog.exec()`` (not ``show()``) so
    the caller blocks on the user's OK/Cancel choice — this is the
    first modal sub-dialog launched from inside another dialog in the
    codebase, establishing the convention S-07 will reuse for Edit.
    """

    # Emitted from ``accept()`` immediately BEFORE ``super().accept()``.
    # Connected slots run synchronously while the dialog is still "open"
    # (``result()`` still ``Rejected``); only after every slot has
    # returned does ``super().accept()`` flip the result and let
    # ``exec()`` return. The emit-before-super-accept order is pinned
    # by a unit test — see ``tests/test_reminder_form_dialog.py``
    # ``test_save_emits_reminder_added_before_super_accept``.
    reminder_added = Signal(Reminder)

    def __init__(
        self,
        *,
        store: ReminderStore,
        scheduler: ReminderScheduler,
        clock: Callable[[], datetime] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and seed the date/time field.

        Args:
            store: ``ReminderStore`` the form persists into on save.
                Required (no default) so tests must inject a tmp-path
                store and never touch ``%APPDATA%``.
            scheduler: ``ReminderScheduler`` whose ``reload()`` arms the
                running session against the freshly-saved reminder.
                Required for the same reason as ``store``.
            clock: Optional injectable clock for the default-value
                seeding. Returns tz-aware UTC. Defaults to the
                module-level ``_utcnow``. Tests inject a frozen clock
                so default-value assertions are stable regardless of
                wall-clock or CI-runner timezone.
            parent: Optional Qt parent. Typically the ``SettingsDialog``
                that opened this form so closing Settings disposes the
                sub-dialog cleanly.
        """
        super().__init__(parent)
        self._store = store
        self._scheduler = scheduler
        self._clock = clock or _utcnow

        self.setWindowTitle("Add Reminder")
        # Stays on top of the parent SettingsDialog. The popup is modal
        # via ``exec()``; ``WindowStaysOnTopHint`` ensures it doesn't
        # slide behind a focus-stealing window the OS pops up
        # concurrently.
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self._name_field = QLineEdit(self)
        self._name_field.setPlaceholderText(_NAME_PLACEHOLDER)

        self._datetime_field = QDateTimeEdit(self)
        self._datetime_field.setCalendarPopup(True)
        self._datetime_field.setDisplayFormat(_DATETIME_DISPLAY_FORMAT)
        self._datetime_field.setDateTime(self._compute_default_datetime())

        # S-06b lead-time spinbox. When ``value() > 0``, ``accept()``
        # treats the datetime widget as the event time and saves
        # ``start_at = event_at - timedelta(minutes=value())``.
        self._lead_minutes_field = QSpinBox(self)
        self._lead_minutes_field.setRange(_LEAD_MIN_VALUE, _LEAD_MAX_VALUE)
        self._lead_minutes_field.setSingleStep(1)
        self._lead_minutes_field.setSuffix(_LEAD_SUFFIX)
        self._lead_minutes_field.setValue(_LEAD_DEFAULT)

        form = QFormLayout()
        form.addRow("Name:", self._name_field)
        form.addRow("Date/time:", self._datetime_field)
        form.addRow("Notify (minutes before event):", self._lead_minutes_field)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

    def _compute_default_datetime(self) -> QDateTime:
        """Seed the date/time field to ``now + 1h`` rounded up to 15-min.

        ``self._clock()`` returns tz-aware UTC. ``QDateTimeEdit`` round-trips
        **naive local** datetimes. The seeding flow is therefore:

        1. ``self._clock()`` → tz-aware UTC
        2. ``.astimezone()`` → tz-aware system local (no arg = system zone)
        3. ``+ timedelta(hours=_DEFAULT_OFFSET_HOURS)`` → 1h ahead
        4. ``_round_up_to_minutes(..., _DEFAULT_ROUND_MINUTES)`` →
           snapped up to next quarter-hour boundary with zero seconds
        5. ``.replace(tzinfo=None)`` → naive local for the widget

        Returns:
            A ``QDateTime`` ready for ``QDateTimeEdit.setDateTime``.
        """
        utc_now = self._clock()
        local_now = utc_now.astimezone()
        local_plus_offset = local_now + timedelta(hours=_DEFAULT_OFFSET_HOURS)
        local_rounded = _round_up_to_minutes(local_plus_offset, _DEFAULT_ROUND_MINUTES)
        naive_local = local_rounded.replace(tzinfo=None)
        return _qdatetime_from_naive_local(naive_local)

    def _show_tooltip(self, widget: QWidget, message: str) -> None:
        """Anchor a ``QToolTip`` below ``widget`` with ``message`` (3s).

        Args:
            widget: Field the tooltip points at. ``widget.parentWidget()``
                or ``self`` are valid anchors; we always pass the field
                itself for visual continuity (same pattern as
                ``SettingsDialog._on_break_interval_edited``).
            message: Tooltip text shown to the user.
        """
        anchor = widget.mapToGlobal(widget.rect().bottomLeft())
        QToolTip.showText(anchor, message, widget, msecShowTime=3000)

    def accept(self) -> None:  # type: ignore[override]
        """Validate, persist, arm, emit, then close.

        Order is load-bearing:

        1. **Validate name.** Stripped name must be non-empty; first-fail
           tooltip + early return mirrors the voice-phrase gate.
        2. **Validate datetime.** The datetime widget is the **event
           time**; the firing time is ``event_at - lead_minutes``. We
           convert the user's naive-local wall clock to tz-aware UTC,
           subtract the lead, and require ``start_at > clock()``. The
           tooltip wording flips based on lead: zero-lead reads
           "Event must be in the future", non-zero-lead reads
           "Event must be at least N minutes in the future" (so the
           user can decide whether to push the event later or trim the
           lead).
        3. **Construct Reminder.** One-shot encoding: ``rrule_str=None``,
           ``end_at=None``, ``id`` auto-generated. ``start_at`` is the
           tz-aware UTC firing instant; ``lead_minutes`` is recorded as
           round-trip metadata so S-07's Edit dialog can reconstruct
           the event time as ``start_at + timedelta(lead_minutes)``.
        4. **Persist.** ``store.add()`` is atomic; the only error we
           guard is ``OSError`` (permission denied / disk full). On
           failure: tooltip anchored to OK button, early return, no
           scheduler reload, no signal emit, no super().accept().
        5. **Arm.** ``scheduler.reload()`` recomputes the next firing
           and rearms the single-shot timer. The roadmap flags this
           call as the S-06 risk surface — without it, the reminder
           sits on disk but never fires in the running session.
        6. **Emit.** ``self.reminder_added.emit(reminder)`` runs
           connected slots synchronously. They see ``self.result() ==
           Rejected`` because ``super().accept()`` hasn't fired yet.
        7. **Close.** ``super().accept()`` flips ``result`` to
           ``Accepted`` and ``exec()`` returns.
        """
        # 1. Name validation
        stripped_name = self._name_field.text().strip()
        if not stripped_name:
            self._show_tooltip(self._name_field, _NAME_EMPTY_MESSAGE)
            return

        # 2. Datetime validation (compare in UTC; widget gives naive local)
        # ``.toPython()`` returns a Python ``datetime`` at runtime but
        # the PySide6 stubs type it as ``object``. Use ``typing.cast``
        # for static narrowing — the runtime contract is documented by
        # PySide6 and an ``assert isinstance`` here would be stripped
        # under ``python -O`` while adding zero value at runtime
        # (retrospective impl-review F5).
        naive_local = cast(datetime, self._datetime_field.dateTime().toPython())
        # ``datetime.now().astimezone().tzinfo`` captures the system
        # local zone as a ``tzinfo`` object. Attaching it via
        # ``.replace`` makes the previously-naive value aware in the
        # user's local zone; ``.astimezone(UTC)`` then converts.
        local_tz = datetime.now().astimezone().tzinfo
        event_at_utc = naive_local.replace(tzinfo=local_tz).astimezone(UTC)
        lead_minutes = self._lead_minutes_field.value()
        start_at_utc = event_at_utc - timedelta(minutes=lead_minutes)
        if start_at_utc <= self._clock():
            message = (
                _format_past_time_with_lead(lead_minutes)
                if lead_minutes > 0
                else _PAST_TIME_MESSAGE
            )
            self._show_tooltip(self._datetime_field, message)
            return

        # 3. Construct one-shot reminder
        reminder = Reminder(
            name=stripped_name,
            start_at=start_at_utc,
            lead_minutes=lead_minutes,
        )

        # 4. Persist (atomic; only OSError needs guarding)
        try:
            self._store.add(reminder)
        except OSError as exc:
            logger.exception("ReminderStore.add failed")
            ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
            anchor_widget = ok_button if ok_button is not None else self._datetime_field
            self._show_tooltip(
                anchor_widget,
                _SAVE_FAILED_FORMAT.format(error=exc.strerror or str(exc)),
            )
            return

        # 5. Arm the running session
        self._scheduler.reload()

        # 6. Emit BEFORE super().accept() so connected slots see the
        #    dialog as still-open (result == Rejected). Pinned by test
        #    ``test_save_emits_reminder_added_before_super_accept``.
        self.reminder_added.emit(reminder)

        # 7. Close
        super().accept()
