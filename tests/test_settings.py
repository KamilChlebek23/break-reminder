"""Round-trip tests for ``break_reminder.storage.settings``.

Covers FR-002 (settings persist under per-user app-data folder),
FR-003 (autostart opt-in), FR-006 (break interval 1-240 minutes),
FR-010 (snooze defaults), and FR-016 (paused state lifecycle including
the reboot-clear contract).

Each test gets a fresh INI file under pytest's ``tmp_path`` so the
suite never touches the real ``%APPDATA%`` location.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from break_reminder.storage.settings import (
    DEFAULT_AUTOSTART,
    DEFAULT_BREAK_INTERVAL_MIN,
    DEFAULT_IDLE_THRESHOLD_SEC,
    DEFAULT_MAX_SNOOZES,
    DEFAULT_SNOOZE_DURATION_MIN,
    DEFAULT_VOICE_ENABLED,
    DEFAULT_VOICE_PHRASE,
    Settings,
    _Keys,
)

# Note: range constants for the snooze setters
# (``SNOOZE_DURATION_*_MINUTES`` / ``MAX_SNOOZES_*``) are referenced via
# the literal numbers in the test names + ``ValueError`` regex strings
# rather than imported, mirroring the way ``TestValidation`` pins the
# break-interval [1, 240] bounds with literal regex matches.


@pytest.fixture
def ini_path(tmp_path: Path) -> Path:
    """Path to a per-test INI file under ``tmp_path``."""
    return tmp_path / "BreakReminder.ini"


@pytest.fixture
def settings(ini_path: Path) -> Settings:
    """A ``Settings`` instance bound to the per-test ``ini_path`` fixture."""
    return Settings(ini_path=ini_path)


class TestDefaults:
    """Defaults are honored when nothing has been written yet."""

    def test_break_interval_default(self, settings: Settings) -> None:
        """Break-interval getter returns ``DEFAULT_BREAK_INTERVAL_MIN`` on a fresh INI."""
        assert settings.break_interval_min == DEFAULT_BREAK_INTERVAL_MIN

    def test_idle_threshold_default(self, settings: Settings) -> None:
        """Idle-threshold getter returns the documented default on a fresh INI."""
        assert settings.idle_threshold_sec == DEFAULT_IDLE_THRESHOLD_SEC

    def test_snooze_duration_default(self, settings: Settings) -> None:
        """Snooze-duration getter returns the documented default on a fresh INI."""
        assert settings.snooze_duration_min == DEFAULT_SNOOZE_DURATION_MIN

    def test_max_snoozes_default(self, settings: Settings) -> None:
        """Max-snoozes getter returns ``DEFAULT_MAX_SNOOZES`` on a fresh INI."""
        assert settings.max_snoozes == DEFAULT_MAX_SNOOZES

    def test_voice_disabled_by_default(self, settings: Settings) -> None:
        """FR-007: voice is opt-in — disabled until the user explicitly turns it on."""
        assert settings.voice_enabled is DEFAULT_VOICE_ENABLED is False

    def test_voice_phrase_default(self, settings: Settings) -> None:
        """Voice-phrase getter returns the documented default on a fresh INI."""
        assert settings.voice_phrase == DEFAULT_VOICE_PHRASE

    def test_autostart_disabled_by_default(self, settings: Settings) -> None:
        """FR-003: autostart is opt-in — disabled until the user explicitly opts in."""
        assert settings.autostart is DEFAULT_AUTOSTART is False

    def test_paused_false_by_default(self, settings: Settings) -> None:
        """FR-016: a fresh INI starts un-paused."""
        assert settings.paused is False


class TestRoundTrip:
    """Values written by one Settings instance are visible to a second."""

    def test_break_interval_persists_across_instances(self, ini_path: Path) -> None:
        """A break-interval write is observable from a freshly constructed instance."""
        first = Settings(ini_path=ini_path)
        first.break_interval_min = 90
        del first

        second = Settings(ini_path=ini_path)
        assert second.break_interval_min == 90

    def test_paused_persists_across_instances(self, ini_path: Path) -> None:
        """The paused flag survives instance teardown (FR-016 — until reboot)."""
        first = Settings(ini_path=ini_path)
        first.paused = True
        del first

        second = Settings(ini_path=ini_path)
        assert second.paused is True

    def test_ini_file_is_actually_written(self, ini_path: Path) -> None:
        """The first setter call materializes the INI file on disk."""
        # The INI file should not exist before we write anything,
        # and should exist on disk after a setter is invoked.
        assert not ini_path.exists()
        s = Settings(ini_path=ini_path)
        s.break_interval_min = 45
        s._qs.sync()
        assert ini_path.exists()
        contents = ini_path.read_text(encoding="utf-8")
        assert "break_interval_min" in contents
        assert "45" in contents


class TestValidation:
    """The break-interval setter enforces FR-006's [1, 240] range."""

    def test_setter_rejects_zero(self, settings: Settings) -> None:
        """Setting break-interval to 0 raises ``ValueError`` (FR-006 lower bound)."""
        with pytest.raises(ValueError, match=r"\[1, 240\]"):
            settings.break_interval_min = 0

    def test_setter_rejects_negative(self, settings: Settings) -> None:
        """Setting break-interval to a negative value raises ``ValueError``."""
        with pytest.raises(ValueError, match=r"\[1, 240\]"):
            settings.break_interval_min = -10

    def test_setter_rejects_above_240(self, settings: Settings) -> None:
        """Setting break-interval above 240 raises ``ValueError`` (FR-006 upper bound)."""
        with pytest.raises(ValueError, match=r"\[1, 240\]"):
            settings.break_interval_min = 241

    def test_setter_accepts_boundary_values(self, settings: Settings) -> None:
        """Boundary values 1 and 240 round-trip through the setter."""
        settings.break_interval_min = 1
        assert settings.break_interval_min == 1
        settings.break_interval_min = 240
        assert settings.break_interval_min == 240

    def test_getter_clamps_corrupt_high_value(self, settings: Settings) -> None:
        """A hand-edited above-range INI value is clamped to 240."""
        # Simulate a hand-edited INI containing an out-of-range value.
        # The getter must clamp rather than crash or honor the bad value.
        settings._qs.setValue(_Keys.BREAK_INTERVAL_MIN, 9999)
        settings._qs.sync()
        assert settings.break_interval_min == 240

    def test_getter_clamps_corrupt_low_value(self, settings: Settings) -> None:
        """A hand-edited below-range INI value is clamped to 1."""
        settings._qs.setValue(_Keys.BREAK_INTERVAL_MIN, -50)
        settings._qs.sync()
        assert settings.break_interval_min == 1

    def test_getter_falls_back_when_value_unparseable(self, settings: Settings) -> None:
        """Non-integer strings fall back to the default rather than crashing."""
        # Strings that can't be int()-parsed must fall back to the default,
        # not crash. QSettings stores everything as strings under IniFormat.
        settings._qs.setValue(_Keys.BREAK_INTERVAL_MIN, "not-a-number")
        settings._qs.sync()
        assert settings.break_interval_min == DEFAULT_BREAK_INTERVAL_MIN


