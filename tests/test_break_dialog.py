"""Tests for ``BreakDialog`` — the FR-009 / US-02 product wedge.

Covers every dismiss path the dialog overrides:
  * Escape key — swallowed by ``keyPressEvent``.
  * ``close()`` (proxy for Alt+F4 / system close button) — refused unless
    a deliberate action set ``_user_action``.
  * Window flags — ``WindowStaysOnTopHint``, ``CustomizeWindowHint``,
    ``WindowTitleHint`` (no system close button).
  * ``WA_ShowWithoutActivating`` + ``NoFocus`` — implements US-02
    (in-flight keystroke completes in the previously focused app).

Plus the action-button paths:
  * "Take a break" → ``outcome_chosen('taken')`` + dialog closes.
  * "Snooze" → ``outcome_chosen('snoozed')`` + dialog closes.
  * Snooze button disabled when ``snooze_remaining=0``.
  * Voice notifier is stopped on either action.

We use pytest-qt's ``qtbot`` for QApplication management and signal
waiting. ``qtbot.addWidget`` ensures every dialog is destroyed at test
teardown, regardless of test outcome.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from break_reminder.notifications.break_dialog import BreakDialog, BreakOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_button(dialog: BreakDialog, text_substring: str) -> QPushButton:
    """Locate a child button by case-insensitive substring of its label."""
    for btn in dialog.findChildren(QPushButton):
        if text_substring.lower() in btn.text().lower():
            return btn
    raise LookupError(f"No button matching {text_substring!r}")


class FakeVoice:
    """Minimal stand-in for ``VoiceNotifier``.

    Only ``stop()`` is exercised by the dialog's action handlers, so we
    just count how many times it was invoked.
    """

    def __init__(self) -> None:
        """Construct the stub with a zeroed ``stop_calls`` counter."""
        self.stop_calls = 0

    def stop(self) -> None:
        """Record one ``stop()`` invocation by incrementing ``stop_calls``."""
        self.stop_calls += 1


@pytest.fixture
def dialog(qtbot) -> BreakDialog:
    """A ``BreakDialog`` with one snooze remaining, registered with ``qtbot``."""
    d = BreakDialog(snooze_remaining=1, voice_notifier=None)
    qtbot.addWidget(d)
    return d


# ---------------------------------------------------------------------------
# FR-009 — dismiss paths must NOT close the dialog
# ---------------------------------------------------------------------------


class TestDismissPathOverrides:
    """FR-009 — every dismiss path must NOT close the dialog."""

    def test_escape_does_not_dismiss(self, qtbot, dialog: BreakDialog) -> None:
        """Pressing Escape leaves the dialog visible (FR-009)."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.isVisible()

    def test_close_event_is_refused_without_user_action(self, qtbot, dialog: BreakDialog) -> None:
        """``close()`` is refused before any action button has been pressed."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        # close() returns False when closeEvent ignores the event.
        # Alt+F4 and the system close button both route through
        # closeEvent, so this single assertion covers all three.
        assert dialog.close() is False
        assert dialog.isVisible()

    def test_repeated_close_attempts_all_refused(self, qtbot, dialog: BreakDialog) -> None:
        """Each repeated ``close()`` is refused — the guard does not wear out."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        for _ in range(5):
            assert dialog.close() is False
        assert dialog.isVisible()

    def test_non_escape_keys_pass_to_parent(self, qtbot, dialog: BreakDialog) -> None:
        """Non-Escape keys delegate to ``QDialog`` and do not dismiss the dialog."""
        # Non-Escape keys are forwarded to QDialog.keyPressEvent (which
        # may or may not do anything, but must not crash and must not
        # dismiss the dialog).
        with qtbot.waitExposed(dialog):
            dialog.show()
        QTest.keyClick(dialog, Qt.Key.Key_A)
        QTest.keyClick(dialog, Qt.Key.Key_Space)
        assert dialog.isVisible()


# ---------------------------------------------------------------------------
# Window-flag and attribute setup (US-02 + FR-009 frame customization)
# ---------------------------------------------------------------------------


class TestWindowFlagsAndAttributes:
    """Window flags and attributes implementing FR-009 / US-02."""

    def test_stays_on_top(self, dialog: BreakDialog) -> None:
        """``WindowStaysOnTopHint`` is set so the dialog is never hidden."""
        flags = dialog.windowFlags()
        assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)

    def test_customize_and_title_flags_set(self, dialog: BreakDialog) -> None:
        """``CustomizeWindowHint`` + ``WindowTitleHint`` strip the close button."""
        # Together these strip the system close button while keeping the
        # title bar — see FR-009 docstring in break_dialog.py.
        flags = dialog.windowFlags()
        assert bool(flags & Qt.WindowType.CustomizeWindowHint)
        assert bool(flags & Qt.WindowType.WindowTitleHint)

    def test_show_without_activating_attribute(self, dialog: BreakDialog) -> None:
        """``WA_ShowWithoutActivating`` is set so the dialog never steals focus (US-02)."""
        assert dialog.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def test_focus_policy_is_no_focus(self, dialog: BreakDialog) -> None:
        """Focus policy is ``NoFocus`` — focus can't slide into a child either (US-02)."""
        # Belt-and-suspenders for US-02: even if focus reaches the
        # window, it can't propagate into any focusable child.
        assert dialog.focusPolicy() == Qt.FocusPolicy.NoFocus


