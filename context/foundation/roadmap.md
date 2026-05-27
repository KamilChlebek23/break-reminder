---
project: BreakReminder
version: 1
status: draft
created: 2026-05-25
updated: 2026-05-27
prd_version: 1
main_goal: low-complexity
top_blocker: none
---

# Roadmap: BreakReminder

> Derived from `context/foundation/prd.md` (v1) + auto-resolved baseline from `context/foundation/tech-stack.md` and the v0.1.0 release on 2026-05-21.
> Edit-in-place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Vision recap

BreakReminder is a Windows 11 tray-resident utility for focus-minded solo programmers who deliberately keep their phone out of the workspace and reflexively dismiss visual popups during deep focus. The product wedge — the one trait that, if removed, makes the product indistinguishable from a Windows toast — is that the break notification cannot be reflexively dismissed (no Esc, no Alt+F4, no click-outside, no focus-loss). The same widget doubles as a custom-reminder tool so the focus-protected workspace doesn't need a second app for adjacent jobs.

## North star

**S-01: settings-window-break-interval-only — user opens settings from the tray and edits the break interval, save, exit.** Under the `low-complexity` lens this is the smallest user-visible flow that closes a real must-have FR (FR-005 + FR-006) and unlocks the rest of v0.2.x in one evening.

> "North star" here means the smallest end-to-end user-visible slice whose successful delivery proves the v0.2.x increment is real — placed as early as Prerequisites allow because everything else only matters once the settings dialog exists.

## At a glance

| ID | Change ID | Outcome (user can …) | Prerequisites | PRD refs | Status |
|---|---|---|---|---|---|
| S-01 | settings-break-interval | open settings from tray and edit the break interval | — | FR-005, FR-006 | done |
| S-02 | settings-autostart-toggle | enable autostart-on-Windows-login from settings | S-01 | FR-003, FR-005 | done |
| S-03 | settings-snooze-config | edit snooze duration and max snoozes from settings | S-01 | FR-005, FR-010 | done |
| S-04 | settings-voice-toggle | enable voice notification and edit the voice phrase from settings | S-01 | FR-005, FR-007 | done |
| S-05 | reminders-list-view | see existing custom reminders in the settings dialog | S-01 | FR-005, FR-012 | done |
| S-06 | reminders-add-form | add a one-shot custom reminder with a name and a date/time | S-05 | FR-011, FR-013 | done |
| S-06b | reminders-lead-time | configure a reminder to fire N minutes (0-60) before the event | S-06 | FR-011, FR-013 | proposed |
| S-07 | reminders-edit-delete | edit and delete custom reminders in the list | S-06 | FR-012 | proposed |
| S-08 | reminders-recurrence-editor | configure a custom reminder to recur daily / weekly / monthly | S-06 | FR-014 | proposed |

## Streams

Navigation aid — groups items that share a Prerequisites chain. Canonical ordering still lives in `## Slices` below; this table is the proposed reading order across two parallel tracks once S-01 lands.

| Stream | Theme | Chain | Note |
|---|---|---|---|
| A | Settings panel | `S-01` → `S-02` / `S-03` / `S-04` (parallel after S-01) | Closes the four small must-have FRs that gate on a settings UI. After S-01, the three remaining are independent — pick whichever fits the next evening. |
| B | Custom reminders | `S-05` → `S-06` → `S-06b` / `S-07` / `S-08` (parallel after S-06) | Joins Stream A at `S-01` (the same QDialog hosts both tabs). Sequenced after Stream A's first slice but otherwise independent of S-02..S-04. |

## Baseline

What's already in place in the codebase as of 2026-05-25 (resolved from `context/foundation/tech-stack.md` and the v0.1.0 release on 2026-05-21). Foundations below assume these are present and do NOT re-scaffold them.

