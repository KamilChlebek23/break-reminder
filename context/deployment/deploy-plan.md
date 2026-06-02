---
project: BreakReminder
target_release: v0.1.0
created: 2026-05-21
based_on:
  - context/foundation/infrastructure.md
  - context/foundation/tech-stack.md
phase_0_completed: true
---

> **Placement note.** This file lives at `context/deployment/deploy-plan.md` rather than the conventional `context/foundation/` because it is a runbook (procedural, version-bound to v0.1.0), not a foundation decision contract (durable, version-agnostic). The split keeps the foundation files clean of step-by-step procedure and lets future releases (v0.1.1, v0.2.0) get their own `deploy-plan-vX.Y.Z.md` siblings without rewriting the foundation.

## Purpose

Runbook for shipping the first published BreakReminder release (v0.1.0) through the GitHub Releases channel chosen in [`infrastructure.md`](../foundation/infrastructure.md). Walks the maintainer from pre-flight checks through tag push, publish, smoke test, and roll-back rehearsal.

## Inputs

- [`context/foundation/infrastructure.md`](../foundation/infrastructure.md) — channel = GitHub Releases (recommended); winget queued as v0.2.x runner-up; risk register inherited verbatim.
- [`context/foundation/tech-stack.md`](../foundation/tech-stack.md) — Python 3.12 + PySide6 (Qt 6) + PyInstaller 6.x + NSIS, on GitHub Actions `windows-latest`.
- [`.github/workflows/release.yml`](../../.github/workflows/release.yml) — the existing tag-driven publish pipeline; treated as authoritative for what CI will do.
- [`installer/break-reminder.nsi`](../../installer/break-reminder.nsi) — NSIS installer script; produces `installer/BreakReminder-Setup-X.Y.Z.exe`.

## Gap evaluation summary — `infrastructure.md` Getting Started against repo state at 2026-05-21

| Item | Status in repo as of 2026-05-21 | Action taken in this plan |
|---|---|---|
| GS#1 Declare `permissions: contents: write` | **Already done** in [`release.yml`](../../.github/workflows/release.yml) lines 20–21 | Verified; no action needed. The Getting Started item is stale; the deploy-plan supersedes it. |
| GS#2 Bootstrap-panic try/except + `MessageBoxW` | Was missing; **landed in Phase 0a** ([`main.py`](../../main.py)) | Done. Stdlib-only path resolution because Qt may itself be the failing import. |
| GS#3 "Check for updates" tray menu item | Was missing; **landed in Phase 0b** ([`break_reminder/app.py`](../../break_reminder/app.py)) | Done. Uses `QDesktopServices.openUrl(QUrl(RELEASES_URL))`; no in-app HTTP call. |
| GS#4 `pynput` submodule smoke test | Was missing; **landed in Phase 0c** ([`main.py`](../../main.py) `--self-test` + [`release.yml`](../../.github/workflows/release.yml) new step) | Done. Bundled-binary smoke test runs after PyInstaller, before NSIS. |
| GS#5 winget secondary channel | Future work | Deferred to v0.2.x per `infrastructure.md` "adopt when user count justifies". |
| GS#6 Code-signing onramp | Future work | Deferred until SmartScreen friction crosses the actionability threshold. v0.1.0 ships unsigned; release notes warn the user about SmartScreen. |
| Version drift: [`pyproject.toml`](../../pyproject.toml) line 3 vs [`installer/break-reminder.nsi`](../../installer/break-reminder.nsi) line 17 | Both at `0.1.0` today; will drift on next release | Surfaced in Phase 1 pre-flight as a manual sync check. Auto-syncing the two sources is out of scope for v0.1.0. |
| `pyinstaller>=6.10` lower-bound vs `infrastructure.md` "6.20.0" prose | Lower-bounded, not pinned; `uv.lock` controls resolved version | Documented; not blocking. Verify resolved version in pre-flight if SmartScreen reputation comes into play. |

## Phase 0 — pre-deployment safety nets (completed by the agent before this runbook was written)

