"""Relevance stage 3: the codebook classifier (PROTOCOL.md §5.4).

The prompt is the frozen codebook (CODEBOOK.md) as the system message
and the article as the coders see it on the labelling page: title, date, lead and
numbered body paragraphs, never the outlet or the URL. The answer is the codebook's
output object, enforced by a JSON schema. Arms are named model settings so a run
manifest records the exact model id and thinking setting of every decision.

The run (`canopy-news classify run`) sends every lexicon candidate and band-top10 article
through the Message Batches API with the protocol's arm (`sonnet`): batches go out one at a
time, each ≤ 200 MB; before each, the spend so far (from the usage of collected results) is
projected to the whole run, and the run stops rather than exceed the approved budget. State
lives in builds/classify/<run>/: batches.jsonl (the ledger), ids/<batch>.json, part-*.parquet
(one row per decision), manifest.json. A second run over the gold articles (`--run repeat
--gold-set gold-v1`) measures stability (PROTOCOL.md §6.4).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Layout
from chrono_harness.timeutil import now_utc

from canopy_news import embeddings, lexicon
from canopy_news.documents import doc_dir

from canopy_news.labels import CODEBOOK, _read_jsonl, codebook_sha256, set_dir

INSTRUCTION = (
    "You classify Serbian news articles for a research corpus. Apply the codebook below "
    "exactly as written: it is the same text human coders use. The article follows in "
    "the user message (title, date, lead, numbered body paragraphs). Answer only with "
    "the codebook's output object; `evidence` is a paragraph number such as \"p3\", or "
    "\"headline\".\n\n"
)

SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "clauses": {"type": "array", "items": {"type": "integer", "enum": [1, 2, 3, 4]}},
        "evidence": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["in_scope", "clauses", "evidence", "confidence"],
    "additionalProperties": False,
}

# $/1M tokens, standard (batch = half): input, output (Anthropic table 2026-09-25)
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5-5": (2.0, 10.0)}
CACHE_READ = 0.10
CACHE_WRITE = {"5m": 1.25, "1h": 2.0}
RUN_ARM = "sonnet"            # the protocol's classifier (PROTOCOL.md §5.4)
RUN_STRATA = ("candidate", "band-top10")
BATCH_BYTES = 200_000_000     # under the API's 256 MB per batch
MAX_ATTEMPTS = 3              # an article that fails this often is reported, not resent
EST_PER_ARTICLE = 0.0025      # $ per article, batch, from the pilot (scripts/cost_model.py)
MIN_MEASURED = 1000           # decided articles before the measured cost drives the projection


@dataclass(frozen=True)
class Arm:
    name: str
    model: str
    params: dict = field(default_factory=dict)


ARMS = {
    "haiku": Arm("haiku", "claude-haiku-4-5", {"temperature": 0}),
    # Sonnet 5.5 rejects non-default sampling parameters; `between_tools` is its no-thinking setting
    "sonnet": Arm("sonnet", "claude-sonnet-5-5", {"thinking": {"type": "between_tools"}}),
    "sonnet-think-low": Arm("sonnet-think-low", "claude-sonnet-5-5",
                            {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}),
}


def system_prompt() -> str:
    return INSTRUCTION + CODEBOOK.read_text(encoding="utf-8")


def article_text(doc: dict) -> str:
    body = doc["body"] or ""
    paras = [body[a:b].strip() for a, b in (doc["para_offsets"] or [[0, len(body)]])]
    lines = [f"Title: {doc['title'] or ''}", f"Date: {doc['day']}", f"Lead: {doc['lead'] or ''}", ""]
    lines += [f"[p{i}] {p}" for i, p in enumerate((p for p in paras if p), 1)]
    return "\n".join(lines)


def request(arm: Arm, doc: dict, cache_ttl: str = "5m") -> dict:
    """Messages API parameters for one article (also the `params` of a batch request)."""
    output_config = {"format": {"type": "json_schema", "schema": SCHEMA},
                     **arm.params.get("output_config", {})}
    extra = {k: v for k, v in arm.params.items() if k != "output_config"}
    return {"model": arm.model, "max_tokens": 4000,
            "system": [{"type": "text", "text": system_prompt(),
                        "cache_control": ({"type": "ephemeral"} if cache_ttl == "5m" else
                                          {"type": "ephemeral", "ttl": cache_ttl})}],
            "messages": [{"role": "user", "content": article_text(doc)}],
            "output_config": output_config, **extra}


def parse(message) -> dict:
    text = next(b.text for b in message.content if b.type == "text")
    return json.loads(text)


def cost(model: str, usage, *, batch: bool = False, cache_ttl: str = "5m") -> float:
    pin, pout = PRICES[model]
    full = (usage.input_tokens * pin
            + (usage.cache_read_input_tokens or 0) * pin * CACHE_READ
            + (usage.cache_creation_input_tokens or 0) * pin * CACHE_WRITE[cache_ttl]
            + usage.output_tokens * pout) / 1e6
    return full / 2 if batch else full


def manifest(arms: list[Arm]) -> dict:
    return {"codebook_sha256": codebook_sha256(), "schema": SCHEMA,
            "arms": {a.name: {"model": a.model, **a.params} for a in arms}}


# ---- the batch run -------------------------------------------------------------------

def run_dir(lay: Layout, run: str) -> Path:
    return lay.build_dir("classify") / run


def _listing(files) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def targets(lay: Layout, ids: set[str] | None = None) -> list[dict]:
    """Corpus articles in the classifier's strata (or exactly `ids`), in event_id order."""
    lex_ver = lexicon.version(lexicon.load())
    band = lay.build_dir("scope") / f"band-{lex_ver}-{embeddings.EMBED_VERSION}.parquet"
    strata = ", ".join(f"'{x}'" for x in RUN_STRATA)
    rows = duckdb.sql(f"""SELECT d.event_id, d.title, d.lead, d.body, d.para_offsets,
        CAST(d.valid_time AS DATE)::VARCHAR AS day, b.stratum
        FROM read_parquet([{_listing(sorted(doc_dir(lay).glob('part-*.parquet')))}]) d
        JOIN read_parquet('{band}') b USING (event_id)
        WHERE d.error IS NULL AND b.stratum IN ({strata})
        ORDER BY d.event_id""").to_arrow_table().to_pylist()
    return [r for r in rows if ids is None or r["event_id"] in ids]


