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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tzlocal

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


class InvalidTimezoneError(ValueError):
    """Raised by ``_coerce_tz`` when a hand-edited tz value cannot be resolved.

    Subclass of ``ValueError`` so ``ReminderStore._read``'s existing
    ``(KeyError, ValueError, TypeError)`` exception tuple catches it
    without modification — the row-containment guarantee in the module
    docstring extends seamlessly to the tz failure mode. Plan-review F3
    chose loud-drop over silent-fallback so a typo'd Warsaw doesn't
    silently become OS-local Tokyo and fire at the wrong wall-clock.
    """


def _coerce_tz(raw: object) -> str:
    """Coerce a hand-editable JSON ``tz`` field into a valid IANA name.

    Mirrors the ``_coerce_lead_minutes`` / ``_coerce_aware_utc``
    storage-boundary pattern. Per plan-review F3, the helper
    distinguishes two failure modes:

    * **Missing field** (``raw is None``) — older ``reminders.json`` files
      predating R-1b lack the key entirely. Legitimate lazy-migration
      case: substitute OS-local silently via
      ``tzlocal.get_localzone_name()``. Pre-fix files keep loading.
    * **Invalid value** (typo'd IANA name, empty string, path traversal,
      wrong type) — the user explicitly typed something that doesn't
      resolve. Raise ``InvalidTimezoneError`` so ``_read``'s
      row-containment drops the whole row with a WARNING (lessons.md
      storage-boundary rule, row-level guard). Silent fallback to
      OS-local on a typo would mask the error and fire at the wrong
      wall-clock for days; the loud-drop is preferable.

    Plan-review F1 surfaced that ``zoneinfo.ZoneInfo("")`` and
    ``ZoneInfo("../etc/passwd")`` raise ``ValueError`` (not
    ``ZoneInfoNotFoundError``) — zoneinfo validates path normalization
    independently of zone existence. Both exception classes must be
    caught in the ``str`` branch.

    Args:
        raw: The value pulled from ``data.get("tz")``. ``None`` when the
            key is missing on disk; otherwise whatever the hand-edit
            produced (string, int, list — input is effectively ``object``).

    Returns:
        A valid IANA timezone name. ``"UTC"`` if ``tzlocal`` itself
        fails on the missing-field path (rare on Windows 11; paranoid
        last-resort fallback).

    Raises:
        InvalidTimezoneError: When ``raw`` is a non-``None`` value that
            doesn't resolve to a ``ZoneInfo``. Caught by ``_read`` at
            the row level via the existing
            ``(KeyError, ValueError, TypeError)`` tuple.
    """
    if raw is None:
        try:
            name = tzlocal.get_localzone_name()
        except ZoneInfoNotFoundError:
            return "UTC"
        return name or "UTC"
    if isinstance(raw, str):
        try:
            ZoneInfo(raw)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise InvalidTimezoneError(f"reminder tz {raw!r} is not a valid IANA name") from exc
        return raw
    raise InvalidTimezoneError(f"reminder tz field has unexpected type {type(raw).__name__}")


@dataclass
class Reminder:
    """A user-created custom reminder (FR-011).

    Invariants:

    * ``start_at`` and ``end_at`` (when set) are always **tz-aware UTC**
      ``datetime`` instances. Every constructing code path —
      ``ReminderFormDialog.accept``, the scheduler's recurrence math,
      and the storage layer's ``from_dict`` — produces tz-aware UTC
      values. Downstream consumers (especially the Edit-mode past-time
      skip predicate in ``ReminderFormDialog``) rely on this so that
      ``start_at_utc == self._editing.start_at`` is a valid comparison
      rather than a ``TypeError`` source. Hand-edits to
      ``reminders.json`` that drop the ``+00:00`` suffix are normalized
      back to UTC-aware via ``_coerce_aware_utc`` at load time.
    * ``tz`` is the IANA timezone name used by ``scheduler.next_firing_after``
      to localize ``start_at`` before handing it to ``dateutil.rrulestr``.
      RRULE's DST handling activates only when ``dtstart`` carries a
      named zone (R-1b fix). Together, ``start_at`` (UTC instant) and
      ``tz`` (named zone) preserve the user's wall-clock intent across
      DST transitions: a "9:00 Warsaw daily" reminder stays at 9:00
      Warsaw on both sides of the spring-forward.
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
    # R-1b: IANA timezone name to localize ``start_at`` to before RRULE
    # math. Default-factory routes through ``_coerce_tz(None)`` so the
    # 55+ existing call sites that don't pass ``tz=`` get OS-local for
    # free — single source of truth for "what is OS-local?".
    tz: str = field(default_factory=lambda: _coerce_tz(None))
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
                values are coerced by ``_coerce_lead_minutes``), optional
                ``tz`` (IANA name, defaults to OS-local via ``_coerce_tz`` —
                pre-R-1b files lack the key entirely; invalid values
                raise ``InvalidTimezoneError`` which ``_read`` catches
                at the row level to drop the bad row).

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
            tz=_coerce_tz(data.get("tz")),
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
