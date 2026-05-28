"""Tests for ``ReminderFormDialog`` (S-06 / S-06b / S-07 / FR-011 / FR-012).

Covers:

- **Defaults** (Add mode): name field empty + placeholder set; datetime
  field defaulted to ``clock() + 1h`` rounded up to the next 15-minute
  boundary in **system local time** (the widget displays naive local).
- **Validation**: empty-name and past-time gates each surface their
  documented tooltip AND block the entire save (no ``store.add``, no
  ``scheduler.reload``, no signal emit, no ``super().accept()``). In
  Edit mode the past-time gate is skipped when the firing time hasn't
  moved from the loaded reminder.
- **Save (Add)**: happy path persists via ``store.add``, calls
  ``scheduler.reload``, and emits ``reminder_added`` with the saved
  ``Reminder``. The emit-before-super-accept ordering is pinned by a
  ``dialog.result()`` snapshot at emit time.
- **Save (Edit, S-07)**: pre-fills name / lead / event-time from the
  loaded ``Reminder``, persists via ``store.update`` (preserving id),
  calls ``scheduler.reload``, and emits ``reminder_updated`` (NOT
  ``reminder_added``) with the updated ``Reminder``. Same emit-before-
  super-accept ordering as Add.
- **Atomic save tripwire**: ``OSError`` from ``store.add`` /
  ``store.update`` blocks scheduler reload, signal emit, and the
  dialog close.
- **Lead minutes (S-06b)**: spinbox bounds + signal payload +
  lead-aware tooltip wording for the past-event gate.

Tests inject a frozen ``Clock`` so default-value and past-time assertions
are stable regardless of the runner's wall clock and system zone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDateTimeEdit, QDialog, QDialogButtonBox, QLineEdit, QMessageBox

from break_reminder.scheduler import ReminderScheduler
from break_reminder.storage.reminders import Reminder, ReminderStore
from break_reminder.ui import reminder_form_dialog as reminder_form_dialog_module
from break_reminder.ui.reminder_form_dialog import (
    _DATETIME_DISPLAY_FORMAT,
    _DEFAULT_OFFSET_HOURS,
    _DEFAULT_ROUND_MINUTES,
    _END_DATE_DEFAULT_OFFSET_DAYS,
    _LEAD_DEFAULT,
    _LEAD_MAX_VALUE,
    _LEAD_MIN_VALUE,
    _LEAD_SUFFIX,
    _MONTHLY_DAY31_TOOLTIP,
    _NAME_EMPTY_MESSAGE,
    _NAME_PLACEHOLDER,
    _NO_FUTURE_OCCURRENCES_MESSAGE,
    _PAST_TIME_MESSAGE,
    _RECURRENCE_CUSTOM_LABEL,
    _RECURRENCE_CUSTOM_TOOLTIP,
    _RECURRENCE_DAILY_LABEL,
    _RECURRENCE_MONTHLY_LABEL,
    _RECURRENCE_NONE_LABEL,
    _RECURRENCE_WEEKLY_LABEL,
    _RRULE_DAILY,
    _RRULE_MONTHLY,
    _RRULE_WEEKLY,
    ReminderFormDialog,
    _format_no_future_occurrences_with_lead,
    _format_past_time_with_lead,
    _local_date_to_utc_end_of_day,
    _picker_choice_to_rrule,
    _qdatetime_from_naive_local,
    _round_up_to_minutes,
    _rrule_to_picker_choice,
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
        """In Add mode (no ``reminder=`` kwarg) the dialog title reads "Add Reminder"."""
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

    def test_name_validation_wins_over_datetime_validation(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both fields invalid → ONLY the name tooltip fires (first-failing-field-wins).

        Retrospective impl-review F4: pins the validation ordering
        contract documented in ``ReminderFormDialog.accept`` (name first,
        datetime second; mirrors the voice-phrase gate). If a future
        refactor flipped the order, the datetime tooltip would surface
        first and the user would see the wrong remediation hint. Tooltip
        recorder verifies exactly one ``showText`` call with the name
        message; a regression flipping the order would either record the
        datetime message or record both.
        """
        calls = _patch_show_text(monkeypatch)
        # Both invalid: name is empty (default) AND datetime is in the past.
        local_past = (clock().astimezone() - timedelta(minutes=30)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))
        # Sanity: name is empty, so name should fail first.
        assert dialog._name_field.text() == ""

        dialog.accept()

        assert store.list_all() == []
        assert scheduler_stub.reload_calls == 0
        assert dialog.result() == int(QDialog.DialogCode.Rejected)
        # Exactly one tooltip surfaced and it's the NAME message (not the
        # past-time message). The early ``return`` after the name gate
        # is what enforces "first failing field wins".
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _NAME_EMPTY_MESSAGE
        assert args[1] != _PAST_TIME_MESSAGE


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

    def test_successful_save_strips_name_whitespace(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """Surrounding whitespace on a non-empty name is trimmed before persistence.

        Retrospective impl-review F3: production calls ``.strip()`` in
        ``accept()`` (``reminder_form_dialog.py``), and
        ``test_whitespace_only_name_blocks_save`` covers the orthogonal
        "all-whitespace blocks save" case. But no test pinned the
        strip-then-keep behaviour on an otherwise valid name. A future
        regression that dropped the ``.strip()`` (leading to entries
        like ``"  Spaced name  "`` in ``reminders.json``) would not be
        caught without this assertion.
        """
        dialog._name_field.setText("  Spaced name  ")
        local_future = (clock().astimezone() + timedelta(minutes=30)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))

        dialog.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].name == "Spaced name"

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
# Atomic-save tripwire (F2 — pre-seeded store invariance)
# ---------------------------------------------------------------------------


class TestReminderFormDialogAtomicSaveTripwire:
    """Validation failure must leave a pre-existing store byte-identical.

    Retrospective impl-review F2: the existing validation tests assert
    ``store.list_all() == []`` against an empty pre-state — they prove
    "validation failure doesn't persist a new reminder" but not
    "validation failure doesn't corrupt prior persisted state". A
    regression that, e.g., re-wrote ``reminders.json`` with empty
    content on the early-return path would slip past every other test.
    Mirrors the S-04 ``TestNotificationsTabValidation`` tripwire shape
    (pre-seed, attempt save, snapshot the store's list_all output, and
    assert byte-identical equality).
    """

    def _preseed(self, store: ReminderStore, clock: Clock) -> Reminder:
        """Persist one reference reminder so the tripwire has a pre-state to defend."""
        seeded = Reminder(
            name="pre-existing",
            start_at=clock() + timedelta(hours=6),
        )
        store.add(seeded)
        return seeded

    def test_empty_name_failure_preserves_prior_store_state(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Empty-name validation failure leaves a pre-seeded store byte-identical."""
        _patch_show_text(monkeypatch)
        seeded = self._preseed(store, clock)
        before = store.list_all()
        # Sanity: pre-seed actually landed.
        assert len(before) == 1 and before[0].id == seeded.id

        # Attempt save with empty name (default) and a valid future datetime.
        local_future = (clock().astimezone() + timedelta(hours=2)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))

        dialog.accept()

        after = store.list_all()
        assert after == before  # byte-identical Reminder list (dataclass equality)
        assert scheduler_stub.reload_calls == 0
        assert dialog.result() == int(QDialog.DialogCode.Rejected)

    def test_past_time_failure_preserves_prior_store_state(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Past-time validation failure leaves a pre-seeded store byte-identical."""
        _patch_show_text(monkeypatch)
        seeded = self._preseed(store, clock)
        before = store.list_all()
        assert len(before) == 1 and before[0].id == seeded.id

        dialog._name_field.setText("past-attempt")
        local_past = (clock().astimezone() - timedelta(minutes=10)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))

        dialog.accept()

        after = store.list_all()
        assert after == before
        assert scheduler_stub.reload_calls == 0
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


# ---------------------------------------------------------------------------
# S-06b: lead-minutes spinbox
# ---------------------------------------------------------------------------