- **Frontend (PySide6 / Qt6):** present (partial). Tray icon + break dialog + reminder dialog all wired (`break_reminder/app.py`, `notifications/break_dialog.py`, `notifications/reminder_dialog.py`). Settings UI window is currently a placeholder `QMessageBox` per `tech-stack.md` "Known stubs" — that's what S-01 replaces.
- **Backend / API:** n/a. Local-only desktop app per PRD §Non-Goals.
- **Data:** present. `storage/settings.py` (QSettings INI), `storage/event_log.py` (CSV append + 1-MB rotation), `storage/reminders.py` (JSON CRUD with atomic writes), `storage/paths.py` (`%APPDATA%\BreakReminder` resolver).
- **Auth:** n/a. Single Windows user per PRD §Access Control.
- **Deploy / infra:** present. PyInstaller one-folder + NSIS + GitHub Actions `release.yml`. v0.1.0 published 2026-05-21; tag → CI → installer asset flow proven end-to-end.
- **Observability:** present (thin). `event_log.py` captures TAKEN / SNOOZED-PAST-CAP / MISSED + custom-reminder firings (FR-015). `main.py` bootstrap-panic logs failures to `%APPDATA%\BreakReminder\bootstrap-error.log`. No analytics surface that reads `events.log` and computes the Primary Success Criterion ratio (≥80% breaks taken in 7 days) — explicitly parked under `low-complexity`.

### FRs and US covered by v0.1.0 (out of scope for new slices)

The PRD must-have FRs and user stories below are **already shipped in v0.1.0** and do not appear in any slice's `PRD refs`. They are listed here for self-review traceability.

- FR-001 — install via downloadable installer (NSIS asset on Releases)
- FR-002 — uninstall preserves user data (NSIS leaves `%APPDATA%\BreakReminder` in place)
- FR-004 — tray icon + tooltip + right-click menu including Reset
- FR-008 — active-time accounting (`activity.py` + `scheduler.py`)
- FR-009 — non-dismissable break popup (`break_dialog.py`)
- FR-010 — snooze cap (functional in `scheduler.py` and `break_dialog.py`; settings UI lands in S-03)
- FR-013 — lightweight dismissable popup for custom reminders (`reminder_dialog.py` exists; exercised once S-06 ships data)
- FR-015 — event-log CSV rotation (`event_log.py`)
- FR-016 — pause/resume with reboot reset
- US-01 — programmer is reminded to take a break (full Given/When/Then exercised in v0.1.0)
- US-02 — programmer cannot reflexively dismiss (FR-009 hardening proven)

## Foundations

(none — under `low-complexity` + `none`-blocker, every slice is small enough to be its own self-contained unit, and the settings-dialog scaffold folds into S-01 rather than splitting into a separate cross-cutting foundation.)

## Slices

### S-01: settings-window-break-interval-only

- **Outcome:** user opens "Open settings…" from the tray menu and a real `QDialog` (not the placeholder `QMessageBox`) appears, showing the current break interval as an editable spinbox; "Save" persists to `%APPDATA%\BreakReminder\BreakReminder.ini` and closes the dialog; "Cancel" closes without saving.
- **Change ID:** `settings-break-interval`
- **PRD refs:** FR-005, FR-006
- **Prerequisites:** —
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:**
  - Should the dialog be tab-based (QTabWidget) or single-pane? Tab-based costs nothing now and pre-empts the layout question for S-02..S-05. — Owner: user. Block: no.
- **Risk:** low. The dialog is a one-field QDialog wrapping the existing `Settings.break_interval_min` getter/setter. The closest pattern in the codebase is `notifications/reminder_dialog.py` (similar simple modal). Time-to-ship is bounded by Qt-layout tinkering, which is well-known territory for the maintainer.
- **Status:** done

### S-02: settings-autostart-toggle

