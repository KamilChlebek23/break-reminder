# Bugfix Reminder DST Drift Implementation Plan

## Overview

Fix the R-1b DST-drift defect in `next_firing_after` — recurring reminders like "Daily 9:00 Europe/Warsaw" silently shift by an hour after DST transitions because `dateutil.rrule.rrulestr(rule, dtstart=start_utc).after(now)` runs RRULE arithmetic in UTC space, where DST does not exist. The fix adds a scheduler-only `tz: str` field to `Reminder` (storage invariant on `start_at` unchanged), localizes `dtstart` and `now` to that zone before RRULE math, captures OS-local IANA at form save time, and defaults missing `tz` to system-local at load time per the existing F3 storage-boundary idiom.

## Current State Analysis

The codebase has **zero existing IANA timezone infrastructure** beyond `datetime.UTC`: no `dateutil.tz`, no `zoneinfo`, no `pytz`, no Settings tz key, no UI tz picker. Production code uses `from datetime import UTC, datetime` exclusively. One established DST-correct pattern exists — `naive.astimezone(UTC)` at the form save path ([`reminder_form_dialog.py:879`](../../../break_reminder/ui/reminder_form_dialog.py)) — but it collapses the user's local-time intent before storage, leaving the firing path with a tz-aware UTC `dtstart` that RRULE math cannot DST-correct.

R-1b's defect (researched and parked during the testing-rrule-reminder-loop change, re-grounded in [`research.md`](research.md)) is confirmed reproducible at HEAD on commit `cd24605a3918430b12a548aecba8f774ed74e804`:

- `break_reminder/scheduler.py:362` — `rule = rrulestr(reminder.rrule_str, dtstart=start)` where `start` is tz-aware UTC
- `break_reminder/scheduler.py:367` — `nxt = rule.after(now, inc=False)` — UTC-space firing arithmetic
- Worked example (Europe/Warsaw spring-forward 2026-03-28→29): a "Daily 9:00 Warsaw" reminder stored as `08:00 UTC` (CET, UTC+1) silently fires at `10:00 CEST` on the first post-DST day (still `08:00 UTC`, now `10:00` wall-clock).

Blast radius is bounded: 5 production Reminder construction sites + 55 test sites + 7 inline dict literals + **0** JSON fixture files + **0** whole-instance `Reminder` equality assertions in tests. Selected fix shape (option (c) — UTC `start_at` UNCHANGED + scheduler-only optional `tz: str` field with a default factory) collapses the constructor blast radius to ~5 sites because the field is optional with a sensible default; all 60 existing constructions stay unchanged.

R-5 (storage malformed-input rollout) hardened the load boundary with row-level containment in `ReminderStore._read` and the `_coerce_aware_utc` / `_coerce_lead_minutes` helpers; the new `tz` field plugs into this existing F3 idiom without inventing a new load pattern.

## Desired End State

After this plan lands:

- A recurring reminder with `tz="Europe/Warsaw"` and `start_at` representing "9:00 Warsaw on 2026-03-28" (= `08:00 UTC`, CET) fires at "9:00 Warsaw on 2026-03-29" (= `07:00 UTC`, CEST) — wall-clock stable across the DST boundary.
- Existing `reminders.json` files load with no migration; missing `tz` field defaults to OS-local at load (lazy persistence on next user edit) via the F3 `_coerce_*` idiom.
- New reminders created via the form persist an explicit `tz` field captured from the OS at save time, so the user's intent ("9:00 wherever I created this") survives across machine moves.
- A failing-then-passing test in `tests/test_scheduler.py` pins the R-1b spring-forward scenario; a sibling non-DST test pins the flat-tz path so the new tz-localization code doesn't silently regress outside DST windows.
- `AGENTS.md` line 88's "RRULE handles DST correctly" claim is scoped to "when `dtstart` carries an IANA-named timezone".
- The archived `2026-05-28-reminders-recurrence-editor/reviews/impl-review.md` carries a 1-line correction noting that the "DST correctness" claim was overscoped and that R-1b was missed.

### Key Discoveries:

- Fix-shape (c) preserves the existing UTC storage invariant — `start_at` and `end_at` stay tz-aware UTC; the new `tz: str` is metadata consumed only by the scheduler. `_coerce_aware_utc` continues to be the UTC chokepoint exactly as today (`break_reminder/storage/reminders.py:86-122`).
- `to_dict` needs **no code change**: `asdict(self)` auto-includes new dataclass fields ([`reminders.py:154-159`](../../../break_reminder/storage/reminders.py)). Easy place to over-engineer.
- `ReminderStore._read` exception tuple needs **no widening**: per plan-review F3, `_coerce_tz` raises `InvalidTimezoneError(ValueError)` on invalid hand-edited tz strings, which is already caught by the existing `(KeyError, ValueError, TypeError)` tuple at [`reminders.py:262`](../../../break_reminder/storage/reminders.py). The lazy-migration path (missing field) returns OS-local without raising. Two distinct failure modes, both safe.
- Stdlib `zoneinfo.ZoneInfo("Europe/Warsaaw")` raises `ZoneInfoNotFoundError` explicitly — avoids the silent-`None` gotcha that `dateutil.tz.gettz` has and that motivated the `_coerce_tz` defensive shape.
- The codebase already uses a `tz: tzinfo | None = None` injection idiom on display helpers (`_format_firing`, `format_body`, `reminder_form_dialog._datetime_local_default_*` family). Mirror-don't-invent: the scheduler test can mock `tzlocal.get_localzone_name` and pass `tz="Europe/Warsaw"` on a fresh `Reminder` without touching production defaults.
- `test_recurring_reminder_integration.py:33-41` contains a `TODO(R-1b)` breadcrumb explicitly deferring the failing test to this change; Phase 2 removes it.

## What We're NOT Doing

