# BreakReminder — agent conventions

This file tells AI coding agents (and humans) the patterns to follow when extending BreakReminder. The PRD lives at `context/foundation/prd.md`; the stack rationale at `context/foundation/tech-stack.md`. This file is the bridge between them and the code.

## Stack at a glance

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | Matches the developer's actual skills, fits 3-week budget |
| GUI | PySide6 (Qt6, LGPL) | Tray icon, modal dialogs, settings, signals — all native |
| Project manager | uv | Modern, fast, the chosen tool |
| Activity hooks | pynput | Cross-platform global keyboard/mouse listener |
| Voice | pyttsx3 | Synchronous; runs on a worker thread |
| Recurrence | python-dateutil (RRULE) | RFC 5545; battle-tested |
| Win32 specifics | pywin32 | Focus Assist, system mute |
| Build | PyInstaller (one-folder) + NSIS | Lands ~30–50 MB on disk |
| Distribution | GitHub Releases | Tag → CI builds → publishes |

## Folder layout

```
break_reminder/         # importable package, snake_case
  __init__.py
  __main__.py           # python -m break_reminder
  app.py                # QApplication, tray, top-level wiring
  activity.py           # pynput → Qt signal bridge (FR-008)
  scheduler.py          # active-time counter + RRULE engine (FR-008, FR-014)
  notifications/
    break_dialog.py     # non-dismissable break popup (FR-009)
    reminder_dialog.py  # dismissable custom-reminder popup (FR-013)
    voice.py            # pyttsx3 + Focus Assist gate (FR-007)
  ui/
    settings_dialog.py  # FR-005/006 settings window
  storage/
    paths.py            # %APPDATA%\BreakReminder resolver
    settings.py         # QSettings (INI) wrapper (FR-002/003/006)
    reminders.py        # custom reminder CRUD (FR-011/012)
    event_log.py        # rotating CSV (FR-015)
tests/                  # pytest, no GUI deps required for unit tests
installer/              # NSIS .nsi script
resources/              # icons (tray icon rendered via QPainter today; placeholder for future bundled .ico)
.github/workflows/      # release.yml: tag → build → publish
main.py                 # thin entry; delegates to break_reminder.app.main
```

## Load-bearing patterns

These patterns are non-trivial and must be preserved across edits. If you change any of them, update this file.

### Where dialogs live — `notifications/` vs `ui/`

`notifications/` holds popups that fire on events — the break dialog (`break_dialog.py`) and the custom-reminder popup (`reminder_dialog.py`). `ui/` holds user-initiated configuration surfaces — settings (`settings_dialog.py`) and future custom-reminder editors (S-05..S-08 in `context/foundation/roadmap.md`). Keep the split crisp: an event-driven popup belongs in `notifications/`; anything the user opens deliberately belongs in `ui/`.

### FR-008 — active-time accounting (`activity.py` + `scheduler.py`)

The PRD says "count only active user time", not wall-clock. Mechanics:

