---
date: 2026-06-02T10:10:00+02:00
researcher: Kamil Chlebek (via Cursor)
git_commit: ca3d258
branch: test/testing-modal-stacking-wedge
repository: break-reminder
topic: "R-2 modal-stacking wedge — FR-009 break popup vs sibling top-level dialogs"
tags: [research, R-2, FR-009, US-02, dialog, modality, pytest-qt, test-plan-phase-2]
status: complete
last_updated: 2026-06-02
last_updated_by: Kamil Chlebek (via Cursor)
---

# Research: R-2 modal-stacking wedge

**Date**: 2026-06-02 10:10 +02:00
**Researcher**: Kamil Chlebek (via Cursor)
**Git Commit**: ca3d258
**Branch**: test/testing-modal-stacking-wedge
**Repository**: break-reminder

## Research Question

R-2 from `context/foundation/test-plan.md` §2:

> *"The FR-009 non-dismissable break popup is on screen but its action buttons cannot be clicked because a sibling top-level dialog (Settings, custom-reminder form, another popup) traps input first. User clears the popup by closing Settings — directly violating US-02 acceptance ('the only way to clear it is an explicit click on I'll take a break or Snooze')."*

Three nested questions:

1. What is the runtime cause of the wedge across the four dialogs (`BreakDialog`, `SettingsDialog`, `ReminderDialog`, `ReminderFormDialog`)?
2. What pytest-qt test shape *actually* proves protection against it (i.e., would fail on the current buggy code and pass after the fix)?
3. What invariants must the eventual fix preserve to satisfy PRD constraints FR-009 / US-02 / FR-013?

## Summary

Three headline findings that change the test-plan's stated approach. Each is load-bearing for `/10x-plan`.

1. **R-2 has a structural cause that S-01's plan explicitly predicted and deferred.** Every dialog in BreakReminder is constructed with `parent=None` — the S-01 (`settings-break-interval`) plan's documented intent for taskbar-entry uniformity. `SettingsDialog.exec()` therefore activates Qt's modal scope without a parent chain to limit it to, so a subsequent sibling `BreakDialog.show()` is on top visually (`WindowStaysOnTopHint`) but its input is routed to the modal Settings event loop. S-01's plan-brief explicitly recorded under Open Risks: *"if `break_due` fires while settings is `.exec()`'d, the user sees both dialogs … left to organic v0.2.x discovery if it surfaces as a real-world annoyance."* Q2 is that discovery. R-2 is overturning a deliberate, documented decision.

2. **The test shape originally specified in test-plan §2 R-2 ("QTest.mouseClick on popup buttons while sibling dialogs are open") gives a false negative.** Agent C empirically demonstrated this: with `SettingsDialog` set `Qt.ApplicationModal` and on screen, `QTest.mouseClick` on `BreakDialog`'s "I'll take a break" button DOES close the popup. The same operation fails at runtime against real OS mouse input. Reason: Qt's offscreen `QTest.mouseClick` synthesizes input *inside* the Qt object model, bypassing the platform-level event routing that the modal `.exec()` loop hijacks. **The R-2 regression test must assert a STRUCTURAL invariant, not a BEHAVIORAL one** — the original "Anti-pattern to avoid" framing in test-plan §2 R-2 (`assertion on visibility only`) was correct but didn't go far enough; the click-honored assertion is *also* contaminated by the test-input pathway.

3. **Two different modality regimes coexist** that R-2 must distinguish:
   - **Unparented + `.exec()`** — `SettingsDialog` (`app.py:343`, no parent). The wedge case Q2 reported.
   - **Parented + `.exec()`** — `ReminderFormDialog` only (`settings_dialog.py:944`/`:995`, `parent=self` which is `SettingsDialog`). It inherits Settings' modal scope by parent chain; the wedge against `BreakDialog` may behave differently and needs separate verification.
   - **Unparented + `.show()`** — `BreakDialog` (`app.py:407`) and `ReminderDialog` (`app.py:397`). Both modeless top-levels; only `BreakDialog` has a singleton guard.

