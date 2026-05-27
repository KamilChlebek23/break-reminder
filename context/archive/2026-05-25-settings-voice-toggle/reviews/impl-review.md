<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Settings — Voice Toggle and Phrase Editor

- **Plan**: `context/changes/settings-voice-toggle/plan.md`
- **Scope**: Phases 1–2 of 2 (full plan)
- **Date**: 2026-05-25
- **Verdict**: APPROVED
- **Findings**: 0 critical · 2 warnings · 4 observations

## Verdicts

| Dimension            | Verdict |
|----------------------|---------|
| Plan Adherence       | PASS    |
| Scope Discipline     | PASS    |
| Safety & Quality     | WARNING |
| Architecture         | PASS    |
| Pattern Consistency  | PASS    |
| Success Criteria     | PASS    |

## Findings

### F1 — Validation tooltip can anchor to a hidden Notifications tab

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: `break_reminder/ui/settings_dialog.py:315-325`
- **Detail**: `QDialogButtonBox` lives at the dialog level, so the user can be on the Scheduling tab when they click OK. If the (voice on, blank phrase) gate trips, `QToolTip.showText` anchors to `_voice_phrase_edit` — but that widget is on the inactive Notifications tab and not visible. The user sees a floating "Voice phrase cannot be empty when voice is enabled." message anchored to nothing they can see, with no obvious cue to switch tabs.
- **Fix A ⭐ Recommended**: Switch to the Notifications tab before showing the tooltip
  - Strength: User lands on the wrong field with the tooltip anchored to a visible widget. One line at the start of the early-return branch plus storing the tab widget reference at build time.
  - Tradeoff: Adds a tab-reference attribute on the dialog and a small conditional jump on every save attempt — minor.
  - Confidence: HIGH — `QTabWidget.setCurrentIndex` is standard; `_tabs` already exists.
  - Blind spot: None significant. Test coverage needs one new assertion that the active tab flipped to "Notifications" after the gate trips.
- **Fix B**: Focus the line edit instead — `setFocus()` auto-activates the parent tab
  - Strength: Even shorter — `self._voice_phrase_edit.setFocus()` before the tooltip; Qt brings the parent tab forward as a side effect.
  - Tradeoff: Side-effect-driven semantics are subtler; future readers may miss why focus alone changes the visible tab.
  - Confidence: MEDIUM — relies on Qt focus-policy behavior that's correct in PySide6 but is implicit, not documented at the call site.
  - Blind spot: If a future Qt version changes focus-into-hidden-tab semantics, this silently breaks.
- **Decision**: FIXED via Fix A (stored `_notifications_tab` ref; `accept()` calls `setCurrentWidget` before tooltip; new assertion in `test_voice_on_blank_phrase_blocks_save`)

### F2 — Atomic-save behavior is correct but not pinned by tests

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: `tests/test_settings_dialog.py:570-595` (`test_voice_on_blank_phrase_blocks_save`)
- **Detail**: The plan explicitly designed atomic save: "a partial save (voice flipped but phrase rejected) cannot land on disk". The implementation honors it via early-return before any setter writes. But the test only asserts `voice_enabled` and `voice_phrase` stayed at their pre-set values — not the break-interval. If a future refactor reorders so the break-interval write happens before the validation gate, no test fires.
- **Fix**: Extend `test_voice_on_blank_phrase_blocks_save` to set `dialog._break_interval_spinbox.setValue(<distinct value>)` before `dialog.accept()` and assert `settings.break_interval_min` did NOT change. One additional assertion line.
- **Decision**: FIXED (folded into the F1 edit — `test_voice_on_blank_phrase_blocks_save` now sets `break_interval_min = 60` on the persisted side, edits the spinbox to 30, and asserts the persisted value stays at 60 after the gate trips)

### F3 — Test button does not debounce; rapid clicks queue serialized speech

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — UX polish, not a defect
- **Dimension**: Safety & Quality
- **Location**: `break_reminder/ui/settings_dialog.py:241-250`, `break_reminder/notifications/voice.py:40-51`
- **Detail**: Five rapid clicks queue five copies of the speech. `VoiceNotifier._current` only tracks the latest future, so earlier ones can't be cancelled by `stop()`. Not a crash — just a UX annoyance.
- **Fix**: Disable the button during in-flight speech via a `done_callback`, OR call `self._voice.stop()` first so each click cancels the prior one.
- **Decision**: FIXED via the simpler `stop()`-first variant (`_on_test_voice_clicked` now calls `self._voice.stop()` before `self._voice.speak(...)`; `StubVoiceNotifier` got a `stop_calls` counter; new `test_click_cancels_prior_in_flight_speech` pins the contract)

### F4 — Whitespace-only phrase passes Test silently

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Safety & Quality
- **Location**: `break_reminder/ui/settings_dialog.py:241-250`, `break_reminder/notifications/voice.py:42`
- **Detail**: `VoiceNotifier.speak` short-circuits on `if not phrase`, but `not "   "` is False — so a whitespace-only phrase clicked through Test reaches `pyttsx3` and produces no audible output. The save-time gate already strips whitespace; Test does not.
- **Fix**: Tighten `VoiceNotifier.speak` to short-circuit on `not phrase.strip()` (single line in `voice.py`; benefits every caller).
- **Decision**: FIXED (`speak()` gate now reads `if not phrase or not phrase.strip(): return`; new `tests/test_voice.py` with 5 tests pinning the empty / whitespace-only / non-empty / leading-trailing-whitespace contracts)

### F5 — `voice_phrase` setter accepts non-string inputs without coercion

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Safety & Quality
- **Location**: `break_reminder/storage/settings.py:170-186`
- **Detail**: `voice_enabled.setter` coerces via `bool(value)`. `voice_phrase.setter` does not coerce — passing `Path("…")` or `int` would store an unexpected representation. The getter does `str(value)` on read so reads are safe, but writes are asymmetric with the bool setter.
- **Fix**: Either coerce with `str(phrase)` for symmetry, or add a one-line note to the docstring stating no coercion is done.
- **Decision**: FIXED via the documentation variant — `voice_phrase.setter` docstring now explicitly notes no coercion + cites impl-review F5. No behavior change; the contract is now visible to anyone reading the setter.

### F6 — Pre-existing setters (`paused`, `break_interval_min`) lack docstrings

- **Severity**: 📝 OBSERVATION
- **Impact**: 🏃 LOW — pre-existing; this slice deviated in the right direction
- **Dimension**: Pattern Consistency
- **Location**: `break_reminder/storage/settings.py:124-131` (`break_interval_min`), `break_reminder/storage/settings.py:198-203` (`paused`)
- **Detail**: The new `voice_*` setters have full Google-style docstrings per the `context/foundation/lessons.md` rule. The two pre-existing setters in the same file have only inline comments. Not a regression introduced by this slice — it just made the inconsistency newly visible.
- **Fix**: Backfill Google-style docstrings on the two old setters in the same change for file-wide consistency, OR accept the divergence and let old setters catch up incrementally.
- **Decision**: FIXED — both `break_interval_min.setter` and `paused.setter` now carry full Google-style docstrings (`Args:` blocks; the int setter additionally documents its `Raises: ValueError` contract). The whole file is now lessons.md-compliant on the setter side.
