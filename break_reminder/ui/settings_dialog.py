r"""Settings dialog (FR-003 / FR-005 / FR-006 / FR-007 / FR-010 / FR-012).

A modal ``QDialog`` that lets the user view and edit BreakReminder's
preferences inside a real settings window. Replaces the v0.1.0
placeholder ``QMessageBox`` that instructed hand-editing the INI file.

Layout uses a ``QTabWidget`` from day one. The current tabs:

- **Scheduling** (S-01 + S-03) — the FR-006 break-interval editor and
  the FR-010 snooze duration / max-snoozes spinboxes.
- **Notifications** (S-04) — the FR-007 voice toggle, editable phrase,
  and a "Test voice" button that previews the unsaved phrase. The
  "Voice phrase cannot be empty when voice is enabled" rule is enforced
  in ``accept()`` via the same transient ``QToolTip`` pattern the
  Scheduling tab uses for the FR-006 range message — saving with that
  combination surfaces the tooltip and skips the persistence write.
- **Lifecycle** (S-02) — the FR-003 Windows-autostart checkbox. Ticking +
  OK writes the per-user
  ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run\BreakReminder``
  value with data ``"<sys.executable>"``; unticking + OK deletes it.
  On winreg failure the dialog surfaces a transient ``QToolTip`` on the
  checkbox and blocks the entire save (atomic save — see S-03 impl-review
  F2 invariant, now extended across all four persisted fields).
- **Reminders** (S-05 / S-06 / S-07) — list of custom reminders pulled
  from ``ReminderStore.list_all()`` once per (re)build. Each row reads
  ``"<name>  —  <next firing | (expired)>"``, sorted chronologically
  (soonest first; expired sink to bottom; tiebreak by name). Empty store
  swaps the list for a centered placeholder label. The button row
  carries ``Add… / Edit… / Delete``. ``Add…`` opens the
  ``ReminderFormDialog`` sub-dialog in Add mode; ``Edit…`` opens the
  same sub-dialog in Edit mode (``reminder=`` kwarg pre-fills);
  ``Delete`` raises a modal ``QMessageBox.question`` Yes/No
  confirmation (default button: No) and on Yes calls
  ``ReminderStore.delete()``. All three flows arm the running session
  via ``ReminderScheduler.reload()`` and rebuild the tab in place via
  ``_refresh_reminders_tab`` so the new state appears immediately.
  Edit / Delete enable on row selection (``currentRowChanged`` →
  ``_on_reminders_selection_changed``) and disable on selection clear.
  The tab does not participate in ``accept()``.

The ``Reminders`` tab is the only reason this module imports
``next_firing_after`` from ``break_reminder.scheduler`` — display logic
needs the same RRULE-aware "when is this next due?" function the
``ReminderScheduler`` already uses. Reusing the pure helper avoids
re-implementing recurrence math in ``ui/`` and keeps the engine the
single source of truth for FR-014 semantics.

Validation is split across two layers, intentionally:

- **Saved-value enforcement** — ``QSpinBox.setMinimum`` /
  ``setMaximum`` constrain ``spinbox.value()`` to FR-006's
  ``[BREAK_INTERVAL_MIN_MINUTES, BREAK_INTERVAL_MAX_MINUTES]`` range.
  Because the save path writes ``spinbox.value()``, the
  ``Settings.break_interval_min`` setter's ``ValueError`` branch is
  unreachable from this dialog and no try/except is needed.
- **Typed-input feedback** — Qt's ``QSpinBox`` does *not* prevent the
  user from typing out-of-range characters into the line edit; it
  silently reverts (below minimum) or truncates to a valid prefix
  (above maximum) when the value commits. The pair
  ``_on_break_interval_text_edited`` (captures raw keystrokes via
  ``lineEdit.textEdited`` before Qt's fixup runs) and
  ``_on_break_interval_edited`` (consumes the snapshot at
  ``editingFinished``) surfaces a transient ``QToolTip`` so the user
  sees the FR-006 constraint instead of a mute revert. See
  ``context/changes/settings-break-interval/plan.md`` "Addenda —
  2026-05-25" for the full rationale.

The dialog is constructed fresh on every "Open settings…" click in
``BreakReminderApp._on_open_settings()`` — no long-lived member, no
stale state across opens. Same lifetime pattern as
``notifications/reminder_dialog.py``'s per-fire instantiation.

``VoiceNotifier`` is injected via the constructor as a required
keyword-only parameter so tests can pass a stub instead of spinning
up a real ``pyttsx3`` worker pool — see
``context/changes/settings-voice-toggle/plan.md`` "Critical
Implementation Details" for the rationale.
"""

from __future__ import annotations

import logging
import sys
import winreg
from datetime import UTC, datetime, timedelta, tzinfo

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from break_reminder.notifications.voice import VoiceNotifier
from break_reminder.scheduler import ReminderScheduler, next_firing_after
from break_reminder.storage.reminders import Reminder, ReminderStore
from break_reminder.storage.settings import (
    BREAK_INTERVAL_MAX_MINUTES,
    BREAK_INTERVAL_MIN_MINUTES,
    MAX_SNOOZES_MAX,
    MAX_SNOOZES_MIN,
    SNOOZE_DURATION_MAX_MINUTES,
    SNOOZE_DURATION_MIN_MINUTES,
    Settings,
)
from break_reminder.ui.reminder_form_dialog import ReminderFormDialog

logger = logging.getLogger(__name__)

# Dialog-wide minimum width (pixels). Without this floor the dialog
# sizes itself to the union of the Scheduling / Notifications /
# Lifecycle tabs' ``sizeHint`` — all three are dominated by compact
# widgets (spinboxes, line edits, checkboxes) and settle at roughly
# 360 px. That width is too narrow for the Reminders tab: a typical
# row like ``"Future one-shot  —  Wed 2026-12-01 11:00"`` is ~42
# characters and the ``QListWidget`` would horizontally scroll on a
# fresh open. 520 px comfortably fits names up to ~55 characters plus
# the ``%a %Y-%m-%d %H:%M`` suffix at the default Segoe UI 9pt size,
# and is a familiar width for a Windows settings dialog (the OS
# Settings flyouts and most Properties dialogs sit in the 480–560 px
# band). The user can still grow the dialog larger; this is a floor,
# not a fixed size.
_DIALOG_MINIMUM_WIDTH = 520

# UI-facing message for the FR-006 range. The bounds themselves come from
# ``storage.settings`` (single source of truth); this string composes them
# into the exact wording the spinbox tooltip and the transient validation
# popup share.
_BREAK_INTERVAL_RANGE_MESSAGE = (
    f"Break interval must be between {BREAK_INTERVAL_MIN_MINUTES} "
    f"and {BREAK_INTERVAL_MAX_MINUTES} minutes."
)

# Tooltip on the max-snoozes spinbox. Surfaces the non-obvious zero-state
# UX: setting the cap to 0 disables snoozing entirely on the next break.
# Without this hint a user lowering the cap to 0 might expect the snooze
# button to still appear and just refuse — the actual behavior is that
# the existing ``snooze_remaining = 0`` path in the scheduler/break
# dialog hides the button outright.
_MAX_SNOOZES_ZERO_TOOLTIP = "0 = no snoozes; the break must be taken or missed."

# Tooltip on the voice checkbox. Conveys the FR-007 contract once at
# the surface where the user is already deciding whether to flip the
# toggle — popup is mandatory; voice is an additional channel, not a
# replacement.
_VOICE_ENABLED_TOOLTIP = "Voice plays alongside the break popup, not instead of it."