- **Outcome:** user opens settings, ticks "Launch BreakReminder at Windows login", saves; the per-user Run-key registry write actually fires; on next Windows login, BreakReminder appears in the tray without manual launch. Unticking removes the Run-key entry.
- **Change ID:** `settings-autostart-toggle`
- **PRD refs:** FR-003, FR-005
- **Prerequisites:** S-01 (the dialog scaffold)
- **Parallel with:** S-03, S-04, S-05
- **Blockers:** —
- **Unknowns:** —
- **Risk:** low. `tech-stack.md` "Known stubs" says "settings key wired; registry write not". The `winreg` module path is well-trodden; a per-user Run-key write is ~5 lines plus a delete-on-untick branch. The Windows registry is mockable via the `monkeypatch` pytest fixture for the unit-test side.
- **Status:** done

### S-03: settings-snooze-config

- **Outcome:** user opens settings, edits "Snooze duration (minutes)" (range 1–30) and "Max snoozes per cycle" (range 0–5), saves; the next break dialog respects the new values. **Scope addendum shipped**: the tray-icon tooltip now flips to `BreakReminder — snooze time left Xm YYs` while a snooze window is open (paused still wins).
- **Change ID:** `settings-snooze-config`
- **PRD refs:** FR-005, FR-010
- **Prerequisites:** S-01
- **Parallel with:** S-02, S-04, S-05
- **Blockers:** —
- **Unknowns:**
  - PRD Open Question #1 (snooze duration default 5 min) is currently unblocked by the working default; does S-03 collapse the question by giving the user a UI to set their own value, or does it remain open until self-observation lands? — Owner: user. Block: no. (dissolved by S-03 on 2026-05-26)
- **Risk:** low. Two spinboxes in the same dialog as S-01. `Settings.snooze_duration_min` and `Settings.max_snoozes` getters/setters already exist.
- **Status:** done

### S-04: settings-voice-toggle

- **Outcome:** user opens settings, ticks "Enable voice notification", optionally edits the spoken phrase, saves; voice now plays alongside the popup on the next break event.
- **Change ID:** `settings-voice-toggle`
- **PRD refs:** FR-005, FR-007
- **Prerequisites:** S-01
- **Parallel with:** S-02, S-03, S-05
- **Blockers:** —
- **Unknowns:**
  - PRD Open Question #3 (voice phrase content) is currently unblocked by the default "Time to take a break"; S-04 ships the user-configurable text option, which dissolves the question. — Owner: user. Block: no.
- **Risk:** low. Checkbox + line-edit in the same dialog. `notifications/voice.py` already exposes the toggle path; settings.py has the keys.
- **Status:** done

### S-05: reminders-list-view

- **Outcome:** user opens settings, switches to the "Reminders" tab/section, and sees a list (likely `QListView` or `QTableView`) of any custom reminders saved in `reminders.json`. List is read-only in this slice; "Add" / "Edit" / "Delete" buttons are present but disabled.
- **Change ID:** `reminders-list-view`
- **PRD refs:** FR-005, FR-012
- **Prerequisites:** S-01
- **Parallel with:** S-02, S-03, S-04
- **Blockers:** —
- **Unknowns:**
  - Should the list show next-firing time or just the recurrence rule string? Next-firing is more useful but requires evaluating RRULEs in the list model — a small extra cost. — Owner: user. Block: no. (dissolved by S-05 on 2026-05-27)
- **Risk:** low. Read-only list bound to `storage/reminders.py`'s existing CRUD layer. No new data flow; the reminders.json file is already opened on app start.
- **Scope addendum shipped**: dialog gained a 520-px minimum width to keep Reminders rows from horizontally scrolling on a fresh open (the other three tabs sized down to ~360 px and were unaffected).
- **Status:** done

### S-06: reminders-add-form

