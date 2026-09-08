#!/usr/bin/env python3
"""Persistent history of every bet selected in this project.

One SQLite file, ``data/bets.db``. Selections are appended when they are made,
closed when the match finishes, and read back as calibration statistics. The
schema and the meaning of each column are specified in specs/tracking.md.

Naming note: ``bets.event_id`` and ``bets.bet_id`` are *Nike's* identifiers,
carried so a row can always be matched back to the offer it came from.
``odds_snapshots.bet_ref`` is this database's own ``bets.id``.
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(
    os.environ.get("BETTING_DB")
    or Path(__file__).resolve().parent.parent / "data" / "bets.db"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id          INTEGER PRIMARY KEY,
    placed_at   TEXT NOT NULL,           -- when the selection was made (ISO 8601)
    starts_at   TEXT,                    -- scheduled start of the event
    sport       TEXT NOT NULL,
    event       TEXT NOT NULL,           -- "Shelton B. vs Hurkacz H."
    event_id    TEXT,                    -- Nike sportEventId
    bet_id      TEXT,                    -- Nike betId
    market      TEXT NOT NULL,
    selection   TEXT NOT NULL,
    odds_nike   REAL NOT NULL,           -- odds actually taken
    odds_close  REAL,                    -- closing odds, filled in at close time
    p_est_low   REAL NOT NULL,           -- fair probability, lower bound
    p_est_high  REAL NOT NULL,           -- fair probability, upper bound
    edge        REAL NOT NULL,           -- p_est_low - 1/odds_nike (conservative)
    ev          REAL NOT NULL,           -- odds_nike * p_est_low - 1
    stake       REAL NOT NULL DEFAULT 1.0,
    confidence  TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    factors     TEXT,                    -- comma-separated drivers, see specs
    note        TEXT,
    result      TEXT CHECK (result IN ('win', 'loss', 'void')),
    pnl         REAL,
    settled_at  TEXT
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id       INTEGER PRIMARY KEY,
    bet_ref  INTEGER NOT NULL REFERENCES bets(id) ON DELETE CASCADE,
    taken_at TEXT NOT NULL,
    odds     REAL NOT NULL,
    source   TEXT NOT NULL DEFAULT 'nike'
);

CREATE INDEX IF NOT EXISTS idx_bets_open ON bets(result) WHERE result IS NULL;
CREATE INDEX IF NOT EXISTS idx_snapshots_bet ON odds_snapshots(bet_ref);
"""


