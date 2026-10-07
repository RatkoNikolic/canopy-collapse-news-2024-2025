"""Documents stage: fetched pages → clean article records (M2).

For every `insert` event in the window, the stored page is passed through
trafilatura (main text + metadata) and normalised:

- title, lead (the page's description), body; section (first URL segment),
  tags, categories; byline kept for the private tier only;
- Cyrillic → Latin (`to_latin`); the original-script title and body are kept
  when the page is mostly Cyrillic, so normalisation stays lossless;
- paragraph offsets into the Latin body, so later claims can cite exact spans;
- a hash of the normalised body, for duplicate and wire-copy detection.

Records go to builds/documents/<EXTRACTOR_VERSION>/part-*.parquet. The stage
is incremental (events already processed are skipped) and rebuildable: a new
EXTRACTOR_VERSION starts a new directory from the stored pages.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, time
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import trafilatura
from chrono_harness import Event, EventLog, Layout, RawStore
from chrono_harness.timeutil import now_utc, to_utc

from canopy_news.config import CORPUS, Window, repo_root

EXTRACTOR_VERSION = f"doc-v8-trafilatura-{trafilatura.__version__}"


def load_rules(path: Path | None = None) -> dict[str, dict[str, list[str]]]:
    """registries/extraction.csv: per-outlet fixes, each with its reason —
    `container` (XPath of the article element), `drop_line` (regex a whole line
    must match), `end_marker` (regex of the line where the article ends)."""
    import csv

    path = path or repo_root() / "registries" / "extraction.csv"
    rules: dict[str, dict[str, list[str]]] = {}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("outlet_id") or "").strip():
                rules.setdefault(r["outlet_id"].strip(), {}).setdefault(
                    r["rule"].strip(), []).append(r["value"])
    return rules

_CYR = "АБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШабвгдђежзијклљмнњопрстћуфхцчџш"
_LAT = ["A", "B", "V", "G", "D", "Đ", "E", "Ž", "Z", "I", "J", "K", "L", "Lj", "M", "N", "Nj",
        "O", "P", "R", "S", "T", "Ć", "U", "F", "H", "C", "Č", "Dž", "Š",
        "a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m", "n", "nj",
        "o", "p", "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š"]
_TRANSLIT = str.maketrans(dict(zip(_CYR, _LAT, strict=True)))
_CYR_RE = re.compile(r"[Ѐ-ӿ]")
_LETTER_RE = re.compile(r"[^\W\d_]")


def to_latin(text: str) -> str:
    """Serbian Cyrillic → Latin (gaj). The original is kept separately, since
    Latin → Cyrillic is not unique (dž, lj, nj)."""
    return text.translate(_TRANSLIT)


def cyrillic_share(text: str) -> float:
    letters = len(_LETTER_RE.findall(text))
    return len(_CYR_RE.findall(text)) / letters if letters else 0.0


def _norm_for_hash(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def paragraph_offsets(body: str) -> list[list[int]]:
    offsets, pos = [], 0
    for para in body.split("\n"):
        if para.strip():
            offsets.append([pos, pos + len(para)])
        pos += len(para) + 1
    return offsets


def _bare(html: str, url: str, metadata: bool) -> dict:
    doc = trafilatura.bare_extraction(html, url=url, with_metadata=metadata,
                                      include_comments=False, include_tables=False,
                                      deduplicate=False)
    return doc.as_dict() if hasattr(doc, "as_dict") else (doc or {})


_BLOCKS = {"p", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"}
_JUNK_TAGS = {"script", "style", "iframe", "noscript", "ins", "form", "button", "figure"}
_JUNK_CLASS = re.compile(r"\b(bn-box|banner|ad-|ads\b|advert|social|share|related|tags|"
                         r"recommended|comments?(-box)?|next-news|end-of-news|news-item)", re.I)


def _container_text(node) -> list[str]:
    """Paragraph-level text of a known article container, in document order;
    scripts, ad slots, share and related widgets, and figures are skipped."""
    for el in list(node.iter()):
        if not isinstance(el.tag, str):
            continue
        if el.tag in _JUNK_TAGS or _JUNK_CLASS.search(el.get("class") or ""):
            el.drop_tree()
    out = []
    for el in node.iter():
        if isinstance(el.tag, str) and el.tag in _BLOCKS and not any(
                a.tag in _BLOCKS for a in el.iterancestors()):
            text = " ".join(el.text_content().split())
            if text:
                out.append(text)
    return out or [line for line in (" ".join(x.split()) for x in node.text_content().split("\n"))
                   if line]


def _apply_line_rules(body: str, rules: dict[str, list[str]]) -> str:
    """Rules are written in Latin script and matched against each line's Latin form,
    so one rule covers a page served in either script."""
    drops = [re.compile(r) for r in rules.get("drop_line", [])]
    ends = [re.compile(r) for r in rules.get("end_marker", [])]
    kept = []
    for line in body.split("\n"):
        latin = to_latin(line.strip())
        if any(e.fullmatch(latin) for e in ends):
            break
        if not any(d.fullmatch(latin) for d in drops):
            kept.append(line)
    return "\n".join(kept).strip("\n")


def extract(html: bytes, url: str, outlet_rules: dict[str, list[str]] | None = None) -> dict:
    """trafilatura main text + metadata, normalised, with the outlet's fixes
    from registries/extraction.csv. Never raises: a failed extraction comes
    back with an empty body and `error` set."""
    rules = outlet_rules or {}
    page = html.decode("utf-8", "replace")
    try:
        d = _bare(page, url, metadata=True)
        if rules.get("container"):
            from lxml import html as lxml_html

            tree = lxml_html.fromstring(page)
            nodes = [n for xp in rules["container"] for n in tree.xpath(xp)]
            if nodes:
                d["text"] = "\n".join(t for n in nodes for t in _container_text(n))
        error = None
    except Exception as exc:  # noqa: BLE001 - one bad page must not stop the stage
        d, error = {}, f"{type(exc).__name__}: {exc}"
    title, lead, body = d.get("title") or "", d.get("description") or "", d.get("text") or ""
    body = _apply_line_rules(body, rules)
    lines = body.split("\n")
    while lines and not lines[0].strip():  # live blogs pad the top with blank lines
        lines.pop(0)
    body = "\n".join(lines)
    if lines and title and _norm_for_hash(lines[0]) == _norm_for_hash(title):
        body = "\n".join(lines[1:])  # the headline repeated as the body's first line
    share = cyrillic_share(title + " " + body)
    body_lat = to_latin(body)
    segments = [s for s in urlsplit(url).path.split("/") if s]
    while segments and segments[0].lower() in {"lat", "ci", "sr", "scc"}:
        segments = segments[1:]
    return {
        "title": to_latin(title), "lead": to_latin(lead), "body": body_lat,
        "title_original": title if share > 0.3 else None,
        "body_original": body if share > 0.3 else None,
        "script": "cyrl" if share > 0.6 else ("mixed" if share > 0.1 else "latn"),
        "cyrillic_share": round(share, 3),
        "section": segments[0].lower() if segments else "",
        "tags": [to_latin(t) for t in (d.get("tags") or [])],
        "categories": [to_latin(c) for c in (d.get("categories") or [])],
        "byline": d.get("author"),
        "page_date": d.get("date"),
        "para_offsets": paragraph_offsets(body_lat),
        "n_chars": len(body_lat),
        "body_hash": hashlib.sha256(_norm_for_hash(body_lat).encode()).hexdigest()[:32],
        "error": error,
    }


SCHEMA = pa.schema([
    ("event_id", pa.string()), ("unit_id", pa.string()), ("outlet_id", pa.string()),
    ("valid_time", pa.timestamp("us", tz="UTC")), ("pub_date_source", pa.string()),
    ("content_sha256", pa.string()), ("extractor", pa.string()),
    ("title", pa.string()), ("lead", pa.string()), ("body", pa.string()),
    ("title_original", pa.string()), ("body_original", pa.string()),
    ("script", pa.string()), ("cyrillic_share", pa.float32()), ("section", pa.string()),
    ("tags", pa.list_(pa.string())), ("categories", pa.list_(pa.string())),
    ("byline", pa.string()), ("page_date", pa.string()),
    ("para_offsets", pa.list_(pa.list_(pa.int32()))), ("n_chars", pa.int32()),
    ("body_hash", pa.string()), ("error", pa.string()),
])


def doc_dir(lay: Layout) -> Path:
    return lay.build_dir("documents") / EXTRACTOR_VERSION


def processed_event_ids(lay: Layout) -> set[str]:
    files = sorted(doc_dir(lay).glob("part-*.parquet"))
    if not files:
        return set()
    listing = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
    return {r[0] for r in duckdb.sql(f"SELECT event_id FROM read_parquet([{listing}])").fetchall()}


def dedupe_parts(directory: Path, key: str = "event_id") -> dict[str, int]:
    """Rewrite a stage's parts with one row per key, if any key occurs twice. The
    deduplicated part is in place before the old parts go, so a crash leaves
    duplicates (rerun) and never a gap."""
    files = sorted(directory.glob("part-*.parquet"))
    if not files:
        return {"rows": 0, "dropped": 0}
    listing = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
    rows, keys = duckdb.sql(
        f"SELECT count(*), count(DISTINCT {key}) FROM read_parquet([{listing}])").fetchone()
    if rows == keys:
        return {"rows": rows, "dropped": 0}
    tmp = directory / f"tmp-{uuid.uuid4().hex[:12]}.parquet"
    duckdb.sql(f"""COPY (SELECT * FROM read_parquet([{listing}])
        QUALIFY row_number() OVER (PARTITION BY {key} ORDER BY {key}) = 1)
        TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    tmp.rename(directory / f"part-{uuid.uuid4().hex[:12]}.parquet")
    for f in files:
        f.unlink()
    return {"rows": keys, "dropped": rows - keys}


