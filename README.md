# canopy-collapse-news-2024-2025

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23260972.svg)](https://doi.org/10.5281/zenodo.23260972)

All news articles from nine Serbian online outlets, **1 November 2024 – 30 April 2025**, as a
verifiable index, with a validated **scope layer** marking the articles about the collapse of
the Novi Sad railway-station canopy on 1 November 2024 and the protest movement that followed.

> **v1.0.** 43,611 of 216,050 articles in scope, with precision **0.846** (0.792–0.897) and
> recall **0.954** (0.905–0.995) against a pre-registered gold set of 300 articles labelled by
> three coders (agreement α 0.887). Per-outlet figures and their limits: `PROTOCOL.md` §6.5,
> `docs/error_analysis.md`.

## What is in it

| | |
|---|---|
| Outlets | Blic, Danas, Informer · RTS, B92, Pink · N1, Telegraf, Nova (three per media type, by reach) |
| Articles | 216,050 in the corpus (217,660 URLs reached) |
| Per article | URL, outlet, publication and fetch time, discovery route, sha256 of the page, a hash of the extracted text, scope decision |
| In scope | 43,611 articles, each with clauses, the deciding paragraph and the classifier's confidence |
| Gold set | 300 articles labelled for scope by three coders, drawn by a public random beacon after the procedure was timestamped |
| Not included | article text, titles, embeddings (the outlets' copyright; the hashes make the text verifiable) |

## Documents

- [`PROTOCOL.md`](./PROTOCOL.md): how the dataset was built, from outlet selection to the
  validated scope layer, with the decisions made along the way.
- [`DATASHEET.md`](./DATASHEET.md): composition, collection, uses and limits.
- [`CODEBOOK.md`](./CODEBOOK.md): the scope definition used by coders and classifier alike.
- [`REPRODUCE.md`](./REPRODUCE.md): every step as a command; how to verify the release.
- [`LABELLING_GUIDE.md`](./LABELLING_GUIDE.md): instructions for the human coders.
- [`docs/extraction_qa.md`](./docs/extraction_qa.md): text extraction quality per outlet.
- [`docs/error_analysis.md`](./docs/error_analysis.md): where the scope layer and the coders
  disagree, and why.

## Get the texts, and check them

The release has no article text, but every row carries `body_sha256`, a hash of the extracted
text (`PROTOCOL.md` §4). `hydrate` fetches the articles from the outlets, politely, extracts
them with this code and checks each against that hash:

```bash
uv sync --extra dev
# index.parquet and scope.parquet from the release (GitHub or Zenodo)
uv run canopy-news hydrate --index index.parquet --scope scope.parquet --in-scope-only --out texts
uv run canopy-news hydrate --index index.parquet --outlets rts --limit 100 --out texts   # a slice
```

Each article comes back **matched** (the same text as collected), **changed** (edited by the
outlet since October 2026, kept and flagged), **gone** or **failed**. The run resumes where it
stopped. Sites are fetched in parallel at ≥ 2 s per request each: about 6 hours for the
in-scope articles, about a day for the whole index. The texts
are the outlets' copyright: use them for your research, do not redistribute them.

`uv run canopy-news verify --per-outlet 20` does the same check on a seeded sample only.

## Licence and citation

Code: Apache-2.0. Derived data and documents: CC BY 4.0. The articles remain the property of
their publishers and are not distributed.

Cite as: Nikolić, R., Fotev Nikolić, A., & Drča, O. (2026). *canopy-collapse-news-2024-2025*
[Data set]. Zenodo. https://doi.org/10.5281/zenodo.23260972

That DOI always points to the latest version; each version also has its own (v1.0.0:
https://doi.org/10.5281/zenodo.23260973). `CITATION.cff` holds the citation metadata; changes
between versions are in [`CHANGELOG.md`](./CHANGELOG.md).
