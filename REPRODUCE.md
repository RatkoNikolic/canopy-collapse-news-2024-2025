# Reproducing the dataset

How each step of [`PROTOCOL.md`](./PROTOCOL.md) is run, what a rerun gives back and what it
cannot, and how to check the release against the live web.

**The standard is verifiable, not identical.** The release carries no article text, and the
web keeps changing: articles are edited or removed, listings and sitemaps shift. A rerun
reproduces the *method* exactly and the *corpus* as far as the web still holds it;
`canopy-news verify` (§4) measures how far that is, article by article, against the released
hashes.

## 1. Environment

- Python 3.13 (≥ 3.11 supported) and [uv](https://docs.astral.sh/uv/):
  `uv sync --extra dev` installs the pinned set from `uv.lock`.
- [`chrono-harness`](https://github.com/RatkoNikolic/chrono-harness) `v0.1.0` (data layout,
  append-only event log, run manifests), installed by git tag.
- Text extraction: trafilatura 2.3.0 plus the per-outlet rules in `registries/extraction.csv`
  (extractor `doc-v8`; quality record: [`docs/extraction_qa.md`](./docs/extraction_qa.md)).
- Lemmatisation: CLASSLA 2.2.3, Serbian standard models (model hashes in `PROTOCOL.md` §4).
- Paid APIs, keys in `.env` (template `.env.example`): Gemini (embeddings, ≈ $17) and
  Anthropic (classifier, ≈ $110–190). `python3 scripts/cost_model.py` prints the estimates.
- Data directories (`raw/ log/ builds/ runs/`) live under the repository root, or under
  `CANOPY_NEWS_ROOT`. They hold ≈ 19 GB after a full run and are never committed.

## 2. The pipeline

Every step is idempotent and resumes where it stopped; `scripts/jobs.sh` runs the long ones
detached. Only the nine outlets with `collect = yes` and only the window
1 Nov 2024 → 30 Apr 2025 are touched.

| # | Step | Command | Output |
|---|---|---|---|
| 1 | Media Cloud daily dumps | `canopy-news dumps` | `raw/` + `raw/_index/mediacloud.jsonl` (sha256 per dump) |
| 2 | Discovery: Media Cloud | `canopy-news discover --route mediacloud --window story-v01` | `builds/discovery/mediacloud/` |
| 3 | Discovery: outlet sitemaps | `… --route sitemaps` | `builds/discovery/sitemap-<outlet>/` |
| 4 | Discovery: naslovi.net | `… --route naslovi` | `builds/discovery/naslovi-<outlet>/` (RTS, B92; ≈ 7 min per day) |
| 5 | Discovery: RTS listings | `… --route rtslist` | `builds/discovery/rtslist-rts/` (after step 4, whose days calibrate RTS's IDs) |
| 6 | Fetch | `canopy-news fetch --window story-v01` | `raw/`, `log/`, `runs/*fetch*/` |
| 7 | Discovery: ID completeness, then fetch again | `… --route idprobe`, then step 6 | `builds/discovery/idprobe-<outlet>/` (Pink, Informer) |
| 8 | Date corrections | `canopy-news redate` | appended records in `log/` |
| 9 | Documents | `canopy-news documents` | `builds/documents/doc-v8-trafilatura-2.3.0/` |
| 10 | Lemmas | `canopy-news lemmas` | `builds/lemmas/…` |
| 11 | Embeddings ($) | `canopy-news embed run` | `builds/embeddings/gemini-emb-2-d768/` |
| 12 | Scope stage 1: lexicon | `canopy-news lexicon` | `builds/scope/lex-<version>.parquet` |
| 13 | Scope stage 2: band | `canopy-news band` | `builds/scope/band-<lexicon>-<embedding>.parquet` |
| 14 | Gold set | `canopy-news labels draw --set gold-v1 --round <drand round in PROTOCOL.md §6.1>`, then `labels page --set gold-v1 --coder R1` (R2, R3) | `gold/scope_labels/gold-v1/` (sample, assignment, beacon record), `builds/labelling/` |
| 15 | Labels | `canopy-news labels import --set gold-v1 <export>` | `gold/scope_labels/gold-v1/labels.jsonl` |
| 16 | Scope stage 3: classifier ($) | `canopy-news classify run --run main --budget <USD>`; stability: `classify run --run repeat --gold-set gold-v1 --budget <USD>` | `builds/classify/<run>/` (ledger, decisions, manifest) |
| 16b | Validation | `canopy-news validate --set gold-v1` | `builds/validation/gold-v1.json` (α, precision, recall, per outlet, extension rule, stability) |
| 17 | Coverage | `canopy-news coverage` | `builds/coverage/story-v01.parquet` |
| 18 | Release files | `canopy-news release --version <v>` | `release/<v>/` |

**Which record counts.** The log is append-only. When a publication time is corrected
(step 8), a later record for the same URL carries the corrected time and names the record it
corrects; every reader takes the latest record per URL.

**Deterministic stages.** Steps 12–14 give byte-identical files on a rerun over the same
documents and vectors (checked by running them twice), and step 14 redraws the same sample and
assignment from the published beacon round. The timestamps in `timestamps/` are checked with
`ots verify timestamps/<file>.ots`.

**Time.** Discovery ≈ 2 days (naslovi.net dominates); fetch ≈ 2–3 days (bounded by the
slowest host); documents minutes; lemmas ≈ 6–9 hours on 12 cores; embeddings a few hours.

## 3. What a rerun gives back, and what it cannot

- **Same method, same selection:** the rules, registries, routes and code are fixed by version.
- **Media Cloud dumps** are stable files; their hashes are in `raw/_index/mediacloud.jsonl`.
- **Sitemaps, naslovi.net and RTS listings change:** a rerun finds most but not exactly the
  same URLs. The released index records what was found and when.
- **Articles change:** some are edited or removed after collection. The released hashes show
  what was collected; `verify` shows what still matches.
- **Embeddings** depend on the hosted model; a rerun matches only while the same model version
  is served.

## 4. Checking the release against the web

```bash
uv run canopy-news verify --per-outlet 20 [--outlets rts,blic]
```

Fetches a seeded random sample of stored articles again (same etiquette as the fetcher),
extracts them with the same extractor, and reports per outlet how many are **unchanged** (same
body hash), **edited** (with a similarity ratio), **gone** (404/410) or **failed**. Without the
stored pages, a reviewer compares a fresh extraction with `body_sha256` in `index.parquet`;
`canopy-news hydrate --index index.parquet [--scope scope.parquet --in-scope-only]` does that
for every article and keeps the texts locally (README).
