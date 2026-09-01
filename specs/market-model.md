# Market model: from odds to a fair probability

The goal of this project is not to predict winners. It is to find selections where
Niké's price is higher than the true probability justifies. Everything below exists to
make that comparison honest.

## 1. Implied probability and the margin

The raw implied probability of a decimal price is `p_implied = 1 / odds`. These do not
sum to 1 across the outcomes of a market; they sum to more, and the excess is the
bookmaker's margin (the vig). For a two-way tennis market at 1.30 / 3.60 the raw
implied probabilities are 0.769 and 0.278, summing to 1.047 — a 4.7 % margin.

Two consequences follow, and getting them the wrong way round is the most common
mistake in this kind of analysis:

- **Comparing your own estimate against the raw `1 / odds` is correct and
  conservative.** That is the price you actually have to beat, margin included.
- **Using another book's raw `1 / odds` as evidence of the true probability is
  wrong.** It is inflated by that book's margin. Before a competitor's price can serve
  as a reference point it must be de-vigged.

## 2. De-vigging

Given the raw implied probabilities `q_i` of a market, remove the margin before
treating them as a probability estimate.

- **Proportional (multiplicative):** `p_i = q_i / Σq`. Simple, and the default. Its
  known flaw is that it under-corrects the favourite and over-corrects the longshot,
  because real bookmaker margin is not spread evenly across outcomes.
- **Power method:** find `k` such that `Σ q_i^k = 1`, then `p_i = q_i^k`. Better
  behaved on lopsided markets — which is most of tennis, where 1.05 / 10.00 prices are
  routine.

Use proportional for roughly balanced markets and power when the favourite is shorter
than about 1.40. State which one was used whenever a consensus number is quoted.

## 3. Estimating the fair probability

The estimate is built in this order, and the order matters:

1. **Anchor on the de-vigged market.** Take the de-vigged consensus of the available
   books (Niké, Tipos, Fortuna). Where several books agree and one is out of line,
   the agreeing majority is the better estimate of the truth.
2. **Adjust for what the price does not yet contain.** A market anchor is only stale
   in respect of information that has not reached it: a late injury or withdrawal, a
   line-up change, a fatigue situation the price has not absorbed, a scheduling
   quirk. Adjustments are small — single-digit percentage points — unless there is
   concrete news.
3. **Express the result as a range, not a point.** For example 42–47 %. The width of
   the range is the honest statement of how much is actually known.
4. **Compute the edge from the bottom of the range.** If the bet only clears the
   threshold at the optimistic end, it does not clear it.

### Why the factor weightings are advisory

Form, absences, rest, venue, head-to-head, motivation (basketball) and surface form,
rating gap, head-to-head, fatigue, tournament context (tennis) are the factors worth
examining, roughly in that order of importance. They are a **checklist for step 2**,
not a formula: there is no defensible arithmetic that turns "30 % weight on form" into
a probability, and pretending otherwise dresses a guess up as a model. Record which
factors drove each selection (`--factors` in `tools/history.py`) so that the tracking
data can eventually say which ones are worth anything. Until that evidence exists,
they are ordered by judgement and honestly labelled as such.

## 4. Edge, EV and stake

```
edge = p_est_low - 1 / odds
EV   = odds * p_est_low - 1            (per unit staked)
```

`tools/history.py add` computes both from `--p-low` and `--odds`, so the arithmetic is
never done by hand.

For staking, the Kelly fraction is `edge / (odds - 1)`. Treat it strictly as a ceiling
and bet a fraction of it — a quarter Kelly is a reasonable default — because full
Kelly is only correct when the probability estimate is exact, and it never is. Flat
stakes are the simpler alternative and cost surprisingly little; the default stake in
the history tool is 1 unit for that reason.

## 5. Closing line value

After a match starts, the price it closed at is the best available estimate of its
true probability, because it embodies all the money and information that arrived
before the off. Recording the closing odds therefore answers a question that win/loss
records cannot answer for months: **did the selection beat the price?**

```
CLV = odds_taken / odds_close - 1
```

Consistently positive CLV means the selection process is finding real mispricings,
even during a losing run. Consistently negative CLV means it is not, even during a
winning one. Record `--odds-close` on every settlement.
