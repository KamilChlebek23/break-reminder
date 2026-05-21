---
name: git-validator
description: >-
  Audit a repository for git hygiene before commit or push. Three read-only
  gates: (1) confirm every path whose name starts with the '10x-' prefix is
  covered by .gitignore, (2) validate the LICENSE file exists, matches the
  pyproject.toml license field, and the copyright year covers the current
  year, (3) scan working-tree files for accidentally committed secrets
  (AWS / GitHub / Slack / Stripe / OpenAI / Google API keys, JWTs,
  private-key blocks, high-entropy assignments to password / secret / token /
  api_key). Surfaces findings and proposes fixes; never auto-edits any file.
  Use when the user says "validate git", "git hygiene", "run git-validator",
  "audit before commit", "pre-push check", or asks for a sanity check before
  pushing.
disable-model-invocation: true
---

# Git Validator

## Purpose

Three-gate inspection of the working tree, run on demand. Read-only. The
skill produces a findings report and proposes fixes. It must not modify any
file in the repository.

## Workflow

Run all three gates in order, then emit one aggregated report. Do not
short-circuit on the first failure — the user wants the full picture in one
pass.

```
[ ] Gate 1 — 10x- prefix coverage in .gitignore
[ ] Gate 2 — LICENSE compliance
[ ] Gate 3 — Sensitive data scan
[ ] Aggregate findings into the Report template at the end of this file
```

Each gate concludes with one of three statuses:

- **PASS** — no findings.
- **WARN** — findings exist but do not block a push (year drift, likely test
  fixture, etc.).
- **FAIL** — findings exist that should block a push (uncovered 10x- path,
  license mismatch, real secret).

---

## Gate 1 — 10x- prefix coverage in .gitignore

### Goal

Every file or directory whose **name segment** starts with `10x-` must be
covered by `.gitignore`. Anything tracked is a high-severity finding;
anything untracked but unignored is a medium-severity finding.

### Steps

1. Enumerate **tracked** 10x- paths:

   ```bash
   git ls-files | rg "(^|/)10x-"
   ```

2. Enumerate **untracked but unignored** 10x- paths (these are precisely the
   ones `.gitignore` is missing):

   ```bash
   git ls-files --others --exclude-standard | rg "(^|/)10x-"
   ```

3. Collapse each match up to the **top-level `10x-*` segment**. Example:
   `.cursor/skills/10x-foo/SKILL.md` collapses to `.cursor/skills/10x-foo/`.
   Deduplicate.

4. Read `.gitignore` (if present) for context — used only to render the
   "proposed additions" block in the canonical style of the existing file
   (trailing slash on directories, no leading slash unless the file already
   uses one).

### Coverage rule

A 10x- path is considered **covered** iff it does not appear in either of
the two `git ls-files` outputs above. Reasoning: `git ls-files` and
`--exclude-standard` already evaluate `.gitignore` patterns, including
wildcards and anchors — so anything still listed is, by definition, not
covered.

### Proposed-fix collapse rule

- **1 or 2 uncovered paths** → propose individual path-anchored entries
  matching the existing `.gitignore` style (trailing `/` for directories).
- **3 or more uncovered paths** → propose individual entries **and** offer a
  single canonical wildcard alternative (`**/10x-*` for repo-wide, or a
  scoped variant like `.cursor/skills/10x-*/` when all hits cluster under one
  parent).

### Output format

```
Gate 1: 10x- prefix coverage — FAIL (3 uncovered, 0 tracked)

Uncovered paths:
  - .cursor/skills/10x-stack-assess/        [untracked]
  - .cursor/skills/10x-tech-stack-selector/ [untracked]
  - .cursor/skills/10x-health-check/        [untracked]

Proposed .gitignore additions:
  .cursor/skills/10x-stack-assess/
  .cursor/skills/10x-tech-stack-selector/
  .cursor/skills/10x-health-check/

Alternative (covers all current and future 10x- artifacts under
.cursor/skills/):
  .cursor/skills/10x-*/
```

If any path is **tracked**, render it with `[tracked — also needs git rm
--cached <path>]` and bump the gate status to FAIL regardless of count.

---

## Gate 2 — LICENSE compliance

### Goal