class TestVoiceSettersRoundTrip:
    """FR-007: ``voice_enabled`` and ``voice_phrase`` setter round-trip.

    The dialog (``break_reminder.ui.settings_dialog.SettingsDialog``)
    is the only production caller of these setters today. The setters
    are intentionally permissive at the persistence layer — the dialog
    enforces the non-empty contract when ``voice_enabled`` is true.
    These tests pin the persistence behavior; the dialog-level gate
    is covered in ``tests/test_settings_dialog.py``.
    """

    def test_voice_enabled_setter_writes_true(self, settings: Settings) -> None:
        """Setting ``voice_enabled`` to True is observable via the getter."""
        settings.voice_enabled = True
        assert settings.voice_enabled is True

    def test_voice_enabled_setter_writes_false(self, settings: Settings) -> None:
        """Setting ``voice_enabled`` to False is observable via the getter."""
        # Pre-set to True so the False write is observable as a state change.
        settings.voice_enabled = True
        settings.voice_enabled = False
        assert settings.voice_enabled is False

    def test_voice_enabled_persists_across_instances(self, ini_path: Path) -> None:
        """A ``voice_enabled`` write is observable from a freshly constructed instance."""
        first = Settings(ini_path=ini_path)
        first.voice_enabled = True
        first._qs.sync()
        del first

        second = Settings(ini_path=ini_path)
        assert second.voice_enabled is True

    def test_voice_phrase_setter_writes_custom_phrase(self, settings: Settings) -> None:
        """Setting ``voice_phrase`` to a custom string is observable via the getter."""
        settings.voice_phrase = "Stretch your back"
        assert settings.voice_phrase == "Stretch your back"

    def test_voice_phrase_setter_accepts_empty_string(self, settings: Settings) -> None:
        """The persistence layer accepts an empty phrase (the dialog gates non-empty).

        Direct setter callers own whatever string they write. The dialog
        blocks empty-when-enabled at its own layer; without that gate
        nothing in the storage layer rejects the write.
        """
        settings.voice_phrase = ""
        assert settings.voice_phrase == ""

    def test_voice_phrase_persists_across_instances(self, ini_path: Path) -> None:
        """A ``voice_phrase`` write is observable from a freshly constructed instance."""
        first = Settings(ini_path=ini_path)
        first.voice_phrase = "Time for a break"
        first._qs.sync()
        del first

        second = Settings(ini_path=ini_path)
        assert second.voice_phrase == "Time for a break"