# ---------------------------------------------------------------------------
# Action-button paths — these are the only legitimate exits
# ---------------------------------------------------------------------------


class TestTakeBreakButton:
    """The 'I'll take a break' button — FR-009's deliberate-exit path."""

    def test_emits_taken_outcome(self, qtbot, dialog: BreakDialog) -> None:
        """Clicking the take-a-break button emits ``BreakOutcome.TAKEN``."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        with qtbot.waitSignal(dialog.outcome_chosen, timeout=500) as blocker:
            _find_button(dialog, "take a break").click()
        assert blocker.args == [BreakOutcome.TAKEN.value]

    def test_closes_the_dialog(self, qtbot, dialog: BreakDialog) -> None:
        """Clicking the take-a-break button is the deliberate close path."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        _find_button(dialog, "take a break").click()
        # close() called by the handler should be accepted because
        # _user_action was set first.
        assert not dialog.isVisible()

    def test_outcome_value_matches_enum(self, qtbot, dialog: BreakDialog) -> None:
        """The signal payload equals ``BreakOutcome.TAKEN.value`` (the literal ``"taken"``)."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        captured: list[str] = []
        dialog.outcome_chosen.connect(lambda v: captured.append(v))
        _find_button(dialog, "take a break").click()
        assert captured == ["taken"]


class TestSnoozeButton:
    """The Snooze button — FR-009's deferral path, gated by FR-010's cap."""

    def test_emits_snoozed_outcome(self, qtbot, dialog: BreakDialog) -> None:
        """Clicking Snooze emits ``BreakOutcome.SNOOZED``."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        with qtbot.waitSignal(dialog.outcome_chosen, timeout=500) as blocker:
            _find_button(dialog, "snooze").click()
        assert blocker.args == [BreakOutcome.SNOOZED.value]

    def test_closes_the_dialog(self, qtbot, dialog: BreakDialog) -> None:
        """Clicking Snooze is the second deliberate close path."""
        with qtbot.waitExposed(dialog):
            dialog.show()
        _find_button(dialog, "snooze").click()
        assert not dialog.isVisible()

    def test_disabled_when_no_snoozes_remaining(self, qtbot) -> None:
        """Snooze button is disabled when ``snooze_remaining=0`` (FR-010 cap)."""
        # When the FR-010 cap is hit, the button must be disabled — the
        # only legitimate exit is "Take a break".
        d = BreakDialog(snooze_remaining=0)
        qtbot.addWidget(d)
        assert not _find_button(d, "snooze").isEnabled()

    def test_enabled_when_snoozes_remaining(self, qtbot) -> None:
        """Snooze button is enabled while ``snooze_remaining > 0``."""
        d = BreakDialog(snooze_remaining=3)
        qtbot.addWidget(d)
        assert _find_button(d, "snooze").isEnabled()

    def test_label_shows_remaining_count(self, qtbot) -> None:
        """Snooze button label displays the remaining-count number."""
        d = BreakDialog(snooze_remaining=2)
        qtbot.addWidget(d)
        assert "2" in _find_button(d, "snooze").text()


# ---------------------------------------------------------------------------
# Voice integration — voice must stop on either action (FR-007)
# ---------------------------------------------------------------------------


class TestVoiceIntegration:
    """Voice integration — voice must stop on either action (US-02)."""

    def test_take_break_stops_voice(self, qtbot) -> None:
        """Take-a-break stops the voice notifier exactly once (US-02)."""
        voice = FakeVoice()
        d = BreakDialog(snooze_remaining=1, voice_notifier=voice)
        qtbot.addWidget(d)
        with qtbot.waitExposed(d):
            d.show()
        _find_button(d, "take a break").click()
        assert voice.stop_calls == 1

    def test_snooze_stops_voice(self, qtbot) -> None:
        """Snooze stops the voice notifier exactly once (US-02)."""
        voice = FakeVoice()
        d = BreakDialog(snooze_remaining=1, voice_notifier=voice)
        qtbot.addWidget(d)
        with qtbot.waitExposed(d):
            d.show()
        _find_button(d, "snooze").click()
        assert voice.stop_calls == 1

    def test_no_voice_notifier_does_not_crash(self, qtbot) -> None:
        """A dialog with ``voice_notifier=None`` accepts an action without raising."""
        d = BreakDialog(snooze_remaining=1, voice_notifier=None)
        qtbot.addWidget(d)
        with qtbot.waitExposed(d):
            d.show()
        # Must not raise — _stop_voice guards on `is None`.
        _find_button(d, "take a break").click()
        assert not d.isVisible()


# ---------------------------------------------------------------------------
# Integration — every dismiss path is covered (smoke test)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Smoke test: the action buttons are the ONLY way out of the dialog."""

    def test_only_action_button_can_close_dialog(self, qtbot, dialog: BreakDialog) -> None:
        """Every dismiss path is refused; only an action button closes the dialog."""
        with qtbot.waitExposed(dialog):
            dialog.show()

        # Try every dismiss path we know about.
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.isVisible()
        assert dialog.close() is False
        assert dialog.isVisible()

        # The action button is the only legitimate exit.
        _find_button(dialog, "take a break").click()
        assert not dialog.isVisible()
