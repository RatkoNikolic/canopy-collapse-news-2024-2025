# Labelling guide: what this dataset is and where your labels fit

Thank you for helping. This page explains, without jargon, what the dataset is, how the
articles were collected, what you will be asked to do, and what your work makes possible.
Reading it takes about 10 minutes. The rules you label by are in the **codebook**, which the
labelling page shows next to every article; this guide explains the context around it.

---

## 1. The dataset in one paragraph

The dataset follows one big Serbian news story through online news: **the protest movement
that began with the collapse of the canopy at the Novi Sad railway station on 1 November
2024**, from 1 November 2024 to 30 April 2025. It lists every news article nine major outlets
published in those six months, and marks which of them are about the story. It is open: anyone
can check how it was built and use it for their own research. The articles' text is not
published, only their web addresses, dates and fingerprints, so anyone can check them against
the outlets' sites.

---

## 2. How the articles were collected

```
 1. Find the articles     2. Download them       3. Clean the text       4. Find the story
 ──────────────────     ──────────────────     ──────────────────     ──────────────────
 lists of article  ──▶  each page, politely ──▶  title, lead, body  ──▶  which articles are
 links per outlet       (one page every          in Latin script         about the protest
                        2+ seconds per site)                             story?  ◀── YOU
```

1. **Which outlets.** Nine Serbian news websites: the three most-used of each kind, by the
   Reuters Institute's *Digital News Report*. That is three newspapers (Blic, Danas,
   Informer), three TV broadcasters (RTS, B92, Pink) and three online-first brands (N1,
   Telegraf, Nova). The rule was written down before any article was collected, and
   **political leaning played no part in the choice**.
2. **Finding the links.** We built lists of every article each outlet published in the
   six months, from public archives (Media Cloud, the outlets' own sitemaps, the naslovi.net
   aggregator). Sections that are clearly not news (sport, celebrity, lifestyle, horoscopes,
   recipes and similar) were left out by their web address before anything was downloaded.
3. **Downloading.** Each page was downloaded once, slowly and politely: no logins, no
   paywalls, no reader comments. That gave **≈ 216,000 news articles**.
4. **Cleaning.** For each article we kept the title, the lead (the short summary under the
   title), the body split into paragraphs, and the publication date. Articles written in
   Cyrillic were converted to Latin script letter by letter, so every article reads the same
   way.

Only a small share of these 216,000 articles is about our story. Most are about other news:
crime, the economy, foreign affairs, local events. The next step is to find the ones that
are about the story, and that is where your labels come in.

---

## 3. Finding the story's articles, and where you fit in

Reading 216,000 articles by hand is impossible, so the computer does it in three stages.
Each stage narrows the set.

| Stage | What it does | Strength | Weakness |
|---|---|---|---|
| **1. Word list** | flags any article that uses words tied to the story (canopy, blockade, plenum, students, protest, and so on), counting the words used by every side of the debate | fast, transparent | misses articles that use none of the words; flags some that only mention them in passing |
| **2. Similarity** | gives every article a score for how similar its meaning is to the flagged articles, to catch what the word list missed | finds articles without the key words | only a ranking, not a decision |
| **3. Classifier** | an AI model reads each likely article with the codebook and decides: *in scope* (and which clauses) or *out* | reads like a person | can make mistakes, and we have to know how many |

**Your labels are the yardstick for all three stages.** Together, the three of us read
**300 articles** picked at random from the whole collection: some the stages above think
are likely about the story, some they think are unlikely, from every outlet. Each of us
decides by the same codebook the AI model uses. Then we compare:

- **How good is the AI model?** Where you and the model disagree, the model is wrong (or the
  case is genuinely hard). This tells us its error rate, including whether it makes more
  mistakes on some outlets than others, which matters for fairness.
- **How much do the word list and the similarity score miss?** Some of the 300 articles come
  from the "unlikely" piles on purpose. If you find story articles there, we know roughly
  how many the computer would have missed across all 216,000.
- **How clear is the codebook?** 50 of the articles are labelled by all three of us,
  independently. Where we agree, the rules are clear; where we disagree, the rule needs a
  closer look. This agreement is reported in the results, whatever it turns out to be.

Your labels are kept with the project (as decisions only: article ID, in/out, clauses,
paragraph, confidence) and become part of the published **gold standard**: the reference
answers that anyone can use to check the method.

---

## 4. Your task

### What you decide for each article

1. **In scope or out?** In scope if the **headline, or at least one full paragraph**, is about
   the story. A passing mention does not count.
