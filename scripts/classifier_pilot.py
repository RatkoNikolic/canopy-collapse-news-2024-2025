#!/usr/bin/env python3
"""Classifier pilot: the same random articles through each arm (Messages API, standard
price), to compare models before the full batch run. Articles come from the lexicon
candidates and band-top10, never from a gold sample. Stops before the cost cap.

    uv run python scripts/classifier_pilot.py --n-candidates 40 --n-band 20 --cap 3
Output: builds/pilot/<name>/{sample,results}.jsonl + manifest.json
"""

from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor

import anthropic
import duckdb
from chrono_harness import Layout

from canopy_news import classify, embeddings, lexicon
from canopy_news.config import repo_root
from canopy_news.documents import doc_dir
from canopy_news.labels import _listing, _read_jsonl
from chrono_harness.timeutil import now_utc


def sample(lay: Layout, n_cand: int, n_band: int, seed: int) -> list[dict]:
    bands = lay.build_dir("scope") / (
        f"band-{lexicon.version(lexicon.load())}-{embeddings.EMBED_VERSION}.parquet")
    gold = {r["event_id"] for p in (lay.gold / "scope_labels").glob("*/sample.jsonl")
            for r in _read_jsonl(p)}
    docs = sorted(doc_dir(lay).glob("part-*.parquet"))
    rows = duckdb.sql(f"""SELECT d.event_id, d.outlet_id, b.stratum, d.title, d.lead, d.body,
        d.para_offsets, CAST(d.valid_time AS DATE)::VARCHAR AS day
        FROM read_parquet([{_listing(docs)}]) d JOIN read_parquet('{bands}') b USING (event_id)
        WHERE b.stratum IN ('candidate', 'band-top10') AND d.error IS NULL
        ORDER BY d.event_id""").to_arrow_table().to_pylist()
    rows = [r for r in rows if r["event_id"] not in gold]
    rng = random.Random(seed)
    out = []
    for stratum, n in (("candidate", n_cand), ("band-top10", n_band)):
        out += rng.sample([r for r in rows if r["stratum"] == stratum], n)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="classifier-2026-10-06")
    ap.add_argument("--n-candidates", type=int, default=40)
    ap.add_argument("--n-band", type=int, default=20)
    ap.add_argument("--arms", default="haiku,sonnet,sonnet-think-low")
    ap.add_argument("--cap", type=float, default=3.0, help="USD; stop before exceeding")
    ap.add_argument("--seed", type=int, default=20261006)
    args = ap.parse_args()
    lay = Layout(repo_root())
    out = lay.build_dir("pilot") / args.name
    out.mkdir(parents=True, exist_ok=True)
    arms = [classify.ARMS[a] for a in args.arms.split(",")]
    docs = sample(lay, args.n_candidates, args.n_band, args.seed)
    (out / "sample.jsonl").write_text("".join(json.dumps(
        {"event_id": d["event_id"], "outlet_id": d["outlet_id"], "stratum": d["stratum"]}) + "\n"
        for d in docs))
    (out / "manifest.json").write_text(json.dumps(
        {**classify.manifest(arms), "started": now_utc().isoformat(), "n": len(docs),
         "seed": args.seed, "cap_usd": args.cap}, indent=2))
    client = anthropic.Anthropic()
    spent, results = 0.0, []
    for arm in arms:
        # one warm-up call writes the cached system prompt before the parallel calls read it
        def run(d, arm=arm):
            req = classify.request(arm, d)
            if "temperature" in req:   # SDK 1.x dropped it from the signature; Haiku 4.5 honours it
                req["extra_body"] = {"temperature": req.pop("temperature")}
            m = client.messages.create(**req)
            return {"event_id": d["event_id"], "arm": arm.name, "model": m.model,
                    "decision": classify.parse(m), "usage": m.usage.model_dump(),
                    "cost": classify.cost(arm.model, m.usage)}
        first = run(docs[0])
        rest = []
        with ThreadPoolExecutor(6) as pool:
            for r in pool.map(run, docs[1:]):
                rest.append(r)
        arm_rows = [first] + rest
        spent += sum(r["cost"] for r in arm_rows)
        results += arm_rows
        print(f"{arm.name:18s} {len(arm_rows)} articles  ${sum(r['cost'] for r in arm_rows):.3f}"
              f"  (total ${spent:.3f})", flush=True)
        with (out / "results.jsonl").open("w") as fh:
            fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in results)
        if spent >= args.cap:
            raise SystemExit(f"cost cap ${args.cap} reached after arm {arm.name}")
    print(json.dumps({"spent_usd": round(spent, 4), "out": str(out)}))


if __name__ == "__main__":
    main()
