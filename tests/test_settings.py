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
