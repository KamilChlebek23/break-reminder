---
project: BreakReminder
researched_at: 2026-05-21
recommended_platform: GitHub Releases
runner_up: winget (microsoft/winget-pkgs)
context_type: mvp
tech_stack:
  language: Python 3.12
  framework: PySide6 (Qt 6) + PyInstaller 6.20.0 + NSIS
  runtime: Windows 11 desktop
---

> **Scope-pivot note.** The skill's stock candidate pool (Cloudflare / Vercel / Netlify / Fly.io / Railway / Render) is uniformly web hosting and was empty after the tech-stack hard filter (see the previous record-of-decision file in git history). This file is a tailored re-run on the question that actually has a real candidate pool for this project: **which Windows distribution channel** to ship the PyInstaller + NSIS installer through. Microsoft Store was hard-filtered out by the no-code-signing answer; the remaining five (GitHub Releases, winget, Chocolatey, Scoop, portable ZIP) were researched in parallel against May 2026 evidence.

## Recommendation

**Distribute on GitHub Releases as the canonical channel.** The incumbent pipeline already publishes correctly, the maintainer has direct hands-on familiarity with no other channel (Q3), the hobbyist-niche audience finds the project via README/Reddit/HN and clicks the Releases link rather than a CLI package manager (Q4), and auto-update is a soft positive rather than a hard requirement (Q5). winget is the strong runner-up and a credible **layer on top** rather than a replacement — its manifest can simply point at the GitHub-Releases-published `.exe`, adding a `winget install break-reminder` install line in the README without changing the build pipeline. Adoption of winget can wait until first-PR moderation latency is justified by user demand.

## Platform Comparison

