"""Global keyboard / mouse activity hook (FR-008).

The PRD says "count only active user time, not wall-clock". To know whether
the user is active, we need an OS-wide hook — Qt only sees input directed
at our own windows. ``pynput`` provides cross-platform listeners that run
on their own internal threads.

The threading constraint is: **never touch a Qt widget from a pynput
listener thread**. We work around that with the standard Qt pattern — a
``QObject`` exposing a signal. Qt's ``AutoConnection`` marshals the signal
emission back to the GUI thread automatically, so the listener thread can
``emit()`` freely without race conditions.

The listeners are non-blocking: ``Listener.start()`` spins them up and
returns. They keep a daemon thread alive for the lifetime of the process,
so we shut them down explicitly on app quit (``stop()``) to avoid the
process hanging on exit.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class ActivityMonitor(QObject):
    """Emits ``activity_detected`` whenever the user touches keyboard or mouse."""

    activity_detected = Signal(object)  # carries a ``datetime`` (UTC, tz-aware)

    def __init__(self, parent: QObject | None = None) -> None:
        """Construct an idle ``ActivityMonitor``; call ``start()`` to begin listening.

        Args:
            parent: Optional Qt parent for ownership / cleanup.
        """
        super().__init__(parent)
        self._kb_listener = None
        self._mouse_listener = None

    def start(self) -> None:
        """Start the global hooks. Idempotent."""
        if self._kb_listener is not None or self._mouse_listener is not None:
            return
        try:
            from pynput import keyboard, mouse
        except ImportError:
            logger.exception("pynput unavailable; activity tracking disabled")
            return

        # All four callbacks emit the same way; the listener thread is
        # the one calling this — Qt marshals the signal across.
        def _emit(*_: object) -> None:
            self.activity_detected.emit(datetime.now(UTC))

        try:
            self._kb_listener = keyboard.Listener(on_press=_emit, on_release=_emit)
            self._mouse_listener = mouse.Listener(on_move=_emit, on_click=_emit, on_scroll=_emit)
            self._kb_listener.start()
            self._mouse_listener.start()
        except Exception:  # noqa: BLE001 — pynput can fail in headless / sandboxed envs
            logger.exception("failed to start pynput listeners")
            self.stop()

    def stop(self) -> None:
        """Stop the global hooks. Safe to call multiple times."""
        for listener_attr in ("_kb_listener", "_mouse_listener"):
            listener = getattr(self, listener_attr)
            if listener is not None:
                try:
                    listener.stop()
                except Exception:  # noqa: BLE001
                    logger.exception("failed to stop %s", listener_attr)
                setattr(self, listener_attr, None)
