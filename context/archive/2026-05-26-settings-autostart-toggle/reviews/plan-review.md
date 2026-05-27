<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Settings Autostart Toggle (S-02)

- **Plan**: `context/changes/settings-autostart-toggle/plan.md`
- **Mode**: Deep
- **Date**: 2026-05-27
- **Verdict**: REVISE
- **Findings**: 2 critical · 2 warnings · 1 observation
- **Note**: This is a **retrospective** review. The slice was already
  `status: implemented` (Phase 1 + Phase 2 shipped 2026-05-26) when the
  review ran. Findings F1 + F2 + F4 are documented gaps the plan-review
  skill *would have* surfaced pre-implementation; they were already
  remediated in the v0.5.0 post-merge hotfix (`8ec5850`,
  `break_reminder/ui/settings_dialog.py:144-201`). The plan and brief
  are kept on disk as the source of intent — F4 was applied as a
  retroactive amendment so the documented intent matches what shipped;
  F1, F2, F3, F5 were left as-is per user decision (notes below).
  `change.md` status is **NOT** flipped back to `plan_reviewed`; the
  slice remains `implemented`.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | WARNING (shared with Blind Spots — fresh-profile users would not have reached the documented end-state under the original plan) |
| Lean Execution | PASS |
| Architectural Fitness | WARNING (wrong winreg primitive on the write helper) |
| Blind Spots | FAIL (multiple — fresh-profile / no-subkey case never enumerated) |
| Plan Completeness | WARNING (helper exception contract under-specified; tooltip wording imprecise) |

## Grounding

8/8 paths verified · 8/8 symbols confirmed at the cited lines (`break_reminder/storage/settings.py:52,65,70,79,230,275`; `context/foundation/tech-stack.md:71`; existing dialog scaffold) · brief↔plan consistent · `## Progress` block well-formed (1 block, 2 phases, 4 P1 + 11 P2 boxes mapped 1:1 to Success Criteria).

## Findings

### F1 — `_delete_autostart_runkey` contract only covers value-absent, not subkey-absent

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Completeness
- **Location**: Phase 1 #3 (winreg helpers); Implementation Approach line 79; Critical Implementation Details line 88
- **Detail**: The plan describes `FileNotFoundError` swallowing in three places (L79, L88, L132) — all framed as "value doesn't exist" or "system that never had the Run-key entry". Nothing distinguishes the two OS-level raise sites: (a) Run subkey absent → `winreg.OpenKey` raises `[WinError 2]`; (b) BreakReminder value absent → `winreg.DeleteValue` raises `[WinError 2]`. An implementer reading the plan writes the obvious shape (`with winreg.OpenKey(...): try: DeleteValue except FileNotFoundError: return`) — which only catches (b). Case (a) escapes, hits `accept()`'s `except OSError:`, fires the atomic-save tripwire, and blocks the save. Direct historical evidence: 11-test CI failure on the v0.5.0 release run (windows-latest, `runneradmin` profile with no Run subkey); commit `8ec5850` fixed by widening the catch to wrap the whole `with winreg.OpenKey(...)` block. Phase 1 #8's `test_delete_helper_swallows_filenotfounderror` reinforces the gap by only specifying the `DeleteValue` raise-site.
- **Fix**: Tighten the helper contract to enumerate both raise sites ("Swallows `FileNotFoundError` from EITHER `winreg.OpenKey` (subkey absent) OR `winreg.DeleteValue` (value absent under an existing subkey) — both map to 'already-deleted' success"). Wrap the whole `with` block in `try/except FileNotFoundError`. Add `test_delete_helper_swallows_filenotfounderror_when_subkey_missing` (monkeypatches OpenKey to raise) and a symmetric `test_delete_helper_propagates_oserror_from_openkey` tripwire (monkeypatches OpenKey to raise PermissionError).
  - Strength: Pins behaviour at the OS-level rather than the call-site level, eliminating the entire fresh-profile failure class.
  - Tradeoff: The widened catch must NOT turn into `except OSError` — that would mask `PermissionError` / GPO blocks as silent success; the symmetric tripwire test guards against this regression.
  - Confidence: HIGH — this exact shape shipped in 8ec5850; CI flipped 11-red → 262-green.
  - Blind spot: None significant.
- **Decision**: ACCEPTED — already remediated in code (8ec5850); plan kept as-is per user.

### F2 — `_write_autostart_runkey` uses `OpenKey`, not `CreateKeyEx`