class TestReminderFormDialogLeadMinutes:
    """S-06b lead-time spinbox + computed-firing-time semantics.

    These tests pin the new behaviour added by S-06b on top of S-06:

    - The spinbox is present, bounded 0-60, defaults to 0, and carries
      the documented suffix.
    - Save with ``lead == 0`` behaves identically to S-06 (the datetime
      widget IS the firing time; saved ``Reminder.lead_minutes`` is 0).
    - Save with ``lead > 0`` interprets the datetime widget as the
      event time and saves ``start_at = event_at - lead`` (firing time)
      plus ``lead_minutes`` as round-trip metadata.
    - Past-event validation tooltip wording flips based on ``lead`` —
      zero-lead reads "Event must be in the future"; non-zero-lead
      reads "Event must be at least N minutes in the future" (with N
      interpolated). The predicate itself is the same in both branches
      (``start_at > now``).
    - The atomic-save tripwire (validation failure → nothing
      persisted) still holds with ``lead > 0``.
    - The ``reminder_added`` signal carries the populated
      ``lead_minutes`` field.
    """

    def test_spinbox_defaults_to_zero(self, dialog: ReminderFormDialog) -> None:
        """The spinbox starts at the documented default value."""
        assert dialog._lead_minutes_field.value() == _LEAD_DEFAULT
        assert _LEAD_DEFAULT == 0

    def test_spinbox_range_matches_documented_bounds(self, dialog: ReminderFormDialog) -> None:
        """The spinbox rejects values outside [0, 60]."""
        assert dialog._lead_minutes_field.minimum() == _LEAD_MIN_VALUE
        assert dialog._lead_minutes_field.maximum() == _LEAD_MAX_VALUE
        assert _LEAD_MIN_VALUE == 0
        assert _LEAD_MAX_VALUE == 60

    def test_spinbox_carries_documented_suffix(self, dialog: ReminderFormDialog) -> None:
        """The displayed suffix matches the module constant."""
        assert dialog._lead_minutes_field.suffix() == _LEAD_SUFFIX

    def test_spinbox_clamps_values_above_max(self, dialog: ReminderFormDialog) -> None:
        """Setting a value above 60 clamps to 60 (Qt's QSpinBox contract).

        Tripwire for the bound: if a future refactor lifts the cap and
        forgets to update this test, the assertion fails and forces a
        deliberate revisit of the bound (and the related plan/PRD
        wording).
        """
        dialog._lead_minutes_field.setValue(999)
        assert dialog._lead_minutes_field.value() == 60

    def test_spinbox_clamps_values_below_min(self, dialog: ReminderFormDialog) -> None:
        """Setting a negative value clamps to 0 (Qt's QSpinBox contract)."""
        dialog._lead_minutes_field.setValue(-5)
        assert dialog._lead_minutes_field.value() == 0

    def test_save_with_lead_zero_persists_zero(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """Default-lead save behaves like S-06: ``start_at = datetime widget``.

        Zero-lead is the degenerate case where event time IS firing
        time. The saved ``Reminder.lead_minutes`` is 0 and the
        ``start_at`` matches the widget value (converted local→UTC) —
        no offset applied.
        """
        dialog._name_field.setText("zero-lead")
        # Pin the spinbox at 0 (sanity — fixture should already give 0).
        dialog._lead_minutes_field.setValue(0)
        local_future = (clock().astimezone() + timedelta(minutes=30)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))

        # Compute the expected UTC value test-side from the same naive
        # local the widget displays, so the assertion holds on any zone.
        local_tz = datetime.now().astimezone().tzinfo
        expected_start_at = local_future.replace(tzinfo=local_tz).astimezone(UTC)

        dialog.accept()

        saved = store.list_all()[0]
        assert saved.lead_minutes == 0
        assert saved.start_at == expected_start_at

    def test_save_with_lead_nonzero_computes_start_at_from_event(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """Non-zero-lead save: widget is event time, ``start_at = event - lead``.

        Pins the S-06b core semantic. With ``lead = 10`` and the user
        picking an event 30 minutes out, the saved firing time
        (``start_at``) lands 20 minutes out — exactly
        ``event - timedelta(minutes=10)``. ``lead_minutes`` is recorded
        verbatim so S-07's Edit dialog can faithfully reconstruct the
        event time.
        """
        dialog._name_field.setText("lead-10")
        dialog._lead_minutes_field.setValue(10)
        local_event = (clock().astimezone() + timedelta(minutes=30)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))

        local_tz = datetime.now().astimezone().tzinfo
        expected_event_at = local_event.replace(tzinfo=local_tz).astimezone(UTC)
        expected_start_at = expected_event_at - timedelta(minutes=10)

        dialog.accept()

        saved = store.list_all()[0]
        assert saved.lead_minutes == 10
        assert saved.start_at == expected_start_at
        # Sanity: the start_at is strictly earlier than the event time.
        assert saved.start_at < expected_event_at

    def test_past_event_with_lead_zero_shows_event_in_future_tooltip(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Zero-lead past-event rejection uses the bare ``_PAST_TIME_MESSAGE``.

        Validation message wording flips on ``lead_minutes``. With
        lead=0, the message is the bare "Event must be in the future"
        constant (no minute count, since none is meaningful).
        """
        calls = _patch_show_text(monkeypatch)
        dialog._name_field.setText("past-zero-lead")
        dialog._lead_minutes_field.setValue(0)
        # 5 minutes BEFORE the frozen clock, in local display zone.
        local_past = (dialog._clock().astimezone() - timedelta(minutes=5)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))

        dialog.accept()

        assert store.list_all() == []
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _PAST_TIME_MESSAGE

    def test_past_event_with_lead_nonzero_shows_lead_specific_tooltip(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-zero-lead past-event rejection interpolates the minute count.

        Event = now + 5 min, lead = 15 min ⇒ start_at = now - 10 min
        (in the past). The tooltip surfaces the specific minute count
        from the spinbox so the user knows whether to push the event
        later or trim the lead.
        """
        calls = _patch_show_text(monkeypatch)
        dialog._name_field.setText("past-with-lead")
        dialog._lead_minutes_field.setValue(15)
        # Event 5 minutes in the future; with lead=15, firing time is
        # 10 minutes in the past — the gate rejects.
        local_event = (dialog._clock().astimezone() + timedelta(minutes=5)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))

        dialog.accept()

        assert store.list_all() == []
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _format_past_time_with_lead(15)
        # Explicit check on the human-readable string so a regression
        # in wording (e.g. dropping the minute count) fails loudly.
        assert "15" in args[1]
        assert "minutes" in args[1]

    def test_past_event_with_lead_one_uses_singular_minute(
        self,
        dialog: ReminderFormDialog,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``lead == 1`` renders ``"1 minute"`` (singular), not ``"1 minutes"``.

        Regression test for the F2 finding in the Phase 1 implementation
        review: the original ``_PAST_TIME_WITH_LEAD_FORMAT`` hard-coded
        the plural ``"minutes"``, producing the ungrammatical "Event must
        be at least 1 minutes in the future" tooltip the moment the user
        stepped the spinbox up to 1. The helper now switches on parity.
        """
        calls = _patch_show_text(monkeypatch)
        dialog._name_field.setText("past-with-lead-one")
        dialog._lead_minutes_field.setValue(1)
        # Event = now (in local display zone); lead=1 ⇒ start_at = now - 1 min
        # (in the past relative to the frozen clock).
        local_event = dialog._clock().astimezone().replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))

        dialog.accept()

        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == "Event must be at least 1 minute in the future"
        # Tripwire: the plural form must NOT appear when lead == 1.
        assert "1 minutes" not in args[1]

    def test_format_past_time_with_lead_pluralizes(self) -> None:
        """Pure-function check of the singular/plural switch on the helper.

        Pinning the helper directly (no dialog spin-up) so both branches
        of the conditional are exercised without depending on the form's
        validation gates. ``lead == 1`` → singular; anything else (2, 60)
        → plural.
        """
        assert _format_past_time_with_lead(1) == "Event must be at least 1 minute in the future"
        assert _format_past_time_with_lead(2) == "Event must be at least 2 minutes in the future"
        assert _format_past_time_with_lead(60) == "Event must be at least 60 minutes in the future"

    def test_atomic_save_tripwire_holds_with_nonzero_lead(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Past-event with non-zero lead must not write to the store.

        Mirrors the S-06 atomic-save tripwire for the new lead-aware
        validation path: a failed validation gates persistence, the
        scheduler, AND the signal. If any of these were to leak past
        the early ``return`` in ``accept()``, this test fails.
        """
        _patch_show_text(monkeypatch)
        dialog._name_field.setText("tripwire")
        dialog._lead_minutes_field.setValue(20)
        local_event = (dialog._clock().astimezone() + timedelta(minutes=5)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))
        received: list[Reminder] = []
        dialog.reminder_added.connect(received.append)

        dialog.accept()

        assert store.list_all() == []
        assert scheduler_stub.reload_calls == 0
        assert received == []
        assert dialog.result() == int(QDialog.DialogCode.Rejected)

    def test_signal_emits_reminder_with_lead_minutes_populated(
        self,
        dialog: ReminderFormDialog,
        clock: Clock,
    ) -> None:
        """The ``reminder_added`` payload carries the configured ``lead_minutes``.

        Connected slots (e.g. the Reminders-tab refresh in
        ``SettingsDialog._refresh_reminders_tab``) receive the saved
        ``Reminder`` and may need to display the lead annotation —
        this test pins that the signal's payload is the populated
        record, not a half-built one.
        """
        dialog._name_field.setText("signal-payload")
        dialog._lead_minutes_field.setValue(25)
        local_event = (clock().astimezone() + timedelta(minutes=60)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))
        received: list[Reminder] = []
        dialog.reminder_added.connect(received.append)

        dialog.accept()

        assert len(received) == 1
        assert received[0].lead_minutes == 25
        assert received[0].name == "signal-payload"


