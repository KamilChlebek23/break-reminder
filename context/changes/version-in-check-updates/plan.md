# Version in "Check for updates" Implementation Plan

## Overview

Replace the silent browser-redirect inside `BreakReminderApp._on_check_for_updates` ([break_reminder/app.py:295-304](../../../break_reminder/app.py)) with a `QMessageBox` that shows the installed version (`break_reminder.__version__`), the app description (lifted from `pyproject.toml`), and two buttons: "Open Releases" (default — does today's `QDesktopServices.openUrl(QUrl(RELEASES_URL))` hop) and "Close" (dismisses without browsing). The user's literal request — "I would like user to see what is current version of application installed on his PC" — is satisfied by making the version visible the moment the click lands, before the browser opens.

## Current State Analysis

- The "Check for updates" QAction is wired at [break_reminder/app.py:213-215](../../../break_reminder/app.py); its slot at [break_reminder/app.py:295-304](../../../break_reminder/app.py) opens `RELEASES_URL` ([break_reminder/app.py:42-45](../../../break_reminder/app.py)) directly via `QDesktopServices.openUrl(QUrl(RELEASES_URL))`.
- `__version__ = "0.2.0"` exists at [break_reminder/__init__.py:7](../../../break_reminder/__init__.py); single source of truth, kept in lockstep with `pyproject.toml` and `installer/break-reminder.nsi` by the v0.2.0 release-prep commit `9b6d55c`.
- `QMessageBox` is already imported at [break_reminder/app.py:25](../../../break_reminder/app.py) (used by the no-tray bootstrap-error message at lines 389-393), so the dialog choice is consistent with existing UI vocabulary.
- `APPLICATION_NAME` is exported by `break_reminder.storage.paths` and is the canonical app-name string used everywhere in tooltips/menus.
- No test currently exercises `_on_check_for_updates`. The closest pattern is `TestOpenSettingsAction` in [tests/test_app.py:291](../../../tests/test_app.py), which monkeypatches `break_reminder.app.SettingsDialog` to capture constructor kwargs and asserts on the captured calls.

## Desired End State

The user opens the tray context menu, clicks "Check for updates", and a modal `QMessageBox` titled "About BreakReminder" appears immediately. The dialog body shows: `BreakReminder v0.2.0` (bold), the app's description from `pyproject.toml` ("A Windows-11 break reminder for phone-free deep-focus workspaces."), and a one-line action prompt ("Click 'Open Releases' to see if a newer version is available."). Two buttons sit at the bottom — "Open Releases" (default, fires `QDesktopServices.openUrl(QUrl(RELEASES_URL))` exactly like today) and "Close" (dismisses without browsing). The local-only NFR is preserved — no network call from inside the app.

### Key Discoveries:

- The version is already accessible via a single import: `from break_reminder import __version__`. No new constants or imports needed beyond the version itself.
- `QMessageBox` supports custom button rows via `box.addButton(label, ButtonRole)` and identifies which one was clicked via `box.clickedButton()`. This is the exact mechanism the new slot needs.
- The description string lives at `pyproject.toml:4`. The two cleanest sources of truth are (a) hardcode the string in `app.py` with a comment pointing at `pyproject.toml`, or (b) read it via `importlib.metadata.metadata("break-reminder")["Summary"]`. Option (a) is preferred for this slice — `importlib.metadata` adds runtime-environment dependence (the package must be installed metadata-wise, which is true in production but adds friction in editable / source-tree dev runs); a hardcoded string with a comment is simpler and the description rarely changes.
- The `RELEASES_URL` constant stays untouched and the existing `QDesktopServices.openUrl` call is preserved verbatim — only its trigger condition changes (now gated on which button the user clicked).

## What We're NOT Doing

- No GitHub API call to detect whether a newer release actually exists. The user opens the Releases page manually and compares — same as today, just with the local version now visible. (Local-only NFR preserved.)
- No release-notes / changelog display in the dialog body.
- No "About" tab inside `SettingsDialog`. The version dialog is a separate, transient `QMessageBox` triggered exclusively from the tray menu.
- No change to the "Check for updates" menu item's label, position, or shortcut. The string stays "Check for updates"; only the click handler changes.
- No new menu items. The slice does not add an "About BreakReminder…" entry — that would expand the menu by a row and the user explicitly picked the hybrid (intercept) shape.
- No autostart, snooze, or reminder work. Strictly the version-in-update-flow surface.

## Implementation Approach

The slot becomes a thin "build a `QMessageBox`, run it modally, branch on the clicked button" function. The two buttons are added explicitly via `box.addButton(...)`; the default button is the "Open Releases" one so Enter triggers today's browser hop. After `box.exec()` returns, the slot inspects `box.clickedButton()` and only fires `QDesktopServices.openUrl(QUrl(RELEASES_URL))` if the user clicked "Open Releases". A user who picked "Close" (or hit Esc) gets a no-op.

The version comes from `from break_reminder import __version__` at the top of `app.py`. The app name comes from the existing `APPLICATION_NAME` import. The description is a single hardcoded string with a comment pointing at `pyproject.toml:4` so a future maintainer knows to keep them in sync.

Tests mirror `TestOpenSettingsAction`'s monkeypatch pattern: replace `break_reminder.app.QMessageBox` with a recording stub, trigger the QAction's `triggered` signal, and assert on (a) the kwargs the stub captured (text contains version + description), (b) the conditional `QDesktopServices.openUrl` call (fires when Open is clicked, NOT fires when Close is clicked).

## Critical Implementation Details

- **Stub design for "which button was clicked"**: `QMessageBox.clickedButton()` returns the actual button object passed to `addButton(...)`. The test stub must record buttons in the order they're added and let the test pre-declare which label "was clicked". The cleanest shape is a class whose `addButton(label, role)` returns and stores a real `QPushButton` keyed by label, and whose `exec()` is a no-op that returns the role of the pre-declared "clicked" button. The slot's subsequent `box.clickedButton() is open_button` identity check then resolves correctly because the same object the slot called `addButton` for is what the stub returns from `clickedButton()`. This is the only non-obvious bit in the test surface.

## Phase 1: Intercept dialog + automated test

### Overview

Rewrite `_on_check_for_updates` to show the version-aware `QMessageBox` and conditionally chain into the existing browser-open path. Add a new `TestCheckForUpdatesAction` test class.

### Changes Required:

#### 1. Rewrite `_on_check_for_updates` in `app.py`

**File**: `break_reminder/app.py`

**Intent**: Replace the unconditional `QDesktopServices.openUrl(QUrl(RELEASES_URL))` with a `QMessageBox` that shows the installed version + app description and a two-button row; the browser opens only when the user clicks "Open Releases".

**Contract**:
- New import `from break_reminder import __version__` at the top of the file alongside the other imports.
- New module-level constant `_APP_DESCRIPTION = "A Windows-11 break reminder for phone-free deep-focus workspaces."` near `RELEASES_URL`, with a `# Mirror of pyproject.toml:4 — keep in sync when the description changes.` comment.
- `_on_check_for_updates` builds a `QMessageBox` with `Icon.Information`, `windowTitle = f"About {APPLICATION_NAME}"`, `text = f"<b>{APPLICATION_NAME} v{__version__}</b>"`, `informativeText = f"{_APP_DESCRIPTION}\n\nClick 'Open Releases' to see if a newer version is available."`, two added buttons ("Open Releases" with `AcceptRole`, "Close" with `RejectRole`), the Open button as default, then `box.exec()`, then a `box.clickedButton() is open_button` guard around the existing `QDesktopServices.openUrl(QUrl(RELEASES_URL))` line.
- Docstring updated to reflect the new "show version, then optionally open browser" behavior. Existing rationale paragraph (no network calls; local-only NFR) is preserved.

#### 2. Add `TestCheckForUpdatesAction` to `tests/test_app.py`

**File**: `tests/test_app.py`

**Intent**: Pin the new behavior — dialog shows version + description, "Open Releases" opens `RELEASES_URL`, "Close" does not.

**Contract**: New `TestCheckForUpdatesAction` class mirroring `TestOpenSettingsAction` (lines 291-340 today). Five tests:
- `test_action_label_is_check_for_updates` — sanity check that the QAction's text is unchanged ("Check for updates").
- `test_dialog_text_includes_installed_version` — monkeypatch `break_reminder.app.QMessageBox` with a recording stub, trigger the action, assert captured `text` contains `__version__`.
- `test_dialog_text_includes_app_description` — same fixture, assert captured `informativeText` contains the pyproject description verbatim.
- `test_open_releases_button_opens_url` — stub `QMessageBox` so `clickedButton()` returns the "Open Releases" button; monkeypatch `QDesktopServices.openUrl`; trigger the action; assert `openUrl` was called once with `QUrl(RELEASES_URL)`.
- `test_close_button_does_not_open_url` — stub `QMessageBox` so `clickedButton()` returns the "Close" button; monkeypatch `QDesktopServices.openUrl`; trigger the action; assert `openUrl` was NOT called.

The "which button was clicked" stubbing is the trickiest part — see the `Critical Implementation Details` section above. The stub class lives at module level next to `FakeVoice` and is reused across all five tests (the per-test variation is just which button-label is pre-declared as "clicked").

### Success Criteria:

#### Automated Verification:

- Unit tests pass: `uv run pytest tests/test_app.py::TestCheckForUpdatesAction`
- Full suite still passes: `uv run pytest`
- Type check passes: `uv run pyright break_reminder/app.py tests/test_app.py`
- Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/app.py tests/test_app.py`
- Format check passes: `uv run ruff format --check break_reminder/app.py tests/test_app.py`

#### Manual Verification:

(All deferred to Phase 2.)

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation before proceeding to Phase 2. The corresponding `- [ ]` checkboxes for these items live in the `## Progress` section at the bottom of the plan.

---

## Phase 2: Manual smoke + bookkeeping

### Overview

Verify the dialog renders correctly on a real running tray and that both buttons behave as documented. Flip `change.md` status to `implemented`. No roadmap entry for this slice (off-roadmap discovery), so no roadmap edit.

### Changes Required:

#### 1. Manual smoke checklist

**File**: human verification (no code change)

**Intent**: Confirm the dialog body, title, button order, default button, and click handlers all behave as designed against the actual installed binary.

**Contract**:
- Run the app from source via `uv run python main.py` OR install the v0.2.0 NSIS installer; either path is fine.
- Right-click the tray icon, click "Check for updates".
- Verify: dialog title contains "About BreakReminder"; body shows "BreakReminder v0.2.0" and the description; two buttons present labeled exactly "Open Releases" and "Close"; Enter key (or default button highlight) targets "Open Releases".
- Click "Close" — dialog dismisses, no browser opens.
- Re-open and click "Open Releases" — dialog dismisses, browser opens to `https://github.com/KamilChlebek23/break-reminder/releases/latest`.

#### 2. `change.md` status flip

**File**: `context/changes/version-in-check-updates/change.md`

**Intent**: Reflect that the slice has shipped.

**Contract**: After manual smoke passes, set `status: implemented` and `updated: <today>`.

### Success Criteria:

#### Automated Verification:

- (None — Phase 2 is human-driven.)

#### Manual Verification:

- Dialog title is "About BreakReminder".
- Dialog body shows the bold "BreakReminder v0.2.0" line.
- Dialog body shows the pyproject description ("A Windows-11 break reminder for phone-free deep-focus workspaces.").
- Two buttons exist with labels "Open Releases" and "Close".
- "Open Releases" is the default (Enter triggers it; visually highlighted).
- "Close" dismisses the dialog without opening any browser.
- "Open Releases" opens `https://github.com/KamilChlebek23/break-reminder/releases/latest` in the default browser.
- `change.md` flipped from `implementing` (set by `/10x-implement`) to `implemented`.

---

## Testing Strategy

### Unit Tests:

- 5 new tests in `TestCheckForUpdatesAction` (label sanity, version-in-text, description-in-text, Open-opens-URL, Close-does-not-open). All use the monkeypatch pattern already established in `TestOpenSettingsAction`.
- Edge cases tested: the no-op path on "Close" (regression-pin so a future refactor can't accidentally re-introduce the unconditional browser hop).

### Integration Tests:

- None — the slice is too small to warrant a separate integration test layer.

### Manual Testing Steps:

1. Run the app (source or installer).
2. Right-click the tray icon, click "Check for updates" — verify dialog title, body, and default button.
3. Click "Close" — verify dialog dismisses with no browser side-effect.
4. Re-open dialog, click "Open Releases" — verify dialog dismisses AND the GitHub Releases page opens in the default browser.
5. Re-open dialog, hit Esc — verify dismissal without browser hop (Esc maps to RejectRole, same as Close).

## Performance Considerations

None. The slice adds one modal `QMessageBox` construction per click, which is negligible.

## Migration Notes

None. Pure UX add to an existing slot; no persisted state, no schema, no installer changes, no behavior change beyond the inserted dialog step.

## References

- Bootstrap notes: `context/changes/version-in-check-updates/change.md`
- Existing slot: [break_reminder/app.py:295-304](../../../break_reminder/app.py)
- Existing `QMessageBox` use in this module: [break_reminder/app.py:389-393](../../../break_reminder/app.py)
- Test pattern to mirror: [tests/test_app.py:291-340](../../../tests/test_app.py) (`TestOpenSettingsAction`)
- Project lessons (Google-style docstrings on every public function): [context/foundation/lessons.md](../../foundation/lessons.md)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Intercept dialog + automated test

#### Automated

- [x] 1.1 Unit tests pass: `uv run pytest tests/test_app.py::TestCheckForUpdatesAction`
- [x] 1.2 Full suite still passes: `uv run pytest`
- [x] 1.3 Type check passes: `uv run pyright break_reminder/app.py tests/test_app.py`
- [x] 1.4 Lint passes (incl. `D` rule group): `uv run ruff check break_reminder/app.py tests/test_app.py`
- [x] 1.5 Format check passes: `uv run ruff format --check break_reminder/app.py tests/test_app.py`

### Phase 2: Manual smoke + bookkeeping

#### Manual

- [ ] 2.1 Dialog title is "About BreakReminder"
- [ ] 2.2 Dialog body shows the bold "BreakReminder v0.2.0" line
- [ ] 2.3 Dialog body shows the pyproject description
- [ ] 2.4 Two buttons exist with labels "Open Releases" and "Close"
- [ ] 2.5 "Open Releases" is the default (Enter triggers it)
- [ ] 2.6 "Close" dismisses the dialog without opening a browser
- [ ] 2.7 "Open Releases" opens the GitHub Releases URL in the default browser
- [ ] 2.8 change.md flipped from `implementing` to `implemented`
