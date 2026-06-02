---
review_type: impl-review
change_id: reminders-recurrence-editor
reviewed_at: 2026-05-28
reviewer: Claude Opus 4.7 (1M context)
verdict: ready-to-ship
findings_count: 0
---

# Implementation Review — `reminders-recurrence-editor`

**Verdict: Plan-faithful, safe, ready to ship.** No findings.

Commits reviewed:

- `3439eb3` — feat(reminders-recurrence-editor): recurrence picker + end-date row (p1)
- `739cd1a` — chore(reminders-recurrence-editor): manual smoke + roadmap bookkeeping (p2)
- `a214189` — chore(reminders-recurrence-editor): close out plan (epilogue)

## Automated success criteria — all green

| Gate | Result |
|---|---|
| `uv run pytest` | **486 passed** in 2.97s |
| `uv run pyright` | **0 errors, 0 warnings** |
| `uv run ruff check` | **All checks passed** |
| `uv run ruff format --check` | **32 files already formatted** |
| `uv run pip-audit` | **No known vulnerabilities** |
| `uv run pip-licenses --fail-on=AGPL` | **No AGPL** |

## Plan drift — none material

All 11 items from `## Implementation Approach` mapped 1:1 onto code:

| Plan step | Where it landed |
|---|---|
| 1. Module-level constants + 3 helpers | `reminder_form_dialog.py:163-348` (`_picker_choice_to_rrule`, `_rrule_to_picker_choice`, `_local_date_to_utc_end_of_day`, `_format_no_future_occurrences_with_lead`) |
| 2. Extend `__init__` with recurrence + end-date rows + signal wiring | `reminder_form_dialog.py:534-688` |
| 3. `_on_recurrence_changed` cascade slot | `reminder_form_dialog.py:726-750` |
| 4. `_on_recurrence_reset_clicked` | `reminder_form_dialog.py:781-810` |
| 5. Recurrence-aware past-time gate in `accept()` | `reminder_form_dialog.py:883-950` (Edit-mode skip widened to `(start_at, rrule_str, end_at)` tuple-equality) |
| 6. `Reminder` construction passes `rrule_str=` + `end_at=` | `reminder_form_dialog.py:957-973` |
| 7. `_compose_row` + `_recurrence_label` | `settings_dialog.py:209-248`, `:331-393` |
| 8. Six new test classes | `tests/test_reminder_form_dialog.py:1670-2424` (TestRecurrencePicker, TestRecurrenceSave, TestRecurrenceEditMode, TestRecurrenceCustomLocked, TestRecurrencePastTimeGate, TestRecurrenceEndDate) |
| 9. `TestComposeRowRecurrence` | `tests/test_settings_dialog.py:1824` |
| 10. AGENTS.md FR-014 bullet removed | Verified gone |
| 11. Phase 2 bookkeeping | `change.md:status=implemented`, `roadmap.md:S-08=done` |

**Positive deviation:** implementer added a 7th test class `TestRecurrenceTranslationHelpers` (line 1802) for direct unit-tests of the three pure helpers. Purely additive — `_picker_choice_to_rrule`, `_rrule_to_picker_choice`, `_local_date_to_utc_end_of_day`, and `_format_no_future_occurrences_with_lead` are each pinned without spinning the dialog.

## Pattern compliance — clean

