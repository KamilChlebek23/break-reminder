# Storage round-trip robustness (R-5 / test-plan Phase 3) — Implementation Plan

## Overview

Ground rollout Phase 3 of `context/foundation/test-plan.md` ("Storage round-trip robustness — parametrized malformed-input"), which protects **R-5**: a user-edited or malformed-on-save `reminders.json` / `BreakReminder.ini` breaks app startup, silently drops reminders, or loses settings.

The dominant gap research surfaced is **structural, not field-level**: `ReminderStore._read()` at `break_reminder/storage/reminders.py:221-232` wraps only the JSON parse in `try/except`. The per-row `Reminder.from_dict(item)` calls on line 232 sit outside the protective block — one bad row crashes the entire load. This plan closes that gap (test-first), pins the field-level + Settings-level behaviors as a regression net, then syncs the docs that close the rollout phase.

## Current State Analysis

From `context/changes/testing-storage-malformed-input/research.md` (full document; 272 lines).

**`break_reminder/storage/reminders.py`** (185 lines, last touched by `1d8d0a8`):

- 6-field `Reminder` dataclass at lines 130-141. Only `lead_minutes` (via `_coerce_lead_minutes` at lines 36-72) and `start_at` / `end_at` (via `_coerce_aware_utc` at lines 75-...) have field-level coercion. `id`, `name`, `rrule_str` are bare subscripts / passthroughs.
- `_read()` at lines 221-232 wraps the JSON parse in `try/except (json.JSONDecodeError, OSError)`. The list comprehension on line 232 is OUTSIDE the protective block — per-row exceptions propagate.
- **No new persisted field has been added since S-06b** (`797328d`). The §2 R-5 audit lens "every field added since S-06b" is empirically empty.
- `tests/test_reminders.py` (36 tests): `TestCoerceLeadMinutes` (lines 320-397) is the canonical pattern Phase 3 mirrors; `TestDefensiveBehavior` (lines 202-230) already covers missing file and unparseable-JSON-top-level; `TestCoerceAwareUtc` (lines 400-488) already covers tz-naive `start_at`/`end_at`. **The remaining gaps are per-row in a multi-row list, malformed ISO (non-tz cases), wrong-type on raw fields, and unknown extra keys.**

**`break_reminder/storage/settings.py`** (325 lines):

- 8 persisted INI keys via `_Keys` at lines 58-66. Defaults at lines 46-52; range constants at lines 21-42.
- Three generic shape-coercion helpers at lines 101-127: `_get_int`, `_get_bool`, `_get_str`. All have safe-fallback semantics.
- **No new persisted key has been added since S-01 / S-04** (`9307c4d`). The §2 R-5 audit lens "clamp helpers added since S-04" lands on a narrower surface than its prose suggested.
- Three unprotected surfaces (all retained as-is per Q2 = `all_pin`):
  1. **`idle_threshold_sec`** (lines 161-164) — getter has lower-clamp only (`max(1, _get_int(...))`), no upper bound, no setter at all.
  2. **`voice_phrase.setter`** (lines 247-272, added in `7b3a8f8`) — only post-S-04 raw/unchecked boundary; docstring at lines 260-266 explicitly documents the round-trip behavior as intentional.
  3. **"Unknown extra key"** — current behavior is silently ignored; correct forward-compat shape, but unpinned.
- `tests/test_settings.py` (54 tests): `TestBoolCoercion` (lines 453-472) covers `_get_bool` semantics but only against `_Keys.VOICE_ENABLED`; `TestSnoozeValidation` (lines 268-364) covers the snooze upper/lower bounds; `TestValidation` (lines 121-166) covers `break_interval_min`. **No test covers `idle_threshold_sec` × OoR-high, `voice_phrase.setter` × non-str, or "unknown extra key" for any of the 8 keys.**

**`break_reminder/storage/event_log.py`** — OUT OF SCOPE. Append-only; no `csv.reader`; cross-module search confirms only writers call it. The test-plan §3 row 3 "named modules" wording was correct.

**App entry points** — `main.py:128-143` wraps `_run()` in a `bootstrap-error.log` + `MessageBoxW` catch (production / PyInstaller). `break_reminder/__main__.py:14-15` (dev) has no catch. **Phase 3's unit-test layer sidesteps this divergence entirely** — all tests target storage modules directly, not `main()`.

**`context/foundation/lessons.md`** — one entry only (Google docstrings). The S-06b "storage `from_dict` is the boundary" lesson was NEVER generalized. Phase 3's docs sync closes that loop.

### Key Discoveries

