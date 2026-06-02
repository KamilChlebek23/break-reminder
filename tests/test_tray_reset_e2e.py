"""End-to-end test for Flow D — Tray Reset re-arms cycle and fires next BreakDialog.

Closes the Reset re-arm tail of R-4 in
``break_reminder/app.py``: the ``_action_reset.triggered →
_on_reset → _apply_break_taken → _break_scheduler.start() → tick →
break_due → _on_break_due → BreakDialog`` chain. The existing test
at ``tests/test_app.py:test_reset_triggers_apply_break_taken`` stops
at the TAKEN CSV row + ``_active_seconds == 0`` precondition; this
e2e extends past that to assert the cycle is FULLY re-armed through
the next user-visible event.

Specifically, this test asserts the chain:

    QAction("Reset").trigger() → _on_reset → _apply_break_taken
      → break_scheduler.on_break_taken() (resets cycle)
      → event_log.record(BREAK, TAKEN)
      → break_scheduler.start() (re-arms timer)
      → tick loop → break_due.emit(snooze_remaining)
      → _on_break_due → _show_break_dialog → BreakDialog.show()

is observable end-to-end **on the freshly re-armed cycle** — proving
the re-arm at ``app.py:471`` (was ``:461`` in plan-time; Phase 1
docstring expansion shifted line numbers down 10) actually starts
the next cycle from zero, not from the pre-Reset accumulator state.

**Fully wired-app design** (no hybrid needed — unlike Flow B):

All three load-bearing connects for Flow D are wired in
``BreakReminderApp.__init__`` / ``_build_tray``, NOT on-demand:

- ``_action_reset.triggered → _on_reset`` at ``app.py:219`` (in
  ``_build_tray``, called from ``__init__``).
- ``_break_scheduler.break_due → _on_break_due`` at ``app.py:287``
  (in ``_wire_signals``, called from ``__init__``).
- ``_break_scheduler.activity_detected → _on_activity`` at
  ``scheduler.py:94`` (in ``BreakScheduler.__init__``).

So the wired ``break_reminder_app`` fixture catches a regression of
ANY of those three connects without the locally-mirrored connect
trick Flow B needed. This is the cleanest of the three e2e flows.

The wired-app fixture also exercises the Phase 1 ``clock=`` kwarg
propagation (STRUCTURAL #1) — the app's internal ``_break_scheduler``
runs on the same virtual ``Clock`` we drive here, so ``_tick()`` is
deterministic without entering the event loop.

**Timing-window oracle (the load-bearing assertion)**:

The test pre-seeds ``settings.break_interval_min = 3`` (180s
threshold) for test speed AND pre-seeds
``app._break_scheduler._active_seconds = 120`` BEFORE triggering
Reset. If ``_apply_break_taken`` failed to reset the accumulator,
the next break would fire at iteration ~60 (120 + 60 = 180); the
test asserts ``dialog_appeared_at == 180``, making the reset
strictly load-bearing for the oracle. Without the pre-seed, a
no-op ``on_break_taken()`` would still see the dialog fire at
iteration 180 (vacuous pass — ``_active_seconds`` was already 0).

See ``context/changes/testing-top-three-e2e-flows/research.md`` §D
(Flow D walkthrough) and §E (R-4 gap ranking).

**Anti-patterns deliberately avoided** (test-plan §2 R-4):

- No ``_StubSignal`` shim. No slot capture-and-invoke.
- No ``QTest.mouseClick`` on action buttons — uses
  ``QAction.trigger()`` (the same path as
  ``tests/test_app.py:test_reset_triggers_apply_break_taken``).
- No ``qtbot.wait()`` / ``qtbot.waitSignal()`` — calls ``_tick()``
  directly. ``_apply_break_taken`` arms a real ``QTimer`` at
  ``app.py:471``; entering the event loop here would race the
  deterministic ``_tick()`` invocations (STRUCTURAL #3).
- No ``_active_seconds == 0`` mirror as the load-bearing oracle —
  it's used only as a precondition snapshot. The user-visible
  oracle is ``BreakDialog`` presence on
  ``QApplication.topLevelWidgets()`` at iteration 180.
- Oracle on ``(event_type, outcome)`` tuple for the CSV row, NOT on
  ``timestamp_iso`` (``EventLog`` has no ``clock=`` seam —
  STRUCTURAL #2 deferred).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from break_reminder.app import BreakReminderApp
from break_reminder.notifications.break_dialog import BreakDialog
from tests.conftest import Clock

pytestmark = pytest.mark.e2e


def _find_action(app: BreakReminderApp, text: str) -> QAction:
    """Locate a tray-menu QAction by exact label.

    Mirrors the helper at ``tests/test_app.py:369-376`` so this e2e
    file has no cross-test-file import surface beyond the shared
    conftest. Kept module-local for the same reason
    ``_read_event_rows`` below is.
    """
    menu = app._tray.contextMenu()
    assert menu is not None, "tray context menu was not built"
    for action in menu.actions():
        if action.text() == text:
            return action
    raise LookupError(f"No tray action labelled {text!r}")


def _read_event_rows(path: Path) -> list[dict[str, str]]:
    """Read the FR-015 event log as a list of ``{column: value}`` dicts.

    Mirrors the helper at ``tests/test_app.py:86-89`` so this e2e
    file is self-contained.
    """
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TestTrayResetE2E:
    """R-4 Flow D: Tray Reset re-arms cycle and fires next BreakDialog.

    The R-4 hops this test closes through real production signal
    paths in the wired ``break_reminder_app`` fixture:

    - Tray ``_action_reset.triggered → _on_reset`` connect at
      ``app.py:219``.
    - ``_on_reset`` slot at ``app.py:307-316``.
    - ``_apply_break_taken`` shared backbone at ``app.py:458-472``,
      including the ``_break_scheduler.start()`` re-arm at
      ``app.py:471``.
    - ``_break_scheduler.break_due → _on_break_due`` connect at
      ``app.py:287``.
    - ``_on_break_due`` slot at ``app.py:394-397`` → ``_show_break_dialog``
      at ``app.py:410-424``.

    Extends the existing ``test_reset_triggers_apply_break_taken``
    (which stops at TAKEN-row + ``_active_seconds == 0``) with the
    "next break actually fires through the wired ``break_due``
    chain" tail. A regression that removed ``_break_scheduler.start()``
    from ``_apply_break_taken`` would not be caught by the existing
    test (Reset's CSV row would still appear) but IS caught here
    (the timer would never tick, and the dialog would never appear
    within the 180-iteration cap).
    """

    def test_tray_reset_logs_taken_and_rearms_cycle_to_fire_next_break_dialog(
        self,
        qtbot,
        break_reminder_app: BreakReminderApp,
        clock: Clock,
    ) -> None:
        """Tray Reset → TAKEN row → cycle re-armed → BreakDialog at exactly iteration 180.

        Uses the wired ``break_reminder_app`` fixture so the
        ``_action_reset.triggered`` connect, the ``break_due``
        connect, and the ``activity_detected`` connect ALL run
        through production wiring (no mirrored connects, unlike
        Flow B).

        The load-bearing oracle is the **timing window**: the
        ``BreakDialog`` MUST appear at iteration 180 (proves the
        cycle re-armed from zero), NOT iteration ~60 (which would
        mean ``_apply_break_taken`` failed to reset the accumulator
        and the pre-seed of 120 + 60 ticks = 180 = threshold), and
        NOT later than 180 (which would mean the new threshold or
        the tick wiring is broken).
        """
        # Small threshold for test speed (3 min = 180s). The scheduler
        # re-reads `settings.snapshot()` on every tick at
        # scheduler.py:211, so post-construction mutation is honored
        # from the next _tick() onward.
        break_reminder_app._settings.break_interval_min = 3

        # Pre-seed accumulator: pretends 2 minutes of active time
        # existed before the user clicks Reset. Without this seed, a
        # regression that broke `_apply_break_taken`'s cycle reset
        # would still pass the iteration-180 oracle (vacuous —
        # `_active_seconds` was already 0). With the seed, a no-op
        # reset would leave _active_seconds = 120 and the dialog
        # would fire at iteration 60 (120 + 60 = 180 = threshold).
        break_reminder_app._break_scheduler._active_seconds = 120

        # Pre-condition snapshot. `_active_break_dialog` is the
        # production holder set inside `_show_break_dialog` at
        # app.py:422; initialized to None at app.py:121.
        assert break_reminder_app._active_break_dialog is None
        assert _read_event_rows(break_reminder_app._event_log.path) == [], (
            "events.log should be empty before Reset"
        )

        # Real tray-action signal path. _action_reset.trigger() emits
        # `triggered`, which crosses the production connect at
        # app.py:219 to `_on_reset`, which delegates to
        # `_apply_break_taken` at app.py:316.
        _find_action(break_reminder_app, "Reset").trigger()

        # Existing-shape extension oracle: exactly one TAKEN row in
        # the CSV. Oracled on (event_type, outcome) per STRUCTURAL #2
        # — EventLog has no clock= seam so timestamp_iso reflects
        # real wall-clock and would flake.
        rows = _read_event_rows(break_reminder_app._event_log.path)
        assert len(rows) == 1, "exactly one event row expected after Reset"
        assert (rows[0]["event_type"], rows[0]["outcome"]) == ("break", "taken"), (
            f"expected (break, taken), got ({rows[0]['event_type']}, {rows[0]['outcome']})"
        )

        # Precondition for the timing oracle (NOT the load-bearing
        # assertion per test-plan §2 R-3 implementation-mirror
        # anti-pattern). If this fails, the oracle below is
        # ambiguous so we surface it early with a clear message.
        assert break_reminder_app._break_scheduler._active_seconds == 0, (
            "_apply_break_taken did not call on_break_taken() — "
            "either app.py:219 connect dropped, _on_reset body broken, "
            "or _apply_break_taken's on_break_taken() call removed"
        )

        # Precondition that DIRECTLY catches a regression of
        # ``_break_scheduler.start()`` at app.py:471 (the QTimer re-arm
        # that makes the next cycle accumulate in production). Without
        # this assertion, the test below would still pass because it
        # drives ``_tick()`` directly — bypassing the timer entirely —
        # so the timer-arm contract would be silently lost in production
        # while the e2e remained green. Implementation peek (mirrors
        # test-plan §2 R-3 caveat) used ONLY as a precondition, not as
        # the load-bearing user-visible oracle.
        assert break_reminder_app._break_scheduler._timer.isActive(), (
            "_apply_break_taken did not re-arm the BreakScheduler timer — "
            "app.py:471 `_break_scheduler.start()` call was likely removed; "
            "in production this would leave the cycle dead until the next "
            "manual user action"
        )

        # Tick loop. Each iteration emits real activity through the
        # production signal path (ActivityMonitor.activity_detected →
        # BreakScheduler._on_activity at scheduler.py:94, :203-204)
        # so _last_input_at refreshes to current clock, then calls
        # _tick() which reads settings.snapshot() (picking up the
        # 3-min threshold) and increments _active_seconds by 1. At
        # iteration 180, _active_seconds reaches 180 >= 3*60 —
        # break_due fires, crosses app.py:287 connect to
        # _on_break_due, which constructs and shows BreakDialog.
        new_threshold_iterations = 3 * 60
        dialog_appeared_at: int | None = None
        for iteration in range(1, new_threshold_iterations + 1):
            break_reminder_app._activity.activity_detected.emit(clock())
            break_reminder_app._break_scheduler._tick()
            if break_reminder_app._active_break_dialog is not None:
                dialog_appeared_at = iteration
                break
            clock.advance(1)

        # The load-bearing R-4 oracle: dialog appeared at EXACTLY
        # iteration 180 (cycle re-armed from zero). NOT iteration
        # ~60 (which would mean _apply_break_taken failed to reset
        # _active_seconds — 120 carry-over + 60 fresh = 180 =
        # threshold), and NOT None (which would mean app.py:287
        # break_due connect is broken, OR app.py:471 start() call
        # was removed, OR _on_break_due / _show_break_dialog body
        # is broken).
        assert dialog_appeared_at == new_threshold_iterations, (
            f"BreakDialog appeared at iteration {dialog_appeared_at}, "
            f"expected exactly {new_threshold_iterations} — either the "
            f"cycle was not re-armed from zero (regression in "
            f"_apply_break_taken's on_break_taken() call), OR the "
            f"break_due → _on_break_due chain is broken (regression in "
            f"app.py:287 connect, app.py:471 start(), or "
            f"_on_break_due / _show_break_dialog body)"
        )

        # Confirm the dialog is the production-constructed BreakDialog
        # registered on the QApplication's top-level widgets and
        # visible (proving _show_break_dialog ran to completion at
        # app.py:423 dialog.show()).
        dialog = break_reminder_app._active_break_dialog
        assert isinstance(dialog, BreakDialog)
        assert dialog in QApplication.topLevelWidgets()
        assert dialog.isVisible(), (
            "BreakDialog was constructed but .show() was never called — "
            "_show_break_dialog body at app.py:410-424 broken"
        )

        # Register with qtbot so its teardown cleans the dialog up —
        # the dialog is owned by app._active_break_dialog but the
        # fixture itself doesn't shut it down (no app.start() means
        # no app.shutdown() either; FR-009's non-dismissable guards
        # ignore programmatic close()).
        qtbot.addWidget(dialog)
