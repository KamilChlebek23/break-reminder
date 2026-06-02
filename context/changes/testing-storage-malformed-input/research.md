---
date: 2026-06-02T12:53:46+02:00
researcher: Kamil Chlebek (via Cursor)
git_commit: 5f3b662
branch: test/testing-storage-malformed-input
repository: break-reminder
topic: "R-5 storage round-trip robustness — malformed-input handling at reminders.py / settings.py / event_log.py boundaries"
tags: [research, R-5, FR-002, FR-015, storage, from_dict, parametrized, test-plan-phase-3]
status: complete
last_updated: 2026-06-02
last_updated_by: Kamil Chlebek (via Cursor)
---

# Research: R-5 storage round-trip robustness

**Date**: 2026-06-02T12:53:46+02:00
**Researcher**: Kamil Chlebek (via Cursor)
**Git Commit**: 5f3b662
**Branch**: test/testing-storage-malformed-input
**Repository**: break-reminder

## Research Question

Ground rollout **Phase 3** of `context/foundation/test-plan.md` ("Storage round-trip robustness — parametrized malformed-input"), which protects **R-5**: a user-edited or malformed-on-save `reminders.json` / `BreakReminder.ini` breaks app startup, silently drops reminders, or loses settings.

For each of `storage/reminders.py`, `storage/settings.py`, and (probe first) `storage/event_log.py`:

1. Enumerate every persisted field/key and the load-boundary classification (coerced / clamped / validated / drop-row / raw-unchecked).
2. Identify any field/key added since the §2 R-5 reference change (S-06b for reminders, S-04 for settings) whose protection lags behind.
3. Cross-reference existing test coverage against the six §2 R-5 malformed-input classes (string-where-int, missing key, out-of-range numeric, malformed RRULE, malformed ISO datetime, unknown extra key).
4. Trace where each load happens at app startup and what the user-visible failure mode is today.
5. Re-extract lessons from S-04 / S-06b / S-09 impl-reviews.

The goal is a research substrate that lets `/10x-plan` write a non-tautological behavior contract: the tests must assert observable failure modes, not "load() did not raise".

## Summary

**The dominant finding is structural, not field-level.** `ReminderStore._read()` at `break_reminder/storage/reminders.py:221-232` wraps **only the JSON parse** in `try/except (json.JSONDecodeError, OSError)`. The list comprehension `[Reminder.from_dict(item) for item in raw]` on line 232 sits **outside** the protective block. A single bad row anywhere in the list — a missing `id`, a malformed `start_at` ISO string, a wrong-type `rrule_str` — raises and aborts the whole load. The 5 well-formed reminders adjacent to one bad row all vanish from `list_all()`. This is the highest-priority Phase 3 target and it dwarfs the field-level work.

Six other findings of varying weight:

1. **No new persisted field/key has been added since either reference change.** `reminders.py`'s schema has the same 6 fields it had at S-06b's `797328d`; only `1d8d0a8` (post-S-06b) hardened `start_at`/`end_at` with `_coerce_aware_utc`. `settings.py`'s 8 keys all existed at S-04's `9307c4d`; post-S-04 commits added setters and one new upper-bound clamp (`snooze_duration_min`). The §2 R-5 "audit fields added since S-06b" lens is therefore **empirically empty** — the unprotected surface is **pre-existing** un-coerced fields that the S-06b lesson was never retroactively applied to.

2. **`event_log.py` is OUT OF SCOPE for R-5.** Strictly append-only — no `csv.reader`, no read-back path. Cross-confirmed by file inspection and cross-module search. The 13 tests in `test_event_log.py` cover append + rotation only.

3. **Two app entry points diverge on a startup storage panic.** `main.py` (PyInstaller `.exe`) wraps `_run()` in a bootstrap-error.log + `MessageBoxW` panic catch at `main.py:128-143`. `break_reminder/__main__.py` (dev `python -m break_reminder`) has no top-level catch — bare traceback on stderr. Phase 3 tests must pin which entry point they exercise; the behavior contract differs.

4. **Construction ≠ load for the three storage layers.** `EventLog()` writes the CSV header eagerly in its constructor (`break_reminder/storage/event_log.py:76-81`) — unwrapped, so an unwritable `%APPDATA%` crashes `BreakReminderApp.__init__`. `Settings()` and `ReminderStore()` are lazy — their first real I/O happens later, kicked off by `app.start()` (`break_reminder/app.py:123`).

