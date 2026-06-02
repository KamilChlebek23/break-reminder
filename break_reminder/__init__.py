r"""BreakReminder — a Windows-11 break reminder for phone-free workspaces.

The user-visible PRD lives at ``context/foundation/prd.md``. The conventions
agents must follow live at ``AGENTS.md``. This package implements the runtime.

## Modules

The sidebar memberlist on this page only lists symbols exposed by
``break_reminder/__init__.py`` itself (``__version__``). The rest of the
public API is split across the modules below — click through, or use the
search box top-left to jump to a specific class or function.

- [`break_reminder.app`](break_reminder/app.html) — QApplication, tray icon, top-level wiring.
- [`break_reminder.activity`](break_reminder/activity.html) — pynput → Qt signal bridge for active-time accounting (FR-008).
- [`break_reminder.scheduler`](break_reminder/scheduler.html) — active-time counter and RFC-5545 RRULE engine (FR-008, FR-014).
- [`break_reminder.notifications`](break_reminder/notifications.html) — break and custom-reminder popups (FR-009, FR-013) plus voice (FR-007).
- [`break_reminder.ui`](break_reminder/ui.html) — user-initiated configuration surfaces: settings dialog, reminder editor (FR-005, FR-006).
- [`break_reminder.storage`](break_reminder/storage.html) — INI settings, reminders JSON, event log CSV under ``%APPDATA%\BreakReminder\``.
"""

__version__ = "0.7.2"
__all__ = ["__version__"]