- **Severity**: ❌ CRITICAL
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness (wrong winreg primitive) + Blind Spots (didn't anticipate missing-subkey case)
- **Location**: Phase 1 #3 (winreg helpers); Implementation Approach line 78
- **Detail**: The plan specifies `winreg.OpenKey` with `KEY_SET_VALUE` for the write helper. `OpenKey` requires the target subkey to already exist — if `HKCU\...\Run` is absent (a freshly provisioned Windows profile, e.g. CI runner, brand-new corporate user, factory-imaged machine), `OpenKey` raises `FileNotFoundError`. The plan never addresses this for the WRITE path even though the symmetric DELETE path is at least mentioned (incompletely — see F1). Latent in CI because no test ticks autostart from a default INI where the subkey is missing — but a real production user on a fresh Windows install would hit this on first tick + OK. The canonical Run-key idiom is `winreg.CreateKeyEx`, which opens the subkey if it exists and creates it if absent.
- **Fix**: Specify `winreg.CreateKeyEx` (not `OpenKey`) for the write helper, with a docstring note "auto-creates the Run subkey if absent — the canonical `HKCU\...\Run` idiom". Add a regression test `test_write_helper_succeeds_when_subkey_missing` pinning the create-or-open contract.
  - Strength: Eliminates the symmetric latent bug at zero implementation cost (one identifier swap); aligns with the documented MS pattern and matches the shipped post-merge fix.
  - Tradeoff: None of consequence — `KEY_SET_VALUE` access semantics are identical between `OpenKey` and `CreateKeyEx`.
  - Confidence: HIGH — documented MS pattern + matches 8ec5850.
  - Blind spot: None significant.
- **Decision**: ACCEPTED — already remediated in code (`break_reminder/ui/settings_dialog.py:170`); plan kept as-is by analogy to F1's accept (user closed F2 modal without explicit answer; F1 and F2 share the same shape and rationale).

### F3 — Phase 1 success criteria don't distinguish local-dev from CI Windows profiles

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Blind Spots
- **Location**: Phase 1 — Success Criteria → Automated Verification (lines 227-232); Open Risks & Assumptions (`plan-brief.md` lines 79-82)
- **Detail**: Phase 1's automated gates are all run-locally commands (`uv run pytest`, `uv run pyright`, `uv run ruff check`, `uv run ruff format --check`). The plan never says "must also pass on the windows-latest CI runner". A typical dev's `HKCU\...\Run` subkey is pre-populated by Windows itself / OneDrive / Edge / Teams — so any winreg path that assumes the subkey exists passes locally and silently fails on the freshly-provisioned `runneradmin` profile that GitHub Actions ships. Open Risks & Assumptions in the brief lists three risks (PyInstaller `sys.executable`, NSIS path stability, locked-down machines); none mention the fresh-profile / no-subkey case — the exact failure mode that broke v0.5.0 CI.
- **Fix**: Extend Open Risks & Assumptions in `plan-brief.md` with a fresh-profile entry, AND add "release.yml CI green on windows-latest tag-push" as a Phase 1 automated success criterion. Either alone would shape the implementer's mental model toward defensive winreg paths; together they make it a hard gate.
  - Strength: The risk note shapes implementer thinking; the CI-green criterion is a hard gate that would block "implemented" status until CI is green end-to-end.
  - Tradeoff: CI-as-gate adds ~5min wall-clock per push; acceptable for a Windows-only codebase where every slice has the same exposure.
  - Confidence: MEDIUM — risk-note is a clear win; CI-gate needs team willingness to actually wait on CI.
  - Blind spot: Whether windows-latest profile shape is stable across runner image versions.
- **Decision**: SKIPPED — user opted not to amend a shipped plan; lesson noted for future plans.

### F4 — Tooltip wording presumes a user-role failure cause that doesn't match the real failure modes

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness (UX wording precision)
- **Location**: Phase 1 #3 (line 126) — `_AUTOSTART_FAILURE_MESSAGE` constant; also Desired End State paragraph (line 40)
- **Detail**: The proposed tooltip "Could not update Windows autostart — try running BreakReminder as your normal user." encodes the failure model "user is running BreakReminder as a different (admin-elevated?) account, and HKCU points at the wrong hive". The actual failure modes are GPO blocks on HKCU writes (corporate machines) and ACL tampering on `HKCU\...\Run` — neither addressed by "running as your normal user". A corporate user reading this would file a ticket asking IT how to do that and get nowhere. The post-merge fix (`break_reminder/ui/settings_dialog.py:138-141`) updated the string to a clearer "your machine may block writes to the per-user startup registry. Contact IT if this persists."
- **Fix**: Replace the proposed string in Phase 1 #3 (and in the Desired End State quote at line 40) with the wording that actually shipped — "Could not update Windows autostart — your machine may block writes to the per-user startup registry. Contact IT if this persists."
- **Decision**: FIXED — applied to both Phase 1 #3 (`_AUTOSTART_FAILURE_MESSAGE` constant rendered as a parenthesized multi-line string assignment) and Desired End State paragraph (single-line tooltip quote).

### F5 — Phase 1 #4 outer `try/except OSError` signals the helper contract leaks too broadly

- **Severity**: ℹ️ OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 1 #4 (line 138) "Wrap in try/except OSError"
- **Detail**: Phase 1 #4 says the dialog should "Wrap in try/except OSError (catches `PermissionError`, `FileNotFoundError`, generic `OSError`)". Combined with the helpers' own `FileNotFoundError` swallowing, listing `FileNotFoundError` in the dialog's outer catch is dead code by contract — no `FileNotFoundError` surfaces from the helpers. The plan would read more sharply if the dialog's outer catch enumerated only `PermissionError` + generic `OSError`, with a one-line note that `FileNotFoundError` is handled inside the helpers per #3.
- **Fix**: Change the parenthetical in Phase 1 #4 to "(catches `PermissionError` and other `OSError` subclasses; `FileNotFoundError` is handled inside the helpers per #3 and never reaches here)".
- **Decision**: SKIPPED — user closed modal without explicit answer; carrying as a doc-polish note rather than amending the shipped plan.

## Lessons-learned for future plans

The fresh-profile / missing-subkey case is the operative lesson from this slice. Future plans that touch Windows registry, filesystem state, or any OS-level resource should:

1. Enumerate **every** raise site of any exception the helper claims to swallow — don't conflate "feature absent" with "container absent".
2. List **CI environment delta** (windows-latest's `runneradmin` profile vs. dev machine) as an explicit risk whenever winreg, filesystem, or env-var paths are touched.
3. Prefer create-or-open primitives (`CreateKeyEx`, `os.makedirs(exist_ok=True)`, `Path.mkdir(parents=True, exist_ok=True)`) over plain open primitives whenever the resource is owned by the application.

These three rules, captured here, are candidates for `context/foundation/lessons.md` if the pattern recurs in a future slice.
