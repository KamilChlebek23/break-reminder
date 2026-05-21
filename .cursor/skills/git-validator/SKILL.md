---
name: git-validator
description: >-
  Audit a repository for git hygiene before commit or push. Three gates:
  (1) confirm every path whose name SEGMENT contains '10x' anywhere is
  covered by .gitignore — interactively asks the user which findings to
  add and appends the selected entries to .gitignore on confirmation,
  (2) validate the LICENSE file exists, matches the pyproject.toml license
  field, and the copyright year covers the current year, (3) scan
  working-tree files for accidentally committed secrets (AWS / GitHub /
  Slack / Stripe / OpenAI / Google API keys, JWTs, private-key blocks,
  high-entropy assignments to password / secret / token / api_key). Gates
  2 and 3 are strictly read-only; only Gate 1 may modify .gitignore, and
  only after explicit user confirmation. Use when the user says "validate
  git", "git hygiene", "run git-validator", "audit before commit",
  "pre-push check", or asks for a sanity check before pushing.
disable-model-invocation: true
---

# Git Validator

## Purpose

Three-gate inspection of the working tree, run on demand. Gates 2 (LICENSE)
and 3 (sensitive data) are strictly read-only. Gate 1 (10x substring path
coverage) may APPEND to `.gitignore` and only `.gitignore`, only after the
user explicitly selects which findings to ignore via the AskQuestion form.
No other file in the repository is ever modified by this skill.

## Workflow

Run all three gates in order, then emit one aggregated report. Do not
short-circuit on the first failure — the user wants the full picture in one
pass.

```
[ ] Gate 1 — 10x substring coverage in .gitignore (interactive)
[ ] Gate 2 — LICENSE compliance
[ ] Gate 3 — Sensitive data scan
[ ] Aggregate findings into the Report template at the end of this file
```

Each gate concludes with one of three statuses:

- **PASS** — no findings.
- **WARN** — findings exist but do not block a push (untracked 10x-named
  paths the user reviewed and declined to ignore, year drift, likely test
  fixture, etc.).
- **FAIL** — findings exist that should block a push (tracked 10x-named
  path, license mismatch, real secret).

---

## Gate 1 — 10x substring coverage in .gitignore

### Goal

Every file or directory whose **name segment** contains the substring `10x`
anywhere (prefix, infix, or suffix — any position) should be either covered
by `.gitignore` or explicitly acknowledged by the user. Tracked paths are a
high-severity finding (FAIL); untracked-but-unignored paths are surfaced
through an interactive AskQuestion form so the user can decide per-path
whether to add them to `.gitignore`.

### Steps

1. Enumerate **tracked** paths whose any segment contains `10x`:

   ```bash
   git ls-files | rg "10x"
   ```

2. Enumerate **untracked but unignored** paths whose any segment contains
   `10x` (these are the candidates for the AskQuestion prompt):

   ```bash
   git ls-files --others --exclude-standard | rg "10x"
   ```

   Match is case-sensitive lowercase. The 10xDevs ecosystem is uniformly
   lowercase; if a future need arises for `10X` matching, change the regex
   to `10[xX]` in both commands above.

3. **Collapse rule.** For each match, walk the path from the root and stop
   at the first segment that contains `10x`. Truncate at the end of that
   segment, with a trailing `/` if it's a directory; otherwise use the file
   path itself. Deduplicate.

   Worked examples:

   - `.cursor/skills/10x-foo/SKILL.md` → `.cursor/skills/10x-foo/`
   - `tests/test_10x_things.py` → `tests/test_10x_things.py`
     (no enclosing 10x-named directory; the file itself carries the match)
   - `parent/no10xbar/file.py` → `parent/no10xbar/`
     (yes — `no10xbar` contains `10x`, substring match, not prefix)
   - `.cursor/.10x-cli-manifest.json/` → `.cursor/.10x-cli-manifest.json/`

4. Read `.gitignore` (if present) for two reasons:

   - Detect the existing leading-slash convention so any new entries match.
   - Idempotency check — if a candidate is already a literal line in
     `.gitignore`, mark it `[already covered]` and skip it from the prompt.

### Coverage rule

A 10x-substring path is considered **covered** iff it does not appear in
either of the two `git ls-files` outputs above. Reasoning: `git ls-files`
and `--exclude-standard` already evaluate `.gitignore` patterns, including
wildcards and anchors — anything still listed is, by definition, not
covered.

### Interactive flow

Branch on finding count after collapse + dedupe:

- **0 findings** → render Gate 1 PASS, no prompt, move on.
- **1 or 2 findings** → emit a single `AskQuestion` with
  `allow_multiple: true`, one option per discovered path. The user checks
  the paths they want appended to `.gitignore`.
- **3 or more findings** → same multi-select, PLUS a wildcard alternative
  option when findings cluster under a common ancestor (e.g.
  `.cursor/skills/*10x*/`). If the user selects both the wildcard and one
  or more individual paths, the skill writes both and notes the redundancy
  in the report.

