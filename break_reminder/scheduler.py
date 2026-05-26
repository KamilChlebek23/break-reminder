"""Schedulers — active-time break engine (FR-008) + RRULE recurrence (FR-014).

Two cooperating schedulers live here. They're independent — the break
scheduler doesn't know about custom reminders and vice versa — so changes
to one rarely touch the other.

``BreakScheduler``
    Implements FR-008's "count only active user time" rule. Listens to
    ``ActivityMonitor.activity_detected`` to keep a ``last_input_at``
    timestamp, ticks once per second, and increments an active-time
    counter only while the user is non-idle (``idle < idle_threshold``).
    When the counter crosses ``break_interval_min * 60``, emits
    ``break_due``. Snooze (FR-010) and pause (FR-016) gate firings.

``ReminderScheduler``
    Implements FR-014 by parsing each reminder's RRULE string with
    ``dateutil.rrule``, finding the next firing, and arming
    ``QTimer.singleShot``. Re-arms after every fire. Reminders without
    an RRULE fire exactly once at their ``start_at``.

Both schedulers emit signals; they don't show UI directly. ``app.py``
wires the signals to the appropriate dialog.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dateutil.rrule import rrulestr
from PySide6.QtCore import QObject, QTimer, Signal

from break_reminder.activity import ActivityMonitor
from break_reminder.storage.reminders import Reminder, ReminderStore
from break_reminder.storage.settings import Settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Module-level real-clock helper. The default ``BreakScheduler`` clock."""
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Break scheduler (FR-008 / FR-010 / FR-016)
# ---------------------------------------------------------------------------