# Transient feedback when the user clicks OK with voice enabled but
# a blank/whitespace phrase. Anchored below the phrase line edit so
# the message lands next to the field that must be fixed.
_VOICE_PHRASE_REQUIRED_MESSAGE = "Voice phrase cannot be empty when voice is enabled."

# Tooltip on the autostart checkbox. Surfaces the FR-003 "user opts
# in via the settings panel, no UAC ceremony" commitment that the
# label alone leaves implicit — security-conscious users may otherwise
# assume autostart needs administrator rights.
_AUTOSTART_TOOLTIP = "No admin required — writes to your per-user Windows startup list."

# FR-003 autostart wiring. The subkey lives under HKCU (per-user, no
# elevation) so the FR-003 "user opts in via the settings panel" UX
# holds without UAC prompting. The value name matches the tray
# application name so a user inspecting Task Manager → Startup or
# regedit sees a row labeled "BreakReminder".
_AUTOSTART_RUNKEY_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_VALUE_NAME = "BreakReminder"

# Transient feedback when the per-user Run-key write/delete fails (e.g.,
# locked-down corporate machine, group-policy-blocked HKCU\...\Run, or
# a winreg API error). Anchored on the autostart checkbox by ``accept()``
# and paired with an early return so the entire save is blocked
# (atomic save — see the S-03 impl-review F2 invariant, extended here).
_AUTOSTART_FAILURE_MESSAGE = (
    "Could not update Windows autostart — your machine may block writes to the "
    "per-user startup registry. Contact IT if this persists."
)

# FR-012 / S-05 Reminders tab strings + format.
#
# ``_FIRING_FORMAT`` is locale-aware via ``%a`` (the day-name honors the
# user's current locale — Polish system shows "śr 2026-06-03 14:00", US
# shows "Wed 2026-06-03 14:00"). This is intentional: the rest of the OS
# chrome around the dialog (calendar widgets, file timestamps) follows
# the same convention.
#
# ``_REMINDERS_EMPTY_MESSAGE`` is intentionally pre-accurate for the
# post-S-06 world ("click Add to create one") so the wording doesn't
# need to change when the Add handler ships.
#
# After S-07 the wrapper-tooltip constant is gone: Edit / Delete drop
# their disabled-pair wrappers (Qt 6 no longer needs them because the
# buttons enable on selection and deliver hover events natively).
_EXPIRED_LABEL = "(expired)"
_FIRING_FORMAT = "%a %Y-%m-%d %H:%M"
_REMINDERS_EMPTY_MESSAGE = "No reminders yet — click Add to create one."

# S-08 / FR-014: row suffix labels for active recurring reminders.
# Appended to ``_compose_row`` so the user sees at a glance that a
# row is recurring (and which frequency). Single source of truth —
# the form module produces ``rrule_str`` strings; only this module
# consumes the display labels. Same precedent as ``_FIRING_FORMAT``.
_RECURRENCE_SUFFIX_DAILY = "daily"
_RECURRENCE_SUFFIX_WEEKLY = "weekly"
_RECURRENCE_SUFFIX_MONTHLY = "monthly"
_RECURRENCE_SUFFIX_CUSTOM = "custom"


def _recurrence_label(rrule_str: str | None) -> str:
    """Map a stored ``rrule_str`` to a row-suffix label.

    Reverse-translation analog of the form's ``_rrule_to_picker_choice``
    but emitting display labels (lowercase) instead of picker labels
    (titlecase). One-shot reminders return the empty string so the
    row format is unchanged from the pre-S-08 baseline; any
    non-mapped ``rrule_str`` returns ``"custom"`` so a hand-edited
    advanced rule (e.g. ``FREQ=WEEKLY;BYDAY=MO,WE,FR``) is visible
    in the list — the user can identify the row that corresponds to
    the locked ``(custom)`` state in the form dialog.

    Args:
        rrule_str: The reminder's stored ``rrule_str`` (verbatim).

    Returns:
        ``""`` for ``None`` (one-shot); one of ``"daily"`` /
        ``"weekly"`` / ``"monthly"`` for the canonical mapped
        strings; ``"custom"`` for anything else.
    """
    if rrule_str is None:
        return ""
    if rrule_str == "FREQ=DAILY":
        return _RECURRENCE_SUFFIX_DAILY
    if rrule_str == "FREQ=WEEKLY":
        return _RECURRENCE_SUFFIX_WEEKLY
    if rrule_str == "FREQ=MONTHLY":
        return _RECURRENCE_SUFFIX_MONTHLY
    return _RECURRENCE_SUFFIX_CUSTOM


# FR-012 / S-07 Delete confirm + failure strings.
#
# ``_DELETE_CONFIRM_TITLE`` / ``_DELETE_CONFIRM_TEXT_FORMAT`` populate
# the modal ``QMessageBox.question`` the Delete button raises. The
# format string interpolates the selected reminder's display name so
# the user sees exactly which row is about to vanish. The
# ``"This cannot be undone."`` postscript matches the destructive-
# action convention Windows Settings uses (no Recycle Bin for app
# data; a confirmed Delete is irreversible).
#
# ``_DELETE_FAILED_FORMAT`` is the transient tooltip anchored on the
# Delete button when ``ReminderStore.delete()`` raises ``OSError``
# (locked file / disk full / AV quarantine). Mirrors the form's
# ``_SAVE_FAILED_FORMAT`` convention; the ``{error}`` placeholder is
# filled with ``OSError.strerror`` (or ``str(exc)`` when ``strerror``
# is empty) so the user sees the OS-level reason for the failure.
_DELETE_CONFIRM_TITLE = "Delete reminder"
_DELETE_CONFIRM_TEXT_FORMAT = 'Delete reminder "{name}"?\nThis cannot be undone.'
_DELETE_FAILED_FORMAT = "Could not delete reminder: {error}"


def _format_firing(fire_at: datetime | None, *, tz: tzinfo | None = None) -> str:
    """Render a next-firing datetime for the Reminders list.

    Args:
        fire_at: The next firing as a tz-aware ``datetime``, or ``None``
            when the reminder's series is exhausted (one-shot already
            past, or recurring series past its ``end_at``).
        tz: Optional target timezone for the conversion. Defaults to
            ``None``, which ``datetime.astimezone()`` interprets as the
            system local zone — production behaviour. Tests pass an
            explicit ``timezone(timedelta(hours=-8))`` so the conversion
            is observable on any CI runner regardless of its system
            zone; without this injection, ``<utc>.astimezone() == <utc>``
            on a UTC runner and the test passes even if the
            implementation skipped the conversion entirely.

    Returns:
        ``"(expired)"`` for a ``None`` input. Otherwise the input
        converted to ``tz`` and formatted as ``"%a %Y-%m-%d %H:%M"``
        (e.g. ``"Wed 2026-06-03 14:00"``).
    """
    if fire_at is None:
        return _EXPIRED_LABEL
    return fire_at.astimezone(tz).strftime(_FIRING_FORMAT)


