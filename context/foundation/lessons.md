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
