"""canopy-news — collection commands.

    canopy-news dumps    [--start 2024-11-01] [--end <yesterday>]
    canopy-news discover [--start ...] [--end ...]
    canopy-news fetch    --window story-v01 [--limit N] [--min-interval 2.0]
    canopy-news status
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime

from chrono_harness import EventLog

from canopy_news import mediacloud, naslovi, rtslist, sitemaps
from canopy_news.discovery import discovery_files, load_routes
from canopy_news.config import CORPUS, WINDOWS, exclusive, layout
from canopy_news.fetch import run_pass
from canopy_news.registry import Registry


def _date(s: str) -> date:
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="canopy-news")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dumps", help="download Media Cloud daily dumps into raw/")
    d.add_argument("--start", type=_date, default=WINDOWS["story-v01"].start)
    d.add_argument("--end", type=_date, default=WINDOWS["story-v01"].end)

    s = sub.add_parser("discover", help="build discovery tables (dumps, sitemaps, naslovi.net)")
    s.add_argument("--route", choices=["mediacloud", "sitemaps", "naslovi", "rtslist", "idprobe", "all"],
                   default="all")
    s.add_argument("--start", type=_date, default=WINDOWS["story-v01"].start)
    s.add_argument("--end", type=_date, default=WINDOWS["story-v01"].end)
    s.add_argument("--window", choices=sorted(WINDOWS), help="use a window's dates")
    s.add_argument("--refresh", action="store_true", help="naslovi: redo days already written")

    f = sub.add_parser("fetch", help="one collection pass over a window")
    f.add_argument("--window", choices=sorted(WINDOWS), required=True)
    f.add_argument("--limit", type=int)
    f.add_argument("--min-interval", type=float, default=2.0)

    dc = sub.add_parser("documents", help="fetched pages → clean article records")
    dc.add_argument("--window", choices=sorted(WINDOWS), default="story-v01")
    dc.add_argument("--workers", type=int, default=4)

    vf = sub.add_parser("verify", help="refetch a sample of stored articles and compare body hashes")
    vf.add_argument("--per-outlet", type=int, default=20)
    vf.add_argument("--seed", type=int, default=20261005)
    vf.add_argument("--outlets", help="comma-separated outlet ids (default: all)")

    rd = sub.add_parser("redate", help="correct discovery-day publication times from the "
                        "stored pages; derived stages follow")
    rd.add_argument("--window", choices=sorted(WINDOWS), default="story-v01")

    co = sub.add_parser("carryover", help="after an extractor bump: copy lemma rows and keep "
                        "vectors of articles whose text did not change")
    co.add_argument("--from", dest="prev", required=True, help="previous documents version dir")

    sub.add_parser("dedupe", help="drop duplicate event_ids from the documents, lemmas and "
                   "embeddings parts (left by overlapping runs)")

    sub.add_parser("band", help="relevance stage 2: similarity to the story centroid, strata")

    rl = sub.add_parser("release", help="build the release files (no article text)")
    rl.add_argument("--version", required=True, help="dataset version, e.g. 1.0.0")

    sub.add_parser("lexicon", help="relevance stage 1: lexicon candidates")

    em = sub.add_parser("embed", help="document embeddings, gemini-embedding-2 Batch API")
    em.add_argument("action", choices=["run", "submit", "collect", "status"])
    em.add_argument("--limit", type=int, help="submit: at most N documents")
    em.add_argument("--budget", type=float, default=25.0,
                    help="approved spend in USD; submit/run refuse to exceed it")
    em.add_argument("--follow", action="store_true",
                    help="run: keep embedding new documents while a fetch or discovery runs")

    lb = sub.add_parser("labels", help="human scope labels: pre-registered draw, pages, import")
    lb.add_argument("action", choices=["round", "draw", "page", "import"])
    lb.add_argument("export", nargs="?", help="import: the page's exported .jsonl")
    lb.add_argument("--set", help="label set name, e.g. gold-v1")
    lb.add_argument("--at", help="round: an ISO time (UTC)")
    lb.add_argument("--round", type=int, help="draw: the drand round fixed in PROTOCOL.md")
    lb.add_argument("--coder", help="page: build the page of one assigned coder")

    cv = sub.add_parser("coverage", help="per outlet × day: discovered, fetched, gone, failed")
    cv.add_argument("--window", choices=sorted(WINDOWS), default="story-v01")

    lm = sub.add_parser("lemmas", help="CLASSLA lemmatisation of the documents")
    lm.add_argument("--workers", type=int, default=8)
    lm.add_argument("--limit", type=int)

    qa = sub.add_parser("qa", help="extraction quality: metrics, and a browser comparison sample")
    qa.add_argument("--compare", type=int, default=0, help="articles per outlet to compare in a browser")
    qa.add_argument("--outlets", help="comma-separated outlet ids to compare (default: all)")

    sub.add_parser("status", help="what is stored so far")

    args = p.parse_args(argv)
    lay = layout()

    if args.cmd == "dumps":
        print(json.dumps(mediacloud.download(lay, args.start, args.end)))
    elif args.cmd == "discover":
        registry = Registry.load(collect_only=True)
        start, end = args.start, args.end
        if args.window:
            start, end = WINDOWS[args.window].start, WINDOWS[args.window].end
        routes = load_routes()
        # one run per route at a time: two would double the request rate on the route's host
        run_route = {
            "mediacloud": lambda: mediacloud.discover(lay, start, end, registry.domains),
            "sitemaps": lambda: sitemaps.discover(lay, routes, registry, start, end),
            "rtslist": lambda: rtslist.discover(lay, routes, registry, start, end),
            "naslovi": lambda: naslovi.discover(lay, routes, registry, start, end,
                                                refresh=args.refresh),
        }
        if args.route == "idprobe":  # a completeness pass after the main routes, never in "all"
            from canopy_news import idprobe
            run_route = {"idprobe": lambda: idprobe.discover(lay, routes, registry, start, end)}
        result = {}
        for name, fn in run_route.items():
            if args.route in (name, "all"):
                with exclusive(lay, f"discover-{name}"):
                    result[name] = fn()
        print(json.dumps(result, indent=2, default=str))
    elif args.cmd == "fetch":
        run = run_pass(lay, WINDOWS[args.window], Registry.load(collect_only=True), limit=args.limit,
                       min_interval_s=args.min_interval)
        print(run.dir)
    elif args.cmd == "documents":
        from canopy_news import documents
        with exclusive(lay, "documents"):
            print(json.dumps(documents.build(lay, WINDOWS[args.window], workers=args.workers)))
    elif args.cmd == "embed":
        from canopy_news import embeddings
        if args.action == "status":  # read-only: no lock, so it works while `run` holds it
            print(json.dumps(embeddings.status(lay), indent=2))
            return
        with exclusive(lay, "embed"):
            if args.action == "run":
                embeddings.run(lay, budget_usd=args.budget, follow=args.follow)
                return
            if args.action == "submit":
                out = embeddings.submit(lay, limit=args.limit, budget_usd=args.budget)
            elif args.action == "collect":
                out = embeddings.collect(lay)
            else:
                out = embeddings.status(lay)
        print(json.dumps(out, indent=2))
    elif args.cmd == "verify":
        from canopy_news import verify
        print(json.dumps(verify.run(
            lay, per_outlet=args.per_outlet, seed=args.seed,
            outlets=set(args.outlets.split(",")) if args.outlets else None), indent=2))
    elif args.cmd == "redate":
        from canopy_news import redate
        with exclusive(lay, "documents"), exclusive(lay, "lemmas"), exclusive(lay, "embed"):
            print(json.dumps(redate.run(lay, WINDOWS[args.window]), indent=2))
    elif args.cmd == "carryover":
        from canopy_news import carryover
        with exclusive(lay, "documents"), exclusive(lay, "lemmas"), exclusive(lay, "embed"):
            print(json.dumps(carryover.run(lay, args.prev), indent=2))
    elif args.cmd == "dedupe":
        from canopy_news import documents, embeddings, lemmas
        out = {}
        for stage, d in (("documents", documents.doc_dir(lay)), ("lemmas", lemmas.lemma_dir(lay)),
                         ("embed", embeddings.emb_dir(lay, "documents"))):
            with exclusive(lay, stage):
                out[stage] = documents.dedupe_parts(d)
        print(json.dumps(out))
    elif args.cmd == "release":
        from canopy_news import release
        print(json.dumps(release.build(lay, args.version), indent=2))
    elif args.cmd == "band":
        from canopy_news import band
        print(json.dumps(band.build(lay), indent=2, ensure_ascii=False))
    elif args.cmd == "lexicon":
        from canopy_news import lexicon
        rep = lexicon.report(lexicon.run(lay))
        (lay.build_dir("scope") / f"{rep['version']}_report.json").write_text(json.dumps(rep, indent=2))
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    elif args.cmd == "labels":
        from pathlib import Path

        from canopy_news import labels
        if args.action == "round":
            if not args.at:
                p.error("labels round needs --at")
            r = labels.round_at(datetime.fromisoformat(args.at.replace("Z", "+00:00")))
            out = {"round": r, "published_at": labels.round_time(r).isoformat()}
        elif not args.set:
            p.error(f"labels {args.action} needs --set")
        elif args.action == "draw":
            if not args.round:
                p.error("labels draw needs --round (the one fixed in PROTOCOL.md)")
            out = labels.draw_set(lay, args.set, args.round)
        elif args.action == "page":
            out = {"page": str(labels.page(lay, args.set, args.coder))}
        else:
            if not args.export:
                p.error("labels import needs the exported .jsonl")
            out = labels.import_labels(lay, args.set, Path(args.export))
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.cmd == "coverage":
        from canopy_news import coverage
        window = WINDOWS[args.window]
        rows = coverage.table(lay, window, Registry.load(collect_only=True))
        coverage.write(lay, window, rows)
        print(json.dumps(coverage.summary(rows), indent=2))
    elif args.cmd == "lemmas":
        from canopy_news import lemmas
        with exclusive(lay, "lemmas"):
            print(json.dumps(lemmas.build(lay, workers=args.workers, limit=args.limit)))
    elif args.cmd == "qa":
        from canopy_news import qa as qa_mod
        out = {"metrics": qa_mod.metrics(lay)}
        if args.compare:
            rows = qa_mod.compare_sample(
                lay, Registry.load(collect_only=True), per_outlet=args.compare,
                outlets=set(args.outlets.split(",")) if args.outlets else None)
            out["compared"] = len(rows)
        qa_mod.qa_dir(lay).mkdir(parents=True, exist_ok=True)
        (qa_mod.qa_dir(lay) / "metrics.json").write_text(json.dumps(out["metrics"], indent=2))
        print(json.dumps(out, indent=2))
    elif args.cmd == "status":
        index = mediacloud.read_index(lay)
        con = EventLog(lay.log).connect()
        kinds = dict(con.execute(
            "SELECT kind, count(*) FROM events WHERE corpus = ? GROUP BY kind", [CORPUS]
        ).fetchall())
        con.close()
        print(json.dumps({
            "dumps_stored": sum(1 for e in index.values() if e.get("sha256")),
            "dumps_missing": sum(1 for e in index.values() if e.get("status") == 404),
            "discovery_files": len(discovery_files(lay)),
            "events": kinds,
        }, indent=2))


if __name__ == "__main__":
    main()