The repository ships a LICENSE that (a) exists, (b) declares the same SPDX
identifier as `pyproject.toml`, (c) covers the current calendar year in its
copyright header, and (d) — for MIT projects — has not drifted from the
canonical OSI text.

### Steps

1. **Existence**. Look for `LICENSE`, `LICENSE.md`, or `LICENSE.txt` at the
   repo root. If none exists → FAIL. Propose an MIT body using the author
   name from `pyproject.toml` (`[project] authors`).

2. **SPDX detection**. Match the LICENSE body's first non-empty line against
   the table below to derive an SPDX identifier:

   - `MIT License` → `MIT`
   - `Apache License, Version 2.0` → `Apache-2.0`
   - `GNU GENERAL PUBLIC LICENSE Version 2` → `GPL-2.0`
   - `GNU GENERAL PUBLIC LICENSE Version 3` → `GPL-3.0`
   - `GNU LESSER GENERAL PUBLIC LICENSE Version 2.1` → `LGPL-2.1`
   - `GNU LESSER GENERAL PUBLIC LICENSE Version 3` → `LGPL-3.0`
   - `BSD 3-Clause License` → `BSD-3-Clause`
   - `BSD 2-Clause License` → `BSD-2-Clause`
   - `Mozilla Public License Version 2.0` → `MPL-2.0`
   - none of the above → WARN, "SPDX undetected — manual review required".

3. **`pyproject.toml` cross-check**. Read the `[project] license` field. If
   the detected SPDX disagrees → FAIL with a one-line summary of the
   mismatch.

4. **Year currency**. Match `Copyright \(c\) (\d{4})(?:[\u2013\-](\d{4}))?`
   on the copyright line. The current calendar year (read from the system
   clock) must be either the single year or fall within the inclusive range.
   If not → WARN with a proposed updated header.

5. **Text fidelity (MIT only)**. Compare the LICENSE body, line by line,
   against the verbatim OSI MIT text in
   [references/canonical-mit.txt](references/canonical-mit.txt) —
   **ignoring the `Copyright (c) ...` line entirely**. Any material
   drift → WARN with a unified diff. (Skip this sub-check for non-MIT
   licenses; document a future extension hook only.)

### Output format

```
Gate 2: LICENSE compliance — PASS

  ✓ LICENSE file exists at repo root (LICENSE)
  ✓ Detected SPDX: MIT
  ✓ Matches pyproject.toml license = "MIT"
  ✓ Copyright year covers <current_year>
  ✓ Text fidelity: matches canonical MIT body
```

For a failing run:

```
Gate 2: LICENSE compliance — FAIL

  ✓ LICENSE file exists at repo root (LICENSE)
  ✓ Detected SPDX: MIT
  ✗ pyproject.toml license = "Apache-2.0" (mismatch)
  ✗ Copyright year: file says "2024", expected to cover <current_year>
  ✗ Text fidelity: 1 line differs from canonical MIT (line 19)

Proposed change (copyright header):
  - Copyright (c) 2024 Kamil Chlebek
  + Copyright (c) 2024-<current_year> Kamil Chlebek

Proposed change (text fidelity, line 19):
  - LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR ARISING FROM,
  + LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,

Resolve the SPDX mismatch first (either update LICENSE to Apache-2.0 or
update pyproject.toml to "MIT").
```

---

## Gate 3 — Sensitive data scan

### Goal

Detect accidentally committed secrets (API keys, tokens, private keys,
high-entropy assignments) anywhere in the working tree.

### Pattern catalogue

Run each pattern via Grep across the working tree. Patterns are case-
sensitive unless flagged `(?i)`.

| Severity | Pattern | What it catches |
| -------- | ------- | --------------- |
| high | `AKIA[0-9A-Z]{16}` | AWS access key id |
| high | `ASIA[0-9A-Z]{16}` | AWS temporary access key |
| high | `gh[pousr]_[A-Za-z0-9]{36,}` | GitHub PAT / OAuth / server / refresh / user-to-server tokens |
| high | `xox[abprs]-[0-9A-Za-z-]+` | Slack tokens |
| high | `sk-[A-Za-z0-9]{20,}` | OpenAI API keys |
| high | `(sk\|pk)_(live\|test)_[A-Za-z0-9]{24,}` | Stripe secret / publishable keys |
| high | `AIza[0-9A-Za-z_-]{35}` | Google API keys |
| medium | `eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}` | JWT tokens |
| high | `-----BEGIN (RSA \|OPENSSH \|EC \|DSA \|PGP )?PRIVATE KEY-----` | Private-key PEM blocks |
| medium | `(?i)(password\|passwd\|pwd\|secret\|token\|api[_-]?key\|auth[_-]?token)\s*[:=]\s*['"][^'"]{12,}['"]` | High-entropy assignment to a sensitive variable name |

