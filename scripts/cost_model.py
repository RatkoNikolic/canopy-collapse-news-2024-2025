#!/usr/bin/env python3
"""Cost of the dataset's paid steps, from measured inputs. Run: python3 scripts/cost_model.py

Embeddings: gemini-embedding-2 on the Gemini Batch API ($0.10 per 1M input tokens), 806 tokens
per article (Gemini count_tokens on 200 documents: title + lead + body <= 8,000 characters,
2.95 characters per token).

Classifier (stage 3, PROTOCOL.md §5.4), Anthropic Message Batches (half the standard price):
articles per stratum and mean characters (title + lead + body, capped at 12k) measured on the
documents; characters per token and prompt tokens from count_tokens (Haiku 4.5: 2.77, Sonnet
5.5: 2.08). Haiku 4.5's minimum cacheable prefix (4,096 tokens) exceeds the prompt (codebook +
instruction), so it is billed in full; Sonnet 5.5 caches it (reads at 0.1x, writes at 1.25x).
Output ≈ 80 (Haiku) / 100 (Sonnet) tokens per article, measured on a 60-article pilot.
"""

HAIKU_B = (0.50, 2.50)     # $/1M tokens, batch: input, output
SONNET_B = (1.00, 5.00)
CACHE_READ, CACHE_WRITE = 0.10, 1.25

ARTICLES = 216_221
EMB_TOK, EMB_PRICE = 806, 0.10
STRATA = {"candidate": (42_971, 3072), "band-top10": (17_326, 1836),
          "band-next20": (34_649, 2063), "rest": (121_275, 2426)}
COVER = {"candidates + band-top10": ["candidate", "band-top10"],
         "+ band-next20": ["candidate", "band-top10", "band-next20"], "all": list(STRATA)}

print(f"Embeddings, {ARTICLES:,} articles x {EMB_TOK} tokens, batch: "
      f"${ARTICLES * EMB_TOK * EMB_PRICE / 1e6:,.0f}")
print("\nClassifier, batch:")
for name, ss in COVER.items():
    n = sum(STRATA[s][0] for s in ss)
    haiku = (sum(STRATA[s][0] * (STRATA[s][1] / 2.77 + 1758) for s in ss) * HAIKU_B[0]
             + n * 80 * HAIKU_B[1]) / 1e6
    art = sum(STRATA[s][0] * STRATA[s][1] / 2.08 for s in ss)
    sonnet = [((art + n * 2362 * (h * CACHE_READ + (1 - h) * CACHE_WRITE)) * SONNET_B[0]
               + n * 100 * SONNET_B[1]) / 1e6 for h in (0.9, 0.5)]
    print(f"  {name:26s} {n / 1e3:5.0f}k  Haiku 4.5 ${haiku:4.0f}   "
          f"Sonnet 5.5 ${sonnet[0]:4.0f}-{sonnet[1]:4.0f} (cache hit 90% / 50%)")
