r"""Custom-reminder model + JSON-backed CRUD (FR-011 / FR-012 / FR-014).

Reminders are stored as a JSON list under ``%APPDATA%\BreakReminder\reminders.json``.
The format is intentionally trivial so users can hand-edit the file if the
in-app UI is broken — same "human-readable" principle that drove the INI
choice for settings and CSV for the event log.

Recurrence (FR-014) is encoded as an iCalendar RRULE string (RFC 5545). This
module persists the string verbatim; computing the next firing is the
scheduler's job (see ``break_reminder.scheduler``). Keeping the parsing out
of the storage layer means an invalid RRULE string never blocks the file
from loading — the scheduler can flag it instead.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from break_reminder.storage.paths import reminders_json_path

# S-06b lead-time bounds enforced on disk read. These deliberately mirror
# ``break_reminder.ui.reminder_form_dialog._LEAD_MIN_VALUE`` /
# ``_LEAD_MAX_VALUE`` — the storage layer can't import the UI layer
# (dependency direction would flip), so the values are duplicated here
# with this cross-reference. A drift between the two surfaces would be
# caught fast by manual smoke (the form's spinbox cap stays at 60 while a
# higher disk value would be clamped down silently on next read).
# FR-015 documents ``reminders.json`` as user-editable; coercing here
# means a hand-edited string / negative value / out-of-range int doesn't
# crash ``ReminderScheduler._fire`` later inside ``timedelta(minutes=...)``.
_LEAD_MIN_VALUE = 0
_LEAD_MAX_VALUE = 60


def _coerce_lead_minutes(raw: object) -> int:
    """Coerce a hand-editable JSON value into the ``[0, 60]`` integer range.

    The storage layer is the only place that sees raw JSON for
    reminders, so input validation lives here rather than at the
    scheduler / form boundaries. Resilient on three axes:

    * **Type**: ``int()`` covers ``int``, ``float``, and numeric
      strings ("15"); anything that doesn't coerce (``None``, "ten",
      a list) returns the default 0.
    * **Lower bound**: negative leads are clamped to 0 — negative
      "minutes before" is nonsensical and would also crash the
      ``timedelta`` subtraction in the form's ``accept()``.
    * **Upper bound**: values above ``_LEAD_MAX_VALUE`` (60) are
      clamped down so a hand-edited entry can't bypass the UI cap.

    Args:
        raw: The value pulled from ``data.get("lead_minutes", 0)``.
            Typically a JSON int, but FR-015 allows hand-edited
            files so the input type is effectively ``object``.

    Returns:
        An integer in ``[_LEAD_MIN_VALUE, _LEAD_MAX_VALUE]``.
    """
    try:
        coerced = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _LEAD_MIN_VALUE
    if coerced < _LEAD_MIN_VALUE:
        return _LEAD_MIN_VALUE
    if coerced > _LEAD_MAX_VALUE:
        return _LEAD_MAX_VALUE
    return coerced


@dataclass
class Reminder:
    """A user-created custom reminder (FR-011)."""

    name: str
    start_at: datetime
    rrule_str: str | None = None  # FR-014: optional iCalendar RRULE
    end_at: datetime | None = None  # FR-014: optional series end
    # S-06b: minutes before the event the popup should fire. ``start_at``
    # remains the firing instant (Model A); ``lead_minutes`` is recorded
    # as round-trip metadata so S-07's Edit dialog can reconstruct the
    # event time as ``start_at + timedelta(minutes=lead_minutes)``.
    # Default 0 keeps every pre-S-06b ``reminders.json`` entry loading
    # with identical firing behavior.
    lead_minutes: int = 0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict; ISO-encodes ``start_at`` / ``end_at``."""
        d = asdict(self)
        d["start_at"] = self.start_at.isoformat()
        d["end_at"] = self.end_at.isoformat() if self.end_at else None
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Reminder:
        """Reconstruct a ``Reminder`` from a dict produced by ``to_dict``.

        Args:
            data: Mapping with ``id``, ``name``, ``start_at`` (ISO 8601),
                optional ``rrule_str``, optional ``end_at`` (ISO 8601),
                optional ``lead_minutes`` (int, defaults to 0 — pre-S-06b
                files lack the key entirely; out-of-range or non-coercible
                values are coerced by ``_coerce_lead_minutes``).

        Returns:
            A populated ``Reminder`` instance.
        """
        return cls(
            id=data["id"],
            name=data["name"],
            start_at=datetime.fromisoformat(data["start_at"]),
            rrule_str=data.get("rrule_str"),
            end_at=datetime.fromisoformat(data["end_at"]) if data.get("end_at") else None,
            lead_minutes=_coerce_lead_minutes(data.get("lead_minutes", 0)),
        )


class ReminderStore:
    """Thread-safe JSON-backed list of reminders."""

    def __init__(self, path: Path | None = None) -> None:
        r"""Bind the store to a JSON file (defaults to the standard per-user path).

        Args:
            path: Optional override for the JSON file location. Defaults
                to ``%APPDATA%\BreakReminder\reminders.json``.
        """
        self._path = path or reminders_json_path()
        self._lock = threading.Lock()

    def list_all(self) -> list[Reminder]:
        """Return every reminder currently in the store."""
        with self._lock:
            return self._read()

    def add(self, reminder: Reminder) -> None:
        """Append ``reminder`` to the store and atomically rewrite the file."""
        with self._lock:
            items = self._read()
            items.append(reminder)
            self._write(items)

    def update(self, reminder: Reminder) -> None:
        """Replace the existing entry with the same ``id`` (no-op if not found)."""
        with self._lock:
            items = [reminder if r.id == reminder.id else r for r in self._read()]
            self._write(items)

    def delete(self, reminder_id: str) -> None:
        """Remove the entry whose ``id`` matches (no-op if not found)."""
        with self._lock:
            items = [r for r in self._read() if r.id != reminder_id]
            self._write(items)

    # ---- private --------------------------------------------------------

    def _read(self) -> list[Reminder]:
        if not self._path.exists():
            return []
        try:
            with self._path.open("r", encoding="utf-8") as fp:
                raw = json.load(fp)
        except (json.JSONDecodeError, OSError):
            # Defensive: a corrupted file shouldn't crash the app on launch.
            # The user will lose the broken file's contents, but the INI
            # settings and event log are unaffected.
            return []
        return [Reminder.from_dict(item) for item in raw]

    def _write(self, items: list[Reminder]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [r.to_dict() for r in items]
        # Atomic write: tmp file + rename. Avoids a half-written JSON file
        # if the app is killed mid-save.
        tmp = self._path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, ensure_ascii=False)
        tmp.replace(self._path)
