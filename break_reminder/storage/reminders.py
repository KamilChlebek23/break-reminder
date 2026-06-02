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

``ReminderStore._read`` is row-resilient on top of the file-level corrupt-JSON
fallback: a single malformed row (missing required key, malformed ISO, wrong
type) is dropped with a ``logger.warning`` naming the row index + exception,
while well-formed siblings continue to load. The file-level guard (corrupt
JSON → ``[]``) and the row-level guard (one bad row → that row dropped) are
independent layers; together they implement FR-015's "Notepad-editable"
stance for the reminders surface.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from break_reminder.storage.paths import reminders_json_path

logger = logging.getLogger(__name__)

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


def _coerce_aware_utc(value: datetime | None) -> datetime | None:
    """Coerce a datetime to tz-aware UTC, treating naive input as UTC.

    The on-disk format always writes ``+00:00`` suffixes (every code
    path constructs tz-aware UTC values before serializing), but FR-015
    documents ``reminders.json`` as user-editable in Notepad. A
    well-intentioned hand-edit that drops the timezone suffix
    (``"2026-06-01T09:00:00"`` instead of ``"...+00:00"``) used to load
    as a tz-naive ``datetime`` and crash downstream comparisons —
    notably the S-07 Edit-mode past-time skip predicate
    (``start_at_utc == self._editing.start_at``) which would raise
    ``TypeError: can't compare offset-naive and offset-aware datetimes``.

    Coercion (rather than rejection) is the chosen response because it
    mirrors the existing ``_coerce_lead_minutes`` self-healing pattern
    — the storage layer treats disk input as potentially-hostile and
    quietly normalizes rather than refusing to load. Naive values are
    assumed to be UTC; that matches what our own code paths produce
    and is the only stable interpretation (we don't know the
    hand-editor's intent).

    Args:
        value: A ``datetime`` from ``datetime.fromisoformat`` (already
            UTC-aware if the input string had a ``+00:00`` suffix;
            tz-naive otherwise) or ``None`` for optional fields like
            ``end_at``.

    Returns:
        ``None`` when ``value`` is ``None``; the same datetime when it
        was already tz-aware; otherwise the datetime with ``tzinfo=UTC``
        attached (interpreting the wall-clock as UTC).
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@dataclass
class Reminder:
    """A user-created custom reminder (FR-011).

    Invariant: ``start_at`` and ``end_at`` (when set) are always
    **tz-aware UTC** ``datetime`` instances. Every constructing code
    path — ``ReminderFormDialog.accept``, the scheduler's recurrence
    math, and the storage layer's ``from_dict`` — produces tz-aware
    UTC values. Downstream consumers (especially the Edit-mode
    past-time skip predicate in ``ReminderFormDialog``) rely on this
    so that ``start_at_utc == self._editing.start_at`` is a valid
    comparison rather than a ``TypeError`` source. Hand-edits to
    ``reminders.json`` that drop the ``+00:00`` suffix are normalized
    back to UTC-aware via ``_coerce_aware_utc`` at load time.
    """

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
        start_at = _coerce_aware_utc(datetime.fromisoformat(data["start_at"]))
        # ``_coerce_aware_utc`` returns ``None`` only for ``None`` input;
        # ``start_at`` is never optional, so narrow the type for callers.
        assert start_at is not None, "start_at must not be None after coercion"
        return cls(
            id=data["id"],
            name=data["name"],
            start_at=start_at,
            rrule_str=data.get("rrule_str"),
            end_at=(
                _coerce_aware_utc(datetime.fromisoformat(data["end_at"]))
                if data.get("end_at")
                else None
            ),
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
        # Row-resilient on three independent layers (see module docstring's
        # "row-resilient" paragraph for the contract): (a) file-level
        # corrupt-JSON → []; (b) non-list top-level → [] + single WARNING;
        # (c) per-row exception → row dropped + WARNING, siblings preserved.
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
        if not isinstance(raw, list):
            # Top-level guard: ``json.load`` accepts any JSON type; iterating
            # a dict yields its keys (strings) and iterating a string yields
            # chars — both would crash inside ``from_dict`` with N spurious
            # per-row warnings. Collapse to a single WARNING + ``[]`` so the
            # log surface stays useful.
            logger.warning(
                "reminders.json top-level is not a list (got %s); ignoring",
                type(raw).__name__,
            )
            return []
        result: list[Reminder] = []
        for index, item in enumerate(raw):
            try:
                result.append(Reminder.from_dict(item))
            except (KeyError, ValueError, TypeError) as exc:
                # FR-015 self-healing: a hand-edit that breaks one row must
                # not nuke the well-formed siblings. Mirrors the field-level
                # ``_coerce_lead_minutes`` / ``_coerce_aware_utc`` precedent
                # at the row level. The exception tuple matches what
                # ``Reminder.from_dict`` can raise: ``KeyError`` (missing
                # required key), ``ValueError`` (malformed ISO from
                # ``datetime.fromisoformat``), ``TypeError`` (non-dict /
                # non-str where one was required).
                logger.warning(
                    "reminders.json row %d is malformed (%s: %s); dropping",
                    index,
                    type(exc).__name__,
                    exc,
                )
        return result

    def _write(self, items: list[Reminder]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [r.to_dict() for r in items]
        # Atomic write: tmp file + rename. Avoids a half-written JSON file
        # if the app is killed mid-save.
        tmp = self._path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, ensure_ascii=False)
        tmp.replace(self._path)
