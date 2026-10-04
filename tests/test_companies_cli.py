import json

import pytest

from internship_hunter import db
from internship_hunter.companies.cli import SEED_DATA_PATH, load_seed


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


def test_seed_data_file_is_valid_json_list():
    entries = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    assert isinstance(entries, list)
    assert len(entries) >= 15  # sanity check we actually seeded a real list


def test_seed_data_entries_have_required_fields_and_valid_tiers():
    required_fields = {
        "name", "website", "state", "city", "stage", "what_they_build",
        "why_fit", "careers_url", "priority_tier",
    }
    entries = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    for entry in entries:
        missing = required_fields - entry.keys()
        assert not missing, f"{entry.get('name')} is missing fields: {missing}"
        assert entry["priority_tier"] in (1, 2, 3, 4), entry["name"]
        assert entry["state"] in {"VA", "CO", "WI"}, (
            f"{entry['name']} has state {entry['state']!r}, expected one of VA/CO/WI "
            "(or an explicit exception should be documented in notes)"
        )


def test_seed_data_has_no_duplicate_names():
    entries = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    names = [e["name"] for e in entries]
    assert len(names) == len(set(names))


def test_seed_data_covers_all_three_target_states():
    entries = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    states = {e["state"] for e in entries}
    assert {"VA", "CO", "WI"} <= states


def test_load_seed_adds_all_companies_on_first_run(conn):
    added, skipped = load_seed(conn)
    entries = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    assert added == len(entries)
    assert skipped == 0
    assert len(db.list_companies(conn)) == len(entries)


def test_load_seed_is_idempotent(conn):
    load_seed(conn)
    added_second_time, skipped_second_time = load_seed(conn)
    entries = json.loads(SEED_DATA_PATH.read_text(encoding="utf-8"))
    assert added_second_time == 0
    assert skipped_second_time == len(entries)
    # No duplicates got created
    assert len(db.list_companies(conn)) == len(entries)