The plan stage (`/10x-plan`) will choose among three candidate fix shapes (see [Open Questions](#open-questions)) and write the structural assertion test that pins the chosen invariant.

## Detailed Findings

### 1. Per-dialog modality + window-flag inventory (Agent A)

| Dialog | Launched via | Modality (explicit) | Parent at construct | Window flags | Window attributes | Focus policy | Action-button locators |
|---|---|---|---|---|---|---|---|
| `BreakDialog` (FR-009) | `.show()` (modeless) | None set explicitly | `None` | `Qt.WindowStaysOnTopHint \| Qt.CustomizeWindowHint \| Qt.WindowTitleHint` | `Qt.WA_ShowWithoutActivating` | `Qt.NoFocus` | **No `objectName` / no `accessibleName`**; identified only by visible text. The "Snooze" button text is dynamic (`"Snooze (N left)"`). Buttons set `setAutoDefault(False)`. |
| `SettingsDialog` | `.exec()` (Qt's `ApplicationModal` event loop) | None set explicitly (`.exec()` makes the loop modal) | `None` | Default | Default | Default | n/a (not in the wedge frame) |
| `ReminderDialog` (FR-013, dismissable) | `.show()` (modeless) | None set explicitly | `None` | Default | Default | Default | n/a |
| `ReminderFormDialog` | `.exec()` from inside `SettingsDialog` | `self` = `SettingsDialog` | Default | `Qt.WA_DeleteOnClose` | Default | n/a |

**Key inventory facts** (verified across the four dialog source files):

- **None** of the four files call `setModal(...)` or `setWindowModality(...)`. Modality is purely a function of `.show()` vs `.exec()`.
- **None** of the four files call `setObjectName(...)` or `setAccessibleName(...)` on action buttons. Test code must match by visible text (and `BreakDialog`'s Snooze text is dynamic).
- **`BreakDialog` is uniquely hardened**: the only one with `WA_ShowWithoutActivating` + `Qt.NoFocus` + button `setAutoDefault(False)`. This is the FR-009 hardening pattern documented in `AGENTS.md` ("non-dismissable break popup"). The hardening intentionally suppresses focus-stealing so an in-flight IDE keystroke completes uninterrupted — but the *same* properties (no focus, no activation) compound the wedge: the popup is even less able to receive input when a sibling modal loop is consuming it.

### 2. Production call-site map (Agent B)

| Dialog | Construct site | Parent | Show method | Trigger |
|---|---|---|---|---|
| `BreakDialog` | `break_reminder/app.py:407` | `None` | `.show()` | `BreakScheduler.break_due` signal **and** tray "Take break now" action |
| `SettingsDialog` | `break_reminder/app.py:343` | `None` | `.exec()` | Tray "Open settings…" action **and** left-click on tray icon |
| `ReminderDialog` | `break_reminder/app.py:397` | `None` | `.show()` | `ReminderScheduler.reminder_due` signal |
| `ReminderFormDialog` (Add) | `break_reminder/ui/settings_dialog.py:944` | `self` (the open `SettingsDialog`) | `.exec()` | Settings "Add reminder" button |
| `ReminderFormDialog` (Edit) | `break_reminder/ui/settings_dialog.py:995` | `self` (the open `SettingsDialog`) | `.exec()` | Settings "Edit reminder" button |

**Multiplicity / guard analysis:**

- `BreakDialog` has the **only** real singleton guard in the codebase: `break_reminder/app.py:400-405` checks `self._active_break_dialog` + `isVisible()` and raises-to-front instead of constructing a second one. Two break popups stacking is therefore impossible at the source.
- `SettingsDialog` has **no guard** — only modality protects against double-open. Two `.exec()` loops can't run from the same Qt thread, so this is de-facto single-instance, but nothing in code enforces it.
- `ReminderDialog` has **no guard at all**. Two `reminder_due` signals firing close together will stack two popups on screen, and only the most recent is tracked in `self._reminder_dialog`. This is a separate latent bug (call it R-2-adjacent) that R-2's test surface might incidentally surface.
- **No app-wide dialog registry exists.** `self._active_break_dialog` is the only tracked handle anywhere.

### 3. Reproduction smoke (Agent C) — **the critical finding**

Agent C wrote and ran a throwaway `tests/_smoke_modal_wedge.py` (since deleted; repo is byte-identical) with two tests:

- **Test A (control)**: `BreakDialog` alone, `QTest.mouseClick` on "I'll take a break" → assert popup closed. Pinned the baseline.
- **Test B (wedge)**: `SettingsDialog` set `setModal(True)` + `Qt.WindowModality.ApplicationModal` + `.show()` (modality-equivalent to production's `.exec()`, but without blocking the test thread), then `BreakDialog.show()` on top, then `QTest.mouseClick` on the "I'll take a break" button.

Result:

```
============================= test session starts =============================
PySide6 6.11.1 -- Qt runtime 6.11.1 -- Qt compiled 6.11.1
plugins: qt-4.5.0
collected 2 items

tests\_smoke_modal_wedge.py ..                                           [100%]

============================== 2 passed in 0.59s ==============================
```

**Both tests passed.** With a fully application-modal `SettingsDialog` on screen, `QTest.mouseClick` on `BreakDialog`'s action button still closed the popup. Agent C separately verified the same with `QAbstractButton.click()` — identical outcome.

**Diagnosis**: `QTest.mouseClick` synthesizes input *inside* Qt's object model. The modal `.exec()` loop and Qt's `ApplicationModal` policy gate **OS-level** mouse / keyboard events (delivered via the platform plugin), not Qt-internal `postEvent` calls. So `QTest.mouseClick` will reach the BreakDialog's button regardless of any modal sibling — and the production bug, which is driven by real OS mouse input being routed to the modal Settings event loop, never appears.

**Implication for the test plan**: the wedge cannot be asserted by clicking the popup button in pytest-qt. It must be asserted **structurally**:

- Option I: assert "after a `break_due` fire path, BreakDialog and SettingsDialog are never co-visible." (Tests the fix that ensures they're never co-displayed in production.)
- Option II: assert "after BreakDialog is shown, `BreakDialog.windowModality() == Qt.ApplicationModal`." (Tests the fix that escalates BreakDialog to application-modal on fire.)
- Option III: assert "after `break_due` fires while SettingsDialog is open, SettingsDialog.isVisible() is False (the app closed it)." (Tests the fix that explicitly closes sibling dialogs.)

The chosen invariant depends on `/10x-plan`'s fix-shape decision (see [Open Questions](#open-questions)).

### 4. Historical decisions R-2 is overturning (Agent E)

#### 4.a Q2 verbatim — the lived incident

The Q2 quote anchoring R-2's "High / High" rating in test-plan §2 lives only in this session's transcript (no archived `*.md` file persists it):

> *"I noticed when popup is fired eg. one reminding about break, edition of settings becames impossible. To clear popup, settings must be closed before."*

Captured in the `/10x-test-plan` Phase 2 interview at `agent-transcripts/4ae0c3ee-7c57-4f71-812d-9003e3725aba/4ae0c3ee-7c57-4f71-812d-9003e3725aba.jsonl` (2026-06-01).

#### 4.b S-01 (`settings-break-interval`) — the decision being overturned

This is the most important historical artifact. The S-01 plan-brief explicitly predicted the wedge and deferred it:

- `context/archive/2026-05-25-settings-break-interval/plan-brief.md:75` (Open Risks):
  > *"if `break_due` fires while settings is `.exec()`'d, the user sees both dialogs. Documented under 'What we're NOT doing'; left to organic v0.2.x discovery if it surfaces as a real-world annoyance."*

- `context/archive/2026-05-25-settings-break-interval/plan.md:29` (Key constraints):
  > *"Concurrent `break_due` during `SettingsDialog.exec()` is **benign**: the break dialog is `.show()`-modeless with `Qt.WindowStaysOnTopHint`, so it appears on top of the modal settings dialog. No special-casing needed in this slice; out-of-scope behavior call left to organic v0.2.x."*

- `context/archive/2026-05-25-settings-break-interval/plan.md:52` (What we're NOT doing):
  > *"No settings-while-break-dialog handling … Concrete UX impact deferred to organic v0.2.x discovery."*

- `context/archive/2026-05-25-settings-break-interval/plan.md:53` (parent=None rationale):
  > *"`parent=None` matches `BreakDialog` / `ReminderDialog` so the dialog gets its own taskbar entry."*

**The S-01 plan's assumption was wrong**: "`WindowStaysOnTopHint` + visible on top = clickable." It conflated *Z-order* (visibility on top) with *input routing* (whether mouse events reach the popup). Test-plan §2 R-2 "Must challenge" already calls this out: *"The `WindowStaysOnTopHint` on the break popup is a Z-order hint, not an input-modality override."* This research confirms that framing empirically.

#### 4.c S-06 (`reminders-add-form`) — the second modality regime

`ReminderFormDialog` is the only dialog in the codebase that is parented and `.exec()`-launched. The S-06 plan flagged this as a new convention:

- `context/archive/2026-05-27-reminders-add-form/plan.md:15`:
  > *"`notifications/reminder_dialog.py:24-55` is the closest precedent for a small modal form … but it's `show()`-based in production — **there is no existing modal sub-dialog launched with `exec()` from inside another dialog in the codebase. S-06 establishes that convention.**"*
- `context/archive/2026-05-27-reminders-add-form/plan.md:89`, `:222`: `ReminderFormDialog(parent=self).exec()`.

S-06 did **not** weigh the new convention against `break_due` firing concurrently — FR-009 was out of scope.

#### 4.d PRD constraints the fix must preserve

- `context/foundation/prd.md:71-86` (US-02 acceptance):
  > *"Escape, click-outside, Alt+F4, and global focus-change events do not dismiss the notification … the only way to clear it is an explicit click on 'I'll take a break' or 'Snooze'."*
- `context/foundation/prd.md:114-115` (FR-009).
- `context/foundation/prd.md:127-128` (FR-013):
  > *"custom reminders use a normal, dismissable popup … Keeps the wedge sharp for the *one* thing that needs it."*

  **Load-bearing constraint**: R-2 cannot symmetrise away the bug by promoting `ReminderDialog` to non-dismissable. The asymmetry is by design.

#### 4.e Phase 1 → Phase 2 handoff note

- `context/archive/2026-06-01-testing-rrule-reminder-loop/research.md:232` (Open Question #4):
  > *"R-2's anchors live in the dialog layer (`break_reminder/notifications/break_dialog.py`, `break_reminder/notifications/reminder_dialog.py`, `break_reminder/ui/settings_dialog.py`) and are properly Phase 2's research scope."*

  Note the omission: `ui/reminder_form_dialog.py` is NOT in this list — Phase 2 research adds it as Finding 4.c above.

#### 4.f Release-gate smoke gap

- `context/deployment/deploy-plan.md:131`:
  > *"Wait for or trigger a break dialog; verify Esc / Alt+F4 / click-outside / focus-loss do NOT dismiss it (FR-009 / US-02)."*

  The only existing FR-009 verification exercises a **single dialog in isolation** — it never opens Settings/ReminderForm first. R-2 was uncovered by the release-gate smoke, which is why the Q2 incident only surfaced post-release.

## Code References

### Production code surface that R-2 touches

- `break_reminder/app.py:343` — `SettingsDialog` construct + `.exec()` (no parent). Modal scope is `ApplicationModal` without parent chain.
- `break_reminder/app.py:397` — `ReminderDialog` construct + `.show()` (no parent). FR-013 dismissable popup; no singleton guard.
- `break_reminder/app.py:400-405` — **The only singleton guard in the app**: `_active_break_dialog + isVisible()` raise-to-front for `BreakDialog`. Future fix may need to extend this pattern to handle sibling dialogs too.
- `break_reminder/app.py:407` — `BreakDialog` construct + `.show()` (no parent). The popup whose input is wedged.
- `break_reminder/notifications/break_dialog.py` (FR-009 hardening per AGENTS.md, line numbers in source):
  - Window flags: `Qt.WindowStaysOnTopHint | Qt.CustomizeWindowHint | Qt.WindowTitleHint`
  - `setAttribute(Qt.WA_ShowWithoutActivating, True)`
  - `setFocusPolicy(Qt.NoFocus)`
  - Buttons: `setAutoDefault(False)`; no `objectName` / no `accessibleName`
  - `keyPressEvent` swallows `Qt.Key_Escape`
  - `closeEvent` ignores unless `self._user_action` is set
- `break_reminder/ui/settings_dialog.py:944` — `ReminderFormDialog(parent=self).exec()` (Add). The only parented + exec'd dialog.
- `break_reminder/ui/settings_dialog.py:995` — `ReminderFormDialog(parent=self).exec()` (Edit). Same pattern.
- `break_reminder/notifications/reminder_dialog.py` — FR-013 dismissable popup. No `setModal` / `setWindowModality`. Will be re-exercised by R-2 in the cross-dialog stack scenarios.
- `break_reminder/ui/reminder_form_dialog.py` — `WA_DeleteOnClose` set; otherwise inherits parent's modal scope.

### Test infrastructure R-2 will reuse

- `tests/conftest.py` — session-scoped `QApplication` fixture; the canonical `Clock` test helper (extracted in Phase 1).
- `tests/test_break_dialog.py:1` (20 tests) — existing FR-009 hardening tests in isolation. Provides the BreakDialog-construction idiom but never co-displays with another dialog.
- `tests/test_settings_dialog.py:1` (100 tests) — Settings widget-wiring; provides the `SettingsDialog`-construction idiom (`Settings(ini_path=...)` + `ReminderStore(path=...)` mocks).
- `tests/test_recurring_reminder_integration.py:1` (4 tests) — Phase 1's integration test; the closest precedent for the cross-module integration shape R-2 will adopt.

## Architecture Insights

1. **The `parent=None` triad is the structural cause of R-2.** Three of the four dialogs (`BreakDialog`, `SettingsDialog`, `ReminderDialog`) are unparented — a deliberate S-01 decision for taskbar-entry uniformity. `SettingsDialog.exec()` therefore activates Qt's `ApplicationModal` policy *without* a parent chain to scope it to, so input routing falls back to "all events go to the modal loop." The sibling `BreakDialog.show()` displays (Z-order) but cannot receive input.

2. **`WindowStaysOnTopHint` is a Z-order hint, not an input-modality override.** This is explicit in test-plan §2 R-2 "Must challenge" and now confirmed empirically. The S-01 plan conflated these; the fix must not repeat the mistake.

3. **The codebase has two coexisting modality regimes** (Finding 4.c): unparented `.exec()` (Settings) and parented `.exec()` (ReminderFormDialog). Their wedge behavior against `BreakDialog` may differ; the test surface must verify both.

4. **There is no app-wide dialog registry.** The only tracked open dialog is `self._active_break_dialog`. The fix may need to extend this — e.g., adding `self._active_settings_dialog` and `self._active_reminder_dialog` — if it pursues the "close sibling on fire" path.

5. **The FR-013 asymmetry is load-bearing** (Finding 4.d). The fix cannot promote `ReminderDialog` to non-dismissable just to symmetrise the wedge — the asymmetry is a PRD contract, and the test-plan §2 R-2 risk-response intent honors it by scoping the wedge to the *break* popup specifically.

6. **The FR-009 hardening (WA_ShowWithoutActivating + Qt.NoFocus + setAutoDefault(False)) compounds the wedge.** These attributes ensure the popup doesn't steal focus from the IDE keystroke in flight (US-02 acceptance) — but they also mean the popup has no way to *take* focus back when a sibling modal loop is consuming input. Any fix that escalates BreakDialog to `Qt.ApplicationModal` will need to re-evaluate the focus posture; raising and activating without stealing the IDE keystroke is a delicate balance.

## Historical Context (from prior changes)

| Artifact | Why it matters for R-2 |
|---|---|
| `context/archive/2026-05-25-settings-break-interval/plan-brief.md:75` | Open Risks predicted the wedge ("organic v0.2.x discovery"). Q2 IS that discovery. |
| `context/archive/2026-05-25-settings-break-interval/plan.md:29,:52,:53` | S-01's "this is benign" assertion + the `parent=None` rationale that produced the structural cause. R-2 is overturning S-01's deferral. |
| `context/archive/2026-05-27-reminders-add-form/plan.md:15,:89,:222` | Establishes the parented + `.exec()` precedent for `ReminderFormDialog`. The second modality regime in the codebase. |
| `context/archive/2026-06-01-testing-rrule-reminder-loop/research.md:232` | Phase 1 → Phase 2 handoff. Confirmed scheduler is signal-emit-only — wedge is purely a dialog-layer concern. |
| `context/archive/2026-06-01-testing-rrule-reminder-loop/plan.md` | The integration-test harness Phase 2 will reuse (session-scoped `QApplication`, virtual clock, recording slot pattern). |
| `context/deployment/deploy-plan.md:131` | Release-gate smoke gap: only single-dialog FR-009 verification. R-2 hardens this. |
| `context/foundation/prd.md:71-86,:114-115,:127-128` | US-02 acceptance, FR-009 contract, FR-013 asymmetry constraint. Bounds the fix. |

## Related Research

- `context/archive/2026-06-01-testing-rrule-reminder-loop/research.md` — Phase 1 of the test-plan rollout (R-1 recurring-reminder loop). Same integration-harness shape; same `Clock` fixture in `tests/conftest.py`; same RRULE-derived oracle discipline applies to R-2 (oracle from PRD contract, not from production code).

## Open Questions

1. **Which fix shape should `/10x-plan` pursue?** Three candidates surfaced; each has a different structural test invariant:
   - **(A) Escalate `BreakDialog` to `Qt.ApplicationModal` on fire.** Smallest code change. Test invariant: `BreakDialog.windowModality() == Qt.ApplicationModal` after `break_due`. Risk: must re-validate the FR-009 `WA_ShowWithoutActivating` + `Qt.NoFocus` interaction — application-modal usually wants focus.
   - **(B) Close sibling top-level dialogs when `break_due` arrives.** Test invariant: after `break_due` fires while `SettingsDialog` is open, `SettingsDialog.isVisible() == False`. Risk: loses the user's in-progress Settings edits unless the app captures + restores them.
   - **(C) Queue `break_due` until sibling dialogs close.** Test invariant: after `break_due` fires while Settings is open, `BreakDialog.isVisible() == False` AND a pending-fire is recorded; after `SettingsDialog` closes, `BreakDialog.isVisible() == True`. Risk: violates NFR timing accuracy ("within 5s of crossing"); user could keep Settings open indefinitely and miss the break entirely.

2. **Should `ReminderDialog` get a singleton guard (Finding 2 / R-2-adjacent)?** It currently has none — two `reminder_due` signals close together stack popups. Out of scope for R-2 narrowly, but cheap to fix in the same change if `/10x-plan` decides to.

3. **Should the release-gate smoke at `context/deployment/deploy-plan.md:131` be extended to exercise the dialog stack manually?** Or is the integration test added by R-2 sufficient and the smoke step can stay single-dialog?

4. **The "another popup" stacking case** mentioned in test-plan §2 R-2 — is back-to-back `BreakDialog` stacking actually possible given the singleton guard at `app.py:400-405`? Likely no; investigate whether the R-2 test should still cover the `BreakDialog`-over-`BreakDialog` case or drop it as architecturally impossible.

5. **What's the right test name and path?** Following Phase 1's pattern, candidate: `tests/test_modal_stacking_integration.py::TestModalStackingWedge`. Or fold into `tests/test_break_dialog.py` as an integration class. `/10x-plan` decides.

## Action items for `/10x-plan`

- Pick a fix shape (A / B / C above) and write the corresponding structural assertion test. **Do NOT use the QTest.mouseClick-on-the-popup-button shape** that test-plan §2 R-2 originally specified — Finding 3 proved it gives a false negative.
- Verify the fix doesn't regress the FR-009 hardening tests in `tests/test_break_dialog.py` (especially the focus-policy + WA_ShowWithoutActivating contracts).
- Cover both modality regimes (Finding 4.c): the test should exercise `BreakDialog` vs `SettingsDialog` (unparented + exec) AND `BreakDialog` vs `ReminderFormDialog` (parented + exec). If they behave identically with the chosen fix, one test covers both; if not, parametrize.
- Update test-plan §2 R-2 "Anti-pattern to avoid" and §6 cookbook row when Phase 2 closes — the "Anti-pattern" entry should explicitly call out the pytest-qt false-negative discovered here.