| ID | File | What changed | Why it matters |
|---|---|---|---|
| 0a | [`main.py`](../../main.py) | Top-level `try/except Exception` around `_run()` writes the traceback to `%APPDATA%\BreakReminder\bootstrap-error.log` and surfaces a `MessageBoxW` before exiting. Path resolution uses `os.environ['APPDATA']` (stdlib only) so the safety net works even when Qt itself failed to import. | Closes the `--windowed` silent-failure mode flagged in `infrastructure.md`'s risk register. Without this, a missing DLL or a broken bundle exits silently with no UX feedback. |
| 0b | [`break_reminder/app.py`](../../break_reminder/app.py) | New `RELEASES_URL` module-level constant + new "Check for updates" `QAction` in the tray context menu, between "Open settings…" and the separator before "Quit". On trigger, calls `QDesktopServices.openUrl(QUrl(RELEASES_URL))`. | Pre-staged mitigation for the "users stay on stale versions because no native auto-update exists" risk. Respects the local-only NFR (the OS opens the browser; the app makes no HTTP call). |
| 0c | [`main.py`](../../main.py) (CLI flag) + [`.github/workflows/release.yml`](../../.github/workflows/release.yml) (new step between "Build PyInstaller bundle" and "Install NSIS") | `--self-test` argv handler imports `pynput.keyboard` / `pynput.mouse` and touches their `Listener` classes (forces backend dispatch); workflow step runs `BreakReminder.exe --self-test` and propagates non-zero exit. | Catches the silent-failure mode where `--collect-submodules pynput` misses a platform-specific submodule introduced upstream. |

Phase 0 verification (all green at completion time):

```text
uv sync                # 224 packages resolved, 58 checked
uv run ruff check      # All checks passed
uv run pyright         # 0 errors, 0 warnings, 0 informations
uv run pytest -q       # all tests passing
```

## Phase 1 — pre-flight checklist (maintainer-executable, before tag push)

1. **Replace the `<OWNER>` placeholder.** In [`break_reminder/app.py`](../../break_reminder/app.py), find the `RELEASES_URL` constant and swap `<OWNER>` for the maintainer's actual GitHub login. Verify by `Select-String -Path break_reminder/app.py -Pattern "<OWNER>"` returning no hits.
2. **Confirm both version sources match.** [`pyproject.toml`](../../pyproject.toml) line 3 and [`installer/break-reminder.nsi`](../../installer/break-reminder.nsi) line 17 must both say `0.1.0`. Drift will produce an installer whose `BreakReminder-Setup-<X.Y.Z>.exe` filename mismatches the GitHub Release tag, breaking the workflow's `installer/BreakReminder-Setup-*.exe` glob.
3. **Run the full local quality gate.** All four must exit zero:

   ```powershell
   uv sync
   uv run ruff check
   uv run pyright
   uv run pytest
   uv run pip-audit
   uv run pip-licenses --fail-on="AGPL"
   ```

