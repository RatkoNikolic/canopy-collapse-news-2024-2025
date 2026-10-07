"""The outlet registry: registries/outlets.csv, filled by the outlet rule in
PROTOCOL.md §2 *before* anything is fetched.

Columns: outlet_id, name, domains (space-separated), basis, rules_version,
and optionally exclude_hosts (space-separated hosts that sit under an
outlet's domain but are not part of it, e.g. a separate portal or a
non-news vertical), collect (yes/no: whether the outlet is retrieved at
all) and eval_v01 (yes/no, the same nine; kept for the run manifests). A host belongs to the outlet with
the longest matching domain, unless it is excluded.

Everything that touches the network loads the registry with
`collect_only=True`, so an outlet marked `collect = no` is never fetched.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from canopy_news.config import repo_root

REQUIRED = ("outlet_id", "name", "domains", "basis", "rules_version")


@dataclass(frozen=True)
class Outlet:
    outlet_id: str
    name: str
    domains: tuple[str, ...]
    basis: str
    rules_version: str
    exclude_hosts: tuple[str, ...] = ()
    collect: bool = True


def _norm(host: str) -> str:
    return host.lower().strip().removeprefix("www.")


class Registry:
    def __init__(self, outlets: list[Outlet]) -> None:
        self.outlets = outlets
        self._by_domain = {_norm(d): o for o in outlets for d in o.domains}
        self._excluded = {_norm(h) for o in outlets for h in o.exclude_hosts}

    @classmethod
    def load(cls, path: Path | None = None, *, collect_only: bool = False) -> Registry:
        path = path or repo_root() / "registries" / "outlets.csv"
        with Path(path).open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if (r.get("outlet_id") or "").strip()]
        outlets = []
        for row in rows:
            missing = [k for k in REQUIRED if not (row.get(k) or "").strip()]
            if missing:
                raise ValueError(f"{path}: outlet {row.get('outlet_id')!r} lacks {missing}")
            outlets.append(Outlet(
                outlet_id=row["outlet_id"].strip(),
                name=row["name"].strip(),
                domains=tuple(_norm(d) for d in row["domains"].split()),
                basis=row["basis"].strip(),
                rules_version=row["rules_version"].strip(),
                exclude_hosts=tuple(_norm(h) for h in (row.get("exclude_hosts") or "").split()),
                collect=(row.get("collect") or "yes").strip().lower() == "yes",
            ))
        if collect_only:
            outlets = [o for o in outlets if o.collect]
        return cls(outlets)

    @property
    def domains(self) -> set[str]:
        return set(self._by_domain)

    @property
    def rules_version(self) -> str:
        versions = {o.rules_version for o in self.outlets}
        return ",".join(sorted(versions))

    def outlet_for(self, host: str) -> Outlet | None:
        host = _norm(host)
        parts = host.split(".")
        for i in range(len(parts) - 1):  # longest suffix first
            candidate = ".".join(parts[i:])
            if candidate in self._excluded:
                return None
            outlet = self._by_domain.get(candidate)
            if outlet is not None:
                return outlet
        return None