def _ledger(d: Path) -> list[dict]:
    return _read_jsonl(d / "batches.jsonl")


def _append(path: Path, row: dict) -> None:
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def results(d: Path) -> list[dict]:
    parts = sorted(d.glob("part-*.parquet"))
    if not parts:
        return []
    return duckdb.sql(f"SELECT * FROM read_parquet([{_listing(parts)}])").to_arrow_table().to_pylist()


def _state(d: Path) -> dict:
    """Decided ids, ids in flight, spend so far and per decided article."""
    rows = results(d)
    decided = {r["event_id"] for r in rows if r["status"] == "succeeded"}
    collected = {b["batch_id"] for b in _ledger(d) if b.get("collected")}
    flight = set()
    for b in _ledger(d):
        if b["batch_id"] not in collected:
            flight |= set(json.loads((d / "ids" / f"{b['batch_id']}.json").read_text()))
    failed: dict[str, int] = {}
    for r in rows:
        if r["status"] != "succeeded":
            failed[r["event_id"]] = failed.get(r["event_id"], 0) + 1
    given_up = {i for i, n in failed.items() if n >= MAX_ATTEMPTS} - decided
    spent = sum(r["cost_usd"] or 0 for r in rows)
    per = spent / len(decided) if decided else None
    return {"decided": decided, "flight": flight, "given_up": given_up, "spent": spent,
            "per_article": per, "rows": len(rows)}


def submit(lay: Layout, run: str, *, budget: float, ids: set[str] | None = None,
           limit: int | None = None, client=None, cache_ttl: str = "1h") -> dict:
    """Send the next batch of undecided articles, if the projected spend stays in budget."""
    import anthropic
    d = run_dir(lay, run)
    (d / "ids").mkdir(parents=True, exist_ok=True)
    arm = ARMS[RUN_ARM]
    todo_all = targets(lay, ids)
    if not (d / "manifest.json").exists():
        (d / "manifest.json").write_text(json.dumps({
            **manifest([arm]), "run": run, "strata": list(RUN_STRATA), "targets": len(todo_all),
            "cache_ttl": cache_ttl, "budget_usd": budget, "api": "Message Batches",
            "created": now_utc().isoformat()}, indent=2) + "\n")
    st = _state(d)
    todo = [r for r in todo_all
            if r["event_id"] not in st["decided"] | st["flight"] | st["given_up"]]
    if limit is not None:
        todo = todo[:limit]
    if not todo:
        return {"submitted": 0, "left": 0, "spent_usd": round(st["spent"], 2)}
    # projection: the measured cost per article once it rests on enough articles (a small first
    # batch is dominated by its one cache write), else the pilot-based estimate
    per = st["per_article"] if len(st["decided"]) >= MIN_MEASURED else EST_PER_ARTICLE
    projected = st["spent"] + per * (len(todo_all) - len(st["decided"]))
    if projected > budget:
        raise SystemExit(f"projected spend ${projected:,.2f} exceeds the approved ${budget:,.2f}; "
                         f"spent ${st['spent']:,.2f} on {len(st['decided'])} articles")
    reqs, size = [], 0
    for r in todo:
        params = request(arm, r, cache_ttl)
        n = len(json.dumps(params, ensure_ascii=False).encode()) + 100
        if reqs and (size + n > BATCH_BYTES or len(reqs) >= 100_000):
            break
        reqs.append({"custom_id": r["event_id"], "params": params})
        size += n
    client = client or anthropic.Anthropic()
    batch = client.messages.batches.create(requests=reqs)
    (d / "ids" / f"{batch.id}.json").write_text(json.dumps([q["custom_id"] for q in reqs]))
    _append(d / "batches.jsonl", {"batch_id": batch.id, "n": len(reqs), "bytes": size,
                                  "submitted_at": now_utc().isoformat()})
    return {"submitted": len(reqs), "batch_id": batch.id, "left": len(todo) - len(reqs),
            "spent_usd": round(st["spent"], 2), "projected_usd": round(projected, 2)}


