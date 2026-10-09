# CLAUDE.md — canopy-collapse-news-2024-2025

How to work in this repo. Read this first, every session.

## What this is

A public dataset: every news article nine Serbian online outlets published from 1 Nov 2024 to
30 Apr 2025, as a verifiable index (URLs, dates, hashes), with a validated scope layer for the
Novi Sad canopy collapse and the protest movement that followed. The method is
[`PROTOCOL.md`](./PROTOCOL.md); what the dataset holds is [`DATASHEET.md`](./DATASHEET.md).
Everything here is public: no private plans, no notes between sessions, no reference to other
private projects or to any employer.

## Documents of record

| File | Holds | Update when |
|---|---|---|
| `PROTOCOL.md` | the method, as done; Appendix A lists decisions made along the way | the method changes (a new dataset version) or a validation figure comes in |
| `CODEBOOK.md` | the scope definition for coders and classifier | never after the first gold label, except as a new codebook version recorded in `PROTOCOL.md` |
| `DATASHEET.md` | composition, collection, uses, limits | counts or uses change |
| `REPRODUCE.md` | every step as a command | a command or step changes |
| `README.md` | the front page | status or contents change |

## Hard rules

1. **Nothing from `raw/` is ever published**, and no data directory is ever committed. Releases
   carry URLs, hashes, dates and derived records only (`canopy-news release` refuses text
   columns). The event log holds headlines in its attrs, so it is released only as the export.
2. **Only the nine outlets with `collect = yes`** in `registries/outlets.csv` are retrieved;
   anything that touches the network loads the registry with `collect_only=True`.
3. **Only the window 1 Nov 2024 → 30 Apr 2025** (`story-v01`) is collected or processed.
4. **Fetching etiquette:** robots.txt including `Crawl-delay`; ≥ 2 s between requests to a
   host; the user agent in `config.py`; no logins, no paywall circumvention, no reader comments.
5. **Neutrality:** outlets are the unit; selection never uses political alignment; the scope
   layer records only whether an article is about the story, never a judgement of its content.
6. **The gold set is fixed:** its sample and assignment are never redrawn; labels are imported,
   never edited; the classifier is never chosen or tuned on gold labels.
7. **Paid API calls need the owner's go-ahead** with a cost estimate first
   (`scripts/cost_model.py`).
8. **The log is append-only:** corrections are new records, never rewrites.
9. **Commits and pushes only when the owner asks.**

## Conventions

- Python ≥ 3.11, uv, `pyproject.toml`; tests in `tests/`; ruff (line length 100).
- Every timestamp is timezone-aware UTC (`chrono_harness.timeutil.to_utc`).
- Every text a stage or a model reads is Latin: Cyrillic pages are transliterated losslessly
  and keep the original script as metadata.
- Stages that write scope outputs process articles in a fixed order, so reruns are
  byte-identical.
- Run manifests record exact model ids and settings.
- Unverified facts in documents carry `[VERIFY]`.

## Commands

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests scripts
scripts/jobs.sh start | fetch | process | autoprocess | embed | stop | status
uv run canopy-news dumps | discover --route R | fetch --window story-v01 | redate
uv run canopy-news documents | lemmas | lexicon | band | coverage | qa | status
uv run canopy-news embed run | submit | collect | status [--budget USD]   # Gemini Batch API ($)
uv run canopy-news labels round --at T | draw --set gold-v1 --round R   # pre-registered draw (PROTOCOL.md §6.1)
uv run canopy-news labels page|import --set gold-v1 [--coder R1]
ots stamp FILE ; ots upgrade FILE.ots ; ots verify FILE.ots                # OpenTimestamps (dev extra)
uv run canopy-news classify run|submit|collect|status [--run main|repeat] [--budget USD] [--gold-set S]  # Message Batches ($)
uv run canopy-news validate --set gold-v1                 # PROTOCOL.md §6.4 figures
uv run canopy-news verify [--per-outlet N]
uv run canopy-news hydrate --index index.parquet [--scope scope.parquet --in-scope-only] [--out texts]
uv run canopy-news release --version V                    # release/<V>/, no text
python3 scripts/cost_model.py
uv run python scripts/classifier_pilot.py [--cap USD]      # classifier arms on non-gold articles ($)
```

API keys live in `.env` (gitignored; template `.env.example`). Data directories live under the
repository root or `CANOPY_NEWS_ROOT`. Long jobs run detached with
`setsid nohup … > builds/logs/<job>.log`; every job is idempotent and resumes.