class TestSnoozeSettersRoundTrip:
    """FR-010: ``snooze_duration_min`` and ``max_snoozes`` setter round-trip.

    Mirrors ``TestVoiceSettersRoundTrip``'s shape — pins setter writes,
    getter reads, and cross-instance persistence for both snooze
    parameters. Validation contracts (range enforcement + getter clamp
    on corrupt INI) live in ``TestSnoozeValidation`` below.
    """

    def test_snooze_duration_setter_writes_value(self, settings: Settings) -> None:
        """Setting ``snooze_duration_min`` to 10 is observable via the getter."""
        settings.snooze_duration_min = 10
        assert settings.snooze_duration_min == 10

    def test_snooze_duration_persists_across_instances(self, ini_path: Path) -> None:
        """A ``snooze_duration_min`` write is observable from a fresh instance."""
        first = Settings(ini_path=ini_path)
        first.snooze_duration_min = 15
        first._qs.sync()
        del first

        second = Settings(ini_path=ini_path)
        assert second.snooze_duration_min == 15

    def test_max_snoozes_setter_writes_value(self, settings: Settings) -> None:
        """Setting ``max_snoozes`` to 3 is observable via the getter."""
        settings.max_snoozes = 3
        assert settings.max_snoozes == 3

    def test_max_snoozes_persists_across_instances(self, ini_path: Path) -> None:
        """A ``max_snoozes`` write is observable from a fresh instance."""
        first = Settings(ini_path=ini_path)
        first.max_snoozes = 4
        first._qs.sync()
        del first

        second = Settings(ini_path=ini_path)
        assert second.max_snoozes == 4