5. **The S-06b boundary-validation lesson is NOT generalized into `lessons.md` yet.** `context/foundation/lessons.md` contains exactly one entry (Google docstrings). The `_coerce_*` boundary-protection pattern stayed in S-06b's impl-review F4 and was not promoted. Phase 3 is a strong candidate to surface it.

6. **Top-six Phase 3 test targets** (ranked by R-5 risk × current coverage gap):

   1. **Structural — `_read` row-containment.** A single bad row currently nukes the entire load. Zero coverage.
   2. **`start_at` malformed/missing** (Reminder). Today crashes through to `ReminderScheduler.start()`. Zero coverage.
   3. **`rrule_str` malformed.** By-design raw-unchecked, but the behavior on load is unpinned. Zero coverage.
   4. **`idle_threshold_sec` × out-of-range high** (Settings). Getter has lower clamp only — `max(1, ...)` at `storage/settings.py:164`. A hand-edited "999999" silently propagates into the FR-008 active-time accounting loop. Zero coverage. **No setter exists** either.
   5. **`voice_phrase.setter` × non-str-where-str** (Settings). The only **post-S-04 raw/unchecked** boundary, added in `7b3a8f8`. Zero coverage on either direction.
   6. **"Unknown extra key" class** (Settings). Untested for every key. The current implementation ignores unknown INI keys, but nothing pins that behavior as a regression net.

