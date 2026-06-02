---
date: 2026-06-02T20:58:00+02:00
researcher: Chlebek, Kamil
git_commit: cd24605a3918430b12a548aecba8f774ed74e804
branch: fix/docs-landing-nav
repository: break-reminder
topic: "Ground `bugfix-reminder-dst-drift` — confirm R-1b defect at HEAD, map blast radius, surface fix-shape options"
tags: [research, bugfix, scheduler, reminder, rrule, dst, fr-014, r-1b, storage-invariant, timezone]
status: complete
last_updated: 2026-06-02
last_updated_by: Chlebek, Kamil
---

# Research: Ground `bugfix-reminder-dst-drift` — confirm R-1b defect at HEAD, map blast radius, surface fix-shape options

**Date**: 2026-06-02T20:58:00+02:00
**Researcher**: Chlebek, Kamil
**Git Commit**: `cd24605a3918430b12a548aecba8f774ed74e804`
**Branch**: `fix/docs-landing-nav`
**Repository**: `break-reminder`

## Research Question

Ground the `bugfix-reminder-dst-drift` change. The R-1b research artifact at [`context/archive/2026-06-01-testing-rrule-reminder-loop/research.md`](../../archive/2026-06-01-testing-rrule-reminder-loop/research.md) (commit `275bf032`, written 2026-06-01 during the R-1 test rollout) analyzed the defect and named two candidate fix shapes. This research re-grounds those findings at current HEAD after four subsequent rollouts (R-2 modal-stacking, R-5 storage malformed-input, R-4 e2e flows, plus the docs site + impl-review fix-ups) and answers four questions `/10x-plan` will need:

1. **Is R-1b still accurate at HEAD?** Or has the surface shifted under us?
2. **What's the precise blast radius?** Every site `Reminder(...)` is constructed.
3. **What timezone infrastructure already exists?** Imports, Settings keys, UI affordances, established patterns.
4. **What's the real fix-shape decision space?** R-1b named two options; what does a fresh look surface?

## Summary

R-1b's defect claim survives intact at HEAD; the planning surface is the same as 2026-06-01 with one adjacent improvement.

- **R-1b defect is reproducible today** at `break_reminder/scheduler.py:362` + `:367` (unchanged byte-for-byte from R-1b). A "Daily 9:00 Europe/Warsaw" reminder stored as `08:00 UTC` (CET) silently fires at `10:00 local` after spring-forward.
- **Blast radius is bounded and well-shaped**: 5 production construction sites + 55 test sites + 7 inline dict literals + 0 JSON fixture files. Zero tests use whole-instance `Reminder` equality, so migration is mechanical (add a `tz=` kwarg / `_coerce_*` helper) rather than semantic (no implicit "expected zone" to re-decide per assertion).
- **The codebase has ZERO existing timezone infrastructure beyond `UTC`**: no `dateutil.tz`, no `zoneinfo`, no `pytz`, no Settings tz key, no UI tz affordance. The single established DST-correct pattern is `naive.astimezone(UTC)` at the form save path ([`reminder_form_dialog.py:879`](../../../break_reminder/ui/reminder_form_dialog.py)) — landed via impl-review F3 during S-08.
- **The "option (a) vs option (b)" framing from R-1b is incomplete.** `datetime.isoformat()` emits an offset (`+01:00`), not an IANA name (`Europe/Warsaw`), so option (a) cannot round-trip the zone identity through `to_dict` / `from_dict` without a sibling `tz` field anyway. Both R-1b options converge on `start_at + tz: str` on disk. A previously-unnamed **option (c)** surfaced — keep `start_at` as tz-aware UTC (storage invariant unchanged) and add a scheduler-only `tz: str` field consumed only when building `dtstart` for `rrulestr` — has the smallest blast radius of the three.
- **Critical gotcha applies to every option**: `dateutil.tz.gettz("Europe/Warsaaw")` (typo) returns `None` silently. A `None` `tzinfo` would crash `_compute_next`'s tz-aware comparison — exactly the failure mode `_coerce_aware_utc` was built to prevent. Whatever option ships needs a `_coerce_tz` helper paralleling `_coerce_lead_minutes` per [`lessons.md`'s storage-boundary rule](../../foundation/lessons.md).

