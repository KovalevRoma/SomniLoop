from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from platformdirs import user_data_dir

from somniloop.core.database import Repository


def show_desktop_notifications(repository: Repository) -> int:
    executable = shutil.which("notify-send")
    if not executable:
        return 0
    repository.sync_birthday_notifications()
    shown = 0
    try:
        delivered = json.loads(repository.get_setting("desktop_birthday_notifications", "{}"))
    except json.JSONDecodeError:
        delivered = {}
    if not isinstance(delivered, dict):
        delivered = {}
    active = repository.list_notifications()
    for notice in active:
        key = str(notice["id"])
        if delivered.get(key) == notice["birthday"]:
            continue
        try:
            result = subprocess.run(
                [
                    executable,
                    "SomniLoop · День рождения",
                    notice["title"],
                    "--app-name=SomniLoop",
                    "--icon=appointment-soon",
                ],
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            delivered[key] = notice["birthday"]
            shown += 1
    active_ids = {str(notice["id"]) for notice in active}
    delivered = {key: value for key, value in delivered.items() if key in active_ids}
    repository.set_setting(
        "desktop_birthday_notifications", json.dumps(delivered, ensure_ascii=False)
    )
    return shown


def main() -> None:
    override = os.environ.get("SOMNILOOP_DATA_DIR")
    data_dir = Path(override).expanduser() if override else Path(user_data_dir("SomniLoop"))
    repository = Repository(data_dir / "somniloop.db")
    try:
        show_desktop_notifications(repository)
    finally:
        repository.close()


if __name__ == "__main__":
    main()