Five axes from the inline criteria in the previous `infrastructure.md` (CLI-first / Managed catalog / Agent-readable docs / Stable scriptable API / MCP integration). Each axis is scored `Pass = 2 / Partial = 1 / Fail = 0`, so the maximum criteria total is 10. Soft-weight deltas are signed contributions credited to specific interview answers — for example `+1 (Q3)` for the existing-familiarity tilt toward GitHub Releases, `−1 (Q4)` for not being the primary discovery funnel — so a future reader can recompute the ranking without rerunning the skill. Two channels are eliminated before scoring: Microsoft Store at the Q1 hard-filter (no code-signing → signed MSIX impossible), and Portable ZIP at the PRD-fit gate (FR-001's Socratic note explicitly rejected portable distribution). Rows are sorted by Total descending; eliminated channels appear at the bottom.

| Channel | CLI-first | Managed catalog | Agent-readable docs | Stable scriptable API | MCP / Integration | Criteria total | Soft-weight delta | Filter / fit gate | Total | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| **GitHub Releases** | Pass (2) | Pass (2) | Pass (2) | Pass (2) | Partial (1) | 9 | `+1 (Q3) +1 (Q4) = +2` | OK | **11** | MCP v1.0.5 (May 2026) read-only on releases — agent shells out to `gh` for writes. |
| **winget** | Pass (2) | Pass (2) | Pass (2) | Pass (2) | Partial (1) | 9 | `+0.5 (Q5) −1 (Q4) = −0.5` | OK | **8.5** | MCP server PREVIEW; first-PR review on `microsoft/winget-pkgs` typically >1 week. |
| **Chocolatey** | Pass (2) | Pass (2) | Pass (2) | Pass (2) | Fail (0) | 8 | `+0.5 (Q5) −1 (Q4) = −0.5` | OK | **7.5** | No official MCP server; community moderation queue: days to weeks, no SLA. |
| **Scoop** | Pass (2) | Partial (1) | Pass (2) | Pass (2) | Fail (0) | 7 | `+0.5 (Q5) −1 (Q4) −0.5 (ops) = −1` | OK | **6** | Self-hosted bucket is the recommended path; adoption requires an extra `.zip` artifact alongside the NSIS `.exe`. |
| Microsoft Store | n/a | n/a | n/a | n/a | n/a | — | — | DROPPED — Q1 (signing) | — | Signed MSIX is mandatory; out of scope per Q1 = no signing. |
| Portable ZIP | Pass (2) | Pass (2) | Pass (2) | Pass (2) | Partial (1) | 9 | (would be +2 if not blocked) | BLOCKED — PRD FR-001 | — | PRD FR-001's Socratic note explicitly rejected portable distribution in favour of the Apps & Features uninstall hook. |

GitHub Releases scores **11**, winget **8.5**, Chocolatey **7.5**, Scoop **6**; Microsoft Store and Portable ZIP are eliminated by the Q1 signing hard-filter and the FR-001 PRD-fit gate respectively.

### Shortlisted Channels

#### 1. GitHub Releases (Recommended)

Already shipping. Q3 (familiarity) and Q4 (audience reach) tilt cleanly toward it. Five-of-five Pass on the criteria axes except MCP, which is Partial because the GitHub MCP Server v1.0.5 (May 2026) exposes release tools READ-ONLY — `create_release` and `upload_release_asset` are not implemented, so an agent driving CI must shell out to `gh release create`. Public-repo cost is effectively zero (2 GiB/asset, unlimited bandwidth, free unmetered `windows-latest` minutes). The current pipeline uses `softprops/action-gh-release@v2.6.2`; v3.0.0 (Node 24) is available for a future migration. The known unsigned-binary friction (SmartScreen) is a Microsoft-side problem, not a channel problem — switching channels does not solve it.

#### 2. winget (Runner-up)

The strongest **add-on** to GitHub Releases. The manifest just references the existing GHR-published `.exe` via `InstallerUrl` + `InstallerSha256`; no change to the PyInstaller or NSIS step is required. Brings native auto-update (`winget upgrade --all`) and first-class CLI installability for users who already use winget. Gaps: first-PR review on `microsoft/winget-pkgs` typically takes >1 week (ongoing version updates merge faster); MCP server is PREVIEW; unsigned NSIS installers occasionally draw extra validation flags during PR review even though they're accepted. CI publishing is fully automated via `vedantmgoyal9/winget-releaser@v2` triggered on tag push. Recommended timing: adopt when the project crosses ~50 active users or when the first README contributor asks for a `winget install` line.

#### 3. Chocolatey

Viable but less attractive than winget for this project. Same install model (`choco install break-reminder`, `choco upgrade break-reminder`), and the CI publish via `crazy-max/ghaction-chocolatey@v4` is straightforward. The community moderation queue runs days to weeks with no SLA per the June 2025 "Behind the Curtain" post — that's a real friction the maintainer absorbs each release. Critically: **no official Chocolatey MCP server** as of May 2026, while winget already has one (in preview). Reserved as a future option if Q4 ever flips toward "CLI package manager" or if Q5 ever flips to "auto-update required" AND winget reach proves insufficient.

## Anti-Bias Cross-Check: GitHub Releases

The previous `infrastructure.md` ran these three lenses against the GitHub Releases incumbent. The May 2026 research surfaced material new evidence; this is a refresh, not a copy.

### Devil's Advocate — Weaknesses

1. **EV-cert SmartScreen bypass was removed in 2025.** Even an EV code-signing certificate no longer guarantees the "Unrecognized app" warning is suppressed on first download — the only path to a clean install UX is Microsoft-side reputation accumulation, which builds slowly per-publisher. The previous file's "EV cert ~$300–500/yr → solved" assumption is wrong as of 2025; signing investment now buys reputation acceleration, not a guarantee.
2. **`GITHUB_TOKEN` default flipped to read-only on Feb 2, 2026.** Any release workflow that doesn't explicitly declare `permissions: contents: write` silently fails the first time it tries to publish. BreakReminder's `release.yml` already uses `softprops/action-gh-release@v2`, which depends on this; the explicit permission must be declared at the workflow or job level. Contributor PRs copying older 2024 tutorials can silently regress this.
3. **GitHub MCP Server v1.0.5 (May 2026) exposes release tools as READ-ONLY.** No `create_release`, no `upload_release_asset`. Agent-driven release publishing must shell out to `gh release create` — agent-side audit logs can attest "intent to publish" but not the publish operation itself. Different boundary than the rest of the agent surface.
4. **NSIS is a niche skill with shrinking community.** `installer/break-reminder.nsi` becomes a maintenance liability the moment it needs to do something non-trivial. AI agents have inconsistent training-data coverage of NSIS scripting compared to WiX/MSI or Inno Setup.
5. **GitHub Releases is a single point of distribution.** If the repo is taken down (DMCA, ToS, account suspension), every install link breaks. No mirror, no fallback CDN.

### Pre-Mortem — How This Could Fail

Six months from launch BreakReminder is in roughly 30 hobbyist hands. In late 2026 Microsoft tightens SmartScreen further (the trajectory continues from the 2025 EV-bypass removal): the "Run anyway" link gets a longer reputation threshold before it appears, and some new-user installs hit a flat refusal until reputation builds. The maintainer, having shipped only unsigned releases, is essentially invisible to Defender's reputation system — every new install is a fresh "Windows protected your PC" wall. Worse: a contributor PR in March 2026 added a release-publish step that copied a 2024 tutorial without `permissions: contents: write`; the change passed PR review and CI (the pipeline runs but skips the `gh release` step silently on its first tag) and three weeks of "I tagged but no release appeared" debugging follows before the maintainer spots it. By month nine the friction is dominantly Microsoft-side (signing reputation) rather than GitHub-side, and the "GitHub Releases is the right channel" conclusion still holds — but the unsigned-binary blocker is now urgent and the windows-side investment can no longer wait for v2.

### Unknown Unknowns

- **Feb 2026 `GITHUB_TOKEN` default change is recent enough to trap contributors copying older templates.** The fix is one line of YAML; the cost of missing it is a silently broken release. Worth pinning in `AGENTS.md` and at the top of `release.yml`.
- **GitHub MCP server's read-only release surface** means future agent-driven release pipelines must use a fine-grained PAT for write operations, not the MCP-injected token. Different secrets-management surface than the rest of the agent flow.
- **`softprops/action-gh-release@v2.6.2` is current; v3.0.0 is on Node 24.** Pinning to v2 long-term will eventually hit a Node 16/20 deprecation in GitHub Actions; mark a 2027-ish migration window.
- **Public-repo bandwidth "unlimited" is policy-soft.** GitHub has terminated abusive accounts; for a hobbyist project this is unlikely but not zero. Mirror policy in the risk register stays relevant.
- **`PyWinSparkle` and `PyUpdater` are unmaintained as of 2026.** If BreakReminder ever wants in-app update notification, it's a `QDesktopServices.openUrl` to the Releases page or a custom polling implementation against the GitHub Releases API — there is no maintained Python library that does the Sparkle-style flow against GitHub Releases.
- **Per-publisher SmartScreen reputation does not transfer between certs.** If switching CAs, plan for a 1–2 week reputation rebuild window; coordinate with a release that has minimal user-visible changes.
- **PyInstaller's `--collect-submodules pynput`** is required because pynput uses dynamic imports the static analyzer misses. If `pynput` ships a major update with new submodules, the release will silently miss them — surfacing as runtime warnings that don't fail CI.

## Operational Story

How GitHub Releases actually operates day to day for BreakReminder. One concrete answer per line.

- **Preview deploys**: PR builds run the full pipeline through PyInstaller + NSIS but **stop before publish** — the `release` job is gated on `startsWith(github.ref, 'refs/tags/v')`. PR artifacts are downloadable from the run page (`Actions → run → BreakReminder-installer`) for manual smoke-testing. Fork PRs run the same gates because secrets are not required for the build itself; publishing is impossible from forks because `contents: write` is not granted to fork tokens.
- **Secrets**: none required at runtime (the app makes no outbound network calls per the local-only NFR). The release pipeline itself uses the workflow's automatic `GITHUB_TOKEN` via `softprops/action-gh-release@v2.6.2`. **As of Feb 2, 2026 the default `GITHUB_TOKEN` is read-only**, so the workflow MUST declare `permissions: contents: write` explicitly. If a code-signing cert is added later, the cert + password live in GitHub Encrypted Secrets at the repo level. If winget is adopted, a fine-grained PAT for `vedantmgoyal9/winget-releaser@v2` lives in the same secret store with `public_repo` scope only.
- **Rollback**: two flavors. (a) **Distribution rollback** — `gh release delete v0.X.Y` then `gh release upload <previous-tag> <previous-installer>` to reinstate; users who already downloaded the broken version stay broken until they re-download. (b) **Fix forward** — push `v0.X.(Y+1)` with the fix. Time-to-revert: minutes for distribution rollback, one CI cycle (~5–10 min) for fix-forward. Data caveat: `%APPDATA%\BreakReminder` schema changes do not roll back; a rolled-back binary may fail to read forward-versioned settings.
- **Approval**: the human is the tag-pusher. Pushing a `v*` tag is the explicit publish approval; agents may run the full build/test/audit pipeline unattended on `main`, but cannot publish a release without a human-pushed tag. This matches FR-001's distribution intent (deliberate, versioned releases). Agent-driven publish via the GitHub MCP server is **not currently supported** because the MCP release tools are read-only as of v1.0.5 — agents must shell out to `gh` for publish operations.
- **Logs**: `gh run list --workflow=release.yml`, `gh run view <run-id>`, `gh run view <run-id> --log` for full pipeline output. Runtime logs do not exist remotely (the app writes only to `%APPDATA%\BreakReminder\events.log` per FR-015; no network sink). For agent-readable structured access: the GitHub MCP Server exposes runs, jobs, steps, artifacts, and releases as typed tools (read-only).

## Risk Register

| Risk | Source | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| SmartScreen "Unrecognized app" warning suppresses installs | Devil's advocate | High | High | Acquire a code-signing certificate when user count justifies (~$300–500/yr EV; OV ~$100–300/yr). **Update vs prior file**: even an EV cert no longer bypasses SmartScreen on first download since 2025; budget for reputation rebuild time too. Until then, document the "More info → Run anyway" path in `README.md` and the GitHub Release notes. |
| `GITHUB_TOKEN` read-only default (Feb 2026) silently breaks unmaintained workflows | Devil's advocate | Medium | High | Declare `permissions: contents: write` explicitly at the workflow or job level in `release.yml`. Pin a comment at the top of the file referencing the 2026-02-02 GitHub change so contributors don't strip it. Add a CI smoke step that asserts the permission is present. |
| GitHub MCP server release tools are read-only — agent cannot publish via MCP | Devil's advocate / Unknown unknowns | Medium | Low | Document in `AGENTS.md` that release publishing must shell out to `gh release create`. Track GitHub MCP server changelog for `create_release` / `upload_release_asset` GA. |
| NSIS expertise becomes a maintenance bottleneck | Devil's advocate | Medium | Medium | Keep `break-reminder.nsi` minimal; document every directive inline; avoid custom NSIS plugins. If complexity grows, evaluate WiX (MSI) or Inno Setup migration. |
| Users stay on stale versions because no native auto-update exists | Pre-mortem | High | Medium | Add a manual "Check for updates" tray menu item in v1.x that opens the GitHub Releases page in the user's default browser via `QDesktopServices.openUrl`. No auto-update infra, respects local-only NFR. Adopt winget as a secondary channel when justified — `winget upgrade --all` provides the auto-update layer without changing the local-only NFR (the upgrade is performed by winget, not by the app). |
| GitHub Releases removal breaks distribution | Devil's advocate | Low | High | Maintain a personal mirror copy of every signed installer in offline storage; document the recovery path in `AGENTS.md`. |
| Per-publisher SmartScreen reputation does not transfer between certs | Unknown unknowns | Medium | Medium | If switching CAs, plan for a 1–2 week reputation rebuild window; coordinate with a release that has minimal user-visible changes. |
| `pynput` dynamic-import drift silently breaks activity tracking | Unknown unknowns | Low | High | Add a smoke test to the release pipeline that imports every `pynput.keyboard` and `pynput.mouse` submodule from inside the bundled binary; fail CI if any submodule is missing post-PyInstaller. |
| `--windowed` swallows bootstrap panics; user sees "nothing happened" | Unknown unknowns | Medium | Medium | Wrap the entry point in a top-level `try/except` that writes a crash log to `%APPDATA%\BreakReminder\bootstrap-error.log` and surfaces a `MessageBox` before exit. |
| `softprops/action-gh-release@v2` Node-runtime deprecation (~2027) | Unknown unknowns | Medium | Low | Track the action's release notes; plan a migration window to v3.x (Node 24). The change is a single-line bump in the workflow YAML. |
| `PyWinSparkle` / `PyUpdater` unmaintained — no in-app update library available | Unknown unknowns | Low | Low | If in-app update notification is desired, implement a custom polling check against the GitHub Releases REST API (`GET /repos/<owner>/break-reminder/releases/latest`) plus `QDesktopServices.openUrl` to the Releases page. Stay clear of unmaintained Sparkle ports. |
| Fork PRs cannot publish, but can ship a build that breaks on the publish step | Research finding | Low | Low | Already mitigated: the publish step is gated on tag refs; PRs cannot reach it. Documented for future contributors. |

## Getting Started

The pipeline is already running for the recommended channel. These are pre-staged actionable mitigations from the risk register, ordered by likely time-to-actionable. Commands are version-pinned against `tech-stack.md` (PyInstaller 6.20.0; `softprops/action-gh-release@v2.6.2`; `actions/upload-artifact@v4`).

1. **Declare workflow-level permissions explicitly.** Add to the top of [.github/workflows/release.yml](.github/workflows/release.yml):

   ```yaml
   permissions:
     contents: write   # required since 2026-02-02 — GITHUB_TOKEN default is read-only
   ```

   This is the single most consequential change to make today; without it, the next release silently fails at publish.

2. **Bootstrap-panic safety net.** Wrap `main.py`'s entry point in a top-level `try/except` that writes to `%APPDATA%\BreakReminder\bootstrap-error.log` and shows a `ctypes.windll.user32.MessageBoxW` before exit. Catches the `--windowed` silent-failure mode without adding any runtime dependency.

3. **Manual update-check menu item.** Add a tray menu entry "Check for updates" that opens `https://github.com/<owner>/break-reminder/releases/latest` via `QDesktopServices.openUrl`. Pure-Python, no auto-update server, respects the local-only NFR.

4. **`pynput` submodule smoke test.** Extend the release workflow with a step after PyInstaller build that runs the bundled binary in a sandboxed mode (e.g. `BreakReminder.exe --self-test`) which imports every `pynput` submodule and exits non-zero on `ImportError`.

5. **(Future) winget as secondary channel.** When user count justifies adopting winget, add a separate workflow that triggers `vedantmgoyal9/winget-releaser@v2` on tag push. The manifest will reference the existing GHR-published `.exe` via `InstallerUrl`; no change to the PyInstaller or NSIS step is required. Sample manifest snippet (the `release.yml` step):

   ```yaml
   - name: Submit winget manifest
     uses: vedantmgoyal9/winget-releaser@v2
     with:
       identifier: <Publisher>.BreakReminder
       installers-regex: 'BreakReminder-Setup-.*\.exe$'
       token: ${{ secrets.WINGET_TOKEN }}
   ```

   The `WINGET_TOKEN` is a fine-grained PAT scoped to `public_repo` only; rotate annually.

6. **(When SmartScreen friction crosses the actionability threshold)** Acquire a code-signing certificate (DigiCert / Sectigo / GlobalSign / SSL.com all sell EV certs at $300–500/yr; OV at $100–300/yr). Wire `signtool sign /tr http://timestamp.sectigo.com /td sha256 /fd sha256` into `release.yml` between the PyInstaller and NSIS steps; cert + password live in GitHub Encrypted Secrets. Note the 2025 caveat: even an EV cert no longer guarantees first-download SmartScreen suppression — budget for reputation rebuild time.

## Out of Scope

The following were not evaluated in this research:

- Web hosting platforms (Cloudflare / Vercel / Netlify / Fly.io / Railway / Render). Hard-filtered out of scope for a desktop app; revisit if a server-side component is added to the PRD.
- **Microsoft Store** — hard-filtered by Q1 (no code-signing). Revisit if a code-signing budget appears.
- Code-signing certificate vendor comparison (DigiCert / Sectigo / GlobalSign / SSL.com). Mentioned in the risk register; selection deferred until SmartScreen friction crosses the actionability threshold.
- CI/CD pipeline configuration changes — `release.yml` is treated as input, not output. Modifications belong to a separate `/10x-implement` pass.
- Production-scale architecture (multi-region, HA, DR) — not applicable to a local-only desktop app.
- In-depth Velopack / Squirrel.Windows / NetSparkle evaluation — these are auto-update libraries, not distribution channels; their adoption is a separate decision conditional on the local-only NFR being relaxed (currently it isn't, per the PRD non-goals).
