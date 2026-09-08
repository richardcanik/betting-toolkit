# Data sources

## 1. Niké odds API (primary, machine-readable)

Niké's mobile site is a JavaScript application, but the data behind it comes from a
plain JSON gateway that needs **no authentication, no cookies and no browser**. This
is the project's source of truth for odds. `tools/nike_odds.py` is the only code that
is allowed to know these details; everything else goes through that tool.

Base URL: `https://m.nike.sk/api-gw/nikeone`

| Endpoint | Purpose |
|---|---|
| `GET /v1/init-data/mobile` | `bettingDays` — the days Niké currently has an offer for |
| `GET /v1/menu` | sport → tournament tree, each node carrying a `boxId` and a match count |
| `GET /v1/boxes/search/mobile` | events and their primary-market odds for one `boxId` |
| `GET /v1/boxes/extended/sport-event-id` | every market of a single match (handicaps, totals, sets, games) |
| `GET /v1/matches/special/superoffer` | Niké's boosted-odds ("superkurz") selection |

### Request conventions

Three details are not obvious and were established by reading the site's own bundle:

1. **Array parameters must be repeated flat keys.** `boxId=bi-7-18-157` works;
   `boxId[0]=bi-7-18-157` makes the gateway answer `400` with an empty body. The web
   client happens to send single values, which is why its own serializer never trips
   over this.
2. **`channel=Mobile` is required** on GET requests to this gateway. Without it the
   same request returns `400`.
3. **Only leaf boxes are queryable.** Menu nodes whose id ends in `-null`
   (`bi-7-18-null`, `bi-5-null-null`) are groupings for display; asking for their
   offer returns `400`.

4. **The menu tree must be walked to its leaves.** Depth is not uniform: under Tenis,
   `bi-7-18-157` (US Open - muži) is a direct child of the sport and is a real
   tournament, while `bi-7-1298-null` (Challenger) is a sibling that reports zero
   matches and carries fourteen tournaments one level below. Reading only the sport's
   direct children finds 4 tennis tournaments; walking to the leaves finds 61. Filter
   on a non-zero match count *after* reaching the leaves, never before.

The web client also appends a `ts` parameter whose value is a second-precision
timestamp in milliseconds where the last three digits sum to 14 — a lightweight bot
check. It is not currently enforced server-side, but `tools/nike_odds.py` sends a
valid one anyway so that the traffic matches what the site itself produces.

### Depth: the primary markets are not the offer

`/v1/boxes/search/mobile` returns only each match's **primary** markets. Reading just
those hides most of the offer, and in particular hides the one place Niké prices
generously:

- **Superšanca** — a boosted market that appears alongside the standard one on a
  handful of matches, at roughly 2 % margin instead of the standard 4 %, and which is
  better than the standard price **on both sides**. On the 2026-09-09 US Open
  quarterfinals it paid 7.34 instead of 7.20, 1.29 instead of 1.27, 3.47 instead of
  3.40. Never quote a Niké price without checking whether a Superšanca exists for that
  match; the standard market is simply the worse version of the same bet.
- **Derivative markets** — set and game handicaps, totals, exact score. These carry
  around 8 % margin against the headline market's 4 %, so they are usually the wrong
  place to look, but they cannot be ruled out without being read.

`tools/nike_odds.py offer` therefore fetches every event in full by default, at roughly
50 markets per match. `--depth primary` is the opt-out, and a `--max-events` guard
refuses an accidental full sweep of a sport like football (about 700 events).

`/v1/matches/special/superoffer` sounds like the boosted offer and is not: it returns
**featured** matches at standard prices. It is not a source of value.

### Response shape

`/v1/boxes/search/mobile` returns four parallel lists that must be joined by id:

- `sportEvents` — the match: `sportEventId`, `participants`, `expiration` (start
  time), `tournamentName`, `statisticsId`.
- `bets` — one entry per market offered on a match, joined via `sportEventId`. The
  prices live in `selectionGrid`, a grid of cells each carrying `odds`, `name`, `tip`,
  and the `enabled`/`locked` flags that say whether the price is actually takeable.

  **One bet can hold more than one market.** The grid's rows are independent: a
  basketball `Zápas` bet carries 1X2 on row 0 and the double chance on row 1. Anything
  computed across a whole bet rather than per row — a margin, a de-vigged probability —
  is meaningless. Group by grid row.
- `markets` — market metadata, joined via `marketId`. Market `367` is
  "Víťaz zápasu" (match winner).
- `boxes` — the tournament container itself.

Sport ids seen so far: tennis `7`, basketball `5`, football `1`, hockey `3`.