_ARTICLE_ID = re.compile(r"/(\d{4,})(?=/|$|-|\.)")


def soft_404(url: str, final_url: str | None) -> bool:
    """A removed article some outlets answer with a redirect to a section page (200):
    the requested URL carries an article id, the final URL does not."""
    if not final_url or final_url == url:
        return False
    ids = set(_ARTICLE_ID.findall(urlsplit(url).path))
    return bool(ids) and not ids & set(_ARTICLE_ID.findall(urlsplit(final_url).path))


def current_inserts(log: EventLog) -> list[Event]:
    """The latest-recorded insert per unit. A correction (redate.py) is a later insert
    of the same unit, so every reader sees one record per article."""
    latest: dict[str, Event] = {}
    for e in log.as_of(now_utc(), corpus=CORPUS, clock="ingest"):
        if e.kind == "insert":
            cur = latest.get(e.unit_id)
            if cur is None or (e.ingest_time, e.event_id) > (cur.ingest_time, cur.event_id):
                latest[e.unit_id] = e
    return list(latest.values())


def window_inserts(lay: Layout, window: Window) -> list[Event]:
    end = to_utc(datetime.combine(window.end, time.max).replace(tzinfo=None).isoformat() + "+00:00")
    start = to_utc(window.start)
    return [e for e in current_inserts(EventLog(lay.log)) if start <= e.valid_time <= end]