def _sort_key(reminder: Reminder, now: datetime) -> tuple:
    """Per-row sort key for the Reminders list (S-05).

    Future firings sort before expired ones (tuple element 0 is ``0`` vs
    ``1``); within the future bucket, ascending by firing time; alphabetical
    case-insensitive name as final tiebreak in both buckets.

    The tuple shape differs between buckets (3-element for future,
    2-element for expired) on purpose. Python's tuple comparison is
    by-element with short-circuit on the first; the two shapes never
    need to compare past element 0 because the ``0`` group always sorts
    before the ``1`` group. Trying to unify the shapes with a sentinel
    ``datetime.max`` for expired would ``TypeError`` because
    ``datetime.max`` is naive and ``next_firing_after`` returns
    tz-aware values.

    Args:
        reminder: The reminder to compute the key for.
        now: Reference time the scheduler uses to decide what counts
            as "next" — same ``datetime.now(UTC)`` snapshot the caller
            passes to ``_compose_row`` so two reminders sharing a
            firing-second never race the sort.

    Returns:
        A tuple suitable for ``sorted(..., key=...)`` that encodes the
        future-then-expired-then-alphabetical ordering.
    """
    fire_at = next_firing_after(reminder, now)
    if fire_at is None:
        return (1, reminder.name.lower())
    return (0, fire_at, reminder.name.lower())


def _compose_row(reminder: Reminder, now: datetime, *, tz: tzinfo | None = None) -> str:
    """Build the display string for one Reminders-list row.

    Pure function — both data sources are explicit parameters so the
    test suite can exercise it without a Qt event loop.

    S-06b branching: when ``reminder.lead_minutes > 0`` and the reminder
    is still active (``next_firing_after`` returned a tz-aware
    ``datetime``), the displayed time switches from the firing instant
    to the **event time** (``fire_at + lead_minutes``) and a
    ``"(fires N min before)"`` suffix is appended — the user cares
    primarily about when the event happens; the firing instant is an
    implementation detail of the lead-time choice. The annotation is
    **omitted** for expired reminders even when ``lead_minutes > 0``,
    because "(fires N min before)" reads as a future promise — claiming
    it for something that has already missed its window is misleading.

    S-08 branching: when ``reminder.rrule_str`` is non-None and the
    reminder is still active, a ``"(<freq>)"`` suffix is appended
    after the lead annotation (or as the only suffix if ``lead == 0``).
    Frequency reads ``daily`` / ``weekly`` / ``monthly`` for canonical
    rules, ``custom`` for hand-edited advanced RRULEs. Expired rows
    still suppress all suffixes — the bare ``"(expired)"`` carries
    enough information.

    Args:
        reminder: The reminder whose name, next firing, ``lead_minutes``,
            and (S-08) ``rrule_str`` populate the row.
        now: Reference time forwarded to ``next_firing_after``.
        tz: Optional target timezone forwarded to ``_format_firing``;
            see that helper's docstring for the rationale behind the
            ``None`` default and why tests pass an explicit offset.

    Returns:
        For an expired reminder: ``"<name>  —  (expired)"`` (no lead
        or recurrence suffix regardless of either field).
        For an active one-shot with ``lead_minutes == 0``:
        ``"<name>  —  <next firing>"`` (unchanged from S-06).
        For an active one-shot with ``lead_minutes > 0``:
        ``"<name>  —  <event time>  (fires N min before)"``.
        For an active recurring reminder with ``lead_minutes == 0``:
        ``"<name>  —  <next firing> (<freq>)"``.
        For an active recurring reminder with ``lead_minutes > 0``:
        ``"<name>  —  <event time>  (fires N min before, <freq>)"``.
    """
    fire_at = next_firing_after(reminder, now)
    if fire_at is None:
        return f"{reminder.name}  —  {_format_firing(None, tz=tz)}"
    recurrence = _recurrence_label(reminder.rrule_str)
    if reminder.lead_minutes > 0:
        event_at = fire_at + timedelta(minutes=reminder.lead_minutes)
        if recurrence:
            return (
                f"{reminder.name}  —  {_format_firing(event_at, tz=tz)}"
                f"  (fires {reminder.lead_minutes} min before, {recurrence})"
            )
        return (
            f"{reminder.name}  —  {_format_firing(event_at, tz=tz)}"
            f"  (fires {reminder.lead_minutes} min before)"
        )
    if recurrence:
        return f"{reminder.name}  —  {_format_firing(fire_at, tz=tz)} ({recurrence})"
    return f"{reminder.name}  —  {_format_firing(fire_at, tz=tz)}"


def _write_autostart_runkey(command: str) -> None:
    r"""Write the per-user autostart Run-key value (FR-003).

    Auto-creates the ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``
    subkey if it does not already exist (the canonical Run-key idiom —
    a freshly-provisioned Windows profile, e.g. a CI runner or a brand-new
    user account, can lack the subkey entirely). Uses ``CreateKeyEx``,
    which opens-the-subkey-or-creates-it-if-absent atomically.

    Idempotent: re-issuing the same command is a no-op for the OS, so
    callers can safely re-write on every Settings → OK without checking
    whether the value already exists. The dialog's "no reconciliation"
    drift policy depends on this.

    Args:
        command: Fully-quoted command string Windows will execute on
            user login. Production callers pass ``f'"{sys.executable}"'``;
            tests pass any string they want to capture.

    Raises:
        OSError: If the registry call fails (``PermissionError`` on a
            locked-down machine, generic ``OSError`` on a registry
            corruption case). The dialog's ``accept()`` catches this
            and surfaces a tooltip; nothing else in the codebase calls
            this helper.
    """
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, _AUTOSTART_RUNKEY_SUBKEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, _AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, command)


