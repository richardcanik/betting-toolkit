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
RECORD_EVERY_MIN="${RECORD_EVERY_MIN:-60}"
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

# The database is a local artifact and is not in git, so on a fresh machine it
# has to be rebuilt from the committed record before anything is written -- or
# the export at the end would overwrite that record with an empty one.
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

# The committed CSV is the record; the database is a local artifact.
$PY tools/history.py export >/dev/null || { say "export zlyhal"; exit 1; }

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
