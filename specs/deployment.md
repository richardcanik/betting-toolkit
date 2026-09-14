# Deployment

## Where things live

The collector runs on a **Raspberry Pi** on a Slovak connection. That is not
incidental: Niké answers a foreign address `mitigation.mode: BLOCK` instead of `FREE`,
and Cloudflare refuses a scripted client from a datacentre address outright — a GitHub
Actions runner could read the offer with `curl` but got `403` from Python on the same
URL, in the same second. A machine on an ordinary domestic line has neither problem, so
the Pi replaces a cloud runner rather than supplementing it.

| What | Where | Why |
|---|---|---|
| **The record** | `data/bets.db` on the Pi | SQLite, written directly by the collector |
| **The backup** | `data/bets.csv`, `data/odds_snapshots.csv` in git | text, diffable, survives the SD card |
| **Analysis** | over SSH, against the Pi's database | no copy to drift out of date |

The database is authoritative and the CSV is a copy of it, never the other way round.
The one exception is disaster recovery: when `data/bets.db` is missing — a fresh
machine, or a dead card — the collector rebuilds it from the committed CSV before
writing anything. Without that the cycle would export an empty database straight over
the record, which was observed destroying four selections during testing.

`history.py export` therefore refuses to write fewer rows than the file already holds
unless forced. Past odds cannot be re-collected once overwritten: a price disappears
from the offer the moment an event starts.

## The cycle

`deploy/collect.sh` runs from a systemd **user** timer every fifteen minutes, and
splits the work by how urgent it is.

| Step | Cadence | Why that cadence |
|---|---|---|
| `refresh --starting-within 90` | every tick | The closing price is gone once the event begins. Costs nothing when nothing is due, because the database is consulted before the network. |
| `consensus … \| bulk-add` | at most hourly | New selections are not urgent, and re-recording is harmless — a bet id already stored is skipped — so this only needs to be often enough not to miss a market opening. |
| `settle` | at most hourly | Results are historical fact and do not expire. |
| `export` + commit + push | at most hourly | Git is the backup, not the store. Writing it every tick would be a hundred commits a day and a hundred needless writes to an SD card. |

Both cadences are tunable through `RECORD_EVERY_MIN` and `BACKUP_EVERY_MIN`.

A `flock` stops a slow run from overlapping the next tick; the timer is `Persistent`,
so a Pi that was switched off catches up instead of skipping silently; and a failed
push is deliberately not an error, because a home connection drops and the commit goes
out with the following run.

## Installing

```
./deploy/install.sh
```

Checks that Niké answers from this network at all, installs the units under
`~/.config/systemd/user`, enables the timer and turns on lingering so it keeps running
when nobody is logged in. Nothing needs root except that one `loginctl` call.

The Pi needs an SSH key allowed to push to the repository, or the collector will commit
locally and never back anything up.

```
systemctl --user list-timers betting-collect.timer
journalctl --user -u betting-collect.service -f
systemctl --user start betting-collect.service      # run one cycle now
```

## Reading the record

Queries go to the Pi over SSH, against the live database:

```
ssh <pi> 'cd betting-toolkit && python3 tools/history.py stats'
ssh <pi> 'sqlite3 -header -column betting-toolkit/data/bets.db "…"'
```

Read-only queries are safe at any time — SQLite handles a concurrent reader — but
anything that writes should not run while a cycle might be in progress.
