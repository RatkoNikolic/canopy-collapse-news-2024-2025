"""Extraction quality check (M2): automatic metrics per outlet, and a sample
compared against the page as a browser renders it (Playwright).

Automatic metrics (all documents): empty and short bodies, median length,
missing title or lead, repeated paragraphs, leftover boilerplate phrases,
page date disagreeing with the event's publication time.

Browser comparison (a seeded sample per outlet): the live page is loaded in
Chromium (see `_chromium`; robots.txt obeyed; ≥ 2 s per host; the project
user agent; third-party hosts, images, media and fonts blocked). For each
article:
- `raw_in_page`: share of our extracted paragraphs found in the rendered page
  text (low = we extracted something a reader does not see);
- `rendered_extra`: share of the paragraphs trafilatura finds in the rendered
  page that are missing from our extraction (high = text loaded by
  JavaScript, or text we cut);
- a screenshot for visual review.
Results go to builds/qa/<EXTRACTOR_VERSION>/.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.robotparser
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit

import duckdb
import httpx
import trafilatura
from chrono_harness import Layout

from canopy_news.config import USER_AGENT
from canopy_news.documents import EXTRACTOR_VERSION, doc_dir, to_latin
from canopy_news.registry import Registry

BOILERPLATE = {
    "procitajte_jos": r"pro[cč]itajte (jo[sš]|i|vi[sš]e)",
    "povezane_vesti": r"povezane (vesti|teme)|najnovije vesti|naj[cč]itanije",
    "foto_video_credit": r"^(foto|video|izvor foto)\s*:",
    "tagovi": r"^tagovi\b|^tags\b",
    "cookies": r"kola[cč]i[cćk]|cookies?",
    "app_social": r"preuzmite (na[sš]u )?aplikaciju|pratite nas na|prijavite se na newsletter",
    "rights": r"sva prava zadr[zž]ana|©",
    "comments": r"komentar(i|a)?\s*\(\d+\)|ostavite komentar",
    "cross_reference": r"vi[sš]e o tome (u|pro[cč]itajte)|u posebnom tekstu|u odvojenom tekstu",
}
_BP = {k: re.compile(v, re.I | re.M) for k, v in BOILERPLATE.items()}
def _chromium() -> str:
    """PLAYWRIGHT_CHROMIUM, else the newest Playwright-managed Chromium in the
    cache, else the system build (the snap build cannot resolve DNS in some VMs)."""
    if os.environ.get("PLAYWRIGHT_CHROMIUM"):
        return os.environ["PLAYWRIGHT_CHROMIUM"]
    cached = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux*/chrome"),
                    key=lambda p: int(p.parts[-3].split("-")[-1]))
    return str(cached[-1]) if cached else "/snap/bin/chromium"


CHROMIUM = _chromium()


def qa_dir(lay: Layout) -> Path:
    return lay.build_dir("qa") / EXTRACTOR_VERSION


def _docs(lay: Layout) -> list[dict]:
    files = sorted(doc_dir(lay).glob("part-*.parquet"))
    if not files:
        return []
    listing = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
    return duckdb.sql(f"""SELECT unit_id, outlet_id, title, lead, body, n_chars, page_date,
        CAST(CAST(valid_time AS DATE) AS VARCHAR) AS vdate, script
        FROM read_parquet([{listing}])
        WHERE error IS NULL""").to_arrow_table().to_pylist()  # error records are not articles


def metrics(lay: Layout) -> dict[str, dict]:
    by_outlet: dict[str, list[dict]] = defaultdict(list)
    for d in _docs(lay):
        by_outlet[d["outlet_id"]].append(d)
    out = {}
    for outlet, docs in sorted(by_outlet.items()):
        n = len(docs)
        bp = Counter()
        repeated = 0
        for d in docs:
            for k, rx in _BP.items():
                if rx.search(d["body"]):
                    bp[k] += 1
            paras = [p.strip() for p in d["body"].split("\n") if len(p.strip()) > 40]
            repeated += len(paras) != len(set(paras))
        out[outlet] = {
            "n": n,
            "empty_lt200": sum(d["n_chars"] < 200 for d in docs) / n,
            "short_lt500": sum(d["n_chars"] < 500 for d in docs) / n,
            "median_chars": median(d["n_chars"] for d in docs),
            "no_title": sum(not d["title"] for d in docs) / n,
            "no_lead": sum(not d["lead"] for d in docs) / n,
            "repeated_paragraphs": repeated / n,
            "page_date_mismatch": sum(bool(d["page_date"]) and d["page_date"] != d["vdate"]
                                      for d in docs) / n,
            "cyrillic_docs": sum(d["script"] != "latn" for d in docs) / n,
            "boilerplate": {k: round(v / n, 3) for k, v in bp.most_common()},
        }
    return out


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", to_latin(text).lower()).split())


def _router(first_party: tuple[str, ...]):
    """Allow first-party documents, scripts and styles; block third parties,
    images, media and fonts (Playwright calls handlers as (route, request))."""
    def handle(route, *_):
        req = route.request
        rhost = (urlsplit(req.url).hostname or "").removeprefix("www.")
        own = any(rhost == f or rhost.endswith("." + f) for f in first_party)
        if not own or req.resource_type in ("image", "media", "font"):
            return route.abort()
        return route.continue_()
    return handle


def compare_sample(lay: Layout, registry: Registry, *, per_outlet: int = 12, seed: int = 7,
                   min_interval_s: float = 2.0, outlets: set[str] | None = None) -> list[dict]:
    from playwright.sync_api import sync_playwright

    by_outlet: dict[str, list[dict]] = defaultdict(list)
    for d in _docs(lay):
        if outlets is None or d["outlet_id"] in outlets:
            by_outlet[d["outlet_id"]].append(d)
    rng = random.Random(seed)
    sample = [d for o in sorted(by_outlet) for d in
              rng.sample(by_outlet[o], min(per_outlet, len(by_outlet[o])))]
    out_dir = qa_dir(lay)
    (out_dir / "screens").mkdir(parents=True, exist_ok=True)
    robots: dict[str, urllib.robotparser.RobotFileParser] = {}
    last: dict[str, float] = {}
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, headless=True)
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 1600})
        for i, d in enumerate(sample):
            url, host = d["unit_id"], urlsplit(d["unit_id"]).hostname or ""
            outlet = registry.outlet_for(host)
            first_party = tuple(outlet.domains) if outlet else (host,)
            if host not in robots:
                rp = urllib.robotparser.RobotFileParser()
                try:
                    resp = httpx.get(f"https://{host}/robots.txt", headers={"User-Agent": USER_AGENT},
                                     timeout=30, follow_redirects=True)
                    rp.parse(resp.text.splitlines() if resp.status_code < 300 else [])
                except httpx.HTTPError:
                    rp.parse([])
                robots[host] = rp
            if not robots[host].can_fetch(USER_AGENT, url):
                results.append({"url": url, "outlet_id": d["outlet_id"], "error": "robots"})
                continue
            wait = min_interval_s - (time.monotonic() - last.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            last[host] = time.monotonic()
            page = context.new_page()

            page.route("**/*", _router(first_party))
            row = {"url": url, "outlet_id": d["outlet_id"]}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                rendered = page.content()
                visible = _norm(page.inner_text("body"))
                shot = out_dir / "screens" / f"{d['outlet_id']}_{i:03d}.png"
                page.screenshot(path=str(shot), full_page=False)
                rd = trafilatura.bare_extraction(rendered, url=url, with_metadata=False,
                                                 include_comments=False, include_tables=False)
                rtext = (rd.as_dict() if hasattr(rd, "as_dict") else (rd or {})).get("text") or ""
                ours = [_norm(x) for x in d["body"].split("\n") if len(x.strip()) > 40]
                theirs = [_norm(x) for x in rtext.split("\n") if len(x.strip()) > 40]
                ours_joined = " ".join(_norm(x) for x in d["body"].split("\n"))
                row |= {
                    "raw_paras": len(ours), "rendered_paras": len(theirs),
                    "raw_in_page": sum(x in visible for x in ours) / len(ours) if ours else None,
                    "rendered_extra": (sum(x not in ours_joined for x in theirs) / len(theirs)
                                       if theirs else None),
                    "extra_samples": [x[:160] for x in theirs if x not in ours_joined][:8],
                    "lead_in_page": bool(d["lead"]) and _norm(d["lead"])[:80] in visible,
                    "screenshot": str(shot.relative_to(lay.root)),
                }
            except Exception as exc:  # noqa: BLE001 - record and continue
                row["error"] = f"{type(exc).__name__}: {exc}"[:300]
            finally:
                page.close()
            results.append(row)
        browser.close()
    name = "compare.jsonl" if outlets is None else f"compare_{'_'.join(sorted(outlets))}.jsonl"
    (out_dir / name).write_text("".join(json.dumps(r) + "\n" for r in results))
    return results