def parse_start(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.astimezone()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def show(rows: list[sqlite3.Row] | list[dict], columns: list[str]) -> None:
    records = [dict(r) for r in rows]
    if not records:
        print("(nothing yet)")
        return
    fmt = lambda v: "" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
    widths = {c: max(len(c), *(len(fmt(r.get(c))) for r in records)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for record in records:
        print("  ".join(fmt(record.get(c)).ljust(widths[c]) for c in columns))


# --- commands --------------------------------------------------------------


def cmd_add(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    p_low, p_high = args.p_low, args.p_high if args.p_high is not None else args.p_low
    if not 0 < p_low <= p_high < 1:
        sys.exit("probabilities must satisfy 0 < p_low <= p_high < 1")
    if args.odds <= 1:
        sys.exit("odds must be greater than 1")

    edge = p_low - 1 / args.odds
    ev = args.odds * p_low - 1
    cur = conn.execute(
        """INSERT INTO bets (placed_at, starts_at, sport, event, event_id, bet_id,
                             market, selection, odds_nike, p_est_low, p_est_high,
                             edge, ev, stake, confidence, factors, note)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            now_iso(), args.starts_at, args.sport, args.event, args.event_id,
            args.bet_id, args.market, args.selection, args.odds, p_low, p_high,
            edge, ev, args.stake, args.confidence, args.factors, args.note,
        ),
    )
    conn.execute(
        "INSERT INTO odds_snapshots (bet_ref, taken_at, odds, source) VALUES (?,?,?,?)",
        (cur.lastrowid, now_iso(), args.odds, "nike"),
    )
    conn.commit()
    print(f"#{cur.lastrowid}  edge {edge:+.1%}  EV {ev:+.1%}  {args.selection} @ {args.odds}")


def cmd_snapshot(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    if conn.execute("SELECT 1 FROM bets WHERE id = ?", (args.id,)).fetchone() is None:
        sys.exit(f"no bet #{args.id}")
    conn.execute(
        "INSERT INTO odds_snapshots (bet_ref, taken_at, odds, source) VALUES (?,?,?,?)",
        (args.id, now_iso(), args.odds, args.source),
    )
    conn.commit()
    print(f"#{args.id}  {args.source} @ {args.odds}")


def cmd_close(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    row = conn.execute("SELECT * FROM bets WHERE id = ?", (args.id,)).fetchone()
    if row is None:
        sys.exit(f"no bet #{args.id}")
    if row["result"] is not None:
        sys.exit(f"#{args.id} is already settled as {row['result']}")

    closing = args.odds_close
    if closing is None and row["starts_at"]:
        # The closing price is the last price seen before the event began.
        last = conn.execute(
            """SELECT odds FROM odds_snapshots
               WHERE bet_ref = ? AND taken_at <= ? ORDER BY taken_at DESC LIMIT 1""",
            (args.id, row["starts_at"]),
        ).fetchone()
        if last:
            closing = last["odds"]

    pnl = {"win": row["stake"] * (row["odds_nike"] - 1), "loss": -row["stake"], "void": 0.0}
    conn.execute(
        "UPDATE bets SET result = ?, pnl = ?, settled_at = ?, odds_close = COALESCE(?, odds_close) WHERE id = ?",
        (args.result, pnl[args.result], now_iso(), closing, args.id),
    )
    if args.odds_close:
        conn.execute(
            "INSERT INTO odds_snapshots (bet_ref, taken_at, odds, source) VALUES (?,?,?,?)",
            (args.id, now_iso(), args.odds_close, "nike-close"),
        )
    conn.commit()
    print(f"#{args.id}  {args.result}  pnl {pnl[args.result]:+.2f}")


def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    where, params = [], []
    if not args.all:
        where.append("result IS NULL")
    if args.sport:
        where.append("sport = ?")
        params.append(args.sport)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(f"SELECT * FROM bets {clause} ORDER BY starts_at, id", params).fetchall()
    show(rows, ["id", "starts_at", "sport", "event", "market", "selection",
                "odds_nike", "edge", "confidence", "result", "pnl"])


def cmd_stats(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    params = [args.sport] if args.sport else []
    clause = "WHERE result IS NOT NULL AND result != 'void'" + (" AND sport = ?" if args.sport else "")
    rows = conn.execute(f"SELECT * FROM bets {clause}", params).fetchall()
    if not rows:
        print("no settled bets yet")
        return

    wins = sum(r["result"] == "win" for r in rows)
    staked = sum(r["stake"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    expected = sum(r["p_est_low"] for r in rows)
    print(f"settled      {len(rows)}")
    print(f"hit rate     {wins / len(rows):.1%}  (model expected {expected / len(rows):.1%})")
    print(f"ROI          {pnl / staked:+.1%}  ({pnl:+.2f} units on {staked:.2f} staked)")

    priced = [r for r in rows if r["odds_close"]]
    if priced:
        clv = sum(r["odds_nike"] / r["odds_close"] - 1 for r in priced) / len(priced)
        beat = sum(r["odds_nike"] > r["odds_close"] for r in priced)
        print(f"CLV          {clv:+.2%} average, beat the close {beat}/{len(priced)}")
    else:
        print("CLV          no closing odds recorded yet")

    print("\ncalibration by stated confidence")
    band = conn.execute(
        f"""SELECT confidence, COUNT(*) n,
                   AVG(result = 'win') hit, AVG(p_est_low) expected,
                   SUM(pnl) / SUM(stake) roi
            FROM bets {clause} GROUP BY confidence""", params).fetchall()
    show(band, ["confidence", "n", "hit", "expected", "roi"])

    print("\nfactor breakdown (which drivers actually work)")
    counts: dict[str, list[int]] = {}
    for row in rows:
        for factor in (row["factors"] or "").split(","):
            factor = factor.strip()
            if not factor:
                continue
            tally = counts.setdefault(factor, [0, 0])
            tally[0] += 1
            tally[1] += row["result"] == "win"
    show(
        [{"factor": k, "n": v[0], "hit": v[1] / v[0]} for k, v in
         sorted(counts.items(), key=lambda kv: -kv[1][0])],
        ["factor", "n", "hit"],
    )


EXPORT_DIR = DB_PATH.parent
TABLES = ("bets", "odds_snapshots")


def columns_of(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def confidence_from_spread(spread: float) -> str:
    """How much the exchange's fair price can be trusted.

    The bid/offer spread is the honest width of the estimate: a market quoted
    within two points is a firm number, one quoted eight points wide is barely a
    number at all.
    """
    if spread <= 0.03:
        return "high"
    return "medium" if spread <= 0.06 else "low"


def cmd_bulk_add(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Record a whole batch of selections from tools/consensus.py output.

    Both sides of every priced match are recorded, not only the likely winner.
    Calibration can only be checked across the full probability range, and a
    record made only of favourites would answer a different, useless question.

    Re-running on the same day is safe: a selection already stored for the same
    Nike bet id is skipped rather than duplicated.
    """
    handle = sys.stdin if args.csv == "-" else open(args.csv, newline="", encoding="utf-8")
    rows = list(csv.DictReader(handle))
    if handle is not sys.stdin:
        handle.close()

    added = skipped = 0
    for row in rows:
        fair, spread = float(row["fair"]), float(row["spread"])
        low = max(0.001, fair - spread / 2)      # conservative end of the estimate
        high = min(0.999, fair + spread / 2)
        existing = conn.execute(
            "SELECT 1 FROM bets WHERE bet_id = ? AND selection = ?",
            (row["bet_id"], row["selection"]),
        ).fetchone()
        if existing:
            skipped += 1
            continue
        odds = float(row["odds"])
        cur = conn.execute(
            """INSERT INTO bets (placed_at, starts_at, sport, event, event_id, bet_id,
                                 market, selection, odds_nike, p_est_low, p_est_high,
                                 edge, ev, stake, confidence, factors, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now_iso(), row["start"], row["sport"], row["event"], row["event_id"],
                row["bet_id"], row["market"], row["selection"], odds, low, high,
                low - 1 / odds, odds * low - 1, args.stake,
                confidence_from_spread(spread), "exchange-consensus",
                f"spread {spread:.4f}; fair {fair:.4f}",
            ),
        )
        conn.execute(
            "INSERT INTO odds_snapshots (bet_ref, taken_at, odds, source) VALUES (?,?,?,?)",
            (cur.lastrowid, now_iso(), odds, "nike"),
        )
        added += 1
    conn.commit()
    stake_note = "papierovo (stake 0)" if args.stake == 0 else f"stake {args.stake}"
    print(f"zapísaných {added}, preskočených ako duplicita {skipped}  [{stake_note}]")


SPORT_IDS = {"tennis": 7, "darts": 88, "snooker": 85, "basketball": 5,
             "table-tennis": 61}


def cmd_refresh(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Re-read Nike's current price for every open bet and store a snapshot.

    A single price captured once is not a record of anything: odds move as money
    and team news arrive, so a selection written down a day early may bear no
    relation to what was available at the off. Repeated snapshots turn that
    unknown into a measurement -- they show how far the line drifted, and the
    last one taken before the start is the closing price that CLV needs.

    What the payout depends on is only the price taken, which is already stored.
    The reason to look again is different: the last price before the off is the
    market's final estimate of the probability, so comparing it against the price
    taken says whether the selection beat the market -- a question that answers
    itself after tens of bets, where win/loss needs hundreds.

    That makes intermediate snapshots optional. Passing --starting-within limits
    the refresh to bets about to begin, which is the only snapshot that has to be
    caught, because after the start it is gone for good.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import nike_odds

    open_bets = conn.execute(
        "SELECT * FROM bets WHERE result IS NULL AND bet_id IS NOT NULL"
    ).fetchall()
    if args.starting_within is not None:
        cutoff = datetime.now(timezone.utc) + timedelta(minutes=args.starting_within)
        now = datetime.now(timezone.utc)
        picked = []
        for bet in open_bets:
            start = parse_start(bet["starts_at"])
            if start and now <= start <= cutoff:
                picked.append(bet)
        open_bets = picked
    if not open_bets:
        print("žiadne otvorené stávky v tomto okne")
        return

    wanted = {r["sport"] for r in open_bets}
    current: dict[tuple[str, str], float] = {}
    for sport in sorted(wanted):
        sport_id = SPORT_IDS.get(sport)
        if sport_id is None:
            continue
        try:
            offer = nike_odds.offer(sport_id, None, live=False, depth=args.depth,
                                    max_events=args.max_events)
        except SystemExit:
            print(f"  {sport}: ponuku sa nepodarilo načítať", file=sys.stderr)
            continue
        for row in nike_odds.rows(offer, None):
            current[(row["bet_id"], row["selection"])] = row["odds"]

    moved = unchanged = gone = 0
    drift = []
    for bet in open_bets:
        odds = current.get((bet["bet_id"], bet["selection"]))
        if odds is None:
            gone += 1
            continue
        last = conn.execute(
            "SELECT odds FROM odds_snapshots WHERE bet_ref = ? ORDER BY id DESC LIMIT 1",
            (bet["id"],),
        ).fetchone()
        if last and abs(last["odds"] - odds) < 1e-9:
            unchanged += 1
            continue
        conn.execute(
            "INSERT INTO odds_snapshots (bet_ref, taken_at, odds, source) VALUES (?,?,?,?)",
            (bet["id"], now_iso(), odds, "nike"),
        )
        moved += 1
        drift.append((abs(odds - bet["odds_nike"]) / bet["odds_nike"], bet, odds))
    conn.commit()

    print(f"otvorených {len(open_bets)}: {moved} sa pohlo, {unchanged} bez zmeny, "
          f"{gone} už nie je v ponuke")
    for _, bet, odds in sorted(drift, reverse=True, key=lambda d: d[0])[:10]:
        shift = (odds - bet["odds_nike"]) / bet["odds_nike"]
        print(f"  #{bet['id']:<4d} {bet['event'][:34]:34s} {bet['selection'][:18]:18s} "
              f"{bet['odds_nike']:5.2f} -> {odds:5.2f}  {shift:+.1%}")


def cmd_export(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Write the committed, reviewable copy of the history.

    The database itself is a local artifact and is not version controlled -- a
    SQLite file is an opaque blob that git cannot diff or merge. These CSVs are
    the durable record, and `import` rebuilds the database from them.
    """
    target = Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        cols = columns_of(conn, table)
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        path = target / f"{table}.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=cols)
            writer.writeheader()
            writer.writerows(dict(r) for r in rows)
        print(f"{len(rows):4d} rows -> {path}")


def cmd_import(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Rebuild the database from the committed CSVs, replacing its contents."""
    source = Path(args.dir)
    missing = [t for t in TABLES if not (source / f"{t}.csv").exists()]
    if missing:
        sys.exit(f"no export found for: {', '.join(missing)} in {source}")

    existing = conn.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
    if existing and not args.force:
        sys.exit(f"{DB_PATH} already holds {existing} bets; pass --force to replace them")

    with conn:
        conn.execute("DELETE FROM odds_snapshots")
        conn.execute("DELETE FROM bets")
        for table in TABLES:
            cols = columns_of(conn, table)
            with open(source / f"{table}.csv", newline="", encoding="utf-8") as handle:
                rows = [
                    tuple(r[c] if r.get(c) not in ("", None) else None for c in cols)
                    for r in csv.DictReader(handle)
                ]
            if rows:
                placeholders = ",".join("?" * len(cols))
                conn.executemany(
                    f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", rows
                )
            print(f"{len(rows):4d} rows <- {source / f'{table}.csv'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create data/bets.db")

    p = sub.add_parser("add", help="record a selected bet")
    p.add_argument("--sport", required=True)
    p.add_argument("--event", required=True, help='"Shelton B. vs Hurkacz H."')
    p.add_argument("--market", required=True)
    p.add_argument("--selection", required=True)
    p.add_argument("--odds", type=float, required=True)
    p.add_argument("--p-low", type=float, required=True, help="fair probability, lower bound")
    p.add_argument("--p-high", type=float, help="upper bound; defaults to --p-low")
    p.add_argument("--confidence", choices=("low", "medium", "high"), required=True)
    p.add_argument("--stake", type=float, default=1.0, help="units, default 1 (flat)")
    p.add_argument("--factors", help="comma-separated drivers, e.g. 'fatigue,surface-form'")
    p.add_argument("--starts-at")
    p.add_argument("--event-id", help="Nike sportEventId")
    p.add_argument("--bet-id", help="Nike betId")
    p.add_argument("--note")

    p = sub.add_parser("snapshot", help="record another odds observation for a bet")
    p.add_argument("id", type=int)
    p.add_argument("--odds", type=float, required=True)
    p.add_argument("--source", default="nike")

    p = sub.add_parser("close", help="settle a bet")
    p.add_argument("id", type=int)
    p.add_argument("result", choices=("win", "loss", "void"))
    p.add_argument("--odds-close", type=float, help="closing odds, for CLV")

    p = sub.add_parser("list", help="open bets, or --all")
    p.add_argument("--all", action="store_true")
    p.add_argument("--sport")

    p = sub.add_parser("stats", help="hit rate, ROI, CLV, calibration")
    p.add_argument("--sport")

    p = sub.add_parser("refresh",
                       help="re-read current odds for open bets and snapshot them")
    p.add_argument("--depth", choices=("full", "primary"), default="primary")
    p.add_argument("--max-events", type=int, default=600)
    p.add_argument("--starting-within", type=int, metavar="MIN",
                   help="only bets starting within this many minutes -- the "
                        "closing snapshot, which is the one that cannot be missed")

    p = sub.add_parser("bulk-add", help="record a batch from consensus.py CSV output")
    p.add_argument("--csv", default="-", help="path, or - for stdin (default)")
    p.add_argument("--stake", type=float, default=0.0,
                   help="0 (default) records without money at stake")

    p = sub.add_parser("export", help="write the committed CSV copy of the history")
    p.add_argument("--dir", default=str(EXPORT_DIR))

    p = sub.add_parser("import", help="rebuild the database from the committed CSVs")
    p.add_argument("--dir", default=str(EXPORT_DIR))
    p.add_argument("--force", action="store_true", help="replace a non-empty database")

    args = parser.parse_args()
    conn = connect()
    if args.cmd == "init":
        print(f"ready: {DB_PATH}")
    else:
        # subcommand names may contain hyphens; function names cannot
        globals()[f"cmd_{args.cmd.replace('-', '_')}"](conn, args)
    conn.close()


if __name__ == "__main__":
    main()
