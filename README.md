# betting-toolkit

Finding value bets — selections where Niké's price is higher than the true probability
justifies — in tennis and basketball. The subject is the price, not the winner.

This repository is **spec-driven**. The specifications in `specs/` are the substance;
the two programs in `tools/` exist only to do the parts a conversation cannot do
reliably — fetching live odds, and remembering every selection.

## Layout

| Path | Contents |
|---|---|
| `specs/data-sources.md` | the Niké JSON API contract, and what the comparison books are for |
| `specs/market-model.md` | implied probability, de-vigging, fair-probability estimation, EV, Kelly, CLV |
| `specs/selection-criteria.md` | thresholds, red flags, output format, confidence bands |
| `specs/tracking.md` | the history database schema, workflow and evaluation metrics |
| `tools/nike_odds.py` | reads the live Niké offer |
| `tools/history.py` | records selections and reports calibration |
| `data/bets.csv` | the committed bet history; `data/bets.db` is a local artifact rebuilt from it |

Python 3 standard library only — no dependencies, no build step.

## Reading the offer

```
tools/nike_odds.py days                                 # days with an offer
tools/nike_odds.py tournaments --sport tennis           # tournaments and their box ids
tools/nike_odds.py offer --sport tennis --market "Víťaz zápasu"
tools/nike_odds.py event 1017349044                     # every market for one match
```

Add `-f csv` or `-f json` for machine-readable output.

## Recording a selection

```
tools/history.py add --sport tennis --event "A vs B" --market "Víťaz zápasu" \
    --selection "B" --odds 2.60 --p-low 0.42 --p-high 0.47 \
    --confidence medium --factors "surface-form,fatigue"

tools/history.py close 1 win --odds-close 2.35
tools/history.py stats
tools/history.py export     # refresh data/*.csv, then commit those
```

The SQLite database is local and gitignored — git cannot diff or merge a binary blob.
The committed record is the CSV export, and `tools/history.py import` rebuilds the
database from it on a new machine. `BETTING_DB` overrides the database path, which is
useful for experiments that should not touch the real record.

## How a day's analysis runs

The judgement stays in conversation. `tools/nike_odds.py` supplies the prices, the
specs supply the method, the analysis produces a ranked list of selections that clear
the thresholds — often a short list, sometimes an empty one — and each one that is
actually taken is written to the database before the event starts.
