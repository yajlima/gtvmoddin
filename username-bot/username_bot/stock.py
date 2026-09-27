"""Username stock: one .txt file per listing, one username per line.

Picked lines are moved to <listing>.sold.txt so a name is never handed out
twice; undo puts them back. Every change takes a file lock and writes
atomically, so the bot and the `order` CLI can run at the same time.
"""

from __future__ import annotations

import fcntl
import os
import re
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

SLUG_RE = re.compile(r"[^a-z0-9_-]+")


class StockError(Exception):
    pass


def slugify(name: str) -> str:
    slug = SLUG_RE.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise StockError(f"bad listing name: {name!r} (use letters, numbers, - or _)")
    return slug[:40]


def clean_lines(text: str) -> list[str]:
    """Split pasted text/file contents into usernames, dropping blanks and #comments."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


class Stock:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- files --------------------------------------------------------------

    def _path(self, slug: str) -> Path:
        return self.dir / f"{slug}.txt"

    def _sold_path(self, slug: str) -> Path:
        return self.dir / f"{slug}.sold.txt"

    @contextmanager
    def _locked(self):
        with open(self.dir / ".lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    @staticmethod
    def _read(path: Path) -> list[str]:
        return clean_lines(path.read_text()) if path.exists() else []

    @staticmethod
    def _write(path: Path, lines: list[str]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("".join(line + "\n" for line in lines))
        os.replace(tmp, path)

    def _require(self, slug: str) -> Path:
        path = self._path(slug)
        if not path.exists():
            raise StockError(f"no listing called {slug!r}")
        return path

    # -- listings -------------------------------------------------------------

    def listings(self) -> dict[str, int]:
        """Listing slug -> usernames left, sorted by name."""
        return {
            p.stem: len(self._read(p))
            for p in sorted(self.dir.glob("*.txt"))
            if not p.name.endswith(".sold.txt")
        }

    def create(self, name: str) -> str:
        slug = slugify(name)
        with self._locked():
            path = self._path(slug)
            if path.exists():
                raise StockError(f"listing {slug!r} already exists")
            self._write(path, [])
        return slug

    def delete(self, slug: str) -> int:
        """Delete a listing; returns how many unsold names were in it. The sold log is kept."""
        with self._locked():
            path = self._require(slug)
            n = len(self._read(path))
            path.unlink()
        return n

    def add(self, slug: str, text: str) -> dict:
        """Append usernames. Skips duplicates already in stock or in the text itself,
        and reports (but still adds) names that were sold before."""
        new = clean_lines(text)
        with self._locked():
            path = self._require(slug)
            lines = self._read(path)
            have = {l.lower() for l in lines}
            sold = {self._sold_line(s).lower() for s in self._read(self._sold_path(slug))}
            added, dupes, resold = [], 0, []
            for line in new:
                if line.lower() in have:
                    dupes += 1
                    continue
                have.add(line.lower())
                added.append(line)
                if line.lower() in sold:
                    resold.append(line)
            self._write(path, lines + added)
        return {"added": len(added), "duplicates": dupes, "previously_sold": resold,
                "left": len(lines) + len(added)}

    # -- orders ---------------------------------------------------------------

    @staticmethod
    def _sold_line(entry: str) -> str:
        return entry.split("\t", 2)[-1]

    def pick(self, slug: str) -> dict:
        """Take a random username out of a listing and log it as sold."""
        with self._locked():
            path = self._require(slug)
            lines = self._read(path)
            if not lines:
                raise StockError(f"{slug} is out of stock")
            i = secrets.randbelow(len(lines))
            line = lines.pop(i)
            pick_id = secrets.token_hex(4)
            self._write(path, lines)
            sold = self._read(self._sold_path(slug))
            self._write(self._sold_path(slug), sold + [f"{pick_id}\t{int(time.time())}\t{line}"])
        return {"id": pick_id, "listing": slug, "line": line, "left": len(lines)}

    def undo(self, slug: str, pick_id: str) -> str:
        """Put a picked username back into stock (e.g. the order was cancelled)."""
        with self._locked():
            path = self._require(slug)
            sold = self._read(self._sold_path(slug))
            for j, entry in enumerate(sold):
                if entry.split("\t", 1)[0] == pick_id:
                    line = self._sold_line(entry)
                    del sold[j]
                    self._write(self._sold_path(slug), sold)
                    self._write(path, self._read(path) + [line])
                    return line
        raise StockError("already undone, or that pick doesn't exist")


def split_details(line: str) -> list[str]:
    """A line can hold several details (name:extra or name|extra); each is sent separately."""
    for sep in ("\t", "|", ":"):
        if sep in line:
            parts = [p.strip() for p in line.split(sep)]
            return [p for p in parts if p] or [line]
    return [line]
