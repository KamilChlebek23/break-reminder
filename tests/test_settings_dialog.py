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
        """Voice on + empty phrase → no setter writes, no ``super().accept()``."""
        self._patch_show_text(monkeypatch)
        # Pre-set a known persisted state so absence of writes is observable.
        settings.voice_enabled = False
        settings.voice_phrase = "untouched"
        # Distinct values across all three Scheduling-tab fields so we can
        # prove the gate is atomic — every edit must NOT leak through when
        # the voice gate trips (impl-review F2 tripwire). The break-interval
        # tripwire pre-dates this slice; the snooze-duration / max-snoozes
        # tripwires were added during the settings-snooze-config impl-review.
        settings.break_interval_min = 60
        settings.snooze_duration_min = 10
        settings.max_snoozes = 3
        settings._qs.sync()

        dialog._break_interval_spinbox.setValue(30)
        dialog._snooze_duration_spinbox.setValue(7)
        dialog._max_snoozes_spinbox.setValue(4)
        dialog._voice_enabled_checkbox.setChecked(True)
        dialog._voice_phrase_edit.setText("")

        dialog.accept()

        # The early-return path means none of the setters ran.
        # Re-read from disk to be sure no write slipped through.
        fresh = Settings(ini_path=Path(settings._qs.fileName()))
        assert fresh.voice_enabled is False
        assert fresh.voice_phrase == "untouched"
        # F2: atomic-save tripwire — every otherwise-valid Scheduling-tab edit
        # must NOT have leaked through when the voice gate trips. If a future
        # refactor reorders any of these setters before the validation gate,
        # the corresponding line below asserts.
        assert fresh.break_interval_min == 60
        assert fresh.snooze_duration_min == 10
        assert fresh.max_snoozes == 3
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

    def test_dialog_has_two_tabs(self, dialog: SettingsDialog) -> None:
        """S-04 ships a second tab alongside Scheduling."""
        tabs = dialog.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.count() == 2

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
