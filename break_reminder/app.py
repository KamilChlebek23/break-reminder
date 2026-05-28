"""QApplication + system tray + top-level signal wiring (FR-004 / FR-005).

This module is the "main()" of BreakReminder. It instantiates every
collaborator and wires their signals, but holds no business logic itself —
all the rules live in ``scheduler.py``, all the persistence in
``storage/``, and all the UI surfaces in ``notifications/``.

Quit semantics: the app is a tray-resident background process. Closing
the (yet-to-be-built) settings window does **not** quit the app — the
user explicitly clicks "Quit" in the tray menu, or kills the process.
``QApplication.setQuitOnLastWindowClosed(False)`` enforces this.
"""

from __future__ import annotations

import logging
import math
import sys
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from break_reminder import __version__
from break_reminder.activity import ActivityMonitor
from break_reminder.notifications.break_dialog import BreakDialog, BreakOutcome
from break_reminder.notifications.reminder_dialog import ReminderDialog
from break_reminder.notifications.voice import VoiceNotifier
from break_reminder.scheduler import BreakScheduler, ReminderScheduler
from break_reminder.storage.event_log import EventLog, EventType, Outcome
from break_reminder.storage.paths import APPLICATION_NAME
from break_reminder.storage.reminders import ReminderStore
from break_reminder.storage.settings import Settings
from break_reminder.ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

# GitHub Releases URL the tray "Check for updates" item opens. KamilChlebek23 is
# the maintainer's GitHub login and MUST be replaced before the v0.1.0
# tag push (see context/deployment/deploy-plan.md Phase 1 step 1).
RELEASES_URL = "https://github.com/KamilChlebek23/break-reminder/releases/latest"

# Mirror of pyproject.toml:4 — keep in sync when the description changes.
# Hardcoded rather than read via importlib.metadata so the dialog works
# in editable / source-tree dev runs without requiring an installed-
# package metadata view (impl-plan version-in-check-updates).
_APP_DESCRIPTION = "A Windows-11 break reminder for phone-free deep-focus workspaces."


