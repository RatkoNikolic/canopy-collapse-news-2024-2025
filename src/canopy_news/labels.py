"""Human scope labels (PROTOCOL.md §6): the pre-registered draw, labelling pages, import.

    canopy-news labels round --at 2026-10-08T12:00:00Z  # the drand round published at that time
    canopy-news labels draw  --set gold-v1 --round R     # sample + assignment, seeded by round R
    canopy-news labels page  --set gold-v1 --coder R1    # local page → builds/labelling/<set>-<coder>.html
    canopy-news labels import --set gold-v1 FILE         # page export → gold/scope_labels/<set>/labels.jsonl

The draw's seeds come from a public randomness beacon (drand mainnet, League of Entropy):
the round is fixed in PROTOCOL.md before it is published, so nobody can know or choose the
seeds in advance, and anyone can redo the draw from the published round. The sample is
stratified by relevance stratum × outlet (lexicon candidates oversampled; non-candidates by
embedding band), each row with its design weight N_h / n_h; articles in
gold/scope_labels/exclude.jsonl (the classifier pilot) are never drawn. Every coder gets the
same shared overlap (for Krippendorff's alpha) and an even share of the rest, both balanced by
stratum and outlet; each coder's page holds only their articles with their coder id fixed, and
import refuses labels for articles not assigned to that coder.

The sample and the labels hold ids and decisions only and are committed; the pages hold
article text and stay local (builds/, never published). Coding is blind: a page shows title,
date, lead and numbered paragraphs, never the outlet, the URL, the stratum or any model output.
Labels carry CODEBOOK.md's sha256, so a label is tied to the codebook text it was made under.
"""

from __future__ import annotations

import hashlib
import json
import random
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from chrono_harness import Layout

from canopy_news import embeddings, lexicon
from canopy_news.config import WINDOWS, repo_root
from canopy_news.documents import doc_dir
from chrono_harness.timeutil import now_utc

CODEBOOK = repo_root() / "CODEBOOK.md"
MIN_PER_OUTLET = 3
QUOTA = {"candidate": 200, "band-top10": 40, "band-next20": 30, "rest": 30}
CODERS, SHARED = ("R1", "R2", "R3"), 50
# drand mainnet (League of Entropy), scheme pedersen-bls-chained: randomness = sha256(signature)
DRAND = "https://api.drand.sh"
DRAND_CHAIN = "8990e7a9aaed2ffed73dbd7092123d6f289930540d7651336225dc172e51b2ce"
DRAND_GENESIS, DRAND_PERIOD = 1595431050, 30
CONFIDENCE = ("high", "medium", "low")


def codebook_sha256() -> str:
    return hashlib.sha256(CODEBOOK.read_bytes()).hexdigest()


def set_dir(lay: Layout, name: str) -> Path:
    return lay.gold / "scope_labels" / name


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def _listing(files: list[Path]) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def allocate(sizes: dict[str, int], n: int, minimum: int = MIN_PER_OUTLET) -> dict[str, int]:
    """n draws over strata: a floor of `minimum` each (capped by size), the rest
    proportional to size by largest remainder, never more than a stratum holds."""
    alloc = {k: min(minimum, v) for k, v in sizes.items()}
    left = n - sum(alloc.values())
    while left > 0:
        room = {k: sizes[k] - alloc[k] for k in sizes if sizes[k] > alloc[k]}
        if not room:
            break
        total = sum(sizes[k] for k in room)
        quota = {k: left * sizes[k] / total for k in room}
        step = {k: min(int(quota[k]), room[k]) for k in room}
        if not any(step.values()):
            step[max(room, key=lambda k: (quota[k] - int(quota[k]), k))] = 1
        for k, v in step.items():
            alloc[k] += v
        left = n - sum(alloc.values())
    return alloc