# ---------------------------------------------------------------------------
# S-07: Edit mode
# ---------------------------------------------------------------------------


def _make_edit_dialog(
    qtbot,
    store: ReminderStore,
    scheduler_stub: StubScheduler,
    clock: Clock,
    reminder: Reminder,
) -> ReminderFormDialog:
    """Build a ``ReminderFormDialog`` in Edit mode wired against fixtures."""
    d = ReminderFormDialog(
        store=store,
        scheduler=scheduler_stub,  # type: ignore[arg-type]
        clock=clock,
        reminder=reminder,
    )
    qtbot.addWidget(d)
    return d


class TestReminderFormDialogEditMode:
    """S-07 Edit-mode pre-fill, save dispatch, signal selection, and past-time skip.

    Mode is determined by the ``reminder=`` kwarg: ``None`` → Add
    (covered above); a ``Reminder`` instance → Edit (covered here).
    The Edit flow re-uses the Add validation gates and the same
    accept-order contract; the divergence points are:

    1. Title reads "Edit Reminder".
    2. Fields pre-fill from the loaded reminder (datetime widget shows
       the **event time** = ``start_at + lead_minutes``).
    3. Save calls ``store.update`` (preserving ``id``), not ``store.add``.
    4. ``reminder_updated`` fires; ``reminder_added`` stays silent.
    5. Past-time gate is **skipped** when the firing time hasn't moved
       — lets the user rename / re-lead an already-expired reminder
       without rescheduling it. Moving the firing time back into the
       past still trips the gate.
    """

    def _make_future_reminder(
        self,
        store: ReminderStore,
        clock: Clock,
        *,
        name: str = "Loaded",
        offset_hours: int = 6,
        lead_minutes: int = 5,
    ) -> Reminder:
        """Pre-seed a future ``Reminder`` and return it for Edit-mode loading."""
        reminder = Reminder(
            name=name,
            start_at=clock() + timedelta(hours=offset_hours),
            lead_minutes=lead_minutes,
        )
        store.add(reminder)
        return reminder

    def test_edit_mode_window_title_is_edit_reminder(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """The title flips to "Edit Reminder" when a ``reminder=`` is supplied."""
        reminder = self._make_future_reminder(store, clock)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        assert d.windowTitle() == "Edit Reminder"

    def test_edit_mode_name_field_pre_filled(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """The name field shows the loaded reminder's name verbatim."""
        reminder = self._make_future_reminder(store, clock, name="Doctor visit")
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        assert d._name_field.text() == "Doctor visit"

    def test_edit_mode_lead_field_pre_filled(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """The lead spinbox shows the loaded reminder's ``lead_minutes``."""
        reminder = self._make_future_reminder(store, clock, lead_minutes=20)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        assert d._lead_minutes_field.value() == 20

    def test_edit_mode_datetime_field_pre_filled_to_event_time(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Datetime widget shows ``start_at + lead_minutes`` (the event time, local naive).

        The user's mental model is event-time-first (matches the
        Reminders list's ``_compose_row`` output and the Add-mode UX
        for non-zero lead). Pre-filling with the raw ``start_at``
        would force the user to mentally re-add the lead every time
        they opened Edit.
        """
        reminder = self._make_future_reminder(store, clock, lead_minutes=10)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)

        expected_event_utc = reminder.start_at + timedelta(minutes=reminder.lead_minutes)
        expected_naive_local = expected_event_utc.astimezone().replace(tzinfo=None)
        actual = d._datetime_field.dateTime().toPython()
        assert actual == expected_naive_local

    def test_edit_mode_unchanged_save_preserves_id(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """OK on a pristine Edit dialog re-writes the same row (same ``id``)."""
        reminder = self._make_future_reminder(store, clock)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)

        d.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].id == reminder.id

    def test_edit_mode_unchanged_save_calls_store_update_not_add(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The save path dispatches to ``store.update``; ``store.add`` is never called.

        Tripwire for the mode dispatch in ``accept``. If a regression
        flipped the branch and called ``add()``, the store would end
        up with two rows (duplicate id) and the assertion fails.
        """
        reminder = self._make_future_reminder(store, clock)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)

        update_calls: list[Reminder] = []
        add_calls: list[Reminder] = []

        def _record_update(r: Reminder) -> None:
            update_calls.append(r)

        def _record_add(r: Reminder) -> None:
            add_calls.append(r)

        monkeypatch.setattr(store, "update", _record_update)
        monkeypatch.setattr(store, "add", _record_add)

        d.accept()

        assert len(update_calls) == 1
        assert update_calls[0].id == reminder.id
        assert add_calls == []

    def test_edit_mode_changed_name_persists(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Editing the name and saving overwrites the prior row's name."""
        reminder = self._make_future_reminder(store, clock, name="Old name")
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        d._name_field.setText("New name")

        d.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].id == reminder.id
        assert items[0].name == "New name"

    def test_edit_mode_changed_datetime_persists_new_start_at(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Editing the event time shifts ``start_at`` by the same delta (lead unchanged).

        Lead held at the loaded value (5 min); user picks an event 3
        hours after the original. The saved ``start_at`` must move by
        exactly 3 hours (not 3 hours minus the lead — the lead is
        round-trip metadata that only modulates the event/firing
        relationship).
        """
        reminder = self._make_future_reminder(store, clock, lead_minutes=5)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)

        original_event_utc = reminder.start_at + timedelta(minutes=reminder.lead_minutes)
        new_event_utc = original_event_utc + timedelta(hours=3)
        new_event_naive_local = new_event_utc.astimezone().replace(tzinfo=None)
        d._datetime_field.setDateTime(_qdatetime_from_naive_local(new_event_naive_local))

        d.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].start_at == reminder.start_at + timedelta(hours=3)
        assert items[0].lead_minutes == 5

    def test_edit_mode_changed_lead_persists_new_start_at(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Changing only the lead moves ``start_at`` earlier; event time unchanged.

        Loaded reminder has ``lead == 5``. We bump the lead to 20 (15
        minutes more) without touching the datetime widget. The saved
        ``start_at`` should land 15 minutes earlier; the
        widget-displayed event time is unchanged.
        """
        reminder = self._make_future_reminder(store, clock, lead_minutes=5)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)

        d._lead_minutes_field.setValue(20)  # +15 minutes of lead

        d.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].lead_minutes == 20
        # Event time (start_at + lead) is preserved; therefore start_at
        # is 15 minutes earlier than the loaded reminder's start_at.
        original_event = reminder.start_at + timedelta(minutes=reminder.lead_minutes)
        new_event = items[0].start_at + timedelta(minutes=items[0].lead_minutes)
        assert new_event == original_event
        assert items[0].start_at == reminder.start_at - timedelta(minutes=15)

    def test_edit_mode_save_emits_reminder_updated(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """A successful Edit save emits ``reminder_updated`` with the persisted record."""
        reminder = self._make_future_reminder(store, clock)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        received: list[Reminder] = []
        d.reminder_updated.connect(received.append)

        d.accept()

        assert len(received) == 1
        assert received[0].id == reminder.id

    def test_edit_mode_save_does_not_emit_reminder_added(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Edit mode must NOT fire the Add-mode signal.

        Tripwire for the mode dispatch on the emit branch. If a
        regression collapsed the two signals (or fired both), the
        ``received_added`` list would be non-empty and the assertion
        fails. Mirror of ``test_edit_mode_unchanged_save_calls_store_update_not_add``
        for the signal side.
        """
        reminder = self._make_future_reminder(store, clock)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        received_added: list[Reminder] = []
        d.reminder_added.connect(received_added.append)

        d.accept()

        assert received_added == []

    def test_edit_mode_emit_before_super_accept_ordering(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Mirror of Add's emit-before-super-accept invariant for the Edit signal."""
        reminder = self._make_future_reminder(store, clock)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        captured_result_at_emit: list[int] = []

        def _capture(_reminder: Reminder) -> None:
            captured_result_at_emit.append(d.result())

        d.reminder_updated.connect(_capture)

        d.accept()

        assert captured_result_at_emit == [int(QDialog.DialogCode.Rejected)]
        assert d.result() == int(QDialog.DialogCode.Accepted)

    def test_edit_mode_unchanged_firing_time_skips_past_time_gate(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Editing a now-expired reminder without moving the firing time succeeds.

        Pins the Edit-mode past-time-skip carve-out. A user who saved
        a reminder for "Tuesday 2pm" and then opens Edit on Wednesday
        to rename it should NOT have to also reschedule it — that
        would force them to either pick a fake future time or lose
        the historical name change. The skip predicate is "firing
        time identical to the loaded value"; renaming alone leaves
        the firing time pinned and the gate yields.
        """
        # Pre-seed a reminder, then advance the clock past its firing
        # time so it would fail the gate if the carve-out didn't apply.
        reminder = self._make_future_reminder(
            store, clock, name="Already expired", offset_hours=1, lead_minutes=0
        )
        clock.advance(seconds=2 * 60 * 60)  # advance 2 hours; reminder now 1h in the past
        _patch_show_text(monkeypatch)  # would record a call if gate fired

        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        d._name_field.setText("Renamed")  # change only the name

        d.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].name == "Renamed"
        assert items[0].start_at == reminder.start_at  # firing time unchanged
        assert d.result() == int(QDialog.DialogCode.Accepted)

    def test_edit_mode_changed_datetime_to_past_blocks_save(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Moving the event time INTO the past trips the gate (skip only applies when unchanged).

        Counter-test to the skip carve-out: the moment the user
        actively dials the firing time backwards into the past, the
        gate re-engages. Otherwise the carve-out would be a foot-gun
        ("I can schedule things in the past as long as I claim to be
        editing").
        """
        calls = _patch_show_text(monkeypatch)
        reminder = self._make_future_reminder(store, clock, lead_minutes=0)
        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)

        # Move the event time to 5 minutes BEFORE the clock.
        local_past = (clock().astimezone() - timedelta(minutes=5)).replace(tzinfo=None)
        d._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))

        d.accept()

        # Store still holds the original loaded reminder, byte-identical.
        items = store.list_all()
        assert len(items) == 1
        assert items[0].start_at == reminder.start_at
        assert d.result() == int(QDialog.DialogCode.Rejected)
        # Tooltip surfaced with the bare past-time message (lead == 0).
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _PAST_TIME_MESSAGE

    def test_edit_mode_changed_lead_into_past_blocks_save(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Increasing the lead such that ``start_at`` goes into the past trips the gate.

        Edit-mode counterpart to the Add-mode lead-into-past test.
        Event time stays where it was (3 minutes in the future, well
        inside reach); but the user bumps the lead to 10, which would
        push the firing instant 7 minutes into the past. The lead-
        aware tooltip wording must fire (NOT the bare past-time
        message — the user composed an impossible event+lead pair,
        not a literal past event).
        """
        calls = _patch_show_text(monkeypatch)
        # Reminder with event time only 3 minutes in the future from the
        # clock; loaded lead is 0 so the load-time firing time == event time.
        reminder_start = clock() + timedelta(minutes=3)
        reminder = Reminder(
            name="lead-bump",
            start_at=reminder_start,
            lead_minutes=0,
        )
        store.add(reminder)

        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        # Bump lead to 10: event = now+3, lead=10 → firing = now-7 (past).
        d._lead_minutes_field.setValue(10)

        d.accept()

        items = store.list_all()
        assert len(items) == 1
        assert items[0].start_at == reminder.start_at  # original preserved
        assert items[0].lead_minutes == 0  # original preserved
        assert d.result() == int(QDialog.DialogCode.Rejected)
        # Lead-aware wording (not the bare past-time message).
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _format_past_time_with_lead(10)

    def test_edit_mode_name_validation_still_applies(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Clearing the name in Edit mode trips the empty-name gate just like Add.

        The name gate is shared between Add and Edit (single ``stripped_name``
        check at the top of ``accept``), but the dispatch downstream differs
        (``store.update`` vs ``store.add``, ``reminder_updated`` vs
        ``reminder_added``). This test pins that the gate fires AND nothing
        in the Edit-specific dispatch leaks through on early return — the
        loaded reminder stays byte-identical on disk and ``reminder_updated``
        stays silent.

        Impl-review F1 follow-up: the plan called this test out by name and
        the Add-mode equivalent (``test_empty_name_blocks_save``) doesn't
        exercise the Edit-mode dispatch surface.
        """
        calls = _patch_show_text(monkeypatch)
        reminder = self._make_future_reminder(store, clock, name="Has a name")
        before = store.list_all()

        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        d._name_field.setText("")  # blank out the pre-filled name
        received_updated: list[Reminder] = []
        d.reminder_updated.connect(received_updated.append)

        d.accept()

        # Store byte-identical to the pre-state (no update dispatched).
        assert store.list_all() == before
        assert scheduler_stub.reload_calls == 0
        assert received_updated == []
        assert d.result() == int(QDialog.DialogCode.Rejected)
        # Tooltip surfaced the empty-name message.
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _NAME_EMPTY_MESSAGE

    def test_edit_mode_cancel_does_not_modify_store(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """``reject()`` on an Edit dialog discards every edit without persisting.

        Even after the user has typed a different name, picked a different
        event time, and bumped the lead, ``reject()`` leaves the store
        byte-identical to the pre-state and ``reminder_updated`` silent.
        Mirror of the Add-mode ``test_reject_does_not_persist`` for the
        Edit branch.
        """
        reminder = self._make_future_reminder(store, clock, name="Keep me", lead_minutes=5)
        before = store.list_all()

        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        d._name_field.setText("Would have been renamed")
        new_event = clock().astimezone() + timedelta(hours=12)
        d._datetime_field.setDateTime(_qdatetime_from_naive_local(new_event.replace(tzinfo=None)))
        d._lead_minutes_field.setValue(30)
        received_updated: list[Reminder] = []
        d.reminder_updated.connect(received_updated.append)

        d.reject()

        assert store.list_all() == before
        assert scheduler_stub.reload_calls == 0
        assert received_updated == []
        assert d.result() == int(QDialog.DialogCode.Rejected)

    def test_edit_mode_oserror_on_store_update_blocks_dialog(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``OSError`` from ``store.update`` triggers the atomic-save tripwire.

        Edit-mode counterpart to ``test_oserror_on_store_add_blocks_dialog_and_shows_tooltip``.
        The OSError catch in ``accept`` wraps both ``store.update`` and
        ``store.add`` in the same ``try`` block, but the Edit branch
        (``store.update`` raising) is not covered by the Add-mode test —
        a regression that, e.g., only caught errors from ``add`` would
        slip past until this test fires.

        On failure: scheduler is NOT reloaded, ``reminder_updated`` is
        NOT emitted, dialog stays open (``super().accept()`` skipped),
        tooltip surfaces with the OS-level reason.
        """
        calls = _patch_show_text(monkeypatch)
        reminder = self._make_future_reminder(store, clock)

        def _raise(_reminder: Reminder) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(store, "update", _raise)

        d = _make_edit_dialog(qtbot, store, scheduler_stub, clock, reminder)
        received_updated: list[Reminder] = []
        d.reminder_updated.connect(received_updated.append)

        d.accept()

        assert scheduler_stub.reload_calls == 0
        assert received_updated == []
        assert d.result() == int(QDialog.DialogCode.Rejected)
        # Tooltip surfaced with the OS-level reason.
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert "Permission denied" in args[1]

    def test_add_mode_constructor_still_works_with_reminder_none(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Explicitly passing ``reminder=None`` is equivalent to omitting the kwarg.

        Sanity tripwire for the dispatch default: every Add-mode test
        in this file relies on the kwarg being absent, but the production
        signature reads ``reminder: Reminder | None = None``. A
        regression that, e.g., flipped the default to a sentinel and
        broke the ``is not None`` check at the four dispatch points
        wouldn't show up in any existing test. This test exercises the
        explicit-``None`` form to keep that path honest.
        """
        d = ReminderFormDialog(
            store=store,
            scheduler=scheduler_stub,  # type: ignore[arg-type]
            clock=clock,
            reminder=None,
        )
        qtbot.addWidget(d)

        # Add-mode invariants: Add title, no loaded reminder, fields seed
        # from defaults.
        assert d.windowTitle() == "Add Reminder"
        assert d._editing is None
        assert d._name_field.text() == ""
        assert d._lead_minutes_field.value() == _LEAD_DEFAULT


# ---------------------------------------------------------------------------
# S-08 / FR-014: recurrence picker + cascade
# ---------------------------------------------------------------------------


def _make_edit_dialog_with_reminder(
    qtbot,
    store: ReminderStore,
    scheduler_stub: StubScheduler,
    clock: Clock,
    reminder: Reminder,
) -> ReminderFormDialog:
    """Build an Edit-mode ReminderFormDialog wired against fixtures."""
    d = ReminderFormDialog(
        store=store,
        scheduler=scheduler_stub,  # type: ignore[arg-type]
        clock=clock,
        reminder=reminder,
    )
    qtbot.addWidget(d)
    return d


class TestRecurrencePicker:
    """Picker structure + the recurrence + end-date row cascade."""

    def test_picker_has_four_default_items(self, dialog: ReminderFormDialog) -> None:
        """Add mode: picker carries exactly the four standard labels."""
        items = [
            dialog._recurrence_picker.itemText(i) for i in range(dialog._recurrence_picker.count())
        ]
        assert items == [
            _RECURRENCE_NONE_LABEL,
            _RECURRENCE_DAILY_LABEL,
            _RECURRENCE_WEEKLY_LABEL,
            _RECURRENCE_MONTHLY_LABEL,
        ]

    def test_picker_default_is_none_in_add_mode(self, dialog: ReminderFormDialog) -> None:
        """Picker default text is ``None`` in Add mode (no kwarg)."""
        assert dialog._recurrence_picker.currentText() == _RECURRENCE_NONE_LABEL

    def test_picker_is_enabled_in_add_mode(self, dialog: ReminderFormDialog) -> None:
        """Picker is enabled in Add mode (no custom-locked state)."""
        assert dialog._recurrence_picker.isEnabled() is True

    def test_reset_button_hidden_in_add_mode(self, dialog: ReminderFormDialog) -> None:
        """Reset button is hidden by default; only the custom-locked path surfaces it."""
        assert dialog._recurrence_reset_button.isVisible() is False

    def test_end_date_checkbox_disabled_when_picker_is_none(
        self, dialog: ReminderFormDialog
    ) -> None:
        """One-shot reminder has no series end → checkbox disabled."""
        assert dialog._end_date_checkbox.isEnabled() is False

    def test_end_date_field_disabled_when_checkbox_unchecked(
        self, dialog: ReminderFormDialog
    ) -> None:
        """Date field follows the checkbox state (default unchecked)."""
        assert dialog._end_date_field.isEnabled() is False

    def test_end_date_checkbox_enables_when_picker_set_to_daily(
        self, dialog: ReminderFormDialog
    ) -> None:
        """Switching to Daily enables the end-date checkbox via the cascade."""
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        assert dialog._end_date_checkbox.isEnabled() is True

    @pytest.mark.parametrize(
        "label",
        [_RECURRENCE_DAILY_LABEL, _RECURRENCE_WEEKLY_LABEL, _RECURRENCE_MONTHLY_LABEL],
    )
    def test_end_date_checkbox_enables_for_each_recurring_choice(
        self, dialog: ReminderFormDialog, label: str
    ) -> None:
        """Every non-None standard choice enables the end-date checkbox."""
        dialog._recurrence_picker.setCurrentText(label)
        assert dialog._end_date_checkbox.isEnabled() is True

    def test_end_date_field_enables_when_checkbox_ticked(self, dialog: ReminderFormDialog) -> None:
        """Picker → Daily, tick checkbox → field enabled."""
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        dialog._end_date_checkbox.setChecked(True)
        assert dialog._end_date_field.isEnabled() is True

    def test_picker_back_to_none_disables_end_date_row(self, dialog: ReminderFormDialog) -> None:
        """Recurring → None → checkbox unticks AND disables; field disables."""
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        dialog._end_date_checkbox.setChecked(True)
        assert dialog._end_date_field.isEnabled() is True
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_NONE_LABEL)
        assert dialog._end_date_checkbox.isChecked() is False
        assert dialog._end_date_checkbox.isEnabled() is False
        assert dialog._end_date_field.isEnabled() is False

    def test_monthly_day31_tooltip_appears_when_start_day_above_28(
        self, dialog: ReminderFormDialog, clock: Clock
    ) -> None:
        """Monthly + day-31 datetime → tooltip surfaces on the picker."""
        local_event = (clock().astimezone() + timedelta(days=60)).replace(tzinfo=None)
        local_event = local_event.replace(day=31, hour=10, minute=0, second=0, microsecond=0)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_MONTHLY_LABEL)
        assert dialog._recurrence_picker.toolTip() == _MONTHLY_DAY31_TOOLTIP

    def test_monthly_day28_or_below_does_not_show_tooltip(
        self, dialog: ReminderFormDialog, clock: Clock
    ) -> None:
        """Monthly + day-15 datetime → no skip-months tooltip."""
        local_event = (clock().astimezone() + timedelta(days=60)).replace(tzinfo=None)
        local_event = local_event.replace(day=15, hour=10, minute=0, second=0, microsecond=0)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_MONTHLY_LABEL)
        assert dialog._recurrence_picker.toolTip() == ""

    def test_monthly_tooltip_clears_when_picker_changes_away_from_monthly(
        self, dialog: ReminderFormDialog, clock: Clock
    ) -> None:
        """Day-31 + Monthly → Weekly clears the tooltip."""
        local_event = (clock().astimezone() + timedelta(days=60)).replace(tzinfo=None)
        local_event = local_event.replace(day=31, hour=10, minute=0, second=0, microsecond=0)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_MONTHLY_LABEL)
        assert dialog._recurrence_picker.toolTip() == _MONTHLY_DAY31_TOOLTIP
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_WEEKLY_LABEL)
        assert dialog._recurrence_picker.toolTip() == ""

    def test_monthly_tooltip_appears_when_datetime_changes_to_day31_with_picker_on_monthly(
        self, dialog: ReminderFormDialog, clock: Clock
    ) -> None:
        """F5 fix: tooltip refresh wires through the datetime change path too."""
        local_event = (clock().astimezone() + timedelta(days=60)).replace(tzinfo=None)
        local_event = local_event.replace(day=15, hour=10, minute=0, second=0, microsecond=0)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_MONTHLY_LABEL)
        assert dialog._recurrence_picker.toolTip() == ""
        local_event_31 = local_event.replace(day=31)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event_31))
        assert dialog._recurrence_picker.toolTip() == _MONTHLY_DAY31_TOOLTIP

    def test_monthly_tooltip_clears_when_datetime_drops_below_day29_with_picker_on_monthly(
        self, dialog: ReminderFormDialog, clock: Clock
    ) -> None:
        """F5 fix: tooltip clears when day drops below the threshold."""
        local_event = (clock().astimezone() + timedelta(days=60)).replace(tzinfo=None)
        local_event = local_event.replace(day=31, hour=10, minute=0, second=0, microsecond=0)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_MONTHLY_LABEL)
        assert dialog._recurrence_picker.toolTip() == _MONTHLY_DAY31_TOOLTIP
        local_event_15 = local_event.replace(day=15)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_event_15))
        assert dialog._recurrence_picker.toolTip() == ""