- **Validation idiom respected.** Recurring-branch failure surfaces via `QToolTip.showText` anchored to `_datetime_field` (`accept` lines 949-950) — same convention as the existing one-shot gate, the voice-phrase gate in `SettingsDialog`, and the OS-error save tooltip. No `QMessageBox` for validation; the only `QMessageBox.question` (`_on_recurrence_reset_clicked` line 794) is a destructive-action confirmation — same precedent as the Delete button.
- **Edit-mode skip widening matches the architectural rationale.** Three-field tuple equality (`start_at == self._editing.start_at AND rrule_str_proposed == self._editing.rrule_str AND end_at_proposed == self._editing.end_at`) at `accept` lines 912-917. Renaming or re-leading an expired *recurring* reminder still saves; rule edits or end-date edits re-engage the gate. F1 fix is in place.
- **FR-015 hand-edit invariant honored.** Custom-locked branch reads `self._original_custom_rrule` directly (line 890), bypassing `_picker_choice_to_rrule` (which would `KeyError` on `(custom)`). A no-op save round-trips the user's hand-edited string byte-for-byte.
- **Threading rules respected.** Every new widget mutation lives in `__init__` or in a Qt slot. No pynput-thread / voice-thread interaction.
- **DST correctness.** `_local_date_to_utc_end_of_day` uses `datetime.combine(picked, time(23, 59, 59)).astimezone(UTC)` (line 328-329) — the same per-instant DST-correct idiom the form's existing datetime save path uses.
- **Storage / scheduler zero-touch as planned.** No edits to `storage/reminders.py` or `scheduler.py`.
- **AGENTS.md "What this scaffold does not yet implement" updated.** FR-014 bullet removed; remaining list is US-01 / icons / snooze countdown.

## Safety — no concerns

- **Defense-in-depth on `end_at`.** `accept` lines 893-898 force `end_at_proposed = None` whenever `rrule_str_proposed is None`, even if the cascade has somehow left the checkbox checked. A buggy cascade can't leak an `end_at` into a one-shot reminder.
- **Recurring-branch gate runs *before* the real `Reminder` construction.** Tentative `Reminder` at lines 936-942 is throwaway; the gate rejects unparseable / exhausted rules (e.g. an `end_at` already in the past) and the user sees `"Recurring reminder has no future firings"` instead of a silently-invisible reminder.
- **Atomicity preserved.** Save still goes through `store.add()` / `store.update()` (lines 977-993); `OSError` still surfaces as a tooltip on the OK button without partial-write side-effects.
- **`emit-before-super-accept` ordering preserved** (lines 1002-1008). No regression of the Add/Edit signal contract.
- **Custom-locked Reset confirmation defaults to `No`** (line 800) — matches the destructive-action wording convention.

## Quality — solid

- Extensive "why" docstrings on every new constant + helper. No narrative comments.
- Module-level constants for every user-visible string (suffix labels, tooltips, confirm copy) — no magic strings, easy to translate later.
- The `cast(date, ...)` / `cast(datetime, ...)` calls (lines 868, 900) match the existing stub-gap precedent — explicitly preferred over `assert isinstance` per the docstring rationale ("would be stripped under `python -O`").
- 486 tests, every new class pins a contract (cascade behavior, byte-for-byte custom preservation, DST round-trip, recurrence-aware gate matrix) rather than just exercising paths.

## F-fix traceability (from `/10x-plan-review`)

Six F-fixes from the plan-review pass all show up in code:

- **F1** — cascade preservation of `end_at` on `(custom)` choice → `_on_recurrence_changed` lines 686-687, `TestRecurrenceCustomLocked` end_at-preservation case.
- **F2** — Edit-mode skip widening to tuple-equality → `accept` lines 912-917, `TestRecurrencePastTimeGate` matrix.
- **F3** — DST-correct local→UTC via `naive.astimezone(UTC)` (not capture-now-offset) → lines 869-878 with explanatory comment.
- **F5** — monthly-tooltip dual-wiring (picker + datetime field both refresh) → line 678 + `_update_monthly_tooltip` cascade.
- **F6** — direct unit tests of pure helpers → `TestRecurrenceTranslationHelpers`.
- **F7** — custom-locked save preserves `end_at` byte-for-byte → `TestRecurrenceCustomLocked` round-trip case.

## Summary

The implementation matches the reviewed-and-fixed plan precisely. Phase 2 bookkeeping is complete. No follow-up work needed.

> **NOTE 2026-06-02**: The "DST correctness" claim above was scoped only to
> `_local_date_to_utc_end_of_day` (end-date conversion). The recurring-firing
> DST drift (R-1b) was missed and shipped with S-08; fixed in
> `context/archive/2026-06-02-bugfix-reminder-dst-drift/`.