- **No UI timezone picker.** Form captures OS-local at save time per Q2's `(ii) system-local at save time` decision. A per-reminder TZ picker (digital-nomad use case) is a separable UX slice for a future change.
- **No one-shot migration of existing `reminders.json` files.** Missing `tz` defaults at load time via F3 idiom; persistence happens lazily on next user edit. Per Q4 decision.
- **No `Reminder` storage-invariant change.** `start_at`/`end_at` stay tz-aware UTC. Per Q1's option (c) decision; alternatives (a) IANA on `start_at` and (b) naive + tz field were rejected for blast radius.
- **No `dateutil.tz.gettz` adoption.** Stdlib `zoneinfo.ZoneInfo` chosen per Q3 for explicit `ZoneInfoNotFoundError` and no silent-`None` gotcha.
- **No new Settings key.** The form captures tz at save time directly via `tzlocal.get_localzone_name()`; no need to expose tz as a user-configurable preference.
- **No lessons.md update in this plan.** A `/10x-impl-review` after merge may surface a lesson about "wall-clock save needs both UTC instant AND IANA name to round-trip user intent across DST" — but committing to that here would pre-empt the review.

## Implementation Approach

Four phases, each commit-shaped:

1. **Storage foundation** (Phase 1) lands the data model (`tz` field + `_coerce_tz`) and runtime dependencies (`tzdata` + `tzlocal`). The field exists but is unused by the scheduler — intermediate state is safe (existing tests stay green; no behavior change).
2. **Scheduler fix via TDD** (Phase 2) writes the failing R-1b test first under `pytest.mark.xfail(strict=True)`, then implements the localize-dtstart-and-now change in `next_firing_after`, then removes the xfail mark. This is the only phase that changes user-visible behavior.
3. **Form integration** (Phase 3) wires `tzlocal.get_localzone_name()` into the form's `accept()` save path so newly-created reminders persist explicit tz (rather than relying on the F3 default-at-load fallback).
4. **Docs + archive cleanup** (Phase 4) corrects the AGENTS.md DST claim, annotates the archived impl-review for grep-discoverability, unparks the test-plan §7 entry, and removes the R-1b breadcrumb.

Phase ordering is dependency-driven: Phase 1's `tz` field must exist before Phase 2's failing test can construct a `Reminder(tz=...)`; Phase 3's form changes consume the field added in Phase 1; Phase 4 is pure documentation and depends on the fix being real.

## Critical Implementation Details

- **State sequencing — Phase 1 ends with a half-built fix on purpose.** After Phase 1, `Reminder.tz` exists and round-trips through `from_dict`/`to_dict`, but `next_firing_after` still ignores it. This is intentional: it lets Phase 2's RED test construct a `Reminder(tz="Europe/Warsaw")` and prove the scheduler bug exists, before Phase 2's GREEN flips the implementation. Do not "fix the scheduler" inside Phase 1 — the xfail-strict RED commit is the regression sentinel for the whole change.

- **xfail-strict ordering — the RED test must actually fail.** `pytest.mark.xfail(strict=True)` makes pytest fail loudly if an xfailed test unexpectedly passes. Phase 2 must land in this order: (1) RED commit adds the xfailed test, CI is green because xfailed-and-failed counts as pass; (2) GREEN commit changes `next_firing_after`, removes the xfail mark in the same commit — the test now passes for the right reason. Splitting "implement" and "remove xfail" into separate commits leaves an intermediate state where CI fails (test passes but is still marked xfail strict).

- **Public scheduler contract stays UTC.** `next_firing_after` callers (`_compute_next` at `scheduler.py:336`) compare the return value to `self._clock()` which is tz-aware UTC. After Phase 2 localizes to `reminder.tz` for the RRULE math, the return value must be converted back to UTC (`.astimezone(UTC)`) before returning. Callers do not need to know tz was ever involved.

