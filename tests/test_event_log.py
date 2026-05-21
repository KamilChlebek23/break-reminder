"""Round-trip tests for ``break_reminder.storage.event_log``.

Covers FR-015: every break/reminder event lands in a structured local log
file, human-readable in Notepad/Excel, with rotation when the file grows
too large.

The rotation tests monkeypatch ``MAX_BYTES`` down to a few hundred bytes
so we don't have to actually write a megabyte of CSV to trigger the path.
"""

from __future__ import annotations

import csv
import threading
from datetime import datetime
from pathlib import Path

import pytest

from break_reminder.storage import event_log as event_log_mod
from break_reminder.storage.event_log import HEADER, EventLog, EventType, Outcome


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    """Path to a per-test event-log file under ``tmp_path``."""
    return tmp_path / "events.log"


@pytest.fixture
def log(log_path: Path) -> EventLog:
    """An ``EventLog`` instance bound to the per-test ``log_path`` fixture."""
    return EventLog(log_path)


def _read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as fp:
        return list(csv.reader(fp))


class TestInitialization:
    """Constructor behavior — file creation, header seeding, parent dirs."""

    def test_creates_file_with_header(self, log_path: Path) -> None:
        """Constructing on a missing file creates it and writes the header row."""
        assert not log_path.exists()
        EventLog(log_path)
        assert log_path.exists()
        assert _read_rows(log_path) == [list(HEADER)]

    def test_existing_file_with_content_is_left_alone(self, log_path: Path) -> None:
        """An existing non-empty log keeps its prior rows intact across reopen."""
        # Pre-populate the file as if a prior run had written events.
        with log_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(HEADER)
            writer.writerow(["2026-01-01T00:00:00+00:00", "break", "taken", "prior"])

        EventLog(log_path)

        rows = _read_rows(log_path)
        assert rows[0] == list(HEADER)
        assert rows[1][3] == "prior"
        assert len(rows) == 2

    def test_empty_existing_file_gets_header(self, log_path: Path) -> None:
        """A zero-byte file is treated like a missing one and gets a header."""
        # An empty file (zero bytes) should be treated like a missing one.
        log_path.touch()
        EventLog(log_path)
        assert _read_rows(log_path) == [list(HEADER)]

    def test_creates_parent_directory_if_missing(self, tmp_path: Path) -> None:
        """Constructor creates any missing parent directories of ``path``."""
        nested = tmp_path / "nested" / "deeper" / "events.log"
        EventLog(nested)
        assert nested.exists()
        assert nested.parent.exists()


class TestRecord:
    """``record()`` round-trips event/outcome/detail through the CSV layer."""

    def test_appends_one_row(self, log: EventLog, log_path: Path) -> None:
        """``record()`` writes exactly one new row with the supplied fields."""
        log.record(EventType.BREAK, Outcome.TAKEN, "smoke")

        rows = _read_rows(log_path)
        assert len(rows) == 2  # header + one event
        ts, etype, outcome, detail = rows[1]
        assert etype == "break"
        assert outcome == "taken"
        assert detail == "smoke"

    def test_timestamp_is_iso_format_with_timezone(self, log: EventLog, log_path: Path) -> None:
        """Timestamps are ISO-8601 and tz-aware (FR-015 — unambiguous)."""
        log.record(EventType.BREAK, Outcome.TAKEN)
        ts = _read_rows(log_path)[1][0]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None  # FR-015 requires unambiguous timestamps

    def test_appends_multiple_rows_in_order(self, log: EventLog, log_path: Path) -> None:
        """Multiple sequential ``record()`` calls preserve insertion order on disk."""
        log.record(EventType.BREAK, Outcome.TAKEN, "first")
        log.record(EventType.BREAK, Outcome.SNOOZED, "second")
        log.record(EventType.REMINDER, Outcome.FIRED, "third")

        rows = _read_rows(log_path)
        assert [r[3] for r in rows[1:]] == ["first", "second", "third"]

    def test_records_each_event_type(self, log: EventLog, log_path: Path) -> None:
        """Every ``EventType`` value round-trips through the CSV layer unchanged."""
        for etype in EventType:
            log.record(etype, Outcome.TAKEN, str(etype))
        rows = _read_rows(log_path)
        recorded_types = [r[1] for r in rows[1:]]
        assert set(recorded_types) == {str(t) for t in EventType}

    def test_records_each_outcome(self, log: EventLog, log_path: Path) -> None:
        """Every ``Outcome`` value round-trips through the CSV layer unchanged."""
        for outcome in Outcome:
            log.record(EventType.BREAK, outcome, str(outcome))
        rows = _read_rows(log_path)
        recorded_outcomes = [r[2] for r in rows[1:]]
        assert set(recorded_outcomes) == {str(o) for o in Outcome}

    def test_detail_with_comma_is_csv_escaped(self, log: EventLog, log_path: Path) -> None:
        """A ``detail`` containing a comma is CSV-quoted; reader recovers it verbatim."""
        # csv.writer should automatically quote fields containing commas
        # so a downstream csv.reader gets the same field back.
        log.record(EventType.REMINDER, Outcome.FIRED, "see dentist, also pharmacy")
        rows = _read_rows(log_path)
        assert rows[1][3] == "see dentist, also pharmacy"


