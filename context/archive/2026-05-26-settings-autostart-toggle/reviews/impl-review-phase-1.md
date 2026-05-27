<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: settings-autostart-toggle

- **Plan**: context/changes/settings-autostart-toggle/plan.md
- **Scope**: Phase 1 of 2
- **Date**: 2026-05-26
- **Verdict**: APPROVED (PASS with 2 minor warnings)
- **Findings**: 0 critical · 2 warnings · 3 observations
- **Commit reviewed**: e9f2ff0 (`feat(settings-autostart-toggle): wire FR-003 Lifecycle tab + Run-key writes (p1)`)
- **Triage outcome**: All 5 findings FIXED in-place (see Decision per finding). Post-fix gates: pytest 259 pass, pyright 0 errors, ruff check clean, ruff format clean.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

Plan-drift check: 8 of 12 planned items MATCH; 4 acceptable DRIFTs (extra defensive tests, sibling test-class organization mirroring S-04, README amendment landing on the INI-keys table because the planned "Settings-dialog feature bullet" doesn't exist in README.md). All "What We're NOT Doing" guardrails held. `accept()` ordering matches the planned sequence verbatim (voice gate → autostart side-effect → INI writes → super().accept()).

Success criteria: `uv run pytest` (258 tests pass), `uv run pyright` (0 errors), `uv run ruff check` (clean), `uv run ruff format --check` (28 files already formatted). Phase 1's plan has no Manual rows; manual smoke is deferred to Phase 2.

## Findings

### F1 — Logging absent on autostart OSError swallow

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: break_reminder/ui/settings_dialog.py:528-541
- **Detail**: The `except OSError:` clause in `accept()` surfaces a user-facing tooltip but drops the exception entirely — no log entry, no traceback. The codebase has an established `logger.exception(...)` pattern in matching swallow paths: `notifications/voice.py:93`, `activity.py:52/66/77`, `scheduler.py:313`. A user reporting "autostart doesn't stick" leaves no diagnostic trail today.
- **Fix**: Add `logger = logging.getLogger(__name__)` at module top, then `logger.exception("autostart Run-key write/delete failed")` inside the `except OSError:` clause before the tab-switch + tooltip lines.
- **Decision**: FIXED

### F2 — `import winreg` at module top breaks non-Windows test imports

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: break_reminder/ui/settings_dialog.py:60
- **Detail**: `winreg` is Windows-only stdlib — importing it on Linux/macOS raises `ModuleNotFoundError`. Production is unaffected (FR-001 makes the app Windows-only and CI uses windows-latest), but Linux/macOS contributors running `uv run pytest` locally now fail at collection time because `tests/test_settings_dialog.py:30` imports the dialog module. The plan's rationale ("the entire app is Windows-only by design") covers production but not the dev-loop case.
- **Fix A ⭐ Recommended**: Document the Windows-only-dev constraint in AGENTS.md and accept that local dev requires Windows.
  - Strength: Matches the FR-001 invariant the project has stood behind since v0.1.0; zero code changes; no never-exercised stub branch.
  - Tradeoff: Linux/macOS contributors cannot run `uv run pytest` locally; CI remains the only place tests run.
  - Confidence: HIGH — Windows-only is foundational and is already documented in tech-stack.md and the PRD.
  - Blind spot: We haven't surveyed whether any contributor actively wants Linux/macOS local dev.
- **Fix B**: Guard with `if sys.platform == "win32": import winreg` and stub both helpers on non-Windows.
  - Strength: Lets the test suite collect on Linux/macOS so local pytest works (modulo PySide6/Qt platform support).
  - Tradeoff: Adds a never-exercised branch that test coverage cannot honestly cover; complicates the otherwise-flat helper module.
  - Confidence: MEDIUM — works mechanically but creates dead code paths the team has otherwise avoided.
  - Blind spot: PySide6 may have other Windows assumptions further down the dialog code that would still break on Linux/macOS, making this fix only half-useful.
- **Decision**: FIXED via Fix A (AGENTS.md "Build & release" preamble)

### F3 — Delete-path OSError → atomic-save test gap

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: tests/test_settings_dialog.py (TestAutostartTabSave, lines 1118-1203)
- **Detail**: Both atomic-save OSError tests (`test_runkey_helper_oserror_blocks_save_and_anchors_tooltip`, `test_runkey_helper_permissionerror_also_blocks_save`) monkeypatch `_write_autostart_runkey` to raise. The symmetric "untick + OK → `_delete_autostart_runkey` raises OSError → blocks save" path is uncovered. Functionally redundant under the current single `except OSError:` shape, but if a future refactor splits the side-effect block into separate try/except per branch the delete branch would silently regress.
- **Fix**: Add one short `test_delete_helper_oserror_blocks_save` mirroring the write test but starting with `autostart=True`, unticking the checkbox, and asserting the same atomic-save guarantees.
- **Decision**: FIXED

### F4 — Failure-tooltip wording recommends an inapplicable fix

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency (user-facing copy)
- **Location**: break_reminder/ui/settings_dialog.py:129-131
- **Detail**: `_AUTOSTART_FAILURE_MESSAGE` reads `"Could not update Windows autostart — try running BreakReminder as your normal user."`. The HKCU\…\Run write already happens AS the current normal user — no elevation is involved and "run as normal user" is the steady state. The real failure modes are GPO blocks, ACL tampering on the Run subkey, or registry corruption. The current wording sends users down a dead-end fix.
- **Fix**: Tighten to `"Could not update Windows autostart — your machine may block writes to the per-user startup registry. Contact IT if this persists."` The existing `assert "autostart" in args[1].lower()` test continues to pass.
- **Decision**: FIXED

### F5 — Autostart checkbox missing tooltip vs voice-checkbox precedent

- **Severity**: 🔍 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: break_reminder/ui/settings_dialog.py:385-386 (`_build_lifecycle_tab`)
- **Detail**: The voice checkbox carries `_VOICE_ENABLED_TOOLTIP` ("Voice plays alongside the break popup, not instead of it") to surface its non-obvious contract on hover. The autostart checkbox has no `setToolTip` call. The label "Launch BreakReminder at Windows login" is more self-explanatory than the voice case, but a one-line tooltip would honor the FR-003 "user opts in via the settings panel, no UAC ceremony" UX commitment that's non-obvious to security-conscious users.
- **Fix**: Add a tooltip constant + `self._autostart_checkbox.setToolTip(...)` call. Optional; defer if you want to keep this slice minimal.
- **Decision**: FIXED
