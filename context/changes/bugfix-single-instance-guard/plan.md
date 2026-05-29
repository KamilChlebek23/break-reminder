# Single-instance guard (S-10) Implementation Plan

## Overview

Launching `BreakReminder.exe` (or `python -m break_reminder`) while another copy is already running produces N independent tray icons, each with its own pynput listeners, schedulers, event-log writer, and reminder-store writer — a correctness bug that causes racing break dialogs and concurrent writes to `events.log` / `reminders.json`. This plan adds a single `QLockFile`-based guard at the top of `break_reminder.app:main()`. On contention the second instance shows `QMessageBox.information("BreakReminder is already running. Look for the clock icon in the system tray.")` and returns 0; on first launch it acquires the lock and holds it for the lifetime of `qt_app.exec()` via `main()`'s local scope. Crashed prior instances are recovered automatically by `QLockFile`'s built-in PID-liveness check (no manual lockfile cleanup ever required).

## Current State Analysis

- **The bug surface.** [break_reminder/app.py](break_reminder/app.py) `main()` (lines 477-499) constructs `QApplication`, calls `setApplicationName`, runs the tray-availability check, and then unconditionally constructs `BreakReminderApp(qt_app)` + `app.start()`. No single-instance check anywhere on the path.
- **What `app.start()` does multiplied by N.** [break_reminder/app.py:118-125](break_reminder/app.py) `start()` calls `self._activity.start()` (spawns two pynput listener threads — one keyboard, one mouse), `self._break_scheduler.start()` (arms a 1-second `QTimer`), `self._reminder_scheduler.start()` (arms recurrence timers per reminder), and `self._tray.show()`. Three launches → six pynput threads, three break-dialog races, three sets of QTimers ticking out of phase, three tray icons.
- **The data-corruption surface this opens.** [break_reminder/storage/event_log.py](break_reminder/storage/event_log.py) appends FR-015 events to a CSV file with no cross-process lock. [break_reminder/storage/reminders.py](break_reminder/storage/reminders.py) writes `reminders.json` via atomic-rename — single-writer safe, multi-writer race-loses-data. With N concurrent instances, BREAK-TAKEN rows can interleave (or be lost on rotation) and a CRUD edit from one instance silently overwrites a CRUD edit from another.
- **Real-world trigger paths.** Two: (1) FR-003 autostart-on-Windows-login + the user double-clicks the desktop shortcut after Windows already started the app — the most common path because the user can't see the (small) tray icon and assumes the app isn't running; (2) developer running `uv run python -m break_reminder` while the bundled `.exe` is in the tray.
- **No prior art for single-instance handling.** Repo-wide grep for `QLockFile` / `QSharedMemory` / `QLocalSocket` / `mutex` / `CreateMutex`: zero hits in production code. Only `context/foundation/infrastructure.md` mentions "already running" (in an unrelated context).
- **Bootstrap-panic constraint.** [main.py](main.py) is deliberately Qt-free (the panic guard catches failures *of* Qt). The single-instance check needs `QStandardPaths` + a `QApplication` for the message box, so it must live inside `break_reminder.app:main()`, not `main.py`. The `--self-test` smoke path in `main.py:_run` returns before `app.main()` is called, so it naturally bypasses the lock — correct: CI must be able to run the smoke test against the same `.exe` the installer ships, and the lock would falsely fail when CI runs the test concurrently with itself.
- **Storage-paths convention.** [break_reminder/storage/paths.py](break_reminder/storage/paths.py) holds one constant (`APPLICATION_NAME`) and four path helpers (`app_data_dir`, `settings_ini_path`, `event_log_path`, `reminders_json_path`). The new `app_lock_path()` mirrors the four existing helpers exactly — one-line wrapper over `app_data_dir() / "app.lock"`.
- **Test infra.** [tests/conftest.py](tests/conftest.py) provides a session-scoped `qapp` fixture (autouse). [tests/test_app.py](tests/test_app.py) uses `tmp_path` to keep storage components out of `%APPDATA%`. The new helper `_acquire_single_instance_lock(path)` is testable in isolation by passing a `tmp_path / "app.lock"` and calling it twice in the same test — `QLockFile` uses an OS-level file lock that the second instance sees as held even within the same Python process, so no subprocess machinery is needed.
- **`QLockFile` semantics that matter.** Default `setStaleLockTime` is 30000ms. `tryLock(0)` is non-blocking. Crucially, `tryLock` first checks whether the PID written into the lockfile is still a live process — if not, the lock is treated as stale regardless of the timestamp and silently removed. This means a hard-killed prior instance (Task Manager → End Task) is recovered automatically the next time the user launches the app, with no manual cleanup. We rely on this behavior and explicitly do NOT touch the default stale time.
- **Lessons.md prior.** [context/foundation/lessons.md](context/foundation/lessons.md) requires Google-style docstrings on every public Python function, and on private helpers that encode non-obvious behavior. `_acquire_single_instance_lock` has a leading underscore, but it encodes the lifetime contract on the returned `QLockFile` (drop the reference and the lock GCs immediately, silently breaking the entire fix) — so the carve-out applies and a docstring IS required, naming the contract and the lifetime expectation. `app_lock_path()` in `storage/paths.py` is plainly public and gets a one-line docstring matching the style of the existing four path helpers.

