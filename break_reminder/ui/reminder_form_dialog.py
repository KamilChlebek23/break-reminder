"""Add / Edit Reminder form dialog (FR-011 / FR-012 / S-06 / S-06b / S-07).

Modal sub-dialog launched from the Reminders tab's Add / Edit buttons.
Collects a name, future date/time, and a 0-60 minute lead time, validates
all three, persists a one-shot ``Reminder`` via the injected
``ReminderStore``, and arms the running session via the injected
``ReminderScheduler``. Emits ``reminder_added`` (Add mode) or
``reminder_updated`` (Edit mode) on success so ``SettingsDialog`` can
rebuild the Reminders tab in place.

S-06b note: when ``lead_minutes > 0``, the datetime widget is the
**event time** and the saved ``start_at`` is ``event_at - lead_minutes``.
When ``lead_minutes == 0`` (the default), the form behaves identically
to S-06 (datetime widget IS the firing time). Storage Model A: lead is
round-trip metadata on ``Reminder`` and the scheduler still arms on
``start_at`` — no scheduler change was required.

S-07 dual-mode design:

- The constructor takes an optional ``reminder: Reminder | None = None``
  parameter. When ``None`` (the default), the dialog is in **Add mode**
  — fields seed from defaults, title reads "Add Reminder", save calls
  ``store.add()``, and ``reminder_added`` fires. When a ``Reminder`` is
  provided, the dialog is in **Edit mode** — fields pre-fill from it,
  title reads "Edit Reminder", save calls ``store.update()`` preserving
  the loaded ``id``, and ``reminder_updated`` fires. Both flows route
  through the same ``accept()``; the mode is checked at the four points
  that diverge (title, pre-fill, save path, signal).
- The past-time gate has an **Edit-mode skip**: when the user hasn't
  moved the firing time (``start_at_utc == self._editing.start_at``),
  the gate is bypassed so renaming or re-leading an already-expired
  reminder doesn't require also rescheduling it. Both halves are pinned
  by ``tests/test_reminder_form_dialog.py``:
  ``test_edit_mode_unchanged_firing_time_skips_past_time_gate`` (skip
  path) and ``test_edit_mode_changed_datetime_to_past_blocks_save`` /
  ``test_edit_mode_changed_lead_into_past_blocks_save`` (apply path).

Design notes:

- The form is **generic by name** so the Edit dialog reuses the same
  class with a pre-populated ``Reminder`` argument (the module is
  ``reminder_form_dialog`` — not ``add_reminder_dialog`` — precisely
  so that reuse doesn't require a file rename or a sibling clone).
  S-07 cashes this contract in. Edit mode reconstructs the event time
  for the widget as ``start_at + timedelta(minutes=lead_minutes)``.
- The dialog reads ``self._clock()`` exactly once at construction to
  seed the date/time field's default value (Add mode only — Edit mode
  uses the loaded ``Reminder``'s event time instead). The clock returns
  tz-aware UTC; the widget displays naive local. See
  ``_compute_default_datetime`` for the explicit UTC → local → +1h →
  round-up → strip-tzinfo conversion.
- ``accept()`` order is load-bearing: validate name → validate datetime
  (with lead-aware tooltip wording and Edit-mode skip) → construct
  Reminder (preserving the loaded ``id`` in Edit mode) → ``store.add()``
  or ``store.update()`` (with ``OSError`` gate) → scheduler.reload →
  emit ``reminder_added`` or ``reminder_updated`` → super().accept().
  The emit-before-super-accept ordering matters because connected slots
  need to see the dialog as still-open (``result`` still ``Rejected``)
  — running them after ``exec()`` has returned is too late since the
  dialog may already be slated for destruction.
- Validation uses the same ``QToolTip.showText`` anchored-to-field
  pattern the ``SettingsDialog`` voice-phrase gate uses
  (``ui/settings_dialog.py`` ``accept()``). Do **not** introduce
  ``QMessageBox`` here — the codebase has no validation ``QMessageBox``
  precedents and the tooltip pattern is the established convention.
  ``QMessageBox`` IS used by the Delete confirm (one level up in
  ``SettingsDialog._on_reminders_delete_clicked``); that's a
  **confirmation** for a destructive action, not validation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfoNotFoundError

import tzlocal
from PySide6.QtCore import QDate, QDateTime, Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from break_reminder.scheduler import next_firing_after
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

# S-08 / FR-014: recurrence picker labels. Four standard items are
# always present in the QComboBox; ``_RECURRENCE_CUSTOM_LABEL`` is
# added conditionally in Edit mode when the loaded ``rrule_str``
# doesn't reverse-translate to one of the four canonical strings
# (e.g. a hand-edited ``"FREQ=WEEKLY;BYDAY=MO,WE,FR"``). The custom
# item is never user-selectable — its presence implies the picker is
# disabled and the loaded rule is preserved verbatim on save unless
# the user clicks Reset and confirms.
_RECURRENCE_NONE_LABEL = "None"
_RECURRENCE_DAILY_LABEL = "Daily"
_RECURRENCE_WEEKLY_LABEL = "Weekly"
_RECURRENCE_MONTHLY_LABEL = "Monthly"
_RECURRENCE_CUSTOM_LABEL = "(custom)"

# S-08: canonical RRULE strings the picker emits on save. These are
# the byte-stable values ``_rrule_to_picker_choice`` exact-matches
# against on Edit pre-fill. Do NOT add normalization (uppercasing,
# whitespace stripping, etc.) — the storage layer round-trips the
# string verbatim and any normalization would diverge from
# hand-edited inputs that fall through to the (custom) catch-all.
_RRULE_DAILY = "FREQ=DAILY"
_RRULE_WEEKLY = "FREQ=WEEKLY"
_RRULE_MONTHLY = "FREQ=MONTHLY"

# S-08: forward-translation map (picker label → RRULE string or None).
# ``_RECURRENCE_NONE_LABEL`` maps to ``None`` so callers can lookup
# unconditionally without a separate is-recurring branch.
# ``_RECURRENCE_CUSTOM_LABEL`` is intentionally absent — the
# custom-locked branch in ``accept()`` reads ``self._original_custom_rrule``
# instead of consulting this map.
_PICKER_TO_RRULE: dict[str, str | None] = {
    _RECURRENCE_NONE_LABEL: None,
    _RECURRENCE_DAILY_LABEL: _RRULE_DAILY,
    _RECURRENCE_WEEKLY_LABEL: _RRULE_WEEKLY,
    _RECURRENCE_MONTHLY_LABEL: _RRULE_MONTHLY,
}

# S-08: end-date row defaults. ``setCalendarPopup(True)`` + a
# 30-day-out default pre-fill keeps the field useful without
# requiring the user to scroll the calendar (matches the +1h-rounded
# datetime default convention from S-06).
_END_DATE_CHECKBOX_LABEL = "End on:"
_END_DATE_DEFAULT_OFFSET_DAYS = 30

# S-08: tooltips + confirmation strings. ``_RECURRENCE_CUSTOM_TOOLTIP``
# surfaces on hover when the picker is locked into ``(custom)`` so
# the user understands why the dropdown is disabled. The Reset
# confirmation borrows the destructive-action wording convention
# (Yes/No, default No) used by the Reminders tab's Delete confirm
# in ``settings_dialog.py``.
_RECURRENCE_CUSTOM_TOOLTIP = "This reminder uses an advanced rule. Click Reset to replace it."
_RECURRENCE_RESET_BUTTON_LABEL = "Reset…"
_RECURRENCE_RESET_CONFIRM_TITLE = "Replace recurrence rule"
_RECURRENCE_RESET_CONFIRM_TEXT = (
    "Replace the custom recurrence rule with one of the standard options?\nThis cannot be undone."
)

# S-08: passive tooltip surfaced on the recurrence picker when the
# user composes a Monthly + day>28 combination. ``dateutil``'s
# plain ``FREQ=MONTHLY`` skips months without that day-of-month
# (Feb / Apr / Jun / Sep / Nov for day-31). The tooltip is
# informational, not a gate — the save still succeeds.
_MONTHLY_DAY31_TOOLTIP = "Months without that day are skipped (e.g. February)"

# S-08: validation message for the recurring-branch past-time gate.
# The recurring gate doesn't reject "start_at in the past"; it
# rejects "no future occurrences exist" (e.g. ``end_at`` is in the
# past, or the rule itself produces nothing after ``now``). Wording
# diverges from ``_PAST_TIME_MESSAGE`` so the user sees a
# rule-specific hint rather than a misleading "event must be in the
# future" message — for a recurring reminder the event is the next
# firing, not the start_at, and the failure mode is rule-level.
_NO_FUTURE_OCCURRENCES_MESSAGE = "Recurring reminder has no future firings"
_NO_FUTURE_OCCURRENCES_WITH_LEAD_FORMAT = (
    "Recurring reminder has no future firings at least {lead} {unit} away"
)


def _picker_choice_to_rrule(choice: str) -> str | None:
    """Translate a picker label to the canonical RRULE string (or ``None``).

    Forward translation — used by ``ReminderFormDialog.accept`` when
    the user clicks OK. The custom-locked path bypasses this helper
    and writes back ``self._original_custom_rrule`` directly, so this
    function never receives ``_RECURRENCE_CUSTOM_LABEL`` and treats
    it as an unknown choice.

    Args:
        choice: One of ``_RECURRENCE_NONE_LABEL`` /
            ``_RECURRENCE_DAILY_LABEL`` / ``_RECURRENCE_WEEKLY_LABEL``
            / ``_RECURRENCE_MONTHLY_LABEL``. Other inputs raise
            ``KeyError`` — this is intentional: the custom-locked
            branch is the only legitimate reason to encounter an
            unmapped value, and the caller routes around this helper
            in that case.

    Returns:
        ``None`` for ``_RECURRENCE_NONE_LABEL``; one of the three
        canonical RRULE strings (``"FREQ=DAILY"`` / ``"FREQ=WEEKLY"``
        / ``"FREQ=MONTHLY"``) otherwise.

    Raises:
        KeyError: When ``choice`` is not in the standard four labels.
    """
    return _PICKER_TO_RRULE[choice]


def _rrule_to_picker_choice(rrule_str: str | None) -> str:
    """Translate an RRULE string to a picker label (catch-all → custom).

    Reverse translation — used by ``ReminderFormDialog.__init__`` in
    Edit mode to seed the picker from the loaded reminder. Exact
    string matching is deliberate: a semantically-equivalent variant
    like ``"FREQ=DAILY;INTERVAL=1"`` falls through to the catch-all
    so the user sees the dialog locked into ``(custom)`` and the
    rule is preserved verbatim on no-op save. This honors FR-015's
    hand-edit invariant — we never silently rewrite the user's rule.

    Args:
        rrule_str: The reminder's stored ``rrule_str`` (verbatim).
            ``None`` means one-shot; an empty / whitespace-only /
            otherwise unmapped non-None value falls through to the
            ``(custom)`` label.

    Returns:
        ``_RECURRENCE_NONE_LABEL`` for ``None``; one of the three
        canonical labels for the matching RRULE string;
        ``_RECURRENCE_CUSTOM_LABEL`` for anything else.
    """
    if rrule_str is None:
        return _RECURRENCE_NONE_LABEL
    if rrule_str == _RRULE_DAILY:
        return _RECURRENCE_DAILY_LABEL
    if rrule_str == _RRULE_WEEKLY:
        return _RECURRENCE_WEEKLY_LABEL
    if rrule_str == _RRULE_MONTHLY:
        return _RECURRENCE_MONTHLY_LABEL
    return _RECURRENCE_CUSTOM_LABEL


def _local_date_to_utc_end_of_day(picked: date) -> datetime:
    """Compose ``picked`` + ``23:59:59`` in system-local zone, return tz-aware UTC.

    The end-date QDateEdit returns a naive Python ``date`` (no time,
    no timezone). The user's mental model is "the series ends on
    <picked date>" — i.e. it should still fire on that date but not
    after. Composing with ``time(23, 59, 59)`` in the system-local
    zone honors that mental model; converting to UTC produces the
    tz-aware value the storage layer expects.

    Mirrors the form's existing local→UTC dance for the datetime
    field (``naive_local.astimezone(UTC)`` in ``accept()``); the
    same DST-correctness rationale applies — Python's ``astimezone``
    on a naive datetime interprets it as local-zone for **that**
    wall-clock value, so DST-spanning end-dates land on the right
    UTC instant.

    Args:
        picked: The naive ``datetime.date`` from
            ``QDateEdit.date().toPython()``.

    Returns:
        A tz-aware UTC ``datetime`` representing 23:59:59 local on
        the picked date.
    """
    naive_local = datetime.combine(picked, time(23, 59, 59))
    return naive_local.astimezone(UTC)


def _format_no_future_occurrences_with_lead(lead: int) -> str:
    """Render the no-future-occurrences tooltip with correct minute plurality.

    Mirrors ``_format_past_time_with_lead``. Pure helper so the wording
    is observable from a test without spinning up the dialog;
    ``lead == 1`` reads "1 minute" rather than "1 minutes".

    Args:
        lead: The current spinbox value at the time of the failed
            save. Expected to be ``>= 1`` (callers should use
            ``_NO_FUTURE_OCCURRENCES_MESSAGE`` for ``lead == 0``).

    Returns:
        The formatted tooltip string.
    """
    unit = "minute" if lead == 1 else "minutes"
    return _NO_FUTURE_OCCURRENCES_WITH_LEAD_FORMAT.format(lead=lead, unit=unit)


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
    """Modal sub-dialog for adding or editing a one-shot custom reminder.

    Constructed by ``SettingsDialog._on_reminders_add_clicked`` (Add
    mode) or ``SettingsDialog._on_reminders_edit_clicked`` (Edit mode)
    with the app's injected ``ReminderStore`` and ``ReminderScheduler``.
    Emits ``reminder_added`` (Add) or ``reminder_updated`` (Edit) with
    the persisted ``Reminder`` on a successful save; the connected slot
    is responsible for refreshing the Reminders tab.

    Mode is determined by the optional ``reminder`` constructor
    parameter: ``None`` → Add mode (fresh entry, auto-generated ``id``),
    a ``Reminder`` → Edit mode (pre-filled, save preserves the loaded
    ``id``).

    The dialog deliberately uses ``QDialog.exec()`` (not ``show()``) so
    the caller blocks on the user's OK/Cancel choice — this is the
    first modal sub-dialog launched from inside another dialog in the
    codebase, established by S-06 and extended by S-07.
    """

    # Emitted from ``accept()`` immediately BEFORE ``super().accept()``
    # in **Add mode** (``self._editing is None``). Connected slots run
    # synchronously while the dialog is still "open" (``result()`` still
    # ``Rejected``); only after every slot has returned does
    # ``super().accept()`` flip the result and let ``exec()`` return.
    # The emit-before-super-accept order is pinned by a unit test —
    # see ``tests/test_reminder_form_dialog.py``
    # ``test_save_emits_reminder_added_before_super_accept``.
    reminder_added = Signal(Reminder)

    # Emitted from ``accept()`` immediately BEFORE ``super().accept()``
    # in **Edit mode** (``self._editing is not None``). Mirrors
    # ``reminder_added`` in shape and ordering; pinned by
    # ``test_edit_mode_save_emits_reminder_updated`` and
    # ``test_edit_mode_emit_before_super_accept_ordering``. Kept as a
    # **separate** signal (rather than overloading ``reminder_added``)
    # so the existing Add-mode test surface stays bit-for-bit valid
    # and the signal name documents which mode ran — useful for any
    # future event-log integration.
    reminder_updated = Signal(Reminder)

    def __init__(
        self,
        *,
        store: ReminderStore,
        scheduler: ReminderScheduler,
        clock: Callable[[], datetime] | None = None,
        reminder: Reminder | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and either seed defaults (Add) or pre-fill (Edit).

        Args:
            store: ``ReminderStore`` the form persists into on save.
                Required (no default) so tests must inject a tmp-path
                store and never touch ``%APPDATA%``.
            scheduler: ``ReminderScheduler`` whose ``reload()`` arms the
                running session against the freshly-saved reminder.
                Required for the same reason as ``store``.
            clock: Optional injectable clock for the default-value
                seeding (Add mode) and the past-time gate (both modes).
                Returns tz-aware UTC. Defaults to the module-level
                ``_utcnow``. Tests inject a frozen clock so default-value
                assertions are stable regardless of wall-clock or
                CI-runner timezone.
            reminder: Optional existing reminder to load. ``None``
                (default) means **Add mode** — fields seed from
                defaults, save calls ``store.add()``, emits
                ``reminder_added``, title reads "Add Reminder". A
                ``Reminder`` instance means **Edit mode** — fields
                pre-fill from it, save calls ``store.update()``
                preserving the loaded ``id``, emits ``reminder_updated``,
                title reads "Edit Reminder".
            parent: Optional Qt parent. Typically the ``SettingsDialog``
                that opened this form so closing Settings disposes the
                sub-dialog cleanly.
        """
        super().__init__(parent)
        self._store = store
        self._scheduler = scheduler
        self._clock = clock or _utcnow
        # ``self._editing`` is the single source of truth for "which
        # mode are we in?" — checked at the four divergence points
        # (title, pre-fill, save path, signal). The stored Reminder
        # also carries the ``id`` we must preserve on update.
        self._editing: Reminder | None = reminder

        self.setWindowTitle("Edit Reminder" if self._editing is not None else "Add Reminder")
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

        # S-06b lead-time spinbox. When ``value() > 0``, ``accept()``
        # treats the datetime widget as the event time and saves
        # ``start_at = event_at - timedelta(minutes=value())``.
        self._lead_minutes_field = QSpinBox(self)
        self._lead_minutes_field.setRange(_LEAD_MIN_VALUE, _LEAD_MAX_VALUE)
        self._lead_minutes_field.setSingleStep(1)
        self._lead_minutes_field.setSuffix(_LEAD_SUFFIX)

        # S-08 / FR-014: recurrence picker + Reset button. The picker
        # carries the four standard items by default; the (custom)
        # item is added conditionally below in the Edit-mode branch
        # when the loaded ``rrule_str`` doesn't reverse-translate.
        # The Reset button hides on default and only surfaces in the
        # custom-locked state.
        self._recurrence_picker = QComboBox(self)
        self._recurrence_picker.addItems(
            [
                _RECURRENCE_NONE_LABEL,
                _RECURRENCE_DAILY_LABEL,
                _RECURRENCE_WEEKLY_LABEL,
                _RECURRENCE_MONTHLY_LABEL,
            ]
        )
        self._recurrence_reset_button = QPushButton(_RECURRENCE_RESET_BUTTON_LABEL, self)
        self._recurrence_reset_button.setVisible(False)
        # Holds the verbatim ``rrule_str`` of a custom-locked Edit
        # load. ``None`` outside the locked state. ``accept()`` reads
        # this to preserve the rule on no-op save; ``_on_recurrence_reset_clicked``
        # clears it on Yes confirm so subsequent saves translate from
        # the picker instead.
        self._original_custom_rrule: str | None = None

        # S-08 / FR-014: end-date row. The QDateEdit is disabled by
        # default and follows the checkbox's toggled state. The
        # checkbox itself is disabled while the picker is None
        # (one-shot reminders have no series end). Default-pre-fill
        # is today + 30 days in system local zone — keeps the field
        # useful without forcing the user to scroll the calendar.
        self._end_date_checkbox = QCheckBox(_END_DATE_CHECKBOX_LABEL, self)
        self._end_date_field = QDateEdit(self)
        self._end_date_field.setCalendarPopup(True)
        self._end_date_field.setDisplayFormat("yyyy-MM-dd")
        default_end_local = (
            self._clock().astimezone() + timedelta(days=_END_DATE_DEFAULT_OFFSET_DAYS)
        ).date()
        self._end_date_field.setDate(
            QDate(default_end_local.year, default_end_local.month, default_end_local.day)
        )
        self._end_date_field.setEnabled(False)
        self._end_date_checkbox.setEnabled(False)

        if self._editing is not None:
            # Edit mode: pre-fill from the loaded reminder. The
            # datetime widget shows the **event time** (firing instant
            # + lead), matching the user's mental model — same
            # convention the Reminders list uses in ``_compose_row``.
            # The UTC → local → naive conversion is the inverse of
            # the save path's local → UTC dance; ``.astimezone()`` on
            # a tz-aware value is well-defined across Python versions
            # so the one-liner is safe.
            self._name_field.setText(self._editing.name)
            self._lead_minutes_field.setValue(self._editing.lead_minutes)
            event_at_utc = self._editing.start_at + timedelta(minutes=self._editing.lead_minutes)
            naive_local = event_at_utc.astimezone().replace(tzinfo=None)
            self._datetime_field.setDateTime(_qdatetime_from_naive_local(naive_local))

            # S-08: pre-fill recurrence + end-date from the loaded
            # reminder. Custom-locked branch (unparseable rrule_str)
            # adds the (custom) item, locks the picker, surfaces the
            # Reset button, and stashes the original rule so save
            # round-trips it byte-for-byte.
            picker_choice = _rrule_to_picker_choice(self._editing.rrule_str)
            if picker_choice == _RECURRENCE_CUSTOM_LABEL:
                self._original_custom_rrule = self._editing.rrule_str
                self._recurrence_picker.addItem(_RECURRENCE_CUSTOM_LABEL)
                self._recurrence_picker.setCurrentText(_RECURRENCE_CUSTOM_LABEL)
                self._recurrence_picker.setEnabled(False)
                self._recurrence_picker.setToolTip(_RECURRENCE_CUSTOM_TOOLTIP)
                self._recurrence_reset_button.setVisible(True)
            else:
                self._recurrence_picker.setCurrentText(picker_choice)

            # End-date pre-fill: tz-aware UTC → system local → naive
            # date. The checkbox+field cascade is reasserted by the
            # initial ``_on_recurrence_changed`` call at the bottom
            # of ``__init__``; for custom-locked + recurring the
            # cascade leaves these set; for None (one-shot) the
            # cascade unticks them — which matches reality because
            # ``_rrule_to_picker_choice(None) == _RECURRENCE_NONE_LABEL``
            # implies ``end_at`` should also be None (round-trip
            # invariant — a one-shot has no series end).
            if self._editing.end_at is not None:
                local_date = self._editing.end_at.astimezone().date()
                self._end_date_checkbox.setChecked(True)
                self._end_date_field.setEnabled(True)
                self._end_date_field.setDate(
                    QDate(local_date.year, local_date.month, local_date.day)
                )
        else:
            # Add mode: defaults (empty name, +1h-rounded datetime,
            # lead=0, recurrence None, end-date unticked).
            self._datetime_field.setDateTime(self._compute_default_datetime())
            self._lead_minutes_field.setValue(_LEAD_DEFAULT)

        form = QFormLayout()
        form.addRow("Name:", self._name_field)
        form.addRow("Date/time:", self._datetime_field)
        form.addRow("Notify (minutes before event):", self._lead_minutes_field)

        # S-08: recurrence row — picker + Reset button side-by-side.
        # The Reset button takes zero width when hidden (Qt's default
        # for ``setVisible(False)`` widgets in a layout), so the
        # row reads as "Recurrence: [picker]" in the common case.
        recurrence_row = QHBoxLayout()
        recurrence_row.setContentsMargins(0, 0, 0, 0)
        recurrence_row.addWidget(self._recurrence_picker)
        recurrence_row.addWidget(self._recurrence_reset_button)
        recurrence_row.addStretch(1)
        form.addRow("Recurrence:", recurrence_row)

        # S-08: end-date row — checkbox + field side-by-side. The
        # form-row label is empty because the checkbox carries its
        # own "End on:" label inline.
        end_date_row = QHBoxLayout()
        end_date_row.setContentsMargins(0, 0, 0, 0)
        end_date_row.addWidget(self._end_date_checkbox)
        end_date_row.addWidget(self._end_date_field)
        end_date_row.addStretch(1)
        form.addRow("", end_date_row)

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

        # S-08: signal wiring. The picker drives the cascade slot;
        # the checkbox drives the date field's enabled state; the
        # datetime field drives the Monthly-day-31 tooltip refresh
        # (so the warning stays in sync regardless of which input
        # the user touches last). The Reset button raises the
        # custom-locked override confirmation.
        self._recurrence_picker.currentTextChanged.connect(self._on_recurrence_changed)
        self._recurrence_reset_button.clicked.connect(self._on_recurrence_reset_clicked)
        self._end_date_checkbox.toggled.connect(self._end_date_field.setEnabled)
        self._datetime_field.dateTimeChanged.connect(self._update_monthly_tooltip)

        # S-08: initial cascade — match the end-date row's enabled
        # state to the freshly-seeded picker. In Add mode the picker
        # is None → cascade disables the end-date row. In Edit mode
        # the cascade is idempotent on the pre-filled state for
        # recurring loads, and unticks the (already-disabled) end-
        # date for one-shot loads. The (custom) branch counts as
        # recurring per F1 — the cascade leaves the end_at pre-fill
        # intact so a no-op save preserves it byte-for-byte.
        self._on_recurrence_changed(self._recurrence_picker.currentText())

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

    def _on_recurrence_changed(self, choice: str) -> None:
        """Cascade the recurrence picker's state onto the end-date row.

        Wired to ``self._recurrence_picker.currentTextChanged``. The
        ``(custom)`` choice counts as recurring for cascade purposes
        (F1 fix from plan review): a loaded custom-locked reminder
        with ``end_at`` set must keep its checkbox checked + field
        enabled so a no-op save doesn't silently drop the user's
        end-date. The Monthly-day-31 tooltip has its own narrower
        guard inside ``_update_monthly_tooltip``, so the (custom)
        choice never accidentally triggers the Monthly warning.

        Args:
            choice: The picker's current text (one of the four
                standard labels or ``(custom)`` in the locked state).
        """
        is_recurring = choice != _RECURRENCE_NONE_LABEL
        self._end_date_checkbox.setEnabled(is_recurring)
        if not is_recurring:
            # Unticking cascades through ``toggled`` to disable the
            # date field too. Only fired when transitioning OUT of a
            # recurring choice so existing pre-fill state is
            # preserved on the recurring → recurring path.
            self._end_date_checkbox.setChecked(False)
        self._update_monthly_tooltip()

    def _update_monthly_tooltip(self) -> None:
        """Refresh the Monthly-day-31 tooltip on the recurrence picker.

        Wired to BOTH ``self._recurrence_picker.currentTextChanged``
        (via ``_on_recurrence_changed`` step 3) AND
        ``self._datetime_field.dateTimeChanged`` so the warning stays
        in sync regardless of which input the user touches last
        (F5 fix from plan review).

        The tooltip is informational, not a gate — ``dateutil``
        naturally skips months without the chosen day-of-month
        (Feb 31 doesn't exist; the rule fires Mar 31 instead). The
        save still succeeds; the user sees the warning on hover.

        While the picker is disabled (custom-locked state), this
        method early-returns so it doesn't clobber the
        ``_RECURRENCE_CUSTOM_TOOLTIP`` set in ``__init__``.
        """
        if not self._recurrence_picker.isEnabled():
            return
        if self._recurrence_picker.currentText() != _RECURRENCE_MONTHLY_LABEL:
            self._recurrence_picker.setToolTip("")
            return
        naive_local = cast(datetime, self._datetime_field.dateTime().toPython())
        if naive_local.day > 28:
            self._recurrence_picker.setToolTip(_MONTHLY_DAY31_TOOLTIP)
        else:
            self._recurrence_picker.setToolTip("")

    def _on_recurrence_reset_clicked(self) -> None:
        """Override the custom-locked picker via a Yes/No confirm.

        Wired to ``self._recurrence_reset_button.clicked``. Yes
        unwinds the entire custom-locked state: drops the original
        rule reference, removes the (custom) item from the dropdown,
        re-enables the picker at None, clears the custom-tooltip,
        and hides the Reset button. The picker's
        ``currentTextChanged`` signal then cascades through
        ``_on_recurrence_changed`` to disable the end-date row.

        No is a noop — leaves the dialog exactly as it was.
        """
        reply = QMessageBox.question(
            self,
            _RECURRENCE_RESET_CONFIRM_TITLE,
            _RECURRENCE_RESET_CONFIRM_TEXT,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._original_custom_rrule = None
        custom_index = self._recurrence_picker.findText(_RECURRENCE_CUSTOM_LABEL)
        if custom_index >= 0:
            self._recurrence_picker.removeItem(custom_index)
        self._recurrence_picker.setEnabled(True)
        self._recurrence_picker.setToolTip("")
        self._recurrence_picker.setCurrentText(_RECURRENCE_NONE_LABEL)
        self._recurrence_reset_button.setVisible(False)

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
           lead). **Edit-mode skip**: when the user hasn't moved the
           firing time (``start_at_utc == self._editing.start_at``),
           the gate is bypassed so renaming or re-leading an already-
           expired reminder doesn't require also rescheduling it.
        3. **Construct Reminder.** One-shot encoding: ``rrule_str=None``,
           ``end_at=None``. In Add mode ``id`` is auto-generated; in
           Edit mode ``id`` is preserved from ``self._editing.id`` so
           ``store.update()`` finds the existing row. ``start_at`` is
           the tz-aware UTC firing instant; ``lead_minutes`` is round-
           trip metadata so the Edit dialog can reconstruct the event
           time as ``start_at + timedelta(lead_minutes)``.
        4. **Persist.** Add mode calls ``store.add()``, Edit mode calls
           ``store.update()``. Both are atomic; the only error we guard
           is ``OSError`` (permission denied / disk full). On failure:
           tooltip anchored to OK button, early return, no scheduler
           reload, no signal emit, no super().accept().
        5. **Arm.** ``scheduler.reload()`` recomputes the next firing
           and rearms the single-shot timer. Without it, the reminder
           sits on disk but the running session doesn't see the change.
           Edit mode arms against the (possibly retimed) reminder; Add
           mode arms against the new entry.
        6. **Emit.** ``self.reminder_added.emit(reminder)`` (Add) or
           ``self.reminder_updated.emit(reminder)`` (Edit) runs
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

        # R-1b Phase 3: capture the user's current OS-local IANA name
        # at save time. Used below at every ``Reminder(...)``
        # construction so the Phase 2 scheduler fix (which localizes
        # RRULE math to ``reminder.tz``) actually receives a real
        # named zone — not a UTC fixed offset. ``tzlocal`` reads
        # the OS's local zone via platform-specific APIs; on Windows
        # it normalizes the Registry's TimeZoneKeyName via
        # ``tzdata``. The ``or "UTC"`` defends against the rare
        # case where ``tzlocal`` returns an empty string on an
        # unconfigured system; the ``try/except`` defends against
        # the rarer case where the Registry's TimeZoneKeyName is
        # corrupted or missing and ``tzlocal`` raises rather than
        # returning empty — mirroring the same fallback chain in
        # ``storage.reminders._coerce_tz`` (impl-review F1).
        try:
            current_tz = tzlocal.get_localzone_name() or "UTC"
        except ZoneInfoNotFoundError:
            current_tz = "UTC"

        # 2. Datetime validation (compare in UTC; widget gives naive local)
        # ``.toPython()`` returns a Python ``datetime`` at runtime but
        # the PySide6 stubs type it as ``object``. Use ``typing.cast``
        # for static narrowing — the runtime contract is documented by
        # PySide6 and an ``assert isinstance`` here would be stripped
        # under ``python -O`` while adding zero value at runtime
        # (retrospective impl-review F5).
        naive_local = cast(datetime, self._datetime_field.dateTime().toPython())
        # ``naive_local.astimezone(UTC)`` interprets the naive value as
        # system-local wall-clock and converts to UTC. Per the Python
        # 3.6+ contract, ``astimezone`` on a naive datetime uses the
        # local zone's offset for **that** wall-clock value — which
        # means DST is correct on a per-instant basis. The previous
        # idiom (``datetime.now().astimezone().tzinfo`` + ``.replace``)
        # captured NOW's offset and reapplied it to ``naive_local``;
        # in a DST-spanning Edit (load a January reminder in July,
        # change only the name, save) that produced a wrong UTC and
        # broke the Edit-mode skip equality. See impl-review F3.
        event_at_utc = naive_local.astimezone(UTC)
        lead_minutes = self._lead_minutes_field.value()
        start_at_utc = event_at_utc - timedelta(minutes=lead_minutes)

        # 2b. S-08: translate recurrence picker + end-date row into
        # the proposed (rrule_str, end_at) pair. Custom-locked path
        # bypasses the picker and writes back ``self._original_custom_rrule``
        # verbatim so a no-op save round-trips the user's original
        # rule byte-for-byte (FR-015 hand-edit invariant).
        picker_choice = self._recurrence_picker.currentText()
        if picker_choice == _RECURRENCE_CUSTOM_LABEL:
            rrule_str_proposed = self._original_custom_rrule
        else:
            rrule_str_proposed = _picker_choice_to_rrule(picker_choice)
        if rrule_str_proposed is None:
            # One-shot: end_at is irrelevant. Defensive — checkbox
            # should already be disabled+unchecked by the cascade,
            # but force None here so a buggy cascade can never leak
            # an end_at into a one-shot reminder.
            end_at_proposed: datetime | None = None
        elif self._end_date_checkbox.isChecked():
            picked_date = cast(date, self._end_date_field.date().toPython())
            end_at_proposed = _local_date_to_utc_end_of_day(picked_date)
        else:
            end_at_proposed = None

        # 2c. Recurrence-aware past-time gate. Edit-mode skip widens
        # to compare three fields (start_at, rrule_str, end_at): when
        # all three match the loaded reminder, the gate yields so a
        # rename / re-lead on an expired reminder still saves. When
        # any one differs, the gate applies. One-shot branch keeps
        # the existing strict-future predicate; recurring branch asks
        # ``next_firing_after`` for at least one future occurrence.
        firing_unchanged_in_edit = (
            self._editing is not None
            and start_at_utc == self._editing.start_at
            and rrule_str_proposed == self._editing.rrule_str
            and end_at_proposed == self._editing.end_at
        )
        if not firing_unchanged_in_edit:
            if rrule_str_proposed is None:
                if start_at_utc <= self._clock():
                    message = (
                        _format_past_time_with_lead(lead_minutes)
                        if lead_minutes > 0
                        else _PAST_TIME_MESSAGE
                    )
                    self._show_tooltip(self._datetime_field, message)
                    return
            else:
                # Construct a tentative Reminder so ``next_firing_after``
                # parses the rule against the proposed (start_at,
                # end_at) pair. Constructing twice is the simplest
                # correct shape — the dataclass is cheap (no IO, no
                # validation), and the gate must run BEFORE the real
                # construction in step 3 so an unparseable / exhausted
                # rule blocks the save.
                # ``tz=current_tz`` because the tentative is only built
                # in the ``not firing_unchanged_in_edit`` branch — by
                # definition the user has reshaped the schedule, so
                # the gate must evaluate against the NEW wall-clock
                # anchor (R-1b Phase 3 F2: refresh tz on firing change).
                tentative = Reminder(
                    name=stripped_name,
                    start_at=start_at_utc,
                    rrule_str=rrule_str_proposed,
                    end_at=end_at_proposed,
                    lead_minutes=lead_minutes,
                    tz=current_tz,
                )
                if next_firing_after(tentative, self._clock()) is None:
                    message = (
                        _format_no_future_occurrences_with_lead(lead_minutes)
                        if lead_minutes > 0
                        else _NO_FUTURE_OCCURRENCES_MESSAGE
                    )
                    self._show_tooltip(self._datetime_field, message)
                    return

        # 3. Construct reminder. In Edit mode pass the loaded ``id``
        # explicitly so ``store.update()`` finds the existing row; in
        # Add mode the dataclass default-factory generates a fresh UUID.
        # S-08: ``rrule_str`` and ``end_at`` round-trip through both
        # branches so recurring reminders persist correctly.
        if self._editing is not None:
            # R-1b Phase 3 F2: preserve ``self._editing.tz`` when the
            # firing time / cadence / end date are byte-identical to
            # the loaded reminder; otherwise refresh to current
            # OS-local. Rationale: a pure rename or re-lead must
            # NOT silently retag the reminder's wall-clock
            # interpretation — a user who moved laptops from Warsaw
            # to LA would otherwise shift every reminder by 9h just
            # by renaming one. When they actively move the firing
            # time, they're reshaping the schedule and the new tz
            # becomes its anchor. The predicate reuses the same
            # ``firing_unchanged_in_edit`` boolean that gates the
            # past-time skip above — same conceptual question
            # ("did anything firing-relevant move?"), one source
            # of truth.
            persisted_tz = self._editing.tz if firing_unchanged_in_edit else current_tz
            reminder = Reminder(
                id=self._editing.id,
                name=stripped_name,
                start_at=start_at_utc,
                rrule_str=rrule_str_proposed,
                end_at=end_at_proposed,
                lead_minutes=lead_minutes,
                tz=persisted_tz,
            )
        else:
            reminder = Reminder(
                name=stripped_name,
                start_at=start_at_utc,
                rrule_str=rrule_str_proposed,
                end_at=end_at_proposed,
                lead_minutes=lead_minutes,
                tz=current_tz,
            )

        # 4. Persist (atomic; only OSError needs guarding). Dispatch
        # by mode: Edit → update, Add → add.
        try:
            if self._editing is not None:
                self._store.update(reminder)
            else:
                self._store.add(reminder)
        except OSError as exc:
            logger.exception(
                "ReminderStore.%s failed",
                "update" if self._editing is not None else "add",
            )
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
        #    dialog as still-open (result == Rejected). Pinned by
        #    ``test_save_emits_reminder_added_before_super_accept`` (Add)
        #    and ``test_edit_mode_emit_before_super_accept_ordering`` (Edit).
        if self._editing is not None:
            self.reminder_updated.emit(reminder)
        else:
            self.reminder_added.emit(reminder)

        # 7. Close
        super().accept()
