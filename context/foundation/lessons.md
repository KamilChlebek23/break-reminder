# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## Document every public Python function with a Google-style docstring

- **Context**: Every public function and method in `.py` files across `break_reminder/`, `tests/`, and `main.py`. Private helpers (leading `_`) are exempt unless they encode non-obvious behavior.
- **Problem**: Documentation is inconsistent between files.
- **Rule**: Always attach a Google-style docstring (one-line summary, then `Args:` / `Returns:` / `Raises:` sections as needed) to every public function and method in `.py` files. Enforce via ruff's `D` rule group with `[tool.ruff.lint.pydocstyle] convention = "google"` so violations fail CI rather than relying on review discipline.
- **Applies to**: implement, impl-review

## Bundle /10x orchestration edits into the change's first phase commit

- **Context**: Changes opened via `/10x-test-plan` + `/10x-new` produce orchestration edits (e.g. `context/foundation/test-plan.md` §3 row status: `not started` → `change opened`) BEFORE the first implementation phase starts. The first phase's commit ritual finds these as dirty-but-untouched paths.
- **Problem**: The dirty-path prompt at commit time forces a per-commit decision (bundle / defer / abort). Deferring orphans the orchestration edit as a stray modification across multiple phase commits; bundling is the natural fit but isn't documented as the default. `/10x-impl-review` will flag the orphan as "out of phase scope" if reviewed mid-flight (see `testing-storage-malformed-input` Phase 1 F6).
- **Rule**: When the first phase commit ritual surfaces a dirty path that came from `/10x-test-plan`, `/10x-new`, or `/10x-shape` orchestration (typically `test-plan.md` §3 status flips, change-folder cell fills, or shape-notes deltas), default to **bundling** into the first phase's commit. Subject line stays scoped to the phase; body should call out the orchestration edit in one line so a reviewer doesn't have to spelunk. Treat any other dirty path as a genuine "unrelated" prompt.
- **Applies to**: implement, impl-review

## Storage-boundary loaders need per-row containment + per-field coercion

- **Context**: Every `from_dict` / `_get_*` / `load()` boundary in `break_reminder/storage/` (today: `reminders.py::Reminder.from_dict` + `ReminderStore._read`; `settings.py::Settings._get_int` / `_get_bool` / `_get_str`). FR-002 / FR-011 / FR-015 designate these files as user-editable in Notepad, so every disk read must treat its input as potentially hostile — a hand-edit, a partial-write crash, or a forward-compat key from a newer build.
- **Problem**: Two distinct failure classes need distinct fixes, and missing either one is silently dangerous. **Field-level**: a hand-edited single field (`lead_minutes = "oops"`, `start_at` dropped its tz suffix) crashes downstream code without per-field protection. **Row-level**: one malformed row in a multi-row list crashes the entire load when the per-row parse call sits outside any try/except, vaporizing well-formed siblings. The S-06b retrospective (impl-review F4 at `context/archive/2026-05-27-reminders-lead-time/reviews/impl-review-phase-1.md:84-92`) surfaced the field-level lesson via `_coerce_lead_minutes`, but it was never generalized to the row-level pattern until `testing-storage-malformed-input` Phase 3 closed `ReminderStore._read`. Both layers are required.
- **Rule**: At every storage-layer disk-read boundary, **both** layers must be present. **(a) Field-level**: every hand-editable field has a `_coerce_*` helper that maps any input (wrong type, out-of-range, malformed) to either a safe value or a documented exception class. Canonical example: `_coerce_lead_minutes` at `break_reminder/storage/reminders.py:36-72` (range clamp + type fallback). **(b) Row-level**: the boundary-level loader wraps per-row parse calls in `try/except` against the documented exception tuple (e.g. `(KeyError, ValueError, TypeError)` for `Reminder.from_dict`), drops the bad row with a `logger.warning` naming the row index + exception class, and preserves well-formed siblings. Canonical example: `ReminderStore._read` post-Phase-3 at `break_reminder/storage/reminders.py` (per-row guard + `isinstance(raw, list)` top-level guard that collapses non-list JSON to a single "top-level is not a list" WARNING). When introducing a new persisted field or a new storage boundary, ask both questions explicitly: "does the field have a `_coerce_*` helper?" AND "does the loader's exception tuple include every class this field can raise?" Mirror this audit in any `/10x-plan` that touches storage.
- **Applies to**: plan, implement, impl-review