- **Outcome:** user clicks "Add" in the list view, a sub-dialog opens with "Name" + "Date/time" fields, "Save" persists to `reminders.json` and the list refreshes; at the saved date/time, the existing `reminder_dialog.py` fires as a dismissable popup. No recurrence yet.
- **Change ID:** `reminders-add-form`
- **PRD refs:** FR-011, FR-013
- **Prerequisites:** S-05
- **Parallel with:** S-02, S-03, S-04
- **Blockers:** —
- **Unknowns:** —
- **Risk:** low-to-medium. Touches more files than S-01..S-04: a new sub-dialog, a save path through `storage/reminders.py`, and a wakeup-arm path through `scheduler.py`'s `ReminderScheduler`. The latter is the only real risk surface — ensuring a freshly added reminder is armed in the running session, not just persisted to disk. The `next_firing_after()` helper in `scheduler.py` is the integration point.
- **Status:** done

### S-06b: reminders-lead-time

- **Outcome:** the Add Reminder form gains a "Notify (minutes before event):" `QSpinBox` (0-60, step 1, default 0). When the user sets a non-zero value, the datetime field is interpreted as the event time and the form computes `start_at = event_at - lead_minutes` at save; when the value is 0 (the default), behavior is identical to S-06. The Reminders list row shows the event time + "(fires N min before)" suffix when `lead_minutes > 0`; existing rows render unchanged.
- **Change ID:** `reminders-lead-time`
- **PRD refs:** FR-011, FR-013
- **Prerequisites:** S-06
- **Parallel with:** S-02, S-03, S-04, S-07, S-08
- **Blockers:** —
- **Unknowns:** —
- **Risk:** low. One field on `Reminder` (storage Model A: round-trip metadata, scheduler unchanged), one `QSpinBox` on the form, one branch in `_compose_row`. Backward-compatible — pre-S-06b `reminders.json` files load with `lead_minutes=0` (no migration). The only non-obvious site is the displayed-time switch in `_compose_row` from firing time to event time; pinned by tests.
- **Status:** proposed

### S-07: reminders-edit-delete

- **Outcome:** user clicks an existing reminder in the list and either "Edit" (opens the same dialog as S-06 pre-filled) or "Delete" (with a confirm); changes/removals are persisted to `reminders.json` and the running scheduler re-arms accordingly.
- **Change ID:** `reminders-edit-delete`
- **PRD refs:** FR-012
- **Prerequisites:** S-06
- **Parallel with:** S-02, S-03, S-04, S-08
- **Blockers:** —
- **Unknowns:** —
- **Risk:** low. The CRUD-edit and CRUD-delete code paths in `storage/reminders.py` already exist; this slice only adds UI affordances and the re-arm signal-flow.
- **Status:** proposed

### S-08: reminders-recurrence-editor

- **Outcome:** when adding or editing a reminder, the user can pick "Recurrence: none / daily / weekly / monthly" with a sensible default and an optional end date; the saved reminder fires on the configured cadence indefinitely (or until end date), proven by `next_firing_after()` advancing across firings.
- **Change ID:** `reminders-recurrence-editor`
- **PRD refs:** FR-014
- **Prerequisites:** S-06
- **Parallel with:** S-02, S-03, S-04, S-07
- **Blockers:** —
- **Unknowns:** —
- **Risk:** low. The RRULE engine in `scheduler.py` is already covered by 8 unit tests (per tech-stack.md); this slice translates UI selections into the RFC 5545 RRULE strings the engine accepts. The translation is small; the test coverage already exists.
- **Status:** proposed

## Backlog Handoff

