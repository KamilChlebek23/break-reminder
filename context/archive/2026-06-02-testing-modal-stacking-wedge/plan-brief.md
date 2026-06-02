# Testing modal-stacking wedge — Plan Brief

> Full plan: `context/changes/testing-modal-stacking-wedge/plan.md`
> Research: `context/changes/testing-modal-stacking-wedge/research.md`

## What & Why

Close R-2 from the test-plan rollout — the FR-009 modal-stacking wedge the user reported as Q2: *"when popup is fired eg. one reminding about break, edition of settings becames impossible. To clear popup, settings must be closed before."* This directly violates US-02 acceptance ("the only way to clear it is an explicit click on 'I'll take a break' or 'Snooze'"). Ship the regression test AND the production fix in one change so the lived-incident path closes in one commit train, then sync the docs (release-gate smoke, test-plan §2/§6/§3 cells, AGENTS.md) so the discovery doesn't fade.

## Starting Point

Every dialog in the codebase is `parent=None` (S-01's deliberate decision for taskbar-entry uniformity). `SettingsDialog.exec()` therefore activates Qt's `ApplicationModal` scope **without a parent chain to scope it to**, so a subsequent `BreakDialog.show()` is on top visually (`WindowStaysOnTopHint`) but its input is routed to the modal Settings loop. S-01's plan-brief explicitly predicted this and deferred to "v0.2.x organic discovery" — Q2 IS that discovery. Phase 1 of the test-plan rollout has already landed the integration-test harness (`tests/conftest.py` `Clock`, session `QApplication`, `*_integration.py` filename convention) Phase 2 builds on.

## Desired End State

A parametrized integration test pins `BreakDialog.windowModality() == Qt.ApplicationModal` AND `QApplication.activeModalWidget() is BreakDialog` after the fire path, across both modality regimes (Settings unparented + `.exec()`; ReminderFormDialog parented + `.exec()`). A 1-line addition to `BreakDialog.__init__` (`setWindowModality(Qt.ApplicationModal)`) turns the test GREEN and fixes the Q2 lived incident. The 20 existing FR-009 hardening tests in `tests/test_break_dialog.py` continue to pass unchanged. Release-gate smoke at `deploy-plan.md:131` exercises the dialog-stack scenario; `test-plan.md` §2 R-2 anti-pattern warns about the `QTest.mouseClick` false negative; §6 cookbook names the shipped pattern; §3 row 2 status flips to `complete`; AGENTS.md's FR-009 hardening list adds the ApplicationModal bullet.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Scope shape | Test + Fix in same change | test-plan.md §3 row 2 explicitly says "if research surfaces the root cause as a modality choice, the same phase ships the fix" — and it did. | Plan |
| Fix shape | A — escalate `BreakDialog` to `Qt.ApplicationModal` | Smallest production diff (1 line); preserves user data in open Settings; preserves FR-013 asymmetry; inverts the structural cause without touching the `parent=None` decision from S-01. | Plan |
| Modality regimes | Parametrize over `SettingsDialog` AND `ReminderFormDialog` | Research §1 identifies both as live regimes that MAY behave differently — parametrize gets coverage of both at near-zero authoring cost. | Plan |
| R-2-adjacent `ReminderDialog` singleton gap | Out of scope — separate change | ReminderDialog stacking is a different bug class (modeless+modeless) than R-2 (modal+modeless); keeps the change sharp on the documented Q2 incident. | Plan |
| Test-fixture modality pattern | `setModal(True) + setWindowModality(ApplicationModal) + .show()` — NOT `.exec()` | `.exec()` blocks the test thread; the pair produces equivalent modality without blocking (Agent C's smoke pattern). | Research §3 |
| Test assertion shape | STRUCTURAL invariants only — NOT `QTest.mouseClick` behavioral | Agent C empirically proved `QTest.mouseClick` and `QPushButton.click()` both bypass the platform modal grab, so a behavioral assertion silently agrees with the bug. | Research §3 |
| Release-gate smoke (`deploy-plan.md:131`) | Update in this change | The change that introduces R-2 protection is the right place to harden the release gate that originally missed Q2. | Plan |
| test-plan.md §2/§6/§3 updates | Update in this change | §6 cookbook convention explicitly says "Per-area patterns. Populated as rollout phases land — each phase's final sub-phase updates the relevant cell." | Plan |

## Scope

**In scope:**
- New test file `tests/test_modal_stacking_integration.py` with 1 parametrized class (2 test cases)
- 1-line `setWindowModality(Qt.ApplicationModal)` addition to `break_reminder/notifications/break_dialog.py::BreakDialog.__init__`
- Module-docstring update on `break_dialog.py` recording the escalation
- Release-gate smoke update at `context/deployment/deploy-plan.md:131`
- `context/foundation/test-plan.md` updates: §2 R-2 anti-pattern, §6 cookbook row, §3 row 2 status cell, frontmatter `rollout_phases_complete`
- `AGENTS.md` FR-009 hardening list — add fifth bullet for ApplicationModal escalation

**Out of scope:**
- `ReminderDialog` singleton guard (R-2-adjacent; modeless+modeless bug class; file separate `/10x-shape`)
- DST-drift fix for recurring firings (R-1b; warrants its own `bugfix-reminder-dst-drift` cycle)
- Any re-parenting of dialogs (S-01's `parent=None` taskbar-uniformity decision stands)
- Promotion of `ReminderDialog` to non-dismissable (FR-013 asymmetry is a PRD contract)
- App-wide dialog registry (not needed by Fix A; would be Fix B/C territory)

## Architecture / Approach

Qt's modal grab nests: the most recently shown modal dialog claims the application-wide input grab, dominating any earlier `.exec()`-loop modal. `setWindowModality(Qt.ApplicationModal)` on `BreakDialog` therefore inverts R-2's structural cause without touching `parent=None`. The grab is independent of window activation, so it coexists with `WA_ShowWithoutActivating + Qt.NoFocus` — US-02's in-flight-keystroke invariant is preserved (this is the load-bearing claim the Phase 2 manual verification re-checks).

Three phases: RED test (Phase 1, fails on current code) → GREEN fix + regression sweep (Phase 2, 1 line + module docstring) → docs sync (Phase 3, three markdown files in one atomic commit). Each phase pauses for human manual-verification before the next starts, mirroring Phase 1 of the test-plan rollout (`testing-rrule-reminder-loop`).

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. RED test | `tests/test_modal_stacking_integration.py::TestModalStackingWedge` with 2 parametrized cases that FAIL on current code, proving the test detects the bug. | Fixture silently produces a non-modal sibling and turns the RED assertion into a vacuous pass — pre-action assertion guards against this. |
| 2. GREEN fix + regression sweep | `BreakDialog.__init__` adds `setWindowModality(Qt.ApplicationModal)`; module docstring updated. Phase 1 tests turn GREEN; all 20 existing `test_break_dialog.py` tests still pass; full `uv run pytest` clean. | The ApplicationModal escalation might interact unexpectedly with `WA_ShowWithoutActivating + Qt.NoFocus`, breaking US-02's in-flight-keystroke acceptance. Manual verification step 2.9 re-checks this directly. |
| 3. Docs sync | `deploy-plan.md:131` release-gate smoke extended; `test-plan.md` §2 R-2 anti-pattern + §6 cookbook + §3 status cell + frontmatter updated; `AGENTS.md` FR-009 list extended. Pure markdown commit, zero `.py` diff. | Forgetting to flip §3 row 2 status to `complete` leaves the orchestrator state machine stuck on Phase 2; sanity-checked by §3.4 manual verification. |

**Prerequisites**: Phase 1 of the test-plan rollout (`testing-rrule-reminder-loop`) must be archived (✅ already done — `context/archive/2026-06-01-testing-rrule-reminder-loop/`). `tests/conftest.py::Clock` is the shared fixture Phase 2's new file imports.

**Estimated effort**: ~1 session across 3 phases. Phase 1 is ~40 lines of test code (mostly fixture setup), Phase 2 is 1 line of production change + 1 paragraph of docstring, Phase 3 is markdown edits across 3 files.

## Open Risks & Assumptions

- **Assumption**: Qt's modal grab nests correctly across PySide6 6.11.1 — the most-recently-shown ApplicationModal claims the application-wide input grab, dominating any earlier `.exec()`-loop modal. Research §3's Agent C smoke pattern already constructed this scenario successfully; Phase 1's RED-then-GREEN ceremony is the proof.
- **Risk**: ApplicationModal escalation might cause `BreakDialog` to steal activation despite `WA_ShowWithoutActivating + Qt.NoFocus`. Mitigation: Phase 2 manual verification step 2.9 explicitly tests US-02's in-flight-keystroke acceptance with a real text editor. If it regresses, Phase 2 stops and `/10x-plan` re-enters Q2.
- **Risk**: The two modality regimes (unparented Settings + parented ReminderFormDialog) might require different fixes — research flagged this but didn't prove it. Mitigation: parametrize over both regimes from Phase 1; if they diverge under Fix A, Phase 1 fails one parameter and we split.

## Success Criteria (Summary)

- The Q2 lived incident is no longer reproducible: launch app → open Settings → trigger break dialog from tray → click "I'll take a break" → popup closes (Phase 2 manual step 2.7).
- The new integration test passes on the fixed code AND failed on the broken code (RED → GREEN ceremony observed across Phase 1 → Phase 2).
- US-02's in-flight-keystroke acceptance is preserved (Phase 2 manual step 2.9).
- The orchestrator state machine in `test-plan.md` §3 advances: row 2 status `complete`, `rollout_phases_complete: 2`. The next `/10x-test-plan` re-run routes to Phase 3 (storage robustness) or Phase 4 (cross-cutting integration), depending on which the user prioritizes.
