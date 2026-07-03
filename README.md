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

Zugang: Zugangscode eingeben (ENV `RADAR_ZUGANGSCODE`, Dev-Default: `radar`)
oder eine beliebige URL mit `?code=radar` öffnen.

## ENV (.env.local)

| Variable | Zweck |
|---|---|
| `RADAR_ZUGANGSCODE` | App-Zugang (Default `radar`) |
| `GEMINI_API_KEY` | Skript-Generierung + Faktencheck (gemini-2.5-flash, Search-Grounding) |
| `DATEN_MODUS` | `lokal` (Default) oder `supabase` |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | nur im Supabase-Modus (Server-only!) |

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

## API (alle hinter Zugangscode)

`GET /api/videos` · `POST /api/feedback` · `POST /api/skript` · `POST /api/faktencheck` ·
`GET /api/agenten` · `GET /api/export?status=angenommen&format=md|csv`

Details: [KONTRAKT.md](./KONTRAKT.md). Die Wissens-Dateien (Chris-Stilguide,
Reaktions-Playbook) liegen in `scraper/wissen/` und werden serverseitig per `fs`
eingelesen — nicht duplizieren.
