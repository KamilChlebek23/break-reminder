# BreakReminder — Tech Stack

> **Status: bootstrapped (manual).** The project was scaffolded by hand on 2026-05-19 because the chosen stack (Python + Qt6 / PySide6) is not in `/10x-tech-stack-selector`'s curated registry. This file is the canonical project stack reference; the off-registry caveat is preserved at the bottom.
>
> **`/10x-bootstrapper` is not applicable** — see `## Bootstrap status` for what actually landed and how to extend it.

## Chosen stack

| Layer | Choice | Resolved version |
|---|---|---|
| Language | Python | 3.12+ |
| GUI framework | PySide6 (Qt 6, LGPL — preferred over PyQt6's GPL/commercial dual licensing) | `>=6.11.1` |
| Project tooling | `uv` | (system-installed) |
| Activity hooks | `pynput` (global keyboard/mouse listeners) | `>=1.8.2` |
| Voice | `pyttsx3` (synchronous; runs on a worker thread) | `>=2.99` |
| Recurrence | `python-dateutil` (RFC 5545 RRULE) | `2.9.0.post0` |
| Win32 specifics | `pywin32` (Focus Assist, system mute) | `>=311` (`sys_platform == 'win32'`) |
| Build (binary) | PyInstaller (one-folder bundle) | `6.20.0` |
| Build (installer) | NSIS (`.nsi` script wraps the PyInstaller `dist/BreakReminder/`) | system-installed |
| Linter / formatter | Ruff | `0.15.13` |
| Test runner | Pytest | `9.0.3` |
| Distribution | GitHub Releases | — |
| CI | GitHub Actions (Windows runner; auto-deploy-on-merge — PR → checks → tag → build → publish) | — |

## Why this stack

A C-embedded developer with occasional Python experience picked Python + Qt6 over the registry-vetted alternatives (Tauri, Flutter) because it's the only choice that matches actual skills against a 3-week after-hours budget. Qt6 via PySide6 covers every load-bearing PRD requirement out of the box: `QSystemTrayIcon` for FR-004; modal `QDialog` with custom Esc / focus-loss handling for FR-009 (non-dismissable break notification); `QSettings` under `%APPDATA%` for FR-002 / FR-003 / FR-015; `QTimer` for FR-008's active-time tick; the full Qt widget toolkit for FR-005 / FR-006 / FR-011 / FR-012 / FR-014. Cross-cutting needs land in well-known Python packages: `pynput` for global keyboard/mouse hooks (FR-008), `pyttsx3` (or `Windows.Media.SpeechSynthesis` via `winrt`) for FR-007 voice, `pywin32` for Focus Assist and system-mute respect (US-01 acceptance). PySide6 is LGPL — clean for open-source distribution. Footprint: PyInstaller binary lands ~30–50 MB on disk, ~70–90 MB resident — comfortably under the < 100 MB RAM idle NFR. The user's 5/5 "no" on a Flutter self-check made the registry-pivot away from Python untenable; this is the deliberate course-correction.

## Captured priors and answers

| Field | Value |
|---|---|
| project | BreakReminder (kebab: `break-reminder`) |
| product_type | desktop |
| target_scale.users | small |
| timeline_budget.mvp_weeks | 3 |
| timeline_budget.after_hours_only | true |
| language_family | python |
| team_size | solo |
| has_auth | false |
| has_payments | false |
| has_realtime | false |
| has_ai | false |
| has_background_jobs | true (scheduler-shaped: in-process `QTimer` / `dateutil.rrule`, not a job queue) |
| Soft preferences | mainstream over niche; license-permissive (PySide6 over PyQt6) |
| Avoids | heavy runtimes (Electron / JVM) |
| deployment_target | github-releases (Windows `.exe` via PyInstaller + NSIS) |
| ci_provider | github-actions |
| ci_default_flow | auto-deploy-on-merge |
| Five-point self-check | 5 / 5 false on Flutter — triggered the off-registry pivot back to Python |

## Bootstrap status

The project is fully scaffolded as of 2026-05-19. What's on disk and what each piece does:

| Artifact | Purpose | FRs covered |
|---|---|---|
| `pyproject.toml` | Runtime + dev deps; Ruff and Pytest config; PyInstaller invocation comment. | — |
| `main.py` + `break_reminder/__main__.py` | Thin entry points (PyInstaller and `python -m` agree). | — |
| `break_reminder/app.py` | `QApplication`, `QSystemTrayIcon` + menu, top-level signal wiring. | FR-004 / FR-005 |
| `break_reminder/activity.py` | `pynput` keyboard/mouse listeners on a background thread, bridged into the Qt event loop via a `QObject` signal. | FR-008 (input layer) |
| `break_reminder/scheduler.py` | `BreakScheduler` (active-time counter, snooze, pause) + `ReminderScheduler` (RRULE-driven, `QTimer.singleShot` arming) + pure `next_firing_after()` helper. | FR-008, FR-010, FR-014, FR-016 |
| `break_reminder/notifications/break_dialog.py` | Non-dismissable break popup — every dismiss path (`Escape`, `Alt+F4`, `closeEvent`, focus-loss) is overridden; `WA_ShowWithoutActivating` so the in-flight keystroke completes in the IDE. | FR-009, US-02 |
| `break_reminder/notifications/reminder_dialog.py` | Deliberately dismissable popup for custom reminders. The split is the point. | FR-013 |
| `break_reminder/notifications/voice.py` | `pyttsx3` on a single-worker `ThreadPoolExecutor`; Focus Assist + system-mute gates stubbed with explicit `TODO(US-01)` markers. | FR-007 |
| `break_reminder/storage/paths.py` | Resolves `%APPDATA%\BreakReminder` via `QStandardPaths`. Org name deliberately unset to avoid Qt's `<org>\<app>` nesting. | FR-002, FR-015 |
| `break_reminder/storage/settings.py` | `QSettings(IniFormat)` wrapper. Single INI file for inspection in Notepad. Defaults for the three Open Questions live as constants. | FR-002, FR-003, FR-006, FR-010, FR-016 |
| `break_reminder/storage/event_log.py` | Append-only CSV with 1-MB rotation; thread-safe. | FR-015 |
| `break_reminder/storage/reminders.py` | JSON-backed CRUD with atomic writes; `Reminder` dataclass holds the optional `rrule_str`. | FR-011, FR-012, FR-014 |
| `tests/test_scheduler.py` | 8 unit tests covering the FR-014 RRULE engine (one-shot, daily, weekly, monthly, end-date, invalid-RRULE, naive-datetime). Pure-Python; no Qt event loop required. | FR-014 verification |
| `installer/break-reminder.nsi` | NSIS script wrapping `dist/BreakReminder/`. Per-user install. Uninstall preserves `%APPDATA%\BreakReminder` per FR-002. No Run-key (autostart is opt-in per FR-003). | FR-001, FR-002, FR-003 |
| `.github/workflows/release.yml` | Windows-runner CI: lint → test → PyInstaller → NSIS → publish to a GitHub Release on tag push. PRs run build-and-test only. | — |
| `AGENTS.md` | Stack-specific conventions for AI agents and humans (folder layout, threading rules, the FR-008/009/014 patterns, build/release commands). | — |

### Verification gates (all green at bootstrap time)

```powershell
uv sync                # 14 packages installed, lockfile clean
uv run pytest          # 8/8 passing
uv run ruff check      # All checks passed
uv run python -m break_reminder   # tray icon appears
```

### Known stubs

The bootstrap is a runnable skeleton, not a finished app. These are intentional gaps, marked in code with `TODO(FR-xxx)`:

- Settings / custom-reminder-CRUD UI (FR-005, FR-006, FR-011, FR-012). Tray menu has a placeholder `QMessageBox`.
- Focus Assist + system-mute query (US-01 acceptance). Stubs return `False` so voice always plays.
- Real tray-icon + window-icon resources. `QStyle.SP_ComputerIcon` is a placeholder.
- Autostart toggle (FR-003). The settings key is wired; the registry write is not.
- Snooze countdown affordance in the popup. The snooze action works; the visual countdown is missing.

## Off-registry caveat (preserved for context)

`/10x-tech-stack-selector`'s schema requires `starter_id` to be a key from `references/starter-registry.yaml`. The registry has no Python+desktop card. Writing a schema-conforming `tech-stack.md` with an off-registry `starter_id` would fail the bootstrapper validator (`scripts/validate-starter-registry-sync.mjs`). This file is therefore **not** schema-conforming — it captures the same information in human-readable form and is the deliberate alternative that doesn't pretend to be a machine hand-off.

If anyone wants to make this stack registry-vetted in the future, the path is to open a PR upstream to `przeprogramowani/10x-cli` adding a `pyside6-qt6` card (with `bootstrapper_confidence: best-effort` until verified end-to-end) and updating `recommended_defaults.desktop.python: pyside6-qt6`. Future projects in this cell would then land a valid `tech-stack.md` automatically and `/10x-bootstrapper` would be applicable.
