"""Append-only CSV event log (FR-015).

One event per row; columns: ``timestamp_iso, event_type, outcome, detail``.
Rotates when the file passes ``MAX_BYTES`` (1 MB) by renaming the existing
file to ``events.log.1`` (overwriting any previous rotation). One level of
rotation is enough — the PRD doesn't require long-term retention; the FR
exists so a user can sanity-check "did the thing fire?" via Notepad.

The format is deliberately Notepad-and-Excel friendly: comma-separated, ISO
timestamps, no quoting unless a field contains a comma. This satisfies
FR-015's "human-readable enough to inspect with Notepad or open in Excel".
"""

from __future__ import annotations

import csv
import threading
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from break_reminder.storage.paths import event_log_path

MAX_BYTES = 1 * 1024 * 1024  # 1 MB
HEADER = ("timestamp_iso", "event_type", "outcome", "detail")


class EventType(StrEnum):
    """The two event categories the FR-015 log records."""

    BREAK = "break"
    REMINDER = "reminder"


class Outcome(StrEnum):
    """How an event terminated, paired with ``EventType`` in each row."""

    TAKEN = "taken"
    SNOOZED = "snoozed"
    MISSED = "missed"  # break notification cleared by no deliberate action
    FIRED = "fired"  # custom reminder fired (no taken/missed concept)


class EventLog:
    """Thread-safe append-only CSV writer."""

    def __init__(self, path: Path | None = None) -> None:
        r"""Open (or create) the CSV at ``path`` and ensure the header row exists.

        Args:
            path: Optional override for the log location. Defaults to the
                standard ``%APPDATA%\BreakReminder\events.log``.
        """
        self._path = path or event_log_path()
        self._lock = threading.Lock()
        self._ensure_header()

    @property
    def path(self) -> Path:
        """Path to the active (non-rotated) CSV file."""
        return self._path

    def record(self, event_type: EventType, outcome: Outcome, detail: str = "") -> None:
        """Append one row. Safe to call from any thread."""
        row = (
            datetime.now(UTC).isoformat(timespec="seconds"),
            str(event_type),
            str(outcome),
            detail,
        )
        with self._lock:
            self._rotate_if_needed()
            with self._path.open("a", encoding="utf-8", newline="") as fp:
                csv.writer(fp).writerow(row)

    def _ensure_header(self) -> None:
        with self._lock:
            if not self._path.exists() or self._path.stat().st_size == 0:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("w", encoding="utf-8", newline="") as fp:
                    csv.writer(fp).writerow(HEADER)

    def _rotate_if_needed(self) -> None:
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return
        if size < MAX_BYTES:
            return
        backup = self._path.with_suffix(self._path.suffix + ".1")
        if backup.exists():
            backup.unlink()
        self._path.rename(backup)
        with self._path.open("w", encoding="utf-8", newline="") as fp:
            csv.writer(fp).writerow(HEADER)
