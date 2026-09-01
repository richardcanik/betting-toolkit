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
   offer returns `400`. Filter to nodes with a non-zero match count.

The web client also appends a `ts` parameter whose value is a second-precision
timestamp in milliseconds where the last three digits sum to 14 — a lightweight bot
check. It is not currently enforced server-side, but `tools/nike_odds.py` sends a
valid one anyway so that the traffic matches what the site itself produces.

### Response shape

`/v1/boxes/search/mobile` returns four parallel lists that must be joined by id:

- `sportEvents` — the match: `sportEventId`, `participants`, `expiration` (start
  time), `tournamentName`, `statisticsId`.
- `bets` — one entry per market offered on a match, joined via `sportEventId`. The
  prices live in `selectionGrid`, a grid of cells each carrying `odds`, `name`, `tip`,
  and the `enabled`/`locked` flags that say whether the price is actually takeable.
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

## 2. Comparison books (line shopping and consensus)

Tipos and Fortuna are used for two distinct purposes that must not be confused:

- **Line shopping** — checking whether the same selection is priced better elsewhere.
- **Consensus fair probability** — a de-vigged average across books as one input to
  the fair-probability estimate (see `specs/market-model.md`).

These are not yet automated. Until they are, their odds are read manually and recorded
with the time they were observed, because an odds quote without a timestamp is not
evidence of anything.

## 3. Context and statistics

Flashscore and Sofascore for form, head-to-head, schedule and injury news;
Tennis Abstract for surface-split tennis data; Basketball-Reference for NBA;
Action Network for market-movement signal. These inform the adjustments in
`specs/market-model.md` but are never a substitute for the price itself.
