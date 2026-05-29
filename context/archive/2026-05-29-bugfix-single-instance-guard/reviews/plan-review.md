<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Single-instance guard (S-10)

- **Plan**: `context/changes/bugfix-single-instance-guard/plan.md`
- **Mode**: Deep
- **Date**: 2026-05-29
- **Verdict**: SOUND (with minor fixes applied during triage)
- **Findings**: 0 critical · 1 warning · 3 observations — all triaged

## Verdicts

| Dimension             | Verdict |
|-----------------------|---------|
| End-State Alignment   | PASS    |
| Lean Execution        | PASS    |
| Architectural Fitness | PASS    |
| Blind Spots           | PASS (1 minor observation) |
| Plan Completeness     | WARNING (1 warning + 2 observations) |

## Grounding

5/5 paths exist (`break_reminder/app.py`, `break_reminder/storage/paths.py`, `tests/test_app.py`, `tests/conftest.py`, `main.py`); 7/7 line-number claims verified against `app.py` (lines 21, 37, 118, 477, 485, 487, 489); ruff config inspected (`pyproject.toml` lines 38-49 — F-rules selected, no `dummy-variable-rgx` override → leading-underscore exemption applies); reminders.json atomic-rename via `tmp.replace(self._path)` confirmed at `break_reminder/storage/reminders.py:242`; `--self-test` short-circuit confirmed at `main.py:120-125` (returns from `_run_self_test` before importing `break_reminder.app`); brief↔plan internally consistent.

## Findings

### F1 — Phase 2 contract is stale relative to current roadmap.md

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Completeness
- **Location**: Phase 2 — Bookkeeping (plan.md lines 142-177)
- **Detail**: Between plan-write and plan-review, the user invoked an explicit roadmap update for S-10. roadmap.md now already has the "At a glance" row (status `planned`), the detailed `### S-10` slice block, and the "Backlog Handoff" row. The Phase 2 contract still said "append rows" — would have produced duplicates. Phase 2 success criterion 2.2 (`grep '^| S-10 |'` returns ≥2 matches) also weakened because it currently passes against the pre-impl roadmap.
- **Fix**: Rewrite Phase 2 'Roadmap S-10 row' contract from 'append rows' to 'flip planned→done + append Done-section bullet + bump frontmatter date'. Tighten success criteria to assert `done` status + Done bullet presence.
- **Decision**: FIXED (applied to plan.md Phase 2 overview, contract for change #2, success criteria, and Progress section items 2.2-2.4)

### F2 — F841/noqa hedge is unnecessary; ruff's default exempts `_*`

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious
- **Dimension**: Plan Completeness
- **Location**: Phase 1.3 (plan.md line 100)
- **Detail**: Plan said "a `# noqa: F841` may be needed if ruff flags the unused-local — verify against current ruff config." Verified against `pyproject.toml` lines 38-49: `[tool.ruff.lint]` selects F-rules with no `dummy-variable-rgx` override, so ruff's default regex exempts `_instance_lock` from F841. The hedge would mislead an implementer into adding an unnecessary `# noqa` that any future RUF100 rule activation would itself flag as dead.
- **Fix**: Replace the hedge with a definitive statement.
- **Decision**: FIXED (applied to plan.md Phase 1.3 contract block)

### F3 — Lessons-rule reasoning for the helper docstring is inverted

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious
- **Dimension**: Plan Completeness
- **Location**: Current State Analysis bullet (plan.md line 18) + Phase 1.2 contract (plan.md line 85)
- **Detail**: Plan said `_acquire_single_instance_lock` is "module-private (leading underscore — exempt under the lessons rule)". But `lessons.md` carve-out: "Private helpers (leading `_`) are exempt UNLESS they encode non-obvious behavior." This function encodes the lifetime contract that, if violated, silently breaks the entire fix — so it is NOT exempt; the docstring is required. Plan reached the right conclusion ("include a brief one anyway") but via wrong reasoning that could mislead future contributors.
- **Fix**: Reword both citations to acknowledge the carve-out and require the docstring on those grounds.
- **Decision**: FIXED (applied to plan.md Current State Analysis lessons.md bullet + Phase 1.2 contract block)

### F4 — PID-reuse window unmentioned in plan.md (only in plan-brief)

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious
- **Dimension**: Blind Spots
- **Detail**: plan-brief.md "Open Risks & Assumptions" called out the 30s PID-reuse risk. plan.md did not mention it at all. A future contributor encountering a "30-second startup hang after kill -9" would have found no answer in plan.md.
- **Fix**: Add a one-line bullet to plan.md's "What We're NOT Doing" noting the PID-reuse window as theoretically possible but practically unreachable, with a manual mitigation if it ever lands.
- **Decision**: FIXED (applied as new bullet at end of plan.md "What We're NOT Doing" section)

## Triage Summary

```
═══════════════════════════════════════════════════════════
  TRIAGE COMPLETE
═══════════════════════════════════════════════════════════

  Fixed:     F1, F2, F3, F4   (4)
  Skipped:                    (0)
  Accepted:                   (0)
  Dismissed:                  (0)

  ► Verdict after fixes: SOUND — ready for /10x-implement
═══════════════════════════════════════════════════════════
```
