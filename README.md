# BreakReminder

A Windows-11 break reminder for phone-free, deep-focus workspaces.

> Tray-resident. Local-only. Notification cannot be reflexively dismissed.
> Doubles as a custom-reminder tool so it doesn't compete with a second app
> for the same desktop real estate.

This README is the developer entry point. The product spec lives at
[`context/foundation/prd.md`](context/foundation/prd.md). The conventions
agents must follow are in [`AGENTS.md`](AGENTS.md).

## Run from source

```powershell
uv sync
uv run python -m break_reminder
```

A tray icon should appear (look in the overflow menu — Windows 11 hides
new tray icons by default). Right-click for the menu.

## Test, lint, format

```powershell
uv run pytest
uv run ruff check
uv run ruff format
```

## Build a Windows installer locally

```powershell
uv run pyinstaller --noconfirm --windowed --name BreakReminder `
                   --collect-submodules pynput main.py
makensis installer\break-reminder.nsi
```

The installer lands at `installer\BreakReminder-Setup-<version>.exe`.

## Cut a release

Tag and push:

```powershell
git tag v0.1.0
git push --tags
```

GitHub Actions takes over from there — see
[`.github/workflows/release.yml`](.github/workflows/release.yml).
