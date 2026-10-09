# Error analysis of the scope layer (gold-v1)

Where the pipeline and the gold labels disagree, and why. Written after the validation figures
(`PROTOCOL.md` §6.5) and changing nothing: the classifier is fixed and the gold labels stand.
Categories and counts only; no article text is quoted.

## Disagreements

Of the 300 gold articles, **29** disagree with the pipeline:

| | Count | Meaning |
|---|---|---|
| False positives | 25 | the pipeline puts the article in scope, the gold label out |
| False negatives | 4 | the gold label puts it in scope, the pipeline out |

## False positives, by kind

| Kind | Count | What happens |
|---|---|---|
| **Protest or "opposition" activity without a stated link** | 9 | The article reports a protest, a gathering or the opposition's actions, or responds to them, but does not say in the text that they are the student movement or tied to the collapse. The codebook requires the connection to be in the text; the coders applied that strictly, the classifier drew the connection from context. |
| **Opinion pieces with one relevant passage** | 5 | Commentary on wider politics with a paragraph touching the protests; the coders judged that the piece is not about the story. |
| **Other topics with a passing reference** | 11 | Statements and reports on other subjects (ministries, infrastructure, foreign politics, city government) that mention the protests, the resignation or the case in passing; one concerns a student blockade abroad, which the codebook names as out of scope. |

By outlet: Informer 9, Danas 6, N1 3, Blic 2, Nova 2, B92 1, Pink 1, Telegraf 1, RTS 0.

**Informer's precision** (0.60, against 0.79–1.00 for the other outlets) comes mostly from the
first kind: 6 of its 9 false positives report protests as actions of the opposition without
naming the students or the collapse, which the coders, following the codebook, marked out.
Three of its 9 lie in band-top10, where each gold article stands for ≈ 590 corpus articles, so
they weigh heavily in the estimate. With 34 gold articles from Informer, the figure is a clear
signal, not a precise one.

A few gold labels in the false positives are arguable the other way (low coder confidence, or
a case close to a clause such as counter-mobilisation or the prosecution over the collapse).
The protocol does not adjudicate labels after the fact; they stand as coded.

## False negatives

- 1 in **band-next20**, which the classifier does not read (§5.4): the cost of the extension
  rule, already counted in the recall.
- 2 **shared articles** on which the coders split two to one.
- 1 article whose link to the movement the classifier judged too weak (low confidence).

## What it means for users

- The in-scope set leans inclusive: about one article in seven that it marks in scope, a
  coder would mark out, most often because the article's link to the movement is implicit.
  Users who need only explicit coverage of the movement can filter on clauses and the
  classifier's confidence, or re-code a sample.
- The inclusion is not even across outlets; per-outlet comparisons of in-scope counts should
  use the per-outlet precision in `validation.json`.
- Coders agree well on in or out (α 0.887) but less on clause 2, the movement's own actions
  (α 0.533): the line between the movement acting (clause 2) and others responding to it
  (clause 3) is the least clear part of the codebook.
