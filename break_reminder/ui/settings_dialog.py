"""Settings dialog (FR-005 / FR-006).

A modal ``QDialog`` that lets the user view and edit the break interval
inside a real settings window. Replaces the v0.1.0 placeholder
``QMessageBox`` that instructed hand-editing the INI file.

Layout uses a ``QTabWidget`` from day one (single "Scheduling" tab today)
so future settings slices (S-02..S-05 in ``context/foundation/roadmap.md``)
can land additional fields without re-organizing the layout.

Validation is split across two layers, intentionally:

- **Saved-value enforcement** — ``QSpinBox.setMinimum`` /
  ``setMaximum`` constrain ``spinbox.value()`` to FR-006's
  ``[BREAK_INTERVAL_MIN_MINUTES, BREAK_INTERVAL_MAX_MINUTES]`` range.
  Because the save path writes ``spinbox.value()``, the
  ``Settings.break_interval_min`` setter's ``ValueError`` branch is
  unreachable from this dialog and no try/except is needed.
- **Typed-input feedback** — Qt's ``QSpinBox`` does *not* prevent the
  user from typing out-of-range characters into the line edit; it
  silently reverts (below minimum) or truncates to a valid prefix
  (above maximum) when the value commits. The pair
  ``_on_break_interval_text_edited`` (captures raw keystrokes via
  ``lineEdit.textEdited`` before Qt's fixup runs) and
  ``_on_break_interval_edited`` (consumes the snapshot at
  ``editingFinished``) surfaces a transient ``QToolTip`` so the user
  sees the FR-006 constraint instead of a mute revert. See
  ``context/changes/settings-break-interval/plan.md`` "Addenda —
  2026-05-25" for the full rationale.

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

from break_reminder.storage.settings import (
    BREAK_INTERVAL_MAX_MINUTES,
    BREAK_INTERVAL_MIN_MINUTES,
    Settings,
)

# UI-facing message for the FR-006 range. The bounds themselves come from
# ``storage.settings`` (single source of truth); this string composes them
# into the exact wording the spinbox tooltip and the transient validation
# popup share.
_BREAK_INTERVAL_RANGE_MESSAGE = (
    f"Break interval must be between {BREAK_INTERVAL_MIN_MINUTES} "
    f"and {BREAK_INTERVAL_MAX_MINUTES} minutes."
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
        self._user_typed_text: str | None = None

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
        # FR-006: break interval is bounded to [1, 240] minutes at the
        # widget level. By the time `editingFinished` fires Qt has already
        # rewritten the lineEdit text via fixup() — out-of-range typing
        # silently reverts to the prior value (below min) or truncates to
        # the longest valid prefix (above max). To detect "user attempted
        # an out-of-range value" we capture their raw keystrokes via
        # `lineEdit.textEdited` BEFORE fixup runs, then check that captured
        # text in `_on_break_interval_edited`.
        self._break_interval_spinbox.setMinimum(BREAK_INTERVAL_MIN_MINUTES)
        self._break_interval_spinbox.setMaximum(BREAK_INTERVAL_MAX_MINUTES)
        self._break_interval_spinbox.setSuffix(" min")
        self._break_interval_spinbox.setToolTip(_BREAK_INTERVAL_RANGE_MESSAGE)
        self._break_interval_spinbox.setValue(self._settings.break_interval_min)
        self._break_interval_spinbox.editingFinished.connect(self._on_break_interval_edited)
        line_edit = self._break_interval_spinbox.lineEdit()
        if line_edit is not None:
            line_edit.textEdited.connect(self._on_break_interval_text_edited)

        form = QFormLayout(tab)
        form.addRow("Break interval (minutes):", self._break_interval_spinbox)

        return tab

    def _on_break_interval_text_edited(self, text: str) -> None:
        """Capture the user's raw typed text before Qt's fixup rewrites it.

        ``QLineEdit.textEdited`` fires on every keystroke before the
        spinbox's ``fixup()`` pipeline runs at commit time. Stashing the
        latest typed text here lets ``_on_break_interval_edited`` compare
        intent against bounds rather than against the post-fixup display.

        Args:
            text: Current contents of the spinbox's underlying
                ``QLineEdit`` after the latest keystroke.
        """
        self._user_typed_text = text

    def _on_break_interval_edited(self) -> None:
        """Show a transient tooltip when the user typed an out-of-range value.

        Qt's ``QSpinBox`` does not "clamp" out-of-range typing the way the
        FR-006 setter does — it reverts (below minimum) or truncates to a
        valid prefix (above maximum). Either way, the user's intent is
        lost from the lineEdit by the time this slot fires. The companion
        ``_on_break_interval_text_edited`` slot snapshots the raw typed
        text on every keystroke; here we parse that snapshot and surface
        a brief popup if it falls outside [1, 240] minutes.
        """
        typed_text = self._user_typed_text
        self._user_typed_text = None
        if typed_text is None:
            return
        try:
            typed_value = int(typed_text.removesuffix(" min").strip())
        except ValueError:
            return
        if BREAK_INTERVAL_MIN_MINUTES <= typed_value <= BREAK_INTERVAL_MAX_MINUTES:
            return
        widget = self._break_interval_spinbox
        QToolTip.showText(
            widget.mapToGlobal(widget.rect().bottomLeft()),
            _BREAK_INTERVAL_RANGE_MESSAGE,
            widget,
            msecShowTime=3000,
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