class BreakScheduler(QObject):
    """Active-time accumulation + break firing."""

    break_due = Signal(int)  # snooze_remaining at the time of firing

    TICK_MS = 1000

    def __init__(
        self,
        *,
        settings: Settings,
        activity: ActivityMonitor,
        parent: QObject | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Wire the scheduler to its settings, activity source, and clock.

        Args:
            settings: ``Settings`` instance whose ``break_interval_min`` /
                ``snooze_duration_min`` / ``idle_threshold_sec`` /
                ``max_snoozes`` are read every tick.
            activity: ``ActivityMonitor`` whose ``activity_detected``
                signal is connected to refresh ``last_input_at``.
            parent: Optional Qt parent.
            clock: Optional injectable ``datetime``-returning callable
                for deterministic tests. Defaults to UTC ``datetime.now``.
        """
        super().__init__(parent)
        self._settings = settings
        self._activity = activity
        # Clock is injectable so tests can drive ``_tick`` deterministically
        # without waiting for real wall-clock seconds. Production passes
        # ``None`` and gets ``datetime.now(UTC)``.
        self._clock = clock or _utcnow

        self._active_seconds = 0
        self._last_input_at: datetime = self._clock()
        self._snoozes_used = 0
        self._snooze_until: datetime | None = None
        self._paused = settings.paused

        self._activity.activity_detected.connect(self._on_activity)

        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        """Arm the per-second tick. Idempotent."""
        self._timer.start()

    def stop(self) -> None:
        """Disarm the per-second tick. Idempotent."""
        self._timer.stop()

    @property
    def seconds_until_break(self) -> int:
        """How many active seconds remain before the next firing.

        Used by the tray-icon tooltip (FR-004). Returns 0 when paused or
        when a break is currently due.
        """
        if self._paused:
            return 0
        threshold = self._settings.break_interval_min * 60
        return max(0, threshold - self._active_seconds)

    @property
    def seconds_until_snooze_end(self) -> int | None:
        """How many wall-clock seconds remain in the active snooze window.

        Used by the tray-icon tooltip (FR-004) to render
        ``BreakReminder — snooze time left Xm YYs`` while a snooze is
        open. Independent of pause: the tooltip layer is responsible for
        gating on ``is_paused`` first.

        Returns:
            ``None`` when no snooze is active or the window has already
            elapsed (so the tooltip flips back to the regular countdown
            the moment the snooze ends, even before the next 1-second
            ``_tick()`` clears ``_snooze_until``). Otherwise the number
            of whole seconds remaining, rounded up so a fractional 0.4s
            still displays as "0m 01s" (avoids a 1-second flicker
            through "0m 00s" before this property returns ``None``).
        """
        if self._snooze_until is None:
            return None
        remaining = (self._snooze_until - self._clock()).total_seconds()
        if remaining <= 0:
            return None
        return math.ceil(remaining)

    # ---- user-facing controls ------------------------------------------

    def pause(self) -> None:
        """Halt active-time accumulation and persist the paused flag (FR-016)."""
        self._paused = True
        self._settings.paused = True

    def resume(self) -> None:
        """Resume active-time accumulation and clear the paused flag (FR-016)."""
        self._paused = False
        self._settings.paused = False

    @property
    def is_paused(self) -> bool:
        """Return ``True`` while ``pause()`` is in effect (FR-016)."""
        return self._paused

    def on_break_taken(self) -> None:
        """User clicked 'I'll take a break' — reset the cycle."""
        self._active_seconds = 0
        self._snoozes_used = 0
        self._snooze_until = None

    def on_break_snoozed(self) -> None:
        """User clicked 'Snooze' — defer the next firing."""
        self._snoozes_used += 1
        self._snooze_until = self._clock() + timedelta(minutes=self._settings.snooze_duration_min)
        # Counter stays at threshold so the next fire happens as soon as
        # the snooze expires, regardless of activity.
        self._active_seconds = self._settings.break_interval_min * 60

    # ---- internals ------------------------------------------------------

    def _on_activity(self, when: datetime) -> None:
        self._last_input_at = when

    def _tick(self) -> None:
        if self._paused:
            return

        now = self._clock()
        snap = self._settings.snapshot()

        # Honor snooze: don't fire while the snooze window is open.
        if self._snooze_until is not None:
            if now < self._snooze_until:
                return
            self._snooze_until = None  # snooze expired; fall through

        idle = (now - self._last_input_at).total_seconds()
        if idle < snap.idle_threshold_sec:
            self._active_seconds += 1

        threshold = snap.break_interval_min * 60
        if self._active_seconds >= threshold:
            snooze_remaining = max(0, snap.max_snoozes - self._snoozes_used)
            self.break_due.emit(snooze_remaining)
            # The slot is responsible for resetting via on_break_taken /
            # on_break_snoozed. We do NOT reset here; otherwise the dialog
            # would race with re-firing if it took >1s to display.
            self._timer.stop()


# ---------------------------------------------------------------------------
# Custom-reminder scheduler (FR-013 / FR-014)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReminderFiring:
    """The next reminder due, with its computed UTC firing time."""

    reminder_id: str
    fire_at: datetime


class ReminderScheduler(QObject):
    """RRULE-driven custom-reminder firing."""

    reminder_due = Signal(str)  # reminder name

    def __init__(
        self,
        *,
        store: ReminderStore,
        parent: QObject | None = None,
    ) -> None:
        """Wire the scheduler to its reminder store and a single-shot QTimer.

        Args:
            store: ``ReminderStore`` whose ``list_all()`` is consulted on
                every reload.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._store = store
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer)
        self._next: _ReminderFiring | None = None

    def start(self) -> None:
        """Compute the next firing and arm the timer."""
        self.reload()

    def stop(self) -> None:
        """Disarm the timer and forget the pending firing."""
        self._timer.stop()
        self._next = None

    def reload(self) -> None:
        """Recompute next firing across all reminders. Call on add/edit/delete."""
        self._timer.stop()
        self._next = self._compute_next()
        if self._next is None:
            return
        ms = max(0, int((self._next.fire_at - datetime.now(UTC)).total_seconds() * 1000))
        # QTimer.start has a 32-bit ms limit (~24.8 days). Reminders further
        # out than that get a daily wakeup that re-checks.
        self._timer.start(min(ms, 24 * 60 * 60 * 1000))

    # ---- internals ------------------------------------------------------

    def _on_timer(self) -> None:
        if self._next is None:
            return
        now = datetime.now(UTC)
        if now < self._next.fire_at:
            # Daily-wakeup case: not actually due yet, just rearm.
            self.reload()
            return
        self._fire(self._next.reminder_id)
        self.reload()

    def _fire(self, reminder_id: str) -> None:
        reminder = next((r for r in self._store.list_all() if r.id == reminder_id), None)
        if reminder is None:
            return
        self.reminder_due.emit(reminder.name)

    def _compute_next(self) -> _ReminderFiring | None:
        now = datetime.now(UTC)
        candidates: list[_ReminderFiring] = []
        for reminder in self._store.list_all():
            fire_at = next_firing_after(reminder, now)
            if fire_at is not None:
                candidates.append(_ReminderFiring(reminder.id, fire_at))
        if not candidates:
            return None
        return min(candidates, key=lambda c: c.fire_at)


def next_firing_after(reminder: Reminder, now: datetime) -> datetime | None:
    """Return the next firing strictly after ``now``, or ``None`` if exhausted.

    Pure function so it's trivially testable without a Qt event loop.
    """
    start = _ensure_aware(reminder.start_at)
    end = _ensure_aware(reminder.end_at) if reminder.end_at else None

    if reminder.rrule_str is None:
        if start > now:
            return start
        return None

    try:
        rule = rrulestr(reminder.rrule_str, dtstart=start)
    except Exception:  # noqa: BLE001 — corrupt RRULE shouldn't crash the scheduler
        logger.exception("invalid RRULE for reminder %s", reminder.id)
        return None

    nxt = rule.after(now, inc=False)
    if nxt is None:
        return None
    nxt = _ensure_aware(nxt)
    if end is not None and nxt > end:
        return None
    return nxt


def _ensure_aware(dt: datetime) -> datetime:
    """Treat naive datetimes as UTC. Reminder data may be stored either way."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