1. `ActivityMonitor(QObject)` exposes a `Signal(activity_at: datetime)`.
2. `pynput.keyboard.Listener` and `pynput.mouse.Listener` run on a background thread (started by `pynput`'s own thread). On every event they call `monitor.activity_detected.emit(...)`. Qt's `AutoConnection` marshals the signal back to the GUI thread — that bridge is the whole point of using a `QObject` here. Do **not** mutate Qt widgets directly from the listener thread.
3. `BreakScheduler` listens to `activity_detected`, stores `last_input_at`, and runs a 1-second `QTimer`.
4. The timer tick computes `idle = now - last_input_at`. If `idle < idle_threshold_seconds` (default 60s, see Open Question #2), it advances `_active_seconds += 1`.
5. When `_active_seconds >= break_interval_minutes * 60`, the scheduler emits `break_due` and resets the counter. The connected slot opens the break dialog.

### FR-009 — non-dismissable break popup (`notifications/break_dialog.py`)

The "non-dismissable" property is implemented by overriding **every** dismiss path:

- `keyPressEvent` — swallow `Qt.Key_Escape`.
- `closeEvent` — `event.ignore()` unless the user clicked an action button (we set `self._user_action = True` first).
- Window flags — `Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint`. The `CustomizeWindowHint` removes the OS close button.
- Focus policy — `setFocusPolicy(Qt.NoFocus)` and `setAttribute(Qt.WA_ShowWithoutActivating, True)` so US-02's "in-flight keystroke completes in the IDE" acceptance criterion holds.

If you add a new way to dismiss the dialog (a button, a menu, a hotkey), it **must** route through `_user_action = True` before `accept()` / `reject()`.

The custom-reminder popup (`reminder_dialog.py`) deliberately does **not** apply any of this — FR-013 says custom reminders are dismissable. Don't bring the FR-009 hardening over to it.

### FR-014 — recurrence engine (`scheduler.py`)

Recurrence is stored as an iCalendar RRULE string (RFC 5545) on each reminder. To compute the next firing:

```python
from dateutil.rrule import rrulestr
rule = rrulestr(reminder.rrule_str, dtstart=reminder.start_at)
next_at = rule.after(now, inc=False)
```

**Do not** roll your own daily/weekly/monthly arithmetic. RRULE handles DST, month-end ("monthly on the 31st"), and end dates correctly; hand-rolled arithmetic will not.

Once `next_at` is known, the scheduler arms `QTimer.singleShot(ms_until_next, _fire_reminder)`. After firing, the scheduler computes the next occurrence and re-arms.

### FR-004 — tray quick-menu (`app.py`)

The system-tray right-click menu, in order:

1. **Take break now** — opens the modal break dialog with `snooze_remaining=0`. User must click "I'll take a break" to actually clear the cycle. Two clicks; logs a TAKEN event.
2. **Reset** — one-click equivalent. Bypasses the dialog, calls `_apply_break_taken()` directly. Same FR-015 logging, same snooze-cap clear, same scheduler re-arm.
3. **Pause / Resume** — single QAction whose label flips on `_refresh_tooltip()`. FR-016 lifecycle.
4. **Open settings…** — opens the FR-005 settings window (`ui/settings_dialog.py`). Currently exposes the FR-006 break-interval editor; S-02..S-08 add tabs for autostart, snooze, voice, and custom-reminder CRUD.
5. **Quit** — clean `QApplication.quit()`.

Take-break-now and Reset are **deliberately redundant**. They serve different mental models: "I'm taking a break" (dialog-confirmed, deliberate) vs "restart my timer" (one-click, no ceremony). Both record TAKEN in FR-015 so the Primary Success Criterion measurement (≥80% breaks taken) stays clean regardless of which the user picks. **Do not** "clean up" by removing one of them — see the FR-004 Socratic note in the PRD.

The `_apply_break_taken` / `_apply_break_snoozed` helpers are the shared backbone — both the dialog flow (`_on_break_outcome`) and the tray Reset (`_on_reset`) route through them. Future tray-side break actions should reuse the same helpers to avoid drift.

### Storage paths (`storage/paths.py`)

All persistent state lives under `QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)`. On Windows that resolves to `%APPDATA%\BreakReminder`. Set `QApplication.setApplicationName("BreakReminder")` **before** any `QStandardPaths` / `QSettings` call — otherwise Qt picks up the executable name and the path becomes wrong on PyInstaller builds. We deliberately do **not** set an organization name, because Qt would then nest `%APPDATA%\<org>\<app>`; `QSettings` is always constructed with an explicit path so it doesn't need one.

`QSettings` is configured with `IniFormat` so the file is `%APPDATA%\BreakReminder\BreakReminder.ini` rather than the registry. This honors FR-002 ("under the standard per-user app data folder") and FR-015's "human-readable in Notepad" principle.

### Voice notification (`notifications/voice.py`)

`pyttsx3` is **synchronous** — `engine.runAndWait()` blocks until speech completes. Always run it on a worker thread (use `concurrent.futures.ThreadPoolExecutor(max_workers=1)` to serialize).

Before speaking, gate on:

1. **Focus Assist** (US-01 acceptance): currently a stub returning `False`. The Windows API is `WTSQuerySessionInformation` with `WTSQuotaUsedAlerts`, or the newer `RtlQueryWnfStateData(WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED)`. Implement when needed; until then `voice.is_blocked()` documents the contract.
2. **System mute** — query via `pycaw` or `pywin32`'s `winrt`. Stub for now.

Voice playback **must stop** the moment the user clicks "I'll take a break" or "Snooze" (US-02 acceptance). The break dialog calls `voice.stop()` in its action handlers.

## Threading rules

- **Qt main thread** owns all widgets, timers, signals, settings reads/writes.
- **pynput listener threads** are spawned by pynput; they emit Qt signals to cross back. Never touch a `QWidget` from these threads.
- **Voice worker thread** is a dedicated `ThreadPoolExecutor`; only `pyttsx3.Engine` instances may live there.
- **No shared mutable state across threads without a lock.** All cross-thread comms goes through Qt signals.

## Build & release

Local dev requires Windows. `break_reminder/ui/settings_dialog.py` imports `winreg` (Windows-only stdlib) at module top to wire the FR-003 autostart Run-key write, so `uv run pytest` fails to collect on Linux/macOS. CI runs on `windows-latest`; tag-driven releases (below) build there as well.

```powershell
# Local dev
uv sync
uv run python -m break_reminder

# Run tests
uv run pytest

# Lint
uv run ruff check
uv run ruff format

# Type check (configured in [tool.pyright] in pyproject.toml)
uv run pyright

# Security audit — fails on any known CVE in installed packages
uv run pip-audit

# License gate — fails on AGPL (only license that would taint distribution).
# See release.yml for the rationale on why GPL build-tools are allowed.
uv run pip-licenses --fail-on="AGPL"

# Local PyInstaller build (produces dist/BreakReminder/)
uv run pyinstaller --noconfirm --windowed --name BreakReminder `
                   --collect-submodules pynput main.py

# Local installer build (requires NSIS on PATH)
makensis installer\break-reminder.nsi
```

Releases are cut by tagging:

```powershell
git tag v0.1.0
git push --tags
```

The GitHub Actions workflow `.github/workflows/release.yml` picks up the tag, builds on `windows-latest`, runs NSIS, and publishes the installer to a GitHub Release.

## Open questions blocking nothing but worth answering

- **Idle threshold (`N` in FR-008).** Default 60s. See PRD Open Question #2.
- **Snooze duration.** Default 5 min. See PRD Open Question #1.
- **Voice phrase.** Default `"Time to take a break"`. See PRD Open Question #3.

These are wired as `Settings` keys with defaults; flipping the default doesn't require a code change.

## What this scaffold does **not** yet implement

The bootstrap stops at runnable skeletons. The following are stubbed and clearly marked with `TODO(FR-xxx)`:

- Focus Assist + system-mute query (US-01 acceptance).
- Real tray-icon + window-icon resources (currently using `QStyle` defaults).
- Snooze countdown UI affordance (the snooze action works; the countdown display in the popup is a placeholder).

When you implement any of the above, remove the `TODO(FR-xxx)` and update this file.
