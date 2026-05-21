---
project: "BreakReminder"
version: 1
status: draft
created: 2026-05-19
context_type: greenfield
product_type: desktop
target_scale:
  users: small
  qps: low
  data_volume: small
timeline_budget:
  mvp_weeks: 3
  hard_deadline: null
  after_hours_only: true
---

# BreakReminder — Product Requirements Document

## Vision & Problem Statement

A focus-minded solo programmer on Windows 11 loses sense of time during deep coding sessions and stays in one position too long. The cost is back and joint pain that disappears when regular short breaks (light exercise + walk) are taken — so the gap isn't the break itself, it's the nudge to take one. Existing break reminders fail in two ways: phone-based tools (Pomodoro apps, smartwatches) assume the phone is at hand, but this user deliberately distances their phone to protect attention; PC-based tools (OS notifications, IDE plugins) are visual-only popups that get dismissed reflexively during deep focus without registering.

The wedge is a PC-native break reminder shaped for phone-free workspaces — designed so a programmer in deep flow cannot simply swipe it away without noticing. The same tool also doubles as a lightweight personal reminder (e.g., "Visit to dentist") so it doesn't compete with a second app for the same desktop real estate.

## User & Persona

**Primary persona** — *Focus-minded solo programmer on Windows 11.*

Works long focused coding sessions; deliberately keeps phone away from workspace to protect attention; experiences back and joint pain when breaks are skipped; runs a Windows 11 PC as their primary workstation. They reach for BreakReminder when they realize after-the-fact that they've gone hours without moving, and want a tool that cannot be reflexively dismissed and doesn't require their phone.

Scope: built for the developer first; shaped to be shareable with a small hobbyist niche of like-minded focus-protectors (distributed openly via a public release page, no signup, no cloud).

## Success Criteria

### Primary

- In a 7-day stretch of installed daily use, the user takes ≥ 80% of triggered breaks (i.e., responds to the notification by getting up / moving, rather than dismissing without action). This is the literal outcome the product exists to produce.

### Secondary

- Custom reminders feature gets real use: ≥ 3 active custom reminders configured after one month — proves the "two-purposes-in-one-widget" design is worth shipping over a single-purpose break timer.
- Voice notification mode is preferred over popup-only after a week of trial — validates the audio-channel insight that visual popups are too easy to dismiss reflexively.

### Guardrails

- **No data leak.** No personal data (custom reminders, schedule, usage stats, break history) ever leaves the device. Local-first is a hard floor.
- **No destructive interrupt.** Notifications must not steal focus from a fullscreen editor mid-keystroke or auto-trigger loud audio during a video call. The "hard to dismiss but not destructive" balance is the design heart of the product.
- **Settings persist across reboots and updates.** Losing user state once would erode trust permanently.
- **Low resource footprint.** The app runs at < 1% CPU and < 100 MB RAM at idle. The app must not contribute to the system fatigue it's trying to prevent.

## User Stories

### US-01: Programmer is reminded to take a break during deep focus

- **Given** the programmer has BreakReminder installed and configured with a chosen break interval (e.g., 60 minutes)
- **And** the programmer has been actively working at their PC since the last break
- **When** the configured interval elapses
- **Then** BreakReminder fires the configured notification (popup, voice, or both)
- **And** the notification persists until the programmer performs a deliberate action (clicks "I'll take a break" or "Snooze")
- **And** if the programmer takes the break, BreakReminder records the event as "taken"
- **And** if the programmer snoozes past the max snooze count or dismisses without action, BreakReminder records the event as "missed"

#### Acceptance Criteria

- Notification is NOT cleared by Escape, click-anywhere-else, Alt+F4, or focus-loss
- Voice notification respects system mute and Windows Focus Assist (no loud audio during a video call or presentation)
- Snooze is available at most N times per break cycle, where N is user-configurable (default 1)
- Taken/missed events are persisted to local storage so they can later feed the break history (see FR-015)

### US-02: Programmer cannot reflexively dismiss a break notification

- **Given** BreakReminder has fired a break notification
- **And** the programmer is in deep focus (e.g., fullscreen IDE, fast typing)
- **When** the programmer reflexively presses Escape, clicks outside the notification, or hits Alt+F4
- **Then** the notification does NOT clear
- **And** the only way to clear it is an explicit click on "I'll take a break" or "Snooze"
- **But** the notification does NOT steal keystrokes from the focused application during the keystroke in flight

#### Acceptance Criteria

- Escape, click-outside, Alt+F4, and global focus-change events do not dismiss the notification
- The notification window does not steal keyboard focus from the user's IDE/editor (the in-flight keystroke completes in the previously focused app)
- Voice playback stops the moment the user interacts with the notification
- Voice volume never exceeds the user's current system volume; if Focus Assist is active, voice mode falls back to popup-only

