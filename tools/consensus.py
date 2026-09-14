#!/usr/bin/env python3
"""Compare Nike's prices against fair probabilities from the Smarkets exchange.

An exchange is people betting against each other rather than against a book, so
its prices carry no margin and need no de-vigging: the mid of the best bid and
the best offer is already the fair probability. That makes it the right anchor
for the market model in specs/market-model.md.

Stdlib only. See --help for the subcommands.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import nike_odds  # noqa: E402
from names import same_person, tokens  # noqa: E402,F401

SMARKETS = "https://api.smarkets.com/v3"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

# Nike sport name -> (nike sport id, smarkets event type)
SPORTS = {
    "tennis": (7, "tennis_match"),
    "darts": (88, "darts_match"),
    "basketball": (5, "basketball_match"),
    "table-tennis": (61, "table_tennis_match"),
    "snooker": (85, "snooker_match"),
}
BATCH = 20  # ids per request; the API accepts comma-separated lists


class ExchangeError(RuntimeError):
    """Smarkets rejected a request."""


def sm_get(path: str, **params) -> dict:
    url = f"{SMARKETS}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:      # rate limited: back off
                time.sleep(2 * (attempt + 1))
                continue
            raise ExchangeError(f"smarkets {exc.code} for {path}") from exc
        except urllib.error.URLError as exc:
            raise ExchangeError(f"smarkets unreachable: {exc.reason}") from exc
    raise ExchangeError(f"smarkets kept rate limiting {path}")


# --- name matching ---------------------------------------------------------


def same_match(nike_sides: list[str], sm_name: str) -> bool:
    """True when both participants line up, in either order."""
    if " vs " not in sm_name:
        return False
    left, right = sm_name.split(" vs ", 1)
    if len(nike_sides) != 2:
        return False
    first, second = nike_sides
    return (same_person(first, left) and same_person(second, right)) or (
        same_person(first, right) and same_person(second, left)
    )


# --- exchange side ---------------------------------------------------------


def exchange_events(event_type: str, days: int, max_pages: int = 40) -> list[dict]:
    """Upcoming exchange events of one type, starting within `days`.

    Smarkets keeps handing back a `next_page` cursor after the last page and
    simply repeats itself, so following the cursor until it disappears never
    terminates. Pagination stops when a page contributes no event that has not
    already been seen.
    """
    horizon = datetime.now(timezone.utc) + timedelta(days=days)
    seen: dict[str, dict] = {}
    cursor = None
    for _ in range(max_pages):
        params = {"type": event_type, "state": "upcoming", "limit": 100}
        if cursor:
            params["cursor"] = cursor
        data = sm_get("/events/", **params)
        page = data.get("events", [])
        fresh = [e for e in page if e["id"] not in seen]
        if not fresh:
            break
        seen.update({e["id"]: e for e in fresh})
        cursor = (data.get("pagination") or {}).get("next_page")
        if not cursor or len(page) < 100:
            break

    kept = []
    for event in seen.values():
        start = parse_start(event.get("start_date"))
        if start and start > horizon:
            continue
        kept.append(event)
    return kept


def parse_start(value: str | None) -> datetime | None:
    """Exchange timestamps come without an offset; they are UTC."""
    if not value:
        return None
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def batched(items: list, size: int = BATCH):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fair_probabilities(
    events: list[dict], max_spread: float = 0.04
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Fair probability per participant, keyed by exchange event id.

    Quote prices are hundredths of a percent, so 4167 means 41.67 %. The mid of
    the best bid and the best offer is taken, then the outcomes are normalised so
    they sum to 1 -- the small residue is the bid/offer spread, not a margin.

    A market is only usable when that spread is narrow. On an illiquid market the
    book can read 16 % bid against 31 % offer, and the midpoint of a fifteen-point
    gap is not a probability, it is the middle of nothing: any "edge" measured
    against it is smaller than the uncertainty in it. Markets wider than
    `max_spread` on any outcome are therefore dropped rather than trusted, and the
    spread of those kept is returned so it stays visible.
    """
    ids = [e["id"] for e in events]
    markets: dict[str, dict] = {}
    for chunk in batched(ids):
        data = sm_get(f"/events/{','.join(chunk)}/markets/")
        for market in data.get("markets", []):
            if (market.get("market_type") or {}).get("name") == "WINNER_2_WAY":
                markets[market["id"]] = market

    contracts: dict[str, list[dict]] = {}
    quotes: dict[str, dict] = {}
    for chunk in batched(list(markets)):
        joined = ",".join(chunk)
        for contract in sm_get(f"/markets/{joined}/contracts/").get("contracts", []):
            contracts.setdefault(contract["market_id"], []).append(contract)
        quotes.update(sm_get(f"/markets/{joined}/quotes/"))

    out: dict[str, dict[str, float]] = {}
    spreads: dict[str, float] = {}
    for market_id, market in markets.items():
        priced, widest = {}, 0.0
        for contract in contracts.get(market_id, []):
            book = quotes.get(str(contract["id"])) or {}
            bids, offers = book.get("bids") or [], book.get("offers") or []
            if not bids or not offers:
                widest = 1.0          # one-sided book: unusable
                continue
            bid, offer = bids[0]["price"] / 10000, offers[0]["price"] / 10000
            widest = max(widest, offer - bid)
            priced[contract["name"]] = (bid + offer) / 2
        total = sum(priced.values())
        if len(priced) == 2 and 0.8 < total < 1.2 and widest <= max_spread:
            out[market["event_id"]] = {k: v / total for k, v in priced.items()}
            spreads[market["event_id"]] = round(widest, 4)
    return out, spreads


