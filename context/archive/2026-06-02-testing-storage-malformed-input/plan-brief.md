# Storage round-trip robustness (R-5 / test-plan Phase 3) — Plan Brief

> Full plan: `context/changes/testing-storage-malformed-input/plan.md`
> Research: `context/changes/testing-storage-malformed-input/research.md`

## What & Why

Ground rollout Phase 3 of `context/foundation/test-plan.md` against **R-5** — a user-edited or malformed-on-save `reminders.json` / `BreakReminder.ini` breaks app startup, silently drops reminders, or loses settings. Research surfaced one dominant gap: `ReminderStore._read()` at `break_reminder/storage/reminders.py:221-232` wraps only the JSON parse in `try/except`. The per-row `Reminder.from_dict` calls on line 232 sit outside the protective block — one bad row crashes the entire load (3 reminders → 0). Phase 3 closes that gap (test-first) and pins the surrounding hand-edit behaviors as a regression net.

## Starting Point

`tests/test_reminders.py` already covers missing-file → `[]` and unparseable-JSON-top-level → `[]` (`TestDefensiveBehavior`), tz-naive `start_at`/`end_at` coercion (`TestCoerceAwareUtc`), and the `lead_minutes` 4-invariant cluster (`TestCoerceLeadMinutes` — the canonical mirror pattern this plan follows). `tests/test_settings.py` covers `break_interval_min` / `snooze_duration_min` / `max_snoozes` clamps + `voice_enabled` bool coercion. **No test covers per-row containment in `_read`, missing required keys, malformed ISO, wrong-type on raw reminders fields, or three unprotected Settings surfaces** (`idle_threshold_sec` no upper clamp, `voice_phrase.setter` raw, "unknown INI key" silently-ignored). Research confirmed `storage/event_log.py` is append-only — out of R-5 scope.

## Desired End State

A user with a hand-edited `reminders.json` containing one malformed row loses **just that row** (with a `logger.warning` naming the index + exception), not the whole list. Every `Reminder.from_dict` field-level behavior is pinned as a regression net — future refactors that change a coerce-point trip a test. Every Settings hand-edit surface (idle_threshold high values, voice_phrase non-str setter, unknown INI keys, bool coercion across all 3 boolean keys) is pinned. The test-plan's §2 R-5 "Must challenge" cell no longer leans on the empirically-empty "since S-06b / since S-04" audit lens. The S-06b "lesson never generalized into `lessons.md`" loop is closed.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
| --- | --- | --- | --- |
| R-5 surface depth | Three modules audited: reminders.py + settings.py (named) + event_log.py probe (confirmed out of scope) | Research surfaced + integration-load grounding flagged as a real Phase 3 input | Research |
| `_read` row-containment direction | Fix in this change + test post-fix invariant (Q1) | Closes the silent-data-loss surface in a strict improvement direction; ~10 LoC of production change; aligns with the S-06b `_coerce_lead_minutes` self-healing precedent | Plan |
| Settings unprotected surfaces | All-pin (Q2) — no production change to settings.py | Voice_phrase setter raw behavior is documented as intentional; unknown-key silent-ignore is correct forward-compat shape; idle_threshold upper-clamp fix would need a product decision (pick a max) that belongs to its own change | Plan |
| Test organization | Extend existing test_reminders.py + test_settings.py (Q3) | Convention-aligned — every existing boundary-test cluster in this codebase lives in the main test file | Plan |
| Test-plan §2 R-5 backports | Land in this change as Phase 4 docs sync (Q4) | Cheap (~5 min of edits); on-topic; prevents future re-reads from chasing the empty audit lens | Plan |
| `lessons.md` generalization | In scope as part of docs-sync Phase 4 (Q5) | Closes the S-06b retrospective's "lesson never generalized" loop directly; lessons.md is consumed by future planning so the rule actively shapes downstream work | Plan |
| Phase shape | 4 phases — Pin-only / RED / GREEN / Docs sync | Mirrors the modal-stacking-wedge precedent (RED → GREEN → docs) with a prepended pin-only phase for the pure-addition surface that doesn't share the production cycle | Plan |

## Scope

**In scope:**

- `TestMalformedReminderFromDict` (Phase 1) — per-field `Reminder.from_dict` malformed-input pinning
- `TestSettingsIdleThresholdHandEdits` + `TestSettingsVoicePhraseRawSetter` + `TestSettingsBoolCoercionSymmetry` + `TestSettingsUnknownKey` (Phase 1) — Settings hand-edit regression net
- `TestReminderStoreReadResilience` (Phase 2 RED) — pin Fix A invariant via failing tests on the per-row + non-list-top-level containment
- `_read` row-containment fix in `break_reminder/storage/reminders.py` (Phase 3 GREEN) — per-row try/except + `isinstance(raw, list)` guard + `logger.warning` + drop
- `context/foundation/test-plan.md` §2 R-5 backports + §3 row 3 → `complete` + §6 Cookbook row (Phase 4)
- `context/foundation/lessons.md` new entry for the storage-boundary-coerce rule (Phase 4)

