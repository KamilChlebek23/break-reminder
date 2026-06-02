"""Integration tests for the FR-009 modal-stacking wedge (R-2).

Pins the structural invariants Fix A requires (``BreakDialog`` claims
``Qt.ApplicationModal`` scope AND dominates ``QApplication.activeModalWidget``)
across both modality regimes from research §1: ``SettingsDialog``
(unparented + ``.exec()``) and ``ReminderFormDialog`` (parented + ``.exec()``).

Scope: cross the wedge boundary that the existing per-dialog hardening
tests in ``tests/test_break_dialog.py`` never exercise — pairs of dialogs
co-displayed where the sibling claims modal scope first. The 20 existing
FR-009 hardening tests stay green; this file adds the cross-dialog
assertion.

See:

- ``context/archive/2026-06-02-testing-modal-stacking-wedge/research.md`` §1 (modality
  inventory), §3 (the ``QTest.mouseClick`` false-negative that drove the
  structural-assertion shape) and §4.b (the S-01 deferred-decision
  history Q2 surfaced).
- ``context/foundation/test-plan.md`` §2 R-2.

**Oracle source rule** (test-plan §2 R-2 "Anti-pattern to avoid"): the
test asserts the structural invariants the PRD FR-009 / US-02 contract
requires — ``BreakDialog.windowModality() == Qt.ApplicationModal`` AND
``QApplication.activeModalWidget() is break_dialog`` — NEVER derived
from re-reading ``BreakDialog`` source. If a future regression breaks
the invariant, this test must FAIL — not silently agree with the
regression.

**Fixture modality rule**: the blocking-modal dialog (Settings or
ReminderForm) is constructed with ``setModal(True) +
setWindowModality(Qt.ApplicationModal) + .show()`` — NEVER ``.exec()``.
``.exec()`` enters its own event loop and blocks the test thread,
preventing the subsequent ``BreakDialog`` construction. The pair
produces a structurally identical ``ApplicationModal`` scope (Agent C's
smoke pattern, ``research.md`` §3).

**``qtbot.waitExposed`` rule**: every ``.show()`` call is wrapped in
``with qtbot.waitExposed(dialog):`` — mirrors the 13-instance convention
in ``tests/test_break_dialog.py`` and lets Qt process the show event
(including modal-grab installation) before assertions run.

**Pre-action assertion scope** (plan-review F1): the fixture sanity
check asserts only on ``blocking_modal.windowModality()``, not on
``QApplication.activeModalWidget()``. Whether the latter populates for
a ``setWindowModality + .show()`` (non-``.exec()``) modal is an
unverified Qt internal; the load-bearing modal-grab check happens
post-action on ``break_dialog``.
"""

from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from break_reminder.notifications.break_dialog import BreakDialog
from break_reminder.notifications.voice import VoiceNotifier
from break_reminder.scheduler import ReminderScheduler
from break_reminder.storage.reminders import ReminderStore
from break_reminder.storage.settings import Settings
from break_reminder.ui.reminder_form_dialog import ReminderFormDialog
from break_reminder.ui.settings_dialog import SettingsDialog
from tests.conftest import Clock, FakeVoice

# Phase 4 (R-4) note: `FakeVoice`, `settings`, `voice`, `store_path`,
# `store`, `clock`, and (renamed) `reminder_scheduler` previously lived
# as local fixtures / a local class here; they were lifted to
# `tests/conftest.py` as part of the R-4 e2e harness foundation. This
# file consumes them by name; the conftest fixture `reminder_scheduler`
# provides the previous `scheduler` parameter.


