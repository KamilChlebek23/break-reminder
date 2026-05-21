"""Shared pytest fixtures.

Storage-layer tests touch ``QSettings`` (which needs at least a
``QCoreApplication``). Dialog tests touch ``QWidget`` subclasses (which
need a full ``QApplication``). pytest-qt provides the latter via its
session-scoped ``qapp`` fixture; depending on it as autouse keeps every
test in a known-good Qt state without per-test setup.

Re-creating Qt application instances within the same Python process is
known to misbehave, so a single session-scoped instance is the only
correct shape here.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _qt_app(qapp: QApplication) -> QApplication:
    """Force pytest-qt's QApplication into existence for every test."""
    return qapp
