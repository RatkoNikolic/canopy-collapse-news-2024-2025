"""Relevance stage 1: the lexicon (PROTOCOL.md §5.2).

Terms live in registries/lexicon.csv, in four lists: `collapse` (neutral,
collapse-specific), `neutral` (movement vocabulary used by every side), and
`protester` / `government` (stance-marked vocabulary, always used as a pair so
that neither side's wording alone decides what is a candidate). A term is a
regex over the lowercased Latin text plus its lemmas; `A && B` means both must
occur in the same article. An article is a candidate if any term matches.
The lexicon only nominates candidates; the classifier (stage 3) decides scope.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout

from canopy_news.config import repo_root
from canopy_news.documents import doc_dir
from canopy_news.lemmas import lemma_dir
from canopy_news.nonnews import NonNews

LISTS = ("collapse", "neutral", "protester", "government")


@dataclass(frozen=True)
class Term:
    list: str
    term: str
    parts: tuple[re.Pattern, ...]


def load(path: Path | None = None) -> list[Term]:
    path = path or repo_root() / "registries" / "lexicon.csv"
    with Path(path).open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("list") or "").strip()]
    return [Term(r["list"].strip(), r["term"].strip(),
                 tuple(re.compile(p.strip()) for p in r["term"].split("&&")))
            for r in rows]


def version(terms: list[Term]) -> str:
    import hashlib

    return "lex-" + hashlib.sha256("\n".join(t.list + ":" + t.term for t in terms)
                                   .encode()).hexdigest()[:10]


def match(text: str, terms: list[Term]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = defaultdict(list)
    for t in terms:
        if all(p.search(text) for p in t.parts):
            hits[t.list].append(t.term)
    return hits


def _listing(files: list[Path]) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def run(lay: Layout) -> dict:
    terms = load()
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    lems = sorted(lemma_dir(lay).glob("part-*.parquet"))
    if not docs:
        return {}
    lemma_join = (f"LEFT JOIN read_parquet([{_listing(lems)}]) l USING (event_id)" if lems else "")
    lemma_cols = ("coalesce(l.lemmas_title,'') || ' ' || coalesce(l.lemmas_lead,'') || ' ' || "
                  "coalesce(l.lemmas_body,'')") if lems else "''"
    rows = duckdb.sql(f"""SELECT d.event_id, d.outlet_id, d.unit_id, CAST(CAST(d.valid_time AS DATE) AS VARCHAR) AS day,
        lower(d.title || '\n' || d.lead || '\n' || d.body) AS text, {lemma_cols} AS lemmas
        FROM read_parquet([{_listing(docs)}]) d {lemma_join}
        ORDER BY d.event_id""").to_arrow_table().to_pylist()   # fixed order: identical files on rerun
    out, per_term = [], Counter()
    nonnews = NonNews.load()   # non-news sections (PROTOCOL.md §3.2) leave the corpus here
    for r in rows:
        if nonnews.reason(r["outlet_id"], r["unit_id"]):
            continue
        hits = match(r["text"] + "\n" + r["lemmas"], terms)
        for lst, ts in hits.items():
            per_term.update(f"{lst}: {t}" for t in ts)
        out.append({"event_id": r["event_id"], "outlet_id": r["outlet_id"], "day": r["day"],
                    **{f"hit_{x}": len(hits.get(x, [])) for x in LISTS},
                    "terms": [f"{x}: {t}" for x in LISTS for t in hits.get(x, [])],
                    "candidate": bool(hits)})
    ver = version(terms)
    out_dir = lay.build_dir("scope")
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(out), out_dir / f"{ver}.parquet", compression="zstd")
    return {"version": ver, "rows": out, "per_term": per_term}


def report(result: dict) -> dict:
    rows = result["rows"]
    n = len(rows)
    by_outlet = defaultdict(lambda: Counter())
    for r in rows:
        c = by_outlet[r["outlet_id"]]
        c["docs"] += 1
        c["candidates"] += r["candidate"]
        for x in LISTS:
            c[x] += r[f"hit_{x}"] > 0
        c["collapse_only_or_neutral"] += r["candidate"] and not (r["hit_protester"] or r["hit_government"])
    return {
        "version": result["version"], "docs": n,
        "candidates": sum(r["candidate"] for r in rows),
        "by_list": {x: sum(r[f"hit_{x}"] > 0 for r in rows) for x in LISTS},
        "candidates_without_protest_term": sum(
            r["candidate"] and not any("protest" in t for t in r["terms"]) or
            (r["candidate"] and len(r["terms"]) > 1) for r in rows),
        "by_outlet": {o: dict(c) for o, c in sorted(by_outlet.items())},
        "per_term": dict(result["per_term"].most_common()),
    }
