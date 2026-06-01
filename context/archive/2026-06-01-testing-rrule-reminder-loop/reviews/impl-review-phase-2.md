<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Testing R-1 Recurring-Reminder Re-arm Loop

- **Plan**: `context/changes/testing-rrule-reminder-loop/plan.md`
- **Scope**: Phase 2 of 2
- **Date**: 2026-06-01
- **Verdict**: APPROVED
- **Findings**: 0 critical, 0 warnings, 1 observation
- **Commits reviewed**: `386ef94` (Phase 2 test + docs), `6e1b92a` (SHA-stamp follow-up)

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS (1 minor observation) |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS (pytest 509/509, ruff clean, pyright 0/0, pip-audit clean) |

## Findings

### F1 — test-plan.md §4 "Test base profile" now stale

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: context/foundation/test-plan.md:82 (and the per-file table immediately below)
- **Detail**: The Phase 2 / Change #1 contract enumerated exactly four cells to refresh (frontmatter, §3 row 1, §6 Cookbook row, §7 Negative space). It deliberately did not enumerate §4 "Test base profile". After Phase 2, line 82 still claims "427 test methods across 12 files; zero integration tests" — but the actual repo state is now 509 tests across 13 files including 4 integration tests in a new file. The per-file table below it is also missing the new test file. This makes the doc internally inconsistent: §3 row 1 advertises Phase 1 as complete and §6 Cookbook explicitly names `tests/test_recurring_reminder_integration.py`, yet §4 still asserts zero integration tests exist. Same pattern as Phase 1's F1 (planned surface vs surrounding doc drift).
- **Fix A** ⭐ Recommended: Defer §4 refresh to the next `/10x-test-plan --refresh` cycle. The §4 cells are the kind of doc that drifts continuously across rollout phases; a per-phase refresh fragments the audit trail and creates a maintenance tax (Phase 3 + Phase 4 would each touch the same cells).
  - Strength: Aligns with the "Refresh cadence" rules already in §8 — §3 status cells evolve per phase; §4 is a snapshot that wants `--refresh`.
  - Tradeoff: Doc is briefly inconsistent (a 5-second read on §4 contradicts §3 row 1).
  - Confidence: HIGH — the doc's own §8 rules tell us §4 is meant to be `--refresh`-scoped.
  - Blind spot: Whether the contradiction confuses a future agent using §4 as ground truth (probably not — §3 + §6 are the orchestrator-relevant cells, and they're correct).
- **Fix B**: Refresh §4 inline now as part of this change.
  - Strength: Doc is internally consistent immediately.
  - Tradeoff: Either amend the Phase 2 commit (history rewrite) or land a tiny follow-up commit. Phase 3/4 will redo the same cells.
  - Confidence: HIGH on mechanics, MED on whether this is the right granularity for §4 updates.
  - Blind spot: Sets a precedent that every rollout phase touches §4.
- **Decision**: DEFERRED via Fix A — to be batched into the next `/10x-test-plan --refresh` cycle.

## Notable Positives (not findings — for the record)

- All four test method titles match the plan's stable-title contract byte-exactly. The weekly test correctly double-duties as R-1a + R-1c with a 13-day-out start_at that forces cap re-entry across BOTH the initial reload AND the post-fire reload.
- Oracle style mixes relative (daily/weekly/lead) and literal (monthly) datetimes — intentional and correct. The monthly case can't use `start_at + timedelta(days=30)` because June has 30 days and July has 31; only a literal date is a faithful RRULE oracle. Daily/weekly use relative form because their period is exact.
- Module docstring quotes the test-plan §2 R-1 anti-pattern rule verbatim ("oracle from RRULE spec, NEVER from re-reading scheduler internals") — locks the conviction inside the test file so a future contributor adding a 5th test sees it before authoring a new oracle.
- Deliberate-regression smoke (Progress 2.6) confirmed the daily test catches a dropped post-fire reload() with a textbook failure message: `At index 1 diff: ('daily', ...2026-05-20...) != ('daily', ...2026-05-21...)`. Reads cleanly even for a contributor unfamiliar with R-1a.
- change.md correctly flipped implementing → implemented. plan.md Progress section has every step `[x]` with SHA back-stamp. SHA-stamp follow-up (`6e1b92a`) chose strict-audit standalone-commit over HEAD amend, preserving immutability of the phase commit.
