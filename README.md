# BreakReminder

A Windows-11 break reminder for phone-free, deep-focus workspaces.

> Tray-resident. Local-only. Notification cannot be reflexively dismissed.
> Doubles as a custom-reminder tool so it doesn't compete with a second app
> for the same desktop real estate.

## What BreakReminder is

A Windows 11 system-tray utility built to sit between you and the keyboard
during long stretches of focused work. The icon lives in the tray, the app
runs at &lt; 1% CPU and &lt; 100 MB RAM at idle, and it surfaces in two ways:

- **The break reminder.** After a configurable interval of *active*
  keyboard and mouse time (default 60 minutes), BreakReminder shows a
  centered, non-dismissable dialog (FR-008, FR-009). `Esc`, `Alt`+`F4`,
  click-outside, and focus-loss are all swallowed; you commit to "I'll
  take a break" or "Snooze". The dialog deliberately does **not** steal
  the keystroke you're in the middle of typing — the in-flight character
  lands where you intended it (US-02).
- **Custom reminders** *(coming in v0.2.x — not part of v0.1.x).*
  User-defined recurring nudges — *"stand up at 11:00"*, *"drink water
  every hour during work days"* — that will fire as light, **dismissable**
  popups (FR-013, FR-014). Same widget, different severity, so the
  adjacent-job reminder rides on the break-reminder app rather than a
  second utility. See [Custom reminders (v0.2.x scope)](#custom-reminders-v02x-scope)
  below for what currently exists on disk.

Both surfaces are local-only. No account, no cloud, no telemetry, no
outbound HTTP calls during normal operation. Settings, custom reminders,
and the break event log all live under `%APPDATA%\BreakReminder\` and are
**preserved across uninstalls** by design (FR-002).

## Why it exists

The product targets one specific failure mode: a focus-minded solo
developer who loses sense of time during long coding sessions and ends up
sitting in one position for hours. The cost is back and joint pain that
disappears when regular short breaks (light exercise, a walk) are taken.
The gap isn't the break itself — it's the nudge to take one.

Existing reminder tools fail some developers in two distinct ways:

- **Phone-based tools** (Pomodoro apps, smartwatches) assume the phone is
  at hand. Some developers deliberately distances their phone from the
  workspace to protect attention; a reminder that requires the phone
  defeats the setup that made deep focus possible in the first place.
- **PC-based visual popups** (Windows toasts, IDE plugins) get reflexively
  dismissed during deep focus without registering. The notification fires,
  the developer swipes it away on autopilot, nothing changes — the same
  rabbit-hole continues for another hour.

BreakReminder's wedge is the combination: PC-native so the phone stays
where you put it, non-dismissable so reflex-dismissal doesn't apply, and
dual-purpose so custom reminders ride on the same widget instead of
pulling you back into a second tool. The "non-dismissable" property is
the **design heart** of the product — without it, BreakReminder is just
another popup; with it, the popup is the one thing that survives deep
focus on autopilot.

End users: read [Install](#install) and [Using BreakReminder](#using-breakreminder).
Contributors and packagers: skip to [For developers](#for-developers).
The product spec lives at [`context/foundation/prd.md`](context/foundation/prd.md);
agent conventions are in [`AGENTS.md`](AGENTS.md); the v0.1.0 deployment runbook
is at [`context/deployment/deploy-plan.md`](context/deployment/deploy-plan.md).

---

## Install

### 1. Download

Open the Releases page and grab the latest installer:

> https://github.com/&lt;OWNER&gt;/break-reminder/releases/latest

Download `BreakReminder-Setup-<version>.exe` from the **Assets** section of
the topmost release. The file is roughly 50 MB; expansion on disk is about
120 MB after install.

### 2. First-run SmartScreen warning

v0.1.x ships unsigned (no Authenticode certificate yet). On first run,
Windows SmartScreen shows a blue dialog titled **"Windows protected your
PC — Unrecognized app"**. This is expected. Click **More info → Run anyway**
to proceed with the install. Code signing is on the roadmap; see the
SmartScreen risk row in [`context/foundation/infrastructure.md`](context/foundation/infrastructure.md).

### 3. What gets installed where

| Location | Contents | Notes |
|---|---|---|
| `%LOCALAPPDATA%\Programs\BreakReminder\` | The app binary + bundled Python + Qt6 DLLs | Per-user install, no UAC prompt |
| Start menu &rarr; **BreakReminder** | Launcher shortcut | Created automatically |
| `%APPDATA%\BreakReminder\` | Settings, custom reminders, event log | Created on first launch; **preserved on uninstall** |

### 4. System requirements

- Windows 11 (Windows 10 is untested and out of scope per the PRD non-goals).
- ~50 MB to download, ~120 MB on disk after install.
- No network access required at runtime — BreakReminder makes zero outbound
  HTTP calls. The "Check for updates" tray item opens your default browser
  to the Releases page; the app itself never phones home.

### 5. Updating to a new version

There is no auto-update channel in v0.1.x. To upgrade:

1. Right-click the tray icon &rarr; **Check for updates**.
2. Download the new `BreakReminder-Setup-<version>.exe` from the Releases
   page.
3. Run it; it overwrites the previous install in place. Your settings,
   custom reminders, and event log under `%APPDATA%\BreakReminder\` are
   preserved.

### 6. Uninstall

Settings &rarr; Apps &rarr; Installed apps &rarr; **BreakReminder** &rarr;
Uninstall. Your data folder at `%APPDATA%\BreakReminder\` is **left in
place** by design so a future re-install picks up where you left off. To
wipe everything, delete that folder manually after uninstalling.

---

## Using BreakReminder

After install, launch from the Start menu. A clock-face icon appears in
the system tray. Windows 11 hides newly-arrived tray icons under the
overflow chevron (`^`) by default — drag the BreakReminder icon out to the
always-visible part of the tray for at-a-glance access to the break
countdown tooltip.

### The tray icon

- **Hover** the icon: tooltip shows the time until the next break, e.g.
  `BreakReminder — next break in 23m 14s`. While a snooze is active, the
  tooltip reads `BreakReminder — snooze time left 4m 32s` and counts
  down to the moment the next break fires. When paused, the tooltip
  reads `BreakReminder — paused` (paused beats both regular and
  snoozing).
- **Left-click** the icon: opens the settings dialog (in v0.1.x this is a
  placeholder pointing you at the INI file — see [Settings](#settings-v01x)).
- **Right-click** the icon: opens the full menu below.

### Tray menu

| Item | What it does |
|---|---|
| **Take break now** | Show the break dialog immediately. Counts as a break when you pick "I'll take a break". |
| **Reset** | Clears the active-time accumulator and snooze count without showing the dialog. Equivalent to "Take break now &rarr; I'll take a break", logged the same way. Does not change pause state. |
| **Pause** / **Resume** | Pause the timer entirely (no breaks fire while paused). Pause does **not** survive a reboot — the next boot starts unpaused per FR-016. |
| **Open settings…** | In v0.1.x, surfaces a placeholder dialog with the path to the INI file. The full settings UI ships in v0.2.x. |
| **Check for updates** | Opens [Releases](#1-download) in your default browser. No HTTP call inside the app. |
| **Quit** | Exits BreakReminder. Closing the (placeholder) settings window does NOT quit; only this menu item or killing the process does. |

### The break dialog

When a break is due, BreakReminder shows a centered dialog with two
buttons — one to take the break, one to snooze (with the remaining
snooze count shown). The dialog is intentionally **non-dismissable**:

- `Esc` is ignored.
- `Alt`+`F4` is ignored.
- Clicking outside the dialog is ignored.
- Losing focus does not auto-close it.

You commit to one of the two buttons. This is FR-009 / US-02 — the whole
point of the app is that the popup is harder to swipe away than a plain
toast notification.

### Active-time accounting

The break timer counts only **active keyboard / mouse activity**. If you
walk away from the desk and the input idle time exceeds the configured
threshold, the timer pauses automatically and resumes when you return.
This means a "60-minute break interval" really means "60 minutes of focused
screen time", not 60 minutes of wall-clock time — which is the whole
distinction from Windows' native screen-time toast (FR-008).

### Settings (v0.1.x)

The settings UI is a placeholder in v0.1.x; the GUI ships in v0.2.x. Until
then, edit `%APPDATA%\BreakReminder\BreakReminder.ini` in any text editor
and **restart BreakReminder** for the changes to take effect.

The file uses standard INI section/key syntax. A complete example with
defaults:

```ini
[scheduling]
break_interval_min=60
idle_threshold_sec=60
snooze_duration_min=5
max_snoozes=1

[notifications]
voice_enabled=false
voice_phrase=Time to take a break

[lifecycle]
autostart=false
```

Keys and constraints:

| Key | Default | Range | What it controls |
|---|---|---|---|
| `scheduling/break_interval_min` | `60` | 1&ndash;240 | Minutes of active time between breaks. |
| `scheduling/idle_threshold_sec` | `60` | 1+ | Seconds of input inactivity that count as "away from desk" — the timer pauses above this. |
| `scheduling/snooze_duration_min` | `5` | 1+ | Minutes added when you click Snooze on the break dialog. |
| `scheduling/max_snoozes` | `1` | 0&ndash;5 | Consecutive snoozes allowed before the dialog stops offering Snooze and forces a break. |
| `notifications/voice_enabled` | `false` | `true`/`false` | Speak the phrase aloud (via Windows SAPI) when a break is due. Off by default. |
| `notifications/voice_phrase` | `Time to take a break` | any text | What the voice says when `voice_enabled=true`. |
| `lifecycle/autostart` | `false` | `true`/`false` | Launch BreakReminder on Windows login. Tickable from **Settings → Lifecycle tab** ("Launch BreakReminder at Windows login"); flipping the box writes (or deletes) the per-user `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\BreakReminder` value. Default off (FR-003 opt-in). |

Out-of-range values are silently clamped at read time, so a typo like
`break_interval_min=9999` becomes `240` rather than crashing the app.

### Custom reminders (v0.2.x scope)

Beyond the break-cycle reminder, BreakReminder will support user-defined
recurring reminders (FR-011 / FR-012) — e.g. *"stand up at 11:00"*, *"drink
water every hour during work days"*. The data file is created at
`%APPDATA%\BreakReminder\reminders.json` and is empty in v0.1.x; the
add/edit GUI ships in v0.2.x. Schema reference for power users who want to
hand-edit JSON early: [`break_reminder/storage/reminders.py`](break_reminder/storage/reminders.py).

### Event log

Every break taken, snoozed, or skipped is appended as a row to
`%APPDATA%\BreakReminder\events.log` (FR-015). The format is plain CSV so
it opens directly in Excel or any text editor. Logs rotate automatically
once they exceed a size threshold.

---

## For developers

The rest of this README covers building from source, running the test
suite, and shipping a release. Skip if you're an end user — everything
below assumes a working Python toolchain.

### Run from source

```powershell
uv sync
uv run python -m break_reminder
```

A tray icon should appear (look in the overflow menu — Windows 11 hides
new tray icons by default). Right-click for the menu.

### Test, lint, format

```powershell
uv run pytest
uv run ruff check
uv run ruff format
```

### Build a Windows installer locally

```powershell
uv run pyinstaller --noconfirm --windowed --name BreakReminder `
                   --collect-submodules pynput main.py
makensis installer\break-reminder.nsi
```

The installer lands at `installer\BreakReminder-Setup-<version>.exe`.

NSIS isn't always on PATH on a fresh dev box; if `makensis` isn't
recognised, install it via `winget install NSIS.NSIS` and add
`C:\Program Files (x86)\NSIS` to your `PATH`, then open a fresh PowerShell.

### Cut a release

Tag and push:

```powershell
git tag v0.1.0
git push --tags
```

GitHub Actions takes over from there — see
[`.github/workflows/release.yml`](.github/workflows/release.yml). The full
runbook including pre-flight checks, tag-push, smoke test, and roll-back
rehearsal lives at
[`context/deployment/deploy-plan.md`](context/deployment/deploy-plan.md).
