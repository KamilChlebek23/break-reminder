"""Shared pytest fixtures and helpers.

Storage-layer tests touch ``QSettings`` (which needs at least a
``QCoreApplication``). Dialog tests touch ``QWidget`` subclasses (which
need a full ``QApplication``). pytest-qt provides the latter via its
session-scoped ``qapp`` fixture; depending on it as autouse keeps every
test in a known-good Qt state without per-test setup.

Re-creating Qt application instances within the same Python process is
known to misbehave, so a single session-scoped instance is the only
correct shape here.

This module also owns the canonical ``Clock`` test helper and a shared
function-scoped fixture set used across the integration / e2e tiers
(Phase 1 R-1, Phase 2 R-2, Phase 4 R-4). The fixtures bind to
``tmp_path`` so each test gets an isolated storage root; they are
deliberately function-scoped (not module/session) so cross-suite state
never leaks.

Two intentional non-conftest exceptions to the lift:

- **The form-dialog suite (``tests/test_reminder_form_dialog.py``) keeps
  its own ``clock`` fixture local.** It pins ``2026-05-20 17:23:45 UTC``
  deliberately off a quarter-hour boundary to exercise the form's +1h
  rounding tests; lifting it here would force every consumer onto that
  epoch.
- **The voice notifier stub (``tests/test_app.py:FakeVoice``) stays
  local.** It carries call-counter attributes (``spoken``,
  ``stop_calls``, ``shutdown_calls``) the conftest no-op ``FakeVoice``
  does not, because ``tests/test_app.py`` asserts on those counts. The
  no-op conftest version below is for tests that need a voice notifier
  to satisfy a constructor but never assert on it.

Lift table (research.md §F): A1-A6 mirror the Phase 1/2 integration
files' duplicated locals (``clock``, ``store_path``, ``store``,
``settings``, ``voice`` + ``FakeVoice``, ``reminder_scheduler``);
B1-B4 are net-new (``activity``, ``break_scheduler``, ``event_log``,
``break_reminder_app``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtWidgets import QApplication

from break_reminder.activity import ActivityMonitor
from break_reminder.app import BreakReminderApp
from break_reminder.notifications.voice import VoiceNotifier
from break_reminder.scheduler import BreakScheduler, ReminderScheduler
from break_reminder.storage.event_log import EventLog
from break_reminder.storage.reminders import ReminderStore
from break_reminder.storage.settings import Settings


@pytest.fixture(scope="session", autouse=True)
def _qt_app(qapp: QApplication) -> QApplication:
    """Force pytest-qt's QApplication into existence for every test."""
    return qapp


class Clock:
    """Mutable, controllable time source for scheduler / form-dialog tests.

    Behaves as a zero-arg callable returning the current ``_now`` value
    (a tz-aware ``datetime`` if the caller seeded one, otherwise naive).
    ``advance(seconds)`` pushes ``_now`` forward by the given number of
    real-time seconds, letting tests drive ``_on_timer`` / ``_tick``
    deterministically without sleeping the test runner.
    """

    def __init__(self, start: datetime) -> None:
        """Pin the clock at ``start``; subsequent calls return that value until advanced.

        Args:
            start: The instant the clock initially reports. Pass a
                tz-aware ``datetime`` (typically UTC) for scheduler
                tests; naive values are accepted but propagate to
                consumers as-is.
        """
        self._now = start

    def __call__(self) -> datetime:
        """Return the clock's current ``_now`` value.

        Returns:
            The instant the clock currently reports. Identity-equal to
            the most recent ``start`` or post-``advance`` value — no
            timezone coercion is applied.
        """
        return self._now

    def advance(self, seconds: float) -> None:
        """Advance the clock forward by ``seconds`` real-time seconds.

        Args:
            seconds: Number of seconds to add to ``_now``. Accepts
                floats for sub-second deltas; passing zero is a no-op.
        """
        self._now += timedelta(seconds=seconds)


class FakeVoice:
    """Sibling stub of ``test_break_dialog.FakeVoice`` for ``SettingsDialog``'s ``VoiceNotifier`` param.

    Not a literal mirror: ``test_break_dialog.FakeVoice`` only exposes
    ``stop()`` + a ``stop_calls`` counter (BreakDialog's narrow
    ``_VoiceController`` Protocol), while this stub additionally
    implements ``speak()`` because ``SettingsDialog``'s Voice tab can
    call it. ``SettingsDialog`` does not exercise either method just to
    build the widget tree (the Voice tab reads phrase / enabled state
    from ``Settings``, not from the notifier), so a no-op stub is
    sufficient for any consumer that just needs a voice notifier
    instance — we never trigger a voice-tab interaction.

    ``tests/test_app.py`` keeps its own ``FakeVoice`` because it asserts
    on call counters this no-op version intentionally lacks.
    """

    def stop(self) -> None:
        """No-op ``stop()`` recorded only for protocol compatibility."""

    def speak(self, phrase: str) -> None:
        """No-op ``speak()`` recorded only for protocol compatibility.

        Args:
            phrase: Ignored — no consumer of this stub triggers voice output.
        """