### Stability

This is an internal API with no compatibility promise. When a command in
`tools/nike_odds.py` starts failing, assume the contract moved: re-read the site
bundle, then update **this document and the tool together**. Never work around a
change by patching only the code.

### Etiquette

`robots.txt` on `m.nike.sk` disallows `/app/*`, `/ulozeny/*`, `/p/*`, `/dr/*` and the
ticket paths; `/tipovanie/*` and the API gateway are not disallowed. Requests are made
at human rates — a handful per analysis, never a continuous poll. There is no scraping
of account, ticket or any other authenticated surface.

### Niké's margin ladder

Margin is not uniform across the offer, and it maps to how exposed Niké feels rather
than to how big the event is. Measured on the match-winner market, 2026-09-08:

| Tier | Median margin |
|---|---|
| Grand Slam (US Open) | ~4.1 % |
| Boosted "Superšanca" | ~2.2 % |
| WTA 125 and Challenger | ~8.0 % |
| ITF | ~10.0 % |

This inverts the usual intuition that small tournaments are where a soft book is
beatable. Niké protects itself with margin precisely where it is least confident, so
on an ITF match the price must be more than five percentage points wrong on a two-way
market before the bet is even break-even — and that is exactly where the least
information is available to establish that it is wrong. Obscurity raises the cost of
being right at the same time as it raises the chance the line is stale.

The practical consequence is to look for value where margin is low and a comparison
price exists, and to treat the deep lower tiers as a place that needs a much larger
demonstrated edge, not a smaller one.

## 2. Smarkets exchange (fair probability)

`https://api.smarkets.com/v3` — public, no API key, no account.

An exchange is people betting against each other rather than against a book. It takes
commission from winnings instead of building a margin into the price, so its prices
already sum to 1 and need no de-vigging: **the mid of the best bid and the best offer
is the fair probability**, which is exactly the anchor `specs/market-model.md` asks
for. `tools/consensus.py` reads it.

| Endpoint | Purpose |
|---|---|
| `GET /events/?type=tennis_match&state=upcoming` | upcoming events of one sport |
| `GET /events/{ids}/markets/` | markets; `WINNER_2_WAY` is the match winner |
| `GET /markets/{ids}/contracts/` | the named outcomes |
| `GET /markets/{ids}/quotes/` | the order book, as bids and offers |

Ids may be comma-separated, about twenty at a time, which turns hundreds of requests
into a handful. Quote prices are hundredths of a percent: `4167` means 41.67 %.

**Pagination never terminates on its own.** `next_page` keeps being returned after the
last page and the same events repeat, so following the cursor until it disappears is an
infinite loop. Stop when a page contributes no event id that has not been seen.

### The binding constraint is liquidity, not coverage

Smarkets lists plenty of events but prices few of them tightly. Measured 2026-09-08:

| Sport | Markets | Median bid/offer spread | Within 4 points |
|---|---|---|---|
| Tennis | 95 | 12.3 % | 15 |
| Darts | 15 | 15.3 % | 0 |

A market quoted 16 % bid against 31 % offer has no usable midpoint — the gap is five
times the edge being hunted, so any "edge" measured against it is smaller than the
uncertainty in it. An early run produced exactly this false positive: a doubles match
appearing to offer +3.10 % edge, on a book with a 14.6-point spread. `consensus.py`
therefore drops any market wider than `--max-spread` (default 4 points).

The consequence is uncomfortable and worth stating plainly: **Smarkets is liquid
precisely where Niké is already efficient** — the marquee matches — and illiquid across
the lower tiers where a stale line is plausible. It verifies the matches that need no
verifying. Reaching the rest needs a deeper source: Betfair, which is far larger but
requires an account and an application key, or The Odds API, which aggregates
bookmakers including Pinnacle and requires a free key.

## 3. Comparison books (line shopping and consensus)

Tipos and Fortuna are used for two distinct purposes that must not be confused:

- **Line shopping** — checking whether the same selection is priced better elsewhere.
- **Consensus fair probability** — a de-vigged average across books as one input to
  the fair-probability estimate (see `specs/market-model.md`).

These are not yet automated. Until they are, their odds are read manually and recorded
with the time they were observed, because an odds quote without a timestamp is not
evidence of anything.

## 4. Context and statistics

Flashscore and Sofascore for form, head-to-head, schedule and injury news;
Tennis Abstract for surface-split tennis data; Basketball-Reference for NBA;
Action Network for market-movement signal. These inform the adjustments in
`specs/market-model.md` but are never a substitute for the price itself.
