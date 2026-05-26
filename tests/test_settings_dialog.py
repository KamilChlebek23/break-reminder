"""Tests for ``SettingsDialog`` — the FR-005 / FR-006 / FR-007 settings window.

Covers the load / save / cancel contract in isolation, without showing
the dialog (no ``exec()``, no event loop pumping). Each test gets a
``tmp_path``-bound ``Settings`` instance and a ``StubVoiceNotifier`` so
the suite never touches the real ``%APPDATA%`` location and never
spins up a ``pyttsx3`` worker pool, mirroring the pattern in
``tests/test_settings.py`` and ``tests/test_app.py``.

Layout invariants are also asserted as tripwires — if a future slice
silently flattens the ``QTabWidget`` or re-labels a tab, the affected
tests fail loudly instead of letting the layout drift unnoticed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QCheckBox, QLineEdit, QPushButton, QSpinBox, QTabWidget

from break_reminder.storage.settings import (
    DEFAULT_BREAK_INTERVAL_MIN,
    DEFAULT_MAX_SNOOZES,
    DEFAULT_SNOOZE_DURATION_MIN,
    DEFAULT_VOICE_PHRASE,
    Settings,
)
from break_reminder.ui import settings_dialog as settings_dialog_module
from break_reminder.ui.settings_dialog import SettingsDialog


class StubVoiceNotifier:
    """No-op ``VoiceNotifier`` stub — same surface, no thread pool.

    Records every ``speak`` call into ``self.spoken`` and counts ``stop``
    calls so tests can assert on the Test-button payload AND on the
    rapid-click cancellation contract (impl-review F3) without
    exercising ``pyttsx3``.
    """

    def __init__(self) -> None:
        """Initialize the stub with an empty call log and zero stop count."""
        self.spoken: list[str] = []
        self.stop_calls = 0

    def speak(self, phrase: str) -> None:
        """Record one ``speak`` invocation by appending ``phrase`` to ``spoken``."""
        self.spoken.append(phrase)

    def stop(self) -> None:
        """Record one ``stop`` invocation by incrementing ``stop_calls``."""
        self.stop_calls += 1


@pytest.fixture
def ini_path(tmp_path: Path) -> Path:
    """Path to a per-test INI file under ``tmp_path``."""
    return tmp_path / "BreakReminder.ini"


@pytest.fixture
def settings(ini_path: Path) -> Settings:
    """A ``Settings`` instance bound to the per-test ``ini_path`` fixture."""
    return Settings(ini_path=ini_path)


@pytest.fixture
def voice() -> StubVoiceNotifier:
    """A ``StubVoiceNotifier`` injected wherever the dialog needs ``VoiceNotifier``."""
    return StubVoiceNotifier()


@pytest.fixture
def dialog(qtbot, settings: Settings, voice: StubVoiceNotifier) -> SettingsDialog:
    """A ``SettingsDialog`` wired against the per-test ``settings`` and ``voice`` fixtures.

    Registered with ``qtbot.addWidget`` so the dialog is destroyed at
    test teardown regardless of test outcome — matches the convention
    in ``tests/test_break_dialog.py``.
    """
    d = SettingsDialog(settings=settings, voice=voice)  # type: ignore[arg-type]
    qtbot.addWidget(d)
    return d


# ---------------------------------------------------------------------------
# Load — initial state matches Settings + bounds enforce FR-006
# ---------------------------------------------------------------------------


class TestLoad:
    """Initial dialog state reflects the injected ``Settings`` and FR-006 bounds."""

    def test_spinbox_initial_value_is_default_on_fresh_settings(
        self, dialog: SettingsDialog
    ) -> None:
        """Spinbox shows ``DEFAULT_BREAK_INTERVAL_MIN`` on a fresh INI."""
        assert dialog._break_interval_spinbox.value() == DEFAULT_BREAK_INTERVAL_MIN

    def test_spinbox_initial_value_reflects_pre_set_value(self, qtbot, ini_path: Path) -> None:
        """Spinbox shows whatever ``Settings.break_interval_min`` already holds."""
        pre_set = Settings(ini_path=ini_path)
        pre_set.break_interval_min = 45
        del pre_set

        d = SettingsDialog(
            settings=Settings(ini_path=ini_path),
            voice=StubVoiceNotifier(),  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)

        assert d._break_interval_spinbox.value() == 45

    def test_spinbox_minimum_is_one(self, dialog: SettingsDialog) -> None:
        """FR-006 lower bound is enforced at the widget level."""
        # Tripwire: if a future agent loosens the lower bound, the
        # Settings setter's ValueError path becomes reachable from the
        # dialog and the no-try/except design assumption breaks.
        assert dialog._break_interval_spinbox.minimum() == 1

    def test_spinbox_maximum_is_240(self, dialog: SettingsDialog) -> None:
        """FR-006 upper bound is enforced at the widget level."""
        # Tripwire: if a future agent loosens the upper bound, the
        # Settings setter's ValueError path becomes reachable from the
        # dialog and the no-try/except design assumption breaks.
        assert dialog._break_interval_spinbox.maximum() == 240

    def test_window_title_is_settings(self, dialog: SettingsDialog) -> None:
        """The dialog's window title is the documented label."""
        assert dialog.windowTitle() == "Settings"

    def test_spinbox_tooltip_explains_range(self, dialog: SettingsDialog) -> None:
        """The spinbox tooltip surfaces FR-006's [1, 240] range to the user.

        QSpinBox bounds prevent the *value* from leaving [1, 240] but the
        underlying QLineEdit accepts out-of-range typing that gets
        silently clamped on commit. A permanent tooltip exposes the
        constraint on hover so the bump isn't surprising.
        """
        tooltip = dialog._break_interval_spinbox.toolTip()
        assert "1" in tooltip
        assert "240" in tooltip

    def test_snooze_duration_spinbox_initial_value_is_default_on_fresh_settings(
        self, dialog: SettingsDialog
    ) -> None:
        """Snooze-duration spinbox shows ``DEFAULT_SNOOZE_DURATION_MIN`` on a fresh INI."""
        assert dialog._snooze_duration_spinbox.value() == DEFAULT_SNOOZE_DURATION_MIN

    def test_snooze_duration_spinbox_minimum_is_one(self, dialog: SettingsDialog) -> None:
        """FR-010 snooze-duration lower bound is enforced at the widget level."""
        # Tripwire: same role as the break-interval lower-bound test —
        # if loosened, the Settings setter's ValueError path becomes
        # reachable from the dialog and the no-try/except design breaks.
        assert dialog._snooze_duration_spinbox.minimum() == 1

    def test_snooze_duration_spinbox_maximum_is_30(self, dialog: SettingsDialog) -> None:
        """FR-010 snooze-duration upper bound is enforced at the widget level."""
        assert dialog._snooze_duration_spinbox.maximum() == 30

    def test_max_snoozes_spinbox_initial_value_is_default_on_fresh_settings(
        self, dialog: SettingsDialog
    ) -> None:
        """Max-snoozes spinbox shows ``DEFAULT_MAX_SNOOZES`` on a fresh INI."""
        assert dialog._max_snoozes_spinbox.value() == DEFAULT_MAX_SNOOZES

    def test_max_snoozes_spinbox_minimum_is_zero(self, dialog: SettingsDialog) -> None:
        """FR-010 max-snoozes lower bound is 0 — disables snoozing entirely."""
        # Zero is intentional, not an oversight. A future agent who
        # "fixes" this to 1 breaks the user-disables-snoozing flow this
        # slice deliberately enables.
        assert dialog._max_snoozes_spinbox.minimum() == 0

    def test_max_snoozes_spinbox_maximum_is_5(self, dialog: SettingsDialog) -> None:
        """FR-010 max-snoozes upper bound is enforced at the widget level."""
        assert dialog._max_snoozes_spinbox.maximum() == 5

    def test_max_snoozes_spinbox_zero_state_tooltip_present(self, dialog: SettingsDialog) -> None:
        """The max-snoozes spinbox carries a tooltip explaining the zero state.

        The string ``"0 = no snoozes"`` is the load-bearing UX hint —
        without it a user lowering the cap to 0 might expect the snooze
        button to refuse rather than disappear. Tripwire for accidental
        tooltip removal during a future refactor.
        """
        tooltip = dialog._max_snoozes_spinbox.toolTip()
        assert "0 = no snoozes" in tooltip


