"""End-to-end test for Flow B — Save Settings interval fires BreakDialog on new threshold.

Closes the four ``_StubSignal`` shim-shaped R-4 gaps in the codebase
(``tests/test_app.py:431``, ``tests/test_settings_dialog.py:2446`` /
``:2749`` / ``:2802``) AND the ``break_due → _on_break_due →
BreakDialog`` connection at ``break_reminder/app.py:287`` (was ``:277``
in plan-time; the Phase 1 docstring expansion shifted it down 10
lines). Specifically, this test asserts the chain:

    SettingsDialog.accept() → break_interval_changed.emit(new)
      → _on_break_interval_changed → break_scheduler.reset_cycle()
      → tick loop → break_due.emit(snooze_remaining)
      → _on_break_due → _show_break_dialog → BreakDialog.show()

is observable end-to-end **on the NEW threshold** — proving the
interval-change actually re-bases the cycle (the S-09 contract) and
the new value is honored by the running scheduler.

The test exercises the wired ``break_reminder_app`` fixture so the
``break_due`` connect at ``app.py:287`` and the production
``_on_break_due`` slot at ``app.py:394-397`` BOTH run through real
production code. A regression that commented out ``app.py:287`` or
broke ``_on_break_due``'s body would fail this test.

**Hybrid wired-app design** (Phase 3 plan-vs-intent triage):

The plan literally said "construct SettingsDialog standalone, wire
both connects in the test". Manual verification 3.11 required "test
fails if either ``app.py:349`` or ``app.py:277`` connect lines were
commented out". Those two are partially incompatible: the
``app.py:287`` (was ``:277``) connect can be caught via the wired-app
fixture (it's at ``__init__``), but the ``app.py:359`` (was ``:349``)
connect is wired **on-demand inside ``_on_open_settings``**, which
calls ``dialog.exec()`` and blocks the test thread. The test
therefore mirrors that on-demand connect locally (matches the
production line byte-for-byte) and uses the wired app for everything
else. This catches:

- A regression in ``app.py:287`` ``break_due`` connect (via wired app).
- A regression in ``_on_break_due`` slot body (via production slot).
- A regression in ``_on_break_interval_changed`` slot body (via
  production slot — the test calls it via the wired connect).
- A regression in ``BreakScheduler.reset_cycle()`` (via wired
  scheduler).
- A regression that broke the ``snap.break_interval_min`` re-read on
  every tick (the timing-window oracle).

The single residual gap: a regression that commented out
``app.py:359`` itself. Catching that would require splitting
``_on_open_settings`` into ``_build_settings_dialog`` + ``exec``,
which is out of scope for Phase 3 (no production refactor budget).

See ``context/changes/testing-top-three-e2e-flows/research.md`` §B
(per-hop coverage), §E (R-4 gap ranking), and §F (the four-shim
inventory this test deprecates).

**Anti-patterns deliberately avoided** (test-plan §2 R-4):

- No ``_StubSignal`` shim. No ``slots[0](5)`` slot capture-and-invoke.
- No ``dialog.exec()`` (blocks test thread); ``dialog.accept()`` only.
- No ``qtbot.wait()`` / ``qtbot.waitSignal()`` after the schedulers
  are running (test-plan §7 + STRUCTURAL #3 in research.md §F: a
  real ``QTimer.start()`` would race the deterministic ``_tick()``).
- No ``_active_seconds == 0`` as the load-bearing oracle (test-plan
  §2 R-3 implementation-mirror anti-pattern); used here only as a
  precondition for the tick loop, NOT the user-visible outcome.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from break_reminder.app import BreakReminderApp
from break_reminder.notifications.break_dialog import BreakDialog
from break_reminder.ui.settings_dialog import SettingsDialog
from tests.conftest import Clock

pytestmark = pytest.mark.e2e


class TestSaveSettingsIntervalE2E:
    """R-4 Flow B: Save Settings interval → reset cycle → fires BreakDialog on new threshold.

    The four R-4 hops this test closes (currently signal-connection-
    only or ``_StubSignal``-shimmed in production):

    - ``break_interval_changed → _on_break_interval_changed`` (mirrored
      locally — production wires it on-demand inside ``_on_open_settings``
      which blocks via ``dialog.exec()``).
    - ``_on_break_interval_changed`` slot body at ``app.py:433-456`` —
      previously tested via ``_StubSignal`` shim at ``test_app.py:431``.
    - ``break_due → _on_break_due`` connect at ``app.py:287`` (production
      wire via wired-app fixture).
    - ``_on_break_due`` slot body at ``app.py:394-397`` — chained into
      ``_show_break_dialog`` at ``app.py:410-424``.
    """

    def test_save_settings_new_interval_resets_cycle_and_fires_break_dialog_on_new_threshold(
        self,
        qtbot,
        break_reminder_app: BreakReminderApp,
        clock: Clock,
    ) -> None:
        """Interval change → reset → tick loop → BreakDialog on new threshold.

        Uses the wired ``break_reminder_app`` fixture so the
        ``break_due → _on_break_due → BreakDialog`` tail runs through
        production. Mirrors ``app.py:359``'s on-demand
        ``break_interval_changed`` connect locally because
        ``_on_open_settings`` blocks the test thread via
        ``dialog.exec()``.

        The load-bearing oracle is the **timing window**: the
        ``BreakDialog`` MUST NOT appear before iteration 300 (would
        mean the old threshold of 10 is still in effect, or
        ``reset_cycle()`` didn't run, or both) AND MUST appear AT
        iteration 300 (proves the new threshold of 5 is honored and
        ``reset_cycle()`` set the accumulator to zero).
        """
        # Pre-seed the OLD threshold. Setter writes through to the
        # underlying QSettings via settings.py:137-159; the scheduler
        # re-reads on every tick via `snap = self._settings.snapshot()`
        # at scheduler.py:211, so this takes effect immediately for the
        # next call to `_tick()`.
        break_reminder_app._settings.break_interval_min = 10

        dialog = SettingsDialog(
            settings=break_reminder_app._settings,
            voice=break_reminder_app._voice,
            reminder_store=break_reminder_app._reminder_store,
            reminder_scheduler=break_reminder_app._reminder_scheduler,
            parent=None,
        )
        qtbot.addWidget(dialog)

        # Mirror app.py:359 — the on-demand connect inside
        # _on_open_settings that the test thread can't reach without
        # blocking on dialog.exec(). Connecting the production slot
        # directly (NOT a shim) so the slot body at app.py:433-456 runs
        # through real code.
        dialog.break_interval_changed.connect(break_reminder_app._on_break_interval_changed)

        # Pre-seed _active_seconds to a non-zero value. This makes the
        # timing-window oracle below strictly load-bearing — without
        # the seed, `_active_seconds` would be 0 already, and a
        # regression that broke `reset_cycle()` would still see the
        # dialog appear at iteration 300 (vacuous pass). With the seed,
        # a no-op `reset_cycle()` would leave `_active_seconds = 290`
        # and the dialog would fire at iteration 10 (290 + 10 = 300),
        # failing the `dialog_appeared_at == 300` assertion with a
        # descriptive message.
        break_reminder_app._break_scheduler._active_seconds = 290

        # Pre-condition snapshot. _active_break_dialog is the production
        # holder set inside _show_break_dialog at app.py:422; it's
        # initialized to None at app.py:121.
        assert break_reminder_app._settings.break_interval_min == 10
        assert break_reminder_app._break_scheduler._active_seconds == 290
        assert break_reminder_app._active_break_dialog is None

        # Change spinbox to NEW threshold and save. SettingsDialog.accept()
        # at settings_dialog.py:1298-1313: reads old, writes new, emits
        # iff old != new — the (10 → 5) delta clears that gate.
        dialog._break_interval_spinbox.setValue(5)
        dialog.accept()

        # Post-accept preconditions for the tick loop. _active_seconds
        # = 0 is an implementation peek per test-plan §2 R-3 — used
        # ONLY as a precondition to make the timing-window oracle below
        # unambiguous, NOT the load-bearing assertion.
        assert break_reminder_app._settings.break_interval_min == 5, (
            "SettingsDialog.accept() did not persist the new interval"
        )
        assert break_reminder_app._break_scheduler._active_seconds == 0, (
            "_on_break_interval_changed did not call reset_cycle() — "
            "either the connect was dropped or the slot body broke"
        )

        # Tick loop. Each iteration emits real activity through the
        # production signal path (ActivityMonitor.activity_detected →
        # BreakScheduler._on_activity at scheduler.py:94, :203-204) so
        # _last_input_at refreshes to current clock, then calls _tick()
        # which reads settings.snapshot() (picking up the new threshold)
        # and increments _active_seconds by 1. At iteration 300,
        # _active_seconds reaches 300 >= 5*60 — break_due fires.
        new_threshold_iterations = 5 * 60
        dialog_appeared_at: int | None = None
        for iteration in range(1, new_threshold_iterations + 1):
            break_reminder_app._activity.activity_detected.emit(clock())
            break_reminder_app._break_scheduler._tick()
            if break_reminder_app._active_break_dialog is not None:
                dialog_appeared_at = iteration
                break
            clock.advance(1)

        # The load-bearing R-4 oracle: dialog appeared exactly at
        # iteration 300 (new threshold honored). NOT earlier (old
        # threshold 10 *60 = 600 would mean dialog appears around
        # iteration 600 — well past our 300-iteration cap, so the
        # assert below would catch "dialog never appeared"; an
        # accumulator-not-reset bug would fire around iteration 0 if
        # _active_seconds carried over). NOT later (a settings.snapshot
        # caching bug would still see old threshold and fire at 600).
        assert dialog_appeared_at == new_threshold_iterations, (
            f"BreakDialog appeared at iteration {dialog_appeared_at}, "
            f"expected exactly {new_threshold_iterations} — the new threshold "
            f"is not being honored, OR reset_cycle() did not zero the "
            f"accumulator, OR app.py:287 break_due connect is broken"
        )
        assert isinstance(break_reminder_app._active_break_dialog, BreakDialog)
        assert break_reminder_app._active_break_dialog in QApplication.topLevelWidgets()
        assert break_reminder_app._active_break_dialog.isVisible(), (
            "BreakDialog was constructed but .show() was never called — "
            "_show_break_dialog body at app.py:410-424 broken"
        )

        # Register with qtbot so its teardown owns the dialog — FR-009's
        # non-dismissable guards in break_dialog.py swallow programmatic
        # close(), so without this the dialog leaks into the next test's
        # modal state. Mirrors tests/test_tray_reset_e2e.py:286-291.
        qtbot.addWidget(break_reminder_app._active_break_dialog)
