# Retrospective Implementation Review — S-06 `reminders-add-form` (Phase 1)

> **Note on prefix.** This is a **retrospective** review run after the slice was already archived. The standard `/10x-impl-review` skill refuses targets under `context/archive/`; that refusal was explicitly overridden so the documentation gap (no review at archive time) could be closed without unarchiving the folder. The `retrospective-` prefix on the filename flags the unusual flow.

## Scope

- **Target**: S-06 `reminders-add-form` (change-id `reminders-add-form`)
- **Slice status**: `archived` (folder lives at `context/archive/2026-05-27-reminders-add-form/`)
- **Phase under review**: Phase 1 only. Phase 2 (`beba743`) and archive epilogue (`4668903`, `4c9c722`) were pure bookkeeping with no production-code review surface.
- **Substantive commit**: `33a665f` — `feat(reminders-add-form): wire Add Reminder sub-dialog (p1)`
- **Author**: Chlebek, Kamil — Wed May 27 10:26:24 2026 +0200

### Carry-over caveat

Commit `797328d` (the S-06b Phase 1 impl-review triage) later modified two of the S-06 production files:

- `break_reminder/storage/reminders.py` — `_coerce_lead_minutes` + `_LEAD_*` constants (F4 of S-06b).
- `break_reminder/ui/reminder_form_dialog.py` — `_format_past_time_with_lead` + `{lead} {unit}` plurality (F2 of S-06b).

Anything in those areas would be S-06b's surface, not S-06's, and is **out of scope** for this review. Sub-agents were briefed to ignore lead-time-related code paths. No finding below overlaps with `797328d`'s fixes.

## Success criteria at HEAD

Re-verified after `797328d` + `f806cad` + `d4faa46`:

- `uv run pytest` → **364 passed** in 3.76 s
- `uv run ruff check` → All checks passed
- `uv run ruff format --check` → 32 files already formatted
- `uv run pyright` → 0 errors, 0 warnings, 0 informations

The slice ships clean at HEAD. Findings below are documentation / robustness polish, not regression flags.

## Plan-vs-impl coverage summary

