# Version in "Check for updates" — Plan Brief

> Full plan: `context/changes/version-in-check-updates/plan.md`

## What & Why

Replace the silent "Check for updates" tray-menu redirect with a `QMessageBox` that shows the user the installed BreakReminder version + the app description, then gives them two buttons: "Open Releases" (the default — does today's browser hop) and "Close" (dismiss without browsing). Closes the user's literal request — "I would like user to see what is current version of application installed on his PC" — without growing the menu and without making a network call.

## Starting Point

The "Check for updates" `QAction` at [break_reminder/app.py:213-215](../../../break_reminder/app.py) currently fires the slot at [break_reminder/app.py:295-304](../../../break_reminder/app.py), which immediately calls `QDesktopServices.openUrl(QUrl(RELEASES_URL))` with no UI in between. The user has no way to see, from inside the app, which version they're running — they have to read the GitHub release page and trust their memory of when they installed.

## Desired End State

Clicking "Check for updates" pops a modal `QMessageBox` titled "About BreakReminder" that shows "BreakReminder v0.2.0" + the pyproject description + an action prompt, with "Open Releases" (default) and "Close" buttons. The browser only opens if the user clicks "Open Releases". The local-only NFR is preserved — no network call from inside the app.

## Key Decisions Made

| Decision                                | Choice                                                       | Why (1 sentence)                                                                                                                                              | Source |
| --------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| UX shape                                | Intercept the existing flow with a `QMessageBox`             | Closes the user's literal request without growing the menu and reuses the existing item label so muscle memory is preserved.                                  | Plan   |
| Dialog body                             | App name + version + pyproject description + action prompt   | Matches the `QMessageBox.about` idiom and uses the existing pyproject.toml description (single source of truth).                                              | Plan   |
| Button row                              | "Open Releases" (default) + "Close"                          | Preserves the existing one-click path to the browser (Enter still works) and gives a no-op exit for users who just wanted to check the version.               | Plan   |
| Network call to GitHub for "is newer?"  | Out of scope — local-only                                    | Preserves the local-only NFR, keeps the slot's existing docstring rationale intact, and matches the user's wording ("see what is current version").           | Plan   |
| Version source                          | `from break_reminder import __version__`                     | Already exists; same value the v0.2.0 release-prep commit kept in lockstep with `pyproject.toml` and the installer.                                           | Plan   |
| Description source                      | Hardcoded constant in `app.py` mirroring `pyproject.toml:4`  | Avoids runtime dependence on `importlib.metadata` (matters in editable / source-tree dev runs); a one-line constant with a sync comment is simpler.            | Plan   |

## Scope

**In scope:**

- Rewrite `BreakReminderApp._on_check_for_updates` to show the `QMessageBox` and branch on the clicked button.
- New module-level constant `_APP_DESCRIPTION` mirroring `pyproject.toml:4`.
- New import of `__version__` from `break_reminder`.
- New `TestCheckForUpdatesAction` test class with 5 tests (label, version-in-text, description-in-text, Open-opens-URL, Close-does-not-open).

**Out of scope:**

- GitHub API call to detect a newer release — local-only NFR preserved.
- Release-notes / changelog display in the dialog body.
- "About" tab inside `SettingsDialog`.
- Menu-item label, position, or shortcut changes.
- New menu items (no "About BreakReminder…" entry).

## Architecture / Approach

The slot becomes a thin "build a `QMessageBox`, run it modally, branch on the clicked button" function. Imports and constants live at module scope (`__version__`, `_APP_DESCRIPTION`); the slot itself is ~10-15 lines. Tests mirror `TestOpenSettingsAction`'s monkeypatch pattern — replace `break_reminder.app.QMessageBox` with a recording stub that lets each test pre-declare which button "was clicked", then trigger the `QAction` and assert on the conditional `QDesktopServices.openUrl` call.

## Phases at a Glance

| Phase                                  | What it delivers                                                                                                                                | Key risk                                                                                                                                         |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1. Intercept dialog + automated test   | Rewritten slot in `app.py`, new `_APP_DESCRIPTION` constant, new `TestCheckForUpdatesAction` class with 5 tests, all CI gates green.            | Stubbing `QMessageBox.clickedButton()` correctly is the only non-obvious bit; pattern-matched from `TestOpenSettingsAction` to de-risk.          |
| 2. Manual smoke + bookkeeping          | Human verification on the running tray; `change.md.status` flipped to `implemented`. No roadmap entry exists, so no roadmap edit.               | Smoke needs the user to actually click "Check for updates" against the running app — minor effort.                                               |

**Prerequisites:** v0.2.0 already shipped (the version constant the dialog displays). Local Python toolchain ready (`uv run pytest` works).
**Estimated effort:** ~30-45 minutes of implementation + ~5 minutes of human smoke.

## Open Risks & Assumptions

- The pyproject description string changes rarely; if it ever changes, the `_APP_DESCRIPTION` constant in `app.py` and the comment pointing at `pyproject.toml:4` keep them in obvious sync. Tolerated as low-friction.
- `QMessageBox` modal behavior is assumed (`QMessageBox.exec` is blocking by default) — matches the existing `QMessageBox.critical` use at `app.py:389-393`.
- The user opens the tray menu via right-click and clicks "Check for updates" — same path that exists today; no new surface to onboard the user to.

## Success Criteria (Summary)

- Clicking "Check for updates" shows the version + description before the browser opens.
- The browser only opens on explicit "Open Releases"; "Close" / Esc dismisses without browsing.
- The full automated test suite (existing + 5 new) stays green; CI gates (lint, format, type check, tests) pass on a single push.
