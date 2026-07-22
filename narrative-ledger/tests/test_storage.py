from pathlib import Path

from pydantic import BaseModel

from ledger.storage import load_model, load_models, write_model_atomic


class FixtureRecord(BaseModel):
    name: str
    count: int


def test_atomic_model_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "record.json"
    record = FixtureRecord(name="candidate", count=1)

    write_model_atomic(path, record)

    assert load_model(path, FixtureRecord) == record
    assert not list(path.parent.glob("*.tmp"))


def test_atomic_model_write_uses_stable_json(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    record = FixtureRecord(name="candidate", count=1)

    write_model_atomic(path, record)
    first = path.read_bytes()
    write_model_atomic(path, record)

    assert path.read_bytes() == first
    assert path.read_text().endswith("\n")


def test_load_models_is_sorted_and_missing_directory_is_empty(tmp_path: Path) -> None:
    records = tmp_path / "records"
    write_model_atomic(records / "b.json", FixtureRecord(name="second", count=2))
    write_model_atomic(records / "a.json", FixtureRecord(name="first", count=1))

    assert load_models(records, FixtureRecord) == (
        FixtureRecord(name="first", count=1),
        FixtureRecord(name="second", count=2),
    )
    assert load_models(tmp_path / "missing", FixtureRecord) == ()
