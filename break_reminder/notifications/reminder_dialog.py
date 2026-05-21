"""Custom-reminder popup (FR-013) — deliberately dismissable.

FR-013 splits notification severity by event type: break notifications use
the FR-009 non-dismissable design (the wedge); custom reminders use a
normal popup that respects every standard dismiss gesture. **Do not** copy
the ``break_dialog`` overrides over here — that would defeat the split.

Voice playback (if globally enabled) is fired-and-forgotten just before
the dialog is shown; the dialog itself doesn't manage the voice
lifecycle because dismissal is unconstrained.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)


class ReminderDialog(QDialog):
    """Lightweight dismissable popup for custom reminders (FR-013)."""

    def __init__(self, *, name: str, parent=None) -> None:
        """Build the reminder popup.

        Args:
            name: Reminder name shown in the popup title row.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self.setWindowTitle("Reminder")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(name)
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        body = QLabel("This is a scheduled reminder.")
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
