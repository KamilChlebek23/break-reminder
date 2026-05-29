r"""Resolve per-user data paths via Qt's ``QStandardPaths``.

On Windows this lands at ``%APPDATA%\BreakReminder`` provided that the
QApplication has had its application name set first (see
``break_reminder.app.main``). Setting an organization name in addition
would make Qt nest ``%APPDATA%\<org>\<app>``, which would put us at
``%APPDATA%\BreakReminder\BreakReminder`` — functionally fine but
ugly. We deliberately leave the organization name unset; QSettings is
always constructed with an explicit path so it doesn't need one.

Failure to set the application name before the first ``QStandardPaths``
call is the most common cause of files landing in the wrong folder for
PyInstaller builds, where the executable name differs from the dev-time
module name.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

APPLICATION_NAME = "BreakReminder"


def app_data_dir() -> Path:
    """Return the per-user app-data folder, creating it on first call."""
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not location:
        # Fallback for environments where QStandardPaths refuses to answer
        # (rare; most often headless test runners). The PRD targets Windows
        # only, so this branch is defensive rather than functional.
        location = str(Path.home() / ".breakreminder")
    path = Path(location)
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_ini_path() -> Path:
    """Path to the BreakReminder settings INI file."""
    return app_data_dir() / "BreakReminder.ini"


def event_log_path() -> Path:
    """Path to the rotating event log (FR-015)."""
    return app_data_dir() / "events.log"


def reminders_json_path() -> Path:
    """Path to the custom-reminders JSON store (FR-011 / FR-012)."""
    return app_data_dir() / "reminders.json"


def app_lock_path() -> Path:
    """Path to the single-instance lockfile (S-10)."""
    return app_data_dir() / "app.lock"
