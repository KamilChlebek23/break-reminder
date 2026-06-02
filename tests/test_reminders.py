"""Round-trip tests for ``break_reminder.storage.reminders``.

Covers FR-011 (add a custom reminder), FR-012 (list / edit / delete), and
FR-014 (recurrence stored as iCalendar RRULE strings, with optional end
dates). The module's defensive corrupt-file-recovery path is exercised
explicitly so a future regression there is caught loudly.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from break_reminder.storage.reminders import (
    _LEAD_MAX_VALUE,
    _LEAD_MIN_VALUE,
    Reminder,
    ReminderStore,
    _coerce_aware_utc,
    _coerce_lead_minutes,
)

UTC = UTC


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Path to a per-test ``reminders.json`` file under ``tmp_path``."""
    return tmp_path / "reminders.json"


@pytest.fixture
def store(store_path: Path) -> ReminderStore:
    """A ``ReminderStore`` instance bound to the per-test ``store_path``."""
    return ReminderStore(store_path)


@pytest.fixture
def valid_reminder_dict() -> dict:
    """A fully-valid serialized ``Reminder`` for ``TestMalformedReminderFromDict``.

    The function-scope default returns a fresh dict per test, so the
    per-field hostile mutations (``del d["id"]``, ``d["start_at"] = ...``)
    don't leak across tests.
    """
    return {
        "id": "00000000-0000-4000-8000-00000000aaaa",
        "name": "valid",
        "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC).isoformat(),
        "rrule_str": None,
        "end_at": None,
    }


