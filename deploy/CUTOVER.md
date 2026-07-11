# Cutover: Christian → Supabase (Multi-Tenant Phase 3)

Voraussetzung: Supabase-Projekt existiert, `supabase_schema_v2.sql` wurde im
SQL-Editor ausgeführt (idempotent, 2× ausführen schadet nicht).

## 1. Vorbereitung (jederzeit, ohne Ausfall)

```bash
# JSON-Snapshot ziehen (Rollback-Netz)
cd /var/lib/docker/volumes/wolf-project_daten/_data
tar czf /root/wolf-daten-snapshot-$(date +%F).tgz *.json
```

## 2. Migration (jederzeit, produktionsneutral — schreibt nur nach Supabase)

```bash
cd /opt/wolf-project/scraper
SUPABASE_URL=https://<projekt>.supabase.co \
SUPABASE_SERVICE_KEY=<service-key> \
GEMINI_API_KEY=<key> \
python3 migriere_tenant_christian.py \
  --email <christians-email> --passwort '<passwort>' \
  --daten-dir /var/lib/docker/volumes/wolf-project_daten/_data
```

Zaehl-Report prüfen; das Skript druckt am Ende die **Christian-UUID**.
Bei Abweichungen: Skript ist idempotent, einfach erneut laufen lassen.

## 3. ENV-Flip (abends NACH dem 20:00-UTC-Lauf)

`.env.server` ergänzen:

```
DATEN_MODUS=supabase
AUTH_MODUS=beides
SUPABASE_URL=https://<projekt>.supabase.co
SUPABASE_SERVICE_KEY=<service-key>
NEXT_PUBLIC_SUPABASE_URL=https://<projekt>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
RADAR_STANDARD_USER=<christian-uuid-aus-schritt-2>
```

`RADAR_STANDARD_USER` sorgt dafür, dass der bisherige offene Betrieb
(kein Login) weiter auf Christians Daten aufloest — er merkt nichts.

```bash
cd /opt/wolf-project && docker compose up -d --build radar scraper
```

## 4. Smoke-Tests

```bash
for p in / /angenommen /rezepte /personen /agenten; do
  echo -n "$p: "; curl -s -o /dev/null -w "%{http_code}" "https://radar.suessstoffmafia.de$p"; echo
done
# Feedback-Roundtrip: in der App ein Video annehmen/zurückholen
# "Jetzt suchen" drücken → Tabelle auftraege bekommt eine Zeile,
# worker.py claimt sie innerhalb 1 min (docker logs wolf-project-scraper-1)
```

Nächster 4h-Cron muss `videos` (Pool) + nach dem 45er-Slot `video_zuordnung`
für Christian füllen.

## 5. Rollback (falls nötig)

`.env.server`: die neuen Zeilen entfernen (bzw. `DATEN_MODUS=lokal`),
`docker compose up -d --build radar scraper`. Das daten/-Volume wurde nie
angefasst — Verlust ist nur Feedback seit dem Flip (Snapshot aus Schritt 1).

## Bekannte Verhaltensänderung

Neue Inbox-Funde bekommen **keine automatischen Skript-Pakete** mehr —
Skripte entstehen on demand über den Button (POST /api/skript). Das spart
Gemini-Kosten pro Nutzer und war eine bewusste Multi-Tenant-Entscheidung.
