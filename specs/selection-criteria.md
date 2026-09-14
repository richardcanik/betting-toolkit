# Selection criteria

## 1. Thresholds

A selection is a candidate only if all of the following hold:

- `EV > 0` computed from the **lower** bound of the fair-probability range.
- `edge >= 3 %`. Below that the estimate's own uncertainty exceeds the supposed
  advantage, and the bet is noise.
- The price is actually takeable — the selection's cell is `enabled` and not `locked`
  in the Niké offer.
- The price is the **best** one Niké offers for that selection. Where a Superšanca
  exists it beats the standard market on both sides, and quoting the standard price
  understates the edge by a percentage point or more (see `specs/data-sources.md`).

Where two candidates have similar edge, the one with the narrower probability range
(higher confidence) ranks first. A large edge derived from a wide range ranks below a
modest edge derived from a narrow one, and a large edge that exists only because
information is missing is not a candidate at all.

## 2. There is no fixed number of selections

The output is every candidate that clears the thresholds. On a strong day that may be
five; on most days it is one or two; on many days it is none.

This is a deliberate departure from the original "top 20 matches of the day" framing.
A day's offer in two sports does not contain twenty genuine 3 %-edge mispricings. A
process required to produce twenty will pad the list with negative-EV filler, and
because the filler outnumbers the real selections it will dominate the results and
make the whole record uninterpretable. Ranking is the useful part; the count is not.

## 2.1 Doubles are excluded

Only matches between single competitors are collected. The reason is not that pairs
play differently but that their **names cannot be matched reliably**. Participants are
joined across sources by shared name tokens, which is safe for one person and not for
a pair: a pair carries two surnames, so it attaches to the wrong exchange event
whenever one of its players is also entered in the singles draw that day — routine at
any tournament.

That is not theoretical. A doubles selection was recorded apparently offering **+12.8 %
edge**, by far the largest ever seen, and it was a mismatched event rather than a
price. One of the pair was playing singles the same afternoon.

Pairs also fit the sport criteria less cleanly than singles: a partner's form is a
second source of variance that the market prices better than any outside estimate can.

`consensus.py --doubles` re-enables them, for when name matching demands both members
of a pair to agree separately rather than either one.

## 3. Red flags

Discard a candidate when:

- **Team news is unconfirmed** close to the start — an unreported absence swamps any
  edge, and this is the single most common way a good-looking number is wrong.
- **The market is illiquid** — a marginal tournament, a low-level ITF or Challenger
  event, or any match where there is no second book to compare against. Without a
  comparison price there is no evidence the line is stale rather than sharp.
- **The outcome is dominated by randomness** — exhibitions, B-teams, dead rubbers,
  matches where one side is visibly unmotivated.
- **The estimate rests on a single source** that cannot be corroborated.

### The one that is not a red flag

A price that is far better at Niké than at every other book is **not** automatically a
discard. That is the definition of the thing being looked for. What matters is *why*
it is out of line:

- **Stale line** — Niké has not yet reacted to news the other books have priced in.
  This is a genuine opportunity and should be taken promptly, since it will not last.
- **Palpable error** — a typo or a mis-set line, of the 1.50-instead-of-15.0 kind.
  Bookmakers void these under their terms, so the bet has no value even when it wins.

Distinguish them by size and shape. A price 10–20 % out of line with a plausible
story behind it is a stale line. A price several times out of line, or one where no
account of the world makes it sensible, is an error. Record which judgement was made.

## 4. Output format per selection

```
[Sport] A vs B — date, time
Market:     match winner / handicap / total / …
Odds:       Niké X.XX | Tipos X.XX | Fortuna X.XX   (observed at HH:MM)
Fair:       XX–XX %   (de-vigged consensus + adjustments)
Edge:       X.X %   EV: +X.X %
Reasoning:  two to four sentences — what the market has not priced, and why
Confidence: low / medium / high
Factors:    the drivers, as recorded in the history database
```

Every quoted price carries the time it was observed. An odds figure without a
timestamp cannot be checked afterwards and is not evidence.

## 5. Confidence bands

- **High** — probability range 5 points wide or less; corroborated by more than one
  source; team news confirmed; a clear account of why the price is wrong.
- **Medium** — range up to 10 points; the story is plausible but partly inferred.
- **Low** — anything wider, or resting on a single source. Low-confidence selections
  are recorded and staked small, because their main purpose is to test whether the
  confidence labels mean anything (see `specs/tracking.md`).
