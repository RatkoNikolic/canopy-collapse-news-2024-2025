# Extraction quality check (extractor history up to `doc-v8`)

The record of how article text is extracted and how well it works per outlet. Aggregate figures only; no article text.

## Method

- **Extractor:** trafilatura 2.3.0 for every outlet, plus per-outlet fixes in `registries/extraction.csv`, each with its reason. A known article container is read block by block (paragraphs, headings, list items, quotes), skipping scripts, ad slots, share, related and recommended widgets, comments and figures.
- **Automatic metrics** (all documents): empty (< 200 chars) and short (< 500) bodies, median length, missing title or lead, repeated paragraphs, leftover boilerplate phrases (`canopy_news.qa.BOILERPLATE`).
- **Browser comparison:** a seeded sample of fetched articles loaded live in Chromium through Playwright (robots.txt obeyed, ≥ 2 s per host, project user agent, third-party hosts, images, media and fonts blocked). Measured per article:
  - `raw_in_page`: share of our extracted paragraphs visible on the rendered page;
  - `rendered_extra`: share of paragraphs a generic extraction of the rendered page finds that ours lacks, with the extra paragraphs listed;
  - whether the lead is visible.
- **Visual check:** screenshots reviewed by Claude for the outlets that needed fixes.

## Fixes (from `doc-v1` to `doc-v5`)

| Outlet | Problem found | Fix |
|---|---|---|
| Informer | teaser lists outside the article were extracted as body (browser check: only 7–15% of extracted text visible to a reader); inside the container, recommended-news blocks and comment rules | read only `div.single-news-content`; lead taken from its `h5`; recommended, comments, next-news, tags and ad blocks skipped |
| N1 | "Oglas" ad labels, "most read" / "latest" labels and the comments prompt after the article | drop those lines; end the article at the comments prompt |
| Danas | social and newsletter prompt appended to every article | drop that line |
| Telegraf | titles from an embedded promoted-video widget ("Video: …", the same titles across unrelated articles) | drop "Video:" lines |
| Nova | trafilatura merged photo captions and the article into single lines and kept the header (browser check: 6% of extracted text visible) | read only the body container (`article.article-wrapper … div.xl:mx-20`); end at the social prompt; drop the "Bonus video" line |
| all | headline repeated as the body's first line | dropped |

## Results

Blic, Danas, Informer, N1, Pink, Telegraf: `doc-v3`, 2,818 documents; Nova and RTS: `doc-v5`, 450 and 400 documents.

| Outlet | Docs | Median chars | Short (< 500) | Empty (< 200) | Repeated paragraphs | Browser: extracted text visible | Browser: lead visible |
|---|---|---|---|---|---|---|---|
| Blic | 356 | 1,729 | 3% | 0% | 1% | 100% | 12/12 |
| Danas | 352 | 1,846 | 3% | 0% | 0% | 100% | 12/12 |
| Informer | 350 | 1,344 | 7% | 1% | 1% | 100% | 12/12 |
| N1 | 350 | 1,710 | 7% | 2% | 1% | 100% | 12/12 |
| Pink | 352 | 1,279 | 11% | 0% | 4% | 100% | 12/12 |
| Telegraf | 1,058 | 1,922 | 1% | 0% | 0% | 100% | 12/12 |
| Nova | 450 | 1,819 | 6% | 0% | 1% | 99% (min 83%) | 8/12 * |
| RTS | 400 | 2,508 | 3% | 3% | 2% | 99% (min 89%) | 11/11 |

\* Nova's lead comes from its meta description, which is sometimes worded differently from the visible lead; the body is complete. RTS pages are Cyrillic: the Latin conversion is stored with the original.

**Extra paragraphs found only on the rendered pages** were, without exception, content excluded on purpose: recommended-story teasers (Informer), other stories' headlines and the comments prompt (N1, Telegraf), the social prompt (Danas). **No outlet loads article text with JavaScript**: the stored HTML contains the full article.

**RTS header furniture (`doc-v6`, 2026-10-04).** The browser check passed RTS, but the header lines above the body were extracted as body text: the date line ("četvrtak, 14.11.2024, 05:55 -> 06:01", split over two lines on live blogs), "Izvor: RTS", "Autor: …" and the repeated headline, in 335 of 400 sampled articles. They also named the outlet to blind coders. `doc-v6` drops them (rules in `registries/extraction.csv`, matched on each line's Latin form because RTS pages are Cyrillic) together with the live-blog "Opširnije / Kraće" buttons. Re-check on 400 RTS articles: no furniture left, no article text lost; 300 articles of other outlets unchanged from `doc-v5`. Known, accepted: RTS live blogs keep blank padding lines inside the body (no effect on text or offsets of the paragraphs themselves); daily exchange-rate pages ("Kursna lista") carry the site menu (service pages, out of scope).

**RTS Latin edition vs our transliteration (2026-10-04).** 20 random RTS articles fetched again from `/lat/` and extracted with `doc-v6`: title and body identical to our Latin conversion of the stored Cyrillic page in 20 of 20 (no character differs). The Cyrillic pages are kept; the `/lat/` pages of the check are in `raw/` under index `rts-lat-check`.

Residual, accepted: in-body cross-references written by the outlet itself ("više o tome u posebnom tekstu", ≈ 3% of Blic articles); they are the outlet's own text.

**B92 (`doc-v7`, 2026-10-05).** Offline metrics flagged repeated paragraphs in 67% of B92 articles and a median length twice the other outlets'. Cause: every B92 page carries ≈ 30 teasers of the *current* news (`article.news-item`, dated at fetch time — October 2026) and they were extracted as body text, so 2024–25 articles held 2026 text (future leakage). On 300 articles the old bodies were ≈ 70% teasers (median new/old length 0.29). `doc-v7` takes the body from `div.single-news-content` (233 → 0 articles with fetch-time teasers; the remaining "2026" mentions are forecasts in the article text) and drops the in-body "Možda vas zanima" label. Browser comparison (12 articles, 2026-10-05, after its fetch ended): 100% of our paragraphs visible on the rendered page in 10 of 11 articles; the extra rendered text is the teasers excluded on purpose. The 11th (78%) showed a second leak: related-article teasers embedded *inside* the body container (`article.news-item` with time, date and a fetch-time "N d" counter), in 162 of 14,432 B92 articles. `doc-v8` skips `news-item` elements inside a container (60/60 cleaned; 0 of 60 per other outlet changed). Metrics after `doc-v8`: repeated paragraphs 1.7% (was 67%), median 1,346 characters; residual "Pročitajte još" cross-references in 3.4% (the outlet's own text, as accepted for Blic). The QA sample and metrics now skip error records (soft 404s).

**Soft 404s (all outlets, `doc-v7`).** Some removed articles answer with a redirect to a section page and status 200 (B92 136, Pink 53, Informer 29, Danas 6, Blic 1): the stored page is a listing, not the article. Such records now carry `error = soft_404` and an empty body (out of the corpus); the fetcher records them as gone (`reason = redirected_to_listing`) and coverage counts them as gone. Other outlets' extraction is unchanged by `doc-v7` (400 of 400 identical to `doc-v6`).

## Pending

Nothing pending for extraction: all 9 outlets checked.