- **Structural finding cross-confirmed by 2 of 3 sub-agents** — `break_reminder/storage/reminders.py:221-232`. One bad row crashes the whole load; 5 well-formed reminders adjacent to one bad row all vanish from `list_all()`.
- **Established mirror pattern** — `tests/test_reminders.py:320-397` (`TestCoerceLeadMinutes`) ships the 4-invariant cluster pattern (passthrough / type coercion / lower clamp / upper clamp) all new boundary-helper tests in this plan follow.
- **The `_coerce_lead_minutes` self-healing precedent** — `break_reminder/storage/reminders.py:36-72`. Establishes "storage layer treats every disk read as potentially-hostile and quietly normalizes". The Phase 3 fix follows the same shape at the `_read()` level (per-row drop with log).
- **`pytest-qt` caplog** — pytest's standard `caplog` fixture works with the project's logging setup; no Qt-specific harness needed (this is a pure-function unit test phase).
- **No existing `logging` import in `reminders.py`** — Phase 3 GREEN adds `import logging` + `logger = logging.getLogger(__name__)` at the top of the module. First time the module uses `logging`.

## Desired End State

When this plan is complete:

1. **`ReminderStore._read()` is row-resilient.** A multi-row `reminders.json` with one malformed row loads the well-formed rows and drops the bad one with a `logger.warning(...)` entry naming the row index + exception. A non-list top-level JSON value returns `[]` with a warning. Today's "one bad row crashes the entire load" failure mode is eliminated.
2. **`Reminder.from_dict`'s per-field behavior is pinned as a regression net.** Every applicable (field × §2 R-5 class) cell has a test asserting today's behavior — what raises, what passes through, what's silently ignored. Future refactors that change a field's coerce-point trip a test.
3. **`Settings`'s unprotected hand-edit surfaces are pinned.** `idle_threshold_sec` accepting any value ≥ 1, `voice_phrase.setter` writing raw, `_get_bool` symmetry across all 3 boolean keys, and "unknown INI key" silently-ignored on every key — all asserted via tests.
4. **`context/foundation/test-plan.md` §2 R-5 reflects the empirical findings.** Source-column path typo fixed; S-04→S-01 naming aligned with the archive header; "Must challenge" cell rewritten so future readers don't chase the empty "since S-06b / since S-04" audit lens.
5. **`context/foundation/test-plan.md` §3 row 3 Status: `complete`.** §6 Cookbook "Storage hand-edit robustness" row carries the shipped pattern (not "TBD").
6. **`context/foundation/lessons.md` carries the boundary-coerce rule.** The S-06b retrospective's "lesson never generalized" finding is closed.
7. **All existing tests still pass.** No regression in the 36 + 54 + 13 = 103 storage tests.

## What We're NOT Doing

- **No `event_log.py` work.** Research confirmed it's strictly append-only; out of R-5 scope. The cookbook §6 update mentions this explicitly so a future reader doesn't re-investigate.
- **No `idle_threshold_sec` upper-clamp fix.** Per Q2 = `all_pin`. Pinning today's no-upper-clamp behavior here; if/when the silent-loss surface bites, a separate `bugfix-idle-threshold-clamp` change can frame the product decision (pick a max value).
- **No `voice_phrase.setter` coercion fix.** Per Q2 = `all_pin`. The setter's raw behavior is documented as intentional in its docstring (`break_reminder/storage/settings.py:260-266`); pinning preserves that.
- **No "raise on unknown INI key" behavior change.** Silent ignore is the correct forward-compat shape; pinning preserves it.
- **No integration / app-startup tests.** Phase 3 is pure-function unit tests; the `main.py` vs `__main__.py` entry-point divergence is out of scope (Phase 4 of the rollout, if needed, picks up the integration surface).
- **No new test files.** Per Q3 = `extend_existing`. New test classes land in `tests/test_reminders.py` and `tests/test_settings.py` alongside the existing boundary-helper clusters.
- **No AGENTS.md edit.** AGENTS.md captures architectural patterns; the `_read` row-containment fix is a small bugfix, not a pattern shift. The cookbook §6 update + lessons.md entry are the right docs surfaces.
- **No production change to Settings.** All 3 Settings unprotected surfaces are pinned, not fixed (per Q2).

## Implementation Approach

Four phases, mirroring the modal-stacking-wedge precedent's RED → GREEN → docs shape (Phases 2-4) with a prepended pin-only Phase 1 for the pure-addition surface:

| # | Phase | Production change? | Phase intent |
|---|---|---|---|
| 1 | Pin-only regression net | No | Add `TestMalformedReminderFromDict` + `TestSettingsHandEditRobustness` (and friends). All tests pass on landing. Pure addition. |
| 2 | RED — `_read` row-containment failing tests | No (test-only) | Add `TestReminderStoreReadResilience`; tests fail RED today because the list comprehension at `reminders.py:232` propagates per-row exceptions. |
| 3 | GREEN — apply the `_read` fix | Yes (~10 LoC) | Wrap per-row `Reminder.from_dict` in `try/except`; add top-level `isinstance(raw, list)` guard; add `import logging` + `logger`. Phase 2 RED tests turn GREEN; full existing suite still PASS (regression sweep). |
| 4 | Docs sync — close the rollout phase | No (docs only) | test-plan.md §2 R-5 backports + §3 row 3 Status `complete` + §6 Cookbook row; lessons.md new entry. |

Test design follows the codebase convention (Q3 = `extend_existing`):