class TestRecurrenceTranslationHelpers:
    """Pure-function coverage for the picker/RRULE helpers."""

    def test_picker_choice_to_rrule_none_label_returns_none(self) -> None:
        """``None`` label → ``None`` (one-shot encoding)."""
        assert _picker_choice_to_rrule(_RECURRENCE_NONE_LABEL) is None

    def test_picker_choice_to_rrule_daily_returns_freq_daily(self) -> None:
        """``Daily`` label → canonical RRULE string."""
        assert _picker_choice_to_rrule(_RECURRENCE_DAILY_LABEL) == _RRULE_DAILY

    def test_picker_choice_to_rrule_weekly_returns_freq_weekly(self) -> None:
        """``Weekly`` label → canonical RRULE string."""
        assert _picker_choice_to_rrule(_RECURRENCE_WEEKLY_LABEL) == _RRULE_WEEKLY

    def test_picker_choice_to_rrule_monthly_returns_freq_monthly(self) -> None:
        """``Monthly`` label → canonical RRULE string."""
        assert _picker_choice_to_rrule(_RECURRENCE_MONTHLY_LABEL) == _RRULE_MONTHLY

    def test_picker_choice_to_rrule_unknown_raises_keyerror(self) -> None:
        """``(custom)`` is not in the forward map (callers route around it)."""
        with pytest.raises(KeyError):
            _picker_choice_to_rrule(_RECURRENCE_CUSTOM_LABEL)

    def test_rrule_to_picker_choice_none_returns_none_label(self) -> None:
        """``None`` rrule_str → ``None`` picker label."""
        assert _rrule_to_picker_choice(None) == _RECURRENCE_NONE_LABEL

    @pytest.mark.parametrize(
        ("rrule_str", "expected_label"),
        [
            (_RRULE_DAILY, _RECURRENCE_DAILY_LABEL),
            (_RRULE_WEEKLY, _RECURRENCE_WEEKLY_LABEL),
            (_RRULE_MONTHLY, _RECURRENCE_MONTHLY_LABEL),
        ],
    )
    def test_rrule_to_picker_choice_canonical_round_trips(
        self, rrule_str: str, expected_label: str
    ) -> None:
        """Each canonical RRULE reverse-translates to its picker label."""
        assert _rrule_to_picker_choice(rrule_str) == expected_label

    def test_rrule_to_picker_choice_advanced_falls_through_to_custom(self) -> None:
        """Hand-edited advanced RRULEs fall through to ``(custom)``."""
        assert _rrule_to_picker_choice("FREQ=WEEKLY;BYDAY=MO,WE,FR") == _RECURRENCE_CUSTOM_LABEL

    def test_rrule_to_picker_choice_empty_string_falls_through_to_custom(self) -> None:
        """Empty-string rrule_str falls through to ``(custom)`` (not None)."""
        assert _rrule_to_picker_choice("") == _RECURRENCE_CUSTOM_LABEL

    def test_local_date_to_utc_end_of_day_returns_aware_utc(self) -> None:
        """Conversion produces a tz-aware UTC datetime at 23:59:59 local."""
        picked = date(2026, 7, 31)
        result = _local_date_to_utc_end_of_day(picked)
        assert result.tzinfo == UTC
        # Round-trip back to local → date and time match the inputs.
        local = result.astimezone()
        assert local.date() == picked
        assert local.time() == time(23, 59, 59)

    def test_format_no_future_occurrences_with_lead_singular(self) -> None:
        """``lead == 1`` renders the singular ``"1 minute"`` form."""
        assert (
            _format_no_future_occurrences_with_lead(1)
            == "Recurring reminder has no future firings at least 1 minute away"
        )

    def test_format_no_future_occurrences_with_lead_plural(self) -> None:
        """``lead != 1`` renders the plural ``"N minutes"`` form."""
        assert (
            _format_no_future_occurrences_with_lead(15)
            == "Recurring reminder has no future firings at least 15 minutes away"
        )