4. **Local PyInstaller build + self-test.**

   ```powershell
   uv run pyinstaller --noconfirm --windowed --name BreakReminder --collect-submodules pynput main.py
   .\dist\BreakReminder\BreakReminder.exe --self-test
   ```

   Expect `OK` on stdout (or silent zero exit if PowerShell drops the AttachConsole'd stream; `$LASTEXITCODE` must be 0).

5. **Local NSIS build.**

   ```powershell
   makensis installer\break-reminder.nsi
   ```

   Verify `installer\BreakReminder-Setup-0.1.0.exe` is produced.

6. **Optional smoke install.** Run the local installer; click through; launch BreakReminder from the Start menu; right-click the tray icon → "Check for updates" — confirm the (still-empty) Releases page opens in the default browser; uninstall via Apps & Features; confirm `%APPDATA%\BreakReminder\` is preserved (FR-002).

7. **Working tree hygiene.** `git status` must show no uncommitted changes; `git log --oneline -5` should show the Phase 0 commits and any post-Phase-0 fixes from this checklist; no in-flight PRs against `main`.

## Phase 2 — tag push + publish (maintainer-executable)

1. Tag and push:

   ```powershell
   git tag -a v0.1.0 -m "BreakReminder 0.1.0 — first public release"
   git push origin v0.1.0
   ```

2. Watch the workflow:

   ```powershell
   gh run watch
   ```

   Or visit `Actions → Release` in the GitHub UI. Wait for both the `build` and `release` jobs to finish green. Total expected wall time: ~6–10 minutes (Windows runner + PyInstaller + NSIS).

3. Verify the published release:

   ```powershell
   gh release view v0.1.0
   ```

   Confirm:
   - Asset `BreakReminder-Setup-0.1.0.exe` is attached.
   - `generate_release_notes: true` produced a sensible auto-generated body (commits / PRs since the previous tag — for v0.1.0 this is the full history since repo init).

4. **Edit the release notes** to prepend a "First-run note" block that reads:

   > BreakReminder v0.1.0 ships unsigned (no Authenticode certificate). Windows SmartScreen will say "Windows protected your PC — Unrecognized app". This is expected. Click **More info → Run anyway** to install. We're tracking signing as a v0.2.x mitigation in the project's `infrastructure.md` risk register.

   Either via `gh release edit v0.1.0 --notes-file <updated-notes.md>` or in the Releases UI.

## Phase 3 — post-publish smoke test (maintainer-executable, fresh-machine flavour)

1. From a clean Windows 11 machine OR a VM snapshot (NOT the dev box — the dev box has SmartScreen reputation noise from local builds): download `BreakReminder-Setup-0.1.0.exe` from the Releases page.
2. Click the installer; observe SmartScreen prompt; click "More info → Run anyway"; complete install.
3. Launch BreakReminder from Start menu; observe tray icon (programmatic clock face per FR-004).
4. Right-click the tray icon → "Check for updates" → confirm the browser opens to the correct Releases URL (the `<OWNER>` placeholder swap from Phase 1 step 1 is what's being verified here).
5. Smoke-test the load-bearing FRs:
   - Tray menu shows: Take break now / Reset / Pause / Open settings… / Check for updates / Quit (FR-004).
   - Wait for or trigger a break dialog; verify Esc / Alt+F4 / click-outside / focus-loss do NOT dismiss it (FR-009 / US-02).
   - Open Settings, then trigger "Take break now" from the tray; verify the popup's "I'll take a break" button is clickable WHILE Settings is still on screen. Then close the popup, open Settings → Reminders → "Add reminder", trigger "Take break now" again, verify the popup is clickable WHILE the reminder form is on screen (R-2 modal-stacking wedge).
6. Uninstall via Settings → Apps → Installed apps → BreakReminder → Uninstall.
7. Confirm `%APPDATA%\BreakReminder\` still exists with `BreakReminder.ini` after uninstall (FR-002).

## Roll-back rehearsal (do this once, document the muscle memory)

**Distribution rollback** (yank the broken release, keep the tag):

```powershell
gh release delete v0.1.0 -y
```

Note: this deletes the GitHub Release but keeps the git tag. Users who already downloaded `BreakReminder-Setup-0.1.0.exe` are NOT recalled.

**Tag deletion** (full rewind, only safe before publish):

```powershell
gh release delete v0.1.0 -y
git tag -d v0.1.0
git push origin :refs/tags/v0.1.0
```

**Fix-forward** (preferred for any post-publish issue):

1. Bump version in BOTH [`pyproject.toml`](../../pyproject.toml) line 3 AND [`installer/break-reminder.nsi`](../../installer/break-reminder.nsi) line 17 to `0.1.1`.
2. Commit; push; tag `v0.1.1`; push the tag. The workflow ships v0.1.1 over v0.1.0 in the Releases page.

Time-to-revert: minutes for distribution rollback, one CI cycle (~6–10 min) for fix-forward.

## Known v0.1.0 caveats (release-notes raw material)

- **Unsigned binary.** SmartScreen warns on first install. Documented mitigation path (EV cert) lives in [`infrastructure.md`](../foundation/infrastructure.md) risk register; deferred until adoption justifies the spend.
- **No native auto-update.** Users manually visit the Releases page (or use the new in-app "Check for updates" tray menu item). Native auto-update is queued via the winget runner-up channel for v0.2.x.
- **Windows 11 only.** Older Windows / macOS / Linux are out of scope per PRD non-goals.
- **Settings UI is a placeholder.** Per the bootstrap status in [`tech-stack.md`](../foundation/tech-stack.md): "Tray menu has a placeholder `QMessageBox`. Settings live in `BreakReminder.ini` until FR-005 lands." v0.1.0 ships with this caveat; FR-005 is v0.2.x scope.

## Cross-references

- All risk-register items are inherited from [`infrastructure.md`](../foundation/infrastructure.md) unchanged. This runbook does not duplicate them; consult the source for likelihood / impact / mitigation.
- Future winget adoption: separate workflow per `infrastructure.md` Getting Started step 5; not done in v0.1.0. The `vedantmgoyal9/winget-releaser@v2` snippet there is the seed for that work.
- Future code-signing onramp: `infrastructure.md` Getting Started step 6 + the SmartScreen-related risk-register row. Trigger condition: SmartScreen friction observed in real-user telemetry (currently telemetry-free; trigger is qualitative — issue reports asking "is this safe to install").
- Future v0.1.1+ deploy plans: copy this file to `context/deployment/deploy-plan-v0.1.1.md` (or similar); the only sections that need updating per release are Phase 1 step 2 (version sync), Phase 2 (tag string), and the "Known caveats" block.
