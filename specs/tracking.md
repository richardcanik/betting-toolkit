# Tracking and evaluation

Every selection is recorded at the moment it is made, in `data/bets.db`, through
`tools/history.py`. Recording after the fact does not work: the point of the database
is to capture what was believed *before* the result was known.

## 1. Schema

`bets` — one row per selection.

| Column | Meaning |
|---|---|
| `placed_at`, `starts_at`, `settled_at` | ISO 8601 with offset |
| `sport`, `event`, `market`, `selection` | human-readable identity of the bet |
| `event_id`, `bet_id` | **Niké's** `sportEventId` and `betId`, so the row can be traced back to the offer |
| `odds_nike` | the price actually taken |
| `odds_close` | the closing price, filled in at settlement, for CLV |
| `p_est_low`, `p_est_high` | the fair-probability range that justified the bet |
| `edge`, `ev` | derived from `p_est_low` and `odds_nike`; never entered by hand |
| `stake` | units; default 1 (flat) |
| `confidence` | `low` / `medium` / `high`, as defined in `specs/selection-criteria.md` |
| `factors` | comma-separated drivers, e.g. `fatigue,surface-form` |
| `result`, `pnl` | `win` / `loss` / `void`, and the resulting profit in units |

`odds_snapshots` — repeated observations of a bet's price over time. `bet_ref` is this
database's own `bets.id`, not Niké's `betId`; the two are deliberately named
differently to keep them apart.

### What is version controlled

The `.db` file is a **local working artifact and is not committed**. A SQLite file is
an opaque binary blob: git cannot diff it, so the history of the record would be
unreviewable, and it cannot merge it, so any divergence between two machines would be
a conflict with no resolution. It is also a personal gambling record, which is a
further reason not to push it to a hosted remote by reflex.

The durable record is instead a plain-text export — `data/bets.csv` and
`data/odds_snapshots.csv` — which git handles properly: every appended bet shows up as
readable added lines, and every later correction is attributable.

```
tools/history.py export      # refresh the CSVs; commit these
tools/history.py import      # rebuild the database from them (--force to replace)
```

Run `export` and commit its output whenever bets are added or settled. Anything not
exported exists only on one machine and is one disk failure from gone.

## 2. Workflow

```
tools/history.py add --sport tennis --event "A vs B" --market "Víťaz zápasu" \
    --selection "B" --odds 2.60 --p-low 0.42 --p-high 0.47 \
    --confidence medium --factors "surface-form,fatigue" \
    --event-id 1017349044 --bet-id 926619271

tools/history.py snapshot 1 --odds 2.45          # optional, as the line moves
tools/history.py close 1 win --odds-close 2.35   # at settlement, with the close
tools/history.py stats                           # calibration to date
tools/history.py export                          # refresh the committed CSVs
```

Recording `--odds-close` is not optional in practice. Without it the database can only
report whether bets won, which takes hundreds of results to become meaningful. With
it, the far more informative CLV question is answerable after a few dozen.

## 3. Metrics

- **Hit rate against expectation.** Do selections estimated at 60 % win about 60 % of
  the time? Systematic optimism is the failure mode to watch for.
- **ROI at flat stakes**, in units, against total staked.
- **Calibration by confidence band.** High-confidence selections should outperform
  low-confidence ones. If they do not, the labels are decorative and the estimation
  process, not the weights, is what needs fixing.
- **CLV** — average `odds_taken / odds_close - 1`, and how often the close was beaten.
- **Factor breakdown** — hit rate of selections carrying each recorded factor.

`tools/history.py stats` reports all of these.

## 4. Revising the method

Sample sizes here are smaller than intuition suggests. At around 2.00 odds, ROI needs
several hundred settled bets before a genuine edge is distinguishable from variance;
probability calibration needs a comparable number per confidence band. Twenty or
thirty results say essentially nothing about ROI, and any change made on that basis is
fitting noise.

Therefore:

- **CLV is the early signal.** It converges much faster than results, and it is what
  should be watched over the first few dozen bets.
- **Results-based revision waits for a real sample** — of the order of 200 settled
  bets in a sport, not 20.
- **Every change is written down** in the log below, with the sample it rested on, so
  a later reader can tell a considered adjustment from a reaction to a bad week.

### Change log

| Date | Sport | n | Hit rate | ROI | CLV | Change | Reason |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
