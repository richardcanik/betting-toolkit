#!/usr/bin/env python3
"""Read the live Nike (m.nike.sk) betting offer.

Talks to the undocumented but unauthenticated JSON API behind the mobile site.
The contract this relies on is written down in specs/data-sources.md; if Nike
changes it, fix the spec and this file together.

Stdlib only. See --help for the subcommands.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = "https://m.nike.sk/api-gw/nikeone"
UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
SPORTS = {"tennis": 7, "basketball": 5, "football": 1, "hockey": 3}


class ApiError(RuntimeError):
    """The gateway rejected a request -- usually a box id it will not serve."""


def _ts() -> int:
    """Timestamp param the web client sends: last three digits sum to 14."""
    base = int(time.time()) * 1000
    while True:
        a, b = random.randint(0, 9), random.randint(0, 9)
        c = 14 - a - b
        if 0 <= c <= 9:
            return base + 100 * a + 10 * b + c


def get(path: str, **params) -> dict:
    """GET a nikeone endpoint.

    Array parameters must be sent as repeated flat keys -- ``boxId=a&boxId=b``.
    Sending them PHP/qs style (``boxId[0]=a``) makes the gateway answer 400.
    """
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        for item in value if isinstance(value, (list, tuple)) else [value]:
            if isinstance(item, bool):
                item = "true" if item else "false"
            pairs.append((key, str(item)))
    pairs.append(("channel", "Mobile"))
    pairs.append(("ts", str(_ts())))

    url = f"{BASE}{path}?{urllib.parse.urlencode(pairs)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip",
            "Accept-Language": "sk-SK,sk;q=0.9",
            "Content-Language": "sk",
            "Referer": "https://m.nike.sk/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
    except urllib.error.HTTPError as exc:
        raise ApiError(f"nike api {exc.code} for {path} ({exc.reason})") from exc
    except urllib.error.URLError as exc:
        sys.exit(f"nike api unreachable: {exc.reason}")
    return json.loads(raw)


def client_context() -> dict:
    """What Nike thinks of the caller: its IP, country, and mitigation mode.

    Nike serves a different `mitigation.mode` by country, so this is how to find
    out whether the offer is reachable from wherever the code happens to run --
    a CI runner abroad, for instance, rather than a Slovak connection.
    """
    req = urllib.request.Request(
        "https://m.nike.sk/api/v1/client-config",
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Accept-Encoding": "gzip", "Referer": "https://m.nike.sk/"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --- offer traversal -------------------------------------------------------


def tournaments(sport_id: int | None, date: str | None) -> list[dict]:
    """Every queryable tournament, found by walking the whole menu tree.

    The tree is deeper than it looks. A sport's direct children mix real
    tournaments with groupings that carry the actual tournaments another level
    down: under Tenis, ``bi-7-18-157`` (US Open - muzi) is a leaf, while
    ``bi-7-1298-null`` (Challenger) reports zero matches and hides fourteen
    tournaments beneath it. Reading only the first two levels therefore misses
    most of the offer -- for tennis, 57 tournaments out of 61.

    Only leaves are returned, because a grouping is not queryable: asking for
    its offer makes the gateway answer 400.
    """
    menu = get("/v1/menu", live=True, prematch=True, showMatchCounts=True, date=date)

    out: list[dict] = []

    def walk(node: dict, sport: dict, depth: int = 0) -> None:
        children = node.get("items") or []
        if children:
            for child in children:
                walk(child, sport, depth + 1)
            return
        if depth == 0:
            return  # the sport itself, with nothing under it
        out.append(
            {
                "sportId": int(sport["sportId"]),
                "sport": sport["label"],
                "boxId": node["boxId"],
                "tournament": node["label"],
                "matches": node.get("matchesCount", 0),
            }
        )

    for sport in menu.get("items", []):
        if sport_id is not None and int(sport["sportId"]) != sport_id:
            continue
        walk(sport, sport)

    # A tournament can appear both directly under the sport and again under a
    # grouping; keep the first sighting of each box.
    seen: set[str] = set()
    return [t for t in out if not (t["boxId"] in seen or seen.add(t["boxId"]))]


def event_markets(event_id: str) -> dict:
    """Every market of one match, including Supersanca and the derivatives.

    One failing event must not abandon the sweep, so an API error is reported
    and skipped rather than raised.
    """
    try:
        return get(
            "/v1/boxes/extended/sport-event-id",
            sportEventId=event_id,
            hideCollapsedMarkets=False,
        )
    except ApiError as exc:
        print(f"skipping event {event_id}: {exc}", file=sys.stderr)
        return {}


def offer(
    sport_id: int | None,
    date: str | None,
    live: bool,
    depth: str = "full",
    max_events: int = 120,
    workers: int = 5,
) -> dict:
    """The complete offer for a sport and day.

    The tournament search only returns each match's *primary* markets. Doing that
    alone hides two things that matter: Nike's boosted "Supersanca" prices, which
    beat the standard market on both sides, and every derivative market. So by
    default each event found is then fetched in full, and `depth="primary"` is
    the opt-out for sports whose offer is too large to sweep.
    """
    # Parent boxes (``bi-7-18-null``) are menu groupings, not queryable offers --
    # asking for one makes the gateway answer 400, so only leaf boxes are fetched.
    boxes = [t["boxId"] for t in tournaments(sport_id, date) if t["matches"]]
    events: dict[str, dict] = {}
    bets: dict[str, dict] = {}
    for box in boxes:
        try:
            data = get(
                "/v1/boxes/search/mobile",
                boxId=box,
                live=live,
                prematch=True,
                results=False,
                date=date,
            )
        except ApiError as exc:
            print(f"skipping {box}: {exc}", file=sys.stderr)
            continue
        for event in data.get("sportEvents", []):
            events.setdefault(event["sportEventId"], event)
        for bet in data.get("bets", []):
            bets.setdefault(bet["betId"], bet)

    if depth == "full" and events:
        if len(events) > max_events:
            sys.exit(
                f"{len(events)} events is more than --max-events {max_events}; "
                f"raise it to sweep them all, or use --depth primary"
            )
        print(f"sweeping all markets for {len(events)} events...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for data in pool.map(event_markets, list(events)):
                for event in data.get("sportEvents", []):
                    events.setdefault(event["sportEventId"], event)
                for bet in data.get("bets", []):
                    bets[bet["betId"]] = bet

    return {"fetched_at": now_iso(), "events": events, "bets": list(bets.values())}


def selections(bet: dict) -> list[dict]:
    """Flatten a bet's selection grid into ``{row, tip, name, odds}`` entries.

    The grid row is kept because a single bet can carry two independent markets
    as separate rows -- a basketball "Zapas" holds 1X2 on row 0 and the double
    chance on row 1. Treating them as one market gives a nonsense margin.
    """
    out = []
    for index, row in enumerate(bet.get("selectionGrid", []) or []):
        for cell in row:
            if cell.get("type") != "selection" or cell.get("odds") is None:
                continue
            out.append(
                {
                    "row": index,
                    "tip": cell.get("tip"),
                    "name": cell.get("name"),
                    "odds": float(cell["odds"]),
                    "enabled": bool(cell.get("enabled")) and not cell.get("locked"),
                }
            )
    return out


# A complete market's implied probabilities sum to a little over 1. Anything far
# above that is two markets added together; anything below 1 would be arbitrage,
# which does not occur inside a single book.
MARGIN_BAND = (1.0, 1.75)


def market_margins(sels: list[dict]) -> dict[int, float | None]:
    """Margin for each selection's market, keyed by grid row.

    The selection grid is a display layout, not a grouping: sometimes one market
    is spread over several rows (a best-of-five exact score, three rows of two),
    and sometimes one bet holds two independent markets (basketball 1X2 on row 0,
    double chance on row 1). Neither reading is universally right, so the grouping
    is chosen by which one produces a plausible margin.
    """
    if not sels or any(not s["enabled"] for s in sels):
        return {s["row"]: None for s in sels}  # incomplete: no honest margin

    rows_present = sorted({s["row"] for s in sels})
    whole = sum(1 / s["odds"] for s in sels)
    if len(sels) > 1 and MARGIN_BAND[0] <= whole <= MARGIN_BAND[1]:
        return {r: round(whole - 1, 4) for r in rows_present}

    per_row = {}
    for index in rows_present:
        row = [s for s in sels if s["row"] == index]
        total = sum(1 / s["odds"] for s in row)
        per_row[index] = (
            round(total - 1, 4)
            if len(row) > 1 and MARGIN_BAND[0] <= total <= MARGIN_BAND[1]
            else None
        )
    return per_row


def rows(data: dict, market: str | None) -> list[dict]:
    """One row per selection, joined to its event. The table you actually read.

    Each row carries its market's margin, because that is the cheapest signal of
    where Nike is pricing sharply: the boosted markets sit near 2 % while the
    standard match winner sits near 4 % and the derivatives near 8 %.
    """
    out = []
    for bet in data["bets"]:
        header = bet.get("header", "")
        if market and market.lower() not in header.lower():
            continue
        event = data["events"].get(bet.get("sportEventId"), {})
        all_sels = selections(bet)
        margins = market_margins(all_sels)
        for sel in (s for s in all_sels if s["enabled"]):
            out.append(
                {
                    "start": event.get("expiration", bet.get("expirationTime", "")),
                    "sport": event.get("sportName", ""),
                    "tournament": event.get("tournamentName", ""),
                    "event": " vs ".join(event.get("participants", [])) or "?",
                    "market": header,
                    "selection": sel["name"],
                    "odds": sel["odds"],
                    "implied": round(1 / sel["odds"], 4),
                    "margin": margins[sel["row"]],
                    "event_id": bet.get("sportEventId", ""),
                    "bet_id": bet.get("betId", ""),
                    "tip": sel["tip"],
                }
            )
    out.sort(key=lambda r: (r["start"], r["event"], r["market"]))
    return out


# --- output ----------------------------------------------------------------


def emit(records: list[dict], fmt: str, columns: list[str] | None = None) -> None:
    if not records:
        print("(no rows)", file=sys.stderr)
        return
    columns = columns or list(records[0].keys())
    if fmt == "json":
        json.dump(records, sys.stdout, ensure_ascii=False, indent=2)
        print()
    elif fmt == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    else:
        widths = {
            c: max(len(c), *(len(str(r.get(c, ""))) for r in records)) for c in columns
        }
        print("  ".join(c.ljust(widths[c]) for c in columns))
        print("  ".join("-" * widths[c] for c in columns))
        for record in records:
            print("  ".join(str(record.get(c, "")).ljust(widths[c]) for c in columns))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # -f is declared on every subcommand rather than globally so that it can be
    # written where it reads naturally: `nike_odds.py offer --sport tennis -f csv`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-f", "--format", choices=("table", "csv", "json"), default="table")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", parents=[common],
                   help="is the API reachable from here, and how does Nike see us")

    sub.add_parser("days", parents=[common],
                   help="betting days Nike currently has an offer for")

    p = sub.add_parser("tournaments", parents=[common], help="tournaments with a live offer")
    p.add_argument("--sport", choices=sorted(SPORTS))
    p.add_argument("--date")

    p = sub.add_parser("offer", parents=[common],
                       help="every market of every event for a sport and day")
    p.add_argument("--sport", choices=sorted(SPORTS), required=True)
    p.add_argument("--date", help="YYYY-MM-DD, default: whatever Nike serves")
    p.add_argument("--market", help="substring filter, e.g. 'Víťaz'")
    p.add_argument("--live", action="store_true")
    p.add_argument("--depth", choices=("full", "primary"), default="full",
                   help="full (default) sweeps every market of every event; "
                        "primary is the headline markets only")
    p.add_argument("--max-events", type=int, default=120,
                   help="refuse a full sweep larger than this (default 120)")
    p.add_argument("--workers", type=int, default=5,
                   help="parallel event fetches (default 5)")

    p = sub.add_parser("event", parents=[common], help="every market for one sportEventId")
    p.add_argument("event_id")
    p.add_argument("--market")

    args = parser.parse_args()
    try:
        run(args)
    except ApiError as exc:
        sys.exit(str(exc))


def run(args: argparse.Namespace) -> None:
    if args.cmd == "check":
        context = client_context()
        client = context.get("clientContext", {})
        mitigation = context.get("mitigation", {})
        offer = tournaments(SPORTS["tennis"], None)
        playable = [t for t in offer if t["matches"]]
        rows = [
            {"položka": "IP", "hodnota": client.get("ip", "?")},
            {"položka": "krajina", "hodnota": client.get("countryCode", "?")},
            {"položka": "mitigation.mode", "hodnota": mitigation.get("mode", "?")},
            {"položka": "tenisové turnaje", "hodnota": len(offer)},
            {"položka": "z toho s ponukou", "hodnota": len(playable)},
        ]
        emit(rows, args.format)
        if not playable:
            sys.exit("ponuka je prázdna -- pravdepodobne blokované z tejto siete")

    elif args.cmd == "days":
        days = get("/v1/init-data/mobile").get("bettingDays", [])
        emit([{"date": d} for d in days], args.format)

    elif args.cmd == "tournaments":
        sport = SPORTS.get(args.sport) if args.sport else None
        emit(tournaments(sport, args.date), args.format)

    elif args.cmd == "offer":
        data = offer(
            SPORTS[args.sport], args.date, args.live,
            depth=args.depth, max_events=args.max_events, workers=args.workers,
        )
        emit(
            rows(data, args.market),
            args.format,
            ["start", "event", "market", "selection", "odds", "implied", "margin",
             "event_id", "bet_id"],
        )

    elif args.cmd == "event":
        data = get(
            "/v1/boxes/extended/sport-event-id",
            sportEventId=args.event_id,
            hideCollapsedMarkets=False,
        )
        data = {
            "fetched_at": now_iso(),
            "events": {e["sportEventId"]: e for e in data.get("sportEvents", [])},
            "bets": data.get("bets", []),
        }
        emit(
            rows(data, args.market),
            args.format,
            ["market", "selection", "odds", "implied", "margin", "bet_id"],
        )


if __name__ == "__main__":
    main()
