# Wolf Radar — Modul-Kontrakt (verbindlich für alle Builder)

## Repo-Layout

```
wolf-radar/                  # = GitHub-Repo, Next.js-App im Root
├── app/                     # Next.js App Router (Seiten + API-Routes)
├── components/              # React-Komponenten
├── lib/daten.ts             # EINZIGER Datenzugriff der App (lokal-JSON | Supabase)
├── lib/gemini.ts            # Gemini-Client für On-Demand (Faktencheck, Neu-Skript)
├── daten/                   # Lokal-Modus-Datenablage (JSON, gitignored außer Beispiel)
├── scraper/                 # Python-Pipeline (läuft lokal + GitHub Actions)
│   ├── lauf.py              # Orchestrator: sammeln → analysieren → skripte → speichern
│   ├── youtube_agent.py     # Claim-Suche + Watchlist (Data API v3)
│   ├── tiktok_agent.py      # Watchlist + Discovery (yt-dlp)
│   ├── instagram_agent.py   # Watchlist (gallery-dl, best effort)
│   ├── mythen_katalog.py    # Suchqueries + Themen-Keywords
│   ├── analyse.py           # Gemini: Relevanz → Claim → Verdict → Scoring
│   ├── skripte.py           # Gemini: 3 Skript-Varianten (Stilguide+Playbook eingebettet)
│   ├── speicher.py          # Persistenz: lokal daten/*.json ODER Supabase (ENV-gesteuert)
│   ├── watchlist.json       # Seed-Beobachtungsliste
│   └── wissen/              # chris_stilguide.md, reaktions_playbook.md, themenlandkarte.md
├── supabase_schema.sql
└── .github/workflows/radar-cron.yml
```

## ENV (Datei .env / .env.local, nie committen)

`YT_API_KEY`, `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `RADAR_ZUGANGSCODE` (App-Zugang), `DATEN_MODUS` = `lokal` | `supabase` (Default: lokal wenn SUPABASE_URL fehlt)

## Datenmodell „video" (JSON im Lokal-Modus == Zeile in Supabase-Sicht)

```json
{
  "id": "youtube:dQw4w9WgXcQ",
  "plattform": "youtube",              // youtube | tiktok | instagram
  "video_id": "dQw4w9WgXcQ",
  "url": "https://…",
  "titel": "…",                         // TikTok/IG: erste Caption-Zeile
  "kanal": "Anzeigename",
  "kanal_id": "UC… | @handle",
  "kanal_follower": 443000,             // null wenn unbekannt
  "veroeffentlicht": "2026-07-01T10:00:00Z",
  "views": 120000, "likes": 4300, "kommentare": 210,
  "dauer_s": 58, "thumbnail_url": "https://…",
  "caption": "Beschreibung/Caption-Volltext",
  "transkript": "… oder null",
  "gefunden_am": "2026-07-03T20:00:00Z",
  "quelle": "claim_suche | watchlist | discovery",
  "status": "inbox",                    // inbox | angenommen | abgelehnt | gespeichert | strittig | archiv
  "score": 87,                          // 0-100
  "scores": { "reichweite": 90, "relevanz": 88, "tauglichkeit": 80 },
  "claim": {
    "aussage": "wörtliches Zitat der Falschaussage",
    "verdict": "klar_falsch",           // klar_falsch | strittig | korrekt (korrekt wird gar nicht gespeichert)
    "konfidenz": 0.93,
    "begruendung": "Ein Satz, warum falsch.",
    "thema": "suessstoffe"              // slug aus mythen_katalog.THEMEN
  },
  "skripte": [ { "variante": 1, "hook_typ": "o_ton_konter", "inhalt_md": "…", "quellen": [{"titel": "…", "url": "…"}] } ],
  "feedback": [ { "aktion": "abgelehnt", "kommentar": "zu klein", "zeit": "…" } ]
}
```

## Lokal-Modus-Dateien (Ordner `daten/`)

- `videos.json` — Array von video-Objekten (Quelle der Wahrheit im Lokal-Modus)
- `agent_runs.json` — Array: `{zeit, quelle, gefunden, neu, analysiert, geflaggt, fehler: [..], dauer_s}`
- `einstellungen.json` — `{gelernt: {themen_boost: {slug: -1..1}, notizen: ["…"]}, zuletzt_gelernt: "…"}`

## API-Routes (Next.js, alle hinter Zugangscode-Cookie)

- `GET  /api/videos?status=inbox&plattform=&thema=` → `{videos: [...]}` sortiert nach score desc
- `POST /api/feedback` `{video_id, aktion, kommentar?}` → aktualisiert status+feedback, triggert Lern-Update
- `POST /api/skript` `{video_id}` → generiert Skript-Paket neu (Gemini, mit Feedback-Kontext)
- `POST /api/faktencheck` `{video_id}` → ausführlicher Quellen-Check (Gemini + Search-Grounding) → `{inhalt_md, quellen}`
- `GET  /api/agenten` → agent_runs + Gesundheit
- `GET  /api/export?status=angenommen&format=md|csv`

## Scoring (in analyse.py, deterministisch nachvollziehbar)

`score = 0.4*reichweite + 0.4*relevanz + 0.2*tauglichkeit` (je 0-100)
- reichweite: log-skaliert aus max(views, follower/10) + Velocity-Bonus (views/Tage seit Upload)
- relevanz: Themen-Kerngewicht (mythen_katalog) × Verdict-Konfidenz × Schadenspotential (Gemini 1-5)
- tauglichkeit: O-Ton zitierbar (+), Watchlist-Person (+), Kurzformat (+), Alter < 14 Tage (+)
Feedback-Lernen: einstellungen.gelernt.themen_boost[slug] ∈ [-1,1] multipliziert relevanz mit (1+0.3*boost).

## Stil-Regeln UI

Deutsch, radikal einfach, Mobile-first. Dark-Theme in Chris-Palette: Near-Black #141618, Gelb #FFB800, Flächen #1D2023/#F3F3F3-Akzente, DM Sans. Eine Karte = ein Video = eine Entscheidung. Keine verschachtelten Menüs.
