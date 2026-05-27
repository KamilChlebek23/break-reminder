"""Round-trip tests for ``break_reminder.storage.reminders``.

Covers FR-011 (add a custom reminder), FR-012 (list / edit / delete), and
FR-014 (recurrence stored as iCalendar RRULE strings, with optional end
dates). The module's defensive corrupt-file-recovery path is exercised
explicitly so a future regression there is caught loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from break_reminder.storage.reminders import Reminder, ReminderStore

UTC = UTC


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Path to a per-test ``reminders.json`` file under ``tmp_path``."""
    return tmp_path / "reminders.json"


@pytest.fixture
def store(store_path: Path) -> ReminderStore:
    """A ``ReminderStore`` instance bound to the per-test ``store_path``."""
    return ReminderStore(store_path)


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