# ---------------------------------------------------------------------------
# Lift A1-A6: shared by R-1 (Phase 1) and R-2 (Phase 2); reused by R-4 (Phase 4)
# ---------------------------------------------------------------------------


@pytest.fixture
def clock() -> Clock:
    """A ``Clock`` pinned at 2026-05-20 06:00 UTC for deterministic time math.

    Same epoch as the scheduler unit-test suites
    (``test_reminder_scheduler.py``, ``test_break_scheduler.py``) and
    Phase 1/2 of the test-plan rollout — keeps cross-suite integration
    math addressing the same instant. The form-dialog suite pins a
    different epoch (``17:23:45 UTC`` off a quarter-hour boundary, by
    design) and so keeps its own ``clock`` local.
    """
    return Clock(datetime(2026, 5, 20, 6, 0, tzinfo=UTC))


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Path to a per-test ``reminders.json`` file under ``tmp_path``."""
    return tmp_path / "reminders.json"


@pytest.fixture
def store(store_path: Path) -> ReminderStore:
    """A ``ReminderStore`` bound to the per-test ``store_path``."""
    return ReminderStore(path=store_path)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A ``Settings`` instance bound to a per-test INI file under ``tmp_path``."""
    return Settings(ini_path=tmp_path / "BreakReminder.ini")


@pytest.fixture
def voice() -> FakeVoice:
    """A no-op ``FakeVoice`` stub for any consumer that needs a voice notifier."""
    return FakeVoice()


@pytest.fixture
def reminder_scheduler(store: ReminderStore, clock: Clock) -> ReminderScheduler:
    """A ``ReminderScheduler`` wired against the in-test store + injected clock.

    Named ``reminder_scheduler`` (not just ``scheduler``) for
    disambiguation against ``break_scheduler`` below — both schedulers
    are routinely needed in the same e2e test (Flow B uses
    ``reminder_scheduler`` indirectly via ``SettingsDialog`` and
    ``break_scheduler`` directly).
    """
    return ReminderScheduler(store=store, clock=clock)


# ---------------------------------------------------------------------------
# Lift B1-B4: net-new for R-4 (Phase 4); useful for any future wired-app e2e
# ---------------------------------------------------------------------------


@pytest.fixture
def activity() -> ActivityMonitor:
    """An ``ActivityMonitor`` with no listeners started.

    ``ActivityMonitor.start()`` spins up pynput keyboard + mouse
    listener threads; tests drive ``activity_detected`` synthetically
    via ``emit()`` from the test thread, so the listeners stay
    dormant. ``stop()`` on an un-started monitor is a no-op
    (``activity.py:69-78``); no teardown needed.
    """
    return ActivityMonitor()


@pytest.fixture
def break_scheduler(settings: Settings, activity: ActivityMonitor, clock: Clock) -> BreakScheduler:
    """A ``BreakScheduler`` wired against in-test settings, activity, and clock.

    The 1Hz ``QTimer`` at ``scheduler.py:96-98`` is constructed but
    NOT started (the fixture omits the ``start()`` call). Tests drive
    ``_tick()`` directly per the test-plan §7 "No deep Qt-internals
    mocking" convention.
    """
    return BreakScheduler(settings=settings, activity=activity, clock=clock)


@pytest.fixture
def event_log(tmp_path: Path) -> EventLog:
    """An ``EventLog`` bound to a per-test CSV file under ``tmp_path``.

    Note: ``EventLog.record`` uses real wall-clock at ``event_log.py:66``
    (no ``clock=`` injection seam exists — STRUCTURAL #2 in research.md
    §F is deferred). Tests that oracle on this fixture's CSV rows must
    assert on ``(event_type, outcome, detail)`` tuples, NOT on
    ``timestamp_iso``.
    """
    return EventLog(path=tmp_path / "events.log")


@pytest.fixture
def break_reminder_app(
    qapp: QApplication,
    settings: Settings,
    event_log: EventLog,
    store: ReminderStore,
    voice: FakeVoice,
    clock: Clock,
) -> BreakReminderApp:
    """A fully wired ``BreakReminderApp`` for Flow D e2e (Phase 4).

    Constructs the wired app with all four injected collaborators plus
    the ``clock=`` kwarg added in Phase 1 (STRUCTURAL #1 fix), so the
    internal ``BreakScheduler`` / ``ReminderScheduler`` instances run
    on virtual time. The fixture deliberately does NOT call
    ``app.start()`` — that would spin up pynput listeners and arm the
    1Hz ``QTimer``, racing the test's deterministic ``_tick()``
    invocations (STRUCTURAL #3 in research.md §F).

    The app holds no resources requiring shutdown when ``start()``
    wasn't called, so teardown is a no-op. The internal collaborators
    (``app._activity``, ``app._break_scheduler``,
    ``app._reminder_scheduler``) are NOT the conftest ``activity`` /
    ``break_scheduler`` / ``reminder_scheduler`` fixture instances —
    the app constructs its own at ``app.py:102-104``.
    """
    return BreakReminderApp(
        qt_app=qapp,
        settings=settings,
        event_log=event_log,
        reminder_store=store,
        voice=cast(VoiceNotifier, voice),
        clock=cast(Callable[[], datetime], clock),
    )
