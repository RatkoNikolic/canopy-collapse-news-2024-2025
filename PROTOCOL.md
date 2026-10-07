# Protocol

**canopy-collapse-news-2024-2025, v1.0.** How the dataset was built, from the choice of outlets
to the set of articles about the story, and how that set is validated. It describes what was
done. It was finalised after collection (2–6 Oct 2026) and **before any gold label and before
the classifier run**; decisions taken during collection, and what prompted them, are listed in
[Appendix A](#appendix-a-decisions-made-during-collection). Commands for every step are in
[`REPRODUCE.md`](./REPRODUCE.md).

Three rules apply in order, each mechanical and written down before it was used on the data
it governs:

1. **Outlets** (§2): which outlets are collected.
2. **Collection** (§3–4): how their articles are found, fetched and turned into text. No topic
   filter.
3. **Scope** (§5–6): which collected articles are about the story, applied to every outlet
   alike and validated against human labels.

Nothing in the selection uses a judgement of an outlet's political alignment. Alignment is
described afterwards, from named third-party sources, as a balance check (§2.4).

---

## 1. The dataset

- **Story:** the protest movement in Serbia that began with the collapse of the canopy at the
  Novi Sad railway station on 1 November 2024.
- **Window:** 1 November 2024 → 30 April 2025, inclusive (six months from the collapse),
  by publication date. Its id in the run manifests and the event log is `story-v01`.
- **Unit:** a news article: an editorial item on an outlet's website, identified by its URL.
- **Layers:** (1) an **index** of every news article the nine outlets published in the window
  that the collection reached, whether or not it concerns the story; (2) a **scope layer**
  marking the articles about the story (§5), with its validation (§6).
- **Text is not published.** The release carries URLs, dates, hashes and derived records (§7).

---

## 2. Outlets

### 2.1 The eligible outlets

An **outlet** is an editorial news website, identified by its domain(s). Excluded by
definition: aggregators (naslovi.net serves only as a discovery route), social-media accounts,
non-news verticals, and outlets without an editorial base in Serbia (the Serbian-language
services of foreign media: RFE/RL, BBC, Al Jazeera Balkans, Sputnik, RT Balkan).

The template is the OSCE/ODIHR election media-monitoring sample (public media first; the main
private outlets by audience and reach; all important national dailies; then fix the sample)
and the Media Ownership Monitor Serbia's per-sector rule. An outlet is **eligible** if it meets
at least one tier:

| Tier | Criterion | Source |
|---|---|---|
| **A. Reach** | Listed among Serbia's online news brands, at any weekly-use figure, in the Reuters Institute *Digital News Report* (DNR) 2025 or 2026 | DNR Serbia pages and their chart data |
| **B. National TV** | The website of every holder of a national-frequency TV licence, and of the public service broadcasters (RTS; RTV for Vojvodina) | REM licence register (licences 561–564/2022: Pink, Happy, Prva, B92; valid 2022–2030) |
| **C. National dailies** | The website of every national general-news daily in print on 1 Nov 2024 | MOM Serbia print list `[VERIFY each against the APR media register]` |
| **D. News agencies** | The public web output of the national news agencies | Tanjug, Beta, FoNet |

"Listed at any figure" has no free parameter: every DNR-listed Serbian brand sits at 11% weekly
use or more, so a threshold below 11% changes nothing and any higher one would need a
justification of its own. DNR is the only source that measures every brand with one method and
is free, citable and archived; Gemius covers only sites that pay for measurement, and
Similarweb's free tier shows five sites.

An eligible outlet is **collectable** if, on 2 Oct 2026: (1) its articles are openly available
as full text; (2) its robots.txt allows a generic research crawler on article paths; (3) its
terms of use contain no clause against automated access, copying by programs or text and data
mining; (4) its site answers requests from the project's identified user agent.

**Eligible and collectable (19):** N1, Blic, Telegraf, Danas, BIRN Srbija, Nova, Radar, RTS,
Srbija danas, B92, Informer, Prva, Pink, Happy, Politika, Večernje novosti, Alo, Srpski telegraf
(web: republika.rs), Tanjug. Domains and tiers: `registries/outlets.csv`.

**Eligible but not collectable (recorded, not collected):**

| Outlet | Tier | Failed condition |
|---|---|---|
| Kurir, Mondo | A (Kurir also C) | (3) the publisher's terms forbid copying and automated programs |
| Južne vesti | A | (4) answered 403 to a non-browser user agent |
| RTV | B | (2) robots.txt disallows all but named search engines |
| Beta, FoNet | D | (1) the public sites carry briefs or teasers only |

Not in any tier, listed so the omissions are visible: Espreso, Objektiv, Nedeljnik, NIN, Vreme,
Insajder, KRIK, Euronews Srbija, Glas zapadne Srbije, 021, Dnevnik.

### 2.2 The nine collected outlets

The dataset collects **the three outlets with the highest DNR 2026 online weekly use within
each type**, ties broken by measured news volume. An outlet that meets several tiers counts in
the type of the medium the brand started in.

| Type | Collected (DNR 2026 weekly use, %) | Not collected |
|---|---|---|
| National dailies (tier C, DNR-listed) | Blic (30), Danas (20), Informer (12) | Politika, Večernje novosti, Alo (not DNR-listed) |
| National TV and the public broadcaster (tier B) | RTS (19), B92 (15), Pink (12; tied with Prva, Pink publishes ≈ 150 news items a day to Prva's ≈ 2) | Prva, Happy |
| Online brands (tier A only) | N1 (36), Telegraf (23), Nova (21; its portal predates its print daily, launched Oct 2020) | BIRN (20), Srbija danas (18), Radar (12) |
| News agency (tier D) | none: agency copy reappears in the collected outlets | Tanjug |

The nine carry ≈ 55% of the news volume of the collectable outlets. Counting Nova as a daily
instead would replace Informer with BIRN Srbija (Appendix A1).

### 2.3 What the selection costs

Kurir and Mondo are two of the four most-used DNR brands, and RTV is the public broadcaster of
the story's city; none could be collected (§2.1). Absence from the dataset is not absence from
the media.

### 2.4 Balance check (description, not selection)

Characterisations by named third parties, never by this project, reported only to show whether
the collected outlets span the spectrum: DNR 2026 names N1, Nova and Danas among "the more
critical media" and Informer and Pink as "pro-government brands", and describes the national
commercial channels as "owned by Serbian companies tied to the political elites" (B92); the
EU Media Pluralism Monitor 2026 assesses the public broadcaster (RTS) as at high risk of
pro-government bias; Blic and Telegraf are commercial outlets without such a characterisation
in these sources. Ownership changes after the window (N1 and Nova, Aug 2026) do not affect it.

---

## 3. Collection

### 3.1 Discovery: finding every article URL

No single source lists every article, so URLs come from several **discovery routes**, each
recorded with every URL it found:

| Route | What it is | Outlets |
|---|---|---|
| Media Cloud | its public daily dumps of news RSS items | Blic, Danas, Informer, N1, Nova, Pink, Telegraf |
| Outlet sitemaps | the outlet's own sitemaps reaching back to Nov 2024 | Blic, Telegraf, N1, Nova, Danas |
| naslovi.net | the aggregator's per-day, per-section listings, each item resolved to the original URL | RTS, B92 |
| RTS listings | RTS's own news-section listings, paged back to the window | RTS |
| ID completeness | article IDs inside the window's range that no route found, requested by ID; the page's canonical URL identifies the article | Pink, Informer |

There is **no topic filter**: every article URL of a collected outlet dated in the window is
fetched, because a topic filter at collection biases the sample in ways a later filter cannot
undo.

### 3.2 Non-news sections

Sections that are not news are excluded **by URL path**, per outlet, with a reason for each
(`registries/nonnews.csv`): sport; celebrity, entertainment and reality shows; lifestyle
(health, horoscope, recipes, pets, auto); TV promotions; English editions; quizzes, comics,
weather; print-edition front pages (a photo of the page, no article text); and BBC syndication
republished by Danas and Blic (the BBC bans text and data mining of its content). News, world,
business, regional, culture, science and technology and opinion are kept. The list is applied
before fetching; sections added to it after their pages were fetched are applied again at the
scope stages (§5), so the corpus is the same either way.

### 3.3 Fetching

- One fetch per URL. robots.txt is obeyed, including `Crawl-delay`; a host whose robots.txt
  answers 401/403/5xx is skipped for the pass.
- At least 2 seconds between requests to one host; `Retry-After` honoured on 429/503.
- No logins, no paywall circumvention (open text only), no reader comments.
- The collection passes identified themselves as `srb-media-dossier/0.1 (research crawler; one
  polite fetch per article; +https://github.com/RatkoNikolic/srb-media-dossier)`, the working
  name of the project at the time, recorded in every fetch manifest. Later requests (`verify`)
  use `canopy-collapse-news/1.0 (…; +https://github.com/RatkoNikolic/canopy-collapse-news-2024-2025)`.
- Every stored page is kept under the sha256 of its bytes; every request (time, status, final
  URL, robots decision, bytes, outcome) is logged in the pass's `fetch_attempts`.
- Collection ran 2–6 Oct 2026.

### 3.4 Dates

The publication time is read from the page: JSON-LD `datePublished`, `article:published_time`,
`itemprop`, then RTS's visible date header (Belgrade time); otherwise the discovery date is
used and marked as such (`date_source`). Every time is stored in UTC. A later correction is
appended to the log as a new record, never written over the old one, and every reader takes
the latest record per URL.

### 3.5 Removed articles

A URL that answers 404/410 is recorded as **gone**, as is a **soft 404**: a removed article
that redirects to a section page with status 200 (the requested URL carries an article ID, the
final URL does not).

### 3.6 Result

**217,660 URLs** reached; **216,050 articles** in the corpus (in the window, with text, not in
an excluded section): Blic 37,910 · Telegraf 37,615 · Informer 30,217 · Danas 27,039 ·
N1 23,064 · Pink 21,146 · Nova 17,860 · B92 14,432 · RTS 6,767. The rest: 1,089 pages dated
outside the window by the page itself (533 of them RTS, from the margins its listing route
fetches around the window's edges), 350 gone, 171 in sections excluded after fetching (§3.2).
Every URL and its status: `index.parquet`; per outlet and day: `coverage.parquet` (§7).

---

## 4. Processing

- **Text extraction.** trafilatura 2.3.0 for every outlet, plus per-outlet rules where a
  quality check failed (`registries/extraction.csv`, each rule with its reason): article
  containers for Informer, Nova and B92; removal of page furniture lines for N1, Danas,
  Telegraf and RTS; teasers inside article containers skipped. Extractor version `doc-v8`.
  The check per outlet: empty and short bodies, length distribution, repeated paragraphs,
  leftover boilerplate, and a comparison of ≈ 100 articles with the browser-rendered page
  (Playwright), which also catches text loaded by JavaScript.
- **Script.** Cyrillic pages (RTS) are transliterated to Latin losslessly and keep the
  original as metadata; on a check of 20 articles the transliteration is character for
  character RTS's own Latin edition.
- **Records.** Per article: title, lead, body with paragraph offsets, publication date,
  section, extractor version, body length and the **sha256 of the extracted body**.
- **Lemmas.** CLASSLA 2.2.3, Serbian standard models (`tokenize, pos, lemma`), over title,
  lead and body. Model files by sha256: lemma `8e75086b…f835395`, pos `dba8c6a1…c29314ea`,
  pretrain `563b3847…7a09ef`.
- **Embeddings.** `gemini-embedding-2`, 768 dimensions, Gemini Batch API; input
  `title: <title> | text: <lead and body>`, at most 8,000 characters; 216,221 documents (the corpus and the 171 pages excluded after fetching). The
  vectors are not released (§7).

---

## 5. Scope: which articles are about the story

### 5.1 Definition

An article is **in scope** if its headline, or at least one full paragraph, concerns one of:

1. **The collapse and its direct consequences:** victims and their number; commemorations; the
   investigations and prosecutions over the collapse and the station's reconstruction
   (including corruption); the reconstruction, its contracts and documentation.
2. **The movement's own actions:** protests, blockades (of faculties, schools, roads,
   institutions), plenums and citizens' assemblies, marches, strikes, the movement's demands
   and statements.
3. **Responses to the movement:** by the government, president, parties, institutions,
   police, courts, universities and other groups, including counter-mobilisation, incidents
   and violence at or against protests, arrests and prosecutions of participants, and
   campaigns about the movement.
4. **Political consequences the article itself ties to the collapse or the movement:**
   resignations, the fall and formation of governments, talk of elections.

Everything else is **out**, including politics, economy, foreign affairs, crime or culture
that the article does not itself connect to the collapse or the movement. The connection must
be in the text. The working form of this definition, with rules for hard cases and examples,
is the codebook ([`CODEBOOK.md`](./CODEBOOK.md)), used alike by the classifier and the human
coders.

Three stages apply the definition, each to every outlet identically: a word list finds likely
articles, an embedding ranking finds likely articles the word list missed, and a classifier
decides.

### 5.2 Stage 1: the lexicon

An article is a **candidate** if its text or lemmas match any term in
`registries/lexicon.csv`, in four lists:

- **collapse** (neutral): the canopy with Novi Sad or the station; the collapse of the canopy;
  the Novi Sad tragedy; 11:52 with Novi Sad; victim counts with Novi Sad; 15/16 minutes of
  silence; the railway infrastructure company; the prosecutors' offices in the case;
  the station's reconstruction;
- **neutral movement terms:** students with blockade, faculty blockade, plenum, protest;
- **protester-side** and **government-side** vocabulary, always included **as a pair**
  (e.g. *ruke su vam krvave*, *pumpaj*, *studentski zahtevi*, *zbor* / *blokaderi*,
  *obojena revolucija*, *tajkunski mediji*, *studenti koji žele da uče*), so the list reaches
  coverage written from either side.

Person names are never terms. The lexicon was written on 2 Oct 2026 and has not changed.
**Result:** 42,971 of the 216,050 articles are candidates (19.9%); by outlet from 6.1% (Telegraf)
to 38.6% (N1).

### 5.3 Stage 2: the embedding band

Every article gets a score: the cosine similarity of its embedding to the **story centroid**.
Before human labels exist, the centroid is built from the lexicon candidates and is
**outlet-balanced**: the mean of each outlet's own candidate centroid, so each outlet weighs the
same (candidate rates differ from 6% to 39% by outlet, and a pooled mean would lean towards how
the outlets with most candidates write). Non-candidates are then split by score into
**band-top10** (top decile, ≈ 17.3k), **band-next20** (next two deciles, ≈ 34.6k) and **rest**
(≈ 121k). The score separates candidates from the rest well (AUC 0.916), and the top of
band-top10 holds plainly in-scope articles from both sides of the coverage that use none of the
lexicon's terms.

### 5.4 Stage 3: the classifier

A language model applies the codebook to each article and returns the codebook's output
object: in scope or not, the clauses, the paragraph that decides, and a confidence. The prompt
is the codebook verbatim plus the article as the coders see it: title, date, lead, numbered
paragraphs, never the outlet or the URL.

- **Model:** `claude-sonnet-5-5`, thinking off (`between_tools`), through the Message Batches
  API, structured output enforced by a JSON schema. The model accepts no sampling parameters,
  so it runs at its default; models that accept them run at temperature 0. The model, its
  settings and the codebook's sha256 are recorded in the run manifest.
- **Why this model:** chosen on a pilot of 60 articles **outside the gold set** (40 candidates,
  20 band-top10) against Claude Haiku 4.5 and Sonnet 5.5 with low-effort thinking. Haiku
  called out articles that read as in scope under the codebook, including articles in one
  side's vocabulary (codebook rule 1), and broke the output format in 15 of 60; thinking added
  nothing. The gold set is **not** used to choose the model, so it stays an unbiased test.
- **What it reads:** every lexicon candidate and every band-top10 article (≈ 60k). The gold set
  (§6) estimates how many in-scope articles lie in band-next20 and rest; if that estimate is
  above 5% of all in-scope articles for a stratum, the classifier is run on that stratum too
  and the result reported as such.
- An article the classifier does not read is out of scope.

---

## 6. Gold set and validation

### 6.1 Pre-registration

The gold set is fixed in three timestamped steps, so a reviewer can check that nothing in it
was chosen after seeing a result:

1. **The procedure** (this section, the code in `src/canopy_news/labels.py`, the codebook and
   the exclusion list) is committed and timestamped **before** the seed exists.
2. **The seed** comes from the public randomness beacon of the League of Entropy (drand
   mainnet, chain `8990e7a9…51b2ce`): **round 6531446, published at 2026-10-07 12:00:00 UTC**. Nobody,
   including the authors, can know or influence that value in advance, and anyone can fetch it
   later. Two seeds are derived from it: sha256(randomness ‖ "sample") and
   sha256(randomness ‖ "assignment"), first 64 bits each.
3. **The draw** (`canopy-news labels draw --set gold-v1 --round 6531446`), its sample,
   assignment and beacon record, is committed and timestamped **before the first label**.

Timestamps are OpenTimestamps proofs (`timestamps/*.ots`) over a file listing the commit and
the sha256 of each fixed file; they anchor in the Bitcoin blockchain and can be checked with
`ots verify`. A sample drawn during development was discarded unlabelled (Appendix A).

### 6.2 The gold set (`gold-v1`)

300 articles drawn at random from the corpus articles with a non-empty body (216,036),
stratified by scope stratum × outlet, so the strata near the boundary are well represented:

| Stratum | Articles in it | Drawn |
|---|---|---|
| Lexicon candidates | 42,969 | 200 |
| band-top10 | 17,307 | 40 |
| band-next20 | 34,614 | 30 |
| rest | 121,146 | 30 |

Within each stratum the draws are spread over outlets: at least 3 per outlet (capped by the
stratum's size), the rest in proportion to size by largest remainder. Every article carries
its design weight N_h / n_h, so every estimate is design-based. The 60 articles of the
classifier pilot (§5.4) are never drawn (`gold/scope_labels/exclude.jsonl`): models, and the
authors while reading the pilot's disagreements, have seen them.

### 6.3 Coding

- **Coders:** three (R1, R2, R3). **50 articles are coded by all three**, independently; the
  other 250 are split evenly. The shared set is a systematic draw over the sample ordered by
  stratum × outlet; the rest are dealt out in turn in the same order, so every coder's share
  is balanced by stratum and outlet (within one article per stratum).
- **Blind:** each coder works on a page with only their articles, showing title, date, lead and
  numbered paragraphs, never the outlet, the URL, the stratum or any model output. Coders work
  alone, do not look articles up, and do not see the sample file (the repository stays private
  until labelling ends). Instructions: [`LABELLING_GUIDE.md`](./LABELLING_GUIDE.md).
- **Output per article:** in scope or not, clauses, the deciding paragraph, confidence (and an
  optional note). Each label carries the codebook's sha256.
- **Agreement:** Krippendorff's α on the shared 50, for scope and per clause. The label used
  for a shared article is the majority of the three.

### 6.4 Estimates

Reported whatever they are, each with a 95% interval:

- **Precision:** the share of articles the pipeline puts in scope that the coders put in scope.
- **Recall:** the share of in-scope articles (estimated over all strata with the design
  weights) that the pipeline puts in scope; the strata the classifier does not read count as
  missed.
- **Per-outlet error:** precision and recall by outlet. Movement vocabulary differs by side,
  so per-outlet recall is the symmetry check.
- **Classifier stability:** the classifier run twice on the gold set; agreement reported.
- **Agreement between coders** (§6.3).

Intervals: Wilson for simple proportions, bootstrap over the stratified design for recall.

---

## 7. Release and verification

**Published:** the code; the registries; this protocol, the codebook and the guide; the gold
sample, assignment and labels (decisions only); and, per version, attached to the release:

| File | Content |
|---|---|
| `index.parquet` | one row per article URL reached in the window: outlet, status (`article`, `gone`, `dated_out`, `excluded_section`, `no_text:<reason>`), publication and fetch times (UTC), date source, discovery route, sha256 of the stored page and of the extracted body, body length, extractor version |
| `scope.parquet` | per article: lexicon hits by list, band score and stratum, classifier decision and clauses |
| `coverage.parquet` | discovered, fetched, dated out, gone and failed URLs per outlet × day |
| `manifest.json`, `SHA256SUMS` | version, code commit, counts, lexicon, embedding and codebook versions; file checksums |

**Not published:** stored pages, article text, titles, lemmas, and the embedding vectors.

**Verification without the text.** Anyone can fetch a URL from the index, extract it with the
published code and compare the body's sha256 with `body_sha256`: equal means the same text,
different means the outlet has since edited or removed it. `canopy-news verify` does this for
a seeded sample per outlet; on 6 Oct 2026, 179 of 180 articles (20 per outlet) were unchanged.
The scope layer can be checked from the published scores and strata; recomputing the scores
needs the embeddings again (≈ $17) and the same model version.

---

## 8. Known limits

- **RTS** is in no general archive; its own listings and naslovi.net give ≈ 37 news articles a
  day against ≈ 60 estimated from its output, so RTS is the least complete outlet.
- **B92** rests on naslovi.net alone.
- **221 articles** (220 B92, 1 RTS) declare no publication date and carry the discovery day
  (`date_source = discovery_day`).
- **Edits after publication:** the collected text is the text at fetch time (Oct 2026), not
  necessarily at publication.
- **Excluded outlets** (§2.3) leave gaps, notably Kurir, Mondo and RTV.
- **Embedding-dependent stage:** the band (§5.3) depends on a hosted model; a different model
  or version gives a different ranking.

---

## Appendix A. Decisions made during collection

Decisions taken after the start of the work, in the order they were made, with what prompted
them. None was taken after seeing any gold label or classifier output on the gold set.

| # | Date (2026) | Decision | Prompted by |
|---|---|---|---|
| A1 | 2 Oct, before any fetch | Collect 9 of the 19 eligible outlets (three per type, §2.2). The rule assigning multi-tier outlets to a type was fixed after the nine had been drafted; counting Nova as a daily would replace Informer with BIRN Srbija. | Cost of processing; disclosed because the assignment rule came second. |
| A2 | 2 Oct, before any fetch | Collect only the six-month window from the collapse. | Scope of the dataset. |
| A3 | 2 Oct, before fetching | Exclude non-news sections by URL path (§3.2). | The unit is a news article; ≈ 42% of URLs were non-news. |
| A4 | 4–5 Oct | Two discovery routes added after gaps showed in the coverage: RTS's own listings; the ID completeness pass for Pink and Informer (+431 and +440 news articles). Six Pink sections were added to the non-news list when the ID pass reached them. | Coverage per outlet × day. |
| A5 | 2–5 Oct | Extractor revised per outlet after quality checks, up to `doc-v8` (§4); each rule recorded with its reason. | Extraction QA, including B92 pages that appended news teasers from the fetch date. |
| A6 | 4 Oct | Embeddings by `gemini-embedding-2` instead of a local model. | The local model returned invalid vectors on the available hardware. |
| A7 | 6 Oct | Blic's `/print/` section (photos of the print front page) added to the non-news list after fetching; its 170 pages leave the corpus at the scope stages. | A verification refetch flagged one such page. |
| A8 | 6 Oct, before any label | The embedding band (§5.3): outlet-balanced centroid, strata by decile; the gold sample's quotas (§6.2). | Candidate rates differ by outlet 6–39%. |
| A9 | 6 Oct, before any label | Three coders with a 50-article overlap (§6.3). | Three coders available; the overlap measures how clear the codebook is. |
| A10 | 6 Oct, before any label | The classifier model, from a pilot on 60 articles outside any gold sample (§5.4); no temperature setting on that model. | Pilot results. |
| A11 | 7 Oct, before any label | A gold sample and assignment drawn on 6 Oct with fixed seeds during development were **discarded unlabelled**, and the gold set was redrawn under the pre-registered procedure with a beacon seed (§6.1). The pilot articles are excluded from the draw. | A seed chosen by the authors cannot be shown not to have been chosen after looking; a public beacon seed can. |

The working history of these decisions is kept in the project's private development
repository and is available to reviewers on request.
