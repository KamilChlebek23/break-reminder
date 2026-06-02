<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Storage round-trip robustness (R-5) — Phase 1

- **Plan**: `context/changes/testing-storage-malformed-input/plan.md`
- **Scope**: Phase 1 of 4 (Pin-only regression net)
- **Date**: 2026-06-02
- **Verdict**: APPROVED
- **Findings**: 0 critical · 1 warning · 5 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Headline

- 9 new tests in `tests/test_reminders.py` + 35 new tests in `tests/test_settings.py` (146 passed in the two files; 556 passed full suite).
- Zero production-code touched; Phase 1 is the pure-addition surface as the plan specified.
- One WARNING (a no-assertion test redundant with its neighbor) + a handful of polish-level observations. Nothing blocks the commit.

## Findings

### F1 — Redundant no-assertion test in TestSettingsVoicePhraseRawSetter

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_settings.py:579-582` (`test_setter_accepts_non_str_without_raising`)
- **Detail**: The test has no explicit assertion — its body is a single `settings.voice_phrase = 42` line. It implicitly pins "the setter does not raise on non-str". The very next test (`test_non_str_setter_round_trips_via_get_str_coercion` at :584-597) also performs the same assignment; any future regression where the setter starts raising on non-str would already be caught by that test (and more visibly, because the round-trip test has a named oracle). More importantly, neither test actually pins the load-bearing claim from the plan — "the setter writes raw, with no `str(...)` coercion at the write boundary" (per the `voice_phrase.setter` docstring at `settings.py:260-266`). The round-trip test only confirms the READ-side coercion happens; the write-side raw-write contract is never directly observed.
- **Fix A ⭐ Recommended**: Re-oracle to assert the raw write at the QSettings layer.
  - Strength: Pins the actual load-bearing claim ("setter does not coerce") rather than the trivially-true "did not raise" — converts a redundant test into a meaningful one. Mirrors the test_settings.py convention of using `_qs.value(...)` for hand-edit assertions (TestValidation:150-152, TestBoolCoercion:463-465).
  - Tradeoff: Slightly longer test body; needs a note acknowledging QSettings IniFormat may stringify on `sync()`.
  - Confidence: HIGH — the `_qs.value(...)` pattern is established repeatedly in this file.
  - Blind spot: None significant.
- **Fix B**: Delete the test.
  - Strength: Cleanest — removes 4 lines that don't earn their keep.
  - Tradeoff: Loses the "isolated no-raise" failure mode (real but marginal — the round-trip test would surface it too).
  - Confidence: HIGH — round-trip test covers it transitively.
  - Blind spot: None significant.
- **Decision**: FIXED via Fix A — re-oracled to `test_setter_writes_non_str_raw_without_coercion` at `tests/test_settings.py:579-598`. Now probes `_qs.value(...)` directly with `assert not isinstance(raw, str)` to pin the no-coercion contract.

### F2 — Class docstring cites research.md §A.4 instead of §A.5

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `tests/test_reminders.py:500` (TestMalformedReminderFromDict docstring)
- **Detail**: Plan Phase 1 #1 Contract says "cite research.md §A.5" (the lessons block of the research). The docstring cites §A.4 (the matrix table). Coverage matrix is intact; only the citation pointer differs.
- **Fix**: Either flip the citation to §A.5 in the docstring, or accept §A.4 (the matrix table is arguably the more useful pointer for a future reader).
- **Decision**: FIXED — flipped `research.md §A.4` → `research.md §A.5` at `tests/test_reminders.py:500`.

### F3 — TestSettingsVoicePhraseRawSetter defers empty-string case to existing test

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: `tests/test_settings.py:561-577` (class docstring + class body)
- **Detail**: Plan Phase 1 #2 listed "write an empty string round-trips as empty" as a must-have for `TestSettingsVoicePhraseRawSetter`. The implementation defers to the existing `TestVoiceSettersRoundTrip.test_voice_phrase_setter_accepts_empty_string` (at :207-215) via an explicit cross-reference in the new class's docstring. Behavior IS pinned, just not duplicated in the new class.
- **Fix**: Accept the defer (the cross-reference avoids redundant coverage and the docstring makes the relationship explicit), or duplicate the assertion in the new class.
- **Decision**: FIXED — added `test_setter_accepts_empty_string` at `tests/test_settings.py:600-619`. Class docstring updated to drop the cross-reference note for empty-string (kept for custom-phrase round-trip, still covered elsewhere).

### F4 — Bare pytest.raises(...) without `match=` regex on 3 tests

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Test Quality
- **Location**: `tests/test_reminders.py` (malformed-ISO + non-str start_at tests), `tests/test_settings.py:622` (`test_no_setter_exists`)
- **Detail**: Plan manual gate 1.7 requires "precise oracles (e.g. `pytest.raises(KeyError)` not `pytest.raises(Exception)`)". The current tests pin the exception CLASS (not just `Exception`), so 1.7 is technically met. But the missing-key tests use `pytest.raises(KeyError, match="id")` etc. — tighter than the ISO/TypeError tests, which are bare. Pattern is inconsistent within the same class.
- **Fix**: Add narrow `match=` regexes to the bare calls (e.g. `match="fromisoformat"`, `match="has no setter"`).
- **Decision**: FIXED — tightened 4 oracles: `tests/test_reminders.py` ISO/TypeError tests now use `match="isoformat"` / `match="fromisoformat"`; `tests/test_settings.py::TestSettingsIdleThresholdHandEdits::test_no_setter_exists` uses `match="no setter"`.

### F5 — `_valid_dict` helper is an instance method

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: `tests/test_reminders.py:524-531` (TestMalformedReminderFromDict._valid_dict)
- **Detail**: Existing reminders tests build dicts via `Reminder(...).to_dict()` inline (see TestRoundTrip, TestReminderSerialization). The new class introduces an instance-method dict factory. Not a strong violation; just a fresh shape.
- **Fix**: Promote to a module-level `@pytest.fixture` named `valid_reminder_dict` (mirrors the existing `store`/`store_path` fixture pattern), or accept the per-class scoping for self-containedness.
- **Decision**: FIXED — promoted to module-level `valid_reminder_dict` fixture at `tests/test_reminders.py:40-54`; all 10 TestMalformedReminderFromDict tests now consume it via injection (function-scope keeps mutations test-local).

### F6 — test-plan.md edit is pre-Phase-1 orchestration, not Phase 1 scope

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Scope Discipline
- **Location**: `context/foundation/test-plan.md` (2-line edit, §3 row 3 Status)
- **Detail**: The 2-line working-tree edit is the `/10x-test-plan`/`/10x-new` orchestration flip (`not started` → `change opened` + change-folder cell). It pre-dates Phase 1 implementation. Phase 4's docs sync owns the next flip (`change opened` → `complete`) + the §2 R-5 backports + §6 Cookbook row + lessons.md entry.
- **Fix**: Handle via the dirty-path prompt in Phase 1's commit ritual — bundle into Phase 1's commit or leave for Phase 4. (Per the established pattern in modal-stacking-wedge's research commit, bundling is OK and avoids a stray dirty path.)
- **Decision**: FIXED + ACCEPTED-AS-RULE — recorded as `Bundle /10x orchestration edits into the change's first phase commit` in `context/foundation/lessons.md`. Fix applied by pre-staging `context/foundation/test-plan.md` into the Phase 1 touched-file set; commit ritual stages without prompting.
