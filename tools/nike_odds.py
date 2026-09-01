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


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --- offer traversal -------------------------------------------------------


def tournaments(sport_id: int | None, date: str | None) -> list[dict]:
    """Leaf boxes (tournaments) of the menu tree, optionally for one sport."""
    menu = get("/v1/menu", live=True, prematch=True, showMatchCounts=True, date=date)
    out = []
    for sport in menu.get("items", []):
        if sport_id is not None and int(sport["sportId"]) != sport_id:
            continue
        for item in sport.get("items", []):
            out.append(
                {
                    "sportId": int(sport["sportId"]),
                    "sport": sport["label"],
                    "boxId": item["boxId"],
                    "tournament": item["label"],
                    "matches": item.get("matchesCount", 0),
                }
            )
    return out


def offer(sport_id: int | None, date: str | None, live: bool) -> dict:
    """Every prematch event + its primary-market odds for a sport and day."""
    # Parent boxes (``bi-7-18-null``) are menu groupings, not queryable offers --
    # asking for one makes the gateway answer 400, so only leaf boxes are fetched.
    boxes = [t["boxId"] for t in tournaments(sport_id, date) if t["matches"]]
    events: dict[str, dict] = {}
    bets: list[dict] = []
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
        bets.extend(data.get("bets", []))
    return {"fetched_at": now_iso(), "events": events, "bets": bets}


def selections(bet: dict) -> list[dict]:
    """Flatten a bet's selection grid into ``{tip, name, odds}`` rows."""
    out = []
    for row in bet.get("selectionGrid", []) or []:
        for cell in row:
            if cell.get("type") != "selection" or cell.get("odds") is None:
                continue
            out.append(
                {
                    "tip": cell.get("tip"),
                    "name": cell.get("name"),
                    "odds": float(cell["odds"]),
                    "enabled": bool(cell.get("enabled")) and not cell.get("locked"),
                }
            )
    return out


def rows(data: dict, market: str | None) -> list[dict]:
    """One row per selection, joined to its event. The table you actually read."""
    out = []
    for bet in data["bets"]:
        header = bet.get("header", "")
        if market and market.lower() not in header.lower():
            continue
        event = data["events"].get(bet.get("sportEventId"), {})
        for sel in selections(bet):
            if not sel["enabled"]:
                continue
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

    sub.add_parser("days", parents=[common],
                   help="betting days Nike currently has an offer for")

    p = sub.add_parser("tournaments", parents=[common], help="tournaments with a live offer")
    p.add_argument("--sport", choices=sorted(SPORTS))
    p.add_argument("--date")

    p = sub.add_parser("offer", parents=[common], help="events and odds for a sport and day")
    p.add_argument("--sport", choices=sorted(SPORTS), required=True)
    p.add_argument("--date", help="YYYY-MM-DD, default: whatever Nike serves")
    p.add_argument("--market", help="substring filter, e.g. 'Víťaz'")
    p.add_argument("--live", action="store_true")

    p = sub.add_parser("event", parents=[common], help="every market for one sportEventId")
    p.add_argument("event_id")
    p.add_argument("--market")

    args = parser.parse_args()
    try:
        run(args)
    except ApiError as exc:
        sys.exit(str(exc))


def run(args: argparse.Namespace) -> None:
    if args.cmd == "days":
        days = get("/v1/init-data/mobile").get("bettingDays", [])
        emit([{"date": d} for d in days], args.format)

    elif args.cmd == "tournaments":
        sport = SPORTS.get(args.sport) if args.sport else None
        emit(tournaments(sport, args.date), args.format)

    elif args.cmd == "offer":
        data = offer(SPORTS[args.sport], args.date, args.live)
        emit(
            rows(data, args.market),
            args.format,
            ["start", "event", "market", "selection", "odds", "implied", "event_id", "bet_id"],
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
            ["market", "selection", "odds", "implied", "bet_id"],
        )


if __name__ == "__main__":
    main()