class BreakReminderApp:
    """Container for the tray icon, schedulers, and dialogs."""

    def __init__(
        self,
        qt_app: QApplication,
        *,
        settings: Settings | None = None,
        event_log: EventLog | None = None,
        reminder_store: ReminderStore | None = None,
        voice: VoiceNotifier | None = None,
    ) -> None:
        r"""Construct the app and wire its collaborators.

        Storage and voice components are injectable so tests can swap in
        tmp-pathed instances without touching ``%APPDATA%``. Production
        callers pass ``None`` for everything except ``qt_app`` and get
        the default-constructed instances bound to the standard per-user
        paths (FR-002 / FR-015).

        Args:
            qt_app: The shared ``QApplication`` instance.
            settings: Optional pre-built ``Settings``; defaults to the
                user's ``%APPDATA%\BreakReminder\BreakReminder.ini``.
            event_log: Optional pre-built ``EventLog``; defaults to the
                rotating CSV under the standard per-user data dir.
            reminder_store: Optional pre-built ``ReminderStore``; defaults
                to the standard ``reminders.json`` location.
            voice: Optional pre-built ``VoiceNotifier``; defaults to a
                fresh one bound to a single-worker thread pool.
        """
        # Storage components are injectable so tests can point at a tmp
        # directory without polluting %APPDATA%. Production passes
        # ``None`` and gets the default-constructed instances, which use
        # the standard per-user paths (FR-002 / FR-015).
        self._qt_app = qt_app

        # FR-016: paused state must NOT survive a reboot. Clear at startup.
        self._settings = settings if settings is not None else Settings()
        self._settings.clear_paused_on_reboot()

        self._event_log = event_log if event_log is not None else EventLog()
        self._reminder_store = reminder_store if reminder_store is not None else ReminderStore()
        self._voice = voice if voice is not None else VoiceNotifier()

        self._activity = ActivityMonitor()
        self._break_scheduler = BreakScheduler(settings=self._settings, activity=self._activity)
        self._reminder_scheduler = ReminderScheduler(store=self._reminder_store)

        self._tray = self._build_tray()
        self._tooltip_timer = QTimer()
        self._tooltip_timer.setInterval(5_000)
        self._tooltip_timer.timeout.connect(self._refresh_tooltip)

        self._active_break_dialog: BreakDialog | None = None

        self._wire_signals()

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def start(self) -> None:
        """Spin up every subsystem, refresh the tray, and show the icon."""
        self._activity.start()
        self._break_scheduler.start()
        self._reminder_scheduler.start()
        self._tooltip_timer.start()
        self._refresh_tooltip()
        self._tray.show()

    def shutdown(self) -> None:
        """Stop every subsystem in reverse-start order. Idempotent."""
        self._tooltip_timer.stop()
        self._reminder_scheduler.stop()
        self._break_scheduler.stop()
        self._activity.stop()
        self._voice.shutdown()

    # -------------------------------------------------------------------
    # Tray (FR-004)
    # -------------------------------------------------------------------

    def _build_tray_icon(self) -> QIcon:
        """Render a clock-face icon at startup (FR-004).

        Drawn in code rather than bundled as a .ico because (a) the project
        has no icon artwork yet, (b) QPainter output is crisp at any DPI,
        and (c) stroking with QPalette.WindowText makes the icon follow
        Windows 11's light/dark tray theme automatically.

        Source resolution is 256x256; Qt down-scales for the actual tray
        size (16x16 on legacy DPI, 32x32 / 48x48 on HiDPI Windows 11).
        """
        size = 256
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = self._qt_app.palette().windowText().color()
        pen = QPen(color)
        pen.setWidth(size // 16)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        # Face: leave a margin so the stroke isn't clipped by the icon edge.
        margin = size // 8
        face = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
        painter.drawEllipse(face)

        cx, cy = size / 2, size / 2
        radius = (size - 2 * margin) / 2

        # Four hour ticks at 12 / 3 / 6 / 9 — full 12 ticks read as noise at 16x16.
        tick_inner = radius * 0.78
        tick_outer = radius * 0.92
        for angle_deg in (0, 90, 180, 270):
            rad = math.radians(angle_deg - 90)
            cos_r, sin_r = math.cos(rad), math.sin(rad)
            painter.drawLine(
                QPointF(cx + tick_inner * cos_r, cy + tick_inner * sin_r),
                QPointF(cx + tick_outer * cos_r, cy + tick_outer * sin_r),
            )

        # Hour hand pointing to 12, minute hand pointing to 3 (canonical
        # watch-face pose; visually balanced and unambiguous as "a clock").
        painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - radius * 0.5))
        painter.drawLine(QPointF(cx, cy), QPointF(cx + radius * 0.7, cy))

        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), size / 32, size / 32)
        painter.end()

        return QIcon(pixmap)

    def _build_tray(self) -> QSystemTrayIcon:
        # Tray icon is rendered in code (see _build_tray_icon). Swap to a
        # bundled resources/breakreminder.ico when real artwork is ready;
        # PyInstaller will need `--add-data resources;resources` then.
        tray = QSystemTrayIcon(self._build_tray_icon())
        tray.setToolTip(APPLICATION_NAME)
        tray.activated.connect(self._on_tray_activated)

        menu = QMenu()

        self._action_take_now = QAction("Take break now", menu)
        self._action_take_now.triggered.connect(self._on_take_break_now)
        menu.addAction(self._action_take_now)

        self._action_reset = QAction("Reset", menu)
        self._action_reset.triggered.connect(self._on_reset)
        menu.addAction(self._action_reset)

        self._action_pause = QAction("Pause", menu)
        self._action_pause.triggered.connect(self._on_toggle_pause)
        menu.addAction(self._action_pause)

        menu.addSeparator()

        self._action_settings = QAction("Open settings…", menu)
        self._action_settings.triggered.connect(self._on_open_settings)
        menu.addAction(self._action_settings)

        self._action_check_updates = QAction("Check for updates", menu)
        self._action_check_updates.triggered.connect(self._on_check_for_updates)
        menu.addAction(self._action_check_updates)

        menu.addSeparator()

        action_quit = QAction("Quit", menu)
        action_quit.triggered.connect(self._on_quit)
        menu.addAction(action_quit)

        tray.setContextMenu(menu)
        return tray

    def _refresh_tooltip(self) -> None:
        """Recompute the tray-icon tooltip and the Pause/Resume menu label.

        Three branches in priority order:

        1. **Paused** (FR-016) — ``BreakReminder — paused``. Wins over
           snooze because pause is the more constraining state (no
           breaks fire while paused, snoozed or not).
        2. **Snoozing** (FR-010) — ``BreakReminder — snooze time left
           Xm YYs``. Active when the scheduler reports a non-``None``
           ``seconds_until_snooze_end``. Flips back to the regular
           countdown the moment the snooze elapses.
        3. **Regular countdown** (FR-008) — ``BreakReminder — next
           break in Xm YYs``.

        Driven by the 5-second ``_tooltip_timer`` plus eager calls from
        every state-changing slot (``_on_toggle_pause``,
        ``_apply_break_taken``, ``_apply_break_snoozed``).
        """
        if self._break_scheduler.is_paused:
            self._tray.setToolTip(f"{APPLICATION_NAME} — paused")
            self._action_pause.setText("Resume")
            return
        self._action_pause.setText("Pause")

        snooze_seconds = self._break_scheduler.seconds_until_snooze_end
        if snooze_seconds is not None:
            minutes, seconds = divmod(snooze_seconds, 60)
            self._tray.setToolTip(
                f"{APPLICATION_NAME} — snooze time left {minutes:d}m {seconds:02d}s"
            )
            return

        seconds = self._break_scheduler.seconds_until_break
        minutes, seconds = divmod(seconds, 60)
        self._tray.setToolTip(f"{APPLICATION_NAME} — next break in {minutes:d}m {seconds:02d}s")

    # -------------------------------------------------------------------
    # Wiring
    # -------------------------------------------------------------------

    def _wire_signals(self) -> None:
        self._break_scheduler.break_due.connect(self._on_break_due)
        self._reminder_scheduler.reminder_due.connect(self._on_reminder_due)
        self._qt_app.aboutToQuit.connect(self.shutdown)

    # -------------------------------------------------------------------
    # Slots
    # -------------------------------------------------------------------

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left-click = open settings. Right-click is handled by Qt's context
        # menu wiring automatically, so we don't handle it here.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_open_settings()

    def _on_take_break_now(self) -> None:
        # FR-004 quick-menu: "Take break now". Treat as a forced break_due
        # with no snooze available — the user is opting in deliberately.
        self._break_scheduler.stop()
        self._show_break_dialog(snooze_remaining=0)

    def _on_reset(self) -> None:
        """FR-004 quick-menu: 'Reset'.

        One-click equivalent of 'Take break now -> I'll take a break':
        clears active-time accumulation, resets the snooze cap, and logs
        a TAKEN event so FR-015 stays consistent with the dialog flow.
        Does not change pause state — Reset is about the timer cycle,
        not the pause toggle.
        """
        self._apply_break_taken()

    def _on_toggle_pause(self) -> None:
        if self._break_scheduler.is_paused:
            self._break_scheduler.resume()
        else:
            self._break_scheduler.pause()
        self._refresh_tooltip()

    def _on_open_settings(self) -> None:
        """Open the settings window (FR-005).

        Constructs a fresh ``SettingsDialog`` against the app's existing
        ``Settings``, ``VoiceNotifier``, and ``ReminderStore`` instances
        and runs it modally. No long-lived member is kept — the dialog
        is GC'd as soon as ``exec()`` returns, so every open is a fresh
        load with no stale state. The Reminders tab's "load once at
        construction" invariant depends on this lifetime; if the dialog
        were ever held across opens, the list would silently go stale.

        Four tabs ship today: "Scheduling" (FR-006 break interval +
        FR-010 snooze), "Notifications" (FR-007 voice toggle, phrase,
        Test), "Lifecycle" (FR-003 Windows autostart), and "Reminders"
        (FR-012 custom-reminders list — Add ships with S-06; S-07/S-08
        will light up Edit/Delete).

        The ``ReminderScheduler`` is threaded through so the Add
        sub-dialog can call ``reload()`` and arm the running session
        against the freshly-saved reminder.

        S-09 wiring: ``dialog.break_interval_changed`` is connected to
        ``_on_break_interval_changed`` BEFORE ``dialog.exec()`` so the
        signal — emitted from ``accept()`` while ``exec()`` is still
        running — is delivered. Connecting after ``exec()`` returns is
        too late: the signal has already fired and the dialog is mid-
        destruction.
        """
        dialog = SettingsDialog(
            settings=self._settings,
            voice=self._voice,
            reminder_store=self._reminder_store,
            reminder_scheduler=self._reminder_scheduler,
        )
        dialog.break_interval_changed.connect(self._on_break_interval_changed)
        dialog.exec()

    def _on_check_for_updates(self) -> None:
        """Show the installed version, then optionally open GitHub Releases.

        Pops a modal ``QMessageBox`` titled "About BreakReminder" with the
        installed version (``break_reminder.__version__``) and the app
        description, plus two buttons: "Open Releases" (default — does
        the same browser hop as before) and "Close" (dismisses without
        browsing). Identity check on the clicked button drives the
        conditional ``QDesktopServices.openUrl`` call.

        No network calls happen inside the app — the OS opens the browser
        — so the local-only NFR stays intact. Pre-staged mitigation for
        the "users stay on stale versions" risk in
        ``context/foundation/infrastructure.md``.
        """
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(f"About {APPLICATION_NAME}")
        box.setText(f"<b>{APPLICATION_NAME} v{__version__}</b>")
        box.setInformativeText(
            f"{_APP_DESCRIPTION}\n\nClick 'Open Releases' to see if a newer version is available."
        )
        open_button = box.addButton("Open Releases", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(open_button)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(RELEASES_URL))

    def _on_quit(self) -> None:
        self._qt_app.quit()

    def _on_break_due(self, snooze_remaining: int) -> None:
        if self._settings.voice_enabled:
            self._voice.speak(self._settings.voice_phrase)
        self._show_break_dialog(snooze_remaining=snooze_remaining)

    def _on_reminder_due(self, name: str, event_at: datetime) -> None:
        self._event_log.record(EventType.REMINDER, Outcome.FIRED, name)
        if self._settings.voice_enabled:
            self._voice.speak(name)
        # Reminder dialog is owned by self so it isn't garbage-collected
        # before the user dismisses it. ``event_at`` arrives tz-aware
        # UTC from the scheduler; the dialog converts to local at
        # format time (S-06b).
        self._reminder_dialog = ReminderDialog(name=name, event_at=event_at)
        self._reminder_dialog.show()

    def _show_break_dialog(self, *, snooze_remaining: int) -> None:
        # If a dialog is already shown, don't stack a second one — just
        # bring the existing one to front.
        if self._active_break_dialog is not None and self._active_break_dialog.isVisible():
            self._active_break_dialog.raise_()
            return

        dialog = BreakDialog(
            snooze_remaining=snooze_remaining,
            voice_notifier=self._voice,
        )
        dialog.outcome_chosen.connect(self._on_break_outcome)
        self._active_break_dialog = dialog
        dialog.show()
        dialog.raise_()

    def _on_break_outcome(self, outcome_value: str) -> None:
        outcome = BreakOutcome(outcome_value)
        if outcome is BreakOutcome.TAKEN:
            self._apply_break_taken()
        else:
            self._apply_break_snoozed()

    def _on_break_interval_changed(self, new_interval: int) -> None:
        """Re-base the break cycle when the user saves a new break interval.

        Called from ``SettingsDialog.break_interval_changed``, which
        fires from ``accept()`` only when the persisted
        ``break_interval_min`` actually differs from the value the
        dialog was opened with. The slot resets the active-time
        accumulator and snooze state via
        ``BreakScheduler.reset_cycle()`` and refreshes the tray
        tooltip immediately so the user sees the new countdown
        without waiting for the next 5-second ``_tooltip_timer``
        refresh (S-09).

        Args:
            new_interval: The newly-persisted break interval in
                minutes. Currently unused — the scheduler reads the
                fresh threshold via ``self._settings.break_interval_min``
                on the next tick — but the signal carries it for
                future observers (e.g., a planned countdown overlay or
                event-log row).
        """
        del new_interval  # forward-compatibility; see docstring
        self._break_scheduler.reset_cycle()
        self._refresh_tooltip()

    def _apply_break_taken(self) -> None:
        """Shared 'user took a break' handler.

        Used by both the dialog flow (``_on_break_outcome``) and the tray
        Reset action (``_on_reset``). Centralising the post-action work
        here means Reset and the dialog can never drift apart on what
        "taken" means — same FR-015 record, same scheduler reset, same
        snooze-cap clear.
        """
        self._break_scheduler.on_break_taken()
        self._event_log.record(EventType.BREAK, Outcome.TAKEN)
        self._active_break_dialog = None
        # Re-arm the active-time tick so the next cycle accumulates.
        self._break_scheduler.start()
        self._refresh_tooltip()

    def _apply_break_snoozed(self) -> None:
        """Shared 'user snoozed the break' handler.

        Mirror of ``_apply_break_taken`` for the SNOOZED branch. Lives at
        the same level so future tray-side snooze actions (if added) can
        reuse it without duplicating the FR-015 / scheduler wiring.
        """
        self._break_scheduler.on_break_snoozed()
        self._event_log.record(EventType.BREAK, Outcome.SNOOZED)
        self._active_break_dialog = None
        self._break_scheduler.start()
        self._refresh_tooltip()


def main() -> int:
    """Process entry point — see ``__main__.py`` and ``main.py``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(APPLICATION_NAME)
    # Tray app: closing the settings window does NOT quit the process.
    qt_app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            APPLICATION_NAME,
            "No system tray detected. BreakReminder requires Windows 11's tray.",
        )
        return 1

    app = BreakReminderApp(qt_app)
    app.start()
    return qt_app.exec()