## Functional Requirements

### Installation & lifecycle

- FR-001: User can install BreakReminder on Windows 11 via a downloadable installer obtained from a public open-source release page. Priority: must-have
  > Socratic: Counter considered: "portable .exe is simpler" / "MSIX reaches more users". Resolution: stands as written; an open-source release-page installer matches the hobbyist-niche distribution model and gives a clean uninstall hook in Windows Apps & Features.
- FR-002: User can uninstall BreakReminder; uninstall removes the binaries but preserves user data (settings, custom reminders, break history) under the standard per-user app data folder so a reinstall resumes without reconfiguration. Priority: must-have
  > Socratic: Counter considered: "delete settings on uninstall". Resolution: revised — keep settings on uninstall (standard "don't make me reconfigure" pattern). User can manually delete the per-user app data folder for a true wipe.
- FR-003: BreakReminder can be configured to launch automatically on Windows startup; **default is OFF**. User opts in via the settings panel. Priority: must-have
  > Socratic: Counter considered: "autostart is annoying — user might be on weekend gaming with no need for breaks". Resolution: revised — autostart is opt-in (default off); the toggle exists, but the user must enable it explicitly.

### Tray icon & UI surface

- FR-004: BreakReminder presents itself as a Windows system tray icon. The icon's tooltip shows the time until next scheduled break; left-click opens the main settings/reminders window; right-click shows a quick menu (Pause, Resume, Take break now, Reset, Open settings, Quit). Priority: must-have
  > Socratic: Counter considered: "a visible desktop widget with countdown is itself distracting" / "tray icon is lighter and less obtrusive". Resolution: revised — tray icon replaces the always-visible widget. Rationale: a constantly-visible countdown defeats flow protection (the thing the product is meant to enable). Material change from seed idea ("Application is widget") — confirmed by user during Socratic round.
  > Socratic (added 2026-05-20): "Reset" is a deliberate convenience duplicate of "Take break now". Counter considered: "isn't this just redundant with Take break now?" / "won't users be confused by two buttons that do the same thing?". Resolution: kept both. Rationale: "Take break now" routes through the FR-009 modal dialog (deliberate-action confirmation, two clicks); "Reset" is a one-click shortcut for users whose mental model is "restart my timer" rather than "I'm taking a break". Both routes record a TAKEN event in FR-015, so the Primary Success Criterion measurement (≥80% breaks taken) stays clean regardless of which entry the user picks. Reset is intentionally NOT a silent counter clear — that interpretation would have weakened FR-009's non-dismissable wedge by becoming a pre-emptive escape hatch.
- FR-005: User can open a main window from the tray icon to access settings and the custom reminders list. Priority: must-have
  > Socratic: Counter considered: "settings could live in a config file; zero UI to build". Resolution: stands as written — the UI is the product; config-file-only would push BreakReminder into the "CLI tool I'll forget to use" category. (Note: break history view scoped out of FR-005 during budget reconciliation; deferred to FR-017 / v2.)

### Break scheduling & notifications

- FR-006: User can configure the break interval as a free-text number of minutes (valid range: 1–240) via the main settings window. Priority: must-have
  > Socratic: Counter considered: "fixed 60-min interval is simpler and matches research" / "free-text entry instead of presets". Resolution: revised — free-text minute entry (1–240); more flexible than presets, same UI complexity.
- FR-007: A popup notification is always fired on a break event; voice notification is an optional additional layer the user can enable in settings. Priority: must-have
  > Socratic: Counter considered: "popup-only matches Windows native UX" / "voice should be required for the wedge to work". Resolution: revised — popup is mandatory (the default channel everyone gets); voice is opt-in additional channel for users who find popups too easy to ignore. Captures both ends of the counter without the all-or-nothing tradeoff.
