from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

RecordT = TypeVar("RecordT", bound=BaseModel)


def load_model(path: Path, model_type: type[RecordT]) -> RecordT:
    return model_type.model_validate_json(path.read_text())


def load_models(directory: Path, model_type: type[RecordT]) -> tuple[RecordT, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        load_model(path, model_type) for path in sorted(directory.glob("*.json"))
    )


def write_model_atomic(path: Path, record: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"{record.model_dump_json(indent=2)}\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
