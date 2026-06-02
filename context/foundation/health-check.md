---
project: BreakReminder
checked_at: 2026-06-02T17:20:00Z
health_status: healthy
context_type: brownfield
language_family: python
stack_assessment_available: false
checks_run:
  - lockfile
  - dependency_audit
  - outdated_deps
  - test_runner
  - ci_cd
  - configuration
audit_findings:
  critical: 0
  high: 0
  moderate: 0
  low: 0
test_runner_detected: true
test_count: 566
ci_provider: github-actions
recommended_fixes: 0
---

# BreakReminder — Health Check

> Re-run after the four-rollout testing sprint completed (R-1 recurring reminder loop, R-2 modal stacking, R-5 storage malformed input, R-4 top-three e2e flows). The project crossed from a "shipped v0.1.0 with 135 tests" state to a "566 tests across three tiers (unit + integration + e2e) with a CI marker split" state in twelve days. Every gate is still green; the project is in a meaningfully stronger state than the 2026-05-21 baseline.

## What changed since the last health check (2026-05-21)

| Area | Change |
|---|---|
| Test suite | **135 → 566 tests** (+431) across 17 files. Four test rollouts shipped: R-1 (`tests/test_recurring_reminder_integration.py`), R-2 (`tests/test_modal_stacking_integration.py`), R-5 (storage hand-edit robustness — extensions to `test_reminders.py` + `test_settings.py`), R-4 (three new e2e files: `test_add_reminder_e2e.py`, `test_save_settings_interval_e2e.py`, `test_tray_reset_e2e.py`). Plus `test_reminder_form_dialog.py` (125 tests), `test_reminder_scheduler.py` (11), `test_reminder_dialog.py` (9). |
| `[.github/workflows/release.yml](../../.github/workflows/release.yml)` | Single `Test` step replaced with two sequential steps `Test (unit)` (`pytest -m "not e2e"`) + `Test (e2e)` (`pytest -m e2e`) — gives the PR view two distinct red/green check marks. **Branch trigger hotfix**: `on.push.branches` and `on.pull_request.branches` corrected from `[main]` to `[master]` (the silent no-CI bug surfaced on the R-4 PR — line 9-13 comment block documents the fix). |
| `[pyproject.toml](../../pyproject.toml)` | Migrated pytest config from legacy `[tool.pytest.ini_options]` to the pytest 9.0+ native `[tool.pytest]` table — the legacy table silently dropped `--strict-markers` from `addopts`. New typed `strict_markers = true` boolean + `markers = ["e2e: ..."]` registration. Pyright floor bumped 1.1.380 → 1.1.410 (clears the upstream upgrade warning). |
| `[.pre-commit-config.yaml](../../.pre-commit-config.yaml)` | **New file** — ruff (`v0.15.13` with `--fix`) + pyright (local hook, whole-project) wired to run on every `git commit`. Local + CI now share the same lint/type gate. |
| `[tests/conftest.py](../../tests/conftest.py)` | Ten shared fixtures lifted from per-file integration tests (`clock`, `store_path`, `store`, `settings`, `voice` + `FakeVoice` class, `reminder_scheduler`, `activity`, `break_scheduler`, `event_log`, `break_reminder_app`) — establishes the harness foundation for the e2e tier. |
| `[break_reminder/app.py](../../break_reminder/app.py)` | `BreakReminderApp.__init__` gained a `clock=` kwarg propagated to both internal schedulers — structural fix that unblocks wired-app e2e tests driving virtual time deterministically. |
| `[context/foundation/lessons.md](lessons.md)` | Three new lessons recorded this period: "Bundle `/10x` orchestration edits into the change's first phase commit"; "Storage-boundary loaders need per-row containment + per-field coercion"; "Signal-connection assertions are not end-to-end coverage" (codifies the R-4 anti-pattern). |
| `[context/foundation/test-plan.md](test-plan.md)` | `rollout_phases_complete: 0 → 4` — all four planned test-tier rollouts shipped. §6 cookbook gained four new recipes (one per rollout). |
| `[context/archive/](../archive/)` | Four new archived changes since 2026-05-21: `2026-06-01-testing-rrule-reminder-loop`, `2026-06-02-testing-modal-stacking-wedge`, `2026-06-02-testing-storage-malformed-input`, `2026-06-02-testing-top-three-e2e-flows`. |

