"""Settings dialog (FR-005 / FR-006 / FR-007).

A modal ``QDialog`` that lets the user view and edit BreakReminder's
preferences inside a real settings window. Replaces the v0.1.0
placeholder ``QMessageBox`` that instructed hand-editing the INI file.

Layout uses a ``QTabWidget`` from day one. The current tabs:

- **Scheduling** (S-01) — the FR-006 break-interval editor.
- **Notifications** (S-04) — the FR-007 voice toggle, editable phrase,
  and a "Test voice" button that previews the unsaved phrase. The
  "Voice phrase cannot be empty when voice is enabled" rule is enforced
  in ``accept()`` via the same transient ``QToolTip`` pattern the
  Scheduling tab uses for the FR-006 range message — saving with that
  combination surfaces the tooltip and skips the persistence write.

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

``VoiceNotifier`` is injected via the constructor as a required
keyword-only parameter so tests can pass a stub instead of spinning
up a real ``pyttsx3`` worker pool — see
``context/changes/settings-voice-toggle/plan.md`` "Critical
Implementation Details" for the rationale.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from break_reminder.notifications.voice import VoiceNotifier
from break_reminder.storage.settings import (
    BREAK_INTERVAL_MAX_MINUTES,
    BREAK_INTERVAL_MIN_MINUTES,
    MAX_SNOOZES_MAX,
    MAX_SNOOZES_MIN,
    SNOOZE_DURATION_MAX_MINUTES,
    SNOOZE_DURATION_MIN_MINUTES,
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

# Tooltip on the max-snoozes spinbox. Surfaces the non-obvious zero-state
# UX: setting the cap to 0 disables snoozing entirely on the next break.
# Without this hint a user lowering the cap to 0 might expect the snooze
# button to still appear and just refuse — the actual behavior is that
# the existing ``snooze_remaining = 0`` path in the scheduler/break
# dialog hides the button outright.
_MAX_SNOOZES_ZERO_TOOLTIP = "0 = no snoozes; the break must be taken or missed."

# Tooltip on the voice checkbox. Conveys the FR-007 contract once at
# the surface where the user is already deciding whether to flip the
# toggle — popup is mandatory; voice is an additional channel, not a
# replacement.
_VOICE_ENABLED_TOOLTIP = "Voice plays alongside the break popup, not instead of it."

# Transient feedback when the user clicks OK with voice enabled but
# a blank/whitespace phrase. Anchored below the phrase line edit so
# the message lands next to the field that must be fixed.
_VOICE_PHRASE_REQUIRED_MESSAGE = "Voice phrase cannot be empty when voice is enabled."


class SettingsDialog(QDialog):
    """Modal settings window (FR-005 / FR-006 / FR-007).

    The dialog reads the current break interval and voice settings from
    the injected ``Settings`` instance at construction time, lets the
    user edit them across two tabs ("Scheduling" and "Notifications"),
    and on **OK** persists the new values through ``Settings``.
    **Cancel** discards and closes without writing.

    The "Notifications" tab also exposes a "Test voice" button that
    speaks the line edit's current (unsaved) text via the injected
    ``VoiceNotifier``. The button is a pure side-effect — it does not
    touch ``Settings`` and never triggers a save.
    """

    SCHEDULING_TAB_LABEL = "Scheduling"
    NOTIFICATIONS_TAB_LABEL = "Notifications"

    def __init__(
        self,
        *,
        settings: Settings,
        voice: VoiceNotifier,
        parent: QWidget | None = None,
    ) -> None:
        """Build the dialog and pre-populate widgets from ``settings``.

        Args:
            settings: ``Settings`` instance whose ``break_interval_min``,
                ``voice_enabled``, and ``voice_phrase`` getters are read
                at construction and whose setters are called when the
                user clicks OK.
            voice: ``VoiceNotifier`` the "Test voice" button speaks
                through. Required (no default) so tests must inject a
                stub — defaulting to a fresh ``VoiceNotifier()`` would
                spin up a real ``pyttsx3`` worker pool every time the
                test suite constructs the dialog.
            parent: Optional Qt parent. Defaults to ``None`` so the
                dialog gets its own top-level taskbar entry, matching
                the convention used by ``BreakDialog`` and
                ``ReminderDialog``.
        """
        super().__init__(parent)
        self._settings = settings
        self._voice = voice
        self._user_typed_text: str | None = None

        self.setWindowTitle("Settings")

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_scheduling_tab(), self.SCHEDULING_TAB_LABEL)
        # Stored on self so accept()'s validation gate can switch to the
        # Notifications tab before anchoring the empty-phrase tooltip — see
        # the impl-review F1 fix in
        # ``context/changes/settings-voice-toggle/reviews/impl-review.md``.
        self._notifications_tab = self._build_notifications_tab()
        self._tabs.addTab(self._notifications_tab, self.NOTIFICATIONS_TAB_LABEL)

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
        """Construct the "Scheduling" tab containing the break-interval and snooze spinboxes.

        Returns:
            A ``QWidget`` ready to be added to ``self._tabs``. Three
            spinboxes are stored on ``self`` so the save path can read
            their values: ``_break_interval_spinbox`` (FR-006),
            ``_snooze_duration_spinbox`` (FR-010 duration), and
            ``_max_snoozes_spinbox`` (FR-010 cap).
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

        # FR-010 snooze duration. No typed-out-of-range tooltip pattern
        # here (decided during /10x-plan): the 1-30 range is small enough
        # that the spinbox's silent fixup is adequate; replicating the
        # break-interval keystroke-capture pair would duplicate ~40 lines
        # for no observable user benefit.
        self._snooze_duration_spinbox = QSpinBox(tab)
        self._snooze_duration_spinbox.setMinimum(SNOOZE_DURATION_MIN_MINUTES)
        self._snooze_duration_spinbox.setMaximum(SNOOZE_DURATION_MAX_MINUTES)
        self._snooze_duration_spinbox.setSuffix(" min")
        self._snooze_duration_spinbox.setValue(self._settings.snooze_duration_min)

        # FR-010 max snoozes per cycle. Lower bound 0 is intentional —
        # see ``_MAX_SNOOZES_ZERO_TOOLTIP`` for the user-facing hint.
        self._max_snoozes_spinbox = QSpinBox(tab)
        self._max_snoozes_spinbox.setMinimum(MAX_SNOOZES_MIN)
        self._max_snoozes_spinbox.setMaximum(MAX_SNOOZES_MAX)
        self._max_snoozes_spinbox.setToolTip(_MAX_SNOOZES_ZERO_TOOLTIP)
        self._max_snoozes_spinbox.setValue(self._settings.max_snoozes)

        form = QFormLayout(tab)
        form.addRow("Break interval (minutes):", self._break_interval_spinbox)
        form.addRow("Snooze duration (minutes):", self._snooze_duration_spinbox)
        form.addRow("Max snoozes per cycle:", self._max_snoozes_spinbox)

        return tab

    def _build_notifications_tab(self) -> QWidget:
        """Construct the "Notifications" tab (FR-007 voice toggle + phrase + Test).

        The tab carries three widgets:

        - ``self._voice_enabled_checkbox`` — pre-populated from
          ``Settings.voice_enabled``. The checkbox tooltip explains the
          FR-007 contract that the popup is mandatory and voice plays
          alongside, not instead of it.
        - ``self._voice_phrase_edit`` — a ``QLineEdit`` pre-populated
          from ``Settings.voice_phrase``. Always editable regardless of
          the checkbox state so the user can prepare the phrase before
          flipping the gate.
        - ``self._voice_test_button`` — a ``QPushButton`` whose
          ``clicked`` signal calls ``_on_test_voice_clicked`` to speak
          the line edit's current (unsaved) text through the injected
          ``VoiceNotifier``.

        Returns:
            A ``QWidget`` ready to be added to ``self._tabs``.
        """
        tab = QWidget(self._tabs)

        self._voice_enabled_checkbox = QCheckBox("Enable voice notification", tab)
        self._voice_enabled_checkbox.setChecked(self._settings.voice_enabled)
        self._voice_enabled_checkbox.setToolTip(_VOICE_ENABLED_TOOLTIP)

        self._voice_phrase_edit = QLineEdit(tab)
        self._voice_phrase_edit.setText(self._settings.voice_phrase)

        self._voice_test_button = QPushButton("Test voice", tab)
        self._voice_test_button.clicked.connect(self._on_test_voice_clicked)

        # Phrase + Test button share a row so the preview lands right
        # next to the field whose contents it speaks.
        phrase_row = QWidget(tab)
        phrase_row_layout = QHBoxLayout(phrase_row)
        phrase_row_layout.setContentsMargins(0, 0, 0, 0)
        phrase_row_layout.addWidget(self._voice_phrase_edit, 1)
        phrase_row_layout.addWidget(self._voice_test_button, 0)

        form = QFormLayout(tab)
        form.addRow(self._voice_enabled_checkbox)
        form.addRow("Voice phrase:", phrase_row)

        return tab

    def _on_test_voice_clicked(self) -> None:
        """Speak the phrase line edit's current (unsaved) text.

        Pure side-effect — does not touch ``Settings`` and does not
        chain into the save path. Calls ``VoiceNotifier.speak`` which
        already runs on a single-worker thread pool, so the GUI thread
        does not block. ``VoiceNotifier.speak("")`` is a documented
        no-op, so an empty phrase produces no audio without raising.

        ``stop()`` is called before ``speak()`` so that rapid Test-button
        clicks cancel the prior in-flight preview rather than queuing
        five copies of the speech serially (impl-review F3).
        """
        self._voice.stop()
        self._voice.speak(self._voice_phrase_edit.text())

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
        """Validate then persist all editable settings and close the dialog.

        Validation gate (FR-007 voice tab): if the voice checkbox is
        ticked but the phrase line edit is blank or whitespace-only,
        surface a transient ``QToolTip`` below the phrase field with
        ``_VOICE_PHRASE_REQUIRED_MESSAGE`` and return early — no setter
        runs and the dialog stays open. The ``(voice_enabled=True,
        voice_phrase="")`` confused state cannot land on disk via the
        GUI.

        Persistence order (Scheduling first, Notifications second):

        - **FR-006 break interval** — written via ``Settings.break_interval_min``;
          widget-level bounds guarantee a [1, 240] value, so the setter's
          ``ValueError`` branch is unreachable here.
        - **FR-010 snooze duration** — written via
          ``Settings.snooze_duration_min``; widget-level [1, 30] bounds
          make the setter's ``ValueError`` branch unreachable from here.
        - **FR-010 max snoozes** — written via ``Settings.max_snoozes``;
          widget-level [0, 5] bounds make the setter's ``ValueError``
          branch unreachable from here.
        - **FR-007 voice toggle and phrase** — written next; the
          ``voice_phrase`` setter is permissive at the persistence layer
          (the dialog-level gate above is the only enforcement of the
          non-empty contract).

        Then chains to ``QDialog.accept`` for the standard close path.
        """
        if self._voice_enabled_checkbox.isChecked() and not self._voice_phrase_edit.text().strip():
            # Surface the Notifications tab BEFORE anchoring the tooltip —
            # the user may have clicked OK from the Scheduling tab, in which
            # case the phrase line edit is on a hidden tab and the tooltip
            # would float anchored to nothing visible. Switching tabs first
            # ensures the message points at the field that needs fixing.
            self._tabs.setCurrentWidget(self._notifications_tab)
            anchor = self._voice_phrase_edit.mapToGlobal(
                self._voice_phrase_edit.rect().bottomLeft()
            )
            QToolTip.showText(
                anchor,
                _VOICE_PHRASE_REQUIRED_MESSAGE,
                self._voice_phrase_edit,
                msecShowTime=3000,
            )
            return

        self._settings.break_interval_min = self._break_interval_spinbox.value()
        self._settings.snooze_duration_min = self._snooze_duration_spinbox.value()
        self._settings.max_snoozes = self._max_snoozes_spinbox.value()
        self._settings.voice_enabled = self._voice_enabled_checkbox.isChecked()
        self._settings.voice_phrase = self._voice_phrase_edit.text()
        super().accept()
