"""Tests for ``SettingsDialog`` — the FR-005 / FR-006 settings window.

Covers the load / save / cancel contract in isolation, without showing
the dialog (no ``exec()``, no event loop pumping). Each test gets a
``tmp_path``-bound ``Settings`` instance so the suite never touches the
real ``%APPDATA%`` location, mirroring the pattern in
``tests/test_settings.py``.

Layout invariants are also asserted as tripwires — if a future slice
silently flattens the ``QTabWidget`` or re-labels the "Scheduling" tab,
the affected tests fail loudly instead of letting the layout drift
unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QSpinBox, QTabWidget

from break_reminder.storage.settings import (
    DEFAULT_BREAK_INTERVAL_MIN,
    Settings,
)
from break_reminder.ui.settings_dialog import SettingsDialog


@pytest.fixture
def ini_path(tmp_path: Path) -> Path:
    """Path to a per-test INI file under ``tmp_path``."""
    return tmp_path / "BreakReminder.ini"


@pytest.fixture
def settings(ini_path: Path) -> Settings:
    """A ``Settings`` instance bound to the per-test ``ini_path`` fixture."""
    return Settings(ini_path=ini_path)


@pytest.fixture
def dialog(qtbot, settings: Settings) -> SettingsDialog:
    """A ``SettingsDialog`` wired against the per-test ``settings`` fixture.

    Registered with ``qtbot.addWidget`` so the dialog is destroyed at
    test teardown regardless of test outcome — matches the convention
    in ``tests/test_break_dialog.py``.
    """
    d = SettingsDialog(settings=settings)
    qtbot.addWidget(d)
    return d


# ---------------------------------------------------------------------------
# Load — initial state matches Settings + bounds enforce FR-006
# ---------------------------------------------------------------------------


class TestLoad:
    """Initial dialog state reflects the injected ``Settings`` and FR-006 bounds."""

    def test_spinbox_initial_value_is_default_on_fresh_settings(
        self, dialog: SettingsDialog
    ) -> None:
        """Spinbox shows ``DEFAULT_BREAK_INTERVAL_MIN`` on a fresh INI."""
        assert dialog._break_interval_spinbox.value() == DEFAULT_BREAK_INTERVAL_MIN

    def test_spinbox_initial_value_reflects_pre_set_value(self, qtbot, ini_path: Path) -> None:
        """Spinbox shows whatever ``Settings.break_interval_min`` already holds."""
        pre_set = Settings(ini_path=ini_path)
        pre_set.break_interval_min = 45
        del pre_set

        d = SettingsDialog(settings=Settings(ini_path=ini_path))
        qtbot.addWidget(d)

        assert d._break_interval_spinbox.value() == 45

    def test_spinbox_minimum_is_one(self, dialog: SettingsDialog) -> None:
        """FR-006 lower bound is enforced at the widget level."""
        # Tripwire: if a future agent loosens the lower bound, the
        # Settings setter's ValueError path becomes reachable from the
        # dialog and the no-try/except design assumption breaks.
        assert dialog._break_interval_spinbox.minimum() == 1

    def test_spinbox_maximum_is_240(self, dialog: SettingsDialog) -> None:
        """FR-006 upper bound is enforced at the widget level."""
        # Tripwire: if a future agent loosens the upper bound, the
        # Settings setter's ValueError path becomes reachable from the
        # dialog and the no-try/except design assumption breaks.
        assert dialog._break_interval_spinbox.maximum() == 240

    def test_window_title_is_settings(self, dialog: SettingsDialog) -> None:
        """The dialog's window title is the documented label."""
        assert dialog.windowTitle() == "Settings"

    def test_spinbox_tooltip_explains_range(self, dialog: SettingsDialog) -> None:
        """The spinbox tooltip surfaces FR-006's [1, 240] range to the user.

        QSpinBox bounds prevent the *value* from leaving [1, 240] but the
        underlying QLineEdit accepts out-of-range typing that gets
        silently clamped on commit. A permanent tooltip exposes the
        constraint on hover so the bump isn't surprising.
        """
        tooltip = dialog._break_interval_spinbox.toolTip()
        assert "1" in tooltip
        assert "240" in tooltip