| Roadmap ID | Change ID | Suggested issue title | Ready for `/10x-plan` | Notes |
|---|---|---|---|---|
| S-01 | `settings-break-interval` | Replace settings placeholder with real QDialog + break-interval edit | yes | Planned + shipped 2026-05-25 |
| S-02 | `settings-autostart-toggle` | Wire FR-003 autostart toggle to per-user Run registry key | yes | Planned + shipped 2026-05-26 |
| S-03 | `settings-snooze-config` | Add snooze duration + max snoozes to settings dialog | yes | Planned + shipped 2026-05-26 |
| S-04 | `settings-voice-toggle` | Add voice on/off + phrase editor to settings dialog | yes | Planned + shipped 2026-05-25 |
| S-05 | `reminders-list-view` | Reminders tab with read-only list bound to reminders.json | yes | Planned + shipped 2026-05-27 |
| S-06 | `reminders-add-form` | Add a one-shot custom reminder via sub-dialog | yes | Planned + shipped 2026-05-27 |
| S-06b | `reminders-lead-time` | Add "notify N min before event" lead-time spinbox to the add form | no | Run after S-06 |
| S-07 | `reminders-edit-delete` | Edit and delete entries in the reminders list | no | Run after S-06 |
| S-08 | `reminders-recurrence-editor` | Daily / weekly / monthly recurrence in the add/edit dialog | no | Run after S-06 |

## Open Roadmap Questions

1. **Snooze duration default value.** Lifted from PRD §Open Questions #1. Candidates: 5 / 10 minutes, or user-configurable. S-03 dissolves this once shipped (the user picks). — Owner: user. Block: S-03. (dissolved by S-03 on 2026-05-26)
2. **Active-time idle threshold.** Lifted from PRD §Open Questions #2. Default 60s. Affects FR-008 user-observable behavior + Notification-timing-accuracy NFR. Not currently surfaced in the settings UI. — Owner: user. Block: roadmap-wide if elevated to a slice; today, no slice depends on resolving it.
3. **Voice notification content.** Lifted from PRD §Open Questions #3. S-04 dissolves this. — Owner: user. Block: S-04. (dissolved by S-04 on 2026-05-25)
4. **AI/ML smart break-time prediction in v2.** Lifted from PRD §Open Questions #4. Out of v1 scope. — Owner: user. Block: no.
5. **Settings-dialog layout: tabbed or single-pane?** Surfaced during S-01 unknowns. Pre-emptively answering this saves rework on S-02..S-05 (each adds a new section). — Owner: user. Block: S-01.
6. **Reminders-list display: rule string or next-firing?** Surfaced during S-05 unknowns. — Owner: user. Block: S-05. (dissolved by S-05 on 2026-05-27)

## Parked

- **PRD §Non-Goals (lifted verbatim).** Cloud sync, mobile companion, calendar integration, Windows 10 / macOS / Linux support, posture / camera tracking, gamification, enterprise features, monetization / telemetry. All explicitly out of v1 per PRD lines 166–173.
- **FR-017: in-app break history view (charts/summaries).** PRD-deferred to v2; the `events.log` data feeds it when built. Today's compliance check happens via Excel inspection.
- **Code signing (Authenticode certificate / EV cert).** Documented as Category B in `context/foundation/infrastructure.md`. SmartScreen friction will be tolerated in v0.1.x and v0.2.x; revisit when adoption justifies the cost.
- **winget secondary distribution channel.** Runner-up to GitHub Releases per `infrastructure.md` Platform Comparison; v0.2.x or later.
- **Focus Assist + system-mute query (US-01 acceptance refinement).** Currently stubbed in `notifications/voice.py`; per AGENTS.md "implement when needed, until then `voice.is_blocked()` documents the contract". Lands when voice is observed firing during a meeting.
- **Snooze countdown affordance in the break dialog.** Listed in `tech-stack.md` "Known stubs"; UX polish, not a PRD must-have. Re-prioritize if `main_goal` flips to `quality`.
- **Primary Success Criterion observability (`--stats-7d` CLI or analytics surface).** The single quality-leaning slice the roadmap deliberately did NOT sequence under `low-complexity`. The data exists in `events.log`; pick this up when self-validation pressure crosses the actionability threshold (probably after a 1-month self-use stretch).
- **Verification slices: uninstall round-trip, bootstrap-panic fault-injection, single-machine smoke test.** Surfaced by the devil's-advocate exercise; explicitly deferred under `low-complexity` + `none`-blocker. Each is small enough to graduate from Parked to a slice if the maintainer decides to harden v0.1.x before extending v0.2.x.