class TestSnoozeValidation:
    """FR-010: snooze setters enforce [1, 30] / [0, 5] ranges; getters clamp corrupt INI.

    Mirrors ``TestValidation`` (which pins the break-interval [1, 240]
    contract). The explicit zero coverage on ``max_snoozes`` is the
    only deviation from that template — zero is intentionally a valid
    input because the existing scheduler/dialog already handle the
    no-snooze-button path correctly when ``max_snoozes = 0``.
    """

    def test_snooze_duration_setter_rejects_zero(self, settings: Settings) -> None:
        """Setting snooze duration to 0 raises ``ValueError`` (FR-010 lower bound)."""
        with pytest.raises(ValueError, match=r"\[1, 30\]"):
            settings.snooze_duration_min = 0

    def test_snooze_duration_setter_rejects_negative(self, settings: Settings) -> None:
        """Setting snooze duration to a negative value raises ``ValueError``."""
        with pytest.raises(ValueError, match=r"\[1, 30\]"):
            settings.snooze_duration_min = -5

    def test_snooze_duration_setter_rejects_above_30(self, settings: Settings) -> None:
        """Setting snooze duration above 30 raises ``ValueError`` (FR-010 upper bound)."""
        with pytest.raises(ValueError, match=r"\[1, 30\]"):
            settings.snooze_duration_min = 31

    def test_snooze_duration_setter_accepts_boundary_values(self, settings: Settings) -> None:
        """Boundary values 1 and 30 round-trip through the setter."""
        settings.snooze_duration_min = 1
        assert settings.snooze_duration_min == 1
        settings.snooze_duration_min = 30
        assert settings.snooze_duration_min == 30

    def test_snooze_duration_getter_clamps_corrupt_high_value(self, settings: Settings) -> None:
        """A hand-edited above-range INI value is clamped to 30."""
        settings._qs.setValue(_Keys.SNOOZE_DURATION_MIN, 9999)
        settings._qs.sync()
        assert settings.snooze_duration_min == 30

    def test_snooze_duration_getter_clamps_corrupt_low_value(self, settings: Settings) -> None:
        """A hand-edited below-range INI value is clamped to 1."""
        settings._qs.setValue(_Keys.SNOOZE_DURATION_MIN, -50)
        settings._qs.sync()
        assert settings.snooze_duration_min == 1

    def test_max_snoozes_setter_rejects_negative(self, settings: Settings) -> None:
        """Setting max_snoozes to a negative value raises ``ValueError`` (FR-010 lower bound)."""
        with pytest.raises(ValueError, match=r"\[0, 5\]"):
            settings.max_snoozes = -1

    def test_max_snoozes_setter_rejects_above_5(self, settings: Settings) -> None:
        """Setting max_snoozes above 5 raises ``ValueError`` (FR-010 upper bound)."""
        with pytest.raises(ValueError, match=r"\[0, 5\]"):
            settings.max_snoozes = 6

    def test_max_snoozes_setter_accepts_boundary_values(self, settings: Settings) -> None:
        """Boundary values 0 and 5 round-trip through the setter (zero is intentional)."""
        # Zero is the load-bearing case — it's the user-disables-snoozing
        # state. The existing scheduler/break-dialog already handle the
        # ``snooze_remaining = 0`` path; this assertion pins the setter's
        # acceptance contract so a future tightening to ``[1, 5]`` is
        # caught here rather than discovered by a confused user.
        settings.max_snoozes = 0
        assert settings.max_snoozes == 0
        settings.max_snoozes = 5
        assert settings.max_snoozes == 5

    def test_max_snoozes_getter_clamps_corrupt_high_value(self, settings: Settings) -> None:
        """A hand-edited above-range INI value is clamped to 5."""
        settings._qs.setValue(_Keys.MAX_SNOOZES, 99)
        settings._qs.sync()
        assert settings.max_snoozes == 5

    def test_max_snoozes_getter_clamps_corrupt_low_value(self, settings: Settings) -> None:
        """A hand-edited below-range INI value is clamped to 0."""
        # Mirrors ``test_snooze_duration_getter_clamps_corrupt_low_value``.
        # The low end is 0 (zero is intentionally valid), so anything
        # negative must clamp up to 0 rather than crash or honor the
        # bad value.
        settings._qs.setValue(_Keys.MAX_SNOOZES, -10)
        settings._qs.sync()
        assert settings.max_snoozes == 0

    def test_snooze_duration_getter_falls_back_when_unparseable(self, settings: Settings) -> None:
        """Non-integer strings on snooze_duration_min fall back to the default."""
        # Mirrors ``TestValidation.test_getter_falls_back_when_value_unparseable``.
        # QSettings stores everything as strings under IniFormat; the
        # shared ``_get_int`` helper must catch the parse failure and
        # return the default rather than raising into user code.
        settings._qs.setValue(_Keys.SNOOZE_DURATION_MIN, "not-a-number")
        settings._qs.sync()
        assert settings.snooze_duration_min == DEFAULT_SNOOZE_DURATION_MIN

    def test_max_snoozes_getter_falls_back_when_unparseable(self, settings: Settings) -> None:
        """Non-integer strings on max_snoozes fall back to the default."""
        settings._qs.setValue(_Keys.MAX_SNOOZES, "not-a-number")
        settings._qs.sync()
        assert settings.max_snoozes == DEFAULT_MAX_SNOOZES


