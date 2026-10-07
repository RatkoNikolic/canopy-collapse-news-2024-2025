"""Validation of the scope layer against the gold set (PROTOCOL.md §6.3–6.4).

    canopy-news validate --set gold-v1     → builds/validation/<set>.json

- Gold label per article: the coder's label; on the shared articles, the majority of three.
- Agreement: Krippendorff's alpha (nominal) on the shared articles, for scope and per clause.
- Pipeline decision per gold article: the classifier's decision if the article is in a stratum
  the classifier reads (PROTOCOL.md §5.4), otherwise out.
- Precision and recall: design-weighted (each article weighs N_h / n_h of its stratum × outlet
  cell), overall and per outlet, with 95% intervals from a stratified bootstrap (resampling
  within each cell).
- Extension rule: the estimated share of all in-scope articles in band-next20 and in rest; a
  stratum above 5% is to be classified too.
- Stability: agreement of the main and the repeat classifier runs on the gold articles both
  decided, with a Wilson interval.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict

from chrono_harness import Layout

from canopy_news import classify
from canopy_news.labels import _read_jsonl, set_dir

EXTEND_SHARE = 0.05
BOOTSTRAP = 2000


def alpha_nominal(units: list[list]) -> float | None:
    """Krippendorff's alpha for nominal data; `units` holds each unit's values (≥ 2 to count)."""
    coinc: Counter = Counter()
    for vals in units:
        m = len(vals)
        if m < 2:
            continue
        for i, a in enumerate(vals):
            for j, b in enumerate(vals):
                if i != j:
                    coinc[(a, b)] += 1 / (m - 1)
    n_c: Counter = Counter()
    for (a, _), v in coinc.items():
        n_c[a] += v
    n = sum(n_c.values())
    if n <= 1:
        return None
    d_o = sum(v for (a, b), v in coinc.items() if a != b)
    d_e = sum(n_c[a] * n_c[b] for a in n_c for b in n_c if a != b) / (n - 1)
    return 1.0 if d_e == 0 else 1 - d_o / d_e


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def gold_labels(sample: list[dict], labels: list[dict], assignment: list[dict]) -> dict:
    """event_id → final gold label {in_scope, clauses}; shared articles by majority of three."""
    by: dict[str, list[dict]] = defaultdict(list)
    for lab in labels:
        by[lab["event_id"]].append(lab)
    shared = {a["event_id"] for a in assignment if a["shared"]}
    out = {}
    for r in sample:
        labs = by.get(r["event_id"], [])
        if not labs:
            continue
        if r["event_id"] in shared:
            if len(labs) < 3:
                continue  # incomplete: the shared articles need all three coders
            yes = sum(lab["in_scope"] for lab in labs)
            ins = yes >= 2
            votes = Counter(c for lab in labs if lab["in_scope"] for c in lab["clauses"])
            out[r["event_id"]] = {"in_scope": ins,
                                  "clauses": sorted(c for c, k in votes.items() if k >= 2) if ins
                                  else []}
        else:
            lab = labs[-1]
            out[r["event_id"]] = {"in_scope": lab["in_scope"], "clauses": lab["clauses"]}
    return out


def _estimate(rows: list[dict]) -> dict:
    tp = sum(r["w"] for r in rows if r["gold"] and r["pred"])
    pred = sum(r["w"] for r in rows if r["pred"])
    gold = sum(r["w"] for r in rows if r["gold"])
    return {"precision": tp / pred if pred else None, "recall": tp / gold if gold else None,
            "est_in_scope": gold}


def _bootstrap(rows: list[dict], seed: int = 1) -> dict:
    cells: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cells[r["cell"]].append(r)
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {"precision": [], "recall": []}
    for _ in range(BOOTSTRAP):
        res = [rng.choice(c) for c in cells.values() for _ in c]
        est = _estimate(res)
        for k in draws:
            if est[k] is not None:
                draws[k].append(est[k])
    out = {}
    for k, v in draws.items():
        v.sort()
        out[k] = (v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]) if v else None
    return out


def _with_ci(rows: list[dict]) -> dict:
    est = _estimate(rows)
    ci = _bootstrap(rows)
    return {"n": len(rows), "precision": est["precision"], "precision_ci": ci["precision"],
            "recall": est["recall"], "recall_ci": ci["recall"]}


def evaluate(sample: list[dict], gold: dict, main: dict, repeat: dict | None = None,
             labels: list[dict] | None = None, assignment: list[dict] | None = None) -> dict:
    """`main` / `repeat`: event_id → classifier decision (bool) of each run."""
    rows = []
    for r in sample:
        if r["event_id"] not in gold:
            continue
        stratum, outlet = r["stratum"].split(":")
        read = stratum in classify.RUN_STRATA
        rows.append({"event_id": r["event_id"], "cell": r["stratum"], "stratum": stratum,
                     "outlet": outlet, "w": r["weight"], "gold": gold[r["event_id"]]["in_scope"],
                     "pred": bool(read and main.get(r["event_id"])),
                     "undecided": read and r["event_id"] not in main})
    out = {"labelled": len(rows), "of": len(sample),
           "undecided_by_classifier": sum(r["undecided"] for r in rows),
           "overall": _with_ci(rows),
           "per_outlet": {o: _with_ci([r for r in rows if r["outlet"] == o])
                          for o in sorted({r["outlet"] for r in rows})}}
    total = sum(r["w"] for r in rows if r["gold"])
    out["extension_rule"] = {}
    for st in ("band-next20", "rest"):
        est = sum(r["w"] for r in rows if r["gold"] and r["stratum"] == st)
        share = est / total if total else None
        out["extension_rule"][st] = {"est_in_scope": round(est), "share": share,
                                     "extend": share is not None and share > EXTEND_SHARE}
    if labels is not None and assignment is not None:
        shared = {a["event_id"] for a in assignment if a["shared"]}
        by: dict[str, list[dict]] = defaultdict(list)
        for lab in labels:
            if lab["event_id"] in shared:
                by[lab["event_id"]].append(lab)
        units = list(by.values())
        out["agreement"] = {"shared_units": len(units),
                            "alpha_scope": alpha_nominal([[x["in_scope"] for x in u]
                                                          for u in units])}
        for c in (1, 2, 3, 4):
            out["agreement"][f"alpha_clause_{c}"] = alpha_nominal(
                [[c in x["clauses"] for x in u] for u in units])
    if repeat is not None:
        both = [e for e in main if e in repeat and e in gold]
        k = sum(main[e] == repeat[e] for e in both)
        out["stability"] = {"n": len(both), "agree": k, "share": k / len(both) if both else None,
                            "ci": wilson(k, len(both))}
    return out


def decisions(lay: Layout, run: str) -> dict[str, bool]:
    rows = classify.results(classify.run_dir(lay, run))
    return {r["event_id"]: bool(r["in_scope"]) for r in rows if r["status"] == "succeeded"}


def run(lay: Layout, name: str) -> dict:
    d = set_dir(lay, name)
    sample, assignment = _read_jsonl(d / "sample.jsonl"), _read_jsonl(d / "assignment.jsonl")
    labels = _read_jsonl(d / "labels.jsonl")
    gold = gold_labels(sample, labels, assignment)
    rep_dir = classify.run_dir(lay, "repeat")
    repeat = decisions(lay, "repeat") if rep_dir.exists() else None
    out = evaluate(sample, gold, decisions(lay, "main"), repeat, labels, assignment)
    path = lay.build_dir("validation") / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    return out
