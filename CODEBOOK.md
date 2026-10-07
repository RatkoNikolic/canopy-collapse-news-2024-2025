# Scope codebook v1 — is this article part of the story?

**Status: v1, frozen before any gold label.** The written instructions the relevance classifier (stage 3) applies to every article it is run on (lexicon candidates and the embedding band), and that human coders apply to the gold set. One codebook for both, so the classifier is measured against the same definition people use. The definition is `PROTOCOL.md` §5.1. Any change after the first gold label makes a new codebook version, recorded in `PROTOCOL.md`, and the validation is redone.

## The story

The protest movement in Serbia that began with the collapse of the canopy at the Novi Sad railway station on 1 November 2024, followed from 1 November 2024 to 30 April 2025.

## Decision

For each article, read the title, the lead and the body, and answer:

**Is the article IN SCOPE?** Yes if its headline, or at least one full paragraph, concerns one of the four clauses below. Mentions in a passing phrase do not count. If yes, give **every clause that applies**.

| Clause | The article concerns… | Includes | Does not include |
|---|---|---|---|
| **1 — Collapse** | the collapse of the canopy and its direct consequences | victims and their number; commemorations and silent tributes; investigations and prosecutions over the collapse and the station's reconstruction (including corruption); the reconstruction, its contracts and its documentation | other construction accidents; railway news unrelated to the collapse |
| **2 — Movement** | the movement's own actions | protests, blockades (of faculties, schools, roads, institutions), plenums and citizens' assemblies, marches, strikes, the movement's demands and statements | protests elsewhere in the world; earlier protests (e.g. lithium, 2023) unless the article ties them to this movement |
| **3 — Responses** | responses to the movement | statements and actions of the government, president, parties, institutions, police, courts and universities about the movement; counter-mobilisation and counter-camps; incidents and violence at or against protests; arrests and prosecutions of participants; campaigns about the movement | responses to unrelated events |
| **4 — Political consequences** | political consequences the article itself ties to the collapse or the movement | resignations; the fall and formation of governments; talk of elections, when the article links them | ordinary politics, appointments or elections with no link in the article |

**Out of scope:** everything else, including articles about politics, the economy, foreign affairs, crime or culture **unless the article itself** connects them to the collapse or the movement. The connection must be in the text; do not infer it from what you know.

## Rules for hard cases

1. **The article decides, not the outlet's framing.** An article that calls participants "blokaderi" and one that calls them "studenti u blokadi" are judged by the same clauses.
2. **Opinion pieces and columns count** when they are about the story.
3. **Live blogs and round-ups** are in scope when at least one item concerns the story with a full paragraph.
4. **Foreign coverage republished** (agencies, foreign media quoted) is in scope when it is about the story.
5. **A protest by another group** (farmers, lawyers, teachers) is in scope only if the article ties it to the movement or the collapse; teachers' strikes over pay that the article links to the blockades are in (clause 2 or 3).
6. **Anniversaries and commemorations** of the collapse within the window are clause 1.
7. **Do not judge truth or intent.** Whether a claim in the article is true, or why someone acted, is irrelevant to scope.
8. **When unsure,** answer *in scope* only if you could point to the paragraph that makes it so.

## Output (classifier and coders alike)

```json
{"in_scope": true, "clauses": [2, 3], "evidence": "<the paragraph number, or 'headline'>", "confidence": "high | medium | low"}
```

- `clauses` is empty when `in_scope` is false.
- `evidence` points to where the decision comes from, so a disagreement can be checked.
- Classifier calls use the most deterministic setting the model accepts: temperature 0 where the model takes it, the model's default where it takes no sampling parameters. The exact model id, its thinking setting and this file's version are recorded in the run manifest; the prompt is this codebook plus the article (title, lead, numbered body paragraphs).

## Examples (constructed, not from the corpus)

| Article | Decision |
|---|---|
| "Students of the Faculty of Law voted at a plenum to continue the blockade." | in scope, clause 2 |
| "The minister said the blockades are financed from abroad." | in scope, clause 3 |
| "Fifteen minutes of silence held in Kragujevac at 11:52." | in scope, clauses 1 and 2 |
| "Prime minister resigns after the attack on students in Novi Sad." | in scope, clauses 3 and 4 |
| "Farmers block the highway near Šabac over milk prices." (no link to the movement) | out of scope |
| "Protests in Georgia continue for the tenth day." | out of scope |
| "New railway line to Subotica opens." (no link to the collapse) | out of scope |
| A weekly politics round-up with one sentence noting that protests continue | out of scope (no full paragraph) |
