"""Settings dialog (FR-005 / FR-006).

A modal ``QDialog`` that lets the user view and edit the break interval
inside a real settings window. Replaces the v0.1.0 placeholder
``QMessageBox`` that instructed hand-editing the INI file.

Layout uses a ``QTabWidget`` from day one (single "Scheduling" tab today)
so future settings slices (S-02..S-05 in ``context/foundation/roadmap.md``)
can land additional fields without re-organizing the layout. Field
validation is enforced at the widget level: ``QSpinBox(1, 240)`` makes
out-of-range entries physically impossible, so the
``Settings.break_interval_min`` setter's ``ValueError`` path is
unreachable from this dialog and no try/except wraps the save call.

The dialog is constructed fresh on every "Open settings…" click in
``BreakReminderApp._on_open_settings()`` — no long-lived member, no
stale state across opens. Same lifetime pattern as
``notifications/reminder_dialog.py``'s per-fire instantiation.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from break_reminder.storage.settings import Settings

# FR-006 break interval is bounded to this inclusive range. Sourced from
# the Settings.break_interval_min docstring; surfaced here so the dialog
# tooltip and the bounds setters share one source of truth.
_BREAK_INTERVAL_MIN_MINUTES = 1
_BREAK_INTERVAL_MAX_MINUTES = 240
_BREAK_INTERVAL_RANGE_MESSAGE = (
    f"Break interval must be between {_BREAK_INTERVAL_MIN_MINUTES} "
    f"and {_BREAK_INTERVAL_MAX_MINUTES} minutes."
)


class SettingsDialog(QDialog):
    """Modal settings window — break interval editor (FR-005 / FR-006).

    The dialog reads the current break interval from the injected
    ``Settings`` instance at construction time, lets the user edit it
    via a bounded ``QSpinBox``, and on **OK** persists the new value
    through ``Settings.break_interval_min``. **Cancel** discards and
    closes without writing.
    """

    SCHEDULING_TAB_LABEL = "Scheduling"

    def __init__(
        self,
        *,
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and pre-populate the spinbox from ``settings``.

        Args:
            settings: ``Settings`` instance whose ``break_interval_min``
                getter is read at construction and whose setter is called
                when the user clicks OK.
            parent: Optional Qt parent. Defaults to ``None`` so the
                dialog gets its own top-level taskbar entry, matching
                the convention used by ``BreakDialog`` and
                ``ReminderDialog``.
        """
        super().__init__(parent)
        self._settings = settings

        self.setWindowTitle("Settings")

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_scheduling_tab(), self.SCHEDULING_TAB_LABEL)

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
        """Construct the "Scheduling" tab containing the break-interval spinbox.

        Returns:
            A ``QWidget`` ready to be added to ``self._tabs``. The
            spinbox is stored on ``self._break_interval_spinbox`` so the
            save path can read its value.
        """
        tab = QWidget(self._tabs)

        self._break_interval_spinbox = QSpinBox(tab)
        # FR-006: break interval is bounded to [1, 240] minutes. Setting
        # the bounds at the widget level constrains the resulting value,
        # but the underlying QLineEdit still accepts text like "0" that
        # gets silently clamped on commit. _on_break_interval_edited
        # surfaces a tooltip when this happens so the bump isn't mute.
        self._break_interval_spinbox.setMinimum(_BREAK_INTERVAL_MIN_MINUTES)
        self._break_interval_spinbox.setMaximum(_BREAK_INTERVAL_MAX_MINUTES)
        self._break_interval_spinbox.setSuffix(" min")
        self._break_interval_spinbox.setToolTip(_BREAK_INTERVAL_RANGE_MESSAGE)
        self._break_interval_spinbox.setValue(self._settings.break_interval_min)
        self._break_interval_spinbox.editingFinished.connect(self._on_break_interval_edited)

        form = QFormLayout(tab)
        form.addRow("Break interval (minutes):", self._break_interval_spinbox)

        return tab

    def _on_break_interval_edited(self) -> None:
        """Show a transient tooltip when the user typed an out-of-range value.

        ``QSpinBox`` silently clamps to ``setMinimum`` / ``setMaximum`` on
        commit (Enter, focus loss, or any path that calls ``value()``).
        Compare the typed text against the post-clamp value; on mismatch,
        surface a brief popup so the user sees the FR-006 constraint
        rather than a mute bump.
        """
        line_edit = self._break_interval_spinbox.lineEdit()
        if line_edit is None:
            return
        typed = line_edit.text().strip()
        actual = str(self._break_interval_spinbox.value())
        if not typed or typed == actual:
            return
        widget = self._break_interval_spinbox
        QToolTip.showText(
            widget.mapToGlobal(widget.rect().bottomLeft()),
            _BREAK_INTERVAL_RANGE_MESSAGE,
            widget,
            widget.rect(),
            3000,
        )

    def accept(self) -> None:
        """Persist the spinbox value and close the dialog.

        Writes ``self._settings.break_interval_min`` from the spinbox
        and then chains to ``QDialog.accept`` for the standard close
        path. The widget-level bounds (set in ``_build_scheduling_tab``)
        guarantee the value is in FR-006's [1, 240] range, so no
        try/except is needed around the setter.
        """
        self._settings.break_interval_min = self._break_interval_spinbox.value()
        super().accept()