def _populate_valid_for_recurrence(
    dialog: ReminderFormDialog, clock: Clock, *, name: str = "Test"
) -> None:
    """Fill the form with a valid name + a future datetime (30 min ahead)."""
    dialog._name_field.setText(name)
    local_future = (clock().astimezone() + timedelta(minutes=30)).replace(tzinfo=None)
    dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_future))


class TestRecurrenceSave:
    """Forward translation: picker + end-date → persisted Reminder."""

    def test_save_with_picker_none_persists_rrule_str_none(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Picker None + checkbox unchecked → saved rrule_str/end_at are None."""
        _populate_valid_for_recurrence(dialog, clock)
        dialog.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str is None
        assert saved.end_at is None

    def test_save_with_picker_daily_persists_freq_daily(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Picker Daily → rrule_str == ``FREQ=DAILY``."""
        _populate_valid_for_recurrence(dialog, clock)
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        dialog.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str == _RRULE_DAILY

    def test_save_with_picker_weekly_persists_freq_weekly(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Picker Weekly → rrule_str == ``FREQ=WEEKLY``."""
        _populate_valid_for_recurrence(dialog, clock)
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_WEEKLY_LABEL)
        dialog.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str == _RRULE_WEEKLY

    def test_save_with_picker_monthly_persists_freq_monthly(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Picker Monthly → rrule_str == ``FREQ=MONTHLY``."""
        _populate_valid_for_recurrence(dialog, clock)
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_MONTHLY_LABEL)
        dialog.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str == _RRULE_MONTHLY

    def test_save_with_end_date_unticked_persists_end_at_none(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Daily + checkbox unticked → end_at is None."""
        _populate_valid_for_recurrence(dialog, clock)
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        dialog._end_date_checkbox.setChecked(False)
        dialog.accept()
        saved = store.list_all()[0]
        assert saved.end_at is None

    def test_save_with_end_date_ticked_persists_end_at_at_local_eod_in_utc(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Daily + ticked end-date 7 days out → end_at == 23:59:59 local in UTC."""
        _populate_valid_for_recurrence(dialog, clock)
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        picked_local_date = (clock().astimezone() + timedelta(days=7)).date()
        dialog._end_date_field.setDate(
            QDate(picked_local_date.year, picked_local_date.month, picked_local_date.day)
        )
        dialog._end_date_checkbox.setChecked(True)
        dialog.accept()
        saved = store.list_all()[0]
        assert saved.end_at is not None
        assert saved.end_at.tzinfo == UTC
        local = saved.end_at.astimezone()
        assert local.date() == picked_local_date
        assert local.time() == time(23, 59, 59)

    def test_save_with_picker_none_ignores_end_date_state(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """Defensive: even if checkbox is somehow checked, picker None → end_at None."""
        _populate_valid_for_recurrence(dialog, clock)
        # Force the checkbox into a logically-impossible state via the
        # API (the cascade would normally clear it, but the accept()
        # branch defends against it anyway).
        dialog._end_date_checkbox.setEnabled(True)
        dialog._end_date_checkbox.setChecked(True)
        # Sanity: picker is still None.
        assert dialog._recurrence_picker.currentText() == _RECURRENCE_NONE_LABEL
        dialog.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str is None
        assert saved.end_at is None


class TestRecurrenceEditMode:
    """Reverse translation: loaded Reminder → pre-filled picker + end-date."""

    def _seed_recurring(
        self,
        store: ReminderStore,
        clock: Clock,
        *,
        name: str = "Loaded",
        rrule_str: str | None = None,
        end_at: datetime | None = None,
        offset_hours: int = 6,
        lead_minutes: int = 0,
    ) -> Reminder:
        """Persist a reminder with the requested recurrence shape."""
        reminder = Reminder(
            name=name,
            start_at=clock() + timedelta(hours=offset_hours),
            rrule_str=rrule_str,
            end_at=end_at,
            lead_minutes=lead_minutes,
        )
        store.add(reminder)
        return reminder

    def test_edit_mode_pre_fills_picker_to_none_for_one_shot(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """Loaded one-shot (rrule_str=None) → picker shows ``None``."""
        reminder = self._seed_recurring(store, clock, rrule_str=None)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        assert d._recurrence_picker.currentText() == _RECURRENCE_NONE_LABEL

    def test_edit_mode_pre_fills_picker_to_daily_for_freq_daily(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """``FREQ=DAILY`` → picker pre-fills to ``Daily``."""
        reminder = self._seed_recurring(store, clock, rrule_str=_RRULE_DAILY)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        assert d._recurrence_picker.currentText() == _RECURRENCE_DAILY_LABEL

    @pytest.mark.parametrize(
        ("rrule_str", "expected_label"),
        [
            (_RRULE_WEEKLY, _RECURRENCE_WEEKLY_LABEL),
            (_RRULE_MONTHLY, _RECURRENCE_MONTHLY_LABEL),
        ],
    )
    def test_edit_mode_pre_fills_picker_to_weekly_and_monthly(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        rrule_str: str,
        expected_label: str,
    ) -> None:
        """Canonical weekly + monthly RRULEs round-trip into the picker."""
        reminder = self._seed_recurring(store, clock, rrule_str=rrule_str)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        assert d._recurrence_picker.currentText() == expected_label

    def test_edit_mode_pre_fills_end_date_checkbox_when_end_at_set(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """Loaded reminder with end_at → checkbox checked, field enabled with that date."""
        end_at_local_date = (clock().astimezone() + timedelta(days=10)).date()
        end_at_utc = _local_date_to_utc_end_of_day(end_at_local_date)
        reminder = self._seed_recurring(store, clock, rrule_str=_RRULE_DAILY, end_at=end_at_utc)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        assert d._end_date_checkbox.isChecked() is True
        assert d._end_date_field.isEnabled() is True
        actual_picked = d._end_date_field.date().toPython()
        assert actual_picked == end_at_local_date

    def test_edit_mode_no_end_at_leaves_checkbox_unchecked(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """Loaded reminder with end_at=None → checkbox unchecked, field disabled."""
        reminder = self._seed_recurring(store, clock, rrule_str=_RRULE_DAILY, end_at=None)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        assert d._end_date_checkbox.isChecked() is False
        assert d._end_date_field.isEnabled() is False

    def test_edit_mode_recurrence_round_trips_through_save_load_save(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """End-to-end: Add Daily + end-date → reopen Edit → no-op save preserves bytes."""
        # First save: Add a Daily reminder with an end-date.
        d1 = ReminderFormDialog(
            store=store,
            scheduler=scheduler_stub,  # type: ignore[arg-type]
            clock=clock,
        )
        qtbot.addWidget(d1)
        _populate_valid_for_recurrence(d1, clock, name="Round-trip")
        d1._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        picked_local = (clock().astimezone() + timedelta(days=10)).date()
        d1._end_date_field.setDate(QDate(picked_local.year, picked_local.month, picked_local.day))
        d1._end_date_checkbox.setChecked(True)
        d1.accept()

        first_saved = store.list_all()[0]
        assert first_saved.rrule_str == _RRULE_DAILY
        assert first_saved.end_at is not None

        # Re-open in Edit mode: picker pre-fills + end-date matches.
        d2 = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, first_saved)
        assert d2._recurrence_picker.currentText() == _RECURRENCE_DAILY_LABEL
        assert d2._end_date_checkbox.isChecked() is True
        assert d2._end_date_field.date().toPython() == picked_local

        # No-op save: same bytes.
        d2.accept()
        second_saved = store.list_all()[0]
        assert second_saved.rrule_str == first_saved.rrule_str
        assert second_saved.end_at == first_saved.end_at
        assert second_saved.id == first_saved.id


_CUSTOM_RRULE = "FREQ=WEEKLY;BYDAY=MO,WE,FR"


def _patch_question_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub QMessageBox.question so it returns Yes without showing a dialog."""
    monkeypatch.setattr(
        "break_reminder.ui.reminder_form_dialog.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )


def _patch_question_no(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub QMessageBox.question so it returns No without showing a dialog."""
    monkeypatch.setattr(
        "break_reminder.ui.reminder_form_dialog.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )


class TestRecurrenceCustomLocked:
    """Edit mode on a hand-edited rrule_str: lock + Reset flow."""

    def _seed_custom(
        self,
        store: ReminderStore,
        clock: Clock,
        *,
        rrule_str: str = _CUSTOM_RRULE,
        end_at: datetime | None = None,
    ) -> Reminder:
        """Persist a reminder with a non-mappable rrule_str."""
        reminder = Reminder(
            name="Custom-locked",
            start_at=clock() + timedelta(hours=6),
            rrule_str=rrule_str,
            end_at=end_at,
        )
        store.add(reminder)
        return reminder

    def test_custom_rrule_pre_fills_picker_to_custom(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """Loaded custom rule → picker shows ``(custom)``, disabled, with tooltip."""
        reminder = self._seed_custom(store, clock)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        assert d._recurrence_picker.currentText() == _RECURRENCE_CUSTOM_LABEL
        assert d._recurrence_picker.isEnabled() is False
        assert d._recurrence_picker.toolTip() == _RECURRENCE_CUSTOM_TOOLTIP

    def test_custom_rrule_shows_reset_button(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """Custom-locked load → Reset button is visible."""
        reminder = self._seed_custom(store, clock)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        # ``isVisible`` on a never-shown dialog returns False; we
        # assert via the explicit visibility flag instead.
        assert d._recurrence_reset_button.isHidden() is False

    def test_save_without_reset_preserves_custom_rrule_str(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """No-change save on custom-locked → rrule_str byte-for-byte preserved."""
        reminder = self._seed_custom(store, clock)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        d._name_field.setText("Renamed only")
        d.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str == _CUSTOM_RRULE
        assert saved.name == "Renamed only"

    def test_save_after_reset_yes_uses_picker_translation(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reset → Yes → setCurrentText(Daily) → save persists ``FREQ=DAILY``."""
        _patch_question_yes(monkeypatch)
        reminder = self._seed_custom(store, clock)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        d._on_recurrence_reset_clicked()
        # After Reset Yes, picker enabled at None.
        assert d._recurrence_picker.isEnabled() is True
        assert d._recurrence_picker.currentText() == _RECURRENCE_NONE_LABEL
        # Now switch to Daily and save.
        d._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        d.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str == _RRULE_DAILY

    def test_reset_no_preserves_state(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reset → No → state untouched; save still preserves the custom rule."""
        _patch_question_no(monkeypatch)
        reminder = self._seed_custom(store, clock)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        d._on_recurrence_reset_clicked()
        assert d._recurrence_picker.currentText() == _RECURRENCE_CUSTOM_LABEL
        assert d._recurrence_picker.isEnabled() is False
        assert d._recurrence_reset_button.isHidden() is False
        assert d._original_custom_rrule == _CUSTOM_RRULE

    def test_reset_yes_hides_button_and_enables_picker(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reset → Yes → Reset button hides, picker enables, original cleared."""
        _patch_question_yes(monkeypatch)
        reminder = self._seed_custom(store, clock)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        d._on_recurrence_reset_clicked()
        assert d._recurrence_reset_button.isHidden() is True
        assert d._recurrence_picker.isEnabled() is True
        assert d._original_custom_rrule is None
        # ``(custom)`` removed from the dropdown.
        labels = [d._recurrence_picker.itemText(i) for i in range(d._recurrence_picker.count())]
        assert _RECURRENCE_CUSTOM_LABEL not in labels

    def test_custom_locked_with_end_at_preserves_end_at_on_no_op_save(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """F1 fix: custom-locked + end_at → no-op save preserves end_at byte-for-byte."""
        end_at_local_date = (clock().astimezone() + timedelta(days=14)).date()
        end_at_utc = _local_date_to_utc_end_of_day(end_at_local_date)
        reminder = self._seed_custom(store, clock, end_at=end_at_utc)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        # No-op save (no field changes).
        d.accept()
        saved = store.list_all()[0]
        assert saved.end_at == end_at_utc
        assert saved.rrule_str == _CUSTOM_RRULE

    def test_custom_locked_end_date_field_remains_enabled(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """F1 fix: custom-locked + end_at → cascade leaves checkbox+field enabled."""
        end_at_local_date = (clock().astimezone() + timedelta(days=14)).date()
        end_at_utc = _local_date_to_utc_end_of_day(end_at_local_date)
        reminder = self._seed_custom(store, clock, end_at=end_at_utc)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        assert d._end_date_checkbox.isChecked() is True
        assert d._end_date_checkbox.isEnabled() is True
        assert d._end_date_field.isEnabled() is True


class TestRecurrencePastTimeGate:
    """Recurrence-aware past-time gate. One-shot branch unchanged."""

    def test_recurring_with_past_start_but_future_occurrence_saves(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Daily + past start_at → save succeeds (next firing = +1 day, future)."""
        dialog._name_field.setText("Daily past")
        local_past = (clock().astimezone() - timedelta(days=2)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        dialog.accept()
        assert dialog.result() == int(QDialog.DialogCode.Accepted)
        saved = store.list_all()[0]
        assert saved.rrule_str == _RRULE_DAILY

    def test_recurring_with_past_end_at_blocks_save(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Daily + past start + past end_at → save blocked with no-future-firings tooltip."""
        calls = _patch_show_text(monkeypatch)
        dialog._name_field.setText("Doomed")
        local_past = (clock().astimezone() - timedelta(days=5)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        # End-date in the past too.
        end_local = (clock().astimezone() - timedelta(days=1)).date()
        dialog._end_date_field.setDate(QDate(end_local.year, end_local.month, end_local.day))
        dialog._end_date_checkbox.setChecked(True)
        dialog.accept()
        assert store.list_all() == []
        assert dialog.result() == int(QDialog.DialogCode.Rejected)
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _NO_FUTURE_OCCURRENCES_MESSAGE

    def test_one_shot_past_time_still_blocked_with_existing_message(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Picker None + past datetime → existing past-time tooltip; nothing persisted."""
        calls = _patch_show_text(monkeypatch)
        dialog._name_field.setText("One-shot past")
        local_past = (clock().astimezone() - timedelta(hours=1)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))
        # Picker stays at None (default).
        dialog.accept()
        assert store.list_all() == []
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _PAST_TIME_MESSAGE

    def test_edit_mode_skip_applies_when_all_three_unchanged(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """Loaded expired one-shot, change name only → save succeeds (skip)."""
        # Pre-seed an expired one-shot (start_at in the past relative
        # to the clock — pre-seed the store directly so this isn't
        # blocked by the form's own gate).
        expired = Reminder(
            name="Expired",
            start_at=clock() - timedelta(hours=2),
            rrule_str=None,
        )
        store.add(expired)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, expired)
        d._name_field.setText("Renamed expired")
        d.accept()
        assert d.result() == int(QDialog.DialogCode.Accepted)
        saved = store.list_all()[0]
        assert saved.name == "Renamed expired"
        assert saved.start_at == expired.start_at

    def test_edit_mode_skip_does_not_apply_when_rrule_changed(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
    ) -> None:
        """Daily reminder loaded; switch picker to Weekly → gate evaluates new rule."""
        # Future Daily reminder — gate should pass for both Daily and
        # Weekly because the new rule still has future occurrences.
        # The point is to prove the gate runs (not skipped) when the
        # rrule changes; we verify by checking the saved rrule_str.
        reminder = Reminder(
            name="Daily-to-weekly",
            start_at=clock() + timedelta(hours=2),
            rrule_str=_RRULE_DAILY,
        )
        store.add(reminder)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        d._recurrence_picker.setCurrentText(_RECURRENCE_WEEKLY_LABEL)
        d.accept()
        saved = store.list_all()[0]
        assert saved.rrule_str == _RRULE_WEEKLY

    def test_edit_mode_skip_does_not_apply_when_end_at_changed(
        self,
        qtbot,
        store: ReminderStore,
        scheduler_stub: StubScheduler,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Loaded Daily; user moves end_at to yesterday → gate fires."""
        calls = _patch_show_text(monkeypatch)
        # Loaded Daily with start_at in the past (so the past-time
        # branch would apply if the gate triggered as one-shot).
        future_end = _local_date_to_utc_end_of_day(
            (clock().astimezone() + timedelta(days=30)).date()
        )
        reminder = Reminder(
            name="EndDateChange",
            start_at=clock() - timedelta(days=2),
            rrule_str=_RRULE_DAILY,
            end_at=future_end,
        )
        store.add(reminder)
        d = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, reminder)
        # Move end_at to yesterday.
        yesterday = (clock().astimezone() - timedelta(days=1)).date()
        d._end_date_field.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        # Checkbox already checked (from pre-fill).
        d.accept()
        # Saved bytes unchanged from pre-state.
        saved = store.list_all()[0]
        assert saved.end_at == future_end  # original preserved
        assert d.result() == int(QDialog.DialogCode.Rejected)
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _NO_FUTURE_OCCURRENCES_MESSAGE

    def test_recurring_with_lead_no_future_uses_lead_aware_message(
        self,
        dialog: ReminderFormDialog,
        store: ReminderStore,
        clock: Clock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Daily + past + past end_at + lead=15 → lead-aware tooltip."""
        calls = _patch_show_text(monkeypatch)
        dialog._name_field.setText("Lead doomed")
        local_past = (clock().astimezone() - timedelta(days=5)).replace(tzinfo=None)
        dialog._datetime_field.setDateTime(_qdatetime_from_naive_local(local_past))
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        end_local = (clock().astimezone() - timedelta(days=1)).date()
        dialog._end_date_field.setDate(QDate(end_local.year, end_local.month, end_local.day))
        dialog._end_date_checkbox.setChecked(True)
        dialog._lead_minutes_field.setValue(15)
        dialog.accept()
        assert store.list_all() == []
        assert len(calls) == 1
        args, _kwargs = calls[0]
        assert args[1] == _format_no_future_occurrences_with_lead(15)
        assert "15" in args[1]


class TestRecurrenceEndDate:
    """End-date defaults + local→UTC round-trip + storage round-trip."""

    def test_end_date_field_default_offset_is_30_days(
        self, dialog: ReminderFormDialog, clock: Clock
    ) -> None:
        """Add mode: end-date field default == today + 30 days in system local."""
        expected = (clock().astimezone() + timedelta(days=_END_DATE_DEFAULT_OFFSET_DAYS)).date()
        actual = dialog._end_date_field.date().toPython()
        assert actual == expected

    def test_end_date_local_to_utc_conversion(
        self, dialog: ReminderFormDialog, store: ReminderStore, clock: Clock
    ) -> None:
        """Picked date X → saved end_at == 23:59:59 local on X, in UTC."""
        _populate_valid_for_recurrence(dialog, clock)
        dialog._recurrence_picker.setCurrentText(_RECURRENCE_DAILY_LABEL)
        picked_local = (clock().astimezone() + timedelta(days=14)).date()
        dialog._end_date_field.setDate(
            QDate(picked_local.year, picked_local.month, picked_local.day)
        )
        dialog._end_date_checkbox.setChecked(True)
        dialog.accept()
        saved = store.list_all()[0]
        # Recompute the expected UTC value test-side so it's correct on
        # any CI runner zone.
        expected_naive_local = datetime.combine(picked_local, time(23, 59, 59))
        local_tz = datetime.now().astimezone().tzinfo
        expected_utc = expected_naive_local.replace(tzinfo=local_tz).astimezone(UTC)
        assert saved.end_at == expected_utc

    def test_end_date_round_trips_through_storage(
        self, qtbot, store: ReminderStore, scheduler_stub: StubScheduler, clock: Clock
    ) -> None:
        """Save with end-date → reopen Edit → checkbox + field match."""
        d1 = ReminderFormDialog(
            store=store,
            scheduler=scheduler_stub,  # type: ignore[arg-type]
            clock=clock,
        )
        qtbot.addWidget(d1)
        _populate_valid_for_recurrence(d1, clock, name="EndDateRT")
        d1._recurrence_picker.setCurrentText(_RECURRENCE_WEEKLY_LABEL)
        picked_local = (clock().astimezone() + timedelta(days=21)).date()
        d1._end_date_field.setDate(QDate(picked_local.year, picked_local.month, picked_local.day))
        d1._end_date_checkbox.setChecked(True)
        d1.accept()
        first_saved = store.list_all()[0]
        d2 = _make_edit_dialog_with_reminder(qtbot, store, scheduler_stub, clock, first_saved)
        assert d2._end_date_checkbox.isChecked() is True
        assert d2._end_date_field.date().toPython() == picked_local