Three Source-column / response-guidance corrections to consider backporting to `test-plan.md` §2 R-5 (see [Open Questions](#open-questions)).

## Detailed Findings

### A. `storage/reminders.py` from_dict + `tests/test_reminders.py` coverage gap

#### A.1 — Persisted Reminder schema (6 fields)

Defined at `break_reminder/storage/reminders.py:130-141`:

| # | Field | Type | Default | JSON key | Coerce-point classification |
|---|---|---|---|---|---|
| 1 | `id` | `str` | — (required) | `"id"` | **raw/unchecked** — bare subscript `data["id"]` |
| 2 | `name` | `str` | — (required) | `"name"` | **raw/unchecked** — bare subscript `data["name"]` |
| 3 | `start_at` | `datetime` | — (required) | `"start_at"` (ISO string) | **coerced for tz-naive only** via `_coerce_aware_utc` at `break_reminder/storage/reminders.py:164-179`; the `datetime.fromisoformat` call itself is unguarded — a non-ISO string raises `ValueError` |
| 4 | `end_at` | `datetime \| None` | `None` | `"end_at"` | Same as `start_at` — coerced for tz-naive only |
| 5 | `rrule_str` | `str` | `""` | `"rrule_str"` | **raw/unchecked** — passed straight into `dateutil.rrule.rrulestr` later, which raises on malformed input |
| 6 | `lead_minutes` | `int` | `0` | `"lead_minutes"` | **coerced + clamped** via `_coerce_lead_minutes` (lines 36-72) + `_LEAD_MIN_VALUE` / `_LEAD_MAX_VALUE` constants — string-where-int → 0, out-of-range → clamp to `[0, 60]` |

`_coerce_lead_minutes` is the **only field-level helper** in the module. It maps `int → passthrough → clamp`, `str → int(...) with fallback to 0 on ValueError → clamp`, anything else → 0. Cited at `break_reminder/storage/reminders.py:36-72`.

#### A.2 — Structural finding: `_read` is load-all-or-nothing

```221:232:break_reminder/storage/reminders.py
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
        return [Reminder.from_dict(item) for item in raw]
```

The `try/except` covers **the JSON parse step only**. The list comprehension on line 232 runs outside the protective block. Per-row exceptions (`KeyError`, `ValueError`, `TypeError`) raised by `Reminder.from_dict` propagate up through `ReminderScheduler.start()` and crash the entire load. There is no per-row try/except, no log-and-drop semantic, and no test pinning this behavior.

This is the test-plan's highest-conviction Phase 3 target.

#### A.3 — "Added since S-06b" gap audit

S-06b's archive contains commit `797328d` (`chore(reminders-lead-time): impl-review report + 6 triaged fixes`). `git log --follow --since="2026-05-27" -- break_reminder/storage/reminders.py` returns:

- `1d8d0a8` — `feat(scheduler): tz-aware UTC coercion for Reminder.start_at / end_at` — added the `_coerce_aware_utc` helper at lines 164-179. Hardened existing fields; **no new field added.**
- `797328d` — S-06b's closing commit (lead-minutes coercion + retrospective).

**No persisted Reminder field has been added since S-06b.** The §2 R-5 audit lens "every field added since S-06b" is empirically empty. The unprotected surface is the **pre-existing** un-coerced fields enumerated in A.1: `id`, `name`, `start_at` (ISO parse), `end_at` (ISO parse), `rrule_str`.

#### A.4 — `tests/test_reminders.py` coverage matrix

The 36 tests cluster on `lead_minutes` and the CRUD round-trip. Rows = the 6 persisted fields; columns = the six §2 R-5 malformed-input classes. `∅` = no coverage. `—` = N/A for the type.

| Field | S→I | MK | OoR | RRULE | ISO | UEK |
|---|---|---|---|---|---|---|
| `id` | ∅ | ∅ (would raise `KeyError`) | — | — | — | ∅ |
| `name` | ∅ | ∅ (would raise `KeyError`) | — | — | — | ∅ |
| `start_at` | — | ∅ (would raise `KeyError`) | — | — | ∅ (would raise `ValueError`) | ∅ |
| `end_at` | — | covered: optional default-`None` round-trip | — | — | ∅ (would raise `ValueError`) | ∅ |
| `rrule_str` | — | covered: default-`""` round-trip | — | ∅ (raw passthrough; raises later in rrulestr) | — | ∅ |
| `lead_minutes` | covered: `TestCoerceLeadMinutes::test_string_coerces_to_int` etc. | covered: `test_missing_key_defaults_to_zero` | covered: 4 clamp invariants (passthrough / type / lower / upper) | — | — | ∅ |

The matrix shows the asymmetry: `lead_minutes` is **fully** parametrized (the canonical S-06b lesson landed). Every other field is **structurally** unpinned (a single malformed row crashes the whole load — see A.2 — so there's nothing for a field-level test to assert in isolation).

#### A.5 — Malformed-input class applicability per field

| Field | Applicable §2 R-5 classes |
|---|---|
| `id` | missing key; wrong-type (int instead of str); unknown extra key (whole-record axis) |
| `name` | missing key; wrong-type; UEK |
| `start_at` | missing key; malformed ISO datetime; tz-naive (orthogonal — already handled by `_coerce_aware_utc`); UEK |
| `end_at` | malformed ISO datetime; tz-naive; UEK |
| `rrule_str` | malformed RRULE; wrong-type (int instead of str); UEK |
| `lead_minutes` | string-where-int (covered); out-of-range (covered); missing key (covered); UEK |

The "one bad row among many" axis applies to every field via the structural finding in A.2 — that's the Phase 3 backbone.

### B. `storage/settings.py` clamp/load + `tests/test_settings.py` coverage gap

#### B.1 — Persisted Settings keys (8 keys via `_Keys` at `break_reminder/storage/settings.py:58-66`)

Defaults at `break_reminder/storage/settings.py:46-52`; range constants at `:21-42`.

| # | Key string | Type | Default | Range | Getter | Setter |
|---|---|---|---|---|---|---|
| 1 | `scheduling/break_interval_min` | `int` | `60` | `[1, 240]` | **clamped** (lines 131-135) | **validated/raised** (lines 137-159) |
| 2 | `scheduling/idle_threshold_sec` | `int` | `60` | `[1, ∞)` — **no upper bound** | **clamped lower-only** (lines 161-164) | **NONE — no setter exists** |
| 3 | `scheduling/snooze_duration_min` | `int` | `5` | `[1, 30]` | **clamped** (lines 166-170) | **validated/raised** (lines 172-194) |
| 4 | `scheduling/max_snoozes` | `int` | `1` | `[0, 5]` | **clamped** (lines 196-200) | **validated/raised** (lines 202-223) |
| 5 | `notifications/voice_enabled` | `bool` | `False` | — | **defaulted/coerced** via `_get_bool` (lines 225-228) | **coerced** `bool(value)` (lines 230-240) |
| 6 | `notifications/voice_phrase` | `str` | `"Time to take a break"` | — | **defaulted/coerced** via `_get_str` (lines 242-245) | **raw/unchecked** — straight-write (lines 247-272, docstring at 260-266 documents the round-trip surprise) |
| 7 | `lifecycle/autostart` | `bool` | `False` | — | **defaulted/coerced** via `_get_bool` (lines 274-277) | **coerced** (lines 279-301) |
| 8 | `lifecycle/paused` | `bool` | `False` | — | **defaulted/coerced** via `_get_bool` (lines 303-306) | **coerced** (lines 308-321) |

Three generic shape-coercion helpers at `break_reminder/storage/settings.py:101-127`:

- `_get_int(key, default)` — `int`/`str` → `int(value)` with `ValueError → default`; **any other type returns `default`**.
- `_get_bool(key, default)` — `bool` → passthrough; `str` → `True` iff lowercased in `{"true","1","yes","on"}`; **anything else falls through to `bool(value)`** (truthy semantics, possibly surprising).
- `_get_str(key, default)` — `str(value)` if not `None`, else `default`.

There are **no named `_clamp_*` / `_coerce_*` helpers** specific to a key — clamping is inline in each getter via `max(...)` / `min(...)`.

#### B.2 — "Added since S-04" gap audit

S-04 archive: `context/archive/2026-05-25-settings-break-interval/`. Closing commit `9307c4d` (`fix(settings-break-interval): fixes after review`). `git log --follow --since="2026-05-25" --oneline -- break_reminder/storage/settings.py`:

| SHA | Subject | Effect on persisted schema |
|---|---|---|
| `e9f2ff0` | `feat(settings-autostart-toggle): wire FR-003 Lifecycle tab + Run-key writes (p1)` | Added `autostart.setter` (coerced). **No new key.** |
| `fc0f6b3` | `feat(settings-snooze-config): scheduling-tab snooze fields + snooze-aware tray tooltip + automated coverage (p1)` | Added `SNOOZE_DURATION_*` + `MAX_SNOOZES_*` range constants; promoted `snooze_duration_min` getter from `max(1, …)` to full `[1, 30]` clamp (**the only new upper-bound clamp post-S-04**); added validating setters for both. **No new key.** |
| `6be99ed` | `refactor(settings-voice-toggle): impl-review report + 6 triaged fixes` | Triage refactor following voice-toggle review. **No new key.** |
| `7b3a8f8` | `feat(settings-voice-toggle): notifications tab + voice setters + automated coverage (p1)` | Added `voice_enabled.setter` (coerced) and `voice_phrase.setter` (raw/unchecked). **No new key.** |
| `9307c4d` | S-04 closing commit. | — |

**All 8 current `_Keys` entries already existed at S-04 close.** No persisted key added post-S-04. The §2 R-5 audit lens "clamp helpers added since S-04" lands on the new upper-bound clamp for `snooze_duration_min` (already tested) and the new setters (mostly tested). The unprotected post-S-04 surface is:

- **`voice_phrase.setter`** (lines 247-272, added in `7b3a8f8`) — the **only** post-S-04 raw/unchecked boundary. Docstring at lines 260-266 explicitly documents that a non-str value would round-trip via `_get_str(str(...))`, with no setter-side coercion. Untested.

#### B.3 — `tests/test_settings.py` coverage matrix

54 tests across 10 classes. Rows = persisted keys; columns = applicable R-5 malformed-input classes (RRULE column dropped — no RRULE-bearing Settings key). `∅` = gap.

| Key | S→I | MK | OoR | ISO | UEK |
|---|---|---|---|---|---|
| `break_interval_min` | `TestValidation::test_getter_falls_back_when_value_unparseable` | `TestDefaults::test_break_interval_default` | `TestValidation::test_getter_clamps_corrupt_high_value` + `_low_value` | — | ∅ |
| `idle_threshold_sec` | ∅ | `TestDefaults::test_idle_threshold_default` | ∅ (no upper clamp) | — | ∅ |
| `snooze_duration_min` | `TestSnoozeValidation::test_snooze_duration_getter_falls_back_when_unparseable` | `TestDefaults::test_snooze_duration_default` | `TestSnoozeValidation::test_snooze_duration_getter_clamps_corrupt_high_value` + `_low_value` | — | ∅ |
| `max_snoozes` | `TestSnoozeValidation::test_max_snoozes_getter_falls_back_when_unparseable` | `TestDefaults::test_max_snoozes_default` | `TestSnoozeValidation::test_max_snoozes_getter_clamps_corrupt_high_value` + `_low_value` | — | ∅ |
| `voice_enabled` | `TestBoolCoercion::test_non_truthy_strings_read_as_false[…]` (only via `_Keys.VOICE_ENABLED`) | `TestDefaults::test_voice_disabled_by_default` | — | — | ∅ |
| `voice_phrase` | ∅ (no test for non-str on read; setter is raw) | `TestDefaults::test_voice_phrase_default` | — | — | ∅ |
| `autostart` | ∅ (`TestBoolCoercion` is wired only against `voice_enabled`) | `TestDefaults::test_autostart_disabled_by_default` | — | — | ∅ |
| `paused` | ∅ (same as `autostart`) | `TestDefaults::test_paused_false_by_default` | — | — | ∅ |

#### B.4 — Top Settings gaps (ranked)

1. **`idle_threshold_sec` × OoR-high** — no upper clamp at all, no setter, no test. A hand-edited "999999" propagates into the FR-008 active-time accounting loop, silently breaking the Primary Success Criterion.
2. **`voice_phrase.setter` × non-str** — only post-S-04 raw/unchecked boundary; behavior unpinned in either direction.
3. **"Unknown extra key" class** — no test enumerates the behavior of an INI file containing a key Settings doesn't know about. Current implementation silently ignores them; that's the right behavior but it's not pinned.
4. **`autostart` / `paused` × bool-coercion** — `TestBoolCoercion`'s 13 parametrized cases are wired only against `voice_enabled`. A future per-key divergence would silently regress one of them.
5. **`idle_threshold_sec` × S→I** — `_get_int`'s fallback branch is exercised for every other int key but not this one.

#### B.5 — `event_log.py` is OUT OF SCOPE for R-5

Evidence: the module imports only `csv` (no `csv.reader`); `record()` opens with mode `"a"` (`break_reminder/storage/event_log.py:73-74`); `_ensure_header()` opens with mode `"w"` (line 80) for seeding but never reads; `_rotate_if_needed()` does `Path.rename` + fresh `"w"` open (lines 83-95). No public method, private helper, or module-level function reads the CSV back into Python. Cross-module search confirms only **writers** import from `event_log` (call sites at `break_reminder/app.py:37, 98, 390, 458, 472`). The 13 tests in `tests/test_event_log.py` cover append + rotation only; the test file defines a local `_read_rows` helper at lines 36-38 using `csv.reader`, but this is a test-side inspection tool, not a production read path.

R-5 requires a load boundary. `event_log.py` has none. Phase 3 omits it; the test-plan §3 row 3 "named modules" wording (`storage/reminders.py + storage/settings.py`) was correct after all.

### C. App startup load + historical impl-review lessons

#### C.1 — Storage construction inside `BreakReminderApp.__init__`

```95:100:break_reminder/app.py
        self._settings = settings if settings is not None else Settings()
        self._settings.clear_paused_on_reboot()

        self._event_log = event_log if event_log is not None else EventLog()
        self._reminder_store = reminder_store if reminder_store is not None else ReminderStore()
        self._voice = voice if voice is not None else VoiceNotifier()
```

No `try/except`. `main()` invokes the constructor with no wrapper:

```551:553:break_reminder/app.py
    app = BreakReminderApp(qt_app)
    app.start()
    return qt_app.exec()
```

#### C.2 — When each layer actually touches disk

The critical distinction: **construction is not load.**

| Layer | First disk I/O | Construction-time? | Wrapped? |
|---|---|---|---|
| `Settings()` | Lazy. `QSettings(path, IniFormat)` at `storage/settings.py:99` opens but does not parse keys; the first key access (and the `clear_paused_on_reboot()` `remove()` call at `app.py:96`) is the first read. | No | No `try/except` in `Settings`; defaults return from `_get_int`/`_get_bool`/`_get_str` on any unexpected type. |
| `EventLog()` | **Eager.** Constructor calls `_ensure_header()` (`storage/event_log.py:56`), which probes existence/size and writes the CSV header. | **Yes — write-on-construct.** | No `try/except`. An `OSError` (unwritable `%APPDATA%`, missing parent, locked file) propagates straight out of `BreakReminderApp.__init__`. |
| `ReminderStore()` | Lazy. Constructor stores path + lock (`storage/reminders.py:185-193`). First read via `ReminderScheduler.start() → reload() → _compute_next() → _read()`, kicked off by `app.start()` at `break_reminder/app.py:123`. | No (deferred to `app.start()`) | Yes, but only for `json.JSONDecodeError, OSError` — see A.2 for the structural gap. |

#### C.3 — Two entry points diverge on a startup panic

`break_reminder/__main__.py` (used by `python -m break_reminder`) has no catch:

```14:15:break_reminder/__main__.py
if __name__ == "__main__":
    sys.exit(main())
```

`main.py` (the PyInstaller entry shim) wraps `_run()` in a last-resort handler that writes the traceback to `%APPDATA%\BreakReminder\bootstrap-error.log` and pops a `MessageBoxW`:

```128:143:main.py
if __name__ == "__main__":
    try:
        sys.exit(_run())
    except Exception:  # noqa: BLE001 -- top-level last-resort handler
        # SystemExit / KeyboardInterrupt derive from BaseException, so
        # they fall through this handler unchanged (intended).
        log_path = _bootstrap_error_log_path()
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
                f.write("\n")
        except Exception:  # noqa: BLE001 -- logging is best-effort
            pass
        _show_panic_box(f"{_APP_NAME} failed to start.\n\nSee: {log_path}")
        sys.exit(1)
```

A storage exception in production (PyInstaller `.exe` → `main.py`) is observable as a panic dialog + log file. In dev (`python -m break_reminder` → `__main__.py`) it surfaces as a bare traceback on stderr and a non-zero exit. The two paths diverge — Phase 3 tests must be explicit about which entry point they exercise. The unit-test layer (no Qt event loop, no entry point) sidesteps this entirely; the behavior contract is "the raise happens at the boundary the test calls".

#### C.4 — Today's user-visible failure mode (per scenario)

Conclusions drawn from C.1–C.3, no runtime probing:

| Scenario | Observable behavior today |
|---|---|
| `reminders.json` missing | Silent — `_read()` returns `[]` at `storage/reminders.py:222-223`. Scheduler arms nothing. No log entry. |
| `reminders.json` is `{` (unparseable JSON) | Silent data loss — `_read()` returns `[]` on `json.JSONDecodeError`. User loses every reminder. No log, no dialog. |
| 3 reminders, one with `"lead_minutes": "abc"` | All three load and arm correctly — `_coerce_lead_minutes` clamps `"abc"` → `0`. No loss. |
| 3 reminders, one with `"start_at": "not-a-date"` | **All three reminders are lost.** The list comprehension at `storage/reminders.py:232` raises `ValueError` on the bad row. Propagates through `ReminderScheduler.start()`. Under PyInstaller: panic dialog + `bootstrap-error.log`. Under dev: bare traceback. This is the dominant Phase 3 target. |
| `BreakReminder.ini` has `break_interval_minutes = 99999` | Silent clamp to `240` via `min(240, max(1, 99999))` at `storage/settings.py:135`. No log, no dialog. |
| `BreakReminder.ini` has `voice_enabled = "yes"` | `_get_bool` returns `True` because `"yes"` is in the whitelist. **Not** strictly malformed. A truly wrong-shape value like `voice_enabled = "maybe"` returns `True` too via `bool("maybe")` — possibly surprising but currently un-asserted. |

#### C.5 — Historical impl-review lessons

##### S-06b reminders-lead-time — F4 (the canonical retrospective)

Path correction: the §2 R-5 source cites `2026-05-27-reminders-lead-time/reviews/impl-review.md`, but the actual file is `impl-review-phase-1.md`. There is no Phase-2 review.

`context/archive/2026-05-27-reminders-lead-time/reviews/impl-review-phase-1.md:84-92` — **F4 — Unvalidated `lead_minutes` on disk read**:

> *"`lead_minutes=data.get("lead_minutes", 0)` accepts whatever the JSON gives — a hand-edited file with `-5`, `9999`, or `"ten"` loads silently; the string case later crashes inside `timedelta(minutes=...)`. Consistent with the project's 'trust the file in `%APPDATA%`' stance (FR-015 documents the file as Notepad-editable; `start_at` ISO parsing also doesn't range-check)."*

Decision: FIXED in the same review — `_LEAD_MIN_VALUE` / `_LEAD_MAX_VALUE` constants + `_coerce_lead_minutes(raw)` helper, with `TestCoerceLeadMinutes` (9 tests pinning passthrough / type / lower / upper invariants).

**Important corollary the review explicitly leaves unfixed:** *"`start_at` ISO parsing also doesn't range-check"*. The same boundary-validation lesson was identified for `start_at` and was **not applied**. This is the exact gap Phase 3 inherits.

**One-line lesson:** Storage `from_dict` is the boundary; every hand-editable field needs a `_coerce_*` helper that maps any input to a safe value, and the helper itself must have parametrized unit tests for the four invariants (passthrough / type coercion / lower clamp / upper clamp).

##### S-01 settings-break-interval — F5 (shared bounds constants)

Naming correction: the test-plan §2 R-5 calls this "S-04"; the archive review header says **S-01** (`context/archive/2026-05-25-settings-break-interval/reviews/impl-review.md:2`). Same change, different label.

`context/archive/2026-05-25-settings-break-interval/reviews/impl-review.md:80-88` — **F5**:

> *"Three independent declarations of the FR-006 [1, 240] range: Settings.break_interval_min getter/setter clamp, the settings_dialog.py module constants, and the plan text. A future loosening (e.g., to [1, 480]) needs three coordinated edits — drift-prone."*

**One-line lesson:** Bounds for clamped settings must live as named constants (`BREAK_INTERVAL_MIN_MINUTES` / `..._MAX_MINUTES`) in `storage/settings.py` and be re-imported by the UI; the clamp lives in the getter, validation (`ValueError`) in the setter. This is the architectural shape now repeated for `break_interval`, `snooze_duration`, `max_snoozes` at `storage/settings.py:21-42`.

##### S-09 bugfix-break-cycle-reset-on-save

`context/archive/2026-05-28-bugfix-break-cycle-reset-on-save/reviews/impl-review.md` — APPROVED, 0 findings. Pure scheduler state — not relevant to R-5.

##### `context/foundation/lessons.md` scan

One entry only — Google-style docstrings. **No storage-boundary lesson has been generalized into `lessons.md`.** The S-06b `_coerce_lead_minutes` insight stayed in the impl-review. This matches the test-plan §2 R-5 source line ("lesson surfaced AT impl-review, not plan-time"). Phase 3 is a candidate to produce a `lessons.md` entry.

## Code References

Reminders boundary:
- `break_reminder/storage/reminders.py:36-72` — `_coerce_lead_minutes` (the only field-level helper; the canonical lesson)
- `break_reminder/storage/reminders.py:130-141` — `Reminder` dataclass (6 persisted fields)
- `break_reminder/storage/reminders.py:164-179` — `_coerce_aware_utc` (tz hardening added post-S-06b)
- `break_reminder/storage/reminders.py:185-193` — `ReminderStore.__init__` (lazy — no eager I/O)
- `break_reminder/storage/reminders.py:221-232` — `ReminderStore._read` (**the structural gap**: try/except wraps JSON parse only; list comprehension is unprotected)

Settings boundary:
- `break_reminder/storage/settings.py:21-42` — named bounds constants (the S-01 F5 pattern)
- `break_reminder/storage/settings.py:46-52` — `DEFAULT_*` constants
- `break_reminder/storage/settings.py:58-66` — `_Keys` (the 8 persisted INI keys)
- `break_reminder/storage/settings.py:101-127` — `_get_int` / `_get_bool` / `_get_str` (generic shape-coercion helpers)
- `break_reminder/storage/settings.py:161-164` — `idle_threshold_sec` getter (**lower-clamp only; no upper bound, no setter**)
- `break_reminder/storage/settings.py:247-272` — `voice_phrase.setter` (**only post-S-04 raw/unchecked boundary**)

App entry + startup:
- `break_reminder/app.py:95-100` — `BreakReminderApp.__init__` storage construction (no `try/except`)
- `break_reminder/app.py:123` — `app.start()` → `ReminderScheduler.start()` → first `_read` call
- `break_reminder/app.py:551-553` — `main()` (no wrapping)
- `break_reminder/__main__.py:14-15` — dev entry point (no top-level catch)
- `main.py:128-143` — PyInstaller entry shim (bootstrap-error.log + `MessageBoxW` panic catch)

Event log:
- `break_reminder/storage/event_log.py:73-74` — `record()` write (`"a"` mode)
- `break_reminder/storage/event_log.py:76-81` — `_ensure_header` write (`"w"`; eager at construction)
- `break_reminder/storage/event_log.py:83-95` — `_rotate_if_needed` (no read path)

Existing tests:
- `tests/test_reminders.py` — 36 tests; `TestCoerceLeadMinutes` is the only parametrized malformed-input cluster
- `tests/test_settings.py` — 54 tests; `TestBoolCoercion` at `:453-472` only against `voice_enabled`; `TestSnoozeValidation` at `:268-364` covers two snooze keys; "unknown extra key" axis untested
- `tests/test_event_log.py:36-38` — `_read_rows` test-side helper using `csv.reader` (not part of production)

## Architecture Insights

1. **The Settings clamp triple is the project's pattern for protected numeric keys.** Introduced in S-01: `(named bounds constants in storage/settings.py, getter clamp via max/min, setter raise via ValueError)`. Re-imported by `ui/settings_dialog.py` so UI and storage cannot drift. Now used for `break_interval`, `snooze_duration`, `max_snoozes`. **`idle_threshold_sec` is the only int Settings key that escaped this pattern** — partial getter clamp, no upper bound, no setter, no shared constants.

2. **The Reminders coerce pattern is incomplete.** S-06b's `_coerce_lead_minutes` is the only field-level helper in `storage/reminders.py`. The S-06b review explicitly anticipated extending it to `start_at` and chose not to. The Phase 3 work has two valid directions: (a) write the test that asserts today's crash behavior as a regression net (deliberately not fixing), or (b) write the test for the desired drop-row-with-log behavior, then implement that in scope. The plan must pick one.

3. **The two entry points are a deliberate boundary.** `main.py` is the production safety net (panic dialog so a non-technical user has something to act on). `__main__.py` is dev — the bare traceback is the feature, not a bug. Phase 3 unit tests don't hit either; they test the storage modules directly.

4. **Construction-time I/O is a footgun.** `EventLog()` writes on construction. If `%APPDATA%\BreakReminder\` is unwritable (locked file, permissions, mid-PyInstaller-update), `BreakReminderApp.__init__` raises. This is currently NOT tested. It's adjacent to R-5 but technically a different class of failure — out of Phase 3 scope unless plan-time decides otherwise.

5. **The "unknown extra key" axis is implicitly safe.** Both `_read()` (reminders) iterates `raw` and only touches keys named in `from_dict`; `QSettings` reads only registered key names. An unknown key is ignored on both sides — but this safety is not pinned by a test, and a future refactor (e.g. `set(data.keys()) <= EXPECTED_KEYS` check) could turn it into a hard error without warning.

## Historical Context (from prior changes)

- `context/archive/2026-05-27-reminders-lead-time/reviews/impl-review-phase-1.md:84-92` — F4: the canonical `_coerce_lead_minutes` retrospective. Explicitly notes `start_at` ISO parsing was left unfixed.
- `context/archive/2026-05-25-settings-break-interval/reviews/impl-review.md:80-88` — F5: the shared bounds-constants pattern (`BREAK_INTERVAL_MIN/MAX_MINUTES` re-imported by UI).
- `context/archive/2026-05-28-bugfix-break-cycle-reset-on-save/reviews/impl-review.md` — APPROVED, 0 findings. Scheduler state only; not relevant.
- `context/foundation/lessons.md` — one entry (Google docstrings). No storage-boundary lesson generalized yet; Phase 3 is a candidate.

## Related Research

- `context/archive/2026-06-02-testing-modal-stacking-wedge/research.md` — R-2 wedge research (different risk; same rollout series).
- `context/archive/2026-05-31-testing-rrule-reminder-loop/research.md` (if present) — R-1 RRULE research, established the virtual-clock / pytest-qt harness Phase 3 inherits the test infrastructure shape from. (Phase 3 is **pure-function unit tests; no Qt event loop**, so the harness is not directly reused, but the test-organization conventions are.)

## Open Questions

1. **Backport candidate — Source-column path typo (§2 R-5).** The test-plan cites `2026-05-27-reminders-lead-time/reviews/impl-review.md`; the actual file is `impl-review-phase-1.md`. Minor — surface during the next `/10x-test-plan` post-research backport check.

2. **Backport candidate — Naming discrepancy (§2 R-5).** The test-plan calls settings-break-interval "S-04"; the archive review header says **S-01**. Same change, different label. Pick one.

3. **Backport candidate — Response-guidance refinement (§2 R-5).** The "Must challenge" cell says *"enumerate every coerce-point and verify coverage for every field added since S-06b; audit storage/settings.py clamp helpers added since S-04"*. Research confirmed **no new field has been added to either schema** since the cited reference changes. The audit lens is empirically empty. The actual unprotected surface is (a) **pre-existing** un-coerced reminders fields, (b) **structural** `_read` row-containment, and (c) the **post-S-04 raw `voice_phrase.setter`** + **`idle_threshold_sec`'s missing upper clamp**. Worth rewording the cell so future re-reads of the test plan don't chase the "new-field" framing.

4. **Plan-time decision — `_read` row-containment direction.** Phase 3's test for the structural gap can either (a) pin today's crash-the-whole-load behavior as a regression net (no production change), or (b) write the test for the desired drop-row-with-log semantic, then implement that in scope (production change). `/10x-plan` will pick — both are defensible. Same question applies to `start_at` malformed-ISO and missing-required-key cases.

5. **Plan-time decision — entry-point coupling.** The unit-test layer sidesteps the `main.py` vs `__main__.py` panic divergence. But if Phase 3 wanted to assert "an unparseable INI panics the user dialog, doesn't silently swallow," that becomes an integration test (Phase 4 territory). Confirm Phase 3 stays at the unit boundary and Phase 4 picks up the entry-point integration if needed.

6. **`event_log.py` re-affirmation.** Research confirms it has no read path → out of scope. If the project ever grows a "view recent events in the tray menu" feature, this calls for a re-research at that time.