**Out of scope:**

- `event_log.py` testing — append-only; no read boundary; out of R-5 surface
- `idle_threshold_sec` upper-clamp fix — pinned not fixed; product decision deferred to a future bugfix change
- `voice_phrase.setter` coercion — pinned not fixed; current raw behavior documented as intentional
- "Raise on unknown INI key" — silent ignore is the correct forward-compat shape
- Integration / app-startup tests — Phase 3 is pure-function unit tests; `main.py` vs `__main__.py` entry-point divergence is Phase 4 of the rollout (if needed)
- New test files — convention-compliant extension of existing files
- `AGENTS.md` edits — the fix is a small bugfix, not a pattern shift; cookbook §6 + lessons.md are the right docs surfaces
- Settings production changes — all 3 unprotected surfaces pinned, not fixed

## Architecture / Approach

The fix is a row-level mirror of the field-level `_coerce_lead_minutes` precedent: where `_coerce_lead_minutes` self-heals a single hand-edited field value, the new `_read` body self-heals a single hand-edited row. The exception tuple `(KeyError, ValueError, TypeError)` matches what `Reminder.from_dict` can raise (missing key, malformed ISO, non-dict row); the top-level `isinstance(raw, list)` guard handles the `{}` / `"foo"` JSON-shape-corruption case. All malformed-input tests are pure-function unit tests using pytest's `caplog` fixture — no Qt event loop, no `pytest-qt` extras needed beyond the existing session-scoped `_qt_app` autouse fixture.

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Pin-only regression net | ~12-15 new tests in `test_reminders.py` + `test_settings.py`; all PASS on landing | Risk: a test asserts a behavior that's actually a bug we should fix. Mitigation: the pin-vs-fix call was the Q1/Q2 decision — answers locked. |
| 2. RED — `_read` containment failing tests | `TestReminderStoreReadResilience` — 4-5 tests; all FAIL RED today | Risk: the test contract over-specifies and locks the Phase 3 fix into a single shape. Mitigation: contract is intent-focused (drop bad rows, log a warning) not implementation-mirror (don't assert function calls). |
| 3. GREEN — apply the `_read` fix | ~10 LoC change to `break_reminder/storage/reminders.py` + 2 import lines + ~2 docstring lines | Risk: the log message shape drifts from Phase 2's caplog assertions. Mitigation: Phase 3's Contract section pins the format string verbatim. |
| 4. Docs sync — close the rollout phase | `test-plan.md` §2/§3/§6 + `lessons.md` new entry | Risk: the §2 R-5 "Must challenge" rewrite drifts from research's finding. Mitigation: research.md "Open Questions" section is the source-of-truth; Phase 4 Contract names the (a)-(d) targets explicitly. |

**Prerequisites:** None — pytest + caplog + `tmp_path` are existing project infrastructure; no new dependencies.

**Estimated effort:** ~1-2 sessions across 4 phases. Phase 1 is the largest (~12-15 new tests) but mechanical; Phase 2/3 are small but require care on the log-shape contract; Phase 4 is ~30 minutes of docs surgery.

## Open Risks & Assumptions

- **Log infrastructure assumption.** The fix uses Python's stdlib `logging` module via `logger = logging.getLogger(__name__)`. This is the first `logging` call in `reminders.py`; the project may or may not have a configured root handler that surfaces WARNINGs at runtime. The unit tests assert via pytest's `caplog` fixture (which works regardless), but the Phase 3 manual smoke depends on the warning being observable somewhere — if no handler is configured, the warning is silently dropped at runtime (still semantically correct: row is dropped, app keeps running) but the user can't diagnose. Worth verifying during Phase 3 manual smoke; if the warning isn't observable, open a small follow-up to add basic logging configuration.
- **S-04 vs S-01 naming.** The test-plan calls the settings-break-interval change "S-04"; the archive review header calls it "S-01"; the roadmap is the tiebreaker. Phase 4 Contract instructs the implementer to cross-reference `context/foundation/roadmap.md` before applying the rename; if the roadmap also says S-04, leave the test-plan alone and document the discrepancy in the archive review instead.

## Success Criteria (Summary)

- A `reminders.json` with one malformed row in a list of three loads two well-formed reminders, drops the bad one, and emits a WARNING log naming the row index + exception class.
- Every pre-Phase-3 storage test still passes (regression sweep across all 36 + 54 + 13 existing tests).
- A future reader of `context/foundation/test-plan.md` §2 R-5 sees an accurate Risk Response Guidance (no empty "since S-06b" framing) and `context/foundation/lessons.md` carries a concrete, file:line-cited rule for the storage-boundary-coerce pattern.