class TestAutostartSetterRoundTrip:
    """FR-003: ``autostart`` setter round-trip.

    Mirrors ``TestVoiceSettersRoundTrip`` for the bool side of FR-007 —
    pins setter writes, getter reads, and cross-instance persistence
    for the autostart opt-in flag. The setter is intentionally
    unconditional (no ``ValueError`` branch) and coerces via
    ``bool(value)`` for symmetry with ``voice_enabled.setter`` and
    ``paused.setter``. The matching Windows-side side-effect (the
    per-user Run-key write) lives in
    ``break_reminder/ui/settings_dialog.py`` and is covered by
    ``tests/test_settings_dialog.py``.
    """

    def test_setter_persists_true_round_trip(self, settings: Settings) -> None:
        """Setting ``autostart`` to True is observable via the getter."""
        settings.autostart = True
        assert settings.autostart is True

    def test_setter_persists_false_round_trip(self, settings: Settings) -> None:
        """Setting ``autostart`` to False is observable via the getter."""
        # Pre-set to True so the False write is observable as a state change.
        settings.autostart = True
        settings.autostart = False
        assert settings.autostart is False

    def test_autostart_persists_across_instances(self, ini_path: Path) -> None:
        """An ``autostart`` write is observable from a freshly constructed instance."""
        first = Settings(ini_path=ini_path)
        first.autostart = True
        first._qs.sync()
        del first

        second = Settings(ini_path=ini_path)
        assert second.autostart is True

    def test_setter_coerces_truthy_input(self, settings: Settings) -> None:
        """Non-bool truthy inputs round-trip as the canonical ``True`` bool.

        Mirrors ``voice_enabled.setter``'s ``bool(value)`` coercion. A
        future caller that hands the setter ``1`` or another truthy
        non-bool gets the canonical ``True`` back through the getter,
        not a string-coerced reflection of whatever they wrote.
        """
        settings.autostart = 1  # type: ignore[assignment]
        assert settings.autostart is True

    def test_setter_coerces_falsy_input(self, settings: Settings) -> None:
        """Non-bool falsy inputs round-trip as the canonical ``False`` bool."""
        # Pre-set True so absence of the False write is observable.
        settings.autostart = True
        settings.autostart = 0  # type: ignore[assignment]
        assert settings.autostart is False


class TestPausedLifecycle:
    """FR-016: paused state persists until explicit resume OR reboot."""

    def test_clear_paused_on_reboot_resets_paused(self, ini_path: Path) -> None:
        """``clear_paused_on_reboot()`` flips an in-memory ``paused`` back to False."""
        s = Settings(ini_path=ini_path)
        s.paused = True
        assert s.paused is True

        # The reboot path: app.main calls clear_paused_on_reboot at startup.
        s.clear_paused_on_reboot()
        assert s.paused is False

    def test_clear_paused_on_reboot_persists_to_disk(self, ini_path: Path) -> None:
        """``clear_paused_on_reboot()`` is observable from a fresh process (FR-016)."""
        first = Settings(ini_path=ini_path)
        first.paused = True
        first.clear_paused_on_reboot()
        del first

        second = Settings(ini_path=ini_path)
        assert second.paused is False

    def test_paused_setter_round_trip(self, settings: Settings) -> None:
        """Setting ``paused`` to True/False round-trips via the getter."""
        settings.paused = True
        assert settings.paused is True
        settings.paused = False
        assert settings.paused is False


class TestBoolCoercion:
    """Boolean-string coercion of INI values written by QSettings IniFormat.

    The getter must coerce both true-like and false-like spellings into
    Python booleans, not return raw strings.
    """

    @pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on"])
    def test_truthy_strings_read_as_true(self, settings: Settings, raw: str) -> None:
        """All truthy spellings (``true``/``1``/``yes``/``on``, any case) read as True."""
        settings._qs.setValue(_Keys.VOICE_ENABLED, raw)
        settings._qs.sync()
        assert settings.voice_enabled is True

    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off", "garbage"])
    def test_non_truthy_strings_read_as_false(self, settings: Settings, raw: str) -> None:
        """Anything not in the truthy set (incl. garbage) reads as False."""
        settings._qs.setValue(_Keys.VOICE_ENABLED, raw)
        settings._qs.sync()
        assert settings.voice_enabled is False