## Dependency Health

```text
Lockfile          : uv.lock (present, real lockfile — not the weak requirements.txt fallback)
pip-audit         : No known vulnerabilities found  (0 critical / 0 high / 0 moderate / 0 low)
pip-licenses      : No AGPL findings (PySide6 LGPL, PyInstaller GPLv2-with-bootloader-exception permitted)
Outdated packages : 6 (all patch-level minor bumps below the "two major versions behind" surface threshold)
```

| Package | Current | Latest | Type | Notes |
|---|---|---|---|---|
| certifi | 2026.4.22 | 2026.5.20 | wheel | Routine root-CA bundle refresh. |
| distlib | 0.4.0 | 0.4.1 | wheel | Transitive of pip-audit. |
| idna | 3.15 | 3.18 | wheel | Transitive. |
| pip | 26.1.1 | 26.1.2 | wheel | uv-managed; bumps automatically. |
| platformdirs | 4.9.6 | 4.10.0 | wheel | Transitive. |
| ruff | 0.15.13 | 0.15.15 | wheel | Tool dep; pinned in `.pre-commit-config.yaml:13` AND `pyproject.toml [dependency-groups].dev`. Two-step bump if you want them in lockstep: `uv lock --upgrade-package ruff` + `pre-commit autoupdate --repo https://github.com/astral-sh/ruff-pre-commit`. |

All six deltas are patch-level. None are AI-collaboration-relevant. Bump opportunistically.

## Test Infrastructure

```text
Test runner       : pytest 9.0+ (configured via [tool.pytest] in pyproject.toml; strict_markers enforced)
Test count        : 566 tests across 17 files (135 at 2026-05-21 → +431)
Tiers             : unit (538 tests, no marker) + integration (25 tests across 2 *_integration.py files,
                    no marker) + e2e (3 tests via @pytest.mark.e2e file-level pytestmark)
Plugins           : pytest-qt (QApplication coupling, qtbot, qapp fixtures)
Collection status : clean (pytest --collect-only -q exits 0)
Shared harness    : tests/conftest.py exposes 10 fixtures + Clock class + FakeVoice stub
```

| File | Tests | Tier |
|---|---|---|
| `tests/test_add_reminder_e2e.py` | 1 | e2e (R-4 Flow A) |
| `tests/test_app.py` | 42 | unit |
| `tests/test_break_dialog.py` | 20 | unit |
| `tests/test_break_scheduler.py` | 30 | unit |
| `tests/test_event_log.py` | 13 | unit |
| `tests/test_modal_stacking_integration.py` | 2 | integration (R-2) |
| `tests/test_recurring_reminder_integration.py` | 4 | integration (R-1) |
| `tests/test_reminder_dialog.py` | 9 | unit |
| `tests/test_reminder_form_dialog.py` | 125 | unit |
| `tests/test_reminder_scheduler.py` | 11 | unit |
| `tests/test_reminders.py` | 51 | unit (includes R-5 boundary-coerce additions) |
| `tests/test_save_settings_interval_e2e.py` | 1 | e2e (R-4 Flow B) |
| `tests/test_scheduler.py` | 8 | unit |
| `tests/test_settings_dialog.py` | 142 | unit |
| `tests/test_settings.py` | 101 | unit (includes R-5 boundary-coerce additions) |
| `tests/test_tray_reset_e2e.py` | 1 | e2e (R-4 Flow D) |
| `tests/test_voice.py` | 5 | unit |

The R-4 tier closes the R-4 "Must challenge" line item from `test-plan.md §2` — the three signal connections at `break_reminder/app.py:287` / `:288` / `:359` are now traversed end-to-end. The "no `_StubSignal` shims" rule is enforced by the new `lessons.md` entry "Signal-connection assertions are not end-to-end coverage" and will be flagged by future `/10x-impl-review` runs.