class TestRotation:
    """File-size-driven log rotation.

    When the log grows past ``MAX_BYTES``, the existing file rotates to
    ``.log.1`` and a new file with header is started.
    """

    def test_rotates_when_size_exceeds_max_bytes(
        self, log_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Crossing ``MAX_BYTES`` produces ``events.log.1`` and a fresh header."""
        monkeypatch.setattr(event_log_mod, "MAX_BYTES", 200)
        log = EventLog(log_path)
        # Each row is roughly ~50 bytes; 50 rows blows past 200 bytes.
        for i in range(50):
            log.record(EventType.BREAK, Outcome.TAKEN, f"detail-{i:02d}")

        backup = log_path.with_suffix(".log.1")
        assert backup.exists(), "rotation did not produce events.log.1"

        # The freshly-rotated file should start with a header.
        assert _read_rows(log_path)[0] == list(HEADER)

    def test_rotation_overwrites_prior_backup(
        self, log_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second rotation cycle replaces the prior ``.log.1`` backup."""
        monkeypatch.setattr(event_log_mod, "MAX_BYTES", 200)
        log = EventLog(log_path)

        for i in range(50):
            log.record(EventType.BREAK, Outcome.TAKEN, f"first-{i:02d}")
        backup = log_path.with_suffix(".log.1")
        first_backup_size = backup.stat().st_size

        # Trigger a second rotation cycle.
        for i in range(50):
            log.record(EventType.BREAK, Outcome.TAKEN, f"second-{i:02d}")

        assert backup.exists()
        # The backup must not be the old one verbatim — the second rotation
        # should have replaced it with the most-recent batch.
        second_backup_size = backup.stat().st_size
        assert (
            second_backup_size != first_backup_size
            or backup.read_text(encoding="utf-8").count("first-") == 0
        )


class TestConcurrency:
    """Thread-safety of ``EventLog.record``.

    ``record`` must be safe under concurrent calls from many threads. The
    break scheduler can plausibly fire while a reminder scheduler also
    fires; both end up calling ``record`` from different Qt-side slots.
    """

    def test_no_data_loss_under_concurrent_appends(self, log: EventLog, log_path: Path) -> None:
        """Concurrent ``record()`` calls produce no clobbered rows and no losses."""
        n_threads = 8
        n_per_thread = 25

        def worker(tid: int) -> None:
            for i in range(n_per_thread):
                log.record(EventType.BREAK, Outcome.TAKEN, f"t{tid}-{i:02d}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = _read_rows(log_path)
        # header + n_threads * n_per_thread events = 1 + 200
        assert len(rows) == 1 + n_threads * n_per_thread

        # Every (thread, sequence) pair is unique — no row was clobbered
        # mid-write by another thread's append.
        details = [r[3] for r in rows[1:]]
        assert len(set(details)) == n_threads * n_per_thread
