"""Tests for ``ReminderFormDialog`` (S-06 / FR-011).

Covers:

- **Defaults**: name field empty + placeholder set; datetime field
  defaulted to ``clock() + 1h`` rounded up to the next 15-minute boundary
  in **system local time** (the widget displays naive local).
- **Validation**: empty-name and past-time gates each surface their
  documented tooltip AND block the entire save (no ``store.add``, no
  ``scheduler.reload``, no signal emit, no ``super().accept()``).
- **Save**: happy path persists via ``store.add``, calls
  ``scheduler.reload``, and emits ``reminder_added`` with the saved
  ``Reminder``. The emit-before-super-accept ordering is pinned by a
  ``dialog.result()`` snapshot at emit time.
- **Atomic save tripwire**: ``OSError`` from ``store.add`` blocks
  scheduler reload, signal emit, and the dialog close.

Tests inject a frozen ``Clock`` so default-value and past-time assertions
are stable regardless of the runner's wall clock and system zone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDateTimeEdit, QDialog, QDialogButtonBox, QLineEdit

from break_reminder.scheduler import ReminderScheduler
from break_reminder.storage.reminders import Reminder, ReminderStore
from break_reminder.ui import reminder_form_dialog as reminder_form_dialog_module
from break_reminder.ui.reminder_form_dialog import (
    _DATETIME_DISPLAY_FORMAT,
    _DEFAULT_OFFSET_HOURS,
    _DEFAULT_ROUND_MINUTES,
    _NAME_EMPTY_MESSAGE,
    _NAME_PLACEHOLDER,
    _PAST_TIME_MESSAGE,
    ReminderFormDialog,
    _qdatetime_from_naive_local,
    _round_up_to_minutes,
)

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


class Clock:
    """Mutable, controllable time source. Returns tz-aware UTC."""

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
def frozen_utc() -> datetime:
    """A fixed UTC instant deliberately offset from a quarter-hour boundary.

    ``17:23:45`` is intentionally not on a 15-minute boundary AND has
    non-zero seconds, so the +1h rounding test exercises the bump path
    (not the "already on a boundary" branch).
    """
    return datetime(2026, 5, 20, 17, 23, 45, tzinfo=UTC)


@pytest.fixture
def clock(frozen_utc: datetime) -> Clock:
    """A ``Clock`` pinned at ``frozen_utc`` for deterministic defaults."""
    return Clock(frozen_utc)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Path to a per-test ``reminders.json`` file under ``tmp_path``."""
    return tmp_path / "reminders.json"


@pytest.fixture
def store(store_path: Path) -> ReminderStore:
    """A ``ReminderStore`` bound to the per-test ``store_path``."""
    return ReminderStore(path=store_path)


class StubScheduler:
    """No-op ``ReminderScheduler`` stand-in that counts ``reload`` calls.

    Production passes a real ``ReminderScheduler`` whose ``reload`` does
    the FR-014 RRULE math; for the form-dialog tests we only need to
    prove the call was issued in the right order — the scheduler's own
    behaviour is covered by ``tests/test_reminder_scheduler.py``.
    """

    def __init__(self) -> None:
        """Initialize the stub with a zero call count."""
        self.reload_calls = 0

    def reload(self) -> None:
        """Record one ``reload`` invocation by incrementing ``reload_calls``."""
        self.reload_calls += 1


@pytest.fixture
def scheduler_stub() -> StubScheduler:
    """A ``StubScheduler`` injected wherever the form needs ``ReminderScheduler``."""
    return StubScheduler()


@pytest.fixture
def dialog(
    qtbot,
    store: ReminderStore,
    scheduler_stub: StubScheduler,
    clock: Clock,
) -> ReminderFormDialog:
    """A ``ReminderFormDialog`` wired against the in-test fixtures."""
    d = ReminderFormDialog(
        store=store,
        scheduler=scheduler_stub,  # type: ignore[arg-type]
        clock=clock,
    )
    qtbot.addWidget(d)
    return d