@pytest.fixture(params=["settings", "reminder_form"])
def blocking_modal(
    request: pytest.FixtureRequest,
    qtbot,
    settings: Settings,
    voice: FakeVoice,
    store: ReminderStore,
    reminder_scheduler: ReminderScheduler,
    clock: Clock,
) -> QDialog:
    """Construct and show a sibling ``ApplicationModal`` dialog without ``.exec()``.

    Parametrized over both modality regimes from research §1:

    - ``"settings"`` — ``SettingsDialog`` (unparented + ``.exec()`` regime
      in production; here ``setModal(True) + .show()`` for test-thread
      compatibility, see module docstring "Fixture modality rule").
    - ``"reminder_form"`` — ``ReminderFormDialog`` (parented + ``.exec()``
      regime in production; same fixture pattern here).

    Sets ``Qt.WindowModality.ApplicationModal`` explicitly AND calls
    ``setModal(True)`` to mirror production's ``.exec()``-loop modal
    scope without entering an event loop that would block the test
    thread. Wraps ``.show()`` in ``qtbot.waitExposed`` so Qt has flushed
    modal-grab installation before the test body runs its assertions.

    Args:
        request: pytest fixture request carrying the parametrize regime.
        qtbot: pytest-qt fixture for widget lifecycle + show waits.
        settings: Per-test ``Settings`` instance.
        voice: No-op voice notifier stub.
        store: Per-test ``ReminderStore``.
        reminder_scheduler: Per-test ``ReminderScheduler``.
        clock: Per-test virtual ``Clock``.

    Returns:
        The constructed and shown blocking-modal dialog, ready for the
        wedge assertion. Registered with ``qtbot`` for teardown.
    """
    regime = request.param
    if regime == "settings":
        dialog: QDialog = SettingsDialog(
            settings=settings,
            voice=cast(VoiceNotifier, voice),
            reminder_store=store,
            reminder_scheduler=reminder_scheduler,
        )
    elif regime == "reminder_form":
        dialog = ReminderFormDialog(
            store=store,
            scheduler=reminder_scheduler,
            clock=clock,
        )
    else:
        raise ValueError(f"Unknown blocking-modal regime: {regime!r}")

    qtbot.addWidget(dialog)
    dialog.setModal(True)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    with qtbot.waitExposed(dialog):
        dialog.show()
    return dialog


class TestModalStackingWedge:
    """R-2: ``BreakDialog`` must dominate the modal grab over a sibling modal dialog.

    Pins the structural invariants of Fix A across both modality regimes.
    RED on current code (no ``setWindowModality`` on ``BreakDialog`` —
    the first post-action assertion fails because ``windowModality()``
    returns the default ``Qt.NonModal``). GREEN after Fix A escalates
    ``BreakDialog`` to ``Qt.ApplicationModal``.
    """

    def test_break_dialog_dominates_modal_scope_when_sibling_modal_open(
        self,
        qtbot,
        blocking_modal: QDialog,
    ) -> None:
        """``BreakDialog`` claims ``ApplicationModal`` over a sibling modal dialog.

        Pre-action: confirm the fixture wired the sibling to
        ``ApplicationModal`` (guards against a vacuous-pass via
        non-modal sibling). Does NOT assert on
        ``QApplication.activeModalWidget()`` for the sibling — whether
        the getter populates for a ``setWindowModality + .show()`` modal
        is an unverified Qt internal (plan-review F1).

        Action: construct + show ``BreakDialog`` on top of the blocking
        modal.

        Post-action: the two structural invariants Fix A must satisfy.
        ``BreakDialog.windowModality() == Qt.ApplicationModal`` is the
        first to fail on current code (default is ``Qt.NonModal``);
        ``QApplication.activeModalWidget() is break_dialog`` is the
        load-bearing behavioral check that Qt actually installed the
        modal grab in favor of ``BreakDialog`` over the prior sibling.

        Args:
            qtbot: pytest-qt fixture for widget lifecycle + show waits.
            blocking_modal: Parametrized sibling modal (``SettingsDialog``
                or ``ReminderFormDialog``) already shown with
                ``ApplicationModal`` scope.
        """
        assert blocking_modal.windowModality() == Qt.WindowModality.ApplicationModal

        break_dialog = BreakDialog(snooze_remaining=1, voice_notifier=None)
        qtbot.addWidget(break_dialog)
        with qtbot.waitExposed(break_dialog):
            break_dialog.show()

        assert break_dialog.windowModality() == Qt.WindowModality.ApplicationModal
        assert QApplication.activeModalWidget() is break_dialog