class TestSnapshot:
    """``snapshot()`` returns a frozen view of every public setting."""

    def test_snapshot_reflects_current_values(self, settings: Settings) -> None:
        """A snapshot captures setters applied before ``snapshot()`` is called."""
        settings.break_interval_min = 30
        snap = settings.snapshot()
        assert snap.break_interval_min == 30
        assert snap.idle_threshold_sec == DEFAULT_IDLE_THRESHOLD_SEC
        assert snap.voice_enabled is False

    def test_snapshot_is_frozen(self, settings: Settings) -> None:
        """A snapshot is a frozen dataclass — assigning to a field raises."""
        snap = settings.snapshot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.break_interval_min = 999  # type: ignore[misc]

    def test_snapshot_does_not_drift_when_settings_change(self, settings: Settings) -> None:
        """A snapshot is value-stable: later setter calls do not mutate it."""
        snap = settings.snapshot()
        original = snap.break_interval_min
        settings.break_interval_min = 120
        # The previously-taken snapshot must be a stable copy.
        assert snap.break_interval_min == original


class TestSettingsIdleThresholdHandEdits:
    """Pin ``idle_threshold_sec`` hand-edit robustness (R-5, research.md §B.4 #1).

    ``idle_threshold_sec`` is the only int Settings key that escaped the
    S-01 "clamp triple" pattern: the getter has a lower clamp
    (``max(1, _get_int(...))`` at ``storage/settings.py:164``) but
    **no upper clamp** and **no setter at all**. A hand-edited
    ``BreakReminder.ini`` containing ``idle_threshold_sec = 999999``
    propagates straight into the FR-008 active-time accounting loop.

    Per /10x-plan Q2 = ``all_pin`` the surface is pinned (not fixed) in
    this phase — picking an upper-bound value is a product decision that
    belongs to its own change. These tests document today's behavior so
    any future tightening (adding an upper clamp constant, adding a
    setter, switching to a "clamp triple") trips visibly.
    """

    def test_getter_accepts_arbitrarily_high_value(self, settings: Settings) -> None:
        """Hand-edited ``999999`` propagates unchanged through the getter — no upper clamp today."""
        settings._qs.setValue(_Keys.IDLE_THRESHOLD_SEC, 999999)
        settings._qs.sync()
        assert settings.idle_threshold_sec == 999999

    def test_getter_clamps_zero_to_one(self, settings: Settings) -> None:
        """Hand-edited ``0`` clamps up to ``1`` via the lower-only clamp."""
        settings._qs.setValue(_Keys.IDLE_THRESHOLD_SEC, 0)
        settings._qs.sync()
        assert settings.idle_threshold_sec == 1

    def test_getter_clamps_negative_to_one(self, settings: Settings) -> None:
        """Hand-edited negative value clamps up to ``1`` via the lower-only clamp."""
        settings._qs.setValue(_Keys.IDLE_THRESHOLD_SEC, -50)
        settings._qs.sync()
        assert settings.idle_threshold_sec == 1

    def test_getter_falls_back_when_value_unparseable(self, settings: Settings) -> None:
        """A non-integer string falls back to ``DEFAULT_IDLE_THRESHOLD_SEC``.

        ``_get_int``'s ``ValueError → default`` branch is exercised here
        for the only int key whose other coverage in this file doesn't
        already pin the same behavior (break-interval, snooze-duration,
        max-snoozes all have their own equivalent tests).
        """
        settings._qs.setValue(_Keys.IDLE_THRESHOLD_SEC, "not-a-number")
        settings._qs.sync()
        assert settings.idle_threshold_sec == DEFAULT_IDLE_THRESHOLD_SEC

    def test_no_setter_exists(self, settings: Settings) -> None:
        """``Settings.idle_threshold_sec`` has no setter — assigning raises ``AttributeError``.

        The other three int keys (break_interval_min, snooze_duration_min,
        max_snoozes) all have validating setters that enforce their range.
        ``idle_threshold_sec`` is asymmetric — there's no setter at all.
        Pin this so a future "add a setter" change has to consciously
        update this assertion.
        """
        # ``match`` pins the failure to the no-setter branch
        # ("property '...' of 'Settings' object has no setter") rather
        # than any other AttributeError that might escape Settings.
        with pytest.raises(AttributeError, match="no setter"):
            settings.idle_threshold_sec = 30  # type: ignore[misc]


