"""Where the tasks live: one JSON file in the data folder.

The folder is $TWIGT_DATA, or else $XDG_DATA_HOME/twigt (~/.local/share/twigt).
A change reads, edits and writes the file under one lock, so two shells or
chats changing tasks at once can't drop each other's edits; the write goes
to a temporary file first and replaces the old one in one step, so a
reader never sees half a file."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path

from twigt.tasks import FORMAT, Data, Problem, empty


def default_folder() -> Path:
    if os.environ.get("TWIGT_DATA"):
        return Path(os.environ["TWIGT_DATA"]).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "twigt"


class Store:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / "twigt.json"

    def read(self) -> Data:
        if not self.path.exists():
            return empty()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT:
            raise Problem(f"{self.path} has format {data.get('format')!r}, this twigt reads {FORMAT}: update twigt")
        return data

    @contextlib.contextmanager
    def change(self) -> Iterator[Data]:
        """The data to change; written back when the block ends without an error."""
        self.folder.mkdir(parents=True, exist_ok=True)
        with open(self.folder / "twigt.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.read()
            yield data
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            temporary.replace(self.path)