def _expected_default_naive_local(frozen_utc: datetime) -> datetime:
    """Compute the naive-local default value the widget should display.

    Mirrors the seeding flow in ``ReminderFormDialog._compute_default_datetime``:
    UTC → system local → +1h → round-up to next 15-min boundary → strip
    tzinfo. Computed test-side (not hardcoded) so the assertion holds on
    any CI runner regardless of system zone.
    """
    local = frozen_utc.astimezone() + timedelta(hours=_DEFAULT_OFFSET_HOURS)
    rounded = _round_up_to_minutes(local, _DEFAULT_ROUND_MINUTES)
    return rounded.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestReminderFormDialogDefaults:
    """Initial-state invariants for the form's two fields."""

    def test_name_field_empty_at_construction(self, dialog: ReminderFormDialog) -> None:
        """The name ``QLineEdit`` starts empty."""
        assert dialog._name_field.text() == ""

    def test_name_field_has_placeholder(self, dialog: ReminderFormDialog) -> None:
        """The name field exposes the documented placeholder string."""
        assert dialog._name_field.placeholderText() == _NAME_PLACEHOLDER

    def test_datetime_field_defaults_to_frozen_now_plus_offset_rounded(
        self, dialog: ReminderFormDialog, frozen_utc: datetime
    ) -> None:
        """Datetime widget defaults to ``clock() + 1h`` rounded up to 15-min, in local zone.

        The expected value is computed from the injected frozen UTC clock
        — NOT hardcoded — so the test holds on any CI runner regardless
        of system zone. The seeding flow is documented inline in
        ``ReminderFormDialog._compute_default_datetime``.
        """
        expected = _expected_default_naive_local(frozen_utc)
        actual = dialog._datetime_field.dateTime().toPython()
        assert actual == expected

    def test_datetime_field_uses_calendar_popup(self, dialog: ReminderFormDialog) -> None:
        """The datetime widget exposes a calendar popup affordance."""
        assert dialog._datetime_field.calendarPopup() is True

    def test_datetime_field_display_format(self, dialog: ReminderFormDialog) -> None:
        """The displayed format matches the documented constant."""
        assert dialog._datetime_field.displayFormat() == _DATETIME_DISPLAY_FORMAT

    def test_window_title_is_add_reminder(self, dialog: ReminderFormDialog) -> None:
        """The dialog title is exactly the documented label."""
        assert dialog.windowTitle() == "Add Reminder"

    def test_dialog_carries_stays_on_top_hint(self, dialog: ReminderFormDialog) -> None:
        """The popup is marked WindowStaysOnTopHint so it can't slip behind."""
        assert bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_round_up_helper_already_on_boundary_with_zero_seconds(self) -> None:
        """Helper no-ops when the input already sits exactly on a 15-min boundary.

        Direct unit test for the ``_round_up_to_minutes`` no-bump branch:
        ``17:15:00`` with zero microseconds returns unchanged (modulo
        ``second=0, microsecond=0`` re-application, which is also
        idempotent here).
        """
        on_boundary = datetime(2026, 5, 20, 17, 15, 0)
        assert _round_up_to_minutes(on_boundary, 15) == on_boundary

    def test_round_up_helper_pushes_to_next_boundary(self) -> None:
        """Helper bumps to the next 15-min slot when not on boundary."""
        off_boundary = datetime(2026, 5, 20, 17, 8, 30)
        expected = datetime(2026, 5, 20, 17, 15, 0)
        assert _round_up_to_minutes(off_boundary, 15) == expected

    def test_round_up_helper_handles_hour_rollover(self) -> None:
        """Helper rolls hours over correctly at the 60-minute boundary."""
        end_of_hour = datetime(2026, 5, 20, 17, 53, 0)
        expected = datetime(2026, 5, 20, 18, 0, 0)
        assert _round_up_to_minutes(end_of_hour, 15) == expected


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _patch_show_text(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replace ``QToolTip.showText`` in the dialog module with a recording stub."""
    calls: list[tuple] = []

    def _stub(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(
        "break_reminder.ui.reminder_form_dialog.QToolTip.showText",
        _stub,
    )
    return calls


class TestReminderFormDialogValidation:
    """Name and datetime gates block save and surface tooltips."""

    def test_empty_name_blocks_save(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Empty name → tooltip + no store mutation + no scheduler reload + no super().accept()."""
        calls = _patch_show_text(monkeypatch)
        # Sanity: the field is empty by default.
        assert dialog._name_field.text() == ""
        received: list[Reminder] = []
        dialog.reminder_added.connect(received.append)

        dialog.accept()

        assert store.list_all() == []
        assert scheduler_stub.reload_calls == 0
        assert received == []
        # Dialog still rejected (super().accept() wasn't called).
        assert dialog.result() == int(QDialog.DialogCode.Rejected)
        # Tooltip surfaced with the documented message.
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _NAME_EMPTY_MESSAGE

    def test_whitespace_only_name_blocks_save(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Whitespace-only name is treated the same as fully empty (strip-then-check)."""
        _patch_show_text(monkeypatch)
        dialog._name_field.setText("   \t  ")

        dialog.accept()

        assert store.list_all() == []
        assert dialog.result() == int(QDialog.DialogCode.Rejected)

    def test_past_time_blocks_save(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Datetime in the past (per the injected clock) → tooltip + atomic-save tripwire."""
        calls = _patch_show_text(monkeypatch)
        dialog._name_field.setText("Past")
        # Set the widget to 5 minutes BEFORE the frozen clock, in local
        # display zone. Convert clock UTC → local for the widget.
        local_now = clock().astimezone()
        local_past = (local_now - timedelta(minutes=5)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))
        received: list[Reminder] = []
        dialog.reminder_added.connect(received.append)

        dialog.accept()

        assert store.list_all() == []
        assert scheduler_stub.reload_calls == 0
        assert received == []
        assert dialog.result() == int(QDialog.DialogCode.Rejected)
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _PAST_TIME_MESSAGE

    def test_exactly_now_blocks_save(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The "strictly in the future" gate rejects ``fire_at == clock()``.

        Documents the gate's strict-inequality semantics: a reminder set
        for the current instant is unobservable to the user (would fire
        the moment they click Save), so we treat it the same as past.
        """
        _patch_show_text(monkeypatch)
        dialog._name_field.setText("Now")
        local_now = clock().astimezone().replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_now))

        dialog.accept()

        assert store.list_all() == []
        assert dialog.result() == int(QDialog.DialogCode.Rejected)


# ---------------------------------------------------------------------------
# Save path
# ---------------------------------------------------------------------------


class TestReminderFormDialogSave:
    """The happy path: persist + reload + emit + super().accept()."""

    def _populate_valid(self, dialog: ReminderFormDialog, clock: Clock) -> None:
        """Set the form to a valid (name, future-datetime) pair.

        Sets the datetime to +30 minutes from the injected clock, in
        local display zone. Keeps the helper short so each test reads
        as the assertion it cares about.
        """
        dialog._name_field.setText("Test reminder")
        local_future = (clock().astimezone() + timedelta(minutes=30)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))

    def test_successful_save_persists_to_store(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """``accept()`` writes one ``Reminder`` to the store."""
        self._populate_valid(dialog, clock)

        dialog.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].name == "Test reminder"
        # start_at is tz-aware UTC.
        assert items[0].start_at.tzinfo is not None
        # One-shot encoding: no RRULE and no end_at.
        assert items[0].rrule_str is None
        assert items[0].end_at is None

    def test_successful_save_calls_scheduler_reload(
        self,
        dialog: ReminderFormDialog,
        clock: Clock,
        scheduler_stub: StubScheduler,
    ) -> None:
        """``accept()`` calls ``scheduler.reload()`` exactly once on success."""
        self._populate_valid(dialog, clock)

        dialog.accept()

        assert scheduler_stub.reload_calls == 1

    def test_successful_save_closes_dialog(
        self,
        dialog: ReminderFormDialog,
        clock: Clock,
    ) -> None:
        """``accept()`` calls ``super().accept()`` so ``result()`` flips to Accepted."""
        self._populate_valid(dialog, clock)

        dialog.accept()

        assert dialog.result() == int(QDialog.DialogCode.Accepted)

    def test_successful_save_emits_reminder_added_with_saved_reminder(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """The signal payload IS the persisted ``Reminder`` (same id)."""
        self._populate_valid(dialog, clock)
        received: list[Reminder] = []
        dialog.reminder_added.connect(received.append)

        dialog.accept()

        assert len(received) == 1
        saved = store.list_all()[0]
        assert received[0].id == saved.id
        assert received[0].name == "Test reminder"

    def test_save_emits_reminder_added_before_super_accept(
        self,
        dialog: ReminderFormDialog,
        clock: Clock,
    ) -> None:
        """``reminder_added`` fires while ``result()`` is still ``Rejected``.

        Pins the load-bearing emit-before-super-accept ordering from
        ``ReminderFormDialog.accept``. The connected slot captures
        ``dialog.result()`` at emit time; if the implementation ever
        flips the order, the captured value would be ``Accepted`` and
        this test fails.

        Uses the ``QDialog.result()`` snapshot technique rather than
        monkeypatching ``QDialog.accept`` — monkeypatching the parent
        method would affect every ``QDialog`` instance in the test
        process and is process-wide brittle.
        """
        self._populate_valid(dialog, clock)
        captured_result_at_emit: list[int] = []

        def _capture(_reminder: Reminder) -> None:
            captured_result_at_emit.append(dialog.result())

        dialog.reminder_added.connect(_capture)

        dialog.accept()

        assert captured_result_at_emit == [int(QDialog.DialogCode.Rejected)]
        # And after accept() returns, the dialog is now Accepted.
        assert dialog.result() == int(QDialog.DialogCode.Accepted)

    def test_local_to_utc_conversion(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """The saved ``start_at`` equals the widget's local wall-clock converted to UTC.

        Pins the local→UTC conversion in ``accept``. Computes the
        expected UTC value test-side from the same local naive value
        the widget displays, so the assertion holds on any CI runner
        regardless of system zone.
        """
        dialog._name_field.setText("zone test")
        local_future = (clock().astimezone() + timedelta(hours=2)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))

        # Expected UTC: re-attach the local zone, then convert.
        local_tz = datetime.now().astimezone().tzinfo
        expected_utc = local_future.replace(tzinfo=local_tz).astimezone(UTC)

        dialog.accept()

        saved = store.list_all()[0]
        assert saved.start_at == expected_utc

    def test_oserror_on_store_add_blocks_dialog_and_shows_tooltip(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``OSError`` from ``store.add`` → atomic-save tripwire fires.

        Specifically: dialog stays open (``super().accept()`` skipped),
        scheduler is NOT reloaded, signal is NOT emitted, and the
        tooltip surfaces with the OS error's ``strerror``.
        """
        calls = _patch_show_text(monkeypatch)

        def _raise(_reminder: Reminder) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(store, "add", _raise)

        self._populate_valid(dialog, clock)
        received: list[Reminder] = []
        dialog.reminder_added.connect(received.append)

        dialog.accept()

        assert scheduler_stub.reload_calls == 0
        assert received == []
        assert dialog.result() == int(QDialog.DialogCode.Rejected)
        # Tooltip surfaced with the OS-level reason.
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert "Permission denied" in args[1]


# ---------------------------------------------------------------------------
# Cancel path
# ---------------------------------------------------------------------------


class TestReminderFormDialogCancel:
    """``reject()`` discards without persisting anything."""

    def test_reject_does_not_persist(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Filling the form then clicking Cancel leaves the store empty + scheduler quiet."""
        dialog._name_field.setText("never saved")
        local_future = (clock().astimezone() + timedelta(hours=1)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))
        received: list[Reminder] = []
        dialog.reminder_added.connect(received.append)

        dialog.reject()

        assert store.list_all() == []
        assert scheduler_stub.reload_calls == 0
        assert received == []
        assert dialog.result() == int(QDialog.DialogCode.Rejected)


# ---------------------------------------------------------------------------
# Module + integration with real scheduler
# ---------------------------------------------------------------------------


class TestReminderFormDialogWiring:
    """End-to-end wiring against a real ``ReminderScheduler``."""

    def test_save_arms_real_scheduler_against_new_reminder(
        self,
        qtbot,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """A successful save makes the real scheduler aware of the new reminder.

        Uses a real ``ReminderScheduler`` (not the stub) so the
        reload-after-save call wires through to ``_compute_next`` and
        the scheduler's ``_next`` slot ends up populated with the
        saved reminder. Tripwire for the production "Add a reminder
        and it actually fires" flow.
        """
        scheduler = ReminderScheduler(store=store, clock=clock)
        d = ReminderFormDialog(
            store=store,
            scheduler=scheduler,
            clock=clock,
        )
        qtbot.addWidget(d)
        d._name_field.setText("real scheduler")
        local_future = (clock().astimezone() + timedelta(minutes=20)).replace(tzinfo=None)
        d._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))

        d.accept()

        assert scheduler._next is not None
        # And the candidate is the one we just saved.
        saved = store.list_all()[0]
        assert scheduler._next.reminder_id == saved.id


# ---------------------------------------------------------------------------
# Module-import sanity (catches typo / circular-import regressions)
# ---------------------------------------------------------------------------


class TestReminderFormDialogModule:
    """Tripwires for the module surface area."""

    def test_module_exports_reminder_form_dialog(self) -> None:
        """The class is reachable via the module path used by callers."""
        assert hasattr(reminder_form_dialog_module, "ReminderFormDialog")

    def test_dialog_carries_button_box_with_ok_and_cancel(self, dialog: ReminderFormDialog) -> None:
        """Standard OK/Cancel buttons are present + wired."""
        ok = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = dialog._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        assert ok is not None
        assert cancel is not None

    def test_dialog_widgets_have_expected_types(self, dialog: ReminderFormDialog) -> None:
        """The two form fields are the documented widget types."""
        assert isinstance(dialog._name_field, QLineEdit)
        assert isinstance(dialog._datetime_field, QDateTimeEdit)