Implication for `/10x-plan`: the design space narrows to three options whose tradeoffs are well-characterized below. The remaining unknowns are user-facing UX (does the form get a TZ picker, or always use system-local?) and runtime portability (does `dateutil.tz.gettz()` work on Windows 11 without bundling tzdata?) — both surfaced as Open Questions.

## Detailed Findings

### § 1 — Defect surface at HEAD (R-1b confirmed)

Every line number cited in R-1b's defect analysis resolves identically at HEAD:

- `break_reminder/scheduler.py:362` — `rule = rrulestr(reminder.rrule_str, dtstart=start)` (the firing-rule construction with a UTC `dtstart`)
- `break_reminder/scheduler.py:367` — `nxt = rule.after(now, inc=False)` (the next-firing-instant math, in UTC space)
- `break_reminder/scheduler.py:376-380` — `_ensure_aware()` helper (treats naive datetimes as UTC, lenient-read contract)
- `break_reminder/storage/reminders.py:127-139` — `Reminder` dataclass invariant docstring (entrenches the tz-aware UTC contract on `start_at`/`end_at`)
- `break_reminder/ui/reminder_form_dialog.py:879` — `event_at_utc = naive_local.astimezone(UTC)` (DST-correct per-instant save, but collapses the user's local-time intent before storage)

The reproduction scenario in R-1b §R-1b ("Worked example, Europe/Warsaw spring-forward March 28→29 2026") still applies verbatim. A failing test that pins this defect would belong in [`tests/test_scheduler.py`](../../../tests/test_scheduler.py) (per the `TODO(R-1b)` breadcrumb at [`tests/test_recurring_reminder_integration.py:33-41`](../../../tests/test_recurring_reminder_integration.py)).

### § 2 — Codebase delta since R-1b (one adjacent improvement, defect unchanged)

R-5 (`testing-storage-malformed-input`, commit `2bab8e9`) hardened the storage boundary but did not touch the recurrence semantics:

- `break_reminder/storage/reminders.py:86-122` — `_coerce_aware_utc()` helper expanded (now handles tz-stripped hand-edits like `"2026-03-28T09:00:00"` without `+00:00`)
- `break_reminder/storage/reminders.py:175` — `from_dict` now wraps the `start_at` parse in `_coerce_aware_utc`
- `break_reminder/storage/reminders.py:185` — same for `end_at`
- `break_reminder/storage/reminders.py:232-277` — `ReminderStore._read()` gained an `isinstance(raw, list)` top-level guard (line 247) and per-row `try/except` (line 259) — the R-5 row-containment fix

These changes **strengthen** the UTC invariant; they don't change the bug's blast radius. `_coerce_aware_utc` is the chokepoint to extend when shipping the fix — whichever option wins, the load path's tz semantics flow through this helper.

Impl-review F3 (during S-08 retrospective) replaced an older `datetime.now().astimezone().tzinfo` + `.replace()` save idiom with `naive_local.astimezone(UTC)` at `reminder_form_dialog.py:879` and added the explanatory comment block at lines 869-878. This is the codebase's anointed DST-correct write pattern; whatever the bugfix does on the load side should align with this established convention.

Test coverage gap unchanged from R-1b: [`tests/test_scheduler.py`](../../../tests/test_scheduler.py) (8 tests), [`tests/test_reminders.py`](../../../tests/test_reminders.py) (51 tests), and [`tests/test_reminder_scheduler.py`](../../../tests/test_reminder_scheduler.py) (11 tests) collectively contain **zero** DST / `ZoneInfo` / `Europe/Warsaw` assertions. Every datetime in these files uses `tzinfo=UTC`, which has no DST.

### § 3 — Blast radius (Reminder constructor sites)

Total: **60 sites** — 5 production + 55 test, plus 7 inline dict literals.

**Production (5 sites):**

- `break_reminder/ui/reminder_form_dialog.py:936` — Add-flow construction (new reminder)
- `break_reminder/ui/reminder_form_dialog.py:958` — Edit-flow construction (existing reminder, recurrence subset)
- `break_reminder/ui/reminder_form_dialog.py:967` — Edit-flow construction (existing reminder, full-edit branch)
- `break_reminder/storage/reminders.py:261` — `Reminder.from_dict(raw)` call inside `ReminderStore._read()`
- `break_reminder/storage/reminders.py:281` — `r.to_dict()` call inside `ReminderStore._write()`

No `dataclasses.replace(reminder, ...)` usage anywhere — every "modified Reminder" path goes through the form's Add/Edit construction.

**Tests (55 sites across 6 files):**

| File | Sites |
|---|---|
| `tests/test_settings_dialog.py` | 27 |
| `tests/test_reminder_scheduler.py` | 12 |
| `tests/test_reminders.py` | 8 (plus the 7 dict literals) |
| `tests/test_recurring_reminder_integration.py` | 4 |
| `tests/test_reminder_form_dialog.py` | (factory `_make_reminder` absorbs most) |
| `tests/test_scheduler.py` | 4 |

Two factory helpers absorb most of the repetitive construction: `_make_reminder` in `tests/test_reminder_form_dialog.py` and `make_reminder` in another test module. Migrating these two factories first cuts the per-site count roughly in half before touching individual test bodies.

**Inline dict literals (7 sites — hand-editable JSON shape):**

All in `tests/test_reminders.py`, used to feed `Reminder.from_dict` directly. The `+00:00`-stripped hand-edit test at `tests/test_reminders.py:666` pins `_coerce_aware_utc`'s lenient-read contract and is the most concentrated cluster of "tz invariant under attack" behavior. No `.json` fixture files exist in the repo — all reminder shapes are inline.

**Test "expected = Reminder(...)" assertion sites:** **0.** Tests compare on individual fields (`r.start_at == expected_dt`, `r.name == "daily"`), never on whole-instance equality. This means migration cost is purely mechanical (add a `tz=...` kwarg or `_coerce_tz` helper) and carries no implicit "expected timezone" semantics that would need to be re-decided per assertion. This is the most encouraging single finding for the migration's tractability.

### § 4 — Timezone infrastructure today (zero IANA, one DST pattern)

The audit found **no existing IANA timezone infrastructure** anywhere in the codebase:

- **Imports**: Production code uses `from datetime import UTC, datetime` exclusively. Zero `dateutil.tz`, zero `zoneinfo`, zero `pytz`, zero `gettz`. Tests add `datetime.timezone` for fixed-offset injection but no named zone.
- **Settings keys** ([`break_reminder/storage/settings.py:58-66`](../../../break_reminder/storage/settings.py)): `BREAK_INTERVAL_MIN`, `IDLE_THRESHOLD_SEC`, `SNOOZE_DURATION_MIN`, `MAX_SNOOZES`, `VOICE_ENABLED`, `VOICE_PHRASE`, `AUTOSTART`, `PAUSED`. **No timezone / locale key.**
- **UI affordances**: scanned `break_reminder/ui/` + `break_reminder/notifications/`. **Zero timezone widgets.** Only `QDateTimeEdit` / `QDateEdit` (naive-local capture).

The codebase has **one** established DST-correct pattern, the `naive.astimezone(UTC)` per-instant idiom at three sites:

- `reminder_form_dialog.py:329` — `_local_date_to_utc_end_of_day`
- `reminder_form_dialog.py:879` — `accept()` save path (the F3 impl-review fix, lines 869-878 comment)
- `scheduler.py:378-379` — `_ensure_aware` (treats naive as UTC, lenient read)

And a UTC→local read pattern for display, with an injectable `tz: tzinfo | None = None` keyword for test injection:

- `reminder_form_dialog.py:569,589,618,707` — end-date and event-time defaults for the form
- `ui/settings_dialog.py:295` — `_format_firing` reminder-list rendering
- `notifications/reminder_dialog.py:66` — reminder popup body formatter

The injectable-tz keyword on display helpers is already shaped to accept a non-system zone without changing production defaults — a useful precedent for the bugfix's test harness.

**Dependency state**: [`pyproject.toml:13`](../../../pyproject.toml) declares `python-dateutil>=2.9.0`. `dateutil.rrule.rrulestr` is the only currently-used surface; `dateutil.tz` is imported nowhere. Whether `dateutil.tz.gettz("Europe/Warsaw")` returns a usable zone on Windows 11 without bundling `tzdata` separately could not be verified from static reading — flagged as Open Question #3.

**Lessons / AGENTS guidance**: [`AGENTS.md:88`](../../../AGENTS.md) contains one DST claim — *"RRULE handles DST, month-end ('monthly on the 31st'), and end dates correctly; hand-rolled arithmetic will not."* — which **the R-1b bug disproves** in its current form. The claim is true ONLY when `dtstart` carries the user's local IANA tz; against a UTC `dtstart` it produces UTC-anchored firings that drift. [`lessons.md`](../../foundation/lessons.md) has no tz-specific lesson; the storage-boundary lesson at lines 19-23 is the closest applicable rule.

### § 5 — Fix-shape decision space (three options, two converge on disk)

R-1b named two options. A fresh look surfaces a third and clarifies that the first two converge on storage shape.

**Option (a) — IANA-tz on `start_at`** (per R-1b's first proposal): change the dataclass invariant from tz-aware UTC to tz-aware IANA. Looks elegant in memory.

> **Trap**: doesn't survive round-trip alone. `datetime(2026, 3, 28, 9, 0, tzinfo=gettz("Europe/Warsaw")).isoformat()` returns `"2026-03-28T09:00:00+01:00"` — only the offset, not the IANA name. On reload, `datetime.fromisoformat(...)` produces a tz-aware datetime with `tzinfo=tzoffset(None, 3600)`, which doesn't know about DST either. So option (a) silently degrades to "fixed-offset" math the moment data is persisted. To preserve the zone identity through serialization, you need a sibling `tz: str` IANA-name field on disk anyway.

**Option (b) — naive local `start_at` + new `tz: str` field** (per R-1b's second proposal): drop the tz-aware invariant; store `start_at` as naive local + IANA name separately; reconstruct zone-aware on load via `start_naive.replace(tzinfo=gettz(reminder.tz))`. Honest about the wire format. Cost: every `Reminder` constructor site has to either provide `tz` or accept a default; the `_coerce_aware_utc` chokepoint disappears entirely (replaced by `_coerce_tz` for the new field). All 55 test sites + the 7 dict literals + both factories migrate.

**Option (c) — UTC `start_at` UNCHANGED + scheduler-only `tz: str` field** (surfaced during this research): keep the storage invariant exactly as it is today; add a new optional `tz: str` field on `Reminder` consumed only by the scheduler's `next_firing_after`. At firing time the scheduler localizes: `start_iana = reminder.start_at.astimezone(gettz(reminder.tz))`, then `rrulestr(rule, dtstart=start_iana).after(now)` does DST-aware math. The 60 Reminder constructor sites are unaffected unless they want to specify a non-default tz (default could be system-local at construction time). The storage layer adds one optional field; `_coerce_aware_utc` continues to enforce the UTC contract on `start_at` exactly as it does today.

**Convergence on disk:** options (a) and (b) both end up with `start_at + tz: str` in the JSON. Option (c) too. The real choice is what `Reminder.start_at` carries in memory:

| Option | In-memory `start_at` | New disk field | Constructor blast radius |
|---|---|---|---|
| (a) IANA-aware `start_at` | `datetime` with IANA `tzinfo` | `tz: str` (required for round-trip) | All 60 sites (every constructor needs `start_at` with IANA tz) |
| (b) Naive `start_at` + tz field | naive `datetime` | `tz: str` (required, replaces tz info) | All 60 sites + the 7 dict literals + 2 factories (invariant change) |
| (c) UTC `start_at` + scheduler-only tz | `datetime` with UTC `tzinfo` (UNCHANGED) | `tz: str` (optional, default system-local at save) | ~5 (form save path adds tz capture; constructors get default; only scheduler reads new field) |

**Hand-edit safety per [lessons.md storage-boundary rule](../../foundation/lessons.md)**: every option requires a new `_coerce_tz(raw: object) -> str` helper. Behavior contract: take any input, return a valid IANA name or a documented exception class. If `gettz(returned_name)` is `None`, the helper falls back to `"UTC"` and logs a WARNING. This mirrors `_coerce_lead_minutes` at `storage/reminders.py:51-83` and `_coerce_aware_utc` at `:86-122`.

**Non-obvious gotcha shared by all three options**: `dateutil.tz.gettz("Europe/Warsaaw")` (typo'd) returns `None` silently. A `Reminder` whose effective tz resolves to `None` would crash `_compute_next` when comparing `fire_at` (naive) to `self._clock()` (tz-aware) — `TypeError: can't compare offset-naive and offset-aware datetimes`. This must be caught at the load boundary, not at the scheduler boundary. Per the row-containment rule from R-5, a bad-tz row should drop with a WARNING, not crash the whole load.

## Code References

Sortable list for `/10x-plan` consumption.

### Defect surface (the firing path)

- `break_reminder/scheduler.py:362` — `rrulestr(reminder.rrule_str, dtstart=start)` — defect anchor (UTC `dtstart`)
- `break_reminder/scheduler.py:367` — `rule.after(now, inc=False)` — UTC-space firing arithmetic
- `break_reminder/scheduler.py:376-380` — `_ensure_aware` — naive-as-UTC lenient contract
- `break_reminder/scheduler.py:297-306` — `reload()` — re-arm path (24h cap)
- `break_reminder/scheduler.py:310-319` — `_on_timer()` — fire-then-rearm
- `break_reminder/scheduler.py:336-345` — `_compute_next()` — earliest-firing selection (tz-aware comparison)

### Storage layer (the invariant chokepoint)

- `break_reminder/storage/reminders.py:127-139` — `Reminder` dataclass invariant docstring
- `break_reminder/storage/reminders.py:51-83` — `_coerce_lead_minutes` — canonical `_coerce_*` shape to mirror for `_coerce_tz`
- `break_reminder/storage/reminders.py:86-122` — `_coerce_aware_utc` — current UTC chokepoint
- `break_reminder/storage/reminders.py:175` — `from_dict` `start_at` parse
- `break_reminder/storage/reminders.py:185` — `from_dict` `end_at` parse
- `break_reminder/storage/reminders.py:232-277` — `ReminderStore._read` — R-5 row-containment guard (line 247) + per-row try/except (line 259)
- `break_reminder/storage/reminders.py:261` — `Reminder.from_dict(raw)` call site
- `break_reminder/storage/reminders.py:281` — `r.to_dict()` call site

### Form save/load (the user-intent capture)

- `break_reminder/ui/reminder_form_dialog.py:329` — `_local_date_to_utc_end_of_day` (end-date conversion)
- `break_reminder/ui/reminder_form_dialog.py:569,589,618,707` — UTC→local display defaults (already accept injectable tz via display helpers)
- `break_reminder/ui/reminder_form_dialog.py:869-878` — comment block explaining the F3-DST-correct save idiom
- `break_reminder/ui/reminder_form_dialog.py:879` — `event_at_utc = naive_local.astimezone(UTC)` — load-bearing save line
- `break_reminder/ui/reminder_form_dialog.py:936` — Add-flow Reminder construction
- `break_reminder/ui/reminder_form_dialog.py:958` — Edit-flow construction (recurrence subset)
- `break_reminder/ui/reminder_form_dialog.py:967` — Edit-flow construction (full-edit branch)

### Test coverage gap (where the failing test belongs)

- `tests/test_scheduler.py:25-85` — pure `next_firing_after` arithmetic (every test uses `tzinfo=UTC`). The R-1b failing test belongs HERE per the `TODO(R-1b)` breadcrumb in `tests/test_recurring_reminder_integration.py:33-41`.
- `tests/test_recurring_reminder_integration.py:33-41` — `TODO(R-1b)` breadcrumb (deferred to this bugfix change)
- `tests/test_reminders.py:666` — `+00:00`-stripped hand-edit test (canonical hand-edit-attack pattern to mirror for new `tz` field)

### Wiring (for /10x-plan blast-radius accounting)

- `tests/test_reminder_form_dialog.py` — `_make_reminder` factory (absorbs most test-side Reminder construction; migrate first)
- `tests/test_settings_dialog.py` — 27 sites (heaviest test file by Reminder count; many are stub-dialog fixtures for the Reminders tab)

## Architecture Insights

Three patterns the fix should respect.

1. **The codebase already has a "tz: tzinfo | None = None" injection idiom on display helpers** (`_format_firing` at `ui/settings_dialog.py:295`, `format_body` at `notifications/reminder_dialog.py:66`). Production passes `None` → system-local; tests pass a fixed tz to assert formatting on a CI runner. This is the cheap-test-injection shape. The bugfix can extend it to the scheduler: `next_firing_after(reminder, now, tz: tzinfo | None = None)` would let the test harness pass `gettz("Europe/Warsaw")` without the production code path changing. Pattern is already established; this is mirror-don't-invent territory.

2. **The R-5 row-containment fix at `ReminderStore._read` is the load-boundary template every `_coerce_*` helper must integrate with**. The per-row `try/except (KeyError, ValueError, TypeError)` at line 259 means a malformed `tz` field can drop just that row with a WARNING (not crash the whole load). The fix MUST extend the exception tuple to include whatever class `_coerce_tz` raises on unrecoverable input — almost certainly a custom `InvalidTimezoneError(ValueError)` so existing siblings keep working. Per [lessons.md storage-boundary rule](../../foundation/lessons.md), the planner must explicitly check both: "(a) does `tz` field have a `_coerce_*` helper?" AND "(b) does `_read`'s exception tuple include every class `_coerce_tz` can raise?"

3. **Clock injection is the universal scheduler-test pattern** (`tests/conftest.py:Clock` lifted in R-4 P1). DST-aware tests need both clock injection AND tz injection. The combined harness shape is: `Clock` seeded to "2026-03-28 06:00 UTC" (which is "07:00 CET" in Warsaw); seed a `Reminder` with `tz="Europe/Warsaw"` and `start_at` representing "9:00 Warsaw" (= `08:00 UTC` in CET); advance `Clock` to "2026-03-29 06:00 UTC" (which is "08:00 CEST" because DST kicked in at 02:00 local); call `_on_timer()`; assert the second-day firing is at `"9:00 CEST"` = `"07:00 UTC"`, NOT `"08:00 UTC"`. The oracle is the user-visible local clock, NOT the UTC instant — derived from the IANA spec, not from re-reading the fix.

## Historical Context (from prior changes)

- [`context/archive/2026-06-01-testing-rrule-reminder-loop/research.md`](../../archive/2026-06-01-testing-rrule-reminder-loop/research.md) §R-1b — **the originating research artifact for this bugfix**. Established the defect, the worked Warsaw example, the two-options framing (now updated to three by this research), and the "warrants its own /10x-shape cycle" parking decision. Open Questions #1 and #2 from that artifact are resolved by this change opening: Q#1 ("add failing test or defer?") → defer-with-breadcrumb chosen and now activated; Q#2 ("which fix shape?") → unresolved, captured below as our Open Question #1.

- [`context/archive/2026-05-28-reminders-recurrence-editor/plan-brief.md:73`](../../archive/2026-05-28-reminders-recurrence-editor/plan-brief.md) — **S-08 considered DST for end-date conversion only**. Verbatim: *"End-date local→UTC conversion across DST transitions may produce surprising stored values"*. The scope did not include firing-time DST. This is why the bug shipped with S-08 unflagged.

- [`context/archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md:56-58`](../../archive/2026-05-28-reminders-recurrence-editor/reviews/impl-review.md) — **"DST correctness" claim scoped only to `_local_date_to_utc_end_of_day`** but reads as if it covered the firing path. Likely contributed to the defect remaining unnoticed until R-1's grounding turned it up.

- [`context/archive/2026-06-02-testing-storage-malformed-input/`](../../archive/2026-06-02-testing-storage-malformed-input/) — R-5's `_coerce_aware_utc` expansion and `_read` row-containment fix landed on commit `2bab8e9`. These are the load-boundary patterns the bugfix's `_coerce_tz` helper must integrate with.

- [`context/foundation/lessons.md`](../../foundation/lessons.md) "Storage-boundary loaders need per-row containment + per-field coercion" — the binding rule for any new persisted field. Mirror `_coerce_lead_minutes` shape: clamp / fallback on bad input, raise a documented exception class so `_read` can drop the row cleanly.

- [`context/foundation/test-plan.md`](../../foundation/test-plan.md) §7 Negative space — explicitly parked DST drift for this change. Verbatim: *"No DST-drift fix for recurring firings. ... The fix changes the `Reminder.start_at` invariant from UTC to IANA-tz-aware; it warrants its own `/10x-shape` cycle as `bugfix-reminder-dst-drift`."* The parking entry should be revisited once this change merges.

## Related Research

- [`context/archive/2026-06-01-testing-rrule-reminder-loop/research.md`](../../archive/2026-06-01-testing-rrule-reminder-loop/research.md) — origin artifact (§R-1a R-1c also useful for understanding the scheduler's re-arm contract that the bugfix must preserve)

## Open Questions

These are the decisions `/10x-plan` (or `/10x-frame`, if scope feels suspect) needs to resolve before any code lands.

1. **Fix shape: (a) IANA `start_at`, (b) naive `start_at` + tz field, or (c) UTC `start_at` + scheduler-only tz?** R-1b named (a) and (b); this research surfaced (c) as the smallest-blast-radius option. (c) is also the most conservative — preserves the existing storage invariant entirely. The honest tradeoff: (c) splits "what the user picked" across two fields in a way that's slightly less intuitive to hand-edit (you'd need both `start_at` and `tz` to round-trip), while (a)/(b) are cleaner conceptually but force every Reminder constructor (~60 sites) to change. **Owner: user. Block: `/10x-plan`.**

2. **Timezone source: stored-per-reminder or always-system-local?** The R-1b worked example assumed the user picks a tz when creating the reminder. Alternative: every reminder fires at "9:00 wherever the OS clock says local is" — useful for a digital-nomad user who carries a laptop across time zones, surprising for a home-office user who expects "9:00 Warsaw" to stay 9:00 Warsaw even when traveling. Both are defensible product choices. The current form has NO tz picker (audit confirmed); the simplest fix is "system-local at save time, then store the IANA name". Adding a per-reminder TZ picker is a separable UX slice. **Owner: user. Block: `/10x-plan` (drives both UI and storage shape).**

3. **Runtime portability: does `dateutil.tz.gettz("Europe/Warsaw")` work on Windows 11 without bundling `tzdata`?** Static reading can't verify. Windows 11 itself does not ship `/usr/share/zoneinfo`; `dateutil.tz` has bundled fallbacks in some configurations. Alternatives: stdlib `zoneinfo.ZoneInfo` with explicit `tzdata` (PyPI) dependency. The plan should pick one approach AND verify on the CI runner (`windows-latest`) before committing. Adding `tzdata` to `pyproject.toml` is cheap (~5MB wheel). **Owner: user. Block: `/10x-plan` Phase 1.**

4. **Data migration for existing `reminders.json` files**: pre-bugfix reminders have no `tz` field. Three defaults available: (a) assume system-local at load time (preserves user intent if they haven't traveled), (b) assume UTC (preserves the current — incorrect — behavior), (c) prompt the user on first load. The codebase has zero installed-user telemetry, so we don't know if anyone has recurring-with-DST reminders in production. v0.7.1 shipped 2026-05-29; spring-forward in Europe was 2026-03-28 (before release). So a user who created a daily reminder between release and now has not yet seen the bug. Probably no migration is needed beyond a single `_coerce_tz(missing) → system_local` default. **Owner: user. Block: `/10x-plan`.**

5. **Failing-test placement and `pytest.mark.xfail` choice**: the R-1b breadcrumb says the failing test belongs in `tests/test_scheduler.py`, not the integration file. Two implementation orders are possible: (a) write the failing test first with `pytest.mark.xfail(strict=True)`, then implement the fix to remove the mark (TDD per `/10x-tdd`); (b) implement the fix and test together (per `/10x-implement`). The bugfix is well-scoped enough that either works; (a) gives a tighter regression signal. **Owner: user. Block: `/10x-plan` / `/10x-tdd`.**

6. **AGENTS.md DST claim update**: the line *"RRULE handles DST, month-end, and end dates correctly; hand-rolled arithmetic will not."* at [`AGENTS.md:88`](../../../AGENTS.md) is misleading in its current form — RRULE only handles DST when `dtstart` carries a local IANA tz. The bugfix's implementation phase should update this line to specify the invariant: *"RRULE handles DST correctly when `dtstart` carries an IANA-named timezone; against a UTC `dtstart` it produces UTC-anchored firings that drift across DST transitions."* **Owner: implementer. Block: `/10x-impl-review`.**