The AskQuestion options must include the literal path that would be
written to `.gitignore` so the user can audit the proposed entry exactly.
A "Skip all" outcome is implicit — the user simply leaves every checkbox
unchecked.

### `.gitignore` write rules

After the user answers, append the selected entries to `.gitignore`:

- **Append-only.** Never rewrite or reorder existing lines.
- **Style mirroring.** Match the existing `.gitignore` convention for
  leading slashes (most repos omit them; respect whatever the file uses).
  Append a trailing `/` for directory entries.
- **Idempotency.** If a selected entry is already a literal line in
  `.gitignore`, skip it (do not double-add) and report it as
  `[already covered]`.
- **Atomicity.** Write all selected entries in a single `StrReplace`
  call (append-after-last-line). Do not chain multiple StrReplace calls
  on `.gitignore` — partial failure must not leave the file half-updated.

### Tracked-file handling

If a discovered path is **tracked** (appears in `git ls-files`),
`.gitignore` alone will NOT untrack it — git already has a tracked record.
The skill renders such findings in a separate report sub-section and
prints the manual remediation command:

```
git rm --cached <path>
```

The skill **never** invokes `git rm`, `git add`, `git commit`,
`git checkout`, or any other index-mutating command. This is enforced by
the Operating Rules below.

Status implication: any tracked finding bumps Gate 1 to **FAIL**
regardless of how many untracked findings the user added or declined.

### Output format

```
Gate 1: 10x substring coverage — WARN (3 findings: 2 added, 1 declined, 0 tracked)

Discovered:
  - .cursor/skills/something-10x/         [untracked]
  - tests/test_10x_things.py              [untracked]
  - .cursor/.10x-cli-manifest.json/       [untracked]

Added to .gitignore by this run:
  + .cursor/skills/something-10x/
  + .cursor/.10x-cli-manifest.json/

Declined by user:
  - tests/test_10x_things.py

Tracked — requires manual `git rm --cached <path>`:
  (none)
```

If a tracked finding exists, render it under the last sub-section with
the exact remediation command:

```
Tracked — requires manual `git rm --cached <path>`:
  - some/tracked/path-with-10x/file.py

  $ git rm --cached "some/tracked/path-with-10x/file.py"

(Skill never invokes git rm. Apply manually, then commit.)
```

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

  Gate 1 — 10x substring coverage : <STATUS> (<n> findings)
  Gate 2 — LICENSE compliance     : <STATUS> (<n> findings)
  Gate 3 — Sensitive data scan    : <STATUS> (<n> findings)

  Overall: <PASS | WARN | FAIL>
  (Overall = the worst status across the three gates;
   FAIL > WARN > PASS.)

## Findings

### Gate 1
<gate 1 output block — Discovered / Added / Declined / Tracked sub-sections,
or "No findings.">

### Gate 2
<gate 2 output block>

### Gate 3
<gate 3 output block, or "No findings.">

## Proposed actions

1. <concrete next step, e.g. "Apply `git rm --cached path/with/10x/file.py`">
2. <concrete next step, e.g. "Update LICENSE copyright header">
3. <concrete next step, e.g. "Remove or rotate the leaked GitHub PAT in foo.py:42">

(Gate 1 may have appended entries to `.gitignore` based on your
multi-select answer; that change is already on disk. No other file is
ever modified by this skill — apply Gate 2 / Gate 3 fixes manually.)
```

---

## Operating rules

These are hard rules. Do not relax them per run.

- **Read-only by default; one carve-out for Gate 1.** The skill MAY append
  entries to `.gitignore` and ONLY `.gitignore`, and ONLY when the user has
  explicitly selected them through the AskQuestion form in Gate 1. No other
  file may be created, modified, deleted, or renamed by this skill —
  including `.gitignore` itself outside the Gate 1 user-confirmed flow. The
  skill NEVER invokes `git add`, `git commit`, `git rm`, `git checkout`, or
  any other command that mutates the git index, HEAD, or working tree.
- **Always redact.** No full secret value ever appears in the report — even
  if the user asks for it. Refer to redaction format above.
- **Cite paths.** Use backticks and `file:line` form for every finding.
  Forward slashes only.
- **Run all three gates.** Never short-circuit. Aggregate results before
  reporting.
- **Fallback when `.gitignore` is absent.** Gate 1 will CREATE `.gitignore`
  with the user-selected entries (still gated on the AskQuestion form — if
  the user declines all candidates, no file is created). Creating
  `.gitignore` for the first time is treated as the "append" carve-out
  applied to a zero-length file.
- **Fallback when `pyproject.toml` is absent.** Gate 2 runs sub-checks 1
  (existence) and 4 (year currency) only; sub-checks 2, 3, and 5 are
  skipped and reported as "skipped — no pyproject.toml".
- **Self-exclusion.** Always exclude
  `.cursor/skills/git-validator/SKILL.md` from gate 3.
- **No history scan.** Only the current working tree and the git index. If
  the user wants history scrubbing, point them at `git filter-repo` or
  `bfg-repo-cleaner` and stop.
