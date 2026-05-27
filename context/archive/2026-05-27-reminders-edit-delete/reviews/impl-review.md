<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Reminders Edit / Delete (S-07)

- **Plan**: `context/changes/reminders-edit-delete/plan.md`
- **Scope**: All phases (Phase 1 + Phase 2, both `[x]` end-to-end)
- **Date**: 2026-05-27
- **Verdict**: APPROVED (with notes)
- **Findings**: 0 critical · 1 warning · 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Findings

### F1 — Four plan-listed Edit-mode tests absent

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Plan Adherence
- **Location**: `tests/test_reminder_form_dialog.py` (`TestReminderFormDialogEditMode`)
- **Detail**: Plan Phase 1 #8 enumerated 15 specific Edit-mode tests. 15 tests landed but the set is not 1:1: 5 were renamed (semantically equivalent), 4 EXTRA tests were added (justified), and 4 plan-listed tests are absent:
  - `test_edit_mode_name_validation_still_applies`
  - `test_edit_mode_cancel_does_not_modify_store`
  - `test_edit_mode_oserror_on_store_update_blocks_dialog`
  - `test_add_mode_constructor_still_works_with_reminder_none`

  Risk assessment: the cancel and `reminder=None` tests are largely redundant with their Add-mode counterparts (same `super().reject()` path, same default-arg semantics). The OSError-on-update test pins a unique code path (`store.update` vs `store.add`); the dispatch in `accept()` wires both into the same `try/except`, but the Edit branch's specific OSError surface has no direct regression tripwire. The name-validation test would re-pin the strip+empty gate in Edit mode — the gate is shared with Add so coverage is transitive.
- **Fix**: Add the four missing tests. The OSError-on-update one is the highest-value of the four (unique code path); the other three are completeness wins that pin the contract the plan documented.
- **Decision**: FIXED — added all four tests in `TestReminderFormDialogEditMode` (411 tests pass, was 407).

### F2 — Edit-mode skip predicate would TypeError on tz-naive disk value

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality (Reliability)
- **Location**: `break_reminder/ui/reminder_form_dialog.py` — `accept()`, past-time gate skip predicate
- **Detail**: The Edit-mode skip uses `start_at_utc == self._editing.start_at` on tz-aware UTC datetimes. If `reminders.json` were hand-edited (or migrated by future code) to contain a tz-naive `start_at`, the comparison would raise `TypeError` ("can't compare offset-naive and offset-aware datetimes"). All BreakReminder code paths write tz-aware values, so this is a hand-edit / future-migration risk, not a current bug.
- **Fix**: Either (a) document the invariant on the `Reminder` dataclass and rely on the storage layer to reject tz-naive on load, or (b) defensively `_ensure_aware()`-wrap both sides of the comparison in the form. (a) is cheaper and matches the rest of the codebase's "tz-aware everywhere" contract.
- **Decision**: FIXED via Fix A — added `_coerce_aware_utc` helper in `storage/reminders.py`, wired into `Reminder.from_dict()` for `start_at` + `end_at`, documented the invariant on the `Reminder` dataclass docstring, and added `TestCoerceAwareUtc` with 6 tests (helper unit tests + integration tests for hand-edited entries without `+00:00`). 417 tests pass (was 411).

### F3 — DST-spanning Edit can break skip equality on no-op save

- **Severity**: 📋 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality (Reliability)
- **Location**: `break_reminder/ui/reminder_form_dialog.py` — Edit pre-fill at `__init__` ↔ save `accept()`
- **Detail**: Pre-fill: `event_at_utc.astimezone().replace(tzinfo=None)` uses `.astimezone()` (no arg), capturing the local zone at the REMINDER's instant (DST-aware for that moment). Save: `naive_local.replace(tzinfo=local_tz)` where `local_tz = datetime.now().astimezone().tzinfo` — captures the local zone at NOW. If the system tzinfo resolves to a zoneinfo instance, attaching it back to a naive datetime computes the correct DST offset for that datetime's wall clock and the skip equality holds. If it resolves to a fixed-offset `timezone(...)` instance (which can happen on some platforms / Python versions), a DST-spanning edit (e.g., loading a January reminder in July without changing anything) can shift the recomputed `start_at_utc` by one hour, fail the equality, and trip the past-time gate on a no-op save.

  This is a pre-existing S-06 issue in the save path; S-07's Edit pre-fill inherits it via the round-trip. Not a regression.
- **Fix**: Use a stable local-zone lookup at both pre-fill and save (e.g., `from zoneinfo import ZoneInfo` + the system-zone resolution helper) so both sides agree on DST behavior for any datetime, regardless of when "now" is.
- **Decision**: FIXED via cleaner approach — replaced the `datetime.now().astimezone().tzinfo` + `.replace(tzinfo=...)` two-step in `accept()` with a single `naive_local.astimezone(UTC)` call. Per the Python 3.6+ contract, `.astimezone(tz)` on a naive datetime uses the local zone's offset for **that specific wall-clock value** (not for "now"), which is DST-correct on a per-instant basis without needing an extra zoneinfo lookup. 417 tests still pass.

### F4 — Delete OSError test stubs ReminderStore.delete itself

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality (Test quality)
- **Location**: `tests/test_settings_dialog.py` — `test_delete_oserror_on_store_delete_keeps_list_intact`
- **Detail**: The test monkeypatches `ReminderStore.delete` to raise `PermissionError`, which pins the `SettingsDialog`-side error-handling (tooltip surfaces, no reload, no refresh) but does NOT independently exercise the storage layer's atomic-rename-on-failure invariant. The storage layer already has its own atomic-save tests; this is a coverage observation, not a missed dimension.
- **Fix**: Optional — add a parallel test that lets the real `ReminderStore` run but makes the underlying file unwritable (e.g., chmod the parent directory read-only on Unix, or use a `tmp_path` the test process can't write). Cost is test-fixture complexity; benefit is end-to-end coverage of the disk + UI atomic-save contract. Skip unless the next bug bites here.
- **Decision**: FIXED via a deeper stub — added `test_delete_real_storage_write_failure_keeps_disk_byte_identical` that monkeypatches the store's private `_write` instead of the public `delete`. The real public `delete()` still runs (lock, read, filter); failure happens at the write-replace step, the disk bytes are snapshotted before/after, and a fresh `ReminderStore` round-trips the same items — pinning the storage atomic-save invariant at the UI boundary. 418 tests pass.
