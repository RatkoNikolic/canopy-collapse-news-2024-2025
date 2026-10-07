# Datasheet

For **canopy-collapse-news-2024-2025**, following *Datasheets for Datasets* (Gebru et al.,
2021). Method details are in [`PROTOCOL.md`](./PROTOCOL.md); figures below are those of the
current build and are final at the v1.0 release.

## Motivation

- **Why was it created?** To have a complete, verifiable record of how nine major Serbian
  online outlets covered the first six months of the protest movement that began with the
  collapse of the Novi Sad railway-station canopy on 1 November 2024, built by a written
  method that others can check and reuse. A topic-filtered collection cannot show what it
  missed; this one indexes all news and marks the story within it.
- **Who created it?** Ratko Nikolić, as an independent open project.
- **Funding:** none. Paid API use (embeddings, classifier) is self-funded and reported in
  `PROTOCOL.md`.

## Composition

- **Instances:** news articles (editorial items on an outlet's website, identified by URL),
  published 1 Nov 2024 – 30 Apr 2025 by nine outlets: Blic, Danas, Informer (dailies);
  RTS, B92, Pink (TV); N1, Telegraf, Nova (online brands).
- **Count:** 217,660 URLs reached; 216,050 articles in the corpus. Per outlet: Blic 37,910 ·
  Telegraf 37,615 · Informer 30,217 · Danas 27,039 · N1 23,064 · Pink 21,146 · Nova 17,860 ·
  B92 14,432 · RTS 6,767.
- **Is it a sample?** It aims at the full population of news articles of these outlets in the
  window, after excluding non-news sections by URL path (`PROTOCOL.md` §3.2). Completeness by
  outlet is reported in `coverage.parquet`; RTS is the least complete (`PROTOCOL.md` §8).
- **What each instance holds (released):** URL, final URL, outlet, status, publication and
  fetch time (UTC), date source, discovery route, sha256 of the stored page and of the
  extracted body, body length, extractor version; and in the scope layer: lexicon hits, band
  score and stratum, classifier decision and clauses.
- **Labels:** 300 articles hand-labelled for scope by three coders (`gold/scope_labels/`);
  scope decisions for all articles by the three-stage procedure (`PROTOCOL.md` §5).
- **Not released:** article text, titles, lemmas, stored pages, embedding vectors (copyright
  of the outlets; the hashes make the text verifiable without publishing it).
- **Errors and noise:** extraction checked per outlet (`docs/extraction_qa.md`); publication
  dates read from the page for all but 221 articles (discovery date instead); text as
  collected in Oct 2026, which may differ from the text at publication.
- **Confidentiality and sensitivity:** published journalism only. Articles name people,
  including private individuals; the release carries no text, and no field identifies a
  person. Articles about the story concern a contested political conflict; the scope layer
  records only whether an article is about the story, never a judgement of its content.

## Collection process

- **How:** URLs from Media Cloud daily dumps, outlet sitemaps, naslovi.net listings, RTS
  listings and an article-ID completeness pass; each page fetched once by a polite crawler
  (robots.txt including Crawl-delay, ≥ 2 s per host, identified user agent, no logins, no
  paywall circumvention, no comments).
- **When:** 2–6 October 2026, for articles published 1 Nov 2024 – 30 Apr 2025.
- **Outlet selection:** by reach and media type, by a rule fixed before collection
  (`PROTOCOL.md` §2); political alignment played no part.
- **Ethics:** public pages only, collected with the outlets' robots.txt and terms respected;
  outlets whose terms forbid automated copying were not collected. No personal data is
  released.

## Preprocessing

Text extraction (trafilatura 2.3.0 with per-outlet rules), lossless Cyrillic-to-Latin
transliteration, lemmatisation (CLASSLA 2.2.3), embeddings (gemini-embedding-2), then the scope
stages. The raw pages are kept privately, so every step can be rerun.

## Uses

- **Intended:** research on news coverage of the story; method research on topic scoping and
  dataset validation; as a frame (the index) to re-collect text for non-commercial research
  where the law allows text and data mining.
- **Not suited for:** comparing outlets' quality or bias without further annotation (the
  dataset makes no such judgement); claims about outlets not collected (§2.3 of the protocol);
  anything requiring the text as published rather than as collected.

## Distribution

- **Where:** GitHub (code, documents, gold labels) and versioned release files with a DOI.
- **Licences:** code Apache-2.0; derived data and documents CC BY 4.0. The articles themselves
  remain the outlets' property and are not distributed.

## Maintenance

- **Maintainer:** Ratko Nikolić (GitHub issues).
- **Versions:** a new version for any change to the method or the data, with a changelog; an
  erratum never rewrites a released version.
