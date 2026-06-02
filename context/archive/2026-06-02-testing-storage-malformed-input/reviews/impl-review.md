<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Storage round-trip robustness (R-5)

- **Plan**: `context/changes/testing-storage-malformed-input/plan.md`
- **Scope**: Full plan, Phases 1-4 of 4
- **Date**: 2026-06-02
- **Verdict**: APPROVED
- **Findings**: 0 critical, 0 warnings, 4 observations
- **Phase commits**: `97f87dd` (p1) → `5468143` (p2) → `2bab8e9` (p3) → `dbd5f85` (p4)

Phase 1 had its own phase-scoped review at `reviews/impl-review-phase-1.md` (6 findings, all triaged + fixed inside the Phase 1 commit). This full-plan review verified those fixes survived through Phases 2/3/4 and focuses new findings on Phases 2-4 + holistic cross-phase coherence.

## Verdicts

| Dimension           | Verdict |
|---------------------|---------|
| Plan Adherence      | PASS    |
| Scope Discipline    | PASS    |
| Safety & Quality    | PASS    |
| Architecture        | PASS    |
| Pattern Consistency | WARNING |
| Success Criteria    | PASS    |

## Findings

### F1 — Order preservation isn't oracled in the row-containment test

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_reminders.py:311-312`
- **Detail**: `test_one_bad_row_drops_only_bad_row` uses a SET assertion: `assert {r.name for r in result} == {"alpha", "omega"}`. Production `_read` preserves insertion order (for-loop + append), and the cookbook recipe says "preserves well-formed siblings" — which intuitively implies original order. A regression that reversed iteration would silently pass this test. The class's only positional test is this one.
- **Fix**: Change to a list assertion: `assert [r.name for r in result] == ["alpha", "omega"]`. Pins the ordered contract; same robustness; one-line change.
- **Decision**: FIXED

### F2 — Combined log oracle is split across two `any(...)` checks

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_reminders.py:346-347`
- **Detail**: `test_bad_row_logs_warning` asserts:
  ```python
  assert any("row 1" in r.getMessage() for r in warnings)
  assert any("ValueError" in r.getMessage() for r in warnings)
  ```
  These pass independently — they would still pass if `"row 1"` lived in warning A and `"ValueError"` lived in warning B. The production code emits a single combined message (`"reminders.json row %d is malformed (%s: %s); dropping"`), so a regression that split that message into two would lose the "row N → exception class" pairing without tripping the test.
- **Fix**: Combine into a single record-level oracle:
  ```python
  assert any(
      "row 1" in m and "ValueError" in m
      for m in (r.getMessage() for r in warnings)
  )
  ```
- **Decision**: FIXED

### F3 — `_read` encodes 3 non-obvious invariants but has no method docstring

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency (against lessons.md #1: Google docstrings)
- **Location**: `break_reminder/storage/reminders.py` (the `_read` method)
- **Detail**: Pre-Phase-3 `_read` was a 6-line "load → parse" helper that qualified for the leading-underscore docstring exemption per `lessons.md:7` ("Private helpers are exempt unless they encode non-obvious behavior"). Post-Phase-3 it carries three independent invariants the lesson itself flags as load-bearing: (a) corrupt-JSON file fallback, (b) non-list top-level guard with a specific log shape, (c) per-row containment with a documented exception tuple. The module-level docstring covers this in prose, but a method-local pointer would help.
- **Fix**: Add a one-paragraph Google-style docstring at `_read` summarizing the three guards. (Or accept the module-docstring coverage explicitly via a one-line `# See module docstring 'row-resilient' paragraph.` comment if you'd rather not duplicate the prose.)
- **Decision**: FIXED — applied as a 4-line upfront comment block (matches the `_write` sibling convention; the in-file pattern is "inline comment, not docstring" for private methods that encode non-obvious behavior).

### F4 — Stale `:36-72` line range in the new lessons.md entry

- **Severity**: OBSERVATION
- **Impact**: LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Cross-phase Coherence (cross-confirmed by both sub-agents)
- **Location**: `context/foundation/lessons.md:23`
- **Detail**: The Phase 4 entry cites `_coerce_lead_minutes at break_reminder/storage/reminders.py:36-72`. The line range was copied from the plan (line 15), but Phase 3 added 11 lines above (`import logging`, module-level `logger`, expanded module docstring), shifting the function to `:51-83`. A reader following the citation lands on the constants block + docstring, not the function body. The companion `ReminderStore._read` citation in the same sentence already wisely omits a line range.
- **Fix**: Update the cited range to `:51-83`, OR drop the range entirely (match the `ReminderStore._read` convention used in the same sentence; future-proofs against unrelated edits above the file).
- **Decision**: FIXED via Fix A — line range updated to `:51-83`.

## Cross-phase coherence (verified PASS — for the record)

- Phase 3 fix turns all 5 Phase 2 RED tests GREEN.
- Exception tuple `(KeyError, ValueError, TypeError)` covers every `from_dict` raise; correctly does NOT catch `AssertionError` (programming-bug indicator at `reminders.py:178`).
- Phase 4 §6 Cookbook names test classes that all exist (`TestMalformedReminderFromDict`, `TestReminderStoreReadResilience`, `TestSettingsIdleThresholdHandEdits`, `TestSettingsVoicePhraseRawSetter`, `TestSettingsBoolCoercionSymmetry`, `TestSettingsUnknownKey`).
- Phase 4 `lessons.md` "canonical example" claim about `_read` matches what Phase 3 actually shipped.
- Storage tests use `tmp_path` via `ini_path`/`store_path` fixtures; no real `%APPDATA%` writes.
- All 6 "What We're NOT Doing" guardrails held (no `event_log.py`, no Settings production change, no `idle_threshold_sec` clamp fix, no `voice_phrase.setter` coercion fix, no `AGENTS.md` edit, no new test files).
- All Phase 1 review fixes (F1-F6) survived Phases 2/3/4 unchanged.

## Automated criteria (verified PASS)

- `uv run pytest` → 562 passed
- `uv run pytest tests/test_reminders.py::TestReminderStoreReadResilience -v` → 5 passed (Phase 2 RED → GREEN)
- `uv run ruff check` on all 3 changed source files → clean
- `uv run pyright` on all 3 changed source files → clean
