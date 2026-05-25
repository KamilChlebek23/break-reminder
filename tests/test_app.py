"""Integration tests for ``BreakReminderApp``.

Focused on the shared break-outcome handlers and the tray menu wiring.

Covers:
  * ``_apply_break_taken`` — the code path used by both the dialog's
    "I'll take a break" branch and the tray Reset action. Must reset
    the active-time counter, clear the snooze cap, and write a TAKEN
    row to the FR-015 event log.
  * ``_apply_break_snoozed`` — mirror handler for the SNOOZED branch.
    Must increment ``snoozes_used``, set a ``_snooze_until`` window,
    and write a SNOOZED row.
  * Tray menu — must contain a "Reset" entry whose triggered signal
    reaches the same code path as ``_apply_break_taken``.

The fixture wires the app against a tmp directory and a ``FakeVoice``
stub so the suite never spins up a pyttsx3 thread pool or writes into
the user's real %APPDATA% directory. ``BreakReminderApp.start()`` is
deliberately NOT called — it would arm the 1-second QTimer and the
pynput listeners, neither of which we want fighting the test harness.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from break_reminder.app import BreakReminderApp
from break_reminder.storage.event_log import EventLog
from break_reminder.storage.reminders import ReminderStore
from break_reminder.storage.settings import Settings


class FakeVoice:
    """Stand-in for ``VoiceNotifier`` — same surface, no thread pool.

    The app uses ``speak``, ``stop``, ``shutdown``; the dialog uses just
    ``stop``. None of the tests below trigger those paths, but the type
    has to satisfy the production signature in case a future test does.
    """

    def __init__(self) -> None:
        """Construct the stub with empty / zeroed call counters."""
        self.spoken: list[str] = []
        self.stop_calls = 0
        self.shutdown_calls = 0

    def speak(self, phrase: str) -> None:
        """Record a ``speak()`` invocation by appending ``phrase`` to ``spoken``."""
        self.spoken.append(phrase)

    def stop(self) -> None:
        """Record one ``stop()`` invocation by incrementing ``stop_calls``."""
        self.stop_calls += 1

    def shutdown(self) -> None:
        """Record one ``shutdown()`` invocation by incrementing ``shutdown_calls``."""
        self.shutdown_calls += 1


@pytest.fixture
def app(qapp: QApplication, tmp_path: Path) -> BreakReminderApp:
    """A ``BreakReminderApp`` wired entirely to ``tmp_path``."""
    settings = Settings(ini_path=tmp_path / "BreakReminder.ini")
    event_log = EventLog(path=tmp_path / "events.csv")
    reminder_store = ReminderStore(path=tmp_path / "reminders.json")
    voice = FakeVoice()

    return BreakReminderApp(
        qt_app=qapp,
        settings=settings,
        event_log=event_log,
        reminder_store=reminder_store,
        voice=voice,  # type: ignore[arg-type]  # FakeVoice satisfies the duck-typed contract
    )


def _read_event_rows(path: Path) -> list[dict[str, str]]:
    """Read the FR-015 event log as a list of {column: value} dicts."""
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Shared handler — covers the dialog flow AND the Reset action
# ---------------------------------------------------------------------------


class TestApplyBreakTaken:
    """The shared TAKEN handler — used by the dialog flow AND the Reset action."""

    def test_clears_active_seconds_counter(self, app: BreakReminderApp) -> None:
        """``_apply_break_taken`` resets the active-time counter to 0."""
        # Pre-load some accumulated time so the reset is observable.
        app._break_scheduler._active_seconds = 42

        app._apply_break_taken()

        assert app._break_scheduler._active_seconds == 0

    def test_clears_snooze_cap(self, app: BreakReminderApp) -> None:
        """``_apply_break_taken`` clears any consumed snooze count."""
        # Simulate a prior snooze having consumed the cap.
        app._break_scheduler._snoozes_used = 3

        app._apply_break_taken()

        assert app._break_scheduler._snoozes_used == 0

    def test_clears_snooze_window(self, app: BreakReminderApp) -> None:
        """``_apply_break_taken`` clears any in-flight snooze-until window."""
        from datetime import UTC, datetime, timedelta

        app._break_scheduler._snooze_until = datetime.now(UTC) + timedelta(minutes=5)

        app._apply_break_taken()

        assert app._break_scheduler._snooze_until is None

    def test_writes_taken_row_to_event_log(self, app: BreakReminderApp, tmp_path: Path) -> None:
        """``_apply_break_taken`` writes a single ``break/taken`` row to FR-015."""
        app._apply_break_taken()

        rows = _read_event_rows(tmp_path / "events.csv")
        assert len(rows) == 1
        assert rows[0]["event_type"] == "break"
        assert rows[0]["outcome"] == "taken"

    def test_clears_active_break_dialog_reference(self, app: BreakReminderApp) -> None:
        """A dangling dialog reference is cleared so the next cycle gets a fresh one."""
        # If a dialog reference is dangling (e.g. user clicked Reset
        # while one was open), the handler must clear it so the next
        # break_due fires a fresh dialog instead of trying to raise the
        # stale one.
        app._active_break_dialog = object()  # type: ignore[assignment]  # any non-None sentinel

        app._apply_break_taken()

        assert app._active_break_dialog is None

    def test_re_arms_the_scheduler_timer(self, app: BreakReminderApp) -> None:
        """The handler re-arms the per-second tick after ``break_due`` stopped it."""
        # The dialog flow stops the timer when break_due fires; the
        # handler is responsible for re-arming it for the next cycle.
        app._break_scheduler.stop()
        assert not app._break_scheduler._timer.isActive()

        app._apply_break_taken()

        assert app._break_scheduler._timer.isActive()

    def test_does_not_change_pause_state(self, app: BreakReminderApp) -> None:
        """FR-016: Reset / Take must NOT flip the pause toggle."""
        # FR-016: pause is independent of the break cycle. Reset / Take
        # must not flip the pause toggle.
        app._break_scheduler.pause()
        assert app._break_scheduler.is_paused

        app._apply_break_taken()

        assert app._break_scheduler.is_paused


class TestApplyBreakSnoozed:
    """The shared SNOOZED handler — mirror of ``_apply_break_taken``."""

    def test_increments_snoozes_used(self, app: BreakReminderApp) -> None:
        """``_apply_break_snoozed`` increments ``_snoozes_used`` by exactly 1."""
        app._apply_break_snoozed()
        assert app._break_scheduler._snoozes_used == 1

    def test_sets_snooze_window(self, app: BreakReminderApp) -> None:
        """``_apply_break_snoozed`` sets a non-``None`` ``_snooze_until`` window."""
        app._apply_break_snoozed()
        assert app._break_scheduler._snooze_until is not None

    def test_writes_snoozed_row_to_event_log(self, app: BreakReminderApp, tmp_path: Path) -> None:
        """``_apply_break_snoozed`` writes a single ``break/snoozed`` row to FR-015."""
        app._apply_break_snoozed()

        rows = _read_event_rows(tmp_path / "events.csv")
        assert len(rows) == 1
        assert rows[0]["event_type"] == "break"
        assert rows[0]["outcome"] == "snoozed"

    def test_clears_active_break_dialog_reference(self, app: BreakReminderApp) -> None:
        """A dangling dialog reference is cleared on the SNOOZED branch too."""
        app._active_break_dialog = object()  # type: ignore[assignment]
        app._apply_break_snoozed()
        assert app._active_break_dialog is None

    def test_re_arms_the_scheduler_timer(self, app: BreakReminderApp) -> None:
        """The handler re-arms the per-second tick on the SNOOZED branch too."""
        app._break_scheduler.stop()
        app._apply_break_snoozed()
        assert app._break_scheduler._timer.isActive()


# ---------------------------------------------------------------------------
# Tray menu — Reset action wiring
# ---------------------------------------------------------------------------


def _find_action(app: BreakReminderApp, text: str) -> QAction:
    """Locate a tray-menu QAction by exact label."""
    menu = app._tray.contextMenu()
    assert menu is not None, "tray context menu was not built"
    for action in menu.actions():
        if action.text() == text:
            return action
    raise LookupError(f"No tray action labelled {text!r}")


class TestTrayMenuWiring:
    """Tray menu entries and their wiring (FR-004 + Reset addition)."""

    def test_reset_action_exists(self, app: BreakReminderApp) -> None:
        """The tray context menu contains a 'Reset' action."""
        assert _find_action(app, "Reset") is not None

    def test_reset_action_appears_after_take_break_now(self, app: BreakReminderApp) -> None:
        """'Reset' appears immediately after 'Take break now' (functional siblings)."""
        # The PRD update places Reset right after "Take break now". Position
        # matters because the two are functionally siblings — keeping them
        # adjacent avoids confusing users who scan the menu top-to-bottom.
        menu = app._tray.contextMenu()
        assert menu is not None
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        take_idx = labels.index("Take break now")
        reset_idx = labels.index("Reset")
        assert reset_idx == take_idx + 1

    def test_take_break_now_still_present(self, app: BreakReminderApp) -> None:
        """Reset is additive — 'Take break now' is NOT replaced (PRD tripwire)."""
        # Reset is additive — it must NOT have replaced "Take break now".
        # The PRD revision keeps both intentionally; this test is the
        # tripwire if a future agent ever decides to "clean up" the menu.
        assert _find_action(app, "Take break now") is not None

    def test_reset_triggers_apply_break_taken(self, app: BreakReminderApp, tmp_path: Path) -> None:
        """Triggering Reset has the same observable effects as ``_apply_break_taken``."""
        app._break_scheduler._active_seconds = 30
        app._break_scheduler._snoozes_used = 1

        _find_action(app, "Reset").trigger()

        # All three observable side effects of _apply_break_taken should
        # be in place after a Reset click.
        assert app._break_scheduler._active_seconds == 0
        assert app._break_scheduler._snoozes_used == 0
        rows = _read_event_rows(tmp_path / "events.csv")
        assert len(rows) == 1
        assert rows[0]["outcome"] == "taken"


# ---------------------------------------------------------------------------
# Tray icon — clock face rendered programmatically (FR-004)
# ---------------------------------------------------------------------------


class TestTrayIcon:
    """Tray icon — the QPainter-rendered clock face (FR-004)."""

    def test_icon_is_set(self, app: BreakReminderApp) -> None:
        """The tray icon is set to a non-null ``QIcon`` (regression tripwire)."""
        # If a future refactor accidentally drops the _build_tray_icon
        # call, the tray would silently show a blank icon. Tripwire.
        assert not app._tray.icon().isNull()

    def test_icon_has_renderable_size(self, app: BreakReminderApp) -> None:
        """The tray icon reports a renderable ``actualSize`` for the tray request."""
        # QIcon.actualSize is what Qt would actually paint at the tray
        # request size. A non-null icon with zero actual size means we
        # set something but Qt can't render it.
        from PySide6.QtCore import QSize

        actual = app._tray.icon().actualSize(QSize(32, 32))
        assert actual.width() > 0
        assert actual.height() > 0


# ---------------------------------------------------------------------------
# Open settings… action — wires to the FR-005 / FR-006 settings dialog
# ---------------------------------------------------------------------------


class TestOpenSettingsAction:
    """Triggering 'Open settings…' constructs the new ``SettingsDialog``.

    These tests substitute ``break_reminder.app.SettingsDialog`` with a
    stub class so the slot's call is observable without spinning up a
    real modal dialog. Patching the imported symbol (rather than the
    class's ``__init__`` / ``exec``) keeps the stub free of Qt internals
    and makes the assertions purely about the wiring contract.
    """

    @staticmethod
    def _make_stub(captures: list[dict]) -> type:
        """Return a stub class that records init kwargs and exec calls into ``captures``."""

        class _StubSettingsDialog:
            def __init__(self, **kwargs: object) -> None:
                captures.append({"init_kwargs": kwargs, "exec_called": False})

            def exec(self) -> int:
                captures[-1]["exec_called"] = True
                return 0

        return _StubSettingsDialog

    def test_action_constructs_and_execs_settings_dialog(
        self, app: BreakReminderApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Triggering the action constructs a ``SettingsDialog`` and calls ``exec`` once."""
        captures: list[dict] = []
        monkeypatch.setattr("break_reminder.app.SettingsDialog", self._make_stub(captures))

        _find_action(app, "Open settings…").trigger()

        assert len(captures) == 1
        assert captures[0]["exec_called"] is True

    def test_dialog_receives_app_settings_instance(
        self, app: BreakReminderApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dialog is constructed with the app's own ``Settings`` instance."""
        # Identity check — not equality. If a future refactor accidentally
        # constructs a duplicate Settings(), the dialog would write into
        # a different QSettings handle and the user's edits would not be
        # observable to the running scheduler.
        captures: list[dict] = []
        monkeypatch.setattr("break_reminder.app.SettingsDialog", self._make_stub(captures))

        _find_action(app, "Open settings…").trigger()

        assert captures[0]["init_kwargs"]["settings"] is app._settings

    def test_dialog_receives_app_voice_instance(
        self, app: BreakReminderApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dialog is constructed with the app's own ``VoiceNotifier`` instance.

        Identity check — same rationale as ``test_dialog_receives_app_settings_instance``.
        If a future refactor accidentally constructs a fresh
        ``VoiceNotifier()`` for the dialog, the Test-voice button would
        speak through a different ``pyttsx3`` worker pool than the one
        the break / reminder events use, and a user who tested the
        phrase successfully might still hear nothing on the next break.
        """
        captures: list[dict] = []
        monkeypatch.setattr("break_reminder.app.SettingsDialog", self._make_stub(captures))

        _find_action(app, "Open settings…").trigger()

        assert captures[0]["init_kwargs"]["voice"] is app._voice

    def test_action_no_longer_shows_placeholder_message_box(
        self, app: BreakReminderApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The placeholder ``QMessageBox.information`` path is dead.

        Tripwire: if a future agent re-introduces the placeholder code
        path (e.g., as a fallback when the dialog fails to construct),
        this test fires and forces a deliberate decision rather than a
        silent regression to the v0.1.0 stub UX.
        """
        from PySide6.QtWidgets import QMessageBox

        info_calls: list[None] = []

        def _record_info(*args: object, **kwargs: object) -> object:
            info_calls.append(None)
            return None

        monkeypatch.setattr(QMessageBox, "information", _record_info)
        captures: list[dict] = []
        monkeypatch.setattr("break_reminder.app.SettingsDialog", self._make_stub(captures))

        _find_action(app, "Open settings…").trigger()

        assert info_calls == []

    def test_left_click_on_tray_also_opens_settings(
        self, app: BreakReminderApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A left-click activation goes through the same slot (FR-004 wiring)."""
        # The Trigger activation reason is what _on_tray_activated routes
        # to _on_open_settings — keep both paths covered so a future
        # change to either doesn't silently drop the left-click affordance.
        from PySide6.QtWidgets import QSystemTrayIcon

        captures: list[dict] = []
        monkeypatch.setattr("break_reminder.app.SettingsDialog", self._make_stub(captures))

        app._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)

        assert len(captures) == 1
        assert captures[0]["exec_called"] is True