12 planned change sites in Phase 1's `### Changes Required:` — all 8 production-code sites match the plan's contracts cleanly. Drift is confined to the two new test files (#9 and #10), and the drift is **net-positive in raw coverage** (5 extra test classes / 7 extra test methods beyond the plan) but **loses 4 specific contracts** the plan named. All 12 "What We're NOT Doing" guardrails are honored. No extra production files in the commit.

| Site | File | Verdict |
|---|---|---|
| #1 | `break_reminder/scheduler.py` — clock injection | MATCH |
| #2 | `break_reminder/ui/reminder_form_dialog.py` (NEW) | MATCH |
| #3 | `settings_dialog.py` — `__init__` accepts `reminder_scheduler` | MATCH |
| #4 | `settings_dialog.py` — `_build_reminders_tab` stores `self._reminders_tab` | MATCH |
| #5 | `settings_dialog.py` — `_build_reminders_button_row` enables Add | MATCH |
| #6 | `settings_dialog.py` — `_on_reminders_add_clicked` slot | MATCH |
| #7 | `settings_dialog.py` — `_refresh_reminders_tab` slot | MATCH |
| #8 | `app.py` — pass `reminder_scheduler` into `SettingsDialog` | MATCH |
| #9 | `tests/test_reminder_scheduler.py` (NEW) | DRIFT (F1) |
| #10 | `tests/test_reminder_form_dialog.py` (NEW) | DRIFT (F2, F3, F4) |
| #11 | `tests/test_settings_dialog.py` — fixture + sweep + `TestRemindersAddButton` | MATCH |
| #12 | `AGENTS.md` — FR-012 bullet rewrite | MATCH |

## Findings

### F1 — `_timer.interval() == 24h_ms` cap assertion missing — OBSERVATION

- **Category**: Plan adherence / test coverage gap
- **File**: `tests/test_reminder_scheduler.py` (commit `33a665f`)
- **Plan reference**: Phase 1 #9 — *"TestReloadHandlesFarFuture: reminder 30 days out; `reload()` arms the timer with `min(ms, 24h_ms)`. Asserts `_timer.interval() == 24*60*60*1000`."*

**Description.** The plan named four test classes; the impl collapsed them into two (`TestClockInjection` and `TestReloadReentrancy`). Most planned contracts survived under renamed methods, but the 24-hour-interval-cap assertion was never written. The closest test, `test_on_timer_early_wakeup_rearms_via_clock`, uses a 7-day-out reminder but asserts on the rearm branch rather than on `scheduler._timer.interval() == 86_400_000`. If a future change drops or breaks the daily-cap branch in `scheduler.py`, no test fails.

**Recommended fix.** Add a single test that asserts the daily cap directly:

```python
def test_reload_caps_timer_at_24h_for_far_future_reminder(
    self, scheduler: ReminderScheduler, store: ReminderStore, clock: Clock
) -> None:
    """Reminders > 24h out arm the QTimer at the 24h cap, not at the full delta."""
    store.add(Reminder(name="far", start_at=clock() + timedelta(days=30)))
    scheduler.reload()
    assert scheduler._timer.interval() == 24 * 60 * 60 * 1000
```

### F2 — `TestReminderFormDialogAtomicSaveTripwire` class entirely missing — OBSERVATION

- **Category**: Plan adherence / test coverage gap
- **File**: `tests/test_reminder_form_dialog.py` (commit `33a665f`)
- **Plan reference**: Phase 1 #10 — *"TestReminderFormDialogAtomicSaveTripwire: `test_validation_failure_does_not_write_partial_state` — pre-seed `reminder_store` with one entry, attempt save with empty name, assert `reminder_store.list_all()` still has exactly the one pre-seeded entry (byte-identical). Pin both the name-empty branch and the past-time branch (two test methods)."*

**Description.** The class is absent. The existing validation tests (`test_empty_name_blocks_save`, `test_past_time_blocks_save`) assert `store.list_all() == []` against an **empty** pre-state. They prove "validation failure doesn't persist a new reminder" but never prove "validation failure doesn't corrupt prior persisted state". The "Atomic Save Tripwire" docstring on the OSError test mentions the concept, but only the OSError path exercises a non-empty post-state. A bug that, e.g., overwrote `reminders.json` with empty content during a validation-failure return path would not be caught.

**Recommended fix.** Add the missing class with two pre-seeded tripwire tests, parallel to S-04's `TestNotificationsTabValidation::test_voice_on_blank_phrase_blocks_save`. ~25 lines.

### F3 — `test_successful_save_strips_name_whitespace` missing — OBSERVATION

- **Category**: Plan adherence / test coverage gap
- **File**: `tests/test_reminder_form_dialog.py` (commit `33a665f`)
- **Plan reference**: Phase 1 #10 (TestReminderFormDialogSave) — *"set name `"  Spaced name  "`, accept, assert stored `name == "Spaced name"`."*

**Description.** Production calls `.strip()` (`reminder_form_dialog.py:373`), and `test_whitespace_only_name_blocks_save` covers the orthogonal "all-whitespace blocks save" case, but no test sets surrounding whitespace on an otherwise valid name and asserts the stored name was trimmed. A future regression that dropped the `.strip()` would not fail any test.

**Recommended fix.** One 6-line test added to `TestReminderFormDialogSave`.

### F4 — `test_name_validation_wins_over_datetime_validation` missing — OBSERVATION

- **Category**: Plan adherence / test coverage gap
- **File**: `tests/test_reminder_form_dialog.py` (commit `33a665f`)
- **Plan reference**: Phase 1 #10 (TestReminderFormDialogValidation) — *"set BOTH name empty AND datetime in the past; assert only the name tooltip fires (first-failing-field-wins; mirrors voice-phrase pattern)."*

**Description.** The "first-failing-field-wins" ordering is a load-bearing UX rule the plan called out explicitly (mirrors the voice-phrase gate). No test sets both fields invalid simultaneously and asserts the order. A future refactor that switched the validation order (datetime-first) would not fail any test.

**Recommended fix.** One ~10-line test using a `QToolTip.showText` recorder to capture which message was shown (or by checking that only the name-field-anchored variant fired).

### F5 — Production `assert` becomes dead under `python -O` — OBSERVATION

- **Category**: Reliability / Pattern compliance
- **File**: `break_reminder/ui/reminder_form_dialog.py:382-385` (HEAD; same logic at commit `33a665f`)

**Description.** `accept()` uses `assert isinstance(naive_local_raw, datetime), "..."` to narrow the PySide6 stub-typed `object` returned by `QDateTimeEdit.dateTime().toPython()`. Under `python -O` the assert is stripped, leaving an unchecked value flowing into `.replace(tzinfo=local_tz).astimezone(UTC)`. Production isn't shipped with `-O` today, and PySide6 in fact always returns a `datetime`, so the assertion is decorative either way. The same pattern is used by `scheduler.py` (`assert self._next is not None` in `_fire`) so it's at least consistent — but consistency on a weak pattern isn't a defense.

**Recommended fix.** Either drop the assert in favor of a `cast(datetime, naive_local_raw)` (silent narrowing, accepts the runtime contract) or escalate to a hard runtime guard:

```python
if not isinstance(naive_local_raw, datetime):
    raise TypeError(
        f"QDateTimeEdit.dateTime().toPython() returned non-datetime: "
        f"{type(naive_local_raw)!r}"
    )
```

The hard guard preserves the safety net under `-O` and surfaces the breakage loudly if a future PySide6 ever changes the contract.

### F6 — Sub-dialog soft leak: parented `ReminderFormDialog` accumulates across repeated clicks — OBSERVATION

- **Category**: Reliability
- **File**: `break_reminder/ui/settings_dialog.py:793-813` (HEAD; same lines in `33a665f` modulo docstring drift)

**Description.** `_on_reminders_add_clicked` constructs `ReminderFormDialog(..., parent=self)` and lets the local `sub_dialog` fall out of scope when `exec()` returns. Because the dialog has a Qt parent, Python's GC won't reclaim it — Qt keeps it alive (hidden) until the parent `SettingsDialog` is destroyed. A user who opens Settings once and clicks Add → Cancel ten times leaves ten ghost `ReminderFormDialog` widgets (plus children: `QLineEdit`, `QDateTimeEdit`, `QSpinBox`, `QDialogButtonBox`) parented to the SettingsDialog. Each one also holds a stale `reminder_added → _refresh_reminders_tab` connection.

In practice this is bounded by the SettingsDialog lifetime (which is short — `_on_open_settings` constructs a fresh SettingsDialog each open and the user typically opens-tweaks-closes), so no heap growth across sessions. But it's a deviation from the typical short-lived-modal pattern and an unnecessary widget pileup.

**Recommended fix.** One line before `exec()`:

```python
sub_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
```

Alternative: drop the parent (`parent=None` or `parent=self.parent()`) and let local-variable lifetime + modal blocking handle cleanup, matching `_on_open_settings`'s own pattern of constructing a fresh dialog and not stashing it.

### F7 — Defensive `is None` guard in `_refresh_reminders_tab` silently swallows the signal — OBSERVATION

- **Category**: Pattern compliance
- **File**: `break_reminder/ui/settings_dialog.py:846-850` (HEAD; same logic in `33a665f`)

**Description.** `self._reminders_tab` is typed `QWidget | None` (initialized `None` at `settings_dialog.py:473`, set to a real widget by `_build_reminders_tab()` which the constructor calls unconditionally at `:499`). The guard exists for pyright type-narrowing, which is reasonable — but the impl chose `if is None: return` (silent no-op) rather than `assert self._reminders_tab is not None`. If the field is ever genuinely `None` when the signal fires, the rebuild is silently dropped and the user sees a stale tab with no indication anything went wrong.

The sibling pattern in `scheduler.py::_fire` (`assert self._next is not None, "_fire is only reachable via _on_timer which guards on self._next"`) is the established convention for narrowing-via-assert with a documenting message — losing on a "shouldn't happen" state should be loud.

**Recommended fix.** Convert to an asserted narrow:

```python
assert self._reminders_tab is not None, (
    "_refresh_reminders_tab called before _build_reminders_tab; "
    "the constructor always builds the tab so this should be unreachable"
)
```

Removes 3 lines, keeps pyright happy, makes future regressions loud.

## Triage

All 7 findings triaged on 2026-05-27. Outcome: 7 / 7 **Fixed at HEAD** in a single combined commit (no skips, no lessons-only).

| F | Title | Disposition | Notes |
|---|---|---|---|
| F1 | 24h interval cap assertion | **Fixed** | Added `test_reload_caps_timer_at_24h_for_far_future_reminder` to `TestClockInjection` in `tests/test_reminder_scheduler.py`. |
| F2 | Atomic-save tripwire class | **Fixed** | Added `TestReminderFormDialogAtomicSaveTripwire` with `test_empty_name_failure_preserves_prior_store_state` + `test_past_time_failure_preserves_prior_store_state`. |
| F3 | Strip-name-whitespace test | **Fixed** | Added `test_successful_save_strips_name_whitespace` to `TestReminderFormDialogSave`. |
| F4 | Name-wins-over-datetime test | **Fixed** | Added `test_name_validation_wins_over_datetime_validation` to `TestReminderFormDialogValidation`. |
| F5 | Production `assert` under `-O` | **Fixed (alt)** | Replaced `assert isinstance` with `typing.cast(datetime, ...)` for silent static narrowing — the runtime contract is documented by PySide6, so the hard guard wasn't worth the line count. |
| F6 | Sub-dialog soft leak | **Fixed** | Added `sub_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)` in `_on_reminders_add_clicked`. Both `_StubFormDialog` test stubs in `tests/test_settings_dialog.py` gained a no-op `setAttribute` to absorb the new call. |
| F7 | Defensive `is None` swallow | **Fixed** | Converted `if is None: return` to `assert ... is not None, "..."` in `_refresh_reminders_tab`, matching the `scheduler.py::_fire` narrowing pattern. |

### Verification after fixes

- `uv run pytest` → **369 passed** (was 364 at the start of the review; +5 tests for F1-F4).
- `uv run ruff check` → All checks passed.
- `uv run ruff format --check` → 32 files already formatted.
- `uv run pyright` → 0 errors, 0 warnings, 0 informations.

### Commits landing on HEAD

- `76e316e` — `refactor(reminders-add-form-retro): apply retrospective-impl-review fixes (F1-F7)` — single combined commit per user preference (`commit_strategy: single`). Touches both production code (`break_reminder/ui/reminder_form_dialog.py`, `break_reminder/ui/settings_dialog.py`) and tests (`tests/test_reminder_scheduler.py`, `tests/test_reminder_form_dialog.py`, `tests/test_settings_dialog.py`). The archived plan/change.md are NOT touched (terminal `status: archived`).
- A follow-up `chore(archive): add retrospective impl-review for reminders-add-form` commit drops this report into the archived `reviews/` subfolder (the commit you're reading the report from — self-referential SHA omitted by design).

## Negative confirmations

Per Agent 2's pass:

- Threading violations introduced by S-06: **0**
- Injection risks introduced by S-06: **0**
- Data-loss paths introduced by S-06: **0** — atomic-save tripwire honored in production (validate → add → reload → emit → super().accept(); on OSError nothing past `store.add` runs).
- Pattern non-compliance introduced by S-06: **0 at HEAD** — `QToolTip.showText` matches `_on_voice_phrase_edited`; `Reminder(...)` uses keyword args; `tests/test_reminder_form_dialog.py` mirrors `test_break_dialog.py`'s structure; Google-style docstrings on every introduced public surface (per `context/foundation/lessons.md`); `_REMINDERS_INDEX` constant rejected in favor of dynamic `indexOf`; Add button drops its wrapper (option a) and the test pins it; `_refresh_reminders_tab` captures `idx` and `old_tab` before mutation as the plan required.
- Guardrails honored: **12 / 12** (no Edit/Delete handlers shipped, no recurrence editor, no `end_at` field, no id surfaced, no list editing, no `ReminderStore.changed` signal, no `QFileSystemWatcher`, no history view, no NSIS/PyInstaller changes, no autostart/pause/voice/tray changes, no new `Settings` keys, no localization).

## Verdict

**APPROVED with 7 OBSERVATION-level recommendations** — 0 CRITICAL, 0 WARNING. The slice ships clean: production code matches the plan's contracts and ships safely. The four DRIFT items (F1–F4) are test-only gaps that don't reflect a behavior bug today — but they're regression tripwires the plan named explicitly. The three quality items (F5–F7) are polish: a hardier runtime guard, a one-line widget-cleanup attribute, and a louder failure mode for a "shouldn't happen" state.

The retrospective exists primarily to close the documentation gap that triggered the `/10x-archive` warning. Closing it confirms the slice was substantively well-implemented; the recommended fixes apply to current HEAD (not to the archived plan) and land as separate `refactor(reminders-add-form-retro)` commits.

## Deferred recommendations

**None.** Every finding was triaged `Fix` (with F5 taking the `typing.cast` variant over the `if/raise TypeError` variant). The standard `follow-ups/review-fixes.md` pattern would normally live under the change folder, but the change folder is archived and there's nothing to defer anyway — all fixes land on HEAD as part of the same combined commit.
