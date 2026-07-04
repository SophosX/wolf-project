# Deployment: eigener VPS (Hostinger) mit Docker

Ein `git clone`, eine `.env`, ein `docker compose up` — mehr braucht der Server nicht.
Drei Container: **caddy** (HTTPS + Landing), **radar** (Next.js-App), **scraper**
(Python-Cron). Die Daten leben als JSON im Docker-Volume `daten`
(`DATEN_MODUS=lokal`) — **kein Supabase nötig**. Beim ersten Start wird der
mitgelieferte Bestand aus `deploy/seed/daten/` eingespielt (88 Videos, Einstellungen,
Vorschläge); vorhandene Daten werden nie überschrieben.

## Voraussetzungen

- VPS mit Ubuntu/Debian, Docker + Docker-Compose-Plugin
  (`curl -fsSL https://get.docker.com | sh`, falls noch nicht installiert)
- Domain `suesstoffmafia.de` (Hostinger)

## 1. DNS (Hostinger-Panel, einmalig)

| Typ | Name  | Wert       |
|-----|-------|------------|
| A   | `@`   | VPS-IP     |
| A   | `www` | VPS-IP     |
| A   | `radar` | VPS-IP   |

Warten, bis `dig +short suesstoffmafia.de` die VPS-IP zeigt — vorher bekommt
Caddy keine Zertifikate.

## 2. Klonen & konfigurieren

```bash
git clone https://github.com/SophosX/wolf-project.git /opt/wolf-project
cd /opt/wolf-project
cp deploy/.env.server.beispiel .env.server
nano .env.server        # GEMINI_API_KEY, YT_API_KEY, APIFY_TOKEN eintragen
```

## 3. Starten

```bash
docker compose up -d --build     # erster Build ~3–5 Minuten
```

Prüfen:

```bash
docker compose ps                # radar sollte "healthy" werden
docker compose logs -f scraper   # supercronic zeigt die geplanten Jobs
```

- `https://suesstoffmafia.de` → Landing (E-Book + Radar)
- `https://suesstoffmafia.de/buch.pdf` → E-Book lädt
- `https://radar.suesstoffmafia.de` → Wolf Radar mit dem Seed-Bestand

## 4. Ersten Scraper-Lauf anstoßen (optional, statt auf die 4-h-Marke zu warten)

```bash
docker compose exec scraper sh -c 'cd /app/scraper && python3 -u lauf.py --nur youtube,tiktok'
```

## 5. Updates einspielen

```bash
cd /opt/wolf-project
git pull
docker compose up -d --build     # Volume "daten" bleibt erhalten
```

Etwa monatlich zusätzlich `docker compose build --no-cache scraper` — das zieht
yt-dlp/gallery-dl frisch (YouTube/TikTok ändern sich laufend). Gelegentlich
`docker system prune -f` gegen wachsenden Build-Cache.

## Zeitplan des Scrapers (deploy/crontab, UTC)

- alle 4 h: YouTube + TikTok
- täglich 05:30: Instagram (Apify) + Transkript-Backfill

## Hinweise

- **Zugangsschutz:** Die App läuft bewusst offen (Entscheidung 2026-07-04). Wer sie
  absichern will, setzt in `.env.server` die Zeile `RADAR_ZUGANGSCODE=…` — mehr ist
  nicht nötig (Middleware ist opt-in).
- **Loom-Video:** Link in `landing/index.html` beim Button `id="loom"` eintragen.
- **YouTube-Quota:** 8 Suchqueries/Lauf × 6 Läufe/Tag ≈ 9.600 Einheiten — knapp
  unterm 10k-Limit. Bei Quota-Fehlern `RADAR_QUERIES_PRO_LAUF=6` setzen.
- **VPS-IP-Rate-Limits:** Rechenzentrums-IPs bekommen bei YouTube-Untertiteln eher
  HTTP 429 — der Audio-Fallback + 30-min-Cooldown fangen das ab; notfalls
  `RADAR_SUBS_COOLDOWN_S` erhöhen.
- **GitHub-Actions-Workflow** (`.github/workflows/radar-cron.yml`): nur noch manueller
  Fallback (workflow_dispatch, braucht Repo-Secrets + Supabase) — der Regelbetrieb
  läuft im scraper-Container.
- **Logs:** `docker compose logs -f radar` bzw. `scraper`; Agenten-Läufe zusätzlich
  im App-Panel unter `/agenten`.
- **Lokaler Mac-Betrieb** (launchd-Jobs `de.wolfradar.*`): nach erfolgreichem
  Server-Gang abschalten mit
  `launchctl unload ~/Library/LaunchAgents/de.wolfradar.radar.plist ~/Library/LaunchAgents/de.wolfradar.taeglich.plist`.