# --- comparison ------------------------------------------------------------


def compare(sport: str, depth: str, days: int, max_events: int,
            max_spread: float) -> list[dict]:
    sport_id, event_type = SPORTS[sport]

    print(f"načítavam ponuku Niké ({sport})...", file=sys.stderr)
    offer = nike_odds.offer(sport_id, None, live=False, depth=depth, max_events=max_events)

    print(f"načítavam burzu Smarkets ({event_type})...", file=sys.stderr)
    events = exchange_events(event_type, days)
    fair, spreads = fair_probabilities(events, max_spread)
    dropped = len(events) - len(fair)
    events = [e for e in events if e["id"] in fair]
    print(f"burza: {len(events)} likvidných udalostí "
          f"({dropped} zahodených pre široké rozpätie)", file=sys.stderr)

    # Best Nike price per (match, participant) -- a boosted market beats the
    # standard one, so the maximum is what a bet would actually be placed at.
    best: dict[str, dict[str, dict]] = {}
    for row in nike_odds.rows(offer, None):
        if row["market"] not in ("Víťaz zápasu", "Superšanca", "Zápas"):
            continue
        side = best.setdefault(row["event_id"], {})
        if row["selection"] not in side or row["odds"] > side[row["selection"]]["odds"]:
            side[row["selection"]] = row

    out = []
    for event_id, sides in best.items():
        if len(sides) != 2:
            continue
        names = list(sides)
        match = next((e for e in events if same_match(names, e["name"])), None)
        if match is None:
            continue
        probs = fair[match["id"]]
        for name, row in sides.items():
            p = next((v for k, v in probs.items() if same_person(name, k)), None)
            if p is None:
                continue
            out.append(
                {
                    "sport": sport,
                    "start": row["start"][:16],
                    "event": row["event"],
                    "selection": name,
                    "market": row["market"],
                    "odds": row["odds"],
                    "implied": round(1 / row["odds"], 4),
                    "fair": round(p, 4),
                    "spread": spreads[match["id"]],
                    "edge": round(p - 1 / row["odds"], 4),
                    "ev": round(row["odds"] * p - 1, 4),
                    "event_id": event_id,
                    "bet_id": row["bet_id"],
                }
            )
    out.sort(key=lambda r: -r["edge"])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("compare", help="Nike prices against exchange fair value")
    p.add_argument("--sport", choices=sorted(SPORTS), required=True)
    p.add_argument("-f", "--format", choices=("table", "csv", "json"), default="table")
    p.add_argument("--min-edge", type=float, default=None,
                   help="only show selections at or above this edge, e.g. 0.03")
    p.add_argument("--depth", choices=("full", "primary"), default="primary",
                   help="full also reads the boosted Superšanca markets (slower)")
    p.add_argument("--days", type=int, default=3, help="exchange horizon (default 3)")
    p.add_argument("--max-events", type=int, default=600)
    p.add_argument("--max-spread", type=float, default=0.04,
                   help="reject exchange markets wider than this, in probability "
                        "(default 0.04 = 4 percentage points)")

    args = parser.parse_args()
    try:
        rows = compare(args.sport, args.depth, args.days, args.max_events,
                       args.max_spread)
    except ExchangeError as exc:
        sys.exit(str(exc))

    if args.min_edge is not None:
        rows = [r for r in rows if r["edge"] >= args.min_edge]
    print(f"spárovaných ponúk: {len(rows)}", file=sys.stderr)
    nike_odds.emit(
        rows, args.format,
        ["sport", "start", "event", "selection", "market", "odds", "implied",
         "fair", "spread", "edge", "ev", "event_id", "bet_id"],
    )


if __name__ == "__main__":
    main()
