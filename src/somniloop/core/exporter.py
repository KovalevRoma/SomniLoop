from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .database import Repository


def export_json(repository: Repository, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(repository.export_payload(), ensure_ascii=False, indent=2)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        temporary.replace(target)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return target


def import_json(repository: Repository, path: str | Path) -> Path:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Корневой элемент экспорта должен быть объектом.")
    return repository.restore_payload(payload)