def population(lay: Layout, window: str = "story-v01") -> list[dict]:
    """Window documents with text, joined to the current lexicon's band strata."""
    lex_ver = lexicon.version(lexicon.load())
    bands = lay.build_dir("scope") / f"band-{lex_ver}-{embeddings.EMBED_VERSION}.parquet"
    if not bands.exists():
        raise SystemExit(f"{bands.name} missing: run `canopy-news band` first")
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    w = WINDOWS[window]
    return duckdb.sql(f"""SELECT d.event_id, d.outlet_id, b.stratum
        FROM read_parquet([{_listing(docs)}]) d JOIN read_parquet('{bands}') b USING (event_id)
        WHERE d.error IS NULL AND length(d.body) > 0
          AND CAST(d.valid_time AS DATE) BETWEEN DATE '{w.start}' AND DATE '{w.end}'
        ORDER BY d.event_id""").to_arrow_table().to_pylist()


def draw(pop: list[dict], quota: dict[str, int], seed: int,
         exclude: set[str] = frozenset()) -> list[dict]:
    """quota: draws per relevance stratum, each spread over outlets by `allocate`."""
    strata: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in pop:
        if r["event_id"] not in exclude:
            strata[(r["stratum"], r["outlet_id"])].append(r["event_id"])
    rng = random.Random(seed)
    out = []
    for stratum, n in quota.items():
        sizes = {o: len(ids) for (s, o), ids in strata.items() if s == stratum}
        for outlet, k in sorted(allocate(sizes, n).items()):
            ids = strata[(stratum, outlet)]
            for eid in rng.sample(ids, k):
                out.append({"event_id": eid, "outlet_id": outlet,
                            "stratum": f"{stratum}:{outlet}",
                            "weight": round(len(ids) / k, 4)})
    rng.shuffle(out)
    for i, r in enumerate(out):
        r["position"] = i
    return out


