# Lessons Learned

> Append-only register of recurring rules and patterns. Re-read at start by /10x-frame, /10x-research, /10x-plan, /10x-plan-review, /10x-implement, /10x-impl-review.

## Document every public Python function with a Google-style docstring

- **Context**: Every public function and method in `.py` files across `break_reminder/`, `tests/`, and `main.py`. Private helpers (leading `_`) are exempt unless they encode non-obvious behavior.
- **Problem**: Documentation is inconsistent between files.
- **Rule**: Always attach a Google-style docstring (one-line summary, then `Args:` / `Returns:` / `Raises:` sections as needed) to every public function and method in `.py` files. Enforce via ruff's `D` rule group with `[tool.ruff.lint.pydocstyle] convention = "google"` so violations fail CI rather than relying on review discipline.
- **Applies to**: implement, impl-review