# ---------------------------------------------------------------------------
# Save — OK persists, Cancel discards
# ---------------------------------------------------------------------------


class TestSave:
    """OK persists the spinbox value through ``Settings``; Cancel discards."""

    def test_accept_persists_via_settings_setter(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """``accept()`` writes the spinbox value through ``Settings.break_interval_min``."""
        dialog._break_interval_spinbox.setValue(30)

        dialog.accept()

        assert settings.break_interval_min == 30

    def test_accept_persists_across_settings_instances(self, qtbot, ini_path: Path) -> None:
        """A persisted value is observable from a freshly constructed ``Settings``."""
        first_settings = Settings(ini_path=ini_path)
        d = SettingsDialog(
            settings=first_settings,
            voice=StubVoiceNotifier(),  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)
        d._break_interval_spinbox.setValue(90)
        d.accept()
        first_settings._qs.sync()
        del first_settings

        second_settings = Settings(ini_path=ini_path)
        assert second_settings.break_interval_min == 90

    def test_reject_does_not_persist(
        self, qtbot, dialog: SettingsDialog, settings: Settings, ini_path: Path
    ) -> None:
        """``reject()`` after editing leaves ``Settings.break_interval_min`` unchanged."""
        # Pre-set to a known value so we can observe the absence of writes.
        settings.break_interval_min = 75
        # Construct a fresh dialog so the spinbox loads the new value.
        # (The fixture-built dialog was constructed before this test set 75.)
        d = SettingsDialog(
            settings=settings,
            voice=StubVoiceNotifier(),  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)
        d._break_interval_spinbox.setValue(15)

        d.reject()

        assert settings.break_interval_min == 75

    def test_reject_does_not_write_to_ini(self, qtbot, ini_path: Path) -> None:
        """``reject()`` on a never-saved dialog does not materialize the INI."""
        # Fresh INI path: the file should not exist, and Cancel must not
        # cause it to exist either.
        s = Settings(ini_path=ini_path)
        d = SettingsDialog(
            settings=s,
            voice=StubVoiceNotifier(),  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)
        d._break_interval_spinbox.setValue(120)

        d.reject()
        s._qs.sync()

        # The Settings constructor itself doesn't write; only the setter
        # does. Cancel skips the setter, so the INI must still be absent.
        assert not ini_path.exists()

    def test_accept_persists_snooze_duration_via_settings_setter(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """``accept()`` writes the snooze-duration spinbox via ``Settings.snooze_duration_min``."""
        dialog._snooze_duration_spinbox.setValue(10)

        dialog.accept()

        assert settings.snooze_duration_min == 10

    def test_accept_persists_max_snoozes_via_settings_setter(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """``accept()`` writes the max-snoozes spinbox via ``Settings.max_snoozes``."""
        dialog._max_snoozes_spinbox.setValue(3)

        dialog.accept()

        assert settings.max_snoozes == 3

    def test_accept_persists_max_snoozes_zero(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """``accept()`` allows persisting ``max_snoozes = 0`` (disable snoozing)."""
        # Explicit zero coverage at the dialog layer — the same
        # invariant ``TestSnoozeValidation.test_max_snoozes_setter_accepts_boundary_values``
        # pins at the persistence layer. Together they guarantee no
        # regression on the user-disables-snoozing flow.
        dialog._max_snoozes_spinbox.setValue(0)

        dialog.accept()

        assert settings.max_snoozes == 0


# ---------------------------------------------------------------------------
# Layout — Scheduling + Notifications tabs (S-01 + S-04)
# ---------------------------------------------------------------------------


class TestLayout:
    """Layout invariants for the Scheduling tab (S-01).

    The Notifications tab's own structural invariants live in
    ``TestNotificationsTabLayout`` below.
    """

    def test_dialog_contains_a_tab_widget(self, dialog: SettingsDialog) -> None:
        """The dialog hosts a ``QTabWidget`` (not a single-pane form)."""
        # Tripwire for the tabbed-from-day-one decision in
        # context/changes/settings-break-interval/plan-brief.md.
        assert dialog.findChild(QTabWidget) is not None

    def test_tab_label_is_scheduling(self, dialog: SettingsDialog) -> None:
        """The S-01 tab label is exactly ``"Scheduling"``."""
        # Tripwire: S-02..S-05 may add tabs but should not silently
        # rename this one — other tests and docs reference the label.
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.tabText(0) == "Scheduling"

    def test_scheduling_tab_contains_a_spinbox(self, dialog: SettingsDialog) -> None:
        """The Scheduling tab contains a ``QSpinBox`` for the interval."""
        # Loose check: any QSpinBox child suffices. The TestLoad cases
        # cover the bounds and value semantics explicitly.
        assert dialog.findChild(QSpinBox) is not None

    def test_scheduling_tab_hosts_three_spinboxes(self, dialog: SettingsDialog) -> None:
        """The Scheduling tab hosts the break-interval + 2 snooze spinboxes (S-01 + S-03).

        Tripwire for the row-count contract. A future slice removing or
        repurposing one of the three rows must update this test
        deliberately.
        """
        # The dialog hosts spinboxes only on the Scheduling tab — the
        # Notifications tab uses a checkbox + line edit. ``findChildren``
        # therefore counts exactly the Scheduling-tab spinboxes.
        spinboxes = dialog.findChildren(QSpinBox)
        assert len(spinboxes) == 3


# ---------------------------------------------------------------------------
# Validation feedback — tooltip fires only on user-typed out-of-range entry
# ---------------------------------------------------------------------------


class TestValidationFeedback:
    """The transient tooltip fires only when the user typed an out-of-range value.

    Empirical Qt behavior verified during /10x-impl-review on 2026-05-25:
    ``QSpinBox`` does not "clamp" out-of-range typing — it reverts (below
    minimum) or truncates to a valid prefix (above maximum). By the time
    ``editingFinished`` fires the user's typed intent is gone from
    ``lineEdit.text()``. ``SettingsDialog`` therefore captures raw typed
    text via ``lineEdit.textEdited`` BEFORE Qt's fixup runs and parses it
    in the ``editingFinished`` slot.

    These tests pin that contract in place: the textEdited capture must
    populate ``_user_typed_text``, the editingFinished slot must consult
    it (not the post-fixup display), and ``QToolTip.showText`` must fire
    only when the captured value falls outside [1, 240]. The tests
    monkeypatch ``QToolTip.showText`` to a recording stub so the suite
    never depends on a real Qt cursor / screen geometry.
    """

    @staticmethod
    def _patch_show_text(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
        """Replace ``QToolTip.showText`` with a call-recording stub.

        Returns:
            The list that the stub appends ``(args, kwargs)`` tuples to.
            Tests assert against ``len(...)`` and the recorded payload.
        """
        calls: list[tuple] = []

        def _stub(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

        # Patch the symbol the dialog imports — settings_dialog imports
        # QToolTip from PySide6.QtWidgets, so patching at the source
        # covers the call site.
        monkeypatch.setattr(
            "break_reminder.ui.settings_dialog.QToolTip.showText",
            _stub,
        )
        return calls

    def test_text_edited_captures_typed_text(self, dialog: SettingsDialog) -> None:
        """``_on_break_interval_text_edited`` snapshots the raw typed text."""
        dialog._on_break_interval_text_edited("0 min")

        assert dialog._user_typed_text == "0 min"

    def test_in_range_typed_value_does_not_show_tooltip(
        self,
        dialog: SettingsDialog,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A valid in-range typed value commits cleanly — no tooltip."""
        calls = self._patch_show_text(monkeypatch)

        dialog._on_break_interval_text_edited("30 min")
        dialog._on_break_interval_edited()

        assert calls == []

    def test_below_min_typed_value_shows_tooltip(
        self,
        dialog: SettingsDialog,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Typed value below the FR-006 minimum surfaces the range tooltip."""
        calls = self._patch_show_text(monkeypatch)

        dialog._on_break_interval_text_edited("0 min")
        dialog._on_break_interval_edited()

        assert len(calls) == 1
        # Second positional arg is the tooltip text — assert it carries
        # the [1, 240] range message so the user sees the actual bounds.
        args, _kwargs = calls[0]
        assert "1" in args[1]
        assert "240" in args[1]

    def test_above_max_typed_value_shows_tooltip(
        self,
        dialog: SettingsDialog,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Typed value above the FR-006 maximum surfaces the range tooltip."""
        calls = self._patch_show_text(monkeypatch)

        dialog._on_break_interval_text_edited("500 min")
        dialog._on_break_interval_edited()

        assert len(calls) == 1

    def test_editing_finished_without_text_edited_no_ops(
        self,
        dialog: SettingsDialog,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No ``textEdited`` capture (e.g., spinbox arrow click) — no tooltip."""
        calls = self._patch_show_text(monkeypatch)
        # Sanity: the constructor leaves the capture slot empty.
        assert dialog._user_typed_text is None

        dialog._on_break_interval_edited()

        assert calls == []

    def test_user_typed_text_resets_after_editing_finished(
        self, dialog: SettingsDialog, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The capture slot resets after each commit so stale text doesn't leak."""
        self._patch_show_text(monkeypatch)
        dialog._on_break_interval_text_edited("30 min")
        dialog._on_break_interval_edited()

        assert dialog._user_typed_text is None

    def test_unparseable_typed_text_does_not_crash(
        self,
        dialog: SettingsDialog,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Garbage input (e.g., empty, non-numeric) returns cleanly without raising."""
        calls = self._patch_show_text(monkeypatch)

        dialog._on_break_interval_text_edited("")
        dialog._on_break_interval_edited()
        dialog._on_break_interval_text_edited("abc min")
        dialog._on_break_interval_edited()

        # Garbage neither crashes nor surfaces the tooltip — the int()
        # parse fails and the slot returns early.
        assert calls == []


# ---------------------------------------------------------------------------
# Notifications tab — load (S-04)
# ---------------------------------------------------------------------------


class TestNotificationsTabLoad:
    """Initial Notifications-tab state reflects ``Settings.voice_*`` (FR-007)."""

    def test_checkbox_unchecked_by_default(self, dialog: SettingsDialog) -> None:
        """FR-007: voice is opt-in — checkbox unchecked on a fresh INI."""
        assert dialog._voice_enabled_checkbox.isChecked() is False

    def test_checkbox_reflects_pre_set_voice_enabled(
        self, qtbot, ini_path: Path, voice: StubVoiceNotifier
    ) -> None:
        """The checkbox shows whatever ``Settings.voice_enabled`` already holds."""
        pre_set = Settings(ini_path=ini_path)
        pre_set.voice_enabled = True
        pre_set._qs.sync()
        del pre_set

        d = SettingsDialog(
            settings=Settings(ini_path=ini_path),
            voice=voice,  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)

        assert d._voice_enabled_checkbox.isChecked() is True

    def test_phrase_field_shows_default_phrase(self, dialog: SettingsDialog) -> None:
        """The phrase field is pre-filled with ``DEFAULT_VOICE_PHRASE`` on a fresh INI."""
        assert dialog._voice_phrase_edit.text() == DEFAULT_VOICE_PHRASE

    def test_phrase_field_reflects_pre_set_voice_phrase(
        self, qtbot, ini_path: Path, voice: StubVoiceNotifier
    ) -> None:
        """The phrase field shows whatever ``Settings.voice_phrase`` already holds."""
        pre_set = Settings(ini_path=ini_path)
        pre_set.voice_phrase = "Stretch your back"
        pre_set._qs.sync()
        del pre_set

        d = SettingsDialog(
            settings=Settings(ini_path=ini_path),
            voice=voice,  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)

        assert d._voice_phrase_edit.text() == "Stretch your back"

    def test_checkbox_tooltip_explains_alongside_contract(self, dialog: SettingsDialog) -> None:
        """The checkbox tooltip surfaces the FR-007 popup-is-mandatory contract.

        Tripwire for the Q4 commitment in
        ``context/changes/settings-voice-toggle/plan-brief.md`` — the
        tooltip is the only UI surface that explains the popup-vs-voice
        relationship; if it goes missing the user has no way to learn
        that voice is additive, not a replacement.
        """
        tooltip = dialog._voice_enabled_checkbox.toolTip()
        assert "alongside" in tooltip.lower()

    def test_phrase_field_enabled_when_checkbox_unchecked(self, dialog: SettingsDialog) -> None:
        """Phrase is editable even when voice is off (Q2: always editable)."""
        # Sanity precondition: the fixture-built dialog has the checkbox
        # unchecked. The phrase line edit must still accept input so
        # the user can prepare the phrase before flipping the gate.
        assert dialog._voice_enabled_checkbox.isChecked() is False
        assert dialog._voice_phrase_edit.isEnabled() is True

    def test_phrase_field_enabled_when_checkbox_checked(self, dialog: SettingsDialog) -> None:
        """Phrase remains editable when voice is on (Q2: always editable)."""
        dialog._voice_enabled_checkbox.setChecked(True)
        assert dialog._voice_phrase_edit.isEnabled() is True


# ---------------------------------------------------------------------------
# Notifications tab — save (S-04)
# ---------------------------------------------------------------------------


class TestNotificationsTabSave:
    """OK persists voice settings; Cancel discards. Co-saves with break interval."""

    def test_accept_persists_checkbox_true(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """``accept()`` writes ``voice_enabled = True`` through the setter."""
        dialog._voice_enabled_checkbox.setChecked(True)

        dialog.accept()

        assert settings.voice_enabled is True

    def test_accept_persists_phrase_change(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """``accept()`` writes the edited phrase through ``Settings.voice_phrase``."""
        dialog._voice_phrase_edit.setText("Stand up and stretch")

        dialog.accept()

        assert settings.voice_phrase == "Stand up and stretch"

    def test_accept_persists_voice_across_settings_instances(
        self, qtbot, ini_path: Path, voice: StubVoiceNotifier
    ) -> None:
        """Voice settings are observable from a freshly constructed ``Settings``."""
        first_settings = Settings(ini_path=ini_path)
        d = SettingsDialog(
            settings=first_settings,
            voice=voice,  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)
        d._voice_enabled_checkbox.setChecked(True)
        d._voice_phrase_edit.setText("Time for a stretch")
        d.accept()
        first_settings._qs.sync()
        del first_settings

        second_settings = Settings(ini_path=ini_path)
        assert second_settings.voice_enabled is True
        assert second_settings.voice_phrase == "Time for a stretch"

    def test_reject_does_not_persist_voice(
        self, qtbot, settings: Settings, voice: StubVoiceNotifier
    ) -> None:
        """``reject()`` after editing voice fields leaves ``Settings`` untouched."""
        # Pre-set known values so absence-of-write is observable.
        settings.voice_enabled = True
        settings.voice_phrase = "original phrase"
        settings._qs.sync()

        d = SettingsDialog(settings=settings, voice=voice)  # type: ignore[arg-type]
        qtbot.addWidget(d)
        d._voice_enabled_checkbox.setChecked(False)
        d._voice_phrase_edit.setText("rejected phrase")

        d.reject()

        assert settings.voice_enabled is True
        assert settings.voice_phrase == "original phrase"

    def test_accept_co_saves_break_interval_and_voice(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """A single ``accept()`` persists Scheduling AND Notifications fields together.

        Tripwire for an S-01 regression — extending ``accept()`` to
        cover the voice fields must NOT skip the break-interval write.
        """
        dialog._break_interval_spinbox.setValue(45)
        dialog._voice_enabled_checkbox.setChecked(True)
        dialog._voice_phrase_edit.setText("Combined save")

        dialog.accept()

        assert settings.break_interval_min == 45
        assert settings.voice_enabled is True
        assert settings.voice_phrase == "Combined save"


# ---------------------------------------------------------------------------
# Notifications tab — validation (voice on + blank phrase blocks save)
# ---------------------------------------------------------------------------


class TestNotificationsTabValidation:
    """The (voice on, blank phrase) combination cannot land via the GUI.

    The persistence-layer setter accepts an empty phrase (see
    ``tests/test_settings.py::TestVoiceSettersRoundTrip``); the dialog
    is the only place that gates the combination. These tests pin
    that gate in place.
    """

    @staticmethod
    def _patch_show_text(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
        """Replace ``QToolTip.showText`` with a recording stub."""
        calls: list[tuple] = []

        def _stub(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))

        monkeypatch.setattr(
            "break_reminder.ui.settings_dialog.QToolTip.showText",
            _stub,
        )
        return calls

    def test_voice_on_blank_phrase_blocks_save(
        self,
        dialog: SettingsDialog,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Voice on + empty phrase → no setter writes, no ``super().accept()``.

        Atomic-save tripwire: every persisted field — break interval,
        snooze duration, max snoozes, voice toggle, voice phrase, AND
        autostart — must remain at its pre-edit value when the voice
        gate trips. If a future refactor reorders any setter before the
        validation gate, one of the assertions below catches it.
        """
        self._patch_show_text(monkeypatch)
        # Pre-set a known persisted state so absence of writes is observable.
        settings.voice_enabled = False
        settings.voice_phrase = "untouched"
        # Distinct values across all four persisted fields so we can prove
        # the gate is atomic — every edit must NOT leak through when the
        # voice gate trips (impl-review F2 tripwire). The break-interval
        # tripwire pre-dates this slice; the snooze tripwires were added
        # during settings-snooze-config impl-review F2; the autostart
        # tripwire was added during settings-autostart-toggle.
        settings.break_interval_min = 60
        settings.snooze_duration_min = 10
        settings.max_snoozes = 3
        settings.autostart = False
        settings._qs.sync()

        dialog._break_interval_spinbox.setValue(30)
        dialog._snooze_duration_spinbox.setValue(7)
        dialog._max_snoozes_spinbox.setValue(4)
        dialog._voice_enabled_checkbox.setChecked(True)
        dialog._voice_phrase_edit.setText("")
        # Tick the autostart checkbox too — the test must prove that
        # neither the registry side-effect NOR the autostart INI write
        # fires when the voice gate trips first. Stub the helpers so a
        # gate failure is the ONLY thing that could possibly skip the
        # writes (eliminates "the registry call swallowed an exception"
        # as a confounder).
        write_calls: list[str] = []
        delete_calls: list[None] = []
        monkeypatch.setattr(
            settings_dialog_module,
            "_write_autostart_runkey",
            lambda command: write_calls.append(command),
        )
        monkeypatch.setattr(
            settings_dialog_module,
            "_delete_autostart_runkey",
            lambda: delete_calls.append(None),
        )
        dialog._autostart_checkbox.setChecked(True)

        dialog.accept()

        # The early-return path means none of the setters ran.
        # Re-read from disk to be sure no write slipped through.
        fresh = Settings(ini_path=Path(settings._qs.fileName()))
        assert fresh.voice_enabled is False
        assert fresh.voice_phrase == "untouched"
        # F2: atomic-save tripwire — every otherwise-valid Scheduling-tab
        # and Lifecycle-tab edit must NOT have leaked through when the
        # voice gate trips. If a future refactor reorders any of these
        # setters before the validation gate, the corresponding line
        # below asserts.
        assert fresh.break_interval_min == 60
        assert fresh.snooze_duration_min == 10
        assert fresh.max_snoozes == 3
        assert fresh.autostart is False
        # And critically: the autostart side-effect must NOT have fired
        # either — the voice gate is the FIRST thing in accept(), before
        # the side-effect block. Both helper stubs stay empty.
        assert write_calls == []
        assert delete_calls == []
        # Dialog stays open — Qt's accept() chain was skipped.
        assert dialog.result() == 0
        # F1: the user must land on the Notifications tab so the tooltip
        # anchor (`_voice_phrase_edit`) is on the visible tab. If the user
        # clicked OK from Scheduling, the dialog flips for them.
        assert dialog._tabs.currentWidget() is dialog._notifications_tab

    def test_voice_on_whitespace_phrase_blocks_save(
        self,
        dialog: SettingsDialog,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Voice on + whitespace-only phrase → blocked the same as fully blank."""
        self._patch_show_text(monkeypatch)
        settings.voice_enabled = False
        settings.voice_phrase = "untouched"
        settings._qs.sync()

        dialog._voice_enabled_checkbox.setChecked(True)
        dialog._voice_phrase_edit.setText("   \t  ")

        dialog.accept()

        fresh = Settings(ini_path=Path(settings._qs.fileName()))
        assert fresh.voice_enabled is False
        assert fresh.voice_phrase == "untouched"

    def test_voice_on_blank_phrase_surfaces_tooltip(
        self,
        dialog: SettingsDialog,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The blocking branch surfaces the FR-007 required-phrase tooltip."""
        calls = self._patch_show_text(monkeypatch)
        dialog._voice_enabled_checkbox.setChecked(True)
        dialog._voice_phrase_edit.setText("")

        dialog.accept()

        assert len(calls) == 1
        args, _kwargs = calls[0]
        # Second positional arg is the tooltip text.
        assert "voice phrase" in args[1].lower()
        assert "empty" in args[1].lower()

    def test_voice_on_non_empty_phrase_saves(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """Voice on + non-empty phrase → save proceeds and dialog closes."""
        dialog._voice_enabled_checkbox.setChecked(True)
        dialog._voice_phrase_edit.setText("Stretch")

        dialog.accept()

        assert settings.voice_enabled is True
        assert settings.voice_phrase == "Stretch"

    def test_voice_off_empty_phrase_saves(self, dialog: SettingsDialog, settings: Settings) -> None:
        """Voice off + empty phrase → save proceeds; the empty phrase persists silently.

        The dialog only gates the (voice on, empty phrase) combination.
        With voice off the empty phrase is unobservable to the user
        and harmless on disk.
        """
        dialog._voice_enabled_checkbox.setChecked(False)
        dialog._voice_phrase_edit.setText("")

        dialog.accept()

        assert settings.voice_enabled is False
        assert settings.voice_phrase == ""


# ---------------------------------------------------------------------------
# Notifications tab — Test voice button
# ---------------------------------------------------------------------------


class TestNotificationsTabTestButton:
    """The Test button speaks the line edit's current text via injected ``VoiceNotifier``."""

    def test_click_calls_speak_once(self, dialog: SettingsDialog, voice: StubVoiceNotifier) -> None:
        """One Test-button click results in exactly one ``speak`` invocation."""
        dialog._voice_test_button.click()

        assert len(voice.spoken) == 1

    def test_click_cancels_prior_in_flight_speech(
        self, dialog: SettingsDialog, voice: StubVoiceNotifier
    ) -> None:
        """Each Test click calls ``stop()`` first so rapid clicks don't queue (F3).

        Without this contract, five rapid clicks would queue five copies of
        the speech in the single-worker thread pool. Calling ``stop()``
        before each ``speak()`` lets each click cancel its predecessor,
        matching the user's mental model of "click again to replace".
        """
        dialog._voice_test_button.click()
        dialog._voice_test_button.click()
        dialog._voice_test_button.click()

        # One stop per click, including the very first (idempotent on a
        # cold notifier — the F3 contract is "always cancel before speak").
        assert voice.stop_calls == 3
        assert len(voice.spoken) == 3

    def test_click_speaks_current_text(
        self, dialog: SettingsDialog, voice: StubVoiceNotifier
    ) -> None:
        """``speak`` receives the line edit's CURRENT (unsaved) text."""
        dialog._voice_phrase_edit.setText("preview phrase")

        dialog._voice_test_button.click()

        assert voice.spoken == ["preview phrase"]

    def test_click_speaks_unsaved_edits(
        self, dialog: SettingsDialog, voice: StubVoiceNotifier
    ) -> None:
        """Editing then clicking Test (without OK) → speak gets the unsaved text."""
        # Default phrase is in the line edit; user types something else
        # but doesn't click OK.
        dialog._voice_phrase_edit.setText("not yet saved")

        dialog._voice_test_button.click()

        assert voice.spoken == ["not yet saved"]

    def test_click_does_not_write_to_settings(
        self, dialog: SettingsDialog, settings: Settings
    ) -> None:
        """Clicking Test is a pure side-effect — ``Settings`` is not touched."""
        # Pre-set known values; clicking Test must not change them.
        settings.voice_enabled = False
        settings.voice_phrase = "before"
        settings._qs.sync()

        dialog._voice_phrase_edit.setText("during preview")
        dialog._voice_test_button.click()

        assert settings.voice_enabled is False
        assert settings.voice_phrase == "before"


# ---------------------------------------------------------------------------
# Notifications tab — layout
# ---------------------------------------------------------------------------


class TestNotificationsTabLayout:
    """Layout invariants for the Notifications tab (S-04)."""

    def test_dialog_has_three_tabs(self, dialog: SettingsDialog) -> None:
        """S-02 + S-04 ship two tabs alongside Scheduling — total three."""
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.count() == 3

    def test_second_tab_label_is_notifications(self, dialog: SettingsDialog) -> None:
        """The Notifications tab label is exactly ``"Notifications"``."""
        # Tripwire: future slices should not silently rename — other
        # tests and docs reference this label.
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.tabText(1) == "Notifications"

    def test_notifications_tab_contains_a_checkbox(self, dialog: SettingsDialog) -> None:
        """The Notifications tab contains a ``QCheckBox`` for the voice toggle."""
        assert dialog.findChild(QCheckBox) is not None

    def test_notifications_tab_contains_a_line_edit(self, dialog: SettingsDialog) -> None:
        """The Notifications tab contains a ``QLineEdit`` for the phrase."""
        # The Scheduling tab's spinbox owns its own QLineEdit child, so
        # we assert against the dialog-level dialog-owned line edit
        # the builder stores as a public-ish attribute.
        assert dialog._voice_phrase_edit is not None
        assert isinstance(dialog._voice_phrase_edit, QLineEdit)

    def test_notifications_tab_contains_a_test_button(self, dialog: SettingsDialog) -> None:
        """The Notifications tab contains the Test-voice ``QPushButton``."""
        # Find any QPushButton in the dialog tree. The DialogButtonBox
        # also contains buttons, so we filter by the documented label.
        buttons = dialog.findChildren(QPushButton)
        labels = [b.text() for b in buttons]
        assert "Test voice" in labels


# ---------------------------------------------------------------------------
# Lifecycle tab — layout (S-02)
# ---------------------------------------------------------------------------


class TestLifecycleTabLayout:
    """Layout invariants for the Lifecycle tab (S-02 / FR-003)."""

    def test_third_tab_label_is_lifecycle(self, dialog: SettingsDialog) -> None:
        """The Lifecycle tab label is exactly ``"Lifecycle"``.

        Tripwire: future slices may add tabs but should not silently
        rename this one — the plan, README, and other tests reference
        the label.
        """
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.tabText(2) == "Lifecycle"

    def test_lifecycle_tab_contains_autostart_checkbox(self, dialog: SettingsDialog) -> None:
        """The Lifecycle tab exposes the autostart ``QCheckBox`` attribute."""
        assert dialog._autostart_checkbox is not None
        assert isinstance(dialog._autostart_checkbox, QCheckBox)

    def test_autostart_checkbox_label_matches_roadmap_wording(self, dialog: SettingsDialog) -> None:
        """The checkbox text is the exact roadmap S-02 wording.

        Tripwire: the wording is the contract between the roadmap, the
        plan, and the running UI. Drift would silently break docs and
        the manual smoke checklist.
        """
        assert dialog._autostart_checkbox.text() == "Launch BreakReminder at Windows login"


# ---------------------------------------------------------------------------
# Lifecycle tab — load (S-02 / FR-003)
# ---------------------------------------------------------------------------


class TestLifecycleTabLoad:
    """Initial Lifecycle-tab state reflects ``Settings.autostart`` (FR-003)."""

    def test_autostart_checkbox_unchecked_when_setting_false(self, dialog: SettingsDialog) -> None:
        """FR-003 default: autostart is opt-in — checkbox unchecked on a fresh INI."""
        assert dialog._autostart_checkbox.isChecked() is False

    def test_autostart_checkbox_checked_when_setting_true(
        self, qtbot, ini_path: Path, voice: StubVoiceNotifier
    ) -> None:
        """The checkbox shows whatever ``Settings.autostart`` already holds."""
        pre_set = Settings(ini_path=ini_path)
        pre_set.autostart = True
        pre_set._qs.sync()
        del pre_set

        d = SettingsDialog(
            settings=Settings(ini_path=ini_path),
            voice=voice,  # type: ignore[arg-type]
        )
        qtbot.addWidget(d)

        assert d._autostart_checkbox.isChecked() is True


# ---------------------------------------------------------------------------
# Lifecycle tab — save (S-02 / FR-003)
# ---------------------------------------------------------------------------


def _patch_runkey_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], list[None]]:
    """Replace the autostart Run-key helpers with capture stubs.

    Returns:
        Two lists. The first records every ``_write_autostart_runkey``
        call's ``command`` argument; the second appends one ``None`` per
        ``_delete_autostart_runkey`` call. Tests assert against
        ``len(...)`` and the recorded payload.
    """
    write_calls: list[str] = []
    delete_calls: list[None] = []

    monkeypatch.setattr(
        settings_dialog_module,
        "_write_autostart_runkey",
        lambda command: write_calls.append(command),
    )
    monkeypatch.setattr(
        settings_dialog_module,
        "_delete_autostart_runkey",
        lambda: delete_calls.append(None),
    )
    return write_calls, delete_calls


class TestAutostartTabSave:
    """OK persists autostart through ``Settings`` AND the Run-key helpers (FR-003).

    The Run-key helpers are monkeypatched to capture stubs so the suite
    never touches the real Windows registry. Tests for the helpers
    themselves live in ``TestRunkeyHelpers`` below.
    """

    def test_check_and_ok_writes_runkey_with_quoted_executable(
        self,
        dialog: SettingsDialog,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Tick + OK → ``_write_autostart_runkey`` called once with quoted ``sys.executable``."""
        write_calls, delete_calls = _patch_runkey_helpers(monkeypatch)
        dialog._autostart_checkbox.setChecked(True)

        dialog.accept()

        assert write_calls == [f'"{sys.executable}"']
        assert delete_calls == []
        assert settings.autostart is True

    def test_uncheck_and_ok_deletes_runkey(
        self,
        qtbot,
        ini_path: Path,
        voice: StubVoiceNotifier,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Untick + OK → ``_delete_autostart_runkey`` called once; INI flips to False."""
        # Pre-set autostart=True so unticking is a state change.
        pre_set = Settings(ini_path=ini_path)
        pre_set.autostart = True
        pre_set._qs.sync()
        del pre_set

        s = Settings(ini_path=ini_path)
        d = SettingsDialog(settings=s, voice=voice)  # type: ignore[arg-type]
        qtbot.addWidget(d)

        write_calls, delete_calls = _patch_runkey_helpers(monkeypatch)
        d._autostart_checkbox.setChecked(False)

        d.accept()

        assert write_calls == []
        assert len(delete_calls) == 1
        assert s.autostart is False

    def test_no_change_still_idempotently_re_issues(
        self,
        qtbot,
        ini_path: Path,
        voice: StubVoiceNotifier,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Opening with autostart=True and OK without changing the box still re-issues the write.

        Per the "no reconciliation" drift policy: every OK click issues
        an idempotent write or delete from scratch. A user who manually
        deleted the Run-key in regedit gets it back next OK without
        having to toggle the checkbox.
        """
        # Pre-set autostart=True; open dialog; click OK without touching
        # the checkbox.
        pre_set = Settings(ini_path=ini_path)
        pre_set.autostart = True
        pre_set._qs.sync()
        del pre_set

        s = Settings(ini_path=ini_path)
        d = SettingsDialog(settings=s, voice=voice)  # type: ignore[arg-type]
        qtbot.addWidget(d)
        # Sanity: the dialog loaded the True state.
        assert d._autostart_checkbox.isChecked() is True

        write_calls, delete_calls = _patch_runkey_helpers(monkeypatch)

        d.accept()

        assert write_calls == [f'"{sys.executable}"']
        assert delete_calls == []

    def test_runkey_helper_oserror_blocks_save_and_anchors_tooltip(
        self,
        dialog: SettingsDialog,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Helper raises ``OSError`` → no INI fields modified, dialog stays open, tab is Lifecycle."""

        def _raise(_command: str) -> None:
            raise OSError("simulated registry failure")

        monkeypatch.setattr(settings_dialog_module, "_write_autostart_runkey", _raise)
        # Patch QToolTip so the test doesn't depend on real Qt cursor geometry.
        tooltip_calls: list[tuple] = []
        monkeypatch.setattr(
            "break_reminder.ui.settings_dialog.QToolTip.showText",
            lambda *args, **kwargs: tooltip_calls.append((args, kwargs)),
        )

        # Pre-set distinct INI values across all four fields so absence
        # of writes is observable.
        settings.break_interval_min = 60
        settings.snooze_duration_min = 10
        settings.max_snoozes = 3
        settings.voice_enabled = False
        settings.voice_phrase = "untouched"
        settings.autostart = False
        settings._qs.sync()

        # User edits everything and ticks autostart.
        dialog._break_interval_spinbox.setValue(30)
        dialog._snooze_duration_spinbox.setValue(7)
        dialog._max_snoozes_spinbox.setValue(4)
        dialog._voice_enabled_checkbox.setChecked(True)
        dialog._voice_phrase_edit.setText("Edited")
        dialog._autostart_checkbox.setChecked(True)

        dialog.accept()

        # Atomic save: NO INI field was written.
        fresh = Settings(ini_path=Path(settings._qs.fileName()))
        assert fresh.break_interval_min == 60
        assert fresh.snooze_duration_min == 10
        assert fresh.max_snoozes == 3
        assert fresh.voice_enabled is False
        assert fresh.voice_phrase == "untouched"
        assert fresh.autostart is False
        # Dialog stayed open.
        assert dialog.result() == 0
        # User landed on the Lifecycle tab so the tooltip is visible.
        assert dialog._tabs.currentWidget() is dialog._lifecycle_tab
        # And the tooltip surfaced with the documented failure message.
        assert len(tooltip_calls) == 1
        args, _kwargs = tooltip_calls[0]
        assert "autostart" in args[1].lower()

    def test_runkey_helper_permissionerror_also_blocks_save(
        self,
        dialog: SettingsDialog,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``PermissionError`` (subclass of ``OSError``) trips the same atomic-save guarantee."""

        def _raise(_command: str) -> None:
            raise PermissionError("simulated GPO block")

        monkeypatch.setattr(settings_dialog_module, "_write_autostart_runkey", _raise)
        monkeypatch.setattr(
            "break_reminder.ui.settings_dialog.QToolTip.showText",
            lambda *args, **kwargs: None,
        )
        settings.break_interval_min = 60
        settings._qs.sync()

        dialog._break_interval_spinbox.setValue(30)
        dialog._autostart_checkbox.setChecked(True)

        dialog.accept()

        fresh = Settings(ini_path=Path(settings._qs.fileName()))
        # No INI write slipped through.
        assert fresh.break_interval_min == 60
        assert fresh.autostart is False
        assert dialog.result() == 0
        assert dialog._tabs.currentWidget() is dialog._lifecycle_tab

    def test_delete_helper_oserror_blocks_save(
        self,
        dialog: SettingsDialog,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Untick path: ``_delete_autostart_runkey`` raises ``OSError`` → atomic-save tripwire fires symmetrically."""

        def _raise() -> None:
            raise OSError("simulated registry failure on delete")

        monkeypatch.setattr(settings_dialog_module, "_delete_autostart_runkey", _raise)
        monkeypatch.setattr(
            "break_reminder.ui.settings_dialog.QToolTip.showText",
            lambda *args, **kwargs: None,
        )
        settings.break_interval_min = 60
        settings.autostart = True
        settings._qs.sync()

        dialog._break_interval_spinbox.setValue(30)
        dialog._autostart_checkbox.setChecked(False)

        dialog.accept()

        fresh = Settings(ini_path=Path(settings._qs.fileName()))
        assert fresh.break_interval_min == 60
        assert fresh.autostart is True
        assert dialog.result() == 0
        assert dialog._tabs.currentWidget() is dialog._lifecycle_tab


# ---------------------------------------------------------------------------
# winreg helper internals (S-02 / FR-003)
# ---------------------------------------------------------------------------


class TestRunkeyHelpers:
    """The two module-level winreg helpers behave correctly against a stubbed registry.

    Tests monkeypatch ``winreg.CreateKeyEx`` (write path) / ``winreg.OpenKey``
    (delete path) / ``SetValueEx`` / ``DeleteValue`` so the suite never
    touches the real Windows registry. The dialog flow tests in
    ``TestAutostartTabSave`` patch the helpers themselves; these tests
    pin the helpers' contract independent of the dialog.
    """

    @staticmethod
    def _patch_winreg(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[tuple]]:
        """Replace the load-bearing ``winreg`` calls with capture stubs.

        ``CreateKeyEx`` (used by the write helper to open-or-create the
        Run subkey) and ``OpenKey`` (used by the delete helper) are both
        patched to return a context-manager-friendly fake handle, since
        the helpers use them as ``with winreg.CreateKeyEx(...) as key:``
        and ``with winreg.OpenKey(...) as key:`` respectively.
        ``SetValueEx`` / ``DeleteValue`` are patched to record their args.

        Returns:
            A dict with four keys: ``create``, ``open``, ``set``,
            ``delete``. Each maps to a list of ``(args, kwargs)`` tuples
            — the calls captured during the test.
        """
        captured: dict[str, list[tuple]] = {
            "create": [],
            "open": [],
            "set": [],
            "delete": [],
        }

        class _FakeHandle:
            def __enter__(self) -> object:
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        def _create_stub(*args: object, **kwargs: object) -> _FakeHandle:
            captured["create"].append((args, kwargs))
            return _FakeHandle()

        def _open_stub(*args: object, **kwargs: object) -> _FakeHandle:
            captured["open"].append((args, kwargs))
            return _FakeHandle()

        def _set_stub(*args: object, **kwargs: object) -> None:
            captured["set"].append((args, kwargs))

        def _delete_stub(*args: object, **kwargs: object) -> None:
            captured["delete"].append((args, kwargs))

        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.CreateKeyEx", _create_stub)
        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.OpenKey", _open_stub)
        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.SetValueEx", _set_stub)
        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.DeleteValue", _delete_stub)
        return captured

    def test_write_helper_calls_set_value_ex_with_correct_args(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_write_autostart_runkey`` writes ``(value_name, 0, REG_SZ, command)``."""
        import winreg

        captured = self._patch_winreg(monkeypatch)

        settings_dialog_module._write_autostart_runkey('"C:\\path with spaces\\BreakReminder.exe"')

        assert len(captured["set"]) == 1
        args, _kwargs = captured["set"][0]
        # Args are (key, value_name, reserved, type, data) per winreg.SetValueEx.
        # We don't assert on `key` (it's the FakeHandle) but DO assert on
        # the rest of the contract.
        _key, value_name, reserved, value_type, data = args
        assert value_name == "BreakReminder"
        assert reserved == 0
        assert value_type == winreg.REG_SZ
        assert data == '"C:\\path with spaces\\BreakReminder.exe"'

    def test_write_helper_uses_createkeyex_against_hkcu_run_subkey(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The write helper calls ``CreateKeyEx`` against HKCU + the documented Run subkey.

        ``CreateKeyEx`` (not ``OpenKey``) is the canonical Run-key idiom
        — it opens the subkey if it exists and creates it if absent,
        eliminating the "subkey missing on a fresh user profile"
        failure mode that breaks plain ``OpenKey``.
        """
        import winreg

        captured = self._patch_winreg(monkeypatch)

        settings_dialog_module._write_autostart_runkey('"x"')

        assert len(captured["create"]) == 1, (
            "write helper must use CreateKeyEx, not OpenKey — otherwise a "
            "machine without an existing Run subkey (e.g. fresh CI runner) "
            "fails on tick + OK"
        )
        assert captured["open"] == [], (
            "write helper must NOT call OpenKey — the create-or-open semantic "
            "of CreateKeyEx is required for the subkey-missing case"
        )
        args, _kwargs = captured["create"][0]
        # Args are (hkey, subkey, reserved, access).
        hkey, subkey, _reserved, access = args
        assert hkey == winreg.HKEY_CURRENT_USER
        assert subkey == r"Software\Microsoft\Windows\CurrentVersion\Run"
        assert access == winreg.KEY_SET_VALUE

    def test_write_helper_succeeds_when_subkey_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r"""Write helper does not raise when the Run subkey did not previously exist.

        ``CreateKeyEx`` transparently creates the subkey in that case
        and returns a usable handle, so ``SetValueEx`` still runs.
        Direct regression test for the production scenario where a
        brand-new Windows profile (CI runner, fresh user) has never
        touched ``HKCU\...\Run`` — the previous ``OpenKey``-based
        implementation would have raised ``FileNotFoundError`` here.
        """
        captured = self._patch_winreg(monkeypatch)

        # Must not raise — the stubbed CreateKeyEx returns a fake handle
        # regardless of whether the "real" subkey exists, mirroring the
        # OS-level create-or-open behaviour.
        settings_dialog_module._write_autostart_runkey('"x"')

        assert len(captured["create"]) == 1
        assert len(captured["set"]) == 1, (
            "SetValueEx must run on the handle returned by CreateKeyEx, "
            "even when the subkey had to be created from scratch"
        )

    def test_delete_helper_calls_delete_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``_delete_autostart_runkey`` calls ``DeleteValue`` with the right value name."""
        captured = self._patch_winreg(monkeypatch)

        settings_dialog_module._delete_autostart_runkey()

        assert len(captured["delete"]) == 1
        args, _kwargs = captured["delete"][0]
        # Args are (key, value_name).
        _key, value_name = args
        assert value_name == "BreakReminder"

    def test_delete_helper_swallows_filenotfounderror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting an absent value is success — ``FileNotFoundError`` is swallowed.

        Without this, an untick-then-OK on a system that never had the
        Run-key entry would raise into ``accept()`` and trip the
        atomic-save tooltip. The helper deliberately treats the
        not-present case as already-deleted.
        """
        # Patch OpenKey to a fake handle that survives `with`, then
        # patch DeleteValue to raise.
        self._patch_winreg(monkeypatch)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("absent value")

        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.DeleteValue", _raise)

        # Must not raise.
        settings_dialog_module._delete_autostart_runkey()

    def test_delete_helper_swallows_filenotfounderror_when_subkey_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r"""``OpenKey`` raising ``FileNotFoundError`` (subkey absent) is swallowed too.

        Direct regression test for the CI-runner failure mode: on a
        freshly provisioned Windows profile the
        ``HKCU\Software\Microsoft\Windows\CurrentVersion\Run``
        subkey itself does not exist, so ``OpenKey`` — not
        ``DeleteValue`` — raises ``FileNotFoundError [WinError 2]``.
        Both "subkey absent" and "value absent" must map to the same
        "already-deleted" success semantic, otherwise every dialog save
        on such a machine trips the atomic-save tooltip.
        """
        self._patch_winreg(monkeypatch)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("absent subkey")

        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.OpenKey", _raise)

        # Must not raise.
        settings_dialog_module._delete_autostart_runkey()

    def test_delete_helper_propagates_other_oserror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-``FileNotFoundError`` ``OSError``s propagate out of the helper.

        Tripwire: the broad-catch ``except FileNotFoundError`` must NOT
        accidentally turn into ``except OSError`` — that would mask
        permission errors as silent success.
        """
        self._patch_winreg(monkeypatch)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("simulated GPO block")

        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.DeleteValue", _raise)

        with pytest.raises(PermissionError):
            settings_dialog_module._delete_autostart_runkey()

    def test_delete_helper_propagates_oserror_from_openkey(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``OpenKey`` raising a non-``FileNotFoundError`` ``OSError`` propagates.

        Symmetric tripwire to ``test_delete_helper_propagates_other_oserror``
        (which exercises the ``DeleteValue`` raise-site). The broadened
        outer ``except FileNotFoundError`` must continue to let
        ``PermissionError`` / generic ``OSError`` from ``OpenKey``
        bubble up so the dialog can surface its autostart tooltip.
        """
        self._patch_winreg(monkeypatch)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("simulated GPO block on OpenKey")

        monkeypatch.setattr("break_reminder.ui.settings_dialog.winreg.OpenKey", _raise)

        with pytest.raises(PermissionError):
            settings_dialog_module._delete_autostart_runkey()