class TestSettingsVoicePhraseRawSetter:
    """Pin ``voice_phrase.setter`` raw-write behavior (R-5, research.md §B.4 #2).

    The setter at ``storage/settings.py:247-272`` is the only post-S-04
    raw/unchecked boundary in this module — it writes ``phrase`` straight
    through with no ``str(...)`` coercion. The docstring at
    ``storage/settings.py:260-266`` explicitly documents this as
    intentional ("the on-disk representation may surprise you").

    Per /10x-plan Q2 = ``all_pin`` the surface is pinned (not fixed)
    in this phase. The matching getter (`_get_str`) coerces via
    ``str(value)`` so a non-string write doesn't crash the next read;
    these tests pin both directions.

    Note: custom-phrase round-trip is already covered by
    ``TestVoiceSettersRoundTrip`` — this class focuses on the raw-write
    contract specifically (non-str pass-through + empty-string accepted
    at the persistence layer).
    """

    def test_setter_writes_non_str_raw_without_coercion(self, settings: Settings) -> None:
        """The setter persists ``42`` as an ``int`` — no ``str(...)`` at the write boundary.

        Pins the raw-write half of the contract documented at
        ``storage/settings.py:260-266``. Without this, a future
        regression that adds ``str(phrase)`` to the setter would only
        be caught indirectly through downstream behavior changes — and
        ``test_non_str_setter_round_trips_via_get_str_coercion`` would
        keep passing (because the value still reads back as ``"42"``
        either way: via setter-side coercion OR via ``_get_str``).
        Probing ``_qs.value`` directly is the only place we can
        observe the setter's coercion vs. raw-write decision.
        """
        settings.voice_phrase = 42  # type: ignore[assignment]
        raw = settings._qs.value(_Keys.VOICE_PHRASE)
        # If the setter had coerced via ``str(42)``, ``raw`` would be
        # ``"42"`` (a str). The ``not isinstance(raw, str)`` check is
        # what pins the no-coercion contract — ``raw == 42`` alone is
        # satisfied by both the int and str shapes.
        assert raw == 42
        assert not isinstance(raw, str)

    def test_non_str_setter_round_trips_via_get_str_coercion(self, settings: Settings) -> None:
        """An int written via the setter reads back as its ``str(...)`` representation.

        Pins the load-bearing contract documented at
        ``storage/settings.py:260-266``: the setter is raw, but the
        getter coerces, so the round-trip surface is safe (just not
        identity-preserving).
        """
        settings.voice_phrase = 42  # type: ignore[assignment]
        settings._qs.sync()
        # The getter coerces via str(value); QSettings IniFormat also
        # round-trips through strings, so both layers conspire to land
        # the read at "42".
        assert settings.voice_phrase == "42"

    def test_setter_accepts_empty_string(self, settings: Settings) -> None:
        """An empty phrase round-trips raw — the persistence layer does not gate it.

        Plan Phase 1 #2 ``TestSettingsVoicePhraseRawSetter`` contract
        item (b). The dialog
        (``break_reminder.ui.settings_dialog.SettingsDialog``) enforces
        the non-empty contract at the UI layer when ``voice_enabled``
        is true; the storage setter is intentionally permissive so
        direct callers (test helpers, future "reset to defaults" path)
        own whatever string they write. Same persisted-empty-string
        contract is also pinned from the round-trip angle by
        ``TestVoiceSettersRoundTrip.test_voice_phrase_setter_accepts_empty_string``;
        duplicating it here groups it with the raw-write surface so
        the raw-setter cluster reads end-to-end without a cross-file
        hop.
        """
        settings.voice_phrase = ""
        assert settings.voice_phrase == ""