## Done

- **S-05: user opens settings, switches to the "Reminders" tab/section, and sees a list (likely `QListView` or `QTableView`) of any custom reminders saved in `reminders.json`. List is read-only in this slice; "Add" / "Edit" / "Delete" buttons are present but disabled.** — Archived 2026-05-27 → `context/archive/2026-05-27-reminders-list-view/`. Lesson: when a feature relies on Qt-widget behaviour that varies by enabled-state (e.g. disabled `QPushButton` silently swallows `QEvent.ToolTip`), surface the behaviour in the plan's Critical Implementation Details and pin it with a wrapper-based test; promote UX-driven dialog-sizing values to named constants asserted by tripwire tests (the 520-px minimum width landed as a manual-verification retrofit, not a plan-time contract); and inject timezone-bearing parameters into pure-function formatters rather than monkeypatching `datetime`, so the conversion behaviour is observable on a UTC CI runner (see plan-review F1 + F5 and impl-review F1).
- **S-02: user opens settings, ticks "Launch BreakReminder at Windows login", saves; the per-user Run-key registry write actually fires; on next Windows login, BreakReminder appears in the tray without manual launch. Unticking removes the Run-key entry.** — Archived 2026-05-27 → `context/archive/2026-05-26-settings-autostart-toggle/`. Lesson: prefer create-or-open winreg primitives (`CreateKeyEx` over `OpenKey`) and enumerate every raise site of any exception a helper claims to swallow — local Windows dev hides the fresh-profile / no-subkey case the windows-latest CI runner exposes (see post-merge hotfix `8ec5850`).
- **S-01: user opens "Open settings…" from the tray menu and a real `QDialog` (not the placeholder `QMessageBox`) appears, showing the current break interval as an editable spinbox; "Save" persists to `%APPDATA%\BreakReminder\BreakReminder.ini` and closes the dialog; "Cancel" closes without saving.** — Archived 2026-05-27 → `context/archive/2026-05-25-settings-break-interval/`. Lesson: enumerate UX-side validation (silent clamp vs. visible feedback) separately from persistence-side validation, and promote shared-domain constants (range bounds) to a single source of truth in the persistence module on first cross-layer use rather than waiting for impl-review to retrofit (see retrospective plan-review F1 + F2).
- **Off-roadmap: show installed app version when user clicks "Check for updates" — tray menu pops a modal `QMessageBox` with `BreakReminder v<__version__>` + app description before optionally opening the GitHub Releases page (Open Releases / Close buttons; local-only NFR preserved, no network call).** — Archived 2026-05-27 → `context/archive/2026-05-25-version-in-check-updates/`. Lesson: —.
- **S-03: user opens settings, edits "Snooze duration (minutes)" (range 1–30) and "Max snoozes per cycle" (range 0–5), saves; the next break dialog respects the new values. Scope addendum shipped: the tray-icon tooltip now flips to `BreakReminder — snooze time left Xm YYs` while a snooze window is open (paused still wins).** — Archived 2026-05-27 → `context/archive/2026-05-26-settings-snooze-config/`. Lesson: cross-tab invariants (e.g., the atomic-save tripwire established by S-04's voice validation gate) belong in the plan's test contract for any slice that adds new persisted writes to `SettingsDialog.accept()`, and when mirroring a precedent test class enumerate ALL failure classes (out-of-range / boundary / clamp-high / clamp-low / unparseable) rather than just the obvious ones — both gaps caught at impl-review with no production impact (see retrospective plan-review F1 + F2).
- **S-04: user opens settings, ticks "Enable voice notification", optionally edits the spoken phrase, saves; voice now plays alongside the popup on the next break event.** — Archived 2026-05-27 → `context/archive/2026-05-25-settings-voice-toggle/`. Lesson: —.