## CI/CD

```text
Provider : GitHub Actions
File     : .github/workflows/release.yml
Trigger  : push to master (corrected from main), pull_request to master, tag-push for "v*"
Stages   : lint ✓  test (unit) ✓  test (e2e) ✓  type-check ✓  security ✓  license ✓  build ✓
```

| Stage | Implementation | Notes |
|---|---|---|
| Install uv | `astral-sh/setup-uv@v8.1.0` | Pinned to exact patch tag per the supply-chain comment block (line 35-42); bump deliberately. |
| Lint | `uv run ruff check` | Selection `E F W I B UP SIM D` with Google pydocstyle convention. |
| Type check | `uv run pyright` | `standard` mode (not strict). Mirror of local pre-commit hook. |
| Test (unit) | `uv run pytest -m "not e2e"` | 563 tests (538 unit + 25 integration). |
| Test (e2e) | `uv run pytest -m e2e` | 3 tests. Separate step → distinct PR check mark. |
| Security | `uv run pip-audit` | Hard-fails on any known CVE. |
| License manifest | `uv run pip-licenses --format=markdown --output-file=licenses.md` | Produced BEFORE the AGPL gate so the artifact always lands (release.yml line 84-96 comment block documents the rationale). |
| License gate | `uv run pip-licenses --fail-on="AGPL"` | Allowlisted: PySide6 LGPL, PyInstaller GPLv2 (bootloader exception). |
| Upload manifest | `actions/upload-artifact@v4` with `if: always()` | Survives downstream failures. |
| Build | PyInstaller one-folder + `--self-test` pynput smoke + `choco install nsis` + NSIS installer | 6 steps before installer upload. |
| Publish | `softprops/action-gh-release@v2`, gated `startsWith(github.ref, 'refs/tags/v')` | `permissions.contents: write` declared explicitly. |

Local + CI gate parity: the new `.pre-commit-config.yaml` runs the same `ruff check` (with `--fix`) and `pyright` (whole-project) hooks on every `git commit`, so most CI failures are now catchable before push.

## Configuration

```text
.gitignore                ✓ present
.editorconfig             ✓ present
.gitattributes            ✓ present
LICENSE                   ✓ present (MIT, matches pyproject.toml [project].license)
README.md                 ✓ present (end-user Install + Using sections, 234 lines)
AGENTS.md                 ✓ present (deeply structured: stack rationale, FR-by-FR pattern notes,
                            threading rules, "do not enter event loop after BreakScheduler.start()"
                            rule freshly added)
.pre-commit-config.yaml   ✓ present (NEW since last check — ruff --fix + pyright)
pyproject.toml            ✓ ruff config (E/F/W/I/B/UP/SIM/D rules)
                          ✓ pyright config (standard mode, Windows platform)
                          ✓ pytest config (pytest 9.0+ native [tool.pytest] table)
                          ✓ google-style pydocstyle convention
                          ✓ markers + strict_markers enforced
.env.example              ✗ missing — N/A for this app (no env vars; local-only Windows desktop binary)
```

`.env.example` "missing" suppressed: BreakReminder is a tray-resident desktop app with zero outbound HTTP, no secrets, no environment-variable inputs. There is nothing to document.

## Foundation files (brownfield context)

```text
context/foundation/prd.md                  ✓ present (frontmatter says greenfield; project is now
                                              far past scaffold — treat as brownfield in practice)
context/foundation/tech-stack.md           ✓ present
context/foundation/lessons.md              ✓ present (4 entries: Google docstrings, orchestration
                                              bundling, storage-boundary coerce, signal-connection
                                              e2e coverage)
context/foundation/test-plan.md            ✓ present (rollout_phases_complete: 4, all R-N rollouts
                                              shipped)
context/foundation/infrastructure.md       ✓ present (GitHub Releases + winget runner-up)
context/foundation/stack-assessment.md     ✗ not run (optional input; skipped per skill guardrails)
context/foundation/health-check.md         ← this file (overwritten this run)
context/foundation/README.md               ✓ present
context/deployment/deploy-plan.md          ✓ present (v0.1.0 runbook)
context/changes/                           (empty — testing-top-three-e2e-flows just archived)
context/archive/                           16 archived changes (settings × 4, reminders × 5,
                                              bugfix × 2, testing rollouts × 4, version-in-check × 1)
```