def _delete_autostart_runkey() -> None:
    r"""Delete the per-user autostart Run-key value if present (FR-003).

    Swallows ``FileNotFoundError`` from either ``OpenKey`` (the Run
    subkey itself is absent — e.g. a fresh GitHub Actions runner profile
    that has never had anything written to
    ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``) or
    ``DeleteValue`` (the subkey exists but the BreakReminder value
    inside it is already gone). Both map to the same "already-deleted"
    semantic — the dialog can always call this without first checking
    whether anything exists.

    Raises:
        OSError: If the registry call fails for any reason other than
            "subkey or value does not exist" (which is silently treated
            as success). The dialog's ``accept()`` catches this and
            surfaces a tooltip.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _AUTOSTART_RUNKEY_SUBKEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        return


class SettingsDialog(QDialog):
    """Modal settings window (FR-003 / FR-005 / FR-006 / FR-007 / FR-010 / FR-012).

    The dialog reads the current break interval, snooze, voice, and
    autostart settings from the injected ``Settings`` instance at
    construction time, lets the user edit them across four tabs
    ("Scheduling", "Notifications", "Lifecycle", "Reminders"), and on
    **OK** persists the new values through ``Settings``. **Cancel**
    discards and closes without writing.

    The "Notifications" tab also exposes a "Test voice" button that
    speaks the line edit's current (unsaved) text via the injected
    ``VoiceNotifier``. The button is a pure side-effect — it does not
    touch ``Settings`` and never triggers a save.

    The "Lifecycle" tab houses the FR-003 autostart checkbox; ticking +
    OK writes the per-user Run-key entry, unticking + OK deletes it.
    Failures surface as a transient tooltip on the checkbox and block
    the entire save.

    The "Reminders" tab renders the contents of the injected
    ``ReminderStore`` as a sorted list (next-firing first, expired
    last, tiebreak by name). After S-07 the full ``Add… / Edit… /
    Delete`` CRUD is wired: Add opens ``ReminderFormDialog`` in Add
    mode; Edit opens the same sub-dialog in Edit mode (with the
    selected reminder pre-filled); Delete raises a modal
    ``QMessageBox`` Yes/No confirmation (default button: No). All
    three flows persist via the store, re-arm the scheduler, and
    rebuild the tab in place via ``_refresh_reminders_tab``. Edit /
    Delete enable on row selection and disable on clear. The tab
    does not participate in ``accept()``; the ``OK`` button still
    only saves the other three tabs' values.
    """

    SCHEDULING_TAB_LABEL = "Scheduling"
    NOTIFICATIONS_TAB_LABEL = "Notifications"
    LIFECYCLE_TAB_LABEL = "Lifecycle"
    REMINDERS_TAB_LABEL = "Reminders"

    # Emitted from ``accept()`` immediately BEFORE ``super().accept()``
    # if and only if ``Settings.break_interval_min`` actually changed
    # since the dialog was opened. Payload is the new (post-save) value
    # in minutes. The S-09 bugfix path: ``BreakReminderApp`` connects
    # this signal in ``_on_open_settings`` to a slot that calls
    # ``BreakScheduler.reset_cycle()`` + ``_refresh_tooltip()`` so the
    # tray countdown re-bases on the new threshold the moment the user
    # clicks OK, instead of carrying over the prior cycle's
    # sub-minute offset.
    #
    # Emit-before-super-accept matters for the same reason the
    # ``ReminderFormDialog.reminder_added`` signal does: connected
    # slots run synchronously and must see ``self.result()`` still
    # ``Rejected`` so they get a coherent dialog state. Pinned by
    # ``test_save_emit_runs_before_super_accept`` in
    # ``tests/test_settings_dialog.py``.
    break_interval_changed = Signal(int)

    def __init__(
        self,
        *,
        settings: Settings,
        voice: VoiceNotifier,
        reminder_store: ReminderStore,
        reminder_scheduler: ReminderScheduler,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and pre-populate widgets from ``settings``.

        Args:
            settings: ``Settings`` instance whose ``break_interval_min``,
                ``voice_enabled``, and ``voice_phrase`` getters are read
                at construction and whose setters are called when the
                user clicks OK.
            voice: ``VoiceNotifier`` the "Test voice" button speaks
                through. Required (no default) so tests must inject a
                stub — defaulting to a fresh ``VoiceNotifier()`` would
                spin up a real ``pyttsx3`` worker pool every time the
                test suite constructs the dialog.
            reminder_store: ``ReminderStore`` the Reminders tab reads
                exactly once at construction via ``list_all()``.
                Required (no default) for the same reason ``voice`` is
                — tests must inject a tmp-path-bound store so the suite
                doesn't touch ``%APPDATA%``. The Add sub-dialog
                persists into the same store; the dialog never writes
                directly outside of that flow.
            reminder_scheduler: ``ReminderScheduler`` the Add sub-dialog
                calls ``reload()`` on to arm the running session
                against a freshly-saved reminder. Required for the same
                reason as ``voice`` / ``reminder_store`` — tests inject
                a stub or a real scheduler bound to the tmp-path store
                so the suite never wires up a real ``QTimer`` against
                production data. The dialog itself does not consult the
                scheduler outside of threading it into the sub-dialog.
            parent: Optional Qt parent. Defaults to ``None`` so the
                dialog gets its own top-level taskbar entry, matching
                the convention used by ``BreakDialog`` and
                ``ReminderDialog``.
        """
        super().__init__(parent)
        self._settings = settings
        self._voice = voice
        self._reminder_store = reminder_store
        self._reminder_scheduler = reminder_scheduler
        self._user_typed_text: str | None = None

        # Populated by ``_build_reminders_tab`` — exactly one is
        # non-``None`` depending on whether the store has any reminders.
        # Stored on self so tests can address them without walking the
        # tab widget tree.
        self._reminders_list: QListWidget | None = None
        self._reminders_placeholder: QLabel | None = None
        # S-07 selection cache. Holds the same ``Reminder`` instances
        # as ``self._reminders_list``'s rows, in the same order
        # (post-``_sort_key`` sort). The Edit / Delete click handlers
        # map ``self._reminders_list.currentRow()`` → this list to
        # locate the selected reminder. Re-populated on every
        # ``_build_reminders_tab`` call so it never drifts from what
        # the list widget displays. Empty when the store is empty
        # (placeholder branch); the selection-gated Edit/Delete
        # buttons stay disabled in that state so an out-of-range index
        # never reaches this cache.
        self._reminders_sorted: list[Reminder] = []
        # The Reminders tab widget itself — stored as of S-06 so the
        # Add-save refresh handler (``_refresh_reminders_tab``) can
        # locate the tab via ``self._tabs.indexOf(self._reminders_tab)``
        # to remove + reinsert it in place. The S-05 rule "store the
        # tab on self only when accept() needs to switch to it" has
        # been amended: storage is now also justified when a non-accept
        # code path needs to address the tab. Initialised lazily by
        # ``_build_reminders_tab``.
        self._reminders_tab: QWidget | None = None

        self.setWindowTitle("Settings")
        # See ``_DIALOG_MINIMUM_WIDTH`` for the rationale — the Reminders
        # tab's list rows are wider than the other three tabs' widgets,
        # so the dialog needs a floor that fits the longest plausible
        # ``"<name>  —  <next firing>"`` string without horizontal
        # scrolling on the ``QListWidget``.
        self.setMinimumWidth(_DIALOG_MINIMUM_WIDTH)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_scheduling_tab(), self.SCHEDULING_TAB_LABEL)
        # Stored on self so accept()'s validation gate can switch to the
        # Notifications tab before anchoring the empty-phrase tooltip — see
        # the impl-review F1 fix in
        # ``context/changes/settings-voice-toggle/reviews/impl-review.md``.
        self._notifications_tab = self._build_notifications_tab()
        self._tabs.addTab(self._notifications_tab, self.NOTIFICATIONS_TAB_LABEL)
        # Stored on self for the same reason as ``_notifications_tab`` —
        # the autostart-failure path in ``accept()`` switches to this tab
        # before anchoring the tooltip on ``_autostart_checkbox``.
        self._lifecycle_tab = self._build_lifecycle_tab()
        self._tabs.addTab(self._lifecycle_tab, self.LIFECYCLE_TAB_LABEL)
        # Reminders tab. The builder assigns ``self._reminders_tab``
        # during construction so ``_refresh_reminders_tab`` can find it
        # later by identity (``indexOf``).
        self._tabs.addTab(self._build_reminders_tab(), self.REMINDERS_TAB_LABEL)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._tabs)
        layout.addWidget(self._buttons)

    def _build_scheduling_tab(self) -> QWidget:
        """Construct the "Scheduling" tab containing the break-interval and snooze spinboxes.

        Returns:
            A ``QWidget`` ready to be added to ``self._tabs``. Three
            spinboxes are stored on ``self`` so the save path can read
            their values: ``_break_interval_spinbox`` (FR-006),
            ``_snooze_duration_spinbox`` (FR-010 duration), and
            ``_max_snoozes_spinbox`` (FR-010 cap).
        """
        tab = QWidget(self._tabs)

        self._break_interval_spinbox = QSpinBox(tab)
        # FR-006: break interval is bounded to [1, 240] minutes at the
        # widget level. By the time `editingFinished` fires Qt has already
        # rewritten the lineEdit text via fixup() — out-of-range typing
        # silently reverts to the prior value (below min) or truncates to
        # the longest valid prefix (above max). To detect "user attempted
        # an out-of-range value" we capture their raw keystrokes via
        # `lineEdit.textEdited` BEFORE fixup runs, then check that captured
        # text in `_on_break_interval_edited`.
        self._break_interval_spinbox.setMinimum(BREAK_INTERVAL_MIN_MINUTES)
        self._break_interval_spinbox.setMaximum(BREAK_INTERVAL_MAX_MINUTES)
        self._break_interval_spinbox.setSuffix(" min")
        self._break_interval_spinbox.setToolTip(_BREAK_INTERVAL_RANGE_MESSAGE)
        self._break_interval_spinbox.setValue(self._settings.break_interval_min)
        self._break_interval_spinbox.editingFinished.connect(self._on_break_interval_edited)
        line_edit = self._break_interval_spinbox.lineEdit()
        if line_edit is not None:
            line_edit.textEdited.connect(self._on_break_interval_text_edited)

        # FR-010 snooze duration. No typed-out-of-range tooltip pattern
        # here (decided during /10x-plan): the 1-30 range is small enough
        # that the spinbox's silent fixup is adequate; replicating the
        # break-interval keystroke-capture pair would duplicate ~40 lines
        # for no observable user benefit.
        self._snooze_duration_spinbox = QSpinBox(tab)
        self._snooze_duration_spinbox.setMinimum(SNOOZE_DURATION_MIN_MINUTES)
        self._snooze_duration_spinbox.setMaximum(SNOOZE_DURATION_MAX_MINUTES)
        self._snooze_duration_spinbox.setSuffix(" min")
        self._snooze_duration_spinbox.setValue(self._settings.snooze_duration_min)

        # FR-010 max snoozes per cycle. Lower bound 0 is intentional —
        # see ``_MAX_SNOOZES_ZERO_TOOLTIP`` for the user-facing hint.
        self._max_snoozes_spinbox = QSpinBox(tab)
        self._max_snoozes_spinbox.setMinimum(MAX_SNOOZES_MIN)
        self._max_snoozes_spinbox.setMaximum(MAX_SNOOZES_MAX)
        self._max_snoozes_spinbox.setToolTip(_MAX_SNOOZES_ZERO_TOOLTIP)
        self._max_snoozes_spinbox.setValue(self._settings.max_snoozes)

        form = QFormLayout(tab)
        form.addRow("Break interval (minutes):", self._break_interval_spinbox)
        form.addRow("Snooze duration (minutes):", self._snooze_duration_spinbox)
        form.addRow("Max snoozes per cycle:", self._max_snoozes_spinbox)

        return tab

    def _build_notifications_tab(self) -> QWidget:
        """Construct the "Notifications" tab (FR-007 voice toggle + phrase + Test).

        The tab carries three widgets:

        - ``self._voice_enabled_checkbox`` — pre-populated from
          ``Settings.voice_enabled``. The checkbox tooltip explains the
          FR-007 contract that the popup is mandatory and voice plays
          alongside, not instead of it.
        - ``self._voice_phrase_edit`` — a ``QLineEdit`` pre-populated
          from ``Settings.voice_phrase``. Always editable regardless of
          the checkbox state so the user can prepare the phrase before
          flipping the gate.
        - ``self._voice_test_button`` — a ``QPushButton`` whose
          ``clicked`` signal calls ``_on_test_voice_clicked`` to speak
          the line edit's current (unsaved) text through the injected
          ``VoiceNotifier``.

        Returns:
            A ``QWidget`` ready to be added to ``self._tabs``.
        """
        tab = QWidget(self._tabs)

        self._voice_enabled_checkbox = QCheckBox("Enable voice notification", tab)
        self._voice_enabled_checkbox.setChecked(self._settings.voice_enabled)
        self._voice_enabled_checkbox.setToolTip(_VOICE_ENABLED_TOOLTIP)

        self._voice_phrase_edit = QLineEdit(tab)
        self._voice_phrase_edit.setText(self._settings.voice_phrase)

        self._voice_test_button = QPushButton("Test voice", tab)
        self._voice_test_button.clicked.connect(self._on_test_voice_clicked)

        # Phrase + Test button share a row so the preview lands right
        # next to the field whose contents it speaks.
        phrase_row = QWidget(tab)
        phrase_row_layout = QHBoxLayout(phrase_row)
        phrase_row_layout.setContentsMargins(0, 0, 0, 0)
        phrase_row_layout.addWidget(self._voice_phrase_edit, 1)
        phrase_row_layout.addWidget(self._voice_test_button, 0)

        form = QFormLayout(tab)
        form.addRow(self._voice_enabled_checkbox)
        form.addRow("Voice phrase:", phrase_row)

        return tab

    def _build_lifecycle_tab(self) -> QWidget:
        """Construct the "Lifecycle" tab (FR-003 autostart checkbox).

        The tab carries one widget:

        - ``self._autostart_checkbox`` — pre-populated from
          ``Settings.autostart``. Ticking + OK fires the per-user
          Run-key write in ``accept()``; unticking + OK fires the
          delete. The checkbox label matches the roadmap S-02
          wording verbatim so docs and code stay in sync.

        Returns:
            A ``QWidget`` ready to be added to ``self._tabs``.
        """
        tab = QWidget(self._tabs)

        self._autostart_checkbox = QCheckBox("Launch BreakReminder at Windows login", tab)
        self._autostart_checkbox.setToolTip(_AUTOSTART_TOOLTIP)
        self._autostart_checkbox.setChecked(self._settings.autostart)

        form = QFormLayout(tab)
        form.addRow(self._autostart_checkbox)

        return tab

    def _build_reminders_tab(self) -> QWidget:
        """Construct the "Reminders" tab (FR-012 / S-05 read-only list).

        Reads ``self._reminder_store.list_all()`` exactly **once** and
        captures a single ``datetime.now(UTC)`` snapshot that's threaded
        through every ``_sort_key`` / ``_compose_row`` call so two
        reminders sharing a firing-second can't race the sort.

        Branches on the store contents:

        - Empty (``list_all() == []``) → swap the list for a centered
          placeholder ``QLabel`` with ``_REMINDERS_EMPTY_MESSAGE``.
          ``self._reminders_list`` stays ``None``;
          ``self._reminders_placeholder`` is the label.
        - Non-empty → build a ``QListWidget`` populated with one
          ``QListWidgetItem`` per reminder, text from ``_compose_row``,
          sorted via ``_sort_key``. ``self._reminders_list`` is the
          widget; ``self._reminders_placeholder`` stays ``None``.
          ``QListWidget.currentRowChanged`` is connected to
          ``_on_reminders_selection_changed`` so S-07 can flip the
          slot body without re-wiring the signal.

        In both branches the disabled ``Add…`` / ``Edit…`` / ``Delete``
        button row (see ``_build_reminders_button_row``) is appended at
        the bottom.

        Returns:
            A ``QWidget`` ready to be added to ``self._tabs``. The
            outer layout is a ``QVBoxLayout`` with two slots: the
            list-or-placeholder on top, the button row on the bottom.
        """
        tab = QWidget(self._tabs)
        # Store on self so ``_refresh_reminders_tab`` can locate the
        # tab by identity for the remove+reinsert flow after a
        # successful Add (S-06). The S-05 rule "store only when
        # ``accept()`` switches to it" is amended: storage is also
        # justified when a non-accept code path needs to address the
        # tab.
        self._reminders_tab = tab
        # Reset the dual-state slots before every (re)build so a rebuild
        # never leaves a stale reference to the old tab's widgets.
        self._reminders_list = None
        self._reminders_placeholder = None
        # Reset the selection cache before every (re)build. After
        # ``_build_reminders_button_row`` runs, the Edit / Delete
        # buttons start disabled (the freshly-built list has no
        # selection), so any stale entries in this cache are
        # unreachable until ``currentRowChanged`` fires with a valid
        # index — which only happens after we repopulate below.
        self._reminders_sorted = []

        # Single shared "now" so every reminder gets compared against
        # the same instant — avoids the rare race where two reminders
        # sharing a firing-second sort differently between consecutive
        # ``_sort_key`` calls because the clock advanced mid-loop.
        now = datetime.now(UTC)
        reminders = self._reminder_store.list_all()

        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        if not reminders:
            self._reminders_placeholder = QLabel(_REMINDERS_EMPTY_MESSAGE, tab)
            self._reminders_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._reminders_placeholder.setWordWrap(True)
            layout.addWidget(self._reminders_placeholder, 1)
        else:
            self._reminders_list = QListWidget(tab)
            # Single sort: materialise the sorted Reminders, populate
            # the list widget, and cache the order in
            # ``self._reminders_sorted`` so the Edit/Delete click
            # handlers can map ``currentRow()`` back to the Reminder.
            # Sorting once (rather than relying on row order matching
            # an external re-sort) eliminates a class of "the list
            # shows row N but the click handler operates on a
            # different reminder" bugs.
            sorted_reminders = sorted(reminders, key=lambda r: _sort_key(r, now))
            self._reminders_sorted = sorted_reminders
            for reminder in sorted_reminders:
                QListWidgetItem(_compose_row(reminder, now), self._reminders_list)
            self._reminders_list.currentRowChanged.connect(self._on_reminders_selection_changed)
            layout.addWidget(self._reminders_list, 1)

        layout.addWidget(self._build_reminders_button_row())

        return tab

    def _build_reminders_button_row(self) -> QWidget:
        """Construct the ``Add… / Edit… / Delete`` row.

        After S-07 all three buttons are enable-capable: ``Add…`` is
        always enabled; ``Edit…`` and ``Delete`` start disabled (no
        row is selected on a freshly-built list) and flip to enabled
        when ``_on_reminders_selection_changed`` fires with a
        non-negative row. They live directly in the row layout — no
        tooltip-bearing wrappers — because the wrapper pattern existed
        only to surface a tooltip on a disabled widget (Qt 6 swallows
        hover events on disabled widgets, so a tooltip set on the
        button itself would never appear). The select-to-enable model
        makes the buttons usable rather than chronically disabled, so
        the wrappers become dead weight.

        The "start disabled" state is **load-bearing**: every
        ``_build_reminders_tab`` rebuild produces a fresh button row
        with no selection on the (rebuilt) list, so Edit/Delete
        default to disabled. ``currentRowChanged`` fires the first
        time the user clicks a row, which routes through
        ``_on_reminders_selection_changed`` and enables them. A unit
        test pins this default-disabled invariant
        (``test_edit_button_disabled_after_refresh_clears_prior_selection``
        and the Delete counterpart) so a future refactor that breaks
        button recreation would surface as a test failure rather than
        as silent data corruption (an enabled Delete with no selection
        would crash on ``currentRow() == -1``).

        Returns:
            A ``QWidget`` row containing the three bare buttons, laid
            out horizontally with a stretchy spacer on the left so the
            buttons hug the right edge of the tab (matches the
            ``QDialogButtonBox`` convention the rest of the dialog
            uses).
        """
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addStretch(1)

        self._reminders_add_button = QPushButton("Add…")
        self._reminders_add_button.clicked.connect(self._on_reminders_add_clicked)
        row_layout.addWidget(self._reminders_add_button)

        self._reminders_edit_button = QPushButton("Edit…")
        # Start disabled — freshly-built lists have no selection.
        # Flipped by ``_on_reminders_selection_changed``.
        self._reminders_edit_button.setEnabled(False)
        self._reminders_edit_button.clicked.connect(self._on_reminders_edit_clicked)
        row_layout.addWidget(self._reminders_edit_button)

        self._reminders_delete_button = QPushButton("Delete")
        self._reminders_delete_button.setEnabled(False)
        self._reminders_delete_button.clicked.connect(self._on_reminders_delete_clicked)
        row_layout.addWidget(self._reminders_delete_button)

        return row

    def _on_reminders_selection_changed(self, current_row: int) -> None:
        """Slot wired to ``QListWidget.currentRowChanged`` (S-07).

        Mirrors the row selection state into the Edit / Delete button
        enabled state: both enable iff a row is selected
        (``current_row >= 0``), both disable when selection clears
        (``current_row == -1``, e.g. after a model reset or a
        programmatic ``setCurrentRow(-1)``).

        The S-05 scaffold-wired the signal to a placeholder body so
        that refactors couldn't silently break the contract; S-07
        fills the body in.

        Args:
            current_row: The newly-selected row index, or ``-1`` when
                the selection is cleared. Used to gate the Edit/Delete
                enabled state directly.
        """
        is_selected = current_row >= 0
        self._reminders_edit_button.setEnabled(is_selected)
        self._reminders_delete_button.setEnabled(is_selected)

    def _on_reminders_add_clicked(self) -> None:
        """Open the Add Reminder sub-dialog and refresh the tab on success.

        Constructs a fresh ``ReminderFormDialog`` parented to ``self``
        and connects its ``reminder_added`` signal to
        ``_refresh_reminders_tab`` **before** ``exec()`` (the signal
        emits from inside the sub-dialog's ``accept()``, which runs
        before ``exec()`` returns). The connected slot rebuilds the
        Reminders tab in place so the new row appears immediately.

        The sub-dialog handles its own validation, persistence
        (``ReminderStore.add``), and scheduler arming
        (``ReminderScheduler.reload``) — this slot is pure wiring.

        ``WA_DeleteOnClose`` ensures the sub-dialog is scheduled for
        destruction the moment it closes (rather than lingering as a
        hidden child of ``self`` until the parent ``SettingsDialog``
        itself closes). Without this, repeated Add → Cancel cycles in
        a single Settings session leave ghost ``ReminderFormDialog``
        instances parented here (retrospective impl-review F6).
        """
        sub_dialog = ReminderFormDialog(
            store=self._reminder_store,
            scheduler=self._reminder_scheduler,
            parent=self,
        )
        sub_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        sub_dialog.reminder_added.connect(self._refresh_reminders_tab)
        sub_dialog.exec()

    def _on_reminders_edit_clicked(self) -> None:
        """Open the Edit Reminder sub-dialog for the selected row.

        Mirrors ``_on_reminders_add_clicked`` shape (parented,
        ``WA_DeleteOnClose``, refresh-on-signal) with three differences:

        1. The ``reminder=`` kwarg pre-fills the form from the selected
           row's ``Reminder`` (looked up by ``currentRow()`` against
           the ``self._reminders_sorted`` cache).
        2. We connect ``reminder_updated`` (not ``reminder_added``) to
           ``_refresh_reminders_tab`` — Add mode fires the former, Edit
           mode fires the latter; both rebuild the tab identically.
        3. The button is **selection-gated** by
           ``_on_reminders_selection_changed`` — it's only enabled when
           ``currentRow() >= 0``, so the assert below is unreachable
           via the GUI. The assert is defensive: it documents the
           invariant and guards against any future code path that
           could fire this handler programmatically without a
           selection (e.g., a keyboard shortcut wired without going
           through the button).

        Steps:

        1. Assert ``self._reminders_list is not None`` (narrows the
           ``QListWidget | None`` type for Pyright and pins the
           invariant).
        2. Read ``currentRow()`` from the list; bail (early return) if
           ``< 0`` — paranoia for the same reason the assert exists.
        3. Look up the Reminder via ``self._reminders_sorted[row]``.
        4. Construct ``ReminderFormDialog(reminder=...)``, set
           ``WA_DeleteOnClose``, connect ``reminder_updated`` to
           ``_refresh_reminders_tab``, then ``exec()``.
        """
        assert self._reminders_list is not None, (
            "_on_reminders_edit_clicked fired without a list widget; "
            "the Edit button is selection-gated and the placeholder "
            "branch never builds the button row in an enabled state"
        )
        row = self._reminders_list.currentRow()
        if row < 0:
            return
        selected = self._reminders_sorted[row]
        sub_dialog = ReminderFormDialog(
            store=self._reminder_store,
            scheduler=self._reminder_scheduler,
            reminder=selected,
            parent=self,
        )
        sub_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        sub_dialog.reminder_updated.connect(self._refresh_reminders_tab)
        sub_dialog.exec()

    def _on_reminders_delete_clicked(self) -> None:
        """Confirm + delete the selected reminder, then rebuild the tab.

        Flow:

        1. Assert ``self._reminders_list is not None`` (mirror of the
           Edit assert; the Delete button is selection-gated the same
           way).
        2. Read ``currentRow()`` and bail if ``< 0``.
        3. Look up the Reminder via ``self._reminders_sorted[row]``.
        4. Raise a modal ``QMessageBox.question`` with Yes/No buttons
           and ``No`` as the default — a stray Enter keypress on the
           confirm dialog cancels the destructive action rather than
           executing it (the Windows Settings convention for
           irreversible operations).
        5. On Yes: call ``ReminderStore.delete(id)`` inside a
           ``try/except OSError`` block. The store's atomic-save
           contract means a failure leaves the prior state on disk
           intact, so on ``OSError`` we surface a transient
           ``QToolTip`` anchored on the Delete button (mirroring the
           form's ``_SAVE_FAILED_FORMAT`` convention) and return
           without rebuilding the tab.
        6. On success: call ``self._reminder_scheduler.reload()`` to
           re-arm the running session against the now-shorter store,
           then ``_refresh_reminders_tab()`` to remove the row from
           the UI immediately.

        The scheduler reload + tab refresh ordering matches the Add
        and Edit flows — engine first, UI second — so a user looking
        at the list after a delete is never staring at a row whose
        timer is still armed.
        """
        assert self._reminders_list is not None, (
            "_on_reminders_delete_clicked fired without a list widget; "
            "the Delete button is selection-gated and the placeholder "
            "branch never builds the button row in an enabled state"
        )
        row = self._reminders_list.currentRow()
        if row < 0:
            return
        selected = self._reminders_sorted[row]
        choice = QMessageBox.question(
            self,
            _DELETE_CONFIRM_TITLE,
            _DELETE_CONFIRM_TEXT_FORMAT.format(name=selected.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            self._reminder_store.delete(selected.id)
        except OSError as exc:
            logger.exception("ReminderStore.delete failed")
            anchor = self._reminders_delete_button.mapToGlobal(
                self._reminders_delete_button.rect().bottomLeft()
            )
            QToolTip.showText(
                anchor,
                _DELETE_FAILED_FORMAT.format(error=exc.strerror or str(exc)),
                self._reminders_delete_button,
                msecShowTime=3000,
            )
            return
        self._reminder_scheduler.reload()
        self._refresh_reminders_tab()

    def _refresh_reminders_tab(self, _reminder: Reminder | None = None) -> None:
        """Remove the Reminders tab and reinsert a freshly-built one.

        Re-uses ``_build_reminders_tab`` verbatim so the sort, compose,
        empty→list transition, and select-gating wiring all evolve in
        one place. The ``_reminder`` parameter exists only to absorb
        the ``reminder_added`` / ``reminder_updated`` signal payload —
        the rebuild reads ``ReminderStore.list_all()`` fresh.

        Order is load-bearing:

        1. Capture ``idx`` via ``indexOf`` BEFORE any mutation — the
           old reference becomes invalid the moment ``removeTab`` runs.
        2. Capture ``was_on_reminders`` (whether the user was looking
           at the Reminders tab) BEFORE the rebuild — needed to
           restore current-tab state at the end. ``removeTab`` causes
           ``QTabWidget`` to silently shift ``currentIndex`` to a
           neighbouring tab during the gap (typically the new last
           tab); ``insertTab`` does NOT restore the prior selection.
           Without an explicit restore, every Add / Edit / Delete
           refresh would yank the user from Reminders onto whatever
           tab Qt chose (in practice: Lifecycle, since it's the new
           last tab after removal). Pinned by
           ``test_refresh_preserves_reminders_as_current_tab``.
        3. Capture ``old_tab`` so we can schedule it for deletion.
        4. ``removeTab(idx)`` removes the page from the tab strip but
           does NOT delete the underlying ``QWidget`` — Qt keeps it
           parented to this dialog.
        5. ``old_tab.deleteLater()`` schedules the orphan for deletion
           on the next event-loop iteration so repeated Adds don't
           accumulate stale tab widgets across the dialog's lifetime.
        6. ``_build_reminders_tab()`` reassigns ``self._reminders_tab``
           (the builder always writes this slot first).
        7. ``insertTab(idx, ..., LABEL)`` puts the fresh tab back at
           the same position so the user's view is undisturbed.
        8. If the user was on Reminders before the rebuild, restore
           the Reminders tab as current. If they were on a different
           tab (atypical — Add / Edit / Delete buttons are only
           reachable from the Reminders tab), leave Qt's choice
           alone so we don't override an intentional cross-tab
           navigation that raced the refresh.

        Args:
            _reminder: Unused — present so this method matches the
                ``reminder_added(Reminder)`` / ``reminder_updated(Reminder)``
                signal signatures when used as a connected slot.
        """
        del _reminder  # signal payload absorbed; rebuild reads the store fresh
        # Narrow the ``QWidget | None`` annotation. The constructor
        # always calls ``_build_reminders_tab()`` (which assigns
        # ``self._reminders_tab = tab`` as its first action) before
        # returning, so this assert is unreachable in practice — but
        # asserting loudly is preferable to silently no-op'ing the
        # rebuild and leaving a stale tab on screen (retrospective
        # impl-review F7; mirrors the ``_fire``-side narrowing pattern
        # in ``scheduler.py``).
        assert self._reminders_tab is not None, (
            "_refresh_reminders_tab called before _build_reminders_tab; "
            "the constructor always builds the tab so this should be unreachable"
        )
        idx = self._tabs.indexOf(self._reminders_tab)
        was_on_reminders = self._tabs.currentIndex() == idx
        old_tab = self._reminders_tab
        self._tabs.removeTab(idx)
        old_tab.deleteLater()
        self._build_reminders_tab()  # reassigns self._reminders_tab
        self._tabs.insertTab(idx, self._reminders_tab, self.REMINDERS_TAB_LABEL)
        if was_on_reminders:
            self._tabs.setCurrentIndex(idx)

    def _on_test_voice_clicked(self) -> None:
        """Speak the phrase line edit's current (unsaved) text.

        Pure side-effect — does not touch ``Settings`` and does not
        chain into the save path. Calls ``VoiceNotifier.speak`` which
        already runs on a single-worker thread pool, so the GUI thread
        does not block. ``VoiceNotifier.speak("")`` is a documented
        no-op, so an empty phrase produces no audio without raising.

        ``stop()`` is called before ``speak()`` so that rapid Test-button
        clicks cancel the prior in-flight preview rather than queuing
        five copies of the speech serially (impl-review F3).
        """
        self._voice.stop()
        self._voice.speak(self._voice_phrase_edit.text())

    def _on_break_interval_text_edited(self, text: str) -> None:
        """Capture the user's raw typed text before Qt's fixup rewrites it.

        ``QLineEdit.textEdited`` fires on every keystroke before the
        spinbox's ``fixup()`` pipeline runs at commit time. Stashing the
        latest typed text here lets ``_on_break_interval_edited`` compare
        intent against bounds rather than against the post-fixup display.

        Args:
            text: Current contents of the spinbox's underlying
                ``QLineEdit`` after the latest keystroke.
        """
        self._user_typed_text = text

    def _on_break_interval_edited(self) -> None:
        """Show a transient tooltip when the user typed an out-of-range value.

        Qt's ``QSpinBox`` does not "clamp" out-of-range typing the way the
        FR-006 setter does — it reverts (below minimum) or truncates to a
        valid prefix (above maximum). Either way, the user's intent is
        lost from the lineEdit by the time this slot fires. The companion
        ``_on_break_interval_text_edited`` slot snapshots the raw typed
        text on every keystroke; here we parse that snapshot and surface
        a brief popup if it falls outside [1, 240] minutes.
        """
        typed_text = self._user_typed_text
        self._user_typed_text = None
        if typed_text is None:
            return
        try:
            typed_value = int(typed_text.removesuffix(" min").strip())
        except ValueError:
            return
        if BREAK_INTERVAL_MIN_MINUTES <= typed_value <= BREAK_INTERVAL_MAX_MINUTES:
            return
        widget = self._break_interval_spinbox
        QToolTip.showText(
            widget.mapToGlobal(widget.rect().bottomLeft()),
            _BREAK_INTERVAL_RANGE_MESSAGE,
            widget,
            msecShowTime=3000,
        )

    def accept(self) -> None:
        """Validate then persist all editable settings and close the dialog.

        Validation gate (FR-007 voice tab): if the voice checkbox is
        ticked but the phrase line edit is blank or whitespace-only,
        surface a transient ``QToolTip`` below the phrase field with
        ``_VOICE_PHRASE_REQUIRED_MESSAGE`` and return early — no setter
        runs and the dialog stays open. The ``(voice_enabled=True,
        voice_phrase="")`` confused state cannot land on disk via the
        GUI.

        Side-effect gate (FR-003 autostart): with the voice gate green,
        the dialog issues the per-user Run-key write or delete BEFORE
        any INI setter. If the registry call raises ``OSError`` (which
        catches ``PermissionError`` and ``FileNotFoundError`` too), the
        dialog switches to the Lifecycle tab, anchors a transient
        ``QToolTip`` on the autostart checkbox, and returns early —
        no INI is written at all. This preserves the S-03 impl-review F2
        atomic-save invariant ("OK saves everything or nothing") across
        all four persisted fields. On success, the autostart INI write
        rides along with the Scheduling/Notifications writes below.

        Persistence order (Scheduling first, Notifications second,
        Lifecycle third):

        - **FR-006 break interval** — written via ``Settings.break_interval_min``;
          widget-level bounds guarantee a [1, 240] value, so the setter's
          ``ValueError`` branch is unreachable here.
        - **FR-010 snooze duration** — written via
          ``Settings.snooze_duration_min``; widget-level [1, 30] bounds
          make the setter's ``ValueError`` branch unreachable from here.
        - **FR-010 max snoozes** — written via ``Settings.max_snoozes``;
          widget-level [0, 5] bounds make the setter's ``ValueError``
          branch unreachable from here.
        - **FR-007 voice toggle and phrase** — written next; the
          ``voice_phrase`` setter is permissive at the persistence layer
          (the dialog-level gate above is the only enforcement of the
          non-empty contract).
        - **FR-003 autostart** — written last; the corresponding
          registry side-effect already succeeded in the side-effect gate
          above, so this write just records the user's intent in the
          INI for the next dialog open.

        Then chains to ``QDialog.accept`` for the standard close path.
        """
        if self._voice_enabled_checkbox.isChecked() and not self._voice_phrase_edit.text().strip():
            # Surface the Notifications tab BEFORE anchoring the tooltip —
            # the user may have clicked OK from the Scheduling tab, in which
            # case the phrase line edit is on a hidden tab and the tooltip
            # would float anchored to nothing visible. Switching tabs first
            # ensures the message points at the field that needs fixing.
            self._tabs.setCurrentWidget(self._notifications_tab)
            anchor = self._voice_phrase_edit.mapToGlobal(
                self._voice_phrase_edit.rect().bottomLeft()
            )
            QToolTip.showText(
                anchor,
                _VOICE_PHRASE_REQUIRED_MESSAGE,
                self._voice_phrase_edit,
                msecShowTime=3000,
            )
            return

        # FR-003: side-effect BEFORE any INI write so a registry failure
        # leaves no partial state behind. ``sys.executable`` resolves to
        # the PyInstaller-frozen ``BreakReminder.exe`` in production and
        # to the python interpreter for source-runs. We deliberately do
        # not support source-run autostart (see plan: "What We're NOT
        # Doing"); the quoted command future-proofs install paths that
        # contain spaces.
        autostart_enabled = self._autostart_checkbox.isChecked()
        try:
            if autostart_enabled:
                _write_autostart_runkey(f'"{sys.executable}"')
            else:
                _delete_autostart_runkey()
        except OSError:
            logger.exception("autostart Run-key write/delete failed")
            # Switch first so the tooltip anchor is on the visible tab,
            # mirroring the voice-empty gate above.
            self._tabs.setCurrentWidget(self._lifecycle_tab)
            anchor = self._autostart_checkbox.mapToGlobal(
                self._autostart_checkbox.rect().bottomLeft()
            )
            QToolTip.showText(
                anchor,
                _AUTOSTART_FAILURE_MESSAGE,
                self._autostart_checkbox,
                msecShowTime=3000,
            )
            return

        # Capture the OLD break interval BEFORE the persistence write so
        # the post-save comparison can detect whether the value actually
        # changed (S-09 bugfix). We read it locally rather than at
        # __init__ time so any future "external write between open and
        # accept" path (none today) would still see the right baseline.
        old_break_interval = self._settings.break_interval_min
        new_break_interval = self._break_interval_spinbox.value()

        self._settings.break_interval_min = new_break_interval
        self._settings.snooze_duration_min = self._snooze_duration_spinbox.value()
        self._settings.max_snoozes = self._max_snoozes_spinbox.value()
        self._settings.voice_enabled = self._voice_enabled_checkbox.isChecked()
        self._settings.voice_phrase = self._voice_phrase_edit.text()
        self._settings.autostart = autostart_enabled

        # S-09: emit BEFORE super().accept() so connected slots see the
        # dialog as still-open. Only fire on an actual change so a save
        # that touches snooze / voice / autostart but leaves the break
        # interval alone preserves the running cycle's accumulator.
        if new_break_interval != old_break_interval:
            self.break_interval_changed.emit(new_break_interval)

        super().accept()