class TestSettingsBoolCoercionSymmetry:
    """Mirror ``TestBoolCoercion`` against ``AUTOSTART`` and ``PAUSED`` (R-5, research.md §B.4 #4).

    ``TestBoolCoercion`` above pins the ``_get_bool`` matrix only against
    ``_Keys.VOICE_ENABLED``. ``AUTOSTART`` and ``PAUSED`` both flow
    through the same ``_get_bool`` helper, so the runtime behavior is
    identical in principle — but no test asserts that per-key. A future
    refactor that splits boolean coercion per key would silently regress
    one of them without tripping a test.

    These four parametrized methods close the symmetry gap. Same input
    matrix as ``TestBoolCoercion`` (truthy spellings + non-truthy / garbage),
    asserted against each of the two keys.
    """

    @pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on"])
    def test_autostart_truthy_strings_read_as_true(self, settings: Settings, raw: str) -> None:
        """All truthy spellings on the AUTOSTART key coerce to ``True`` via ``_get_bool``."""
        settings._qs.setValue(_Keys.AUTOSTART, raw)
        settings._qs.sync()
        assert settings.autostart is True

    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off", "garbage"])
    def test_autostart_non_truthy_strings_read_as_false(self, settings: Settings, raw: str) -> None:
        """Anything not in the truthy set (incl. garbage) on AUTOSTART reads as ``False``."""
        settings._qs.setValue(_Keys.AUTOSTART, raw)
        settings._qs.sync()
        assert settings.autostart is False

    @pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on"])
    def test_paused_truthy_strings_read_as_true(self, settings: Settings, raw: str) -> None:
        """All truthy spellings on the PAUSED key coerce to ``True`` via ``_get_bool``."""
        settings._qs.setValue(_Keys.PAUSED, raw)
        settings._qs.sync()
        assert settings.paused is True

    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off", "garbage"])
    def test_paused_non_truthy_strings_read_as_false(self, settings: Settings, raw: str) -> None:
        """Anything not in the truthy set (incl. garbage) on PAUSED reads as ``False``."""
        settings._qs.setValue(_Keys.PAUSED, raw)
        settings._qs.sync()
        assert settings.paused is False


class TestSettingsUnknownKey:
    """Pin unknown-INI-key silently-ignored behavior (R-5, research.md §B.4 #3).

    A hand-edited or forward-compat ``BreakReminder.ini`` containing a
    key Settings doesn't know about (e.g.,
    ``scheduling/unknown_future_setting = foo``) loads cleanly today —
    every getter only reads the keys it knows; the unknown key is
    neither honored nor rejected.

    This is the **correct** forward-compat shape for an INI written by
    a newer build and read by an older build. Per /10x-plan Q2 =
    ``all_pin`` the behavior is pinned, not changed. A future tightening
    ("raise on unknown key" validation) would have to consciously
    update these assertions rather than silently slipping in.
    """

    def test_unknown_key_does_not_break_known_getters(self, settings: Settings) -> None:
        """An unknown INI key leaves every documented getter at its default."""
        settings._qs.setValue("scheduling/unknown_future_setting", "future-value")
        settings._qs.sync()
        # All 8 documented keys still return their defaults — no crash, no
        # cross-talk from the unknown key.
        assert settings.break_interval_min == DEFAULT_BREAK_INTERVAL_MIN
        assert settings.idle_threshold_sec == DEFAULT_IDLE_THRESHOLD_SEC
        assert settings.snooze_duration_min == DEFAULT_SNOOZE_DURATION_MIN
        assert settings.max_snoozes == DEFAULT_MAX_SNOOZES
        assert settings.voice_enabled == DEFAULT_VOICE_ENABLED
        assert settings.voice_phrase == DEFAULT_VOICE_PHRASE
        assert settings.autostart == DEFAULT_AUTOSTART
        assert settings.paused is False

    def test_unknown_key_persists_in_ini_file_across_instances(self, ini_path: Path) -> None:
        """We don't strip unknown keys on read — a hand-edited key survives instance teardown.

        Tripwire for a future "purge unknown keys" change: if Settings
        ever starts pruning the on-disk INI to known keys only, this
        test fails — forcing the change to be explicit.
        """
        first = Settings(ini_path=ini_path)
        first._qs.setValue("scheduling/unknown_future_setting", "future-value")
        # Touch a known key so the INI is actually flushed to disk.
        first.break_interval_min = 45
        first._qs.sync()
        del first

        second = Settings(ini_path=ini_path)
        assert second._qs.value("scheduling/unknown_future_setting") == "future-value"
