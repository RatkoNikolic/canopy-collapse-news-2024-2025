# Changelog

## 1.1.0 — 2026-10-09

DOI 10.5281/zenodo.23261738.


- `canopy-news hydrate`: rebuilds the article texts from the released index, fetching each
  article politely and checking it against `body_sha256` (matched / changed / gone / failed).
- Documentation: the precise definition of the body hash (`PROTOCOL.md` §4).
- Data: unchanged. `index.parquet`, `scope.parquet`, `coverage.parquet` and `validation.json` are
  byte-identical to 1.0.0; `manifest.json` names the new version and commit.

## 1.0.0 — 2026-10-09

First release: the index of 216,050 articles, the scope layer (43,611 in scope), validation
against the pre-registered gold set `gold-v1`. DOI 10.5281/zenodo.23260973.