## Desired End State

When the user launches BreakReminder while another instance is already running (most often: clicks the desktop shortcut after Windows autostart already brought up the tray icon), the second process shows a single modal `QMessageBox.information` titled "BreakReminder" with the body "BreakReminder is already running. Look for the clock icon in the system tray." The user clicks OK and the second process exits cleanly with code 0. The first instance is unaffected — its tray icon, schedulers, and listeners continue running. When the user launches after a hard-killed prior instance (Task Manager → End Task on the running tray icon), the new launch detects the stale lockfile via `QLockFile`'s PID-liveness check, removes it transparently, and proceeds to a normal startup with no manual intervention. The lockfile lives at `%APPDATA%\BreakReminder\app.lock`; on uninstall the existing NSIS script's "leave `%APPDATA%` in place" behavior preserves it (harmless on next install — automatically reclaimed on first launch).

### Key Discoveries:

- The lock acquisition must come AFTER `qt_app.setApplicationName(APPLICATION_NAME)` (so `QStandardPaths` resolves to `%APPDATA%\BreakReminder` rather than the executable name) but BEFORE `BreakReminderApp(qt_app)` (so the second instance does not pay any of the heavy initialization cost — pynput listener startup, tray-icon QPainter rendering, scheduler arming).
- Holding the `QLockFile` reference as a local variable in `main()` is sufficient — Python's lexical scoping keeps the object alive until `main()` returns (which only happens after `qt_app.exec()` returns, which only happens at process exit). `QLockFile`'s destructor unlocks; no explicit `unlock()` call is needed on the happy path.
- `QLockFile.tryLock(0)` returns `False` for ANY failure mode (lock already held, lockfile unreadable, parent dir unwritable). The user-facing message is the same regardless — "BreakReminder is already running. Look for the clock icon in the system tray." — because a `%APPDATA%` access failure would break the rest of the app anyway (Settings, EventLog, ReminderStore all write there). This was an explicit decision in planning (Q3: "single message" recommended option).
- Per the planning Q&A: no `--allow-multiple` CLI flag and no `BREAKREMINDER_ALLOW_MULTIPLE` env var. A developer who needs to run a second copy renames `%APPDATA%\BreakReminder\app.lock` (or runs against a fresh `%APPDATA%` via `set APPDATA=...`).
- `--self-test` does NOT acquire the lock. Verified by tracing `main.py:_run`: when `--self-test` is in argv, the function returns before calling `from break_reminder.app import main as app_main`, so the entire `app.main()` body — including the lock acquisition — is skipped. This matches the smoke-test contract (CI runs the smoke test against the same `.exe` the installer ships; the smoke test must not contend with a running tray instance during a pre-release rehearsal).

## What We're NOT Doing