def _row(run: str, res, cache_ttl: str) -> dict:
    row = {"event_id": res.custom_id, "run": run, "status": res.result.type, "model": None,
           "in_scope": None, "clauses": None, "evidence": None, "confidence": None,
           "stop_reason": None, "input_tokens": None, "cache_read": None, "cache_write": None,
           "output_tokens": None, "cost_usd": 0.0, "error": None,
           "collected_at": now_utc().isoformat()}
    if res.result.type != "succeeded":
        err = getattr(res.result, "error", None)
        row["error"] = str(getattr(getattr(err, "error", err), "type", err))[:200]
        return row
    m = res.result.message
    u = m.usage
    row.update({"model": m.model, "stop_reason": m.stop_reason, "input_tokens": u.input_tokens,
                "cache_read": u.cache_read_input_tokens or 0,
                "cache_write": u.cache_creation_input_tokens or 0,
                "output_tokens": u.output_tokens,
                "cost_usd": cost(RUN_ARM_MODEL, u, batch=True, cache_ttl=cache_ttl)})
    try:
        dec = parse(m)
        row.update({"in_scope": bool(dec["in_scope"]), "clauses": sorted(set(dec["clauses"])),
                    "evidence": dec["evidence"], "confidence": dec["confidence"]})
    except (StopIteration, ValueError, KeyError) as e:
        row.update({"status": "unparsed", "error": f"{type(e).__name__}: {m.stop_reason}"})
    return row


RUN_ARM_MODEL = ARMS[RUN_ARM].model
RESULT_SCHEMA = pa.schema([
    ("event_id", pa.string()), ("run", pa.string()), ("status", pa.string()),
    ("model", pa.string()), ("in_scope", pa.bool_()), ("clauses", pa.list_(pa.int64())),
    ("evidence", pa.string()), ("confidence", pa.string()), ("stop_reason", pa.string()),
    ("input_tokens", pa.int64()), ("cache_read", pa.int64()), ("cache_write", pa.int64()),
    ("output_tokens", pa.int64()), ("cost_usd", pa.float64()), ("error", pa.string()),
    ("collected_at", pa.string())])


def collect(lay: Layout, run: str, client=None) -> dict:
    """Write the results of every ended batch; errored or unparsed rows get resubmitted."""
    import anthropic
    d = run_dir(lay, run)
    client = client or anthropic.Anthropic()
    ttl = json.loads((d / "manifest.json").read_text()).get("cache_ttl", "5m")
    out = {"collected": 0, "waiting": 0}
    ledger = _ledger(d)
    done = {b["batch_id"] for b in ledger if b.get("collected")}
    for b in ledger:
        if b.get("collected") or b["batch_id"] in done:
            continue
        batch = client.messages.batches.retrieve(b["batch_id"])
        if batch.processing_status != "ended":
            out["waiting"] += 1
            continue
        rows = [_row(run, r, ttl) for r in client.messages.batches.results(b["batch_id"])]
        pq.write_table(pa.Table.from_pylist(rows, schema=RESULT_SCHEMA),
                       d / f"part-{uuid.uuid4().hex[:12]}.parquet", compression="zstd")
        _append(d / "batches.jsonl", {**b, "collected": now_utc().isoformat(),
                                      "rows": len(rows)})
        done.add(b["batch_id"])
        out["collected"] += 1
    return {**out, **status(lay, run)}


def status(lay: Layout, run: str) -> dict:
    d = run_dir(lay, run)
    if not (d / "manifest.json").exists():
        return {"run": run, "started": False}
    st = _state(d)
    rows = results(d)
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    return {"run": run, "targets": json.loads((d / "manifest.json").read_text())["targets"],
            "decided": len(st["decided"]), "in_flight": len(st["flight"]),
            "given_up": len(st["given_up"]),
            "result_rows": by, "spent_usd": round(st["spent"], 2),
            "per_article_usd": round(st["per_article"], 5) if st["per_article"] else None}


def gold_ids(lay: Layout, gold_set: str) -> set[str]:
    return {r["event_id"] for r in _read_jsonl(set_dir(lay, gold_set) / "sample.jsonl")}


def follow(lay: Layout, run: str, *, budget: float, ids: set[str] | None = None,
           poll: int = 120) -> dict:
    """Submit, wait, collect, until every target has a decision (one batch in flight)."""
    while True:
        st = collect(lay, run) if _ledger(run_dir(lay, run)) else status(lay, run)
        if st.get("in_flight", 0) == 0:
            sub = submit(lay, run, budget=budget, ids=ids)
            print(json.dumps({"time": now_utc().isoformat(), **sub}), flush=True)
            if sub["submitted"] == 0:
                return status(lay, run)
        time.sleep(poll)
