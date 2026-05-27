# Settings — Voice Toggle and Phrase Editor — Plan Brief

> Full plan: `context/changes/settings-voice-toggle/plan.md`

## What & Why

Add a "Notifications" tab to the existing `SettingsDialog` with three controls — an "Enable voice notification" checkbox, an editable "Voice phrase" line edit, and a "Test voice" button that previews the unsaved phrase. Closes FR-007's user-configurable voice surface (popup is mandatory; voice is opt-in additional channel) and dissolves PRD Open Question #3 by giving the user, not the spec, the final say on the spoken phrase.

## Starting Point

`SettingsDialog` (built in S-01) already hosts a `QTabWidget` with a single "Scheduling" tab — the tabbed layout was scaffolded for exactly this case. `Settings.voice_enabled` and `Settings.voice_phrase` getters exist and are already consumed by `BreakReminderApp._on_break_due` / `_on_reminder_due`, but neither has a setter, so today the only way to flip voice or change the phrase is hand-editing `BreakReminder.ini`. `VoiceNotifier` is owned by the app and ready to be injected into the dialog so the Test button can speak through the existing pyttsx3 worker pool.

## Desired End State

The user opens settings, sees two tabs, switches to Notifications, ticks the voice checkbox, edits the phrase, clicks **Test voice** to preview it through their speakers, clicks **OK**, and the next break event plays the popup AND the voice. The values persist across app restarts. If the user tries to save with voice enabled and a blank phrase, a transient tooltip surfaces below the phrase field and the dialog stays open — the (`enabled=true`, `phrase=""`) confused state never lands on disk.

## Key Decisions Made

| Decision                                             | Choice                                              | Why (1 sentence)                                                                                                                                                                                | Source |
| ---------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| Phrase preview surface                               | Test button next to phrase field                    | Lets the user hear the actual current text (including unsaved edits) without waiting for a real break event — closes the FR-007 confidence gap.                                                 | Plan   |
| Phrase editability when voice off                    | Always editable                                     | Removes a fiddly enable/disable toggle and lets the user prepare the phrase before flipping the gate; an empty phrase is harmless when voice is off.                                            | Plan   |
| Empty-phrase save while voice on                     | Block save with inline tooltip                      | Reuses S-01's transient `QToolTip.showText` pattern and prevents a confused (`voice_enabled=true`, `phrase=""`) state from ever persisting.                                                     | Plan   |
| Communicating "voice is additive, not a replacement" | Tooltip on the voice checkbox                       | Conveys the popup-is-always-mandatory contract once, where the user is already paying attention; avoids permanent banner real estate.                                                           | Plan   |
| `VoiceNotifier` plumbing                             | Required keyword-only kwarg on `SettingsDialog`     | Defaulting to a fresh `VoiceNotifier()` would bind pyttsx3's speech engine in every test that constructs the dialog — forcing a stub at the call site keeps the test suite fast and audio-free. | Plan   |
| `voice_phrase` setter validation                     | Permissive (accepts any string, including empty)    | The dialog enforces non-empty-when-enabled at the UI layer — duplicating the rule in the setter would make a future "reset to defaults" call fight itself.                                      | Plan   |
| Re-arm signal on save                                | None — values read live on every event              | `_on_break_due` and `_on_reminder_due` already read `Settings.voice_*` per event, so changes apply on the next break with zero new wiring.                                                      | Plan   |

## Scope

**In scope:**

- `voice_enabled.setter` and `voice_phrase.setter` on `Settings` with Google-style docstrings.
- New "Notifications" tab on `SettingsDialog` with checkbox, phrase line edit, Test button, and tooltip on the checkbox.
- `accept()` validation: voice-on + blank phrase blocks save and surfaces the existing tooltip pattern.
- `VoiceNotifier` injection through the dialog constructor (required keyword-only kwarg).
- One-line wiring in `BreakReminderApp._on_open_settings`.
- Automated tests: setter round-trips, tab load, tab save, validation, Test-button behaviour, layout, and `_voice` injection identity.

**Out of scope:**

- Volume / rate / system-voice controls; per-event phrase override.
- Decoupling break-voice and reminder-voice (FR-007 + FR-013 keep them under one global gate).
- Async / threaded preview, keyboard shortcut for Test, phrase length cap, Focus Assist hint.
- Any change to FR-007 wiring at `app.py:307-315` (already reads the values live).
- Any other setters (autostart is S-02, snooze is S-03).

## Architecture / Approach

`Settings` gets two thin setters mirroring the `break_interval_min.setter` shape (no validation — the dialog owns the non-empty-when-enabled rule). `SettingsDialog` gains a new `_build_notifications_tab` builder, a new `_on_test_voice_clicked` slot, and an extended `accept()` that runs validation BEFORE persistence and short-circuits via early return when validation fails. The Test button calls `VoiceNotifier.speak` directly with the line edit's current text — no intermediate state, no save side-effect. Tests inject a stub voice notifier so the suite never instantiates a real pyttsx3 engine.

## Phases at a Glance

| Phase                                                    | What it delivers                                                                                                                                            | Key risk                                                                                                                                          |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Notifications tab + voice setters + automated coverage | Two `Settings` setters, the new tab with all three widgets, validation in `accept()`, the one-line `app.py` wiring, and the matching test classes.          | The `voice` injection becomes a required kwarg — every existing dialog test must update its fixture in lockstep or `TestLoad` etc. start failing. |
| 2. Manual smoke + roadmap bookkeeping                    | Audio-on smoke through a real break event; roadmap S-04 → done; PRD Open Question #3 annotated as dissolved; `change.md` flipped to `implemented`. | Smoke needs a working speaker on the dev machine; without audio, the FR-007 path can't be validated.                                              |

**Prerequisites:** S-01 (`settings-break-interval`) shipped — this slice extends the same dialog. Local dev machine must have a working audio output for Phase 2.
**Estimated effort:** ~1 implementer session for Phase 1, ~10 minutes of human smoke for Phase 2.

## Open Risks & Assumptions

- The `voice` constructor kwarg becoming required is an internal-API break. Acceptable because `SettingsDialog` has exactly one production caller (`app.py`) and the test fixtures live in this repo — no external consumers.
- `pyttsx3` is assumed to be available at runtime. Already a hard dep per `pyproject.toml`; if a future packaging change strips it, the Test button (and the existing `_on_break_due` voice call) breaks together — same blast radius as today.
- The smoke step assumes the user changes `break_interval_min` to a short value (e.g., 2 minutes) and restores it afterwards. Captured explicitly in the manual checklist.

## Success Criteria (Summary)

- A non-technical user can enable, customize, and preview the spoken break phrase entirely through the GUI — without ever editing `BreakReminder.ini`.
- The (`voice_enabled=true`, `voice_phrase=""`) confused state cannot land on disk through the dialog.
- The full automated test suite (existing + new) stays green; CI gates (lint, format, type check, tests) pass on a single push.