2. **Which clauses apply** (one or more), if in scope:
   - **1 Collapse:** the canopy collapse and its direct consequences (victims, commemorations,
     the investigation, the station's reconstruction);
   - **2 Movement:** what the movement does (protests, blockades, plenums, marches, demands);
   - **3 Responses:** how others respond to the movement (government, president, parties,
     police, courts, universities; incidents at protests; arrests; counter-gatherings);
   - **4 Political consequences:** resignations, the fall and formation of the government,
     talk of elections, when the article itself links them to the story.
3. **Evidence:** click the headline or the paragraph(s) that made you decide.
4. **Confidence:** high, medium or low.

The codebook on the page has the full definitions, eight rules for hard cases and examples.
**When this guide and the codebook seem to differ, the codebook wins.**

### Who labels what

Each reviewer has a number and a page of their own:

| Reviewer | Your file | Articles |
|---|---|---|
| R1 | `gold-v1-R1.html` | 134 |
| R2 | `gold-v1-R2.html` | 133 |
| R3 | `gold-v1-R3.html` | 133 |

Your page contains **only your articles**, and your reviewer number is already filled in,
so there is nothing to coordinate: label everything on your page. 50 of your articles are
also on the other two pages and 83–84 are yours alone. You are not told which are which, on
purpose: label every article the same way. Each page has the same mix of likely and unlikely
articles and of outlets.

### How to do it

1. Open **your** file (see the table) in **Chrome or Edge** (it works offline). The top of the
   page shows *reviewer R1*, *R2* or *R3*: check it is yours.
2. Click **Save to file…** and choose where to save. From then on every label is written to
   that file as you go. Do this **at the start of every sitting** (choosing the same file
   again is fine: it always holds all your labels so far). Your labels are also kept in the
   browser between sittings, as long as you use the same browser on the same computer and do
   not clear its data. If in doubt, use **Export** at the end of a sitting.
3. Label with the mouse or the keyboard: <kbd>y</kbd>/<kbd>n</kbd> in or out,
   <kbd>1</kbd>–<kbd>4</kbd> clauses, click a paragraph for evidence,
   <kbd>h</kbd>/<kbd>m</kbd>/<kbd>l</kbd> confidence, <kbd>Enter</kbd> save and go to the next
   one. *Next open* jumps to the first article you have not labelled yet.
4. When you are done, or at the end of each sitting, send the saved file (or the export) to
   the coordinator. Its name includes your reviewer number.

It takes about **one minute per article**, so roughly **2–2.5 hours for your 133–134**.
Spread it over several sittings: labels are kept between sittings, and you can go back and change a
label at any time.

### Ground rules

- **Work on your own.** Do not discuss articles with the other labellers until everyone has
  finished. The comparison between the three of you only works if the labels are independent.
- **Judge the text, not the source.** The page deliberately hides which outlet published the
  article. Please do not search for the article online to find out. The same rules apply
  whichever side an article is written from: an article that calls participants
  "blokaderi" and one that calls them "studenti u blokadi" are judged the same way.
- **Do not judge truth or intent.** Whether a claim is true, or why someone did something,
  is irrelevant. The only question is whether the article is about the story.
- **Use your own judgement.** Please do not use AI tools to help decide; the point is to
  have a human answer to compare the AI against.
- **Unsure? Say so.** Pick the best answer and mark confidence *low*, and write a short note
  if something is unclear. Low-confidence labels are useful information, not a failure.
- **Keep the file private.** The page contains the full text of the articles, which belongs
  to the outlets. Do not forward or publish it, and delete it when the labelling is done.
  Only your decisions are kept, never the text.

---

## 5. What the dataset is for

Once the labels are in, they measure how well the computer found the story's articles, and
those figures are published with the dataset. The dataset is then used by research on how the
story was covered and how it developed, starting with a companion project that follows how a
running summary of the story goes out of date as new facts arrive. Because the way it was
built is written down step by step ([`PROTOCOL.md`](./PROTOCOL.md)), other researchers can use
it, check it and build on it.

### What will be published

- the code, open source;
- the list of article web addresses with fingerprints (hashes), so anyone can check them,
  but **no article text**;
- for each article, whether it is about the story;
- your scope labels (decisions only) and the agreement between the three of us;
- how accurate the computer's selection is, overall and per outlet.

---

## Glossary

| Term | Meaning |
|---|---|
| **In scope** | The article is about the story, by the codebook's rules. |
| **Codebook** | The written rules for deciding in or out; the same text for people and for the AI model. |
| **Gold standard** | Reference answers made by people, used to check the computer's work. |
| **Classifier** | The AI model that decides in or out for the rest of the articles. |
