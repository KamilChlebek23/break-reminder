"""Non-dismissable break-notification popup (FR-009 / US-02).

This is the product wedge: the dialog must stay on screen until the user
clicks a deliberate action button, even when they reflexively press
``Escape``, ``Alt+F4``, click outside, or change focus to another window.
At the same time, US-02 requires that the in-flight keystroke completes
in the previously focused app — i.e., the dialog must **appear without
stealing keyboard focus**.

Every dismiss path is overridden:

* ``keyPressEvent`` — ``Qt.Key_Escape`` is swallowed.
* ``closeEvent`` — ignored unless ``self._user_action`` was set first by
  one of the action handlers. Alt+F4 routes through ``closeEvent``, so
  this single guard catches both.
* ``WindowFlags`` — ``WindowStaysOnTopHint | CustomizeWindowHint |
  WindowTitleHint`` removes the OS close button.
* ``WA_ShowWithoutActivating`` + ``show()`` (not ``exec()``) — the window
  appears on top without stealing focus from the IDE.

If you add a new way to clear the dialog (a button, a hotkey), it **must**
set ``self._user_action = True`` before calling ``close()``. Otherwise
``closeEvent`` will refuse and the dialog will appear undismissable.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class _VoiceController(Protocol):
    """The narrow contract BreakDialog needs from a voice notifier.

    ``VoiceNotifier`` (in notifications/voice.py) implements this
    structurally, as does any test fake with a no-arg ``stop()`` method.
    Declaring it as a Protocol — instead of importing the concrete
    ``VoiceNotifier`` — keeps tests free of ``cast(...)`` ceremony and
    documents that the dialog only consumes one method of the dependency.
    """

    def stop(self) -> None: ...


class BreakOutcome(StrEnum):
    """The two terminal outcomes of a break popup, as logged in FR-015."""

    TAKEN = "taken"
    SNOOZED = "snoozed"


class BreakDialog(QDialog):
    """The FR-009 non-dismissable break popup."""

    outcome_chosen = Signal(str)  # BreakOutcome value

    def __init__(
        self,
        *,
        snooze_remaining: int,
        voice_notifier: _VoiceController | None = None,
        parent=None,
    ) -> None:
        """Build the break dialog with FR-009 dismiss-path overrides applied.

        Args:
            snooze_remaining: How many snoozes the user has left in the
                current cycle. The Snooze button is disabled when this
                reaches 0 (FR-010).
            voice_notifier: Object whose ``stop()`` method is called
                when the user clicks an action button (US-02).
                ``None`` skips voice control entirely.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._user_action = False
        self._voice = voice_notifier

        self.setWindowTitle("Time to take a break")
        # CustomizeWindowHint strips the default frame; we re-add the title
        # bar explicitly with WindowTitleHint, but no system menu / close
        # button. StaysOnTopHint keeps it visible even when the IDE is
        # fullscreen.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        # WA_ShowWithoutActivating + Qt.NoFocus implements US-02:
        # "the in-flight keystroke completes in the previously focused app".
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._build_ui(snooze_remaining)

    # ---- UI -------------------------------------------------------------

    def _build_ui(self, snooze_remaining: int) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Time to take a break")
        title_font = title.font()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        body = QLabel("You've been at the keyboard for a while. Stand up, stretch, walk a bit.")
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)

        take_btn = QPushButton("I'll take a break")
        take_btn.setDefault(False)
        take_btn.setAutoDefault(False)
        take_btn.clicked.connect(self._on_take_break)
        buttons.addWidget(take_btn)

        snooze_btn = QPushButton(f"Snooze ({snooze_remaining} left)")
        snooze_btn.setEnabled(snooze_remaining > 0)
        snooze_btn.setAutoDefault(False)
        snooze_btn.clicked.connect(self._on_snooze)
        buttons.addWidget(snooze_btn)

        layout.addLayout(buttons)

    # ---- action handlers ------------------------------------------------

    def _on_take_break(self) -> None:
        self._stop_voice()
        self._user_action = True
        self.outcome_chosen.emit(BreakOutcome.TAKEN.value)
        self.close()

    def _on_snooze(self) -> None:
        self._stop_voice()
        self._user_action = True
        self.outcome_chosen.emit(BreakOutcome.SNOOZED.value)
        self.close()

    def _stop_voice(self) -> None:
        if self._voice is not None:
            self._voice.stop()

    # ---- dismiss-path overrides (FR-009 / US-02) ------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Swallow ``Qt.Key_Escape``; defer everything else to ``QDialog`` (FR-009)."""
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Refuse closes that didn't go through an action button (FR-009).

        Alt+F4, the OS close button (if visible), and click-outside-then-
        close all route here. Only an action handler having set
        ``self._user_action = True`` first counts as a deliberate dismissal.
        """
        if not self._user_action:
            event.ignore()
            return
        event.accept()