# ---------------------------------------------------------------------------
# Save — OK persists, Cancel discards
# ---------------------------------------------------------------------------


class TestSave:
    """OK persists the spinbox value through ``Settings``; Cancel discards."""

    def test_accept_persists_via_settings_setter(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """``accept()`` writes the spinbox value through ``Settings.break_interval_min``."""
        dialog._break_interval_spinbox.setValue(30)

        dialog.accept()

        assert settings.break_interval_min == 30

    def test_accept_persists_across_settings_instances(self, qtbot, ini_path: Path) -> None:
        """A persisted value is observable from a freshly constructed ``Settings``."""
        first_settings = Settings(ini_path=ini_path)
        d = SettingsDialog(settings=first_settings)
        qtbot.addWidget(d)
        d._break_interval_spinbox.setValue(90)
        d.accept()
        first_settings._qs.sync()
        del first_settings

        second_settings = Settings(ini_path=ini_path)
        assert second_settings.break_interval_min == 90

    def test_reject_does_not_persist(
        self, dialog: SettingsDialog, settings: Settings, ini_path: Path
    ) -> None:
        """``reject()`` after editing leaves ``Settings.break_interval_min`` unchanged."""
        # Pre-set to a known value so we can observe the absence of writes.
        settings.break_interval_min = 75
        # Construct a fresh dialog so the spinbox loads the new value.
        # (The fixture-built dialog was constructed before this test set 75.)
        d = SettingsDialog(settings=settings)
        d._break_interval_spinbox.setValue(15)

        d.reject()

        assert settings.break_interval_min == 75

    def test_reject_does_not_write_to_ini(self, qtbot, ini_path: Path) -> None:
        """``reject()`` on a never-saved dialog does not materialize the INI."""
        # Fresh INI path: the file should not exist, and Cancel must not
        # cause it to exist either.
        s = Settings(ini_path=ini_path)
        d = SettingsDialog(settings=s)
        qtbot.addWidget(d)
        d._break_interval_spinbox.setValue(120)

        d.reject()
        s._qs.sync()

        # The Settings constructor itself doesn't write; only the setter
        # does. Cancel skips the setter, so the INI must still be absent.
        assert not ini_path.exists()


# ---------------------------------------------------------------------------
# Layout — single "Scheduling" tab today (S-01)
# ---------------------------------------------------------------------------


class TestLayout:
    """Layout invariants for S-01 — single tab today, more tabs in S-02..S-05."""

    def test_dialog_contains_a_tab_widget(self, dialog: SettingsDialog) -> None:
        """The dialog hosts a ``QTabWidget`` (not a single-pane form)."""
        # Tripwire for the tabbed-from-day-one decision in
        # context/changes/settings-break-interval/plan-brief.md.
        assert dialog.findChild(QTabWidget) is not None

    def test_tab_widget_has_exactly_one_tab(self, dialog: SettingsDialog) -> None:
        """S-01 ships with exactly one tab; S-02..S-05 add more."""
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.count() == 1

    def test_tab_label_is_scheduling(self, dialog: SettingsDialog) -> None:
        """The S-01 tab label is exactly ``"Scheduling"``."""
        # Tripwire: S-02..S-05 may add tabs but should not silently
        # rename this one — other tests and docs reference the label.
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.tabText(0) == "Scheduling"

    def test_scheduling_tab_contains_a_spinbox(self, dialog: SettingsDialog) -> None:
        """The Scheduling tab contains a ``QSpinBox`` for the interval."""
        # Loose check: any QSpinBox child suffices. The TestLoad cases
        # cover the bounds and value semantics explicitly.
        assert dialog.findChild(QSpinBox) is not None
