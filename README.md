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
- **Custom reminders.** User-defined nudges — *"stand up at 11:00"*,
  *"drink water every hour during work days"* — fire as light,
  **dismissable** popups (FR-011, FR-012, FR-013, FR-014). Same widget,
  different severity, so the adjacent-job reminder rides on the
  break-reminder app rather than a second utility. Created from
  **Settings → Reminders**: name, date/time, optional 0-60 minute lead
  ("notify N minutes before the event"), and optional daily / weekly /
  monthly recurrence with an optional end date. See
  [Custom reminders](#custom-reminders) below.

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

BreakReminder currently ships unsigned (no Authenticode certificate yet).
On first run, Windows SmartScreen shows a blue dialog titled **"Windows protected your
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

There is no in-app auto-update channel. To upgrade:

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
- **Left-click** the icon: opens the [settings dialog](#settings).
- **Right-click** the icon: opens the full menu below.

### Tray menu

| Item | What it does |
|---|---|
| **Take break now** | Show the break dialog immediately. Counts as a break when you pick "I'll take a break". |
| **Reset** | Clears the active-time accumulator and snooze count without showing the dialog. Equivalent to "Take break now &rarr; I'll take a break", logged the same way. Does not change pause state. |
| **Pause** / **Resume** | Pause the timer entirely (no breaks fire while paused). Pause does **not** survive a reboot — the next boot starts unpaused per FR-016. |
| **Open settings…** | Opens the tabbed [settings dialog](#settings): Scheduling, Notifications, Lifecycle, Reminders. |
| **Check for updates** | Opens [Releases](#1-download) in your default browser. No HTTP call inside the app. |
| **Quit** | Exits BreakReminder. Closing the settings window does NOT quit; only this menu item or killing the process does. |

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

### Settings

BreakReminder's preferences live in a four-tab dialog opened via the
**Open settings…** tray menu item: **Scheduling** (break interval,
snooze duration, max snoozes), **Notifications** (voice on/off, voice
phrase), **Lifecycle** (autostart on Windows login), and **Reminders**
(custom-reminder list with Add / Edit / Delete). Clicking OK saves all
fields on the first three tabs atomically — if any field's validation
or registry side-effect fails, none of them are written. The Reminders
tab persists each Add / Edit / Delete immediately on its own button
(it does not participate in the OK save).

The dialog persists to `%APPDATA%\BreakReminder\BreakReminder.ini`;
you can also edit the file by hand and **restart BreakReminder** for
the changes to take effect, if you prefer the text-editor route. The
dialog and the file are equivalent surfaces over the same keys.

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

### Custom reminders

Beyond the break-cycle reminder, BreakReminder supports user-defined
custom reminders (FR-011 / FR-012 / FR-014) — e.g. *"stand up at
11:00"*, *"drink water every hour during work days"*. Manage them from
**Settings → Reminders**: each entry has a name, a date/time, an
optional 0–60 minute lead (fire N minutes before the event), and an
optional recurrence (none / daily / weekly / monthly) with an optional
end date. The list shows the next firing time per row plus a
`(daily)` / `(weekly)` / `(monthly)` suffix when recurrence is set;
expired one-shots sink to the bottom.

When a reminder fires, a **dismissable** popup appears with the
reminder's name and the original event time — `Esc`, the close button,
and click-outside all dismiss it. This is deliberate (FR-013): custom
reminders are advisory, not enforced. The non-dismissable hardening
applies only to the break dialog (FR-009).

Reminders persist to `%APPDATA%\BreakReminder\reminders.json` via
atomic writes (rename-replace). Schema reference for power users who
want to hand-edit the JSON:
[`break_reminder/storage/reminders.py`](break_reminder/storage/reminders.py).
Hand-edited custom RRULE strings (outside the picker's daily / weekly /
monthly vocabulary) round-trip safely — the recurrence picker locks
into a `(custom)` state with a **Reset to None** affordance until the
user explicitly opts back into the picker's choices.

### Event log

Every break taken, snoozed, or skipped is appended as a row to
`%APPDATA%\BreakReminder\events.log` (FR-015). The format is plain CSV so
it opens directly in Excel or any text editor. Logs rotate automatically
once they exceed a size threshold.

---

## Release history

Newest first. Dates are tag-push dates.

### v0.7.0 — 2026-05-28

S-08 + S-09. Daily / weekly / monthly recurrence on custom reminders
(FR-014); break-countdown bugfix on Settings save (FR-006, FR-008).

- **S-08 reminders-recurrence-editor**: the Add / Edit Reminder form
  gains a **Recurrence** picker (`none` / `daily` / `weekly` /
  `monthly`) and an optional **End date** field. Recurring reminders
  fire on the configured cadence indefinitely, or until the end date,
  via the existing RFC 5545 RRULE engine in
  `break_reminder/scheduler.py` (`next_firing_after`). The Reminders
  list now appends a `(daily)` / `(weekly)` / `(monthly)` suffix to the
  firing-time column. Hand-edited custom RRULE strings outside the
  picker's vocabulary round-trip safely: the picker locks into a
  `(custom)` state with a **Reset to None** affordance, so a
  power-user-authored RRULE is never silently dropped on Edit save.
- **S-09 bugfix-break-cycle-reset-on-save**: changing the break
  interval in **Settings → Scheduling** and clicking OK now resets the
  active-time accumulator and clears any in-flight snooze, so the tray
  countdown restarts cleanly from the new threshold (`Nm 00s`).
  Previously, the seconds digit appeared frozen on the prior cycle's
  offset because both old and new thresholds are minute-aligned, so
  `(threshold − active_seconds) mod 60` was independent of the
  threshold change; the next break consequently fired up to 59 seconds
  early or late relative to the new value. Reset only fires when
  `break_interval_min` actually changes — saving with only voice or
  snooze edits leaves the running cycle alone. The new
  `BreakScheduler.reset_cycle()` primitive backs both this path and
  the existing dialog-flow / tray-Reset path; behaviour is unchanged
  for the existing callers.

Test suite: 418 → 501.

### v0.6.0 — 2026-05-27

S-05, S-06, S-06b, S-07. New **Reminders** tab in the settings dialog
and the full custom-reminder CRUD surface (FR-011, FR-012, FR-013).
Stream B (custom reminders) is now complete.

- **S-05 reminders-list-view**: read-only list of every reminder saved
  in `%APPDATA%\BreakReminder\reminders.json`. Rows render the firing
  time + name. Add / Edit / Delete buttons are present but disabled —
  the scaffold S-06 and S-07 fill in. Dialog gained a 520-px minimum
  width so reminder rows don't horizontally scroll on a fresh open.
- **S-06 reminders-add-form**: **Add** opens a modal sub-dialog with
  Name + Date/time fields. Save persists to `reminders.json` via
  `ReminderStore.add`, re-arms the running session via
  `ReminderScheduler.reload`, and refreshes the list in place. At the
  saved instant, the existing dismissable `reminder_dialog.py` fires
  (FR-013). One-shot only — recurrence comes in S-08.
- **S-06b reminders-lead-time**: form gains a **Notify (minutes before
  event)** spinbox (0–60, default 0). When non-zero, the datetime
  widget is interpreted as the event time and the saved firing time is
  `event - lead`. The list row shows the event time + "(fires N min
  before)" suffix when lead > 0. Storage Model A keeps the scheduler
  unchanged — lead is round-trip metadata on the `Reminder`.
- **S-07 reminders-edit-delete**: Edit + Delete buttons now do what
  they say. **Edit** reopens the same form pre-filled (preserving id),
  with a past-time-gate skip when the user changed only the name or
  lead. **Delete** confirms with `QMessageBox.question` (default No)
  and removes the row + JSON entry. `OSError` on either path surfaces
  a transient tooltip and leaves the store byte-identical (atomic-save
  invariant).
- Storage hardening (impl-review F2 carry-in): hand-edited
  `reminders.json` entries that drop the `+00:00` UTC suffix are
  normalized via `_coerce_aware_utc` on load, so the Edit-mode
  past-time-skip comparison never raises `TypeError` on tz-naive disk
  values.
- Form-side DST fix (impl-review F3 carry-in): replaced the
  `datetime.now().astimezone().tzinfo` + `.replace` round-trip with a
  single `naive_local.astimezone(UTC)` call so a DST-spanning no-op
  Edit save doesn't falsely trip the past-time gate.

Test suite: 262 → 418.

### v0.5.0 — 2026-05-26

S-02 settings-autostart-toggle. New **Lifecycle** tab in the settings
dialog with a single "Launch BreakReminder at Windows login" checkbox
(FR-003).

- Ticking + OK writes the per-user
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\BreakReminder`
  registry value to `"<install path>"`; unticking + OK deletes it.
  No UAC prompt — per-user Run-key writes don't require elevation.
  Default off.
- Atomic save: any registry failure (group-policy block, ACL tampering,
  etc.) anchors a transient tooltip on the checkbox and blocks the
  entire OK save, leaving INI and registry both unchanged. Extends the
  v0.4.0 snooze-config atomic-save invariant to a fourth field.
- Closes the v0.1.0 "Known stubs" line for FR-003 — the settings key
  was wired since v0.1.0; the registry write is wired now.
- Stream A (settings panel) of the roadmap is now complete: FR-003
  (autostart), FR-006 (break interval), FR-007 (voice on/off + phrase),
  and FR-010 (snooze duration + cap) are all user-configurable from
  the dialog.
- Hotfix (post-tag): autostart helpers now handle the case where the
  `HKCU\...\Run` subkey doesn't pre-exist on the user profile (write
  uses `CreateKeyEx` to create-or-open; delete swallows
  `FileNotFoundError` from both `OpenKey` and `DeleteValue`).
  Surfaced by the v0.5.0 CI run on `windows-latest`, where the
  freshly-provisioned `runneradmin` profile had no Run subkey at all.

Test suite: 238 → 262.

### v0.4.0 — 2026-05-26

S-03 settings-snooze-config. **Scheduling** tab gains two spinboxes
for snooze parameters (FR-010), and the tray tooltip becomes
snooze-aware.

- New **Snooze duration (minutes)** spinbox (1–30) and **Max snoozes
  per cycle** spinbox (0–5; 0 = no snoozes, the break must be taken
  or missed). Closes PRD Open Question #1.
- Tray tooltip flips to `BreakReminder — snooze time left Xm YYs`
  while a snooze window is open, then back to the regular countdown
  when the snooze elapses or the user takes a break. Pause still wins
  (paused > snoozing > regular countdown).
- Setter validation on both new fields (`ValueError` on out-of-range);
  getter clamps for hand-edited corrupt INI values so an invalid file
  doesn't crash the app.

Test suite: 198 → 238.

### v0.3.0 — 2026-05-25

version-in-check-updates. The tray menu's **Check for updates** item
now displays the current app version inline (`Check for updates
(v0.3.0)`), so users can confirm what they're running without opening
a separate dialog.

### v0.2.0 — 2026-05-25

First real settings GUI. The **Open settings…** tray item now opens a
tabbed dialog instead of the v0.1.x INI-path placeholder.

- S-01 settings-break-interval. New **Scheduling** tab with the
  break-interval spinbox (FR-005, FR-006).
- S-04 settings-voice-toggle. New **Notifications** tab with a
  voice-on/off checkbox, editable phrase line edit, **Test voice**
  button, and a voice-empty-phrase validation gate (FR-007). Dissolves
  PRD Open Question #3.

Test suite: 33 → 198.

### v0.1.0 — 2026-05-21

First public release. Tray-resident, non-dismissable break reminder.

- Centered, non-dismissable break dialog (FR-008, FR-009). `Esc`,
  `Alt+F4`, click-outside, and focus-loss are all swallowed; the user
  picks "I'll take a break" or "Snooze".
- Active-time accounting: the timer counts only active keyboard /
  mouse input, pausing automatically when you walk away from the desk
  and resuming when you return (FR-008).
- Tray menu: Take break now / Reset / Pause / Open settings / Check
  for updates / Quit (FR-004).
- Pause does NOT survive a reboot — the next boot is unpaused (FR-016).
- INI-based settings under `%APPDATA%\BreakReminder\BreakReminder.ini`
  (the GUI shipped in v0.2.0).
- Per-user NSIS installer with no UAC prompt; settings preserved on
  uninstall (FR-002).

Test suite: 33.

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
