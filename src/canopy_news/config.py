"""Corpus constants: the corpus name, the dated windows, where data lives."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from chrono_harness import Layout

CORPUS = "sr-media"

# The collection passes (Oct 2026) identified themselves as
#   "srb-media-dossier/0.1 (research crawler; one polite fetch per article;
#    +https://github.com/RatkoNikolic/srb-media-dossier)"
# (recorded in each fetch manifest; PROTOCOL.md §3.3). Later requests (verify, QA) use:
USER_AGENT = (
    "canopy-collapse-news/1.0 (research crawler; one polite fetch per article; "
    "+https://github.com/RatkoNikolic/canopy-collapse-news-2024-2025)"
)


@dataclass(frozen=True)
class Window:
    name: str
    start: date  # inclusive
    end: date  # inclusive
    role: str
    evaluate: bool  # recorded in fetch manifests; True for the dataset's window

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


WINDOWS: dict[str, Window] = {
    w.name: w
    for w in (
        # the id is the one recorded in the run manifests and the event log
        Window("story-v01", date(2024, 11, 1), date(2025, 4, 30),
               "the dataset's window: six months from the collapse (PROTOCOL.md §1)",
               evaluate=True),
    )
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None) -> None:
    """KEY=value lines from the repo's .env into the environment; variables
    already set win. API keys live there (template: .env.example)."""
    path = path or repo_root() / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def layout() -> Layout:
    """The data root defaults to the repo root (raw/ log/ builds/ runs/ are
    gitignored); CANOPY_NEWS_ROOT moves it, e.g. to a larger disk."""
    root = os.environ.get("CANOPY_NEWS_ROOT") or repo_root()
    return Layout(Path(root)).ensure()


@contextmanager
def exclusive(lay: Layout, stage: str) -> Iterator[None]:
    """One run of an incremental stage at a time: a second run would see the same
    work as not done and write it twice. Exits if another run holds the lock."""
    path = lay.builds / "locks" / f"{stage}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"{stage} is already running (lock {path})") from None
        yield