def sample(lay: Layout, name: str, *, quota: dict[str, int] = QUOTA,
           seed: int) -> dict:
    path = set_dir(lay, name) / "sample.jsonl"
    if path.exists():
        raise SystemExit(f"{path} exists: a drawn sample is never redrawn; use a new --set")
    exclude = excluded(lay)
    pop = population(lay)
    rows = draw(pop, quota, seed, exclude)
    _write_jsonl(path, rows)
    meta = {"set": name, "drawn_at": now_utc().isoformat(), "seed": seed,
            "population": len(pop), "excluded": len(exclude),
            "lexicon": lexicon.version(lexicon.load()),
            "embedding": embeddings.EMBED_VERSION, "n": len(rows), "quota": quota,
            "min_per_outlet": MIN_PER_OUTLET, "codebook_sha256": codebook_sha256()}
    (path.parent / "sample_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def excluded(lay: Layout) -> set[str]:
    """Never drawn: gold/scope_labels/exclude.jsonl and every earlier set's sample."""
    d = lay.gold / "scope_labels"
    return ({r["event_id"] for r in _read_jsonl(d / "exclude.jsonl")}
            | {r["event_id"] for p in d.glob("*/sample.jsonl") for r in _read_jsonl(p)})


def round_at(t: datetime) -> int:
    """The drand round published at time t (rounds start at genesis, one per period)."""
    return (int(t.timestamp()) - DRAND_GENESIS) // DRAND_PERIOD + 1


def round_time(r: int) -> datetime:
    return datetime.fromtimestamp(DRAND_GENESIS + (r - 1) * DRAND_PERIOD, tz=UTC)


def beacon(r: int) -> dict:
    """Fetch round r and check randomness = sha256(signature); the BLS signature itself can be
    verified against the chain's public key with drand's own tools."""
    url = f"{DRAND}/{DRAND_CHAIN}/public/{r}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        rec = json.load(resp)
    if rec["round"] != r:
        raise SystemExit(f"beacon answered round {rec['round']}, not {r}")
    if hashlib.sha256(bytes.fromhex(rec["signature"])).hexdigest() != rec["randomness"]:
        raise SystemExit("beacon randomness does not match its signature")
    return {**rec, "chain": DRAND_CHAIN, "url": url, "time": round_time(r).isoformat()}


def seeds(randomness: str) -> tuple[int, int]:
    """Two independent 64-bit seeds (sample, assignment) from the beacon's randomness."""
    def one(tag: bytes) -> int:
        return int(hashlib.sha256(bytes.fromhex(randomness) + tag).hexdigest()[:16], 16)
    return one(b"sample"), one(b"assignment")


def draw_set(lay: Layout, name: str, r: int) -> dict:
    """The pre-registered draw: sample and assignment of set `name`, seeded by drand round r."""
    if round_time(r) > now_utc():
        raise SystemExit(f"round {r} is published at {round_time(r).isoformat()}: not yet")
    rec = beacon(r)
    s_sample, s_assign = seeds(rec["randomness"])
    d = set_dir(lay, name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "beacon.json").write_text(json.dumps(rec, indent=2) + "\n")
    out = {"beacon_round": r, "sample": sample(lay, name, seed=s_sample)}
    out["assignment"] = write_assignment(lay, name, coders=list(CODERS), shared=SHARED,
                                         seed=s_assign)
    return out


def _balanced(rows: list[dict], rng: random.Random) -> list[dict]:
    """Rows grouped by stratum (relevance stratum, then outlet), shuffled within each group.
    Taking every k-th row, or dealing rows out in turn, then splits every stratum and every
    outlet evenly (within one row)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["event_id"]):
        groups[r["stratum"]].append(r)
    out = []
    for k in sorted(groups):
        rng.shuffle(groups[k])
        out += groups[k]
    return out


def assign(rows: list[dict], coders: list[str], shared: int, seed: int) -> list[dict]:
    """Shared overlap for every coder, the rest split evenly; both balanced by stratum × outlet."""
    rng = random.Random(seed)
    ordered = _balanced(rows, rng)
    step = len(ordered) / shared
    start = rng.random() * step
    shared_ids = {ordered[int(start + k * step)]["event_id"] for k in range(shared)}
    rest = _balanced([r for r in rows if r["event_id"] not in shared_ids], rng)
    out = [{"event_id": r["event_id"], "coders": list(coders), "shared": True}
           for r in ordered if r["event_id"] in shared_ids]
    out += [{"event_id": r["event_id"], "coders": [coders[k % len(coders)]], "shared": False}
            for k, r in enumerate(rest)]
    return sorted(out, key=lambda a: a["event_id"])


def write_assignment(lay: Layout, name: str, *, coders: list[str], shared: int,
                     seed: int) -> dict:
    d = set_dir(lay, name)
    path = d / "assignment.jsonl"
    if path.exists():
        raise SystemExit(f"{path} exists: an assignment is never redrawn")
    if (d / "labels.jsonl").exists():
        raise SystemExit("labels already imported for this set: assign before labelling")
    rows = _read_jsonl(d / "sample.jsonl")
    out = assign(rows, coders, shared, seed)
    _write_jsonl(path, out)
    per = {c: sum(c in a["coders"] for a in out) for c in coders}
    meta = {"set": name, "assigned_at": now_utc().isoformat(), "seed": seed, "coders": coders,
            "shared": shared, "per_coder": per, "codebook_sha256": codebook_sha256()}
    (d / "assignment_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def assigned(lay: Layout, name: str) -> dict[str, set[str]] | None:
    """coder → assigned event_ids, or None when the set has no assignment."""
    rows = _read_jsonl(set_dir(lay, name) / "assignment.jsonl")
    if not rows:
        return None
    out: dict[str, set[str]] = defaultdict(set)
    for a in rows:
        for c in a["coders"]:
            out[c].add(a["event_id"])
    return dict(out)


def page(lay: Layout, name: str, coder: str | None = None) -> Path:
    rows = _read_jsonl(set_dir(lay, name) / "sample.jsonl")
    if not rows:
        raise SystemExit(f"no sample for set {name}: run `canopy-news labels draw` first")
    if coder is not None:
        mine = (assigned(lay, name) or {}).get(coder)
        if not mine:
            raise SystemExit(f"no articles assigned to {coder} in {name}")
        rows = [r for r in rows if r["event_id"] in mine]
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    ids = ", ".join(f"'{r['event_id']}'" for r in rows)
    text = {d["event_id"]: d for d in duckdb.sql(f"""SELECT event_id, title, lead, body,
            para_offsets, CAST(valid_time AS DATE)::VARCHAR AS day
        FROM read_parquet([{_listing(docs)}]) WHERE event_id IN ({ids})""")
        .to_arrow_table().to_pylist()}
    items = []
    for r in sorted(rows, key=lambda r: r["position"]):
        d = text[r["event_id"]]
        body = d["body"] or ""
        paras = [body[a:b] for a, b in (d["para_offsets"] or [[0, len(body)]])]
        items.append({"id": r["event_id"], "day": d["day"], "title": d["title"] or "",
                      "lead": d["lead"] or "", "paras": paras})
    html = (Path(__file__).parent / "labelling_page.html").read_text()
    data = {"set": name, "codebook_sha256": codebook_sha256(), "items": items,
            "codebook": CODEBOOK.read_text(), "coder": coder}
    out = lay.build_dir("labelling") / (f"{name}-{coder}.html" if coder else f"{name}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html.replace("/*__DATA__*/null",
                                json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    return out


def validate(label: dict, sample_ids: set[str],
             assignment: dict[str, set[str]] | None = None) -> str | None:
    if label.get("event_id") not in sample_ids:
        return "event_id not in sample"
    if assignment is not None and label["event_id"] not in assignment.get(label.get("coder"), ()):
        return "event_id not assigned to this coder"
    if not isinstance(label.get("in_scope"), bool):
        return "in_scope must be true or false"
    clauses = label.get("clauses")
    if not isinstance(clauses, list) or any(c not in (1, 2, 3, 4) for c in clauses):
        return "clauses must be a list of 1–4"
    if label["in_scope"] != bool(clauses):
        return "clauses must be non-empty exactly when in_scope"
    if label["in_scope"] and not label.get("evidence"):
        return "evidence required when in_scope"
    if label.get("confidence") not in CONFIDENCE:
        return "confidence must be high, medium or low"
    if not label.get("coder"):
        return "coder missing"
    return None


def import_labels(lay: Layout, name: str, export: Path) -> dict:
    """Merge a page export into labels.jsonl: the latest label per (event_id, coder) wins."""
    sample_ids = {r["event_id"] for r in _read_jsonl(set_dir(lay, name) / "sample.jsonl")}
    path = set_dir(lay, name) / "labels.jsonl"
    current = {(r["event_id"], r["coder"]): r for r in _read_jsonl(path)}
    plan = assigned(lay, name)
    errors, added = [], 0
    for i, lab in enumerate(_read_jsonl(export)):
        if (err := validate(lab, sample_ids, plan)) is not None:
            errors.append({"line": i + 1, "event_id": lab.get("event_id"), "error": err})
            continue
        lab["clauses"] = sorted(set(lab["clauses"]))
        key = (lab["event_id"], lab["coder"])
        old = current.get(key)
        if old is None or datetime.fromisoformat(lab["labelled_at"]) >= \
                datetime.fromisoformat(old["labelled_at"]):
            added += old is None
            current[key] = lab
    _write_jsonl(path, sorted(current.values(), key=lambda r: (r["event_id"], r["coder"])))
    out = {"labels": len(current), "new": added, "errors": errors,
           "remaining": len(sample_ids) - len({k[0] for k in current})}
    if plan is not None:
        out["per_coder"] = {c: {"labelled": sum(k[1] == c for k in current), "assigned": len(ids)}
                            for c, ids in sorted(plan.items())}
    return out