def _work(args: tuple[str, str, str, dict]) -> tuple[str, dict]:
    raw_root, sha, url, rules = args
    return sha, extract(RawStore(Path(raw_root)).get(sha), url, rules)


def _chunks(items: list, n: int) -> Iterator[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def build(lay: Layout, window: Window, *, workers: int = 4, chunk: int = 2000) -> dict[str, int]:
    out_dir = doc_dir(lay)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = processed_event_ids(lay)
    rules = load_rules()
    todo = [e for e in window_inserts(lay, window) if e.event_id not in done]
    counts = {"already": len(done), "processed": 0, "empty_body": 0, "errors": 0}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in _chunks(todo, chunk):
            results = dict(pool.map(_work, [(str(lay.raw), e.content_sha256, e.unit_id,
                                             rules.get(e.attrs.get("outlet_id"), {}))
                                            for e in part], chunksize=50))
            rows = []
            for e in part:
                r = results[e.content_sha256]
                final = e.attrs.get("final_url")
                if soft_404(e.unit_id, final):  # a listing page, not the article: out of the corpus
                    r = {**r, "body": "", "body_original": None, "lead": "", "para_offsets": [],
                         "n_chars": 0, "error": f"soft_404: redirected to {final}"}
                rows.append({"event_id": e.event_id, "unit_id": e.unit_id,
                             "outlet_id": e.attrs.get("outlet_id"), "valid_time": e.valid_time,
                             "pub_date_source": e.attrs.get("pub_date_source"),
                             "content_sha256": e.content_sha256, "extractor": EXTRACTOR_VERSION,
                             **r})
                counts["empty_body"] += r["n_chars"] < 200
                counts["errors"] += r["error"] is not None
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA),
                           out_dir / f"part-{uuid.uuid4().hex[:12]}.parquet", compression="zstd")
            counts["processed"] += len(rows)
    return counts
