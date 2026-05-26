r"""Typed wrapper around ``QSettings`` (INI format).

Stores user preferences (FR-002, FR-003, FR-006, FR-010, FR-016) as a single
``BreakReminder.ini`` file under ``%APPDATA%\BreakReminder`` so the file is
inspectable in Notepad / Excel — same human-readable principle as the
event log.

All Open-Question defaults (PRD §Open Questions) are surfaced as constants
here so flipping a default doesn't require touching the rest of the code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

from break_reminder.storage.paths import settings_ini_path

# --- Bounds (FR-006 / FR-010) ---------------------------------------------

# Inclusive range for the break interval in minutes. Single source of truth
# for the persistence layer's clamp/validation (see ``break_interval_min``
# below) and the UI layer's spinbox bounds (see
# ``break_reminder/ui/settings_dialog.py``). Loosening the range requires
# changing only this pair plus the matching FR-006 wording in the PRD.
BREAK_INTERVAL_MIN_MINUTES = 1
BREAK_INTERVAL_MAX_MINUTES = 240

# FR-010 snooze-duration range. Same single-source-of-truth pattern as the
# break-interval pair above; consumed by the ``snooze_duration_min``
# getter/setter and the matching ``QSpinBox`` bounds in
# ``break_reminder/ui/settings_dialog.py``.
SNOOZE_DURATION_MIN_MINUTES = 1
SNOOZE_DURATION_MAX_MINUTES = 30

# FR-010 max-snoozes-per-cycle range. Lower bound 0 is intentional — the
# user can disable snoozing entirely; the existing scheduler/dialog already
# handle ``snooze_remaining = 0`` by hiding the snooze button.
MAX_SNOOZES_MIN = 0
MAX_SNOOZES_MAX = 5

# --- Defaults -------------------------------------------------------------

DEFAULT_BREAK_INTERVAL_MIN = 60  # FR-006 default; user-configurable 1–240
DEFAULT_IDLE_THRESHOLD_SEC = 60  # PRD Open Question #2
DEFAULT_SNOOZE_DURATION_MIN = 5  # PRD Open Question #1
DEFAULT_MAX_SNOOZES = 1  # FR-010 default; configurable 0–5
DEFAULT_VOICE_ENABLED = False  # FR-007: voice is opt-in
DEFAULT_VOICE_PHRASE = "Time to take a break"  # PRD Open Question #3
DEFAULT_AUTOSTART = False  # FR-003: autostart opt-in


# --- Keys -----------------------------------------------------------------


class _Keys:
    BREAK_INTERVAL_MIN = "scheduling/break_interval_min"
    IDLE_THRESHOLD_SEC = "scheduling/idle_threshold_sec"
    SNOOZE_DURATION_MIN = "scheduling/snooze_duration_min"
    MAX_SNOOZES = "scheduling/max_snoozes"
    VOICE_ENABLED = "notifications/voice_enabled"
    VOICE_PHRASE = "notifications/voice_phrase"
    AUTOSTART = "lifecycle/autostart"
    PAUSED = "lifecycle/paused"  # FR-016: pause/resume; cleared on reboot


@dataclass(frozen=True)
class Snapshot:
    """Immutable snapshot of all settings at one point in time."""

    break_interval_min: int
    idle_threshold_sec: int
    snooze_duration_min: int
    max_snoozes: int
    voice_enabled: bool
    voice_phrase: str
    autostart: bool


class Settings:
    r"""Read/write app preferences via ``QSettings`` in INI format.

    The default-constructed instance writes to ``%APPDATA%\BreakReminder\BreakReminder.ini``.
    Tests (and any future code that needs a sandboxed location) can pass an
    explicit ``ini_path`` to point at a different file. Same injection
    pattern as ``EventLog`` and ``ReminderStore``.
    """

    def __init__(self, ini_path: Path | str | None = None) -> None:
        r"""Open the INI at ``ini_path`` (or the standard per-user location).

        Args:
            ini_path: Optional override for the INI location. Defaults to
                ``%APPDATA%\BreakReminder\BreakReminder.ini``.
        """
        resolved = str(ini_path) if ini_path is not None else str(settings_ini_path())
        self._qs = QSettings(resolved, QSettings.Format.IniFormat)

    # ---- generic helpers -------------------------------------------------

    def _get_int(self, key: str, default: int) -> int:
        # QSettings.value() returns ``object`` per its stubs because INI
        # round-trips everything through strings, but the in-memory cache
        # may hand back the original int when set in the same session.
        # Both shapes are valid inputs to int(); anything else is treated
        # as missing/corrupt and falls back to the default.
        value = self._qs.value(key, default)
        if isinstance(value, (int, str)):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    def _get_bool(self, key: str, default: bool) -> bool:
        value = self._qs.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def _get_str(self, key: str, default: str) -> str:
        value = self._qs.value(key, default)
        return str(value) if value is not None else default

    # ---- typed properties -----------------------------------------------

    @property
    def break_interval_min(self) -> int:
        """Configured break-interval in minutes, clamped to FR-006's range."""
        raw = self._get_int(_Keys.BREAK_INTERVAL_MIN, DEFAULT_BREAK_INTERVAL_MIN)
        return max(BREAK_INTERVAL_MIN_MINUTES, min(BREAK_INTERVAL_MAX_MINUTES, raw))

    @break_interval_min.setter
    def break_interval_min(self, minutes: int) -> None:
        """Persist the FR-006 break-interval after enforcing its range.

        Unlike the bool / string setters in this class, this one validates
        on write rather than coercing. The dialog's ``QSpinBox`` already
        clamps user input visually, but a direct caller (test helper, future
        CLI flag, default-reset path) gets a clear ``ValueError`` instead of
        a silently truncated value.

        Args:
            minutes: Break interval in minutes. Must satisfy
                ``BREAK_INTERVAL_MIN_MINUTES <= minutes <= BREAK_INTERVAL_MAX_MINUTES``.

        Raises:
            ValueError: If ``minutes`` is outside the FR-006 range.
        """
        if not BREAK_INTERVAL_MIN_MINUTES <= minutes <= BREAK_INTERVAL_MAX_MINUTES:
            raise ValueError(
                f"break_interval_min must be in "
                f"[{BREAK_INTERVAL_MIN_MINUTES}, {BREAK_INTERVAL_MAX_MINUTES}] (FR-006)"
            )
        self._qs.setValue(_Keys.BREAK_INTERVAL_MIN, minutes)

    @property
    def idle_threshold_sec(self) -> int:
        """Idle threshold (seconds) above which active-time stops accumulating (FR-008)."""
        return max(1, self._get_int(_Keys.IDLE_THRESHOLD_SEC, DEFAULT_IDLE_THRESHOLD_SEC))

    @property
    def snooze_duration_min(self) -> int:
        """How long a snooze defers the next break popup (FR-010)."""
        raw = self._get_int(_Keys.SNOOZE_DURATION_MIN, DEFAULT_SNOOZE_DURATION_MIN)
        return max(SNOOZE_DURATION_MIN_MINUTES, min(SNOOZE_DURATION_MAX_MINUTES, raw))

    @snooze_duration_min.setter
    def snooze_duration_min(self, minutes: int) -> None:
        """Persist the FR-010 snooze duration after enforcing its range.

        Same tight-validation contract as ``break_interval_min.setter`` —
        the dialog's ``QSpinBox`` clamps user input visually so the
        ``ValueError`` branch is unreachable from the GUI; a direct
        caller (test helper, future CLI flag, default-reset path) gets
        a clear error instead of a silently truncated value.

        Args:
            minutes: Snooze duration in minutes. Must satisfy
                ``SNOOZE_DURATION_MIN_MINUTES <= minutes <= SNOOZE_DURATION_MAX_MINUTES``.

        Raises:
            ValueError: If ``minutes`` is outside the FR-010 range.
        """
        if not SNOOZE_DURATION_MIN_MINUTES <= minutes <= SNOOZE_DURATION_MAX_MINUTES:
            raise ValueError(
                f"snooze_duration_min must be in "
                f"[{SNOOZE_DURATION_MIN_MINUTES}, {SNOOZE_DURATION_MAX_MINUTES}] (FR-010)"
            )
        self._qs.setValue(_Keys.SNOOZE_DURATION_MIN, minutes)

    @property
    def max_snoozes(self) -> int:
        """Maximum snoozes per cycle, clamped to FR-010's [0, 5]."""
        raw = self._get_int(_Keys.MAX_SNOOZES, DEFAULT_MAX_SNOOZES)
        return max(MAX_SNOOZES_MIN, min(MAX_SNOOZES_MAX, raw))

    @max_snoozes.setter
    def max_snoozes(self, value: int) -> None:
        """Persist the FR-010 max-snoozes-per-cycle cap after enforcing its range.

        Zero is a valid input — the user can disable snoozing entirely;
        the existing scheduler emits ``snooze_remaining = 0`` and the
        break dialog hides the snooze button on that path. Same tight-
        validation contract as ``break_interval_min.setter`` and
        ``snooze_duration_min.setter``.

        Args:
            value: Max snoozes per break cycle. Must satisfy
                ``MAX_SNOOZES_MIN <= value <= MAX_SNOOZES_MAX``.

        Raises:
            ValueError: If ``value`` is outside the FR-010 range.
        """
        if not MAX_SNOOZES_MIN <= value <= MAX_SNOOZES_MAX:
            raise ValueError(
                f"max_snoozes must be in [{MAX_SNOOZES_MIN}, {MAX_SNOOZES_MAX}] (FR-010)"
            )
        self._qs.setValue(_Keys.MAX_SNOOZES, value)

    @property
    def voice_enabled(self) -> bool:
        """Whether the voice channel is on (FR-007 — opt-in by default)."""
        return self._get_bool(_Keys.VOICE_ENABLED, DEFAULT_VOICE_ENABLED)

    @voice_enabled.setter
    def voice_enabled(self, value: bool) -> None:
        """Persist the FR-007 voice gate.

        Args:
            value: ``True`` to enable voice notification (popup still
                fires alongside per FR-007), ``False`` to disable.
                Coerced via ``bool(value)`` so a stray int or other
                truthy value writes the canonical bool.
        """
        self._qs.setValue(_Keys.VOICE_ENABLED, bool(value))

    @property
    def voice_phrase(self) -> str:
        """Phrase ``VoiceNotifier`` speaks for break events (FR-007)."""
        return self._get_str(_Keys.VOICE_PHRASE, DEFAULT_VOICE_PHRASE)

    @voice_phrase.setter
    def voice_phrase(self, phrase: str) -> None:
        """Persist the FR-007 voice phrase.

        The setter is intentionally permissive — empty and whitespace-only
        phrases are accepted at the persistence layer. The dialog
        (``break_reminder.ui.settings_dialog.SettingsDialog``) enforces
        the non-empty contract when ``voice_enabled`` is true so the
        confused (``voice_enabled=True, voice_phrase=""``) state cannot
        land via the GUI. Direct callers that bypass the dialog (e.g.,
        a future "reset to defaults" path) own whatever string they
        write here.

        Note: unlike ``voice_enabled.setter`` (which coerces via ``bool(value)``),
        this setter writes ``phrase`` straight through without ``str(...)``
        coercion. Callers are expected to pass a ``str``. The matching getter
        already coerces on read with ``str(value)``, so a non-string write
        won't crash the next read — but the on-disk representation may surprise
        you (e.g., ``Path("…")`` round-trips as ``"."``-relative output, not
        the absolute path you stored). See impl-review F5.

        Args:
            phrase: The phrase ``VoiceNotifier.speak`` will pronounce.
                Must be a ``str``; no coercion is performed at the setter.
        """
        self._qs.setValue(_Keys.VOICE_PHRASE, phrase)

    @property
    def autostart(self) -> bool:
        """Whether the app registers for Windows autostart (FR-003)."""
        return self._get_bool(_Keys.AUTOSTART, DEFAULT_AUTOSTART)

    @property
    def paused(self) -> bool:
        """Pause flag (FR-016). Cleared at every reboot by ``app.main``."""
        return self._get_bool(_Keys.PAUSED, False)

    @paused.setter
    def paused(self, value: bool) -> None:
        """Persist the FR-016 pause flag.

        Paused state survives until either an explicit resume (a setter call
        with ``False``) or the next reboot. Reboot-reset is handled by
        ``app.main`` calling ``clear_paused_on_reboot`` at startup; this
        setter handles only explicit user toggles. Coerced via ``bool(value)``
        for symmetry with the other bool setters in this class.

        Args:
            value: ``True`` to pause break scheduling, ``False`` to resume.
        """
        self._qs.setValue(_Keys.PAUSED, bool(value))

    def clear_paused_on_reboot(self) -> None:
        """Called once at app startup; FR-016 says paused must not survive reboots."""
        self._qs.remove(_Keys.PAUSED)

    def snapshot(self) -> Snapshot:
        """Return an immutable ``Snapshot`` of every setting at this instant.

        Used by the scheduler tick so a single tick reads a consistent set
        of values even if the user is editing settings concurrently.
        """
        return Snapshot(
            break_interval_min=self.break_interval_min,
            idle_threshold_sec=self.idle_threshold_sec,
            snooze_duration_min=self.snooze_duration_min,
            max_snoozes=self.max_snoozes,
            voice_enabled=self.voice_enabled,
            voice_phrase=self.voice_phrase,
            autostart=self.autostart,
        )