- All new test classes live in `tests/test_reminders.py` (after `TestCoerceAwareUtc`) or `tests/test_settings.py` (after `TestSnapshot`).
- Each class docstring names the invariants it pins (mirroring `TestCoerceLeadMinutes.__doc__` shape).
- Per-test docstrings explain WHY the assertion matters (regression catchment, not just behavior description).
- Use `@pytest.fixture` for shared setup (e.g. `store_path`, `caplog` configuration), not module-level state.

## Critical Implementation Details

**Phase 3 `_read` fix — exception tuple + log shape**

The fix is non-obvious in three ways and the shape matters for downstream tests (Phase 2 RED assertions and the cookbook §6 entry both reference it):

- **Exception tuple `(KeyError, ValueError, TypeError)`.** `Reminder.from_dict` can raise any of three: `KeyError` (missing `id` / `name` / `start_at`), `ValueError` (malformed ISO from `datetime.fromisoformat`), `TypeError` (passing a non-dict to a `dict[…]` subscript when iterating a non-list top-level). Catching `Exception` is too broad (swallows programming errors); catching only `KeyError` would let `start_at` ISO failures propagate.
- **`isinstance(raw, list)` top-level guard.** `json.load` can return any JSON type; iterating a dict yields keys (strings), iterating a string yields chars. Both crash inside `from_dict`. Without the guard, the per-row `try/except` would log N spurious warnings; with the guard, the malformed shape produces one warning and `[]`.
- **`logger.warning` (not `info`, not `error`).** Per the `_coerce_*` self-healing precedent, the storage layer treats hand-edits as expected input — not an error. WARNING is the right level: the user might want to know, but the app keeps running. The log message must name the row index (when applicable) and the exception so a user inspecting the log can identify which entry in the file is bad.

The exact log message shape and exception tuple are documented in Phase 3's Contract section.

## Phase 1: Pin-only regression net (no production change)

### Overview

Add `TestMalformedReminderFromDict` to `tests/test_reminders.py` and `TestSettingsHandEditRobustness` (plus 2 sibling classes) to `tests/test_settings.py`. All tests pass on landing — pure addition that closes the §2 R-5 coverage matrix for behaviors that don't need a production change.

### Changes Required

#### 1. `tests/test_reminders.py` — TestMalformedReminderFromDict

**File**: `tests/test_reminders.py`

**Intent**: Pin `Reminder.from_dict`'s behavior on each malformed-input class per persisted field. These per-field behaviors don't change with the Phase 3 `_read` fix (the fix is at a higher level). Class lives after `TestCoerceAwareUtc` to preserve the boundary-helper cluster ordering.

**Contract**: New `TestMalformedReminderFromDict` test class with class-level docstring naming the matrix it covers (cite research.md §A.5). One test per (field × applicable class) cell from research.md §A.4 that is currently empty (i.e. not already covered by `TestCoerceLeadMinutes`, `TestCoerceAwareUtc`, `TestRoundTrip`, or `TestReminderSerialization`). At minimum:

- Missing required keys: `id`, `name`, `start_at` (3 tests; document that today they raise `KeyError`).
- Malformed ISO datetime: `start_at`, `end_at` (2 tests; today raise `ValueError` from `datetime.fromisoformat`).
- Wrong-type on raw fields: `name` as non-str, `rrule_str` as non-str (2 tests; document today's pass-through behavior).
- Unknown extra key in the dict (1 test; today silently ignored).

Each test asserts today's behavior via `with pytest.raises(...)` or `assert recovered.field == expected`. No code change required for these to pass.

#### 2. `tests/test_settings.py` — TestSettingsIdleThresholdHandEdits + TestSettingsVoicePhraseRawSetter + TestSettingsBoolCoercionSymmetry + TestSettingsUnknownKey

**File**: `tests/test_settings.py`

**Intent**: Pin the three Settings unprotected surfaces + the `_get_bool` symmetry gap. All four classes land after `TestSnapshot` (lines 475-498) to preserve the file's "defaults → round-trip → validation → snapshot" ordering. All tests pass on landing.

**Contract**: Four new test classes:

- **`TestSettingsIdleThresholdHandEdits`** — pin getter behavior for `idle_threshold_sec`. At minimum: a) writing `999999` via `QSettings` directly round-trips as `999999` (no upper clamp); b) writing `"not-a-number"` falls back to `DEFAULT_IDLE_THRESHOLD_SEC` via `_get_int`'s `ValueError → default` branch; c) writing `0` clamps up to `1` via the lower clamp; d) confirm `Settings` has no `idle_threshold_sec.setter` (e.g. `with pytest.raises(AttributeError): settings.idle_threshold_sec = 30`).
- **`TestSettingsVoicePhraseRawSetter`** — pin the raw-setter contract. At minimum: a) write a non-str via the setter (e.g. `settings.voice_phrase = 42`); read back returns `str(42) == "42"` via `_get_str`'s `str(...)` coercion; b) write an empty string round-trips as empty; c) cite the setter's docstring at `settings.py:260-266` as the source-of-truth.
- **`TestSettingsBoolCoercionSymmetry`** — extend `TestBoolCoercion`'s 13 cases to `_Keys.AUTOSTART` and `_Keys.PAUSED` (currently only wired against `_Keys.VOICE_ENABLED`). Two parametrized tests (one per key) replaying the same `non_truthy_strings_read_as_false` / `truthy_strings_read_as_true` matrix.
- **`TestSettingsUnknownKey`** — pin "unknown INI key" silently-ignored behavior. At minimum: a) write an unknown key like `scheduling/unknown_future_setting = "foo"` via raw `QSettings`; b) construct a fresh `Settings`; c) assert all 8 documented keys still return their default values (none crash); d) (optional) assert the unknown key is still present in the INI file on disk (we don't strip it).

### Success Criteria

#### Automated Verification

- New test classes added to `tests/test_reminders.py` and `tests/test_settings.py`; `uv run pytest tests/test_reminders.py tests/test_settings.py -v` PASS.
- Full test suite still PASS: `uv run pytest`.
- Lint clean: `uv run ruff check tests/test_reminders.py tests/test_settings.py`.
- Format clean: `uv run ruff format --check tests/test_reminders.py tests/test_settings.py`.
- Type check clean: `uv run pyright tests/test_reminders.py tests/test_settings.py`.
- pre-commit hooks pass: `pre-commit run --files tests/test_reminders.py tests/test_settings.py`.

#### Manual Verification

- Read each new class docstring — the invariants named are concretely tied to research.md §A.5 / §B.4 gaps, not vague "covers malformed input" prose.
- Read 2-3 representative test bodies — assertions check today's behavior precisely (e.g. exception type matches `KeyError` not `Exception`).
- Confirm new test classes are positioned in the correct files (`test_reminders.py` after `TestCoerceAwareUtc`; `test_settings.py` after `TestSnapshot`).

**Implementation Note**: After completing Phase 1 and all automated verification passes, pause here for manual confirmation from the human that the manual review was successful before proceeding to Phase 2.

---

## Phase 2: RED — `_read` row-containment failing tests

### Overview

Add `TestReminderStoreReadResilience` to `tests/test_reminders.py` (after `TestDefensiveBehavior`). Tests assert the **post-fix** invariant: a list with one bad row drops only that row + logs a warning; well-formed siblings load; a non-list top-level returns `[]` with a warning. The tests fail RED today because the list comprehension at `break_reminder/storage/reminders.py:232` propagates per-row exceptions.

### Changes Required

#### 1. `tests/test_reminders.py` — TestReminderStoreReadResilience

**File**: `tests/test_reminders.py`

**Intent**: Pin Fix A's invariant via failing tests. The class lives immediately after `TestDefensiveBehavior` (lines 202-230) — same defensive cluster, extending it from "whole-file-corrupt → []" to "per-row-corrupt → drop bad + keep good".

**Contract**: New `TestReminderStoreReadResilience` test class. At minimum 4 tests:

- **`test_one_bad_row_drops_only_bad_row`** — write a JSON list of 3 reminder-dicts where the middle one has `start_at = "not-a-date"`. `store.list_all()` returns 2 well-formed reminders (the first and third). Today: ValueError from `datetime.fromisoformat` propagates; `list_all()` raises.
- **`test_bad_row_logs_warning`** — same setup; use pytest's `caplog` fixture at WARNING level; assert at least one record matches "reminders.json row 1" (or row index of the bad entry) AND the exception class name appears in the log message.
- **`test_all_bad_rows_returns_empty_list`** — write a JSON list of 3 reminder-dicts all with malformed `start_at`. `list_all()` returns `[]`; `caplog` captures 3 WARNING records. Today: raises on the first row.
- **`test_top_level_dict_returns_empty_list_with_warning`** — write `{}` (or `{"key": "value"}`) to the file. `list_all()` returns `[]`; `caplog` captures exactly 1 WARNING record matching "top-level is not a list". Today: raises (iterating a dict yields keys → `from_dict("key")` raises TypeError on `data["id"]`).
- (Optional 5th) **`test_top_level_string_returns_empty_list_with_warning`** — write `"foo"` to the file. Same expected behavior as the dict case. Today: also raises.

Use the existing `store_path` / `store` fixtures from `tests/test_reminders.py:28-37`. Use pytest's built-in `caplog` fixture (`def test_x(self, caplog, store_path):`) — no Qt event loop, no extra fixtures.

**Phase 2 expected outcome**: `uv run pytest tests/test_reminders.py::TestReminderStoreReadResilience -v` shows **4 (or 5) FAILED**. The existing 36 + Phase-1 additions still PASS. This is the canonical RED state.

### Success Criteria

#### Automated Verification

- New `TestReminderStoreReadResilience` class added; `uv run pytest tests/test_reminders.py::TestReminderStoreReadResilience -v` shows FAIL on every new test (RED).
- Existing tests unaffected: `uv run pytest tests/test_reminders.py -k "not TestReminderStoreReadResilience"` PASS.
- Full suite shows the expected delta: pre-commit passes (no lint/format/type issues introduced by the new test class).
- Lint / format / type / pre-commit pass on the new test class.

#### Manual Verification

- Read the RED failure messages — each one points clearly at "expected behavior X, got exception Y". A future reader can understand from the failure alone what the post-fix behavior should be.
- Confirm `caplog` is being used (not `monkeypatch`-ing `logging`); the test follows pytest's idiomatic caplog pattern.
- Confirm the assertions use behavior-level oracles (the RRULE/contract says X), not implementation-mirror oracles (the source code does X).

**Implementation Note**: After completing Phase 2 and all automated verification confirms the expected RED state, pause for manual confirmation before proceeding to Phase 3.

---

## Phase 3: GREEN — apply the `_read` fix

### Overview

Modify `break_reminder/storage/reminders.py` so per-row exceptions in `_read` are caught, logged, and skipped; add a top-level shape guard so non-list JSON returns `[]` with a warning. Phase 2 RED tests turn GREEN. All existing 36 + Phase-1 additions still PASS (regression sweep).

### Changes Required

#### 1. `break_reminder/storage/reminders.py` — _read row-containment fix

**File**: `break_reminder/storage/reminders.py`

**Intent**: Prevent any single malformed JSON entity (per-row exception OR non-list top-level) from crashing `ReminderStore._read()`. Bad rows are dropped with a `logger.warning` naming the row index + exception; well-formed rows are preserved. Mirrors the self-healing precedent of `_coerce_lead_minutes` at the row level rather than the field level.

**Contract**: Three additive changes to the module:

1. **Imports** — add `import logging` (alphabetically positioned with the stdlib block at the top of the file, after `import json` / before `import threading`).
2. **Module-level logger** — after the `from break_reminder.storage.paths import reminders_json_path` line, add: `logger = logging.getLogger(__name__)`.
3. **`_read` body** — replace lines 221-232 with the shape below. The exception tuple `(KeyError, ValueError, TypeError)` matches the three classes `Reminder.from_dict` can raise (`KeyError` on missing required key, `ValueError` on malformed ISO, `TypeError` when a non-dict is passed in). The `isinstance(raw, list)` guard handles the non-list top-level case (avoiding N spurious per-row warnings when iterating a dict yields keys).

```python
def _read(self) -> list[Reminder]:
    if not self._path.exists():
        return []
    try:
        with self._path.open("r", encoding="utf-8") as fp:
            raw = json.load(fp)
    except (json.JSONDecodeError, OSError):
        # Defensive: a corrupted file shouldn't crash the app on launch.
        # The user will lose the broken file's contents, but the INI
        # settings and event log are unaffected.
        return []
    if not isinstance(raw, list):
        logger.warning(
            "reminders.json top-level is not a list (got %s); ignoring",
            type(raw).__name__,
        )
        return []
    result: list[Reminder] = []
    for index, item in enumerate(raw):
        try:
            result.append(Reminder.from_dict(item))
        except (KeyError, ValueError, TypeError) as exc:
            # FR-015 self-healing: a hand-edit that breaks one row must
            # not nuke the well-formed siblings. Mirror the row-level
            # contract of _coerce_lead_minutes at the row level.
            logger.warning(
                "reminders.json row %d is malformed (%s: %s); dropping",
                index,
                type(exc).__name__,
                exc,
            )
    return result
```

#### 2. `break_reminder/storage/reminders.py` — module docstring touch-up (small)

**File**: `break_reminder/storage/reminders.py`

**Intent**: Document the row-level self-healing in the module docstring so a future reader doesn't have to re-derive it from `_read`. Append one sentence to the existing module docstring's "Recurrence" paragraph (lines 8-12) or as a new short paragraph.

**Contract**: Add ~2 sentences naming that `_read` is row-resilient: malformed per-row entries are dropped with a WARNING-level log; the file-level JSON parse fallback (corrupt JSON → `[]`) and the row-level fallback (one bad row → that row dropped) are independent layers. No code change beyond the docstring edit.

### Success Criteria

#### Automated Verification

- Phase 2 RED tests turn GREEN: `uv run pytest tests/test_reminders.py::TestReminderStoreReadResilience -v` PASS.
- Existing tests still PASS (regression sweep): `uv run pytest tests/test_reminders.py` PASS (all 36 + Phase-1 additions + Phase-2 additions).
- Full project suite still PASS: `uv run pytest`.
- Lint / format / type check / pre-commit pass: `uv run ruff check break_reminder/storage/reminders.py && uv run ruff format --check break_reminder/storage/reminders.py && uv run pyright break_reminder/storage/reminders.py && pre-commit run --files break_reminder/storage/reminders.py`.

#### Manual Verification

- `git diff break_reminder/storage/reminders.py` shows ~10 LoC of production change concentrated in `_read` + 2 import-level lines + ~2 lines of docstring. No drive-by edits.
- Confirm the log message shape (`row %d is malformed (%s: %s); dropping`) is what Phase 2 tests assert on. A drift here would silently regress one of the RED tests.
- Confirm `logger.warning` (not `logger.error` or `logger.info`) per the self-healing intent.
- Manual smoke: edit a real `reminders.json` to add a row with `"start_at": "not-a-date"` in the middle of 2 valid rows. Launch the app; confirm well-formed reminders still appear in the tray menu / dialog. Check `bootstrap-error.log` is NOT created; check the application log (wherever Python `logging` is captured) contains the WARNING.

**Implementation Note**: After Phase 3 and all automated verification passes, pause for manual confirmation. The manual smoke is load-bearing — Phase 2's caplog tests assert the log shape but not the end-to-end runtime behavior.

---

## Phase 4: Docs sync — close the rollout phase

### Overview

Apply the test-plan §2 R-5 backports research surfaced, flip §3 row 3 Status to `complete`, update §6 Cookbook with the shipped pattern, and add a new `context/foundation/lessons.md` entry closing the S-06b "lesson never generalized" loop.

### Changes Required

#### 1. `context/foundation/test-plan.md` §2 R-5 — backports

**File**: `context/foundation/test-plan.md`

**Intent**: Land the 3 backport candidates research surfaced (cited in research.md "Open Questions" #1-#3). These are cheap, on-topic, and prevent future re-reads from chasing an empirically-empty audit lens.

**Contract**: Three targeted edits to the R-5 row of the Risk Map (§2) and the Risk Response Guidance table:

- **Source path typo** — the R-5 row's Source column cites `S-06b retrospective impl-review (`797328d`)…`; the actual review file is `impl-review-phase-1.md`, not `impl-review.md`. If the test-plan currently cites the explicit filename anywhere in §2 R-5, correct it.
- **S-04 → S-01 naming alignment** — the Risk Response Guidance R-5 "Must challenge" cell currently says `audit storage/settings.py clamp helpers added since S-04`. The archive review header for `2026-05-25-settings-break-interval/reviews/impl-review.md:2` says `S-01`. Cross-reference `context/foundation/roadmap.md` to confirm which label is canonical, then align the test-plan reference to match (likely change S-04 → S-01).
- **Response-guidance refinement** — rewrite the R-5 "Must challenge" cell so it doesn't lean on the empirically-empty "since S-06b / since S-04" lens. The new cell should point at: (a) **pre-existing un-coerced** reminders fields (`name`, `id`, `start_at` ISO parse, `rrule_str`); (b) the **structural** `_read` row-containment that Phase 3 just closed; (c) the **post-S-04 raw** `voice_phrase.setter`; (d) the **`idle_threshold_sec` missing upper clamp** (pinned, not fixed — flag for future bugfix).

#### 2. `context/foundation/test-plan.md` §3 row 3 — Status flip

**File**: `context/foundation/test-plan.md`

**Intent**: Mark Phase 3 complete in the orchestrator's state table. Bump `rollout_phases_complete: 2 → 3` in the YAML frontmatter.

**Contract**: Single Status cell edit (`change opened` → `complete`); preserve the Change folder cell (`` `testing-storage-malformed-input` ``). Frontmatter: `rollout_phases_complete: 2 → 3`.

#### 3. `context/foundation/test-plan.md` §6 Cookbook — "Storage hand-edit robustness" row

**File**: `context/foundation/test-plan.md`

**Intent**: Replace the "TBD" row content with the shipped pattern, mirroring the §6 entries Phase 1 and Phase 2 wrote.

**Contract**: The "Storage hand-edit robustness" row's Pattern cell should reference: `tests/test_reminders.py::TestMalformedReminderFromDict` (per-field from_dict pinning), `tests/test_reminders.py::TestReminderStoreReadResilience` (per-row drop-with-log; the structural fix at `break_reminder/storage/reminders.py:_read`), and `tests/test_settings.py::TestSettingsHandEditRobustness` (Settings raw-edit pinning). Name the canonical example structure (caplog for log assertion; one bad row + N well-formed rows for the row-containment case). Add a one-line note that `event_log.py` is out of scope because it has no read boundary (cite research.md §B for the cross-module audit).

#### 4. `context/foundation/lessons.md` — boundary-coerce rule

**File**: `context/foundation/lessons.md`

**Intent**: Generalize the S-06b retrospective F4 + Phase 3 structural confirmation into a rule consumed by future `/10x-frame`, `/10x-research`, `/10x-plan`, `/10x-impl-review` runs. Closes the research.md C.5 finding that "the S-06b lesson was never generalized into `lessons.md`".

**Contract**: New entry following the existing `lessons.md` template (Context / Problem / Rule / Applies to). The rule should name: (a) storage `from_dict` boundaries (and equivalents) treat every disk read as potentially-hostile input per FR-015's "Notepad-editable" stance; (b) every hand-editable field needs a `_coerce_*` helper that maps any input to a safe value; (c) the boundary-level loader (e.g. `ReminderStore._read`) must wrap per-row parse calls in try/except so one bad row doesn't crash the entire load. Cite `_coerce_lead_minutes` at `break_reminder/storage/reminders.py:36-72` as the field-level canonical example and `ReminderStore._read` post-Phase-3 as the row-level canonical example. Applies to: `plan`, `implement`, `impl-review`.

### Success Criteria

#### Automated Verification

- All 4 docs modified: `git diff --name-only HEAD~1` (or the Phase 4 commit) shows exactly `context/foundation/test-plan.md` and `context/foundation/lessons.md`. No `.py` files touched.
- Sanity: `git diff --stat` of the Phase 4 commit shows zero Python file changes.
- Full test suite still PASS (regression sanity that docs-only edits didn't break anything): `uv run pytest`.

#### Manual Verification

- `context/foundation/test-plan.md` §3 row 3 Status reads `complete`; frontmatter `rollout_phases_complete: 3`.
- §2 R-5 Risk Response Guidance "Must challenge" cell no longer references "since S-06b" / "since S-04" as the audit lens; instead points at the surfaces named in #1.contract (a)-(d).
- §6 Cookbook "Storage hand-edit robustness" row names the three test class targets + the post-Phase-3 `_read` fix; no remaining "TBD" in the row.
- `context/foundation/lessons.md` has a new entry following the existing template; rule wording is concrete (names files, names patterns), not vague.

**Implementation Note**: After Phase 4 and all automated verification passes, pause for manual confirmation. After confirmation, the rollout phase is complete and ready for `/10x-impl-review testing-storage-malformed-input` (per the test-plan post-Phase-N continuation rule).

---

## Testing Strategy

### Unit Tests

- **Phase 1 pin-only**: per-field `Reminder.from_dict` behaviors (missing key / wrong type / malformed ISO / unknown extra key); per-key Settings hand-edit robustness (idle_threshold_sec no upper clamp; voice_phrase raw setter; _get_bool symmetry; unknown INI key); ~12-15 new tests across the two files.
- **Phase 2 RED + Phase 3 GREEN**: `TestReminderStoreReadResilience` — 4-5 tests pinning the post-fix row-containment invariant (one bad row → that row dropped; all bad → []; non-list top-level → []; caplog assertions throughout).
- All tests run under `uv run pytest` with the existing session-scoped `_qt_app` fixture (autouse for storage tests; harmless here because we don't touch QWidgets).

### Integration Tests

Out of scope for Phase 3. Per the test-plan §3 row 3 ("Test types: Parametrized pure-function unit tests; no Qt event loop"), integration coverage is Phase 4's responsibility. The `main.py` vs `__main__.py` entry-point divergence is explicitly out of Phase 3 scope.

### Manual Testing Steps

1. **End-to-end smoke for Phase 3 fix.** Edit `%APPDATA%\BreakReminder\reminders.json` directly: insert a row with `"start_at": "definitely-not-a-date"` in between two valid rows. Launch the app. Confirm:
   - The well-formed reminders appear in the tray quick-menu / settings dialog.
   - The bad row is NOT shown anywhere.
   - The app does NOT pop the panic dialog (`%APPDATA%\BreakReminder\bootstrap-error.log` is NOT created).
   - The Python logger emits a WARNING with row index + exception class. (How this surfaces depends on the project's logging config — at minimum, running via `python -m break_reminder` should show the warning on stderr.)

2. **Docs review for Phase 4.** Open `context/foundation/test-plan.md` and confirm §2 R-5 + §3 row 3 + §6 Cookbook all look right. Open `context/foundation/lessons.md` and read the new entry from a "future-me" perspective — does it tell me what to do?

3. **Regression sweep.** Pause Settings, change break-interval, resume, take a break, add a reminder, edit a reminder, delete a reminder. All should work as before. Phase 3's fix only changes the `_read` path; nothing downstream should be affected.

## Performance Considerations

Negligible. The `_read` change replaces a list comprehension with a `for` loop + per-row `try/except`. For typical reminder counts (≤ 50 per the PRD's small-team / single-user shape), the overhead is microseconds. The `isinstance(raw, list)` check is one bytecode operation. No optimization needed; no profiling required.

## Migration Notes

None. The `_read` fix is strictly more permissive than today's behavior (it accepts inputs that previously crashed) — no on-disk format change, no backward-compat tax. A user with an existing well-formed `reminders.json` sees zero behavior change. A user with a malformed `reminders.json` sees an improvement (data preserved instead of lost).

## References

- Research: `context/changes/testing-storage-malformed-input/research.md`
- Test plan: `context/foundation/test-plan.md` §2 R-5, §3 row 3, §6 Cookbook
- Canonical mirror pattern: `tests/test_reminders.py:320-397` (`TestCoerceLeadMinutes`) + `tests/test_reminders.py:400-488` (`TestCoerceAwareUtc`)
- Source-of-truth for `_read` fix: `break_reminder/storage/reminders.py:221-232`
- S-06b retrospective F4: `context/archive/2026-05-27-reminders-lead-time/reviews/impl-review-phase-1.md:84-92`
- S-01 (test-plan calls it "S-04") F5 shared-bounds-constants pattern: `context/archive/2026-05-25-settings-break-interval/reviews/impl-review.md:80-88`
- Lessons.md template: `context/foundation/lessons.md`

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. See `references/progress-format.md`.

### Phase 1: Pin-only regression net

#### Automated

- [x] 1.1 `TestMalformedReminderFromDict` added to `tests/test_reminders.py` after `TestCoerceAwareUtc`; class covers per-field malformed-input cases from research.md §A.4 not already covered (missing required keys, malformed ISO, wrong-type, unknown extra key) — 97f87dd
- [x] 1.2 `TestSettingsIdleThresholdHandEdits` + `TestSettingsVoicePhraseRawSetter` + `TestSettingsBoolCoercionSymmetry` + `TestSettingsUnknownKey` added to `tests/test_settings.py` after `TestSnapshot` — 97f87dd
- [x] 1.3 New tests PASS on landing: `uv run pytest tests/test_reminders.py tests/test_settings.py -v` — 97f87dd
- [x] 1.4 Full suite PASS: `uv run pytest` — 97f87dd
- [x] 1.5 Lint / format / type / pre-commit clean on the two test files — 97f87dd

#### Manual

- [x] 1.6 Each new class docstring names invariants concretely (tied to research.md §A.5 / §B.4); not vague "covers malformed input" prose — 97f87dd
- [x] 1.7 Representative test bodies use precise oracles (e.g. `pytest.raises(KeyError)` not `pytest.raises(Exception)`) — 97f87dd
- [x] 1.8 New classes are positioned in the correct files at the correct insertion points — 97f87dd

### Phase 2: RED — `_read` row-containment failing tests

#### Automated

- [x] 2.1 `TestReminderStoreReadResilience` added to `tests/test_reminders.py` after `TestDefensiveBehavior`; ≥ 4 tests covering the contract in Phase 2 Changes Required #1 — 5468143
- [x] 2.2 New tests FAIL RED: `uv run pytest tests/test_reminders.py::TestReminderStoreReadResilience -v` shows FAIL on every new test — 5468143
- [x] 2.3 Existing + Phase 1 tests unaffected: `uv run pytest tests/test_reminders.py -k "not TestReminderStoreReadResilience"` PASS — 5468143
- [x] 2.4 Lint / format / type / pre-commit clean on the new test class — 5468143

#### Manual

- [x] 2.5 RED failure messages clearly indicate the expected post-fix behavior (a future reader can understand the fix from the failure alone) — 5468143
- [x] 2.6 Tests use pytest's `caplog` fixture (not `monkeypatch`ed logging); idiomatic pattern — 5468143
- [x] 2.7 Assertions use behavior-level oracles, not implementation-mirror oracles — 5468143

### Phase 3: GREEN — apply the `_read` fix

#### Automated

- [x] 3.1 `break_reminder/storage/reminders.py` modified: `import logging` added; `logger = logging.getLogger(__name__)` added at module level; `_read` body replaced per Phase 3 Changes Required #1 contract
- [x] 3.2 Module docstring updated to document the row-resilience (Phase 3 Changes Required #2)
- [x] 3.3 Phase 2 RED tests turn GREEN: `uv run pytest tests/test_reminders.py::TestReminderStoreReadResilience -v` PASS
- [x] 3.4 Existing tests still PASS (regression sweep): `uv run pytest tests/test_reminders.py` PASS
- [x] 3.5 Full suite still PASS: `uv run pytest`
- [x] 3.6 Lint / format / type / pre-commit clean on `reminders.py`

#### Manual

- [ ] 3.7 `git diff break_reminder/storage/reminders.py` shows ~10 LoC of production change concentrated in `_read` + 2 import-level lines + ~2 docstring lines; no drive-by edits
- [ ] 3.8 Log message shape (`row %d is malformed (%s: %s); dropping`) matches what Phase 2 caplog tests assert on
- [ ] 3.9 End-to-end smoke: edit a real `reminders.json` with one bad row; launch app; well-formed reminders appear; bad row silently dropped; no panic dialog; WARNING in app log

### Phase 4: Docs sync — close the rollout phase

#### Automated

- [ ] 4.1 `git diff --name-only` for the Phase 4 commit shows exactly `context/foundation/test-plan.md` + `context/foundation/lessons.md`; no `.py` files
- [ ] 4.2 `git diff --stat` shows zero Python file changes
- [ ] 4.3 Full suite PASS (regression sanity): `uv run pytest`

#### Manual

- [ ] 4.4 `context/foundation/test-plan.md` §3 row 3 Status reads `complete`; frontmatter `rollout_phases_complete: 3`
- [ ] 4.5 §2 R-5 Risk Response Guidance "Must challenge" cell rewritten per Phase 4 Changes Required #1 contract (a)-(d); no remaining "since S-06b" / "since S-04" framing
- [ ] 4.6 §6 Cookbook "Storage hand-edit robustness" row names all three test class targets + post-Phase-3 `_read` fix; no remaining "TBD"
- [ ] 4.7 `context/foundation/lessons.md` carries a new entry following the existing template; rule wording is concrete (names files, names patterns)
- [ ] 4.8 Source path typo (`impl-review.md` → `impl-review-phase-1.md`) and S-04 → S-01 naming corrections both applied if applicable to any §2 R-5 cells
