"""End-to-end test for Flow A — Add Reminder via form fires ReminderDialog.

Closes the single biggest R-4 invisibility hop in the codebase: the
connection at ``break_reminder/app.py:288`` between
``ReminderScheduler.reminder_due`` and ``BreakReminderApp._on_reminder_due``,
and the production slot body itself (``app.py:399-408``) which has
**zero ripgrep matches** in ``tests/`` today.

The test exercises the whole live chain in one assertion:

1. User constructs and fills ``ReminderFormDialog`` against the wired
   app's real ``ReminderStore`` and the wired app's real
   ``ReminderScheduler`` (NOT a standalone scheduler the test wires
   itself — that simplification would lose the load-bearing R-4
   safety net per research.md §E).
2. ``dialog.accept()`` persists the reminder, arms the scheduler,
   emits ``reminder_added`` — production code path.
3. Virtual clock advances past the scheduled time; the test calls
   ``_on_timer()`` directly (the established pattern from
   test-plan §7 "No deep Qt-internals mocking").
4. Production ``reminder_due.emit(...)`` crosses the real ``connect``
   at ``app.py:288`` into production ``_on_reminder_due``, which
   constructs a ``ReminderDialog`` and calls ``.show()`` on it.
5. Test asserts the ``ReminderDialog`` instance is held on
   ``app._reminder_dialog`` AND appears on
   ``QApplication.topLevelWidgets()``.

A regression that commented out ``app.py:288``, broke
``_on_reminder_due``'s body, or stopped holding a reference to the
constructed dialog would all fail this test. That is the R-4
load-bearing contract (empirically verified by mutation test at
phase-2 implementation time — commenting the connect line made the
final assertion fail at ``test_add_reminder_e2e.py:155``).

See ``context/changes/testing-top-three-e2e-flows/research.md`` §A
(per-hop coverage table) and §E (the R-4 anti-pattern this test
deliberately avoids).

**Anti-patterns deliberately avoided** (test-plan §2 R-4):

- No ``_StubSignal`` shim. No ``Mock()`` of ``_on_reminder_due``.
- No ``slot.assert_called_with(...)`` oracle.
- No ``QTest.mouseClick`` on the dialog button (test-plan §2 R-2
  bypasses OS modal grab; not relevant to ``accept()`` directly but
  documented here for consistency with the cookbook).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from PySide6.QtWidgets import QApplication

from break_reminder.app import BreakReminderApp
from break_reminder.notifications.reminder_dialog import ReminderDialog
from break_reminder.storage.reminders import ReminderStore
from break_reminder.ui.reminder_form_dialog import (
    ReminderFormDialog,
    _qdatetime_from_naive_local,
)
from tests.conftest import Clock

pytestmark = pytest.mark.e2e


class TestAddReminderE2E:
    """R-4 Flow A: Add Reminder → ReminderScheduler arms → fires ReminderDialog.

    The three R-4 hops this test closes (all currently signal-
    connection-only in production):

    - ``reminder_due → _on_reminder_due`` connect at ``app.py:288``.
    - ``_on_reminder_due`` slot body at ``app.py:399-408`` (zero
      ripgrep matches in ``tests/`` before this file landed).
    - ``ReminderDialog`` construction + ``.show()`` at ``app.py:407-408``.
    """

    def test_add_reminder_through_form_arms_scheduler_and_fires_dialog(
        self,
        qtbot,
        break_reminder_app: BreakReminderApp,
        store: ReminderStore,
        clock: Clock,
    ) -> None:
        """Form save → scheduler armed → virtual-clock tick → ReminderDialog visible.

        Uses the wired ``break_reminder_app`` fixture so the form,
        scheduler, and slot all run against the production connect at
        ``app.py:288`` — commenting that line out would make this test
        fail (manual verification 2.9, empirically confirmed). The
        form is constructed with the app's internal
        ``_reminder_scheduler`` (NOT a standalone one — the standalone
        choice would bypass the production wire and silently lose the
        R-4 contract).
        """
        # The conftest `store` and the wired app's `_reminder_store` are
        # the same object — the `break_reminder_app` fixture passes
        # `reminder_store=store`. Asserted here as a precondition so a
        # future fixture rewire that broke the identity would surface
        # immediately rather than as a confusing "reminder vanished"
        # downstream.
        assert break_reminder_app._reminder_store is store

        form = ReminderFormDialog(
            store=store,
            scheduler=break_reminder_app._reminder_scheduler,
            clock=clock,
            parent=None,
        )
        qtbot.addWidget(form)

        # Pick a fire-time 5 minutes after the virtual clock. The form
        # consumes naive-LOCAL datetimes via its `_datetime_field`
        # (`reminder_form_dialog.py:351-358`); the production save path
        # converts back to tz-aware UTC for storage. Using the form's
        # own conversion helper keeps the test honest about the field
        # contract — a test that wrote directly to `start_at` would
        # bypass the very gate (`reminder_form_dialog.py:920`) that
        # `clock=clock` is load-bearing for.
        target_utc = clock() + timedelta(minutes=5)
        target_naive_local = target_utc.astimezone().replace(tzinfo=None)
        form._name_field.setText("E2E Flow A reminder")
        form._datetime_field.setDateTime(_qdatetime_from_naive_local(target_naive_local))

        # Pre-condition snapshot. Both must be empty / unarmed so the
        # post-accept assertion is unambiguous (it caught the
        # save AND the arm, not pre-existing state). ``_reminder_dialog``
        # is set lazily by the slot at ``app.py:407`` — it has no
        # default value on ``__init__`` — so ``getattr`` is the safe
        # accessor here.
        assert store.list_all() == []
        assert break_reminder_app._reminder_scheduler._next is None
        assert getattr(break_reminder_app, "_reminder_dialog", None) is None

        form.accept()

        # Post-accept: store round-trip + scheduler arm.
        persisted = store.list_all()
        assert len(persisted) == 1, "ReminderFormDialog.accept() did not persist the reminder"
        saved = persisted[0]
        assert saved.name == "E2E Flow A reminder"
        assert break_reminder_app._reminder_scheduler._next is not None
        assert break_reminder_app._reminder_scheduler._next.reminder_id == saved.id

        # Advance the virtual clock past the fire-time + a 1-second
        # cushion (mirrors the pattern in
        # `tests/test_recurring_reminder_integration.py`).
        clock.advance(5 * 60 + 1)
        break_reminder_app._reminder_scheduler._on_timer()

        # The load-bearing R-4 oracle: the production connect at
        # `app.py:288` ran, the production slot at `app.py:399-408`
        # constructed a `ReminderDialog`, and that dialog is on
        # `QApplication.topLevelWidgets()`. NOT a slot-called assertion;
        # NOT a `_StubSignal` capture.
        reminder_dialog = getattr(break_reminder_app, "_reminder_dialog", None)
        assert reminder_dialog is not None, (
            "Production _on_reminder_due never ran — app.py:288 connect or slot body broken"
        )
        assert isinstance(reminder_dialog, ReminderDialog)
        assert reminder_dialog in QApplication.topLevelWidgets()
        assert reminder_dialog.isVisible(), (
            "ReminderDialog was constructed but .show() was never called"
        )