def _make_reminder(name: str = "test", **overrides: object) -> Reminder:
    defaults: dict = {
        "name": name,
        "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Reminder(**defaults)  # type: ignore[arg-type]


class TestEmptyStore:
    """Behavior when the store has no reminders yet."""

    def test_list_all_returns_empty_when_no_file_exists(self, store_path: Path) -> None:
        """``list_all()`` returns ``[]`` and does not create the file."""
        assert not store_path.exists()
        store = ReminderStore(store_path)
        assert store.list_all() == []
        # list_all must NOT create the file as a side effect.
        assert not store_path.exists()

    def test_list_all_returns_empty_when_file_is_empty_array(self, store_path: Path) -> None:
        """A file containing the literal ``[]`` is read as an empty store."""
        store_path.write_text("[]", encoding="utf-8")
        assert ReminderStore(store_path).list_all() == []


class TestCRUD:
    """Add/list/update/delete contract (FR-011 / FR-012)."""

    def test_add_then_list_returns_one(self, store: ReminderStore) -> None:
        """``add()`` followed by ``list_all()`` returns the reminder we added."""
        r = _make_reminder("dentist")
        store.add(r)

        items = store.list_all()
        assert len(items) == 1
        assert items[0].id == r.id
        assert items[0].name == "dentist"

    def test_add_preserves_insertion_order(self, store: ReminderStore) -> None:
        """``list_all()`` returns reminders in the order they were added."""
        names = ["alpha", "bravo", "charlie", "delta"]
        for name in names:
            store.add(_make_reminder(name))
        assert [r.name for r in store.list_all()] == names

    def test_update_replaces_matching_id(self, store: ReminderStore) -> None:
        """``update()`` swaps an existing entry by ``id`` and persists the change."""
        original = _make_reminder("initial")
        store.add(original)

        edited = Reminder(
            id=original.id,
            name="renamed",
            start_at=original.start_at,
            rrule_str="FREQ=DAILY",
        )
        store.update(edited)

        items = store.list_all()
        assert len(items) == 1
        assert items[0].id == original.id
        assert items[0].name == "renamed"
        assert items[0].rrule_str == "FREQ=DAILY"

    def test_update_is_noop_when_id_not_present(self, store: ReminderStore) -> None:
        """``update()`` with an unknown ``id`` leaves the existing list unchanged."""
        # The current contract: update() rewrites the list using a comprehension,
        # so an unknown id leaves the list unchanged. Pin that behavior.
        store.add(_make_reminder("kept"))
        store.update(_make_reminder("phantom"))  # different id — won't match
        names = [r.name for r in store.list_all()]
        assert names == ["kept"]

    def test_delete_removes_matching_id(self, store: ReminderStore) -> None:
        """``delete()`` removes the matching ``id`` and leaves siblings alone."""
        keep = _make_reminder("keep")
        drop = _make_reminder("drop", start_at=datetime(2026, 7, 1, tzinfo=UTC))
        store.add(keep)
        store.add(drop)

        store.delete(drop.id)

        ids = [r.id for r in store.list_all()]
        assert ids == [keep.id]

    def test_delete_is_noop_for_unknown_id(self, store: ReminderStore) -> None:
        """``delete()`` with an unknown ``id`` is a silent no-op."""
        store.add(_make_reminder("sole-survivor"))
        store.delete("does-not-exist")
        assert len(store.list_all()) == 1


class TestRoundTrip:
    """Disk-round-trip parity across instances.

    Values written by one ReminderStore must come back identically from a
    second instance reading the same file.
    """

    def test_rrule_str_round_trips_verbatim(self, store_path: Path) -> None:
        """An RRULE string is persisted verbatim across a fresh load."""
        rrule = "FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=12"
        store = ReminderStore(store_path)
        store.add(_make_reminder("standup", rrule_str=rrule))
        del store

        loaded = ReminderStore(store_path).list_all()[0]
        assert loaded.rrule_str == rrule

    def test_end_at_round_trips_with_timezone(self, store_path: Path) -> None:
        """A tz-aware ``end_at`` survives the JSON round-trip with its tzinfo."""
        end = datetime(2026, 12, 31, 17, 0, tzinfo=UTC)
        store = ReminderStore(store_path)
        store.add(_make_reminder("quarterly", rrule_str="FREQ=MONTHLY", end_at=end))
        del store

        loaded = ReminderStore(store_path).list_all()[0]
        assert loaded.end_at == end

    def test_optional_fields_round_trip_as_none(self, store_path: Path) -> None:
        """Unset ``rrule_str`` / ``end_at`` come back as ``None`` after a reload."""
        store = ReminderStore(store_path)
        store.add(_make_reminder("oneshot"))
        del store

        loaded = ReminderStore(store_path).list_all()[0]
        assert loaded.rrule_str is None
        assert loaded.end_at is None

    def test_id_round_trips_as_uuid_string(self, store_path: Path) -> None:
        """The auto-assigned UUID ``id`` survives the JSON round-trip."""
        original = _make_reminder("with-id")
        store = ReminderStore(store_path)
        store.add(original)
        del store

        loaded = ReminderStore(store_path).list_all()[0]
        assert loaded.id == original.id

    def test_full_lifecycle_persists(self, store_path: Path) -> None:
        """Add → reopen → update → reopen → delete → reopen converges to ``[]``."""
        # Add → restart → update → restart → delete → restart should
        # converge to an empty list, with each phase observable.
        store_a = ReminderStore(store_path)
        r = _make_reminder("phase-1")
        store_a.add(r)
        del store_a

        store_b = ReminderStore(store_path)
        store_b.update(Reminder(id=r.id, name="phase-2", start_at=r.start_at))
        del store_b

        store_c = ReminderStore(store_path)
        assert store_c.list_all()[0].name == "phase-2"
        store_c.delete(r.id)
        del store_c

        store_d = ReminderStore(store_path)
        assert store_d.list_all() == []


class TestDefensiveBehavior:
    """Defensive paths: corrupt files and tmp-file leftovers.

    The store must not crash on a malformed file, and must not leave
    half-written tmp files behind on the happy path.
    """

    def test_corrupted_json_returns_empty_list(self, store_path: Path) -> None:
        """A corrupt JSON file produces an empty list, not an exception."""
        store_path.write_text("{ not valid json", encoding="utf-8")
        store = ReminderStore(store_path)
        assert store.list_all() == []

    def test_corrupted_json_does_not_clobber_file_on_read(self, store_path: Path) -> None:
        """Reading a corrupt file does not silently overwrite it."""
        # A read of a corrupted file must NOT silently overwrite it —
        # the user might still recover the bytes manually. Only writes
        # replace the file.
        bad = "{ not valid json"
        store_path.write_text(bad, encoding="utf-8")
        ReminderStore(store_path).list_all()
        assert store_path.read_text(encoding="utf-8") == bad

    def test_no_tmp_file_left_after_successful_write(self, store_path: Path) -> None:
        """A successful write removes the ``.json.tmp`` staging file."""
        store = ReminderStore(store_path)
        store.add(_make_reminder("test"))
        tmp_file = store_path.with_suffix(".json.tmp")
        assert not tmp_file.exists()


class TestReminderStoreReadResilience:
    """Row-containment invariant for ``ReminderStore._read`` (R-5, post-Phase-3 fix).

    Pins the post-fix behavior so the Phase 3 GREEN fix has a precise
    oracle. Today (pre-Phase-3) every test in this class FAILS RED — the
    list comprehension at ``break_reminder/storage/reminders.py:232``
    propagates per-row exceptions through ``ReminderStore.list_all()``,
    so one bad row crashes the entire load.

    Post-fix expectations (per the Phase 3 contract in
    ``plan.md`` "Critical Implementation Details"):

    1. One bad row → that row dropped, well-formed siblings preserved.
    2. All bad rows → empty list, each one logged at WARNING level.
    3. Non-list top-level (dict / string) → empty list + a single
       "top-level is not a list" WARNING (no spurious per-row warnings
       from iterating a dict's keys or a string's chars).

    Logging uses Python's stdlib ``logging`` (not Qt-side); the post-fix
    module logger is ``logging.getLogger("break_reminder.storage.reminders")``
    and pytest's built-in ``caplog`` fixture captures it without any
    monkey-patching — same idiomatic pattern recommended by
    ``research.md`` §A.6 "logging surface".

    Sibling cluster: extends ``TestDefensiveBehavior`` (above) from
    "whole-file-corrupt → []" to "per-row-corrupt → drop bad + keep good".
    """

    @staticmethod
    def _malformed_row() -> dict:
        """A reminder-shaped dict whose ``start_at`` triggers ``ValueError``.

        Useful when the test needs a "syntactically a dict but breaks
        ``from_dict``" row — e.g. when assembling a mixed good/bad list
        to exercise the per-row containment branch.
        """
        return {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "broken",
            "start_at": "definitely-not-iso",
            "rrule_str": None,
            "end_at": None,
            "lead_minutes": 0,
        }

    def test_one_bad_row_drops_only_bad_row(self, store_path: Path, store: ReminderStore) -> None:
        """Post-fix: a 3-row list with the middle row malformed loads the 2 siblings.

        Today (RED): the malformed middle row raises ``ValueError`` from
        ``datetime.fromisoformat``; the list comprehension propagates;
        ``list_all()`` raises before any reminder is returned.
        """
        rows = [
            _make_reminder(name="alpha").to_dict(),
            self._malformed_row(),
            _make_reminder(name="omega").to_dict(),
        ]
        store_path.write_text(json.dumps(rows), encoding="utf-8")
        result = store.list_all()
        assert len(result) == 2
        assert {r.name for r in result} == {"alpha", "omega"}

    def test_bad_row_logs_warning(
        self,
        store_path: Path,
        store: ReminderStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Post-fix: the dropped row emits a WARNING naming the row index + exception class.

        Log message shape (per the Phase 3 contract):
        ``"reminders.json row %d is malformed (%s: %s); dropping"``.
        The test asserts on substrings — the row index (``1``, the
        middle of a 3-element list) and the exception class name
        (``ValueError`` from malformed-ISO) — rather than on the literal
        format string, so a wording change that preserves the
        load-bearing pieces doesn't break the test.

        Today (RED): no logger exists in the module; the exception
        propagates instead of being caught and logged.
        """
        rows = [
            _make_reminder(name="alpha").to_dict(),
            self._malformed_row(),
            _make_reminder(name="omega").to_dict(),
        ]
        store_path.write_text(json.dumps(rows), encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="break_reminder.storage.reminders"):
            store.list_all()
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and r.name == "break_reminder.storage.reminders"
        ]
        assert any("row 1" in r.getMessage() for r in warnings)
        assert any("ValueError" in r.getMessage() for r in warnings)

    def test_all_bad_rows_returns_empty_list(
        self,
        store_path: Path,
        store: ReminderStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Post-fix: a list where every row is malformed returns ``[]`` + 3 WARNINGs.

        Pin the WARNING count to ``3`` so a silent "we dropped 2 of 3
        without telling you" regression trips here. Each per-row drop
        is independently observable; nothing is silently merged.

        Today (RED): the first row's exception propagates; the remaining
        rows are never inspected; ``list_all()`` raises.
        """
        rows = [self._malformed_row(), self._malformed_row(), self._malformed_row()]
        store_path.write_text(json.dumps(rows), encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="break_reminder.storage.reminders"):
            result = store.list_all()
        assert result == []
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and r.name == "break_reminder.storage.reminders"
        ]
        assert len(warnings) == 3

    def test_top_level_dict_returns_empty_list_with_warning(
        self,
        store_path: Path,
        store: ReminderStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Post-fix: a JSON object at the top level returns ``[]`` + ONE ``"not a list"`` WARNING.

        Without the ``isinstance(raw, list)`` top-level guard, iterating
        a dict yields its keys (strings), which would crash inside
        ``from_dict`` with N spurious per-row warnings (one per key).
        The guard collapses this to a single "top-level is not a list"
        WARNING and an empty result — that single-WARNING contract is
        what the assertion pins.

        Today (RED): iterating the dict yields the key ``"foo"`` as a
        ``str``; ``from_dict("foo")`` raises ``TypeError`` on
        ``data["id"]``; ``list_all()`` raises.
        """
        store_path.write_text('{"foo": "bar"}', encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="break_reminder.storage.reminders"):
            result = store.list_all()
        assert result == []
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and r.name == "break_reminder.storage.reminders"
        ]
        assert len(warnings) == 1
        assert "top-level is not a list" in warnings[0].getMessage()

    def test_top_level_string_returns_empty_list_with_warning(
        self,
        store_path: Path,
        store: ReminderStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Post-fix: a JSON string at the top level matches the dict-case behavior.

        Same expected shape as ``test_top_level_dict_*`` — the
        ``isinstance(raw, list)`` guard catches the non-list cases
        uniformly, regardless of which non-list JSON type was written.

        Today (RED): iterating ``"foo"`` yields characters;
        ``from_dict("f")`` raises ``TypeError`` on ``data["id"]``;
        ``list_all()`` raises.
        """
        store_path.write_text('"foo"', encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="break_reminder.storage.reminders"):
            result = store.list_all()
        assert result == []
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and r.name == "break_reminder.storage.reminders"
        ]
        assert len(warnings) == 1
        assert "top-level is not a list" in warnings[0].getMessage()


class TestReminderSerialization:
    """``Reminder.to_dict`` / ``from_dict`` round-trip parity.

    Important because storage is JSON-by-hand, not pydantic — every
    serializable field has to survive a full encode/decode cycle.
    """

    def test_to_dict_then_from_dict_preserves_all_fields(self) -> None:
        """Every populated field round-trips through ``to_dict`` → ``from_dict``."""
        r = Reminder(
            name="round-trip",
            start_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            rrule_str="FREQ=WEEKLY;BYDAY=TU",
            end_at=datetime(2026, 12, 1, tzinfo=UTC),
        )
        recovered = Reminder.from_dict(r.to_dict())
        assert recovered.id == r.id
        assert recovered.name == r.name
        assert recovered.start_at == r.start_at
        assert recovered.rrule_str == r.rrule_str
        assert recovered.end_at == r.end_at

    def test_to_dict_emits_iso_format_strings(self) -> None:
        """``to_dict`` emits ISO-8601 strings for datetimes (or ``None``)."""
        r = _make_reminder()
        d = r.to_dict()
        # start_at and end_at must be JSON-friendly strings (or None for end_at)
        assert isinstance(d["start_at"], str)
        datetime.fromisoformat(d["start_at"])  # raises if not ISO
        assert d["end_at"] is None


class TestReminderLeadMinutes:
    """``Reminder.lead_minutes`` field (S-06b) round-trip behavior.

    The field is round-trip metadata under Storage Model A — ``start_at``
    keeps meaning "firing time", and ``lead_minutes`` records how many
    minutes before the event the popup should fire so S-07's Edit
    dialog can reconstruct the event time as
    ``start_at + timedelta(minutes=lead_minutes)``. The three tests
    below pin the default, the non-zero round-trip, and the
    backward-compat read for pre-S-06b ``reminders.json`` files.
    """

    def test_default_lead_minutes_is_zero(self) -> None:
        """A ``Reminder`` constructed without ``lead_minutes`` defaults to 0."""
        r = _make_reminder("default-lead")
        assert r.lead_minutes == 0

    def test_to_dict_roundtrip_preserves_lead_minutes(self) -> None:
        """A non-zero ``lead_minutes`` survives ``to_dict`` → ``from_dict``.

        Uses an explicit value (15) rather than relying on the dataclass
        default so the round-trip path is observably exercised — a
        regression that silently dropped the field would produce 0 on
        the recovered side and this assertion would fail.
        """
        r = _make_reminder("with-lead", lead_minutes=15)
        d = r.to_dict()
        assert d["lead_minutes"] == 15  # serialized verbatim
        recovered = Reminder.from_dict(d)
        assert recovered.lead_minutes == 15

    def test_from_dict_missing_key_defaults_to_zero(self) -> None:
        """A dict without ``lead_minutes`` (pre-S-06b file) loads as 0.

        Tripwire for backward compatibility: existing users' on-disk
        ``reminders.json`` entries were written by S-06 without the
        ``lead_minutes`` key. ``from_dict`` must accept those dicts
        and produce a ``Reminder`` with ``lead_minutes == 0`` (same
        firing behavior as before this slice).
        """
        legacy_dict = {
            "id": "00000000-0000-4000-8000-000000000000",
            "name": "legacy",
            "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC).isoformat(),
            "rrule_str": None,
            "end_at": None,
            # NB: no ``lead_minutes`` key — pre-S-06b file shape.
        }
        recovered = Reminder.from_dict(legacy_dict)
        assert recovered.lead_minutes == 0
        # Sanity: the rest of the round-trip still works.
        assert recovered.name == "legacy"
        assert recovered.start_at == datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


class TestCoerceLeadMinutes:
    """``_coerce_lead_minutes`` boundary helper (S-06b hardening, F4).

    FR-015 documents ``reminders.json`` as user-editable in Notepad, so the
    storage layer treats every disk read as potentially-hostile input.
    These tests pin the four invariants the helper enforces:

    1. Valid int passes through unchanged.
    2. Non-coercible types fall back to ``_LEAD_MIN_VALUE`` (0).
    3. Negative values clamp up to ``_LEAD_MIN_VALUE``.
    4. Values above ``_LEAD_MAX_VALUE`` (60) clamp down.

    The fourth invariant also doubles as the contract between the
    storage bounds and the UI's spinbox cap — the two surfaces
    duplicate the bounds for layering reasons and a drift would slip
    past the form's validation only to be silently corrected here.
    """

    def test_valid_int_passes_through(self) -> None:
        """A well-formed int in range returns unchanged."""
        assert _coerce_lead_minutes(0) == 0
        assert _coerce_lead_minutes(15) == 15
        assert _coerce_lead_minutes(60) == 60

    def test_numeric_string_coerces(self) -> None:
        """``"15"`` (string from a hand-edit) coerces to ``15``."""
        assert _coerce_lead_minutes("15") == 15

    def test_float_coerces_via_int_truncation(self) -> None:
        """``int(15.7) == 15`` — float input truncates rather than rounding."""
        assert _coerce_lead_minutes(15.7) == 15

    def test_non_coercible_string_falls_back_to_min(self) -> None:
        """``"ten"`` is not a numeric string — fall back to ``_LEAD_MIN_VALUE``.

        Without this fallback, ``int("ten")`` would raise ``ValueError``
        inside ``from_dict`` and the entire ``reminders.json`` file
        would fail to load.
        """
        assert _coerce_lead_minutes("ten") == _LEAD_MIN_VALUE

    def test_none_falls_back_to_min(self) -> None:
        """``None`` (e.g. ``"lead_minutes": null`` in JSON) → 0."""
        assert _coerce_lead_minutes(None) == _LEAD_MIN_VALUE

    def test_list_falls_back_to_min(self) -> None:
        """Wrong-type values (lists, dicts) → 0 rather than crash."""
        assert _coerce_lead_minutes([1, 2, 3]) == _LEAD_MIN_VALUE

    def test_negative_clamps_to_min(self) -> None:
        """Negative leads are nonsensical — clamp up to ``_LEAD_MIN_VALUE``."""
        assert _coerce_lead_minutes(-5) == _LEAD_MIN_VALUE
        assert _coerce_lead_minutes(-1) == _LEAD_MIN_VALUE

    def test_above_max_clamps_down(self) -> None:
        """Values above ``_LEAD_MAX_VALUE`` clamp down to the cap."""
        assert _coerce_lead_minutes(61) == _LEAD_MAX_VALUE
        assert _coerce_lead_minutes(9999) == _LEAD_MAX_VALUE

    def test_from_dict_coerces_hostile_input(self) -> None:
        """End-to-end: ``from_dict`` of a hand-edited dict with bad lead value.

        The most-likely real-world failure: someone opens
        ``reminders.json`` in Notepad, types ``"lead_minutes": 9999``,
        saves. Pre-fix this loaded as 9999 and the form's display + the
        scheduler's ``timedelta`` arithmetic would happily process it.
        Post-fix it clamps to 60 — same upper bound the UI enforces.
        """
        hostile_dict = {
            "id": "00000000-0000-4000-8000-000000000001",
            "name": "hand-edited",
            "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC).isoformat(),
            "rrule_str": None,
            "end_at": None,
            "lead_minutes": 9999,
        }
        recovered = Reminder.from_dict(hostile_dict)
        assert recovered.lead_minutes == _LEAD_MAX_VALUE


class TestCoerceAwareUtc:
    """``_coerce_aware_utc`` boundary helper (impl-review F2 hardening).

    Pins the tz-aware invariant the ``Reminder`` dataclass docstring
    documents. Three invariants:

    1. Already-aware datetimes pass through unchanged.
    2. Tz-naive datetimes (from a hand-edited ``reminders.json`` where
       the user dropped the ``+00:00`` suffix) gain a UTC tzinfo so
       downstream comparisons don't raise ``TypeError``.
    3. ``None`` (for optional ``end_at``) round-trips as ``None``.

    Without this helper the S-07 Edit-mode past-time skip predicate
    (``start_at_utc == self._editing.start_at``) would crash on any
    hand-edited entry that lost its timezone suffix, since Python
    refuses to compare tz-aware and tz-naive datetimes.
    """

    def test_aware_utc_passes_through(self) -> None:
        """A tz-aware UTC datetime returns unchanged (identity preserved)."""
        aware = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        result = _coerce_aware_utc(aware)
        assert result is aware

    def test_aware_non_utc_passes_through(self) -> None:
        """A tz-aware non-UTC datetime is not re-anchored; we preserve the zone.

        The helper is "ensure tz-aware", not "convert to UTC". A future
        code path that hands us an aware datetime in another zone
        (e.g., a recurrence rule that returns local times) must round-
        trip its zone faithfully — only naive inputs get UTC attached.
        """
        from datetime import timedelta, timezone

        est = timezone(timedelta(hours=-5))
        aware_est = datetime(2026, 6, 1, 9, 0, tzinfo=est)
        result = _coerce_aware_utc(aware_est)
        assert result is aware_est

    def test_naive_gains_utc(self) -> None:
        """A tz-naive datetime gets ``tzinfo=UTC`` (wall-clock interpreted as UTC)."""
        naive = datetime(2026, 6, 1, 9, 0)
        result = _coerce_aware_utc(naive)
        assert result == datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        assert result is not None and result.tzinfo is UTC

    def test_none_returns_none(self) -> None:
        """``None`` input (optional ``end_at``) returns ``None``."""
        assert _coerce_aware_utc(None) is None

    def test_from_dict_normalizes_naive_start_at(self) -> None:
        """A hand-edited entry without timezone suffix loads as UTC-aware.

        Most-likely real-world failure mode: user opens
        ``reminders.json`` in Notepad, edits the time, and saves
        without re-adding the ``+00:00`` suffix. ``fromisoformat``
        returns a tz-naive datetime; pre-fix this loaded into
        ``Reminder.start_at`` and crashed any tz-aware comparison
        downstream (notably the S-07 Edit-mode skip predicate).
        Post-fix it normalizes to ``datetime(..., tzinfo=UTC)``.
        """
        hand_edited = {
            "id": "00000000-0000-4000-8000-000000000002",
            "name": "hand-edited-no-tz",
            "start_at": "2026-06-01T09:00:00",  # NO +00:00 suffix
            "rrule_str": None,
            "end_at": None,
        }
        recovered = Reminder.from_dict(hand_edited)
        assert recovered.start_at == datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        assert recovered.start_at.tzinfo is not None

    def test_from_dict_normalizes_naive_end_at(self) -> None:
        """A hand-edited ``end_at`` without timezone suffix loads as UTC-aware.

        Symmetric tripwire to ``start_at`` for the optional end-date
        field. Tests that the coercion is applied to ``end_at`` too,
        not just ``start_at``.
        """
        hand_edited = {
            "id": "00000000-0000-4000-8000-000000000003",
            "name": "with-end-no-tz",
            "start_at": datetime(2026, 6, 1, 9, 0, tzinfo=UTC).isoformat(),
            "rrule_str": "FREQ=DAILY",
            "end_at": "2026-12-31T17:00:00",  # NO +00:00 suffix
        }
        recovered = Reminder.from_dict(hand_edited)
        assert recovered.end_at == datetime(2026, 12, 31, 17, 0, tzinfo=UTC)
        assert recovered.end_at is not None and recovered.end_at.tzinfo is not None


class TestMalformedReminderFromDict:
    """``Reminder.from_dict`` per-field behavior on malformed-input classes (R-5, FR-015).

    These per-field behaviors are unchanged by the Phase 3 ``_read``
    row-containment fix — the fix wraps ``from_dict`` at the row level;
    ``from_dict`` itself keeps its current raise / coerce / pass-through
    contract. Each test pins today's behavior so a future refactor that
    changes a coerce-point trips here.

    Matrix coverage (research.md §A.5) — empty cells from the existing
    suite that this class fills:

    1. Missing required keys (``id`` / ``name`` / ``start_at``) raise
       ``KeyError`` — they are bare subscripts in ``from_dict``, not
       ``data.get(...)`` calls.
    2. Malformed ISO datetime strings raise ``ValueError`` from
       ``datetime.fromisoformat``. Distinct from the tz-naive case
       already covered by ``TestCoerceAwareUtc``.
    3. Non-str ``start_at`` raises ``TypeError`` from ``fromisoformat``.
    4. Non-str / wrong-type values on the unguarded fields (``id``,
       ``name``, ``rrule_str``) pass through silently — the dataclass
       annotations are not runtime-enforced.
    5. Unknown extra keys are silently ignored — ``from_dict`` only
       reads named keys.

    Class lives after ``TestCoerceAwareUtc`` to preserve the
    boundary-helper cluster ordering (CoerceLeadMinutes →
    CoerceAwareUtc → MalformedFromDict).
    """

    def test_missing_id_raises_key_error(self, valid_reminder_dict: dict) -> None:
        """A dict missing ``id`` raises ``KeyError`` (bare subscript at from_dict)."""
        del valid_reminder_dict["id"]
        with pytest.raises(KeyError, match="id"):
            Reminder.from_dict(valid_reminder_dict)

    def test_missing_name_raises_key_error(self, valid_reminder_dict: dict) -> None:
        """A dict missing ``name`` raises ``KeyError`` (bare subscript at from_dict)."""
        del valid_reminder_dict["name"]
        with pytest.raises(KeyError, match="name"):
            Reminder.from_dict(valid_reminder_dict)

    def test_missing_start_at_raises_key_error(self, valid_reminder_dict: dict) -> None:
        """A dict missing ``start_at`` raises ``KeyError`` (bare subscript at from_dict)."""
        del valid_reminder_dict["start_at"]
        with pytest.raises(KeyError, match="start_at"):
            Reminder.from_dict(valid_reminder_dict)

    def test_malformed_start_at_iso_raises_value_error(self, valid_reminder_dict: dict) -> None:
        """A non-ISO ``start_at`` string raises ``ValueError`` from ``fromisoformat``.

        Distinct from the tz-naive case in ``TestCoerceAwareUtc`` —
        ``_coerce_aware_utc`` only fires AFTER ``fromisoformat`` returns
        a datetime; ``"not-a-date"`` fails before that, in the parse
        step itself.
        """
        valid_reminder_dict["start_at"] = "not-a-date"
        # ``match`` pins the failure to ``datetime.fromisoformat``'s
        # parse-step branch ("Invalid isoformat string: ...") rather
        # than any other ValueError that might bubble through from_dict.
        with pytest.raises(ValueError, match="isoformat"):
            Reminder.from_dict(valid_reminder_dict)

    def test_malformed_end_at_iso_raises_value_error(self, valid_reminder_dict: dict) -> None:
        """A non-ISO ``end_at`` string raises ``ValueError`` (only when truthy)."""
        valid_reminder_dict["end_at"] = "definitely-not-iso"
        with pytest.raises(ValueError, match="isoformat"):
            Reminder.from_dict(valid_reminder_dict)

    def test_non_str_start_at_raises_type_error(self, valid_reminder_dict: dict) -> None:
        """A non-string ``start_at`` (e.g. an int) raises ``TypeError`` from ``fromisoformat``."""
        valid_reminder_dict["start_at"] = (
            12345  # not a str — fromisoformat rejects on type, not value
        )
        # ``match`` pins the failure to the fromisoformat type-check
        # branch ("fromisoformat: argument must be str") rather than
        # any other TypeError that could surface in the dataclass.
        with pytest.raises(TypeError, match="fromisoformat"):
            Reminder.from_dict(valid_reminder_dict)

    def test_non_str_id_passes_through_silently(self, valid_reminder_dict: dict) -> None:
        """A non-string ``id`` (e.g. int from hand-edit) is stored as-is — dataclass annotation is not runtime-enforced.

        Pins today's silent pass-through so a future runtime-type-check
        refactor would trip here rather than slip in unobserved.
        """
        valid_reminder_dict["id"] = 42  # type: ignore[assignment]
        recovered = Reminder.from_dict(valid_reminder_dict)
        assert recovered.id == 42  # not coerced to str

    def test_non_str_name_passes_through_silently(self, valid_reminder_dict: dict) -> None:
        """A non-string ``name`` is stored as-is — same lesson as ``id``."""
        valid_reminder_dict["name"] = 7  # type: ignore[assignment]
        recovered = Reminder.from_dict(valid_reminder_dict)
        assert recovered.name == 7

    def test_non_str_rrule_passes_through_silently(self, valid_reminder_dict: dict) -> None:
        """A non-string ``rrule_str`` is stored as-is.

        The scheduler will raise later when it hands the value to
        ``dateutil.rrule.rrulestr``; the storage boundary itself is
        permissive by design (cite ``reminders.py`` module docstring:
        "an invalid RRULE string never blocks the file from loading —
        the scheduler can flag it instead").
        """
        valid_reminder_dict["rrule_str"] = 999  # type: ignore[assignment]
        recovered = Reminder.from_dict(valid_reminder_dict)
        assert recovered.rrule_str == 999

    def test_unknown_extra_key_is_silently_ignored(self, valid_reminder_dict: dict) -> None:
        """An unknown extra key in the dict is silently ignored — ``from_dict`` reads named keys only.

        Forward-compat shape: a future build that writes an extra field
        can still be read by an older build (the extra field is dropped,
        but the rest of the row loads). Pinning so a future tightening
        to "raise on unknown key" can't slip in without a deliberate
        decision.
        """
        valid_reminder_dict["future_setting"] = "tomorrow's-feature"  # type: ignore[assignment]
        recovered = Reminder.from_dict(valid_reminder_dict)
        assert recovered.name == "valid"
        assert not hasattr(recovered, "future_setting")