- **Two-layer validation with different semantics (per plan-review F3).** Load-time `storage/reminders.py:_coerce_tz` distinguishes "missing field" (returns OS-local — lazy migration of older files) from "invalid value" (raises `InvalidTimezoneError(ValueError)`, caught by `_read`'s row-containment which drops the whole row + logs). Runtime `scheduler.py:_resolve_zone` defensively swallows `(ZoneInfoNotFoundError, ValueError)` → falls back to `ZoneInfo("UTC")` + WARNING — handles in-memory `Reminder` instances constructed bypassing `from_dict` (especially in tests). The layers differ deliberately: storage is strict (an invalid tz string is a fingerprint of a hand-edit error worth surfacing); scheduler is lenient (an invalid in-memory tz is most likely a test fixture issue not worth crashing production over). **Alternative considered and rejected (per plan-review F8):** lift invariant enforcement to a `Reminder.__post_init__` validator so the scheduler can trust `reminder.tz` unconditionally. Rejected because (a) the codebase doesn't use dataclass `__post_init__` anywhere else — adding it here introduces a new pattern, and (b) it would run on all 60 existing test `Reminder(...)` constructions, coupling test fixtures to `tzlocal` availability. Defensive duplication is the cheaper trade-off; revisit if `_resolve_zone` proves awkward in practice.

## Phase 1: Storage foundation

### Overview

Add the `tz: str` field to `Reminder`, the `_coerce_tz` load-boundary helper, and the runtime dependencies (`tzdata`, `tzlocal`). After this phase the data model carries tz but the scheduler still ignores it — all existing tests pass; no user-visible behavior change.

### Changes Required:

#### 1. Runtime dependencies

**File**: `pyproject.toml`

**Intent**: Add IANA tzdata (zoneinfo data) and OS-local tz detection (`tzlocal`) to the runtime dependency set so production has cross-platform IANA support. `tzdata` provides the IANA database that `zoneinfo.ZoneInfo` reads on Windows; `tzlocal>=5.0` exposes `get_localzone_name()` returning a stable IANA string across Windows / Linux / macOS.

**Contract**: Append `"tzdata>=2024.1"` and `"tzlocal>=5.0"` to the alphabetically-sorted `[project].dependencies` list. Run `uv lock` and commit the refreshed `uv.lock`. Verify the additions pass `uv run pip-audit` and `uv run pip-licenses --fail-on="AGPL"`.

**Also update the PyInstaller invocation in pyproject.toml's comment block** (lines 88-93) — `tzdata` is a data-only package whose `.zoneinfo` files PyInstaller does NOT auto-discover (empirically: without tzdata, `zoneinfo.ZoneInfo('Europe/Warsaw')` raises `ZoneInfoNotFoundError` on Windows; the bundled .exe would hit the same failure for every reminder load post-fix). Change the example invocation from:

```
uv run pyinstaller --noconfirm --windowed --name BreakReminder \
                   --collect-submodules pynput main.py
```

to:

```
uv run pyinstaller --noconfirm --windowed --name BreakReminder \
                   --collect-submodules pynput \
                   --collect-data tzdata main.py
```

(Same flag goes into `.github/workflows/release.yml` if the PyInstaller invocation is duplicated there — implementer should grep both and update consistently.)

Per plan-review F4: this is the release-build foot-gun that local dev + CI tests won't catch (both install tzdata via uv sync); only the first packaged installer build after the fix would hit it.

#### 2. `_coerce_tz` helper

**File**: `break_reminder/storage/reminders.py`

**Intent**: Mirror the `_coerce_lead_minutes` / `_coerce_aware_utc` precedent. Provide hand-edit-safe coercion from raw JSON to a validated IANA name. Defends the storage boundary per the lessons.md storage-boundary rule. Distinguishes two failure modes per plan-review F3:

- **Missing field (`None`)** — older file predating the fix; legitimate lazy-migration case. Substitute OS-local silently.
- **Invalid value (typo'd string, wrong type, empty string, path-traversal)** — user explicitly typed something that doesn't resolve. Raise `InvalidTimezoneError` so `_read`'s row-containment drops the whole row with a WARNING (per lessons.md rule (b), Row-level). The user notices the missing reminder, greps the log, fixes the typo. This is preferable to silently swapping a typo'd Warsaw for OS-local Tokyo and firing at the wrong wall-clock for days.

**Contract**: New module-level exception class plus function:

```python
class InvalidTimezoneError(ValueError):
    """Raised by _coerce_tz when a hand-edited tz value cannot be resolved."""
```

Subclass of `ValueError` so `ReminderStore._read`'s existing exception tuple `(KeyError, ValueError, TypeError)` (line 262) catches it without modification — no row-tuple widening needed.

New module-level function `_coerce_tz(raw: object) -> str`:

- `raw is None` (field missing from disk) → return `tzlocal.get_localzone_name()` (lazy migration: existing reminders.json files lacking the field default to OS-local; this is the file-is-older-than-the-fix case)
- `raw is str` and `ZoneInfo(raw)` succeeds → return `raw` unchanged
- `raw is str` and `ZoneInfo(raw)` raises `(ZoneInfoNotFoundError, ValueError)` → raise `InvalidTimezoneError(f"reminder tz {raw!r} is not a valid IANA name")` (no log here — `_read` logs the dropped row at WARNING with index + class name). Both `zoneinfo` exception classes must be caught: `ZoneInfoNotFoundError` for unknown zones (`"Europe/Warsaaw"`, `"foo/bar/baz"`) and `ValueError` for malformed keys (`""`, `"../etc/passwd"` — `zoneinfo` validates path normalization independently of zone existence).
- `raw` is anything else (int, list, dict) → raise `InvalidTimezoneError(f"reminder tz field has unexpected type {type(raw).__name__}")`
- If `tzlocal.get_localzone_name()` itself returns `None` or raises in the `None` branch (rare on Windows 11): catch and return `"UTC"` as last-resort fallback (paranoid but cheap).

Default factory at the dataclass level continues to call `_coerce_tz(None)` — that path remains safe (always returns a valid string).

Add a docstring documenting the contract: "missing field → OS-local; valid IANA → preserved; invalid → InvalidTimezoneError (caught by _read row-containment)". Reference the lessons.md storage-boundary rule by name and explicitly cite plan-review F3 as the rationale for the missing-vs-invalid split.

#### 3. `tz` field on `Reminder` dataclass

**File**: `break_reminder/storage/reminders.py`

**Intent**: Add an optional `tz: str` field to the `Reminder` dataclass. Default-factory captures OS-local at construction time so existing 55+ test sites and 5 production sites need no code changes — they get OS-local automatically.

**Contract**: Insert after `lead_minutes: int = 0` (line 151) and before `id: str = field(default_factory=lambda: str(uuid.uuid4()))` (line 152):

```python
tz: str = field(default_factory=lambda: _coerce_tz(None))
```

Using `_coerce_tz(None)` as the default factory routes through the same fallback chain that the load path uses — single source of truth for "what is OS-local?".

Update the class docstring's invariant paragraph (lines 127-139) to extend the contract: `start_at` and `end_at` stay tz-aware UTC (unchanged); the new `tz` is the IANA name to localize to for RRULE math. Together they preserve user wall-clock intent across DST.

#### 4. `from_dict` wires `_coerce_tz`

**File**: `break_reminder/storage/reminders.py`

**Intent**: Apply tz coercion at the load boundary per the F3 idiom (all coercions applied before constructing `Reminder(...)`).

**Contract**: Add `tz=_coerce_tz(data.get("tz"))` to the `cls(...)` call inside `from_dict` (currently lines 179-190). Place after `lead_minutes=_coerce_lead_minutes(...)` for alphabetical-by-field-position consistency.

#### 5. `to_dict` — verify auto-emission, no code change

**File**: `break_reminder/storage/reminders.py`

**Intent**: `to_dict` uses `asdict(self)` which auto-includes any new dataclass field. No code change needed — but Phase 1's round-trip test must verify this contract holds (defensive: a future refactor could replace `asdict` with manual construction).

**Contract**: No source change. A round-trip test in Phase 1's test work asserts `Reminder(tz="Europe/Warsaw").to_dict()["tz"] == "Europe/Warsaw"`.

#### 6. Storage tests

**File**: `tests/test_reminders.py`

**Intent**: Mirror the `_coerce_lead_minutes` test pattern around line 666 (the `+00:00`-stripped hand-edit test). Pin the `_coerce_tz` behavior contract and the `from_dict`/`to_dict` round-trip for the new field. Cover the row-containment path (a row with invalid tz value is dropped with a WARNING; well-formed siblings preserved — per plan-review F3).

**Contract**: Add tests covering:
- `_coerce_tz(None)` → returns OS-local IANA string (mock `tzlocal.get_localzone_name` to return `"Europe/Warsaw"`; assert) — lazy-migration path
- `_coerce_tz("Europe/Warsaw")` → returns `"Europe/Warsaw"` unchanged
- `_coerce_tz("Europe/Warsaaw")` (typo, triggers `ZoneInfoNotFoundError`) → raises `InvalidTimezoneError` (assert via `pytest.raises`)
- `_coerce_tz(123)` (wrong type) → raises `InvalidTimezoneError`
- `_coerce_tz("")` (empty string, triggers `ValueError`: "keys must be normalized relative paths") → raises `InvalidTimezoneError`
- `_coerce_tz("../etc/passwd")` (path traversal, triggers `ValueError`: "keys must refer to subdirectories of TZPATH") → raises `InvalidTimezoneError`. Pinned explicitly because `ZoneInfo` raises `ValueError` here, not `ZoneInfoNotFoundError` — implementer must catch both.
- `InvalidTimezoneError` is a `ValueError` subclass: `issubclass(InvalidTimezoneError, ValueError)` is True — pinned so `_read`'s `(KeyError, ValueError, TypeError)` tuple keeps working without widening.
- Round-trip: `Reminder(name="t", start_at=<utc>, tz="Europe/Warsaw").to_dict()["tz"] == "Europe/Warsaw"`
- Backward-compat: load a dict without `"tz"` key → resulting `Reminder.tz` equals OS-local (lazy-migration path)
- **Row-containment on invalid tz**: `ReminderStore._read` on a file with two rows where row 0 has `"tz": "Europe/Warsaaw"` (typo) and row 1 has a valid tz → row 0 is DROPPED with a WARNING naming the row index + `InvalidTimezoneError`; row 1 loads successfully. Mirror the existing `_read` row-containment test pattern (see how row-containment is tested for `_coerce_lead_minutes` failures).

Mock `tzlocal.get_localzone_name` to return `"Europe/Warsaw"` for these tests so they're deterministic on any CI runner.

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_reminders.py`
- All other tests still pass: `uv run pytest`
- Type checking passes: `uv run pyright`
- Linting passes: `uv run ruff check && uv run ruff format --check`
- Security audit passes: `uv run pip-audit`
- License gate passes: `uv run pip-licenses --fail-on="AGPL"`
- `uv.lock` refreshed and committed alongside `pyproject.toml`
- PyInstaller smoke build with the new `--collect-data tzdata` flag (per F4) succeeds locally: `uv run pyinstaller --noconfirm --windowed --name BreakReminder --collect-submodules pynput --collect-data tzdata main.py` produces `dist/BreakReminder/`, and inspecting it shows tzdata data files are bundled (e.g. `dist/BreakReminder/_internal/tzdata/zoneinfo/Europe/Warsaw` exists, or PyInstaller's equivalent layout for the current version)

#### Manual Verification:

- Hand-edit a `reminders.json` entry to add `"tz": "Europe/Warsaw"` (a valid IANA name) → restart app → verify the entry loads without warnings
- Hand-edit a `reminders.json` entry to add `"tz": "Europe/Warsaaw"` (typo'd) → restart app → verify the entry IS DROPPED with a single WARNING in the log naming row index + `InvalidTimezoneError`; sibling well-formed rows still load
- Hand-edit a `reminders.json` entry to remove the `"tz"` key entirely → restart app → verify the entry loads with OS-local default and no warnings (lazy-migration path: missing field is fine, invalid value is not)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase. Phase blocks use plain bullets — the corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Scheduler fix (TDD)

### Overview

The bugfix itself. Write the failing R-1b regression test first under `pytest.mark.xfail(strict=True)`, then change `next_firing_after` to localize `dtstart` and `now` to `reminder.tz` before `rrulestr` math, then remove the xfail mark in the same commit. Add a non-DST counter-test so the new code path doesn't silently regress flat-tz scenarios. Remove the now-obsolete R-1b breadcrumb from the integration tests.

Drive this phase via `/10x-tdd bugfix-reminder-dst-drift` rather than `/10x-implement` — the breadcrumb explicitly deferred a failing test to this change, the bug has a precise reproduction in research, and the test infrastructure (clock injection, scheduler unit tests, conftest fixtures) is mature.

### Changes Required:

#### 1. RED — failing R-1b test

**File**: `tests/test_scheduler.py`

**Intent**: Pin the R-1b DST-drift defect using the Europe/Warsaw spring-forward worked example from research. Marked `pytest.mark.xfail(strict=True)` so the test fails loudly when the fix lands without removing the mark.

**Contract**: Add a new test class `TestDstDrift` (or extend an existing class if there's a natural one) with at least:

- `test_daily_warsaw_reminder_does_not_drift_across_spring_forward` — Construct `Reminder(name="...", start_at=datetime(2026, 3, 28, 8, 0, tzinfo=UTC), rrule_str="FREQ=DAILY", tz="Europe/Warsaw")` (this is "9:00 Warsaw on 2026-03-28", CET = UTC+1). Call `next_firing_after(reminder, datetime(2026, 3, 28, 7, 0, tzinfo=UTC))`. Expected (post-fix): `datetime(2026, 3, 29, 7, 0, tzinfo=UTC)` (= 9:00 Warsaw on 2026-03-29, CEST = UTC+2). Pre-fix: returns `datetime(2026, 3, 29, 8, 0, tzinfo=UTC)` which would be 10:00 Warsaw — wrong by exactly the DST offset.

Mark with `@pytest.mark.xfail(strict=True, reason="R-1b DST drift defect; will be fixed in Phase 2 GREEN")`.

The oracle is the RRULE specification, not a re-read of `next_firing_after` — derive the expected UTC instants from "9:00 Warsaw local on day N", NOT from running the scheduler.

#### 2. GREEN — localize before rrulestr math

**File**: `break_reminder/scheduler.py`

**Intent**: Resolve `reminder.tz` to a `ZoneInfo` and pass an IANA-aware `dtstart` to `rrulestr`; pass an IANA-aware `now` to `rule.after()`. RRULE's DST handling activates only when `dtstart` carries a named zone, not a fixed offset.

**Contract**: Inside `next_firing_after` (currently at `scheduler.py:348-373`):

1. Add a module-level helper `_resolve_zone(name: str) -> ZoneInfo` that returns `ZoneInfo(name)` or, on `ZoneInfoNotFoundError`, logs a WARNING and returns `ZoneInfo("UTC")`. Defensive — though `_coerce_tz` should catch bad names at load, in-memory `Reminder` instances bypassing `from_dict` (especially in tests) could still slip through.
2. After `start = _ensure_aware(reminder.start_at)` (line 353), add: `zone = _resolve_zone(reminder.tz)`.
3. Change `rule = rrulestr(reminder.rrule_str, dtstart=start)` (line 362) to `rule = rrulestr(reminder.rrule_str, dtstart=start.astimezone(zone))`.
4. Change `nxt = rule.after(now, inc=False)` (line 367) to `nxt = rule.after(now.astimezone(zone), inc=False)`.
5. After the existing `nxt = _ensure_aware(nxt)` (line 370), add `nxt = nxt.astimezone(UTC)` so the public return contract stays tz-aware UTC for `_compute_next`'s caller comparisons.

Import `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError` at the top of the module (after the existing `from datetime import UTC, datetime` line).

Update `next_firing_after`'s docstring to note that RRULE math is now performed in `reminder.tz` (not UTC) but the return value remains tz-aware UTC.

#### 3. GREEN — remove xfail mark

**File**: `tests/test_scheduler.py`

**Intent**: After GREEN, the R-1b test passes for the right reason. `xfail(strict=True)` would then fail the suite because an xfailed test unexpectedly passed. Remove the mark in the same commit as the implementation so CI never sees an intermediate red state.

**Contract**: Delete the `@pytest.mark.xfail(strict=True, ...)` decorator (or `pytest.mark.xfail(...)` parameter, depending on how it was added) from the R-1b test added in step 1.

#### 4. Non-DST counter-test

**File**: `tests/test_scheduler.py`

**Intent**: Ensure the tz-localization code path doesn't silently regress flat-tz scenarios; pin behavior outside DST windows so a future refactor that strips the `astimezone(zone)` calls doesn't pass the DST test alone.

**Contract**: Add `test_daily_warsaw_reminder_no_drift_within_dst_window` (or similar) — `Reminder(start_at=datetime(2026, 6, 15, 7, 0, tzinfo=UTC), rrule_str="FREQ=DAILY", tz="Europe/Warsaw")` (= 9:00 Warsaw, CEST). Assert two consecutive firings are exactly 24h apart (no DST boundary in mid-June). Oracle: `start_at + timedelta(days=N)` per RRULE spec.

Optionally add a `tz="UTC"` test to confirm the new code path is identity-on-UTC (i.e., `localize-to-UTC then localize-back-to-UTC` is a no-op on the returned value).

#### 5. Remove R-1b breadcrumb

**File**: `tests/test_recurring_reminder_integration.py`

**Intent**: The TODO at lines 33-41 explicitly says "When the bugfix change opens, the failing test belongs in `tests/test_scheduler.py`". With Phase 2's test landed, the comment is obsolete.

**Contract**: Delete lines 33-41 (the entire `# TODO(R-1b)` block). Preserve the surrounding context (the Phase 4 R-4 note about lifted fixtures stays untouched).

### Success Criteria:

#### Automated Verification:

- The R-1b regression test passes: `uv run pytest tests/test_scheduler.py -k dst_drift`
- All scheduler tests pass: `uv run pytest tests/test_scheduler.py`
- All other tests still pass: `uv run pytest`
- The non-DST counter-test passes
- No xfail marks remain on the R-1b test (mechanical check: `grep -n "xfail" tests/test_scheduler.py | grep -i "dst"` returns no matches — the R-1b test name contains "dst" so this anchors on the test identifier rather than human judgment; per plan-review F6)
- Type checking passes: `uv run pyright`
- Linting passes: `uv run ruff check && uv run ruff format --check`

#### Manual Verification:

- Examine `tests/test_scheduler.py` — the R-1b test passes for the right reason (assertion checks the post-DST instant, not the pre-DST one)
- Examine `tests/test_recurring_reminder_integration.py` — the `TODO(R-1b)` block is gone, surrounding R-4 note is intact

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Form integration

### Overview

Capture the OS-local IANA name at form save time and pass it to all three Reminder constructions in `accept()`. Without this phase, newly-created reminders default to OS-local at first load (correct on the creation machine but could resolve differently on a different machine); with this phase, the form persists explicit user intent.

### Changes Required:

#### 1. Capture OS-local tz at save time

**File**: `break_reminder/ui/reminder_form_dialog.py`

**Intent**: Capture `tzlocal.get_localzone_name()` once at the top of the datetime-validation section of `accept()`, then pass it to all three Reminder constructions. Captured value represents "the machine the user was on when they created/edited this reminder" — explicit intent that survives machine moves.

**Contract**: Add `import tzlocal` at the top of the module. Inside `accept()`, after `naive_local = cast(datetime, self._datetime_field.dateTime().toPython())` (line 868), add:

```python
tz_name = tzlocal.get_localzone_name() or "UTC"
```

Compute `tz_to_use` differentiating Add and Edit paths so editing-while-traveling doesn't silently rewrite tz (per plan-review F2):

- **Add path** (`self._editing is None`): always use `tz_name` (current OS-local) — explicit capture of "where the user is right now".
- **Edit path** (`self._editing is not None`): preserve `self._editing.tz` when `firing_unchanged_in_edit` is true (the existing predicate at lines 912-917 already checks `start_at_utc == self._editing.start_at and rrule_str_proposed == self._editing.rrule_str and end_at_proposed == self._editing.end_at`). When the user changed any firing-relevant field, refresh to `tz_name` — the user is restating intent in the new context. Pure name / lead-minutes edits keep the original tz untouched.

Reuse the existing `firing_unchanged_in_edit` boolean — it computes exactly the right predicate. Place the `tz_to_use` assignment after `firing_unchanged_in_edit` is computed (after line 917) and pass it to all three Reminder constructions:

- Tentative construction at `:936` (past-time gate check) — uses `tz_to_use` so the gate sees the actual persisted tz
- Edit-branch construction at `:958` — uses `tz_to_use` (preserves on no-firing-change)
- Add-branch construction at `:967` — uses `tz_to_use` (which equals `tz_name` since `self._editing is None`)

Field ordering inside each `Reminder(...)` call: match the dataclass field order (after `lead_minutes`, before `id`). Add a brief comment above the `tz_name = ...` line explaining the F3-aligned save pattern (UTC instant + IANA name together capture user wall-clock intent), and a comment near `tz_to_use` explaining the preserve-on-edit rationale (plan-review F2: prevents travel-and-rename cross-DST drift).

#### 2. Integration test

**File**: `tests/test_reminder_form_dialog.py`

**Intent**: Confirm the form save path persists tz. Mock `tzlocal.get_localzone_name` so the test is deterministic on any CI runner.

**Contract**: Add three tests pinning the Add-path capture and the Edit-path preserve/refresh semantics (per plan-review F2):

- `test_add_path_captures_os_local_tz` — `monkeypatch.setattr("break_reminder.ui.reminder_form_dialog.tzlocal.get_localzone_name", lambda: "Europe/Warsaw")`. Drive the form (no `_editing`) through `accept()`. Assert the Reminder added to the store has `tz == "Europe/Warsaw"`.

- `test_edit_path_preserves_tz_when_only_name_changed` — load an existing reminder with `tz="Europe/Warsaw"`. Monkeypatch tzlocal to return a DIFFERENT zone (e.g. `"Asia/Tokyo"`) to simulate user editing while traveling. Change only the name field. Save. Assert the resulting Reminder has `tz == "Europe/Warsaw"` (preserved, NOT refreshed). This is the travel-and-rename regression guard.

- `test_edit_path_refreshes_tz_when_firing_field_changed` — same setup as the preserve test (loaded tz="Europe/Warsaw", tzlocal mocked to "Asia/Tokyo"), but change the datetime field too. Save. Assert the resulting Reminder has `tz == "Asia/Tokyo"` (refreshed, because user restated intent by changing a firing-relevant field).

Mirror the existing form-test patterns for fixture wiring.

### Success Criteria:

#### Automated Verification:

- Form-dialog tests pass: `uv run pytest tests/test_reminder_form_dialog.py`
- All tests still pass: `uv run pytest`
- Type checking passes: `uv run pyright`
- Linting passes: `uv run ruff check`

#### Manual Verification:

- Launch the app, open the reminder form, create a new one-shot reminder, save, inspect `%APPDATA%\BreakReminder\reminders.json` — the new entry contains `"tz": "<your-local-iana>"` (e.g. `"Europe/Warsaw"`)
- Edit the same reminder (change just the name), save, re-inspect the file — `tz` is still present and matches your OS-local

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Docs + archive cleanup

### Overview

Correct the AGENTS.md DST claim to specify the IANA-name caveat; annotate the archived impl-review for grep-discoverability of the correction; update the test-plan §7 entry to mark the parked DST drift as resolved. Pure documentation phase — no code changes, no test changes.

### Changes Required:

#### 1. AGENTS.md DST claim correction

**File**: `AGENTS.md`

**Intent**: Line 88 currently says *"RRULE handles DST, month-end ('monthly on the 31st'), and end dates correctly; hand-rolled arithmetic will not."* — true ONLY when `dtstart` carries an IANA name. The R-1b bug existed precisely because `dtstart` was UTC.

**Contract**: Replace line 88 with two sentences that scope the claim:

- First sentence: state that hand-rolled daily/weekly/monthly arithmetic should be avoided.
- Second sentence: state that RRULE handles DST, month-end, and end dates correctly **when `dtstart` carries an IANA-named timezone**; against a UTC `dtstart` it produces UTC-anchored firings that drift across DST transitions (link to this change folder by relative path for grep-discoverability).

The exact wording is the implementer's choice; the load-bearing requirement is that the IANA-vs-UTC distinction is explicit and a reader following AGENTS.md cannot conclude RRULE+UTC is DST-safe.

#### 2. Archive annotation

**File**: `context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md`

**Intent** (per plan-review F7): Line 57's "DST correctness" bullet is explicitly scoped to `_local_date_to_utc_end_of_day` (the end-date conversion path), but the bullet header reads as broader when skimmed, and the "DST round-trip" phrase at line 74 is genuinely ambiguous. A future agent grepping the archive for "DST" finds both the original scoped claim AND the correction. Preserves archive integrity (one-line additive note at the bottom; no edits to the original review body) while preventing the bullet header or the ambiguous line-74 phrase from being over-read in isolation.

**Contract**: Append one paragraph at the very end of the file (no edits to existing content):

```
> **NOTE 2026-06-02**: The "DST correctness" claim above was scoped only to
> `_local_date_to_utc_end_of_day` (end-date conversion). The recurring-firing
> DST drift (R-1b) was missed and shipped with S-08; fixed in
> `context/changes/bugfix-reminder-dst-drift/`.
```

#### 3. test-plan §7 unparking

**File**: `context/foundation/test-plan.md`

**Intent**: §7 explicitly parks the DST drift item for "bugfix-reminder-dst-drift" — with the fix landed, the entry should be marked resolved (or removed if the §7 convention is to delete completed entries).

**Contract**: Update the §7 parked-entry that mentions R-1b / DST drift to note completion, linking to this change folder. Match the existing §7 convention: if other resolved items are deleted, delete; if they're left with a "RESOLVED" annotation, annotate. The implementer should read §7's existing pattern and follow it.

#### 4. change.md status update

**File**: `context/changes/bugfix-reminder-dst-drift/change.md`

**Intent**: Mark the change as ready for /10x-impl-review and eventual /10x-archive.

**Contract**: Update front-matter: `status: implemented` (or whatever the next status in the /10x change lifecycle is — implementer should check `change.md` template conventions in other recently-archived changes). Update `updated:` field.

### Success Criteria:

#### Automated Verification:

- All tests still pass: `uv run pytest` (no code changes in this phase, but defensive)
- `grep -n "DST" AGENTS.md` returns the corrected line
- `grep -n "DST" context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md` returns BOTH the original claim AND the new correction note

#### Manual Verification:

- Read AGENTS.md line 88 — the IANA vs UTC distinction is explicit
- Read the archived impl-review — the correction note is at the bottom; the original review body is untouched
- Read test-plan.md §7 — the DST drift entry shows as resolved
- Read change.md — status reflects implementation completion

**Implementation Note**: After completing this phase and all automated verification passes, the implementer should run `/10x-impl-review bugfix-reminder-dst-drift` to evaluate the implementation against this plan. After review, run `/10x-archive bugfix-reminder-dst-drift` to move the change folder to `context/archive/`.

---

## Testing Strategy

### Unit Tests:

- `_coerce_tz` behavior contract: missing field → OS-local (lazy migration); valid IANA → preserved; invalid string / wrong type / empty string / path-traversal → raises `InvalidTimezoneError` (caught by `_read` row-containment per F3)
- `Reminder` round-trip: `to_dict` emits `tz`; `from_dict` consumes `tz`; default factory uses OS-local
- `_resolve_zone` (scheduler): valid IANA → `ZoneInfo`; invalid IANA → `ZoneInfo("UTC")` + WARNING
- `next_firing_after` R-1b regression: Europe/Warsaw spring-forward 2026-03-28→29; daily reminder fires at 9:00 local on both sides of the boundary (different UTC instants)
- `next_firing_after` non-DST sanity: same `Reminder(tz="Europe/Warsaw")` in mid-June (no DST boundary); consecutive firings exactly 24h apart
- `next_firing_after` UTC identity: `Reminder(tz="UTC")` produces identical results to pre-fix behavior

### Integration Tests:

- `ReminderStore._read` row-containment with malformed `tz`: a row with `"tz": "Europe/Warsaaw"` (typo) IS DROPPED with a single WARNING naming row index + `InvalidTimezoneError`; well-formed siblings load successfully (per plan-review F3)
- Form `accept()` Add path: `tzlocal.get_localzone_name` mocked → resulting Reminder has the mocked tz
- Form `accept()` Edit path preserve: loaded `tz="Europe/Warsaw"`, mocked OS-local=`"Asia/Tokyo"`, only name changed → Reminder.tz unchanged
- Form `accept()` Edit path refresh: same setup but datetime changed too → Reminder.tz refreshes to `"Asia/Tokyo"`

### Manual Testing Steps:

1. Hand-edit `%APPDATA%\BreakReminder\reminders.json`: add `"tz": "Europe/Warsaw"` to an entry, restart app, verify it loads
2. Hand-edit the same entry to a typo'd tz (`"Europe/Warsaaw"`), restart, verify single WARNING + entry IS DROPPED (row-containment per F3); sibling rows still load
3. Create a new reminder via the form, save, inspect `reminders.json` — confirms explicit tz capture at save
4. (Time-travel-hardware permitting) Set OS clock to just before Europe/Warsaw spring-forward; create a daily 9:00 reminder; advance clock past spring-forward; verify the reminder fires at the expected local time on the post-DST day. Accept this is hard to verify on a single live machine; the automated R-1b test is the trustworthy oracle.

## Migration Notes

**Existing `reminders.json` files require no migration when the `tz` field is missing entirely** — per Q4 (default missing tz to OS-local at load time), pre-bugfix reminders load with the F3 `_coerce_tz(None) → OS-local IANA` fallback. The persisted `tz` field is written back to disk on the next user edit of that reminder (lazy persistence). For users who never edit a given reminder again, the file representation stays missing the `tz` field forever — but functionally the reminder behaves correctly post-fix because the default is applied at every load.

**Hand-edited files with an INVALID `tz` value** (typo, empty string, wrong type) are NOT silently substituted (per plan-review F3); the affected row is dropped with a WARNING. This is the only "migration risk" surface: a power-user who hand-edited a typo'd tz pre-fix would lose that one reminder post-fix and need to either remove the bad field (gets lazy-migration default) or fix the typo. Sibling well-formed rows are unaffected. This trade-off intentionally avoids the worse failure mode where a Warsaw typo silently becomes Asia/Tokyo on a Tokyo machine.

If a user is currently affected by R-1b (a recurring reminder that has visibly drifted across DST), they have two recovery paths after the fix lands:
1. Edit the reminder in the form (any change persists tz explicitly).
2. Do nothing — the reminder will fire at the correct local time on the next firing, because the F3 default uses OS-local which is what the user intended.

There is no need to walk `reminders.json` on app boot or prompt the user.

## Performance Considerations

Negligible. `ZoneInfo` construction is cheap (sub-millisecond) and `next_firing_after` is called once per reminder per scheduler tick (every few minutes). `tzlocal.get_localzone_name()` reads from the Windows registry / `/etc/localtime` once per form save — also cheap and infrequent.

`zoneinfo.ZoneInfo` instances are cached by Python (per-process, per-name), so repeated `ZoneInfo("Europe/Warsaw")` calls return the same object. No need for application-level caching.

## References

- Related research: `context/changes/bugfix-reminder-dst-drift/research.md`
- Origin research (R-1b defect identification): `context/archive/2026-06-01-testing-rrule-reminder-loop/research.md`
- Defect surface: `break_reminder/scheduler.py:362` + `:367`
- Storage invariant chokepoint: `break_reminder/storage/reminders.py:86-122` (`_coerce_aware_utc`)
- Storage coercion precedent to mirror: `break_reminder/storage/reminders.py:51-83` (`_coerce_lead_minutes`)
- Form save save-path F3 idiom: `break_reminder/ui/reminder_form_dialog.py:869-879`
- R-1b breadcrumb to remove: `tests/test_recurring_reminder_integration.py:33-41`
- AGENTS.md DST claim to correct: `AGENTS.md:88`
- Lessons rule applied: `context/foundation/lessons.md` (storage-boundary loaders need per-row containment + per-field coercion)
- Test infrastructure precedent (clock + tz injection): `tests/conftest.py` (`Clock`), `break_reminder/ui/settings_dialog.py:295` (`tz: tzinfo | None = None` injection idiom)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Storage foundation

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_reminders.py` — 0cbfb4b
- [x] 1.2 All other tests still pass: `uv run pytest` — 0cbfb4b
- [x] 1.3 Type checking passes: `uv run pyright` — 0cbfb4b
- [x] 1.4 Linting passes: `uv run ruff check && uv run ruff format --check` — 0cbfb4b
- [x] 1.5 Security audit passes: `uv run pip-audit` — 0cbfb4b
- [x] 1.6 License gate passes: `uv run pip-licenses --fail-on="AGPL"` — 0cbfb4b
- [x] 1.7 `uv.lock` refreshed and committed alongside `pyproject.toml` — 0cbfb4b
- [x] 1.8 PyInstaller smoke build with `--collect-data tzdata` succeeds and bundles tzdata data files (per F4) — 0cbfb4b

#### Manual

- [x] 1.9 Hand-edit reminders.json with valid `"tz": "Europe/Warsaw"` loads without warnings — 0cbfb4b
- [x] 1.10 Hand-edit reminders.json with typo'd tz IS DROPPED with a single WARNING (row-containment per F3); siblings preserved — 0cbfb4b
- [x] 1.11 Hand-edit reminders.json without `"tz"` key loads with OS-local default and no warnings (lazy migration) — 0cbfb4b

### Phase 2: Scheduler fix (TDD)

#### Automated

- [x] 2.1 The R-1b regression test passes: `uv run pytest tests/test_scheduler.py -k dst_drift` — 5360c11
- [x] 2.2 All scheduler tests pass: `uv run pytest tests/test_scheduler.py` — 5360c11
- [x] 2.3 All other tests still pass: `uv run pytest` — 5360c11
- [x] 2.4 The non-DST counter-test passes — 5360c11
- [x] 2.5 No xfail marks on the R-1b test: `grep -n "xfail" tests/test_scheduler.py | grep -i "dst"` returns nothing — 5360c11
- [x] 2.6 Type checking passes: `uv run pyright` — 5360c11
- [x] 2.7 Linting passes: `uv run ruff check && uv run ruff format --check` — 5360c11

#### Manual

- [x] 2.8 The R-1b test passes for the right reason (asserts post-DST instant, not pre-DST) — 5360c11
- [x] 2.9 `TODO(R-1b)` block removed from `tests/test_recurring_reminder_integration.py`; R-4 note intact — 5360c11

### Phase 3: Form integration

#### Automated

- [x] 3.1 Form-dialog tests pass: `uv run pytest tests/test_reminder_form_dialog.py` — 8221bca
- [x] 3.2 All tests still pass: `uv run pytest` — 8221bca
- [x] 3.3 Type checking passes: `uv run pyright` — 8221bca
- [x] 3.4 Linting passes: `uv run ruff check` — 8221bca

#### Manual

- [x] 3.5 Newly-created reminder via the form persists `"tz": "<os-local-iana>"` in reminders.json — 8221bca
- [x] 3.6 Editing the same reminder (rename only) PRESERVES its original tz; editing the datetime refreshes it — 8221bca

### Phase 4: Docs + archive cleanup

#### Automated

- [x] 4.1 All tests still pass: `uv run pytest` — 68ee93f
- [x] 4.2 `grep -n "DST" AGENTS.md` returns the corrected line — 68ee93f
- [x] 4.3 `grep -n "DST" context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md` returns BOTH the original claim AND the correction — 68ee93f

#### Manual

- [x] 4.4 AGENTS.md line 88 explicitly distinguishes IANA `dtstart` from UTC `dtstart` — 68ee93f
- [x] 4.5 Archived impl-review correction note is at the bottom; original review body untouched — 68ee93f
- [x] 4.6 test-plan.md §7 DST drift entry shows as resolved — 68ee93f
- [x] 4.7 change.md status reflects implementation completion — 68ee93f