### Scan scope

Include: every file in the working tree EXCEPT —

- `.git/`
- `.venv/`, `venv/`, `env/`
- `build/`, `dist/`, `node_modules/`, `__pycache__/`
- Anything matched by `.gitignore` (re-derive via `git ls-files --others
  --exclude-standard --cached`).

This skill file itself is part of the working tree and **must be excluded**
from the scan to avoid matching its own pattern catalogue. Add
`.cursor/skills/git-validator/SKILL.md` to the per-run exclusion list.

### Redaction format

Every reported value is redacted to the first 4 characters plus `***`. Do
not echo full secret values into the report under any circumstance.

### Finding format

```
[high]   break_reminder/foo.py:42  AWS access key
         AKIA*** (redacted)

[medium] tests/fixtures/example.py:7  api_key assignment
         api_key = "sk-*** (redacted, likely test fixture — verify)"
```

### False-positive guidance

- A hit inside `tests/`, `fixtures/`, `examples/`, or any path containing
  `example` in a segment is rendered with the trailing tag
  `(likely test fixture — verify)` and downgraded one severity step (high →
  medium, medium → low).
- Sentinel values are suppressed silently. The recognised sentinels are the
  AWS-documentation example key, GitHub placeholder PATs, and Stripe demo
  keys. The agent recognises these by their literal value and excludes them
  from the report.
- A user can permanently silence a single line by appending the inline
  comment `# git-validator: allow` (or `// git-validator: allow` /
  `<!-- git-validator: allow -->` for the appropriate language). The skill
  honours this comment when it appears on the same line as the match.

---

## Report template

After running all three gates, emit exactly this structure:

```
# Git Validator Report — <ISO timestamp>

## Summary

  Gate 1 — 10x- prefix coverage : <STATUS> (<n> findings)
  Gate 2 — LICENSE compliance   : <STATUS> (<n> findings)
  Gate 3 — Sensitive data scan  : <STATUS> (<n> findings)

  Overall: <PASS | WARN | FAIL>
  (Overall = the worst status across the three gates;
   FAIL > WARN > PASS.)

## Findings

### Gate 1
<gate 1 output block, or "No findings.">

### Gate 2
<gate 2 output block>

### Gate 3
<gate 3 output block, or "No findings.">

## Proposed actions

1. <concrete next step, e.g. "Add three lines to .gitignore">
2. <concrete next step, e.g. "Update LICENSE copyright header">
3. <concrete next step, e.g. "Remove or rotate the leaked GitHub PAT in foo.py:42">

(No files have been modified by this skill. Apply the proposed changes
manually if you agree.)
```

---

## Operating rules

These are hard rules. Do not relax them per run.

- **Read-only.** Never call any tool that writes, creates, deletes, or
  renames files. Never run `git add`, `git commit`, `git rm`, `git
  checkout`, or any command that mutates the index or working tree.
- **Always redact.** No full secret value ever appears in the report — even
  if the user asks for it. Refer to redaction format above.
- **Cite paths.** Use backticks and `file:line` form for every finding.
  Forward slashes only.
- **Run all three gates.** Never short-circuit. Aggregate results before
  reporting.
- **Fallback when `.gitignore` is absent.** Gate 1 reports FAIL with a
  proposed minimal `.gitignore` body covering all discovered 10x- paths.
- **Fallback when `pyproject.toml` is absent.** Gate 2 runs sub-checks 1
  (existence) and 4 (year currency) only; sub-checks 2, 3, and 5 are
  skipped and reported as "skipped — no pyproject.toml".
- **Self-exclusion.** Always exclude
  `.cursor/skills/git-validator/SKILL.md` from gate 3.
- **No history scan.** Only the current working tree and the git index. If
  the user wants history scrubbing, point them at `git filter-repo` or
  `bfg-repo-cleaner` and stop.