- **No `QLocalSocket` "activate-existing-instance" wiring.** When the user double-clicks the shortcut a second time, we just tell them the app is already running — we do NOT bring the existing tray menu / settings dialog to the front. Per the planning UX decision: more polished, but adds a real IPC surface (server socket, message protocol, listener thread) that is scope-creep under `low-complexity`. Re-prioritize if `main_goal` flips to `quality`.
- **No Windows-specific named-mutex via `pywin32`.** `QLockFile` is cross-platform Qt code already in deps; using it for the lockfile is structurally equivalent and works in dev runs (`uv run python -m break_reminder`) and the PyInstaller bundle identically.
- **No CLI flag or environment variable to bypass the lock.** The smallest possible surface is the right one for a personal-use tray app — locked in via planning Q4.
- **No event-log entry for "rejected second instance".** FR-015 is about break-activity outcomes (TAKEN / SNOOZED / MISSED + custom-reminder firings), not process lifecycle. Adding a new `EventType.PROCESS_REJECTED` row to `events.log` would muddy the Primary Success Criterion ratio readout.
- **No retroactive locking for the v0.1.x..v0.6.x era.** This is a forward-only fix. Users on older versions retain the multi-instance bug until they update; this is acceptable because the data-corruption window has been narrow in practice (no user reports of `events.log` or `reminders.json` corruption to date).
- **No bootstrap-panic touch in `main.py`.** `main.py` stays Qt-free per its existing doctrine. The lock check happens inside `break_reminder.app:main()`. A hypothetical "Qt itself failed to load" failure mode therefore does NOT acquire the lock — but it also does NOT spawn a duplicate tray icon (because the duplicate startup path requires Qt to work). The bootstrap-panic and single-instance concerns are fully orthogonal.
- **No PyInstaller / NSIS / `release.yml` changes.** No new files to bundle, no new dependencies, no new install-time steps. The lockfile is created on first launch under the existing `%APPDATA%\BreakReminder\` directory the storage layer already manages.
- **No `--self-test` change.** The smoke-test path naturally bypasses the lock (verified by the existing `main.py:_run` short-circuit) and must continue to do so for CI to work.
- **No clamping of stale-lock time.** We rely on Qt's default `staleLockTime = 30000ms` plus the PID-liveness check. Lower or higher values offer no observable benefit for this app.
- **No work-around for the theoretical PID-reuse window.** If BreakReminder crashes and Windows reuses its PID for an unrelated long-running process within Qt's 30-second stale-lock window, `QLockFile.tryLock` could see "PID alive" and refuse to acquire — the user would observe up to a 30-second startup hang before the staleLockTime fallback kicks in. Practically unreachable on Windows (PID reuse is slow and the process table churn for a personal workstation is low), but worth a single-bullet acknowledgement so a future contributor encountering "30-second startup hang after kill -9" can find the explanation here. Mitigation if it ever lands: rerun the launcher after 30 seconds, or rename `%APPDATA%\BreakReminder\app.lock` manually.

## Implementation Approach

Single-phase code change touching three production files and one test file. Implementer's natural order:

1. **Add `app_lock_path()` to `break_reminder/storage/paths.py`** — one-liner mirroring the four existing path helpers. Keeps the lockfile location alongside the other per-user-data paths so the maintenance surface stays in one module.
2. **Add module-private `_acquire_single_instance_lock(path: Path) -> QLockFile | None` to `break_reminder/app.py`** — constructs a `QLockFile`, calls `tryLock(0)`, returns the locked `QLockFile` on success or `None` on contention. The function is parameterized on `path` (rather than calling `app_lock_path()` internally) so tests can drive it against `tmp_path` without monkeypatching `storage.paths`.
3. **Wire it into `main()`** — between `qt_app.setQuitOnLastWindowClosed(False)` and the existing `if not QSystemTrayIcon.isSystemTrayAvailable()` check. On `None` return, show `QMessageBox.information(None, APPLICATION_NAME, "BreakReminder is already running. Look for the clock icon in the system tray.")` and return 0. On success, bind the returned `QLockFile` to a local variable `_instance_lock` (the underscore prefix flags it as "held for side effects") and continue with normal startup; the local keeps the lock object alive for the lifetime of the process.
4. **Tests, one new class.** `TestSingleInstanceLock` in `tests/test_app.py` covering: (a) first call against a clean `tmp_path` returns a non-None `QLockFile` whose `isLocked()` is True; (b) second call against the same path while the first lock is held returns `None`; (c) after the first lock is unlocked / dropped, a third call against the same path acquires successfully (proves the lock isn't permanently sticky); (d) a smoke test that `app_lock_path()` returns a path under `app_data_dir()`.

## Critical Implementation Details

- **Ordering inside `main()`.** The lock acquisition must run AFTER `qt_app.setApplicationName(APPLICATION_NAME)` (so `QStandardPaths.writableLocation(AppDataLocation)` resolves to `%APPDATA%\BreakReminder` rather than the executable's name — the same constraint that drives every other call in `app.main()`) but BEFORE `QSystemTrayIcon.isSystemTrayAvailable()` and `BreakReminderApp(qt_app)` (so a contended startup is a fast no-op rather than spinning up listeners and rendering a tray icon we'll throw away). The right insertion point is between `qt_app.setQuitOnLastWindowClosed(False)` and the tray-availability `if`.

- **Lock lifetime.** The `QLockFile` returned by `_acquire_single_instance_lock` MUST be bound to a name in `main()`'s local scope (e.g., `_instance_lock = _acquire_single_instance_lock(...)`) and that name MUST persist until `qt_app.exec()` returns. Failing to bind — e.g., calling `_acquire_single_instance_lock(...)` without storing the return value — would let the `QLockFile` go out of scope immediately, its destructor would unlock, and the very next launch would NOT detect us as running. The underscore prefix on `_instance_lock` documents the held-for-side-effects intent.

- **Stale-lock recovery is automatic — do not configure it.** `QLockFile.tryLock` performs a PID-liveness check on every call: if the PID written into the lockfile no longer maps to a live process (e.g., the prior tray instance was killed via Task Manager), the lock is treated as stale, the file is removed, and `tryLock` proceeds to acquire afresh. This happens regardless of `setStaleLockTime`. We therefore leave the default (30000ms) untouched; tweaking it has no observable effect for this app.

- **Same-process double-acquire is a real test path.** Two `QLockFile` instances in the same Python process pointing at the same path — when the first holds the lock and the second calls `tryLock(0)` — return `False` for the second, because Qt uses an OS-level file lock under the hood (`LockFileEx` on Windows, `flock` elsewhere) and OS file locks are per-handle, not per-process. This is why the test class can drive both branches without spawning a subprocess.

## Phase 1: Implementation

### Overview

Production code change + automated test coverage for the single-instance lock. This phase ends with a green CI gate (pytest, pyright, ruff, pip-audit, pip-licenses) but BEFORE the manual cross-process smoke test on real Windows.

### Changes Required:

#### 1. `app_lock_path()` in `storage/paths.py`

**File**: `break_reminder/storage/paths.py`

**Intent**: Add a path helper for `%APPDATA%\BreakReminder\app.lock` so the lockfile location lives alongside the other per-user data paths and is reused by both production code and tests.

**Contract**: New public function `app_lock_path() -> Path` returning `app_data_dir() / "app.lock"`. One-line Google-style docstring matching the four existing helpers (`settings_ini_path`, `event_log_path`, `reminders_json_path`).

#### 2. `_acquire_single_instance_lock` helper in `break_reminder/app.py`

**File**: `break_reminder/app.py`

**Intent**: Encapsulate the `QLockFile` construction + `tryLock(0)` into a module-private helper that is unit-testable in isolation. Returns the locked `QLockFile` on success (the caller binds it to a name to keep it alive), or `None` on contention (any failure mode — held by another live instance, lockfile unreadable, parent dir unwritable). Per planning Q3, the caller treats every `None` return identically.

**Contract**: New module-level function with signature `_acquire_single_instance_lock(lock_path: Path) -> QLockFile | None`. Constructs `QLockFile(str(lock_path))`, calls `tryLock(0)`, returns the lock on True, returns `None` on False. The function is parameterized on `lock_path` so tests can drive it against `tmp_path` without monkeypatching `storage.paths`. Although the function is module-private (leading underscore), it encodes non-obvious behavior — the lifetime contract on the returned `QLockFile` — so the lessons.md private-helper carve-out applies and a Google-style docstring IS required, naming both the contract (lock acquired or `None` on contention) and the lifetime expectation (caller must bind the return value for the duration of the lock's intended hold).

Also add the import: `from PySide6.QtCore import QLockFile` (group with the existing `QtCore` imports on line 21).

#### 3. Wire the lock into `main()`

**File**: `break_reminder/app.py`

**Intent**: Insert the lock-acquisition between the existing `qt_app.setQuitOnLastWindowClosed(False)` and the `QSystemTrayIcon.isSystemTrayAvailable()` check. On contention, show a single information-level message box and return 0 (clean exit, not an error code). On success, bind the returned lock to `_instance_lock` so it lives until `qt_app.exec()` returns.

**Contract**: After the existing `qt_app.setQuitOnLastWindowClosed(False)` (line 487), add:
- `_instance_lock = _acquire_single_instance_lock(app_lock_path())`
- on `_instance_lock is None`: `QMessageBox.information(None, APPLICATION_NAME, "BreakReminder is already running. Look for the clock icon in the system tray.")` and `return 0`
- on success: continue to the existing tray-availability check; the lock stays bound for the rest of `main()`

Add the import: `from break_reminder.storage.paths import APPLICATION_NAME, app_lock_path` (extend the existing one-name import on line 37). The `_instance_lock` local variable name uses an underscore prefix to flag it as held-for-side-effects; ruff's default `dummy-variable-rgx` exempts leading-underscore names from F841 (verified against `[tool.ruff.lint]` in `pyproject.toml` — no `dummy-variable-rgx` override) — no `# noqa` needed.

