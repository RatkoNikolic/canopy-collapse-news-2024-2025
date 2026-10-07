"""Embeddings: gemini-embedding-2 (768 dimensions) on the Gemini Batch API.

Decided 2026-10-04, replacing Qwen3-Embedding-8B on llama.cpp on the Mac host:
llama.cpp's Metal backend returned all-NaN vectors for many inputs (issue #29216;
656 of 1,000 documents) and the NaN-free settings were too slow for the corpus.

One model embeds every level the project uses (articles, passages, claims,
queries). gemini-embedding-2 takes its task as a text prefix, not a parameter:
documents are "title: … | text: …", queries "task: search result | query: …".
Below 3,072 dimensions it returns unit vectors already. Inputs go one Content
per text: a bare list of strings would be embedded as a single aggregate.

Documents go through the Batch API ($0.10 per 1M input tokens, half the
interactive price): `submit` writes JSONL request files (key = event_id),
uploads them and creates jobs; `collect` polls the jobs and writes the vectors
to builds/embeddings/<EMBED_VERSION>/documents/part-*.parquet. Job state lives
in batches/*.json next to the parts, so both steps resume after a crash and a
document is never submitted twice. `submit` refuses to go past the approved
budget, estimated from the characters sent and a measured
characters-per-token ratio. On Tier 1 the Batch API caps the tokens enqueued at
once (a 50M-token job was refused with 429), so `run` submits one ≈ 800k-token
batch at a time, collects it and repeats. Queries use the interactive endpoint.
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import CostRecord, Layout, Run, RunManifest
from chrono_harness.timeutil import now_utc

from canopy_news.config import CORPUS, load_env
from canopy_news.documents import doc_dir

MODEL = "gemini-embedding-2"
DIMS = 768
EMBED_VERSION = f"gemini-emb-2-d{DIMS}"
PRICE_PER_M = 0.10  # Batch API, text input, $/1M tokens (ai.google.dev pricing, 2026-10-04)
BODY_CHARS = 8000  # ≈ 2k tokens: past the median article, well inside the 8,192-token limit
MAX_TOKENS = 800_000  # per batch: Tier 1 caps tokens enqueued at once (≈ 0.5–1M observed)
MIN_TOKENS = 100_000
DONE_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}
DEAD_STATES = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def doc_text(title: str | None, lead: str | None, body: str | None) -> str:
    text = "\n".join(x for x in (lead, (body or "")[:BODY_CHARS]) if x)
    return f"title: {title or 'none'} | text: {text}"


def query_text(q: str) -> str:
    return f"task: search result | query: {q}"


def client():
    from google import genai
    load_env()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY missing: copy .env.example to .env and fill it in")
    return genai.Client(api_key=key)


def check_vector(v: list | None) -> list[float]:
    if not v or len(v) != DIMS or any(x is None or not math.isfinite(x) for x in v):
        raise ValueError(f"bad vector (length {len(v) if v else 0}, expected {DIMS}, or NaN)")
    return v


def embed_queries(cl, texts: list[str]) -> list[list[float]]:
    """Interactive embeddings for a few texts (queries, checks), one Content per text."""
    from google.genai import types
    res = cl.models.embed_content(
        model=MODEL, contents=[types.Content(parts=[types.Part(text=t)]) for t in texts],
        config=types.EmbedContentConfig(output_dimensionality=DIMS))
    return [check_vector(e.values) for e in res.embeddings]


def emb_dir(lay: Layout, level: str) -> Path:
    return lay.build_dir("embeddings") / EMBED_VERSION / level


def _listing(files: list[Path]) -> str:
    return ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)


def request_line(key: str, text: str) -> str:
    # an EmbedContentRequest in the API's own field names (not the SDK's `config`)
    return json.dumps({"key": key, "request": {"content": {"parts": [{"text": text}]},
                                               "output_dimensionality": DIMS}},
                      ensure_ascii=False)


def parse_output_line(line: str) -> tuple[str, list[float] | None, str | None]:
    """(key, vector, error) from one line of a batch output file."""
    rec = json.loads(line)
    key = rec.get("key")
    if rec.get("error"):
        return key, None, json.dumps(rec["error"])[:300]
    resp = rec.get("response") or {}
    emb = resp.get("embedding") or (resp.get("embeddings") or [None])[0] or {}
    try:
        return key, check_vector(emb.get("values")), None
    except ValueError as exc:
        return key, None, str(exc)


class Batches:
    """The job ledger: one JSON file per submitted request file."""

    def __init__(self, lay: Layout) -> None:
        self.dir = emb_dir(lay, "documents") / "batches"
        self.dir.mkdir(parents=True, exist_ok=True)

    def all(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.dir.glob("*.json"))]

    def save(self, b: dict) -> None:
        (self.dir / f"{b['id']}.json").write_text(json.dumps(b, indent=2) + "\n")


def embedded_ids(lay: Layout) -> set[str]:
    parts = sorted(emb_dir(lay, "documents").glob("part-*.parquet"))
    if not parts:
        return set()
    return {r[0] for r in duckdb.sql(
        f"SELECT event_id FROM read_parquet([{_listing(parts)}])").fetchall()}


def chars_per_token(lay: Layout, cl, sample: int = 200) -> float:
    """Measured once on a sample of documents (count_tokens is free) and kept."""
    path = emb_dir(lay, "documents") / "chars_per_token.json"
    if path.exists():
        return json.loads(path.read_text())["chars_per_token"]
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    rows = duckdb.sql(f"""SELECT title, lead, body FROM read_parquet([{_listing(docs)}])
        USING SAMPLE {sample} ROWS (reservoir, 7)""").fetchall()
    chars = tokens = 0
    for t, ld, b in rows:
        text = doc_text(t, ld, b)
        chars += len(text)
        tokens += cl.models.count_tokens(model=MODEL, contents=text).total_tokens
    ratio = chars / tokens
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"chars_per_token": ratio, "sample": len(rows), "chars": chars,
                                "tokens": tokens, "measured_at": now_utc().isoformat()}) + "\n")
    return ratio


def estimate_cost(chars: int, ratio: float) -> tuple[int, float]:
    tokens = round(chars / ratio)
    return tokens, tokens * PRICE_PER_M / 1e6


def committed_cost(batches: list[dict]) -> float:
    """Estimated spend of every batch that is or may be billed (all but dead ones)."""
    return sum(b["est_cost_usd"] for b in batches if b["state"] not in DEAD_STATES)


def token_chunks(texts: list[tuple[str, str]], ratio: float,
                 max_tokens: int) -> list[list[tuple[str, str]]]:
    """Consecutive chunks whose estimated tokens stay within max_tokens (the Batch API
    caps the tokens enqueued at once per account tier); a single longer text is alone."""
    chunks, cur, cur_tok = [], [], 0
    for k, t in texts:
        tok = len(t) / ratio
        if cur and cur_tok + tok > max_tokens:
            chunks.append(cur)
            cur, cur_tok = [], 0
        cur.append((k, t))
        cur_tok += tok
    return chunks + ([cur] if cur else [])


def submit(lay: Layout, *, limit: int | None = None, budget_usd: float = 25.0,
           max_tokens: int = MAX_TOKENS, max_jobs: int | None = None) -> dict:
    cl = client()
    ledger = Batches(lay)
    batches = ledger.all()
    pending = {k for b in batches if b["state"] not in DEAD_STATES and not b["collected"]
               for k in b["keys"]}
    skip = embedded_ids(lay) | pending
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    if not docs:  # e.g. right after an extractor bump, before the documents stage has run
        return {"submitted": 0, "remaining": 0}
    rows = [r for r in duckdb.sql(f"""SELECT event_id, title, lead, body
        FROM read_parquet([{_listing(docs)}]) WHERE error IS NULL AND length(body) > 0
        ORDER BY event_id""").fetchall() if r[0] not in skip]
    rows = rows[:limit] if limit is not None else rows
    if not rows:
        return {"submitted": 0, "remaining": 0}
    ratio = chars_per_token(lay, cl)
    texts = [(r[0], doc_text(r[1], r[2], r[3])) for r in rows]
    chunks = token_chunks(texts, ratio, max_tokens)[:max_jobs]
    req_dir = emb_dir(lay, "documents") / "requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for chunk in chunks:
        f_tok, f_cost = estimate_cost(sum(len(t) for _, t in chunk), ratio)
        already = committed_cost(ledger.all())
        if already + f_cost > budget_usd:
            raise SystemExit(f"over budget: ${already:.2f} committed + ${f_cost:.2f} estimated "
                             f"> ${budget_usd:.2f} approved; ask before raising --budget")
        bid = f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        path = req_dir / f"{bid}.jsonl"
        path.write_text("".join(request_line(k, t) + "\n" for k, t in chunk), encoding="utf-8")
        try:
            uploaded = cl.files.upload(file=str(path), config={"display_name": bid,
                                                                "mime_type": "jsonl"})
            job = cl.batches.create_embeddings(model=MODEL, src={"file_name": uploaded.name},
                                               config={"display_name": bid})
        except Exception:
            path.unlink(missing_ok=True)  # no job, nothing billed: leave no trace to resume
            raise
        b = {"id": bid, "job": job.name, "model": MODEL, "dims": DIMS, "requests": str(path),
             "input_file": uploaded.name, "n": len(chunk), "keys": [k for k, _ in chunk],
             "est_tokens": f_tok, "est_cost_usd": round(f_cost, 4), "chars_per_token": ratio,
             "state": job.state.name if job.state else "JOB_STATE_PENDING",
             "submitted_at": now_utc().isoformat(), "collected": False}
        ledger.save(b)
        out.append({k: b[k] for k in ("id", "job", "n", "est_tokens", "est_cost_usd", "state")})
    submitted = sum(len(c) for c in chunks)
    return {"submitted": submitted, "remaining": len(texts) - submitted,
            "committed_est_usd": round(committed_cost(ledger.all()), 2), "jobs": out}


def _quota_error(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


def run(lay: Layout, *, budget_usd: float = 25.0, max_tokens: int = MAX_TOKENS,
        follow: bool = False, poll_s: int = 60, idle_s: int = 1800) -> None:
    """One batch at a time: collect finished jobs, submit the next chunk, wait.
    A quota refusal shrinks the chunk and waits; with `follow`, an empty queue waits
    for the documents stage while a fetch or discovery is still running."""
    import subprocess
    size = max_tokens
    while True:
        rep = collect(lay)
        if any(not b["collected"] and b["state"] not in DEAD_STATES for b in Batches(lay).all()):
            time.sleep(poll_s)
            continue
        if rep["jobs"]:
            print(json.dumps({"at": now_utc().isoformat(), "collected": rep["jobs"],
                              "embedded_total": rep["embedded_total"],
                              "committed_est_usd": rep["committed_est_usd"]}), flush=True)
        try:
            res = submit(lay, budget_usd=budget_usd, max_tokens=size, max_jobs=1)
        except Exception as exc:
            if not _quota_error(exc):
                raise
            size = max(MIN_TOKENS, int(size * 0.7))
            print(json.dumps({"at": now_utc().isoformat(), "quota": True,
                              "next_max_tokens": size}), flush=True)
            time.sleep(300)
            continue
        if res["submitted"]:
            print(json.dumps({"at": now_utc().isoformat(), "submitted": res["jobs"],
                              "remaining": res["remaining"]}), flush=True)
            continue
        def busy() -> bool:
            return subprocess.run(["pgrep", "-f", "[b]in/canopy-news (fetch|discover|documents)"],
                                  capture_output=True).returncode == 0
        if follow and not busy():  # a fetch restart leaves a gap of seconds: look again
            time.sleep(120)
        if not (follow and busy()):
            print(json.dumps({"at": now_utc().isoformat(), "done": True,
                              "embedded_total": rep["embedded_total"]}), flush=True)
            return
        time.sleep(idle_s)


def _write(out_dir: Path, rows: list[dict]) -> None:
    schema = pa.schema([("event_id", pa.string()), ("outlet_id", pa.string()),
                        ("vector", pa.list_(pa.float32(), DIMS))])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema),
                   out_dir / f"part-{uuid.uuid4().hex[:12]}.parquet", compression="zstd")


def collect(lay: Layout) -> dict:
    """Poll every uncollected job; write the vectors of finished ones."""
    cl = client()
    ledger = Batches(lay)
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    report = []
    for b in ledger.all():
        if b["collected"] or b["state"] in DEAD_STATES:
            continue
        job = cl.batches.get(name=b["job"])
        b["state"] = job.state.name
        if b["state"] in DONE_STATES:
            raw = cl.files.download(file=job.dest.file_name)
            vecs, errors = {}, []
            for line in raw.decode("utf-8").splitlines():
                if line.strip():
                    key, v, err = parse_output_line(line)
                    if v is not None:
                        vecs[key] = v
                    else:
                        errors.append({"key": key, "error": err})
            outlet = dict(duckdb.sql(f"""SELECT event_id, outlet_id
                FROM read_parquet([{_listing(docs)}])""").fetchall()) if docs else {}
            rows = [{"event_id": k, "outlet_id": outlet.get(k), "vector": v}
                    for k, v in vecs.items()]
            if rows:
                _write(emb_dir(lay, "documents"), rows)
            manifest = RunManifest(
                kind="build", corpus=CORPUS, adapter="embeddings/documents",
                adapter_version=EMBED_VERSION, storage_backend="files",
                models={"embedder": MODEL},
                params={"batch_id": b["id"], "job": b["job"], "dims": DIMS,
                        "body_chars": BODY_CHARS, "requests": b["n"], "embedded": len(rows),
                        "errors": len(errors), "price_per_m": PRICE_PER_M,
                        "tokens_estimated_from_chars": True})
            with Run(lay.runs, manifest, label="embed-documents") as run:
                run.record_cost(CostRecord(stage="embed", model=MODEL, calls=b["n"],
                                           input_tokens=b["est_tokens"],
                                           cost_usd=b["est_cost_usd"]))
                (run.dir / "errors.jsonl").write_text(
                    "".join(json.dumps(e) + "\n" for e in errors))
            b |= {"collected": True, "collected_at": now_utc().isoformat(),
                  "embedded": len(rows), "errors": len(errors)}
        ledger.save(b)
        report.append({k: b.get(k) for k in ("id", "state", "n", "embedded", "errors")})
    batches = ledger.all()
    return {"jobs": report, "committed_est_usd": round(committed_cost(batches), 2),
            "embedded_total": len(embedded_ids(lay))}


def status(lay: Layout) -> dict:
    batches = Batches(lay).all()
    by_state: dict[str, int] = {}
    for b in batches:
        by_state[b["state"]] = by_state.get(b["state"], 0) + b["n"]
    oldest = min((datetime.fromisoformat(b["submitted_at"]) for b in batches
                  if not b["collected"]), default=None)
    return {"requests_by_state": by_state, "embedded": len(embedded_ids(lay)),
            "committed_est_usd": round(committed_cost(batches), 2),
            "oldest_uncollected": oldest.isoformat() if oldest else None}
