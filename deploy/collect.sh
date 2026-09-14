#!/usr/bin/env bash
# One collection cycle. Run from a systemd timer every 15 minutes.
#
# Two jobs of different urgency share this script. Snapshotting bets that are
# about to start is time-critical -- a price vanishes from the offer at the off
# and cannot be recovered -- so it runs every time, and costs nothing when
# nothing is due, because the database is consulted before the network. Writing
# down new selections and settling finished ones is not urgent, so it runs at
# most hourly and keeps the request volume civil.
set -uo pipefail

REPO="${BETTING_REPO:-$HOME/betting-toolkit}"
STAMP="${XDG_STATE_HOME:-$HOME/.local/state}/betting-toolkit"
LOCK="$STAMP/collect.lock"
LAST_RECORD="$STAMP/last-record"
LAST_BACKUP="$STAMP/last-backup"
RECORD_EVERY_MIN="${RECORD_EVERY_MIN:-60}"
BACKUP_EVERY_MIN="${BACKUP_EVERY_MIN:-60}"
SPORTS="${BETTING_SPORTS:-tennis darts snooker basketball}"

mkdir -p "$STAMP"
cd "$REPO" || { echo "repozitár nenájdený: $REPO"; exit 1; }

# A slow run must never overlap the next tick.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') predchádzajúci beh ešte bežií, preskakujem"
  exit 0
fi

say() { echo "$(date '+%F %T') $*"; }
PY=${PYTHON:-python3}

say "--- cyklus začína"

# The database on this machine is the record; the collector writes into it
# directly. It is absent only on a fresh machine or after losing the disk, and
# then the committed CSV is what it is rebuilt from -- without this the export
# below would write an empty database straight over that CSV.
if [ ! -f data/bets.db ]; then
  say "databáza neexistuje, obnovujem ju zo záznamu v gite"
  $PY tools/history.py import --dir data || { say "import zlyhal"; exit 1; }
fi

# Always: the snapshot that cannot be missed.
$PY tools/history.py refresh --starting-within 90 || say "refresh zlyhal"

# Hourly: new selections, and grading what has finished.
now=$(date +%s)
last=0
[ -f "$LAST_RECORD" ] && last=$(cat "$LAST_RECORD" 2>/dev/null || echo 0)
if [ $(( (now - last) / 60 )) -ge "$RECORD_EVERY_MIN" ]; then
  for sport in $SPORTS; do
    say "zapisujem $sport"
    $PY tools/consensus.py compare --sport "$sport" -f csv \
        --days 1 --max-spread 0.10 2>/dev/null \
      | $PY tools/history.py bulk-add || say "  $sport preskočený"
  done
  $PY tools/history.py settle || say "settle zlyhal"
  echo "$now" > "$LAST_RECORD"
else
  say "zápis preskočený (naposledy pred $(( (now - last) / 60 )) min)"
fi

# Git is the off-device backup, not the working store, so it does not need
# writing every quarter hour: that would be a hundred commits a day and a
# hundred needless writes to an SD card. The database already holds everything.
last_backup=0
[ -f "$LAST_BACKUP" ] && last_backup=$(cat "$LAST_BACKUP" 2>/dev/null || echo 0)
if [ $(( ($(date +%s) - last_backup) / 60 )) -lt "$BACKUP_EVERY_MIN" ]; then
  say "--- záloha preskočená (ďalšia o $(( BACKUP_EVERY_MIN - ($(date +%s) - last_backup) / 60 )) min)"
  exit 0
fi

$PY tools/history.py export >/dev/null || { say "export zlyhal"; exit 1; }
date +%s > "$LAST_BACKUP"

if git diff --quiet -- data/; then
  say "--- bez zmien"
  exit 0
fi

git add data/
git -c user.name="betting-pi" -c user.email="betting-pi@localhost" \
    commit -q -m "collect: $(date '+%F %H:%M %Z')"
# The Pi may be offline; the commit stands and pushes with the next run.
if git push -q origin HEAD 2>/dev/null; then
  say "--- commit a push hotové"
else
  say "--- commit hotový, push zlyhal (pushne sa nabudúce)"
fi
