<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Single-instance guard (S-10)

- **Plan**: `context/changes/bugfix-single-instance-guard/plan.md`
- **Scope**: Phase 1 + Phase 2 (full plan)
- **Date**: 2026-05-29
- **Verdict**: APPROVED
- **Findings**: 0 critical · 0 warnings · 0 observations
- **Commits reviewed**: `6ac557f` (Phase 1), `93437bd` (Phase 2), `74a907e` (epilogue)

## Verdicts

| Dimension           | Verdict |
|---------------------|---------|
| Plan Adherence      | PASS    |
| Scope Discipline    | PASS    |
| Safety & Quality    | PASS    |
| Architecture        | PASS    |
| Pattern Consistency | PASS    |
| Success Criteria    | PASS    |

## Findings

None. Clean review. See evidence summary below.

## Evidence Summary

### Plan Adherence (PASS)

All four planned changes match the plan exactly.

1. **`break_reminder/storage/paths.py`** — `app_lock_path()` returns `app_data_dir() / "app.lock"` with a one-line Google-style docstring matching the four sibling helpers (`app_data_dir`, `settings_ini_path`, `event_log_path`, `reminders_json_path`). MATCH.

2. **`break_reminder/app.py` (helper)** — `_acquire_single_instance_lock(lock_path: Path) -> QLockFile | None` constructs `QLockFile(str(lock_path))`, calls `tryLock(0)`, returns the lock on True / `None` on False. Docstring documents both the contract (lock acquired or `None` on contention) AND the lifetime expectation (caller must bind the return value for the duration of the lock's intended hold), as required by `lessons.md`'s "non-obvious behavior" carve-out for private helpers. MATCH.

3. **`break_reminder/app.py` (main wiring)** — Lock acquired between `qt_app.setQuitOnLastWindowClosed(False)` and the tray-availability check. Correct ordering: AFTER `setApplicationName` (so `QStandardPaths` resolves to `%APPDATA%\BreakReminder`) and BEFORE `BreakReminderApp` construction (so a contended startup is a fast no-op). Bound to `_instance_lock`; no `# noqa: F841` needed (ruff's default `dummy-variable-rgx` exempts underscore-prefixed names — verified against `pyproject.toml`). MATCH.

4. **`tests/test_app.py`** — `TestSingleInstanceLock` with all four required tests (`test_acquires_against_clean_path`, `test_second_acquire_returns_none_while_first_held`, `test_third_acquire_after_unlock_succeeds`, `test_app_lock_path_under_app_data_dir`). All four pass in ~0.10s. MATCH.

### Scope Discipline (PASS)

All "What We're NOT Doing" boundaries respected — verified absent in the diff:

- No `QLocalSocket` IPC for "activate-existing-instance".
- No `pywin32` / `CreateMutex` named mutex.
- No `--allow-multiple` CLI flag or `BREAKREMINDER_ALLOW_MULTIPLE` env var.
- No `EventType.PROCESS_REJECTED` row in `events.log`.
- `main.py` untouched (Qt-free bootstrap doctrine preserved).
- `pyproject.toml`, PyInstaller spec, NSIS script, `release.yml` all untouched.
- `--self-test` short-circuit in `main.py:_run` untouched (still bypasses the lock as designed).
- `setStaleLockTime` not called — relies on Qt's default 30000ms + PID-liveness check.

Three benign EXTRAs noted, none material:
- A multi-line explanatory comment in `main()` above the `_instance_lock` binding reinforcing the lifetime contract. The plan argued the underscore prefix alone documents intent, but the additional comment is strictly clearer for future readers.
- Defensive `try/finally unlock()` cleanup in tests — prevents handle leaks if an assertion fails mid-test. Strictly safer than the plan required.
- An extra `isLocked()` assertion in `test_third_acquire_after_unlock_succeeds` — pins the observable property the plan implied.

### Safety & Quality (PASS)

No CRITICAL or WARNING findings. Verified:

- No hardcoded secrets; no path traversal (lock path constructed from `QStandardPaths`-resolved `%APPDATA%\BreakReminder`).
- Lock acquisition is a single sub-millisecond `stat` + OS-level file lock (`LockFileEx` on Windows). No blocking I/O on the GUI thread beyond startup.
- `setApplicationName` ordering preserved: lock path resolves correctly under `%APPDATA%\BreakReminder\app.lock`.
- No collision with existing `BreakReminder.ini`, `events.log`, `reminders.json` — distinct filename in the same directory.
- Stale-lock recovery is automatic via Qt's PID-liveness check — verified working in manual test 1.11 (Task Manager kill → relaunch succeeds with no manual cleanup).

### Architecture (PASS)

- Path helper added to `storage/paths.py` alongside its four siblings — same module boundary, no new abstraction layer introduced.
- Lock acquisition lives at the top of `break_reminder.app:main()`, respecting the `AGENTS.md` rule that `main.py` stays Qt-free.
- No new threads introduced. Lock acquired on the main thread; held by `main()`'s local scope until `qt_app.exec()` returns.

### Pattern Consistency (PASS)

- `app_lock_path()` docstring style matches the four sibling path helpers exactly.
- `_acquire_single_instance_lock` docstring is longer than the other private helpers in `app.py` — justified by the lifetime contract documentation and explicitly approved by `lessons.md`'s "non-obvious behavior" carve-out.
- Test class `TestSingleInstanceLock` follows the existing `tests/test_app.py` class style (uses `tmp_path`, relies on the autouse `qapp` fixture from `conftest.py`, mirrors assertion idioms used by `TestBreakReminderApp` and `TestUpdateCheck`).

### Success Criteria (PASS)

Re-verified at HEAD (`74a907e`):

**Phase 1 Automated:**
- `pytest tests/test_app.py -v -k TestSingleInstanceLock` → 4 passed
- `pytest` → 505 passed
- `pyright` → 0 errors, 0 warnings, 0 informations
- `ruff check` → all checks passed
- `ruff format --check` → 32 files already formatted
- `pip-audit` → no known vulnerabilities
- `pip-licenses --fail-on=AGPL` → no AGPL license

**Phase 1 Manual:** user confirmed all 7 items (1.8–1.14), including the bundled `.exe --self-test` while a tray instance is running. Screenshot supplied by the user proves the `QMessageBox.information` contract verbatim (text, info icon, single OK button).

**Phase 2 Automated:** 4 `git grep` bookkeeping checks all return expected counts.

## Notes for Future Slices

- The plan-review findings (F1–F4) were correctly triaged before implementation began. No regression in the implemented work.
- The `f"{APPLICATION_NAME} …"` form in the contention message box is byte-identical at runtime to the plan's verbatim literal `"BreakReminder …"` because `APPLICATION_NAME == "BreakReminder"`. Single-source-of-truth via the constant is a marginal improvement over the literal — not flagged.
- Theoretical PID-reuse window during Qt's 30-second stale-lock period is acknowledged in the plan's "What We're NOT Doing" section and remains an accepted risk (low Windows PID churn on a personal workstation makes this practically unreachable).
