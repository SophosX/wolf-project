#!/bin/sh
# Wolf Radar — lokaler Cron-Wrapper (läuft via launchd, bis GitHub-Actions live ist)
#
# Aufruf:  lauf_lokal.sh [quellen|transkribiere]
#   ohne Argument      -> youtube,tiktok (4-h-Takt)
#   "instagram"        -> nur Instagram (1x täglich, Apify)
#   "transkribiere"    -> Transkript-Backfill für Bestand
#
# launchd hat kein Homebrew-PATH und keine .env — beides wird hier gesetzt.

set -u
SCRAPER_DIR="$(cd "$(dirname "$0")" && pwd)"
RADAR_DIR="$(dirname "$SCRAPER_DIR")"
PROJEKT_DIR="$(cd "$RADAR_DIR/../.." && pwd)"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
# System-Python explizit: dort sind requests & Co. installiert
# (das Homebrew-python3 stünde im PATH zuerst, hat die Module aber nicht)
PYTHON3="/usr/bin/python3"

# API-Keys aus der Projekt-.env laden
if [ -f "$PROJEKT_DIR/.env" ]; then
  set -a
  . "$PROJEKT_DIR/.env"
  set +a
fi

# Nie zwei Läufe parallel (mkdir ist atomar); verwaiste Locks nach 3 h ignorieren.
# FESTER Pfad (nicht $TMPDIR): die App prüft/startet Läufe über denselben Lock.
LOCK="/tmp/wolfradar-lauf.lock"
if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
  rmdir "$LOCK" 2>/dev/null || true
fi
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[lauf_lokal] $(date '+%F %T') Lauf uebersprungen — anderer Lauf aktiv" >&2
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT INT TERM

LOG_DIR="$RADAR_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/lauf_lokal.log"
# Log klein halten: bei > 2 MB die ältere Hälfte verwerfen
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || echo 0)" -gt 2097152 ]; then
  tail -c 1048576 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

MODUS="${1:-youtube,tiktok}"
echo "==== $(date '+%F %T') Lauf startet (Modus: $MODUS) ====" >> "$LOG"
cd "$SCRAPER_DIR"
if [ "$MODUS" = "transkribiere" ]; then
  "$PYTHON3" -u lauf.py --transkribiere >> "$LOG" 2>&1
else
  "$PYTHON3" -u lauf.py --nur "$MODUS" >> "$LOG" 2>&1
fi
STATUS=$?
echo "==== $(date '+%F %T') Lauf fertig (Exit $STATUS) ====" >> "$LOG"
exit $STATUS
