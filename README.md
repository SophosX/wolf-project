# 🐺 Wolf Radar

Findet reichweitenstarke deutsche Videos mit **klaren Ernährungs-Falschinfos** und bereitet
für Christian Wolf **Reaktions-Skripte** vor. Next.js 15 (App Router, TypeScript) —
Schnittstellen sind in [KONTRAKT.md](./KONTRAKT.md) verbindlich festgelegt.

## Schnellstart (lokal)

```bash
npm install
cp .env.local.beispiel .env.local   # Keys eintragen (siehe unten)
npm run dev                          # → http://localhost:3000
```

Zugang: standardmäßig **offen** — die App startet direkt im Dashboard.
Optional per ENV `RADAR_ZUGANGSCODE=<code>` hinter einen Zugangscode legen
(Einstieg dann via `/login` oder `?code=<code>`).

## ENV (.env.local)

| Variable | Zweck |
|---|---|
| `RADAR_ZUGANGSCODE` | optionaler Zugangsschutz — ungesetzt = App offen |
| `GEMINI_API_KEY` | Analyse, Skripte, Faktencheck, Audio-Transkription |
| `RADAR_MODELL_QUALITAET` | Modell für Verdict/Faktencheck/Skripte (Default `gemini-2.5-pro`) |
| `RADAR_MODELL_SCHNELL` | Modell für Vorfilter/Extraktion (Default `gemini-2.5-flash`) |
| `RADAR_WEBCHECK` | `0` schaltet die Websuche-Verifikation (Stufe C+) ab (Default an) |
| `RADAR_AUDIO_MAX` | Audio-Transkriptionen pro Lauf (Default 12) |
| `DATEN_MODUS` | `lokal` (Default) oder `supabase` |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | nur im Supabase-Modus (Server-only!) |

## Transkription (alle Plattformen)

Neue Kandidaten werden im Lauf direkt transkribiert, damit Analyse & Faktencheck mit dem
**gesprochenen Wort** arbeiten (bei TikTok/Reels steht die Falschaussage selten in der Caption):
YouTube über Auto-Untertitel (Audio-Fallback bei 429/fehlenden Subs), TikTok über das
yt-dlp-`download`-Format, Instagram über die CDN-URL aus dem Apify-Item — jeweils
ffmpeg → Mono-MP3 → Gemini-Audio-Transkription. Backfill für Bestandsvideos:
`python3 scraper/lauf.py --transkribiere`. Ohne Sprache (Musik-Shorts) bleibt das
Transkript bewusst leer.

## Scraper-Haertung: Instagram-Session-Cookie (optional) & TikTok-Discovery

**Instagram** blockt anonyme Zugriffe oft (Login-Wall, 401). Der IG-Agent läuft
ohne Login weiter (Best effort), aber mit einem Session-Cookie deutlich zuverlässiger:

1. Im Browser (am besten ein **Zweit-/Wegwerf-Account**, nicht Chris' Hauptaccount!)
   bei instagram.com einloggen.
2. DevTools öffnen (`F12` bzw. `Cmd+Alt+I`) → Tab **Application** (Chrome) /
   **Storage** (Firefox) → **Cookies** → `https://www.instagram.com`.
3. Den **Wert** des Cookies `sessionid` kopieren (lange Zeichenkette mit `%3A` darin).
4. Lokal in `.env` eintragen: `IG_SESSIONID=<wert>` — für GitHub Actions als
   Repo-Secret `IG_SESSIONID` anlegen (Settings → Secrets → Actions).

Hinweise: Der Cookie ist ein **Voll-Zugang zum Account** — nie committen, nie teilen.
Er wird ungültig, sobald man sich im Browser ausloggt (deshalb Browser-Tab einfach
schließen statt Logout). Der Agent schreibt ihn nur in eine temporäre Cookie-Datei,
die nach dem Lauf gelöscht wird. Weitere IG-Schutzmechanismen: exponentielles Backoff
zwischen Profilen, Abbruch des restlichen IG-Laufs beim ersten 401 („IG rate-limited"),
Handle-Cache `daten/ig_handle_status.json` (fehlgeschlagene Handles nur 1×/Woche erneut).
Im Cron läuft Instagram nur **1× täglich** (05:30 UTC), YouTube+TikTok alle 4 h.

**TikTok-Discovery:** Zusätzlich zur Watchlist scannt der TikTok-Agent die kuratierte
Liste `scraper/discovery.json` (~12 große deutsche Ernährungs-/Fitness-Profile,
Handles per yt-dlp verifiziert) — je Profil nur die neuesten 15 Videos, weitergereicht
werden nur Kandidaten mit > 20 000 Views (`quelle: "discovery"`).
Abschalten: `RADAR_TIKTOK_DISCOVERY=0`.

## Datenfluss

- **Lokal-Modus:** `lib/daten.ts` liest/schreibt `daten/*.json` (Write-Lock, atomare Writes).
  Fehlt `daten/videos.json`, werden die Fixtures aus `daten/beispiel/` als Fallback geladen.
  Der Python-Scraper (`scraper/`) schreibt dieselben Dateien.
- **Supabase-Modus:** identische Schnittstelle über `@supabase/supabase-js` (SERVICE_KEY, nur Server).

## Seiten

| Route | Inhalt |
|---|---|
| `/` | Inbox: gerankte Karten (Score desc) — Annehmen / Ablehnen (mit Grund) / Später / Kommentar |
| `/angenommen` | Skript-Pakete: 3 Varianten-Tabs, Kopieren, Neu generieren, Faktencheck, Export |
| `/gespeichert` | Für später gemerkt |
| `/strittig` | Konservativ geflaggt — nicht eindeutig genug |
| `/archiv` | Abgelehnt (mit Grund) + Archiv |
| `/agenten` | Agenten-Läufe, Funde je Quelle, Fehler rot, Beobachtungsliste |

## API (hinter Zugangscode, falls `RADAR_ZUGANGSCODE` gesetzt)

`GET /api/videos` · `POST /api/feedback` · `POST /api/skript` · `POST /api/faktencheck` ·
`GET /api/agenten` · `GET /api/export?status=angenommen&format=md|csv`

Details: [KONTRAKT.md](./KONTRAKT.md). Die Wissens-Dateien (Chris-Stilguide,
Reaktions-Playbook) liegen in `scraper/wissen/` und werden serverseitig per `fs`
eingelesen — nicht duplizieren.
