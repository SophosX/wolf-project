#!/bin/sh
# Erststart-Seed: fehlende Daten-Dateien ins Volume kopieren (idempotent,
# überschreibt NIE vorhandene Daten) — danach den Next-Standalone-Server starten.
set -eu

for f in /seed/daten/*.json; do
  ziel="/app/daten/$(basename "$f")"
  [ -f "$ziel" ] || cp "$f" "$ziel"
done
if [ -d /seed/daten/beispiel ] && [ ! -d /app/daten/beispiel ]; then
  cp -r /seed/daten/beispiel /app/daten/beispiel
fi
# Verwaisten Schreib-Lock nach hartem Neustart räumen
rm -f /app/daten/.videos.lock

exec node server.js