- FR-008: BreakReminder counts only *active* user time (keyboard / mouse input within the last N seconds) toward the break interval. When the active-time counter reaches the configured break interval, BreakReminder fires the notification. Idle time (no input) does not advance the counter. Priority: must-have
  > Socratic: Counter considered: "wall-clock is simpler" / "should check idle / should count only active typing". Resolution: revised — count only active user time. Rationale: a meeting where you're listening (no input) shouldn't accumulate "sitting in focus" time; without this, the product fires notifications when no break is needed and erodes trust. Material scope addition: requires Windows keyboard/mouse activity hooks. Acknowledged budget cost. (The exact value of N is an Open Question — see #2.)
- FR-009: The break notification cannot be reflexively dismissed — the user must perform a deliberate action (e.g. click "I'll take a break" or "Snooze") to clear it. Priority: must-have
  > Socratic: Counter considered: "aggressive design risks breaking workflow" / "power users will kill the process". Resolution: stands as written — this IS the product wedge; without it, BreakReminder is just another popup app. US-02 guards against the lost-keystroke failure mode. Killable-by-Task-Manager is an acceptable escape valve (a user motivated enough to kill the process has self-selected out of the persona).
- FR-010: User can snooze a break notification (configurable max snoozes per cycle, default 1, maximum 5), after which it re-fires and snooze is unavailable until the user takes a break. Priority: must-have
  > Socratic: Counter considered: "snooze undermines non-dismissable design" / "without snooze users will kill the app instead". Resolution: stands as written — user explicitly accepts snooze as the necessary pressure valve. Without it, the only way to "not take this break right now" is to kill the app, which means the next break is also missed. Capped snoozes prevent indefinite deferral. (Snooze duration in minutes is an Open Question — see #1.)
- FR-016: User can pause and resume break reminders (e.g., during a meeting or a deep focus block); paused state persists until explicitly resumed or until next reboot. Priority: must-have
  > Socratic: Counter considered: "pause = unlimited snooze" / "should be auto-triggered by meeting detection". Resolution: stands as written — explicit manual pause with reboot-reset prevents the "forgot to resume" failure mode. Auto-detect-meeting could land in v2 once the manual pause baseline is proven.

### Custom reminders

- FR-011: User can add a custom reminder with a name (e.g. "Visit to dentist") and a date/time. Priority: must-have
  > Socratic: Counter considered: "second product bolted on; ship pure break-reminder first" / "Windows Calendar already handles this". Resolution: stands as written — the wedge is "one PC-native widget, no phone, no second app"; splitting custom reminders out to Calendar would violate that wedge and force the persona back to a second tool.
- FR-012: User can list, edit, and delete custom reminders from the main UI. Priority: must-have
  > Socratic: Counter considered: "config file editing would suffice for the hobbyist persona". Resolution: stands as written — list/edit/delete is the minimum usable CRUD surface; without it, FR-011 is dead on arrival.
- FR-013: When a custom reminder's time arrives, BreakReminder fires a **lightweight, dismissable popup** (with optional voice if the user has enabled voice globally). This is intentionally *less* aggressive than the break notification (FR-009) — the user must be informed of the reminder, but not blocked. Priority: must-have
  > Socratic: Counter considered: "custom reminders should NOT use non-dismissable design — a dentist reminder shouldn't lock the screen" / "popup-only for custom reminders". Resolution: revised — split notification severity by event type. Break notifications use FR-009's non-dismissable design (the focus protection wedge); custom reminders use a normal, dismissable popup. Keeps the wedge sharp for the *one* thing that needs it.
- FR-014: User can configure a custom reminder to recur (daily / weekly / monthly), with sensible defaults (start time, end date optional). Priority: must-have
  > Socratic: Counter considered: "don't put v2 features in PRD" / "promote to must-have because most useful custom reminders are recurring (daily standup, weekly retro, monthly bills)". Resolution: revised — promoted from nice-to-have to must-have. Without recurrence, the custom-reminders feature is half-baked; the most natural reminders for a programmer (standup, retro, monthly bills) all need recurrence.

### Break event logging & history

- FR-015: BreakReminder persists every break event (taken / snoozed / missed) and every custom reminder firing to a structured local log file under the per-user app data folder (one event per row, including timestamp, event type, and outcome). The file format is human-readable enough to inspect with Notepad or open in Excel for compliance review. Priority: must-have
  > Socratic: Counter considered: "history UI" vs "log file only". Resolution: split — log file is must-have (cheap to add, preserves data for the Primary success criterion via external inspection); the in-app history view is split out as FR-017 below and deferred to v2.
- FR-017: User can view an in-app break history with charts/summaries of taken vs missed breaks over time. Priority: nice-to-have (v2)
  > Socratic: Counter considered during budget reconciliation. Resolution: deferred to v2. The data captured by FR-015 in v1 will feed this UI when it's built. Compliance validation in v1 happens via external inspection of the log file.

## Non-Functional Requirements

- **Resource footprint.** On a typical Windows 11 workstation, BreakReminder's idle CPU usage stays below 1% and its resident memory stays below 100 MB over any 5-minute window when no notification is being fired.
- **Local-only data.** No user data (settings, custom reminders, break events, activity statistics) leaves the device. The app makes no outbound network calls during normal operation. Network connectivity is not required for any feature.
- **Notification timing accuracy.** When the user's accumulated active time crosses the configured interval, the user perceives the break notification within 5 seconds of the crossing.
- **Install friction.** From completing the installer download to the tray icon appearing in the system tray, the user performs no more than 2 clicks beyond the OS's standard UAC prompt.
- **First-run sanity.** A user who installs BreakReminder and ignores all settings can take their first triggered break without opening any configuration UI — defaults are functional out of the box.
- **Update safety.** An in-place update of BreakReminder preserves all user state (settings, custom reminders, break event log) and does not silently change any user-configured value (interval, notification mode, pause state, voice on/off, autostart toggle).

## Business Logic

BreakReminder decides that a break is due when the user's accumulated keyboard/mouse activity since the last break exceeds their configured interval, and enforces the nudge with a notification that cannot be cleared without a deliberate user action.

The rule consumes two user-facing inputs: the user's configured break interval (in minutes), and the user's ongoing keyboard/mouse activity at the PC. Idle time — periods when the user is not interacting with the PC — does not advance the accumulation counter; the rule effectively measures "time spent in focused work" rather than wall-clock elapsed time. When the accumulated active time crosses the threshold, BreakReminder produces an enforced break notification as its output: a popup (always) plus optional voice (if the user has enabled voice in settings), that requires the user to click a deliberate action button ("I'll take a break" or "Snooze") to clear. Reflexive dismiss gestures (Escape, click-outside, Alt+F4, focus-loss) do not clear it.

The user encounters this rule when they are working in deep focus on their PC. The notification surfaces at the moment the rule has decided a break is due — not when a wall-clock timer expires, not when the user remembers, not when their phone rings. Custom reminders (FR-011 to FR-014) use a parallel but lighter rule: when a custom reminder's scheduled time arrives, BreakReminder fires a dismissable popup (the wedge does not apply to non-break reminders).

## Access Control

Single user per Windows account; no authentication, no cloud, no signup.

Each Windows user on the PC gets their own isolated BreakReminder state (settings, custom reminders, notification preferences, break event log) automatically — by storing everything under the standard per-user app data location. This gives a "shared device with multiple users" behavior for free, without an in-app profile picker.

Flat permission model inside the running app: one user, one set of settings. No admin/viewer split, no roles.

## Non-Goals

- **No cloud sync or cross-device profile sharing.** BreakReminder is local-first; each Windows account is its own island. Settings do not roam across machines.
- **No mobile companion app, smartwatch integration, or any phone-side surface.** The product wedge is "phone-free workspace"; adding a phone surface would directly violate it.
- **No external calendar integration in v1** (Outlook, Google Calendar, etc.). Custom reminders are managed entirely inside BreakReminder; they do not sync to or read from any external calendar.
- **No Windows 10, macOS, or Linux support in v1.** Windows 11 only. Cross-platform expansion is a v2+ conversation, contingent on demand.
- **No posture, eye-tracking, camera, or microphone-based activity detection.** Keyboard and mouse input are the only signals used to determine active time. Avoids privacy concerns and hardware dependencies.
- **No gamification** (streaks, badges, leaderboards, achievement points). BreakReminder is a health tool, not a habit-tracker; gamification would erode the seriousness of the break enforcement.
- **No enterprise features.** No MDM packaging, no group policy, no central admin, no team rollouts. Hobbyist-niche distribution only.
- **No monetization, paywall, or telemetry for business purposes.** BreakReminder is free; no tracking, ever. Source openly available to the public.

## Open Questions

1. **Snooze duration.** How long does each snooze postpone the break notification? Candidates: fixed 5 minutes, fixed 10 minutes, or user-configurable (e.g., 1–30 minutes). Affects FR-010. Owner: user. Block: no (a sensible default like 5 minutes lets the MVP ship; revisit after first week of use).
2. **Active-time idle threshold (`N` in FR-008).** What window of input-free time counts as "idle" and pauses the active-time accumulation? Candidates: 30 seconds, 60 seconds, 2 minutes. Affects FR-008's user-observable behavior and the Notification-timing-accuracy NFR. Owner: user. Block: no (default 60s is reasonable; tune after self-observation).
3. **Voice notification content.** When voice mode is enabled, what does BreakReminder say? Candidates: a fixed phrase ("Time to take a break"), the reminder name read aloud (for custom reminders), or a user-configurable phrase per reminder. Affects FR-007 and FR-013. Owner: user. Block: no.
4. **AI/ML "smart" break-time prediction in v2.** During shaping, this was deliberately NOT added to Non-Goals — leaving it ambiguous whether it's a deferred future feature or simply unaddressed. Should v2 explicitly plan for activity-aware/ML-driven break timing, or should it be ruled out for consistency with the "deterministic, explainable rule" stance? Owner: user. Block: no (post-MVP decision).