#### 4. `TestSingleInstanceLock` in `tests/test_app.py`

**File**: `tests/test_app.py`

**Intent**: Pin the four observable contracts of `_acquire_single_instance_lock`: (a) acquires successfully against a clean lockfile path, (b) returns None when the lock is already held by an in-process holder, (c) re-acquires successfully after the first lock is unlocked / GC'd, (d) `app_lock_path()` resolves under `app_data_dir()`.

**Contract**: New test class `TestSingleInstanceLock` with at least these tests:
- `test_acquires_against_clean_path` — `_acquire_single_instance_lock(tmp_path / "app.lock")` returns a non-None `QLockFile` whose `isLocked()` is True.
- `test_second_acquire_returns_none_while_first_held` — first call holds the lock; second call against the same path returns `None`. Pinned by storing the first return value in a local for the duration of the test (otherwise the lock is GC'd before the second call).
- `test_third_acquire_after_unlock_succeeds` — explicitly call `unlock()` on the first `QLockFile`, then a fresh `_acquire_single_instance_lock(...)` against the same path returns a non-None lock.
- `test_app_lock_path_under_app_data_dir` — assert `app_lock_path().parent == app_data_dir()` and `app_lock_path().name == "app.lock"`.

Tests use the existing session-scoped `qapp` fixture (autouse via conftest) and `tmp_path` for the lockfile path. Import: `from break_reminder.app import _acquire_single_instance_lock` and `from break_reminder.storage.paths import app_data_dir, app_lock_path`.

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_app.py -v` (includes new `TestSingleInstanceLock`)
- Full suite passes: `uv run pytest`
- Type check passes: `uv run pyright`
- Linting passes: `uv run ruff check`
- Format check passes: `uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual Verification:

- Real Windows: launch `BreakReminder.exe` (or `uv run python -m break_reminder`) — tray icon appears.
- Real Windows: with the first instance running, launch a second copy — `QMessageBox.information` appears titled "BreakReminder" with body "BreakReminder is already running. Look for the clock icon in the system tray." Click OK; the second process exits cleanly. The first instance's tray icon remains, schedulers continue ticking.
- Real Windows: with the first instance running, launch a third copy — same behavior as the second.
- Real Windows: hard-kill the first instance via Task Manager (End Task on `BreakReminder.exe`). Verify `%APPDATA%\BreakReminder\app.lock` still exists on disk. Launch a fresh copy — startup proceeds normally (no message box), lockfile is reclaimed, tray icon appears.
- Real Windows: with the first instance running, click the tray icon → Open settings… → modify break interval, click OK — works (sanity check that the lock doesn't interfere with normal in-process operation).
- Real Windows: existing flows (Take break now, Reset, Pause/Resume, break-due dialog, custom reminders, Check for updates) all still work.
- Real Windows: launch the bundled `.exe --self-test` while a tray instance is running — exits 0 (smoke test bypasses the lock as designed).

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Bookkeeping

### Overview

Lightweight follow-up: flip the change folder's `change.md` status from `planned` to `implemented`, update its `updated:` date, and finish the roadmap S-10 entry — flip the existing `planned` rows to `done` and append the still-missing Done-section bullet. The "At a glance" / Slices / "Backlog Handoff" rows themselves were added pre-implementation (during the planning chat) and already carry status `planned`; this phase only flips them and adds the Done section. No code edits.

### Changes Required:

#### 1. `change.md` status flip

**File**: `context/changes/bugfix-single-instance-guard/change.md`

**Intent**: Reflect the implemented state for `/10x-archive`'s soft-warning gate ("Status is X; expected implemented or impl_reviewed").

**Contract**: Frontmatter `status: planned` → `status: implemented`; `updated: <today>`.

#### 2. Roadmap S-10 status flip + Done bullet

**File**: `context/foundation/roadmap.md`

**Intent**: Flip the existing S-10 rows from `planned` to `done` and append the still-missing Done-section bullet. The "At a glance" row, the detailed `### S-10` slice block, and the "Backlog Handoff" row were added pre-implementation during the planning chat; this phase only updates their status and adds the Done section, mirroring how S-09 was recorded after its implementation.

**Contract**:
- "At a glance" table: flip the existing S-10 row's Status column from `planned` to `done` (the row itself is already in place at line ~42).
- Slices section: flip the `### S-10` block's `- **Status:** planned` to `- **Status:** done` (currently at line ~223).
- "Backlog Handoff" table: leave the row in place — its Notes column is forward-looking ("Discovered 2026-05-29 from real-world use; planned same day") and remains accurate after implementation; no flip needed.
- "Done" section: append a new bullet at the bottom of the existing list, mirroring S-09's bullet style. Format: `- **S-10: <one-line outcome restatement>** — Archived <YYYY-MM-DD> → \`context/archive/<dated-folder>/\`. Lesson: <single sentence or em-dash if none>.` Use today's date as the archive marker; the actual archive happens via `/10x-archive` after the impl-review step.
- Frontmatter: bump `updated:` to today's date.

### Success Criteria:

#### Automated Verification:

- `git grep -nE 'status: implemented' context/changes/bugfix-single-instance-guard/change.md` returns exactly one match.
- `git grep -nE '\| S-10 \|.*\| done \|' context/foundation/roadmap.md` returns exactly one match (the "At a glance" row, post-flip).
- `git grep -nE '\*\*Status:\*\* done' context/foundation/roadmap.md` count increases by one vs. baseline (the `### S-10` slice block, post-flip).
- `git grep -nE '\*\*S-10:' context/foundation/roadmap.md` returns at least one match (the new Done-section bullet).

---

## Testing Strategy

### Unit Tests:

- **Lock acquisition against clean path** — first call to `_acquire_single_instance_lock(tmp_path / "app.lock")` returns a non-None `QLockFile` whose `isLocked()` is True.
- **Contention returns None** — second call against the same path while the first lock is in scope returns `None`. Pinned by binding the first return value in a local for the test duration.
- **Re-acquire after unlock** — explicitly calling `unlock()` on the first `QLockFile` (or letting it go out of scope) allows a subsequent call against the same path to succeed.
- **`app_lock_path()` resolves under `app_data_dir()`** — smoke that the path helper behaves like its four siblings.

### Integration Tests:

- The cross-process behavior — i.e., proving that two separate Python processes (or two instances of the bundled `.exe`) reject each other — is covered by the manual verification list, not by an automated subprocess test. Spawning a second `python -m break_reminder` from pytest would require careful teardown to avoid leaving a tray icon between test runs; the cost outweighs the benefit for a personal-use Windows app.

### Manual Testing Steps:

The Phase 1 Manual Verification list IS the manual testing surface; Phase 2 has no new manual surface beyond verifying the docs read coherently after the roadmap edit.

## Performance Considerations

- **Lock acquisition cost** — `QLockFile.tryLock(0)` is one stat + one OS-level file-lock attempt. Sub-millisecond on local disk.
- **Cold-start impact** — adds at most a single file-system probe to the existing startup sequence. Imperceptible against the existing pynput listener startup + tray-icon QPainter render + scheduler arming.
- **No new IO during steady-state** — the lock is acquired once at startup and released at process exit. No periodic refresh, no background thread.
- **No new persistence** — `app.lock` is regenerated on every launch; its contents (PID + hostname + app name) are managed by Qt and consume <100 bytes.

## Migration Notes

No data migration. No `Settings` schema change, no `reminders.json` shape change. Existing `BreakReminder.ini` and `reminders.json` files load and behave identically. The lockfile is created on first launch under the existing `%APPDATA%\BreakReminder\` directory.

**Uninstall**: the existing NSIS script's "leave `%APPDATA%` in place" behavior preserves the lockfile across uninstall/reinstall cycles. This is harmless — the next launch's `QLockFile.tryLock` does the PID-liveness check, finds the prior PID is dead (because the prior process is long gone), treats the lockfile as stale, removes it, and acquires a fresh lock. No manual cleanup required.

**Downgrade path**: if a user installs v0.7.x (this slice) and then downgrades to v0.6.x, the lockfile from v0.7.x is harmless to v0.6.x (which doesn't read it). No backward-compatibility concern.

## References

- Roadmap entry (to be added in Phase 2): `context/foundation/roadmap.md` § S-10.
- Bug analysis: see chat dialogue 2026-05-29 (root cause: no single-instance check in `break_reminder.app:main()`; symptom: N tray icons + concurrent storage writers).
- Existing `main()` body to modify — `break_reminder/app.py:477-499`.
- Existing storage-paths helpers to mirror — `break_reminder/storage/paths.py:39-51`.
- Existing test infra — `tests/conftest.py` (autouse `qapp` fixture), `tests/test_app.py` (the file the new test class lands in).
- Bootstrap-panic doctrine the lock check must NOT touch — `main.py:1-25`.
- `--self-test` short-circuit that naturally bypasses the lock — `main.py:_run` (the `--self-test` arg branch returns before importing `break_reminder.app`).
- Qt 6 `QLockFile` documentation: https://doc.qt.io/qt-6/qlockfile.html — note the PID-liveness check semantics and `setStaleLockTime` defaults.
- Prior bugfix-shape precedent — `context/archive/2026-05-28-bugfix-break-cycle-reset-on-save/plan.md` (S-09): same single-phase + bookkeeping shape.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Implementation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_app.py -v` (includes new `TestSingleInstanceLock`)
- [x] 1.2 Full suite passes: `uv run pytest`
- [x] 1.3 Type check passes: `uv run pyright`
- [x] 1.4 Linting passes: `uv run ruff check`
- [x] 1.5 Format check passes: `uv run ruff format --check`
- [x] 1.6 Security audit passes: `uv run pip-audit`
- [x] 1.7 License gate passes: `uv run pip-licenses --fail-on="AGPL"`

#### Manual

- [x] 1.8 Real Windows: launch BreakReminder — tray icon appears
- [x] 1.9 Real Windows: launch second copy — message box appears, second process exits cleanly, first instance unaffected
- [x] 1.10 Real Windows: launch third copy — same behavior as second
- [x] 1.11 Real Windows: hard-kill via Task Manager, relaunch — startup proceeds normally (stale lockfile reclaimed)
- [x] 1.12 Real Windows: open Settings → modify break interval → OK with first instance running — works (no lock interference with in-process operation)
- [x] 1.13 Real Windows: existing flows (Take break now, Reset, Pause/Resume, break-due dialog, custom reminders, Check for updates) all still work
- [x] 1.14 Real Windows: bundled `.exe --self-test` while a tray instance is running — exits 0

### Phase 2: Bookkeeping

#### Automated

- [ ] 2.1 `git grep -nE 'status: implemented' context/changes/bugfix-single-instance-guard/change.md` returns exactly one match
- [ ] 2.2 `git grep -nE '\| S-10 \|.*\| done \|' context/foundation/roadmap.md` returns exactly one match (At a glance row, post-flip)
- [ ] 2.3 `git grep -nE '\*\*Status:\*\* done' context/foundation/roadmap.md` count increased by one vs. baseline (Slices block, post-flip)
- [ ] 2.4 `git grep -nE '\*\*S-10:' context/foundation/roadmap.md` returns at least one match (Done-section bullet)