The brownfield chain is well-stocked. Stack-assess is not a precondition for health-check; running it later would add the per-quality-gate scorecard but would not change today's verdict.

## Verdict

**Status: `healthy`**

| Signal | Reading |
|---|---|
| Audit findings | 0 critical, 0 high, 0 moderate, 0 low |
| Test runner | pytest 9.0+, 566 tests across 3 tiers, clean collection, strict_markers enforced |
| CI coverage | All 7 stages present (lint / test-unit / test-e2e / type / security / license / build) |
| Local-CI parity | pre-commit hooks mirror CI lint + type-check |
| Foundation files | PRD, AGENTS.md, lessons.md, test-plan.md, infrastructure.md, deploy-plan.md, tech-stack.md all present |
| Configuration | .editorconfig, .gitignore, .gitattributes, LICENSE, ruff/pyright/pytest all configured |
| Lockfile | uv.lock real (not the weak requirements.txt fallback) |
| Process maturity | 16 archived changes, 4 lessons codified, 4 test-tier rollouts shipped |

## Recommendations

**No Category A fixes required.** The project clears every must-fix gate for AI-assistant workflows.

Three opportunistic improvements, each strictly optional:

1. **Bump ruff to 0.15.15 in lockstep across both pin sites** (effort: quick)
   - `uv lock --upgrade-package ruff`
   - Update `.pre-commit-config.yaml:13` `rev: v0.15.13` → `rev: v0.15.15` (or `uv run pre-commit autoupdate --repo https://github.com/astral-sh/ruff-pre-commit`)
   - The comment block at `.pre-commit-config.yaml:7-9` explicitly calls out "keep in lockstep with `context/foundation/test-plan.md §4 Stack`" — bump all three together if you take this fix.

2. **Consider bumping pyright `typeCheckingMode` from `standard` to `strict`** (effort: moderate)
   - `pyproject.toml:76` comment already flags this as a future direction: "Bump to strict once the codebase is fully typed and the third-party stub gaps below are gone."
   - With 566 tests + Google-docstring enforcement + per-module pattern conventions in place, the codebase is in a stronger position to absorb strict-mode errors than at the previous check. Try it in a side branch first; if the error count is manageable (< 20), absorb them into a small chore commit.

3. **Refresh certifi opportunistically** (effort: quick)
   - `uv lock --upgrade-package certifi` — patch-level CA bundle refresh. Not security-relevant in this app (no outbound HTTP) but keeps the lockfile current.

None of the three blocks AI-collaboration quality. Address them on the next housekeeping pass or whenever the dependency surface gets touched for an unrelated reason.

## Comparison to 2026-05-21 baseline

| Dimension | 2026-05-21 | 2026-06-02 | Delta |
|---|---|---|---|
| Tests | 135 | 566 | **+431** (×4.2) |
| Test files | 7 | 17 | +10 |
| Test tiers | 1 (unit) | 3 (unit / integration / e2e) | +2 |
| CI test steps | 1 | 2 (unit + e2e split) | +1 |
| `.pre-commit-config.yaml` | absent | ruff + pyright | new |
| Pyright | 1.1.380 | 1.1.410 | +30 patches |
| Lessons codified | 1 | 4 | +3 |
| Archived changes | 12 | 16 | +4 |
| Audit findings | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | same (clean) |
| Health verdict | healthy | healthy | maintained |

The project did not just hold the line; it materially strengthened. The R-4 e2e tier closes a class of bug (broken `.connect()` calls invisible to slot-capture unit tests) that the previous `_StubSignal` patterns could not catch, and the new `lessons.md` entry makes that anti-pattern impossible to re-introduce silently.
