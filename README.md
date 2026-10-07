# canopy-collapse-news-2024-2025

All news articles from nine Serbian online outlets, **1 November 2024 – 30 April 2025**, as a
verifiable index, with a validated **scope layer** marking the articles about the collapse of
the Novi Sad railway-station canopy on 1 November 2024 and the protest movement that followed.

> **Status: v1.0 in preparation.** Collection and processing are complete. The gold set is
> pre-registered (`PROTOCOL.md` §6.1): its procedure is timestamped before a public beacon
> fixes its seed, and its draw before the first label. The labels and the classifier run
> follow; then the release files and validation figures.

## What is in it

| | |
|---|---|
| Outlets | Blic, Danas, Informer · RTS, B92, Pink · N1, Telegraf, Nova (three per media type, by reach) |
| Articles | 216,050 in the corpus (217,660 URLs reached) |
| Per article | URL, outlet, publication and fetch time, discovery route, sha256 of the page and of the extracted text, scope decision |
| Gold set | 300 articles labelled for scope by three coders |
| Not included | article text, titles, embeddings (the outlets' copyright; the hashes make the text verifiable) |

## Documents

- [`PROTOCOL.md`](./PROTOCOL.md): how the dataset was built, from outlet selection to the
  validated scope layer, with the decisions made along the way.
- [`DATASHEET.md`](./DATASHEET.md): composition, collection, uses and limits.
- [`CODEBOOK.md`](./CODEBOOK.md): the scope definition used by coders and classifier alike.
- [`REPRODUCE.md`](./REPRODUCE.md): every step as a command; how to verify the release.
- [`LABELLING_GUIDE.md`](./LABELLING_GUIDE.md): instructions for the human coders.
- [`docs/extraction_qa.md`](./docs/extraction_qa.md): text extraction quality per outlet.

## Verify an article

Every release row carries `body_sha256`, the hash of the extracted text. Fetch the URL,
extract it with this code and compare:

```bash
uv sync --extra dev
uv run canopy-news verify --per-outlet 20      # a seeded sample per outlet against the live web
```

Equal hashes mean the same text; a difference means the outlet has edited or removed the
article since October 2026.

## Licence and citation

Code: Apache-2.0. Derived data and documents: CC BY 4.0. The articles remain the property of
their publishers and are not distributed. A citation with DOI comes with the v1.0 release.
