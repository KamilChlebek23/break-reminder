"""Shared pytest fixtures and helpers.

Storage-layer tests touch ``QSettings`` (which needs at least a
``QCoreApplication``). Dialog tests touch ``QWidget`` subclasses (which
need a full ``QApplication``). pytest-qt provides the latter via its
session-scoped ``qapp`` fixture; depending on it as autouse keeps every
test in a known-good Qt state without per-test setup.

Re-creating Qt application instances within the same Python process is
known to misbehave, so a single session-scoped instance is the only
correct shape here.

This module also owns the canonical ``Clock`` test helper — a mutable
callable time source consumed by the scheduler suites and the form-
dialog suite. Each consuming test file keeps its **own** ``clock``
fixture local because epochs diverge (scheduler tests pin
``2026-05-20 06:00 UTC``; the form-dialog suite pins
``2026-05-20 17:23:45 UTC`` deliberately off a quarter-hour boundary
to exercise the form's +1h rounding tests). Only the class is shared
here; the per-file fixture wiring encodes per-suite intent.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication


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
