#!/usr/bin/env bash
# Installs the collector on a Raspberry Pi as a user service.
#
# A user service, not a system one, so it needs no root and runs as whoever owns
# the git checkout and the SSH key that pushes it. Lingering is enabled so the
# timer runs when nobody is logged in, which is the normal state of a Pi.
set -euo pipefail

REPO="${BETTING_REPO:-$HOME/betting-toolkit}"
UNITS="$HOME/.config/systemd/user"

[ -d "$REPO/.git" ] || { echo "nenašiel som git repozitár v $REPO"; exit 1; }
command -v python3 >/dev/null || { echo "chýba python3"; exit 1; }
command -v flock   >/dev/null || { echo "chýba flock (apt install util-linux)"; exit 1; }

echo "== kontrola dostupnosti Niké"
python3 "$REPO/tools/nike_odds.py" check || {
  echo "Niké z tejto siete neodpovedá -- zber by nezbieral nič"; exit 1; }

echo "== inštalujem systemd jednotky do $UNITS"
mkdir -p "$UNITS"
install -m 644 "$REPO/deploy/betting-collect.service" "$UNITS/"
install -m 644 "$REPO/deploy/betting-collect.timer"   "$UNITS/"

systemctl --user daemon-reload
systemctl --user enable --now betting-collect.timer

# Without lingering the timer stops when the last session ends.
if ! loginctl show-user "$USER" -p Linger --value | grep -q yes; then
  echo "== zapínam lingering (vyžiada si heslo)"
  sudo loginctl enable-linger "$USER"
fi

echo
echo "hotovo. Užitočné príkazy:"
echo "  systemctl --user list-timers betting-collect.timer"
echo "  journalctl --user -u betting-collect.service -f"
echo "  systemctl --user start betting-collect.service   # spustiť hneď"
