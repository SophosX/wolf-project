# Wolf Radar — Handoff / Stand & Testplan

**Stand: 2026-07-06 ~00:25 UTC.** Diese Datei fasst zusammen, was in der Session vom
2026-07-05/06 gemacht wurde, was noch offen ist, und wie beim nächsten Mal getestet/
ausgewertet wird. (Nicht committen nötig — reines Arbeitsnotiz-File.)

Domain: https://radar.suessstoffmafia.de (DREI s). Server srv738783.
Container: `wolf-project-scraper-1` (supercronic-Cron), `wolf-project-radar-1` (Next.js UI).
Daten-Volume: `/var/lib/docker/volumes/wolf-project_daten/_data/` (videos.json, agent_runs.json,
agent_status.json, einstellungen.json, vorschlaege.json). ENV: `/opt/wolf-project/.env.server`.

## Was diese Session geändert wurde (alles committet auf Branch `fix/radar-zuverlaessig-apify-suche`)

1. **Cron-Lock-Race behoben** (`deploy/crontab`): 4h-Job + Minuten-Job feuerten beide bei :00
   mit `flock -n` → ~50 % der Läufe brachen in ms ab. Fix: Minuten-Job prüft Flag VOR flock;
   4h-Job blockiert (kein -n).
2. **Suche komplett auf Apify** (kein Data-API-Quota/429 mehr):
   - YouTube: `streamers~youtube-scraper`, ALLE 40 `SUCHQUERIES`/Lauf, Vorschläge additiv.
   - TikTok: `clockworks~tiktok-scraper`, Keyword-Suche mit `mythen_katalog.SOCIAL_SUCHQUERIES`
     (vorher NUR Watchlist/Discovery-Profile → war fast leer).
   - Instagram: Hashtag-Suche über bestehenden IG-Actor (Tag-URLs), `SOCIAL_HASHTAGS`.
   - Provenienz je Video in `quelle_query`; alle liefern `such_protokoll` (Pro-Begriff-Transparenz).
3. **UI-Transparenz**: Inbox-`SuchStatusLeiste` ("Letzte Suche vor X · N Begriffe · M gesichtet · K neu"
   + Warnung bei gestörtem Lauf + funktionierender „Jetzt suchen"-Button), `/agenten`-Sektion
   „Was die letzte Suche ergab" (pro Suchbegriff), `VideoKarte` zeigt `gefunden_am` + Suchbegriff,
   `STATUS_STALE_MS` 2h→15min, geteilter Zeitplan `lib/zeitplan.ts`.
4. **Fast-Dubletten** (`speicher.markiere_dubletten`, Ende jedes Laufs): gleicher Kanal + sehr
   ähnliche Aussage → nur reichweitenstärkstes bleibt inbox, Rest 'archiv' (`dublette_von`).
5. **Analyse-Cap** `RADAR_ANALYSE_MAX_NEU` (Default 25) je Quelle/Lauf (reichweitenstärkste zuerst).
6. Demo-Notiz „Apfelessig" aus einstellungen.json entfernt (war Test-Seed vom 4.7.).

## OFFENE PUNKTE (zuerst erledigen)

- [ ] **Cap deployen**, falls noch nicht: prüfen mit
      `docker exec wolf-project-scraper-1 grep RADAR_ANALYSE_MAX_NEU /app/scraper/lauf.py`.
      Fehlt → `cd /opt/wolf-project && docker compose up -d --build scraper` (nur wenn kein Lauf aktiv:
      `docker exec wolf-project-scraper-1 cat /app/daten/agent_status.json | grep '"aktiv"'`).
- [ ] **Backfill-Lauf** (manuell `--nur tiktok,instagram`, 23:30 UTC, ohne Cap): prüfen ob sauber
      durchlief + gespeichert (`docker exec wolf-project-scraper-1 tail -30 /tmp/social_test.log`).
- [ ] **QUALITÄT TikTok/IG prüfen** (WICHTIG, s.u.) — 36/55 TikTok geflaggt (65 %) ist verdächtig hoch.

## Testplan nächste Session

1. **Autonomie**: `docker logs wolf-project-scraper-1 | grep '0 \*/4'` (24h) — kein ms-„exit status 1";
   `grep -c 429` ≈ 0; agent_runs.json hat je 4h-Slot einen Eintrag.
2. **Abdeckung/Frische**: Videos je Plattform (youtube/tiktok/instagram, inbox) zählen; gefunden_am
   frisch/verteilt? TikTok & IG jetzt gut vertreten (vorher 0/2)?
3. **QUALITÄT (Kern)**: 10-15 geflaggte Videos quer über alle Plattformen, Schwerpunkt NEUE TikTok/IG.
   Je Video: Ist `claim.aussage` die echte Kernbehauptung? Transkript vorhanden & passend? `verdict`
   gerechtfertigt (keine Falsch-Positiven / geflaggte Debunks)? `claim.quellen` echt? Deutsch+Ernährung
   korrekt? Schwache Fälle mit Video-ID notieren. Bei Über-Flaggen: Verdict-Prompt/Schwelle in
   `analyse.py` für Social strenger.
4. **Kosten**: Apify-Ausgaben/Tag schätzen; ggf. `RADAR_*_MAX` / `RADAR_YT_APIFY_DATEFILTER` drosseln.
5. **UI**: radar.suessstoffmafia.de + /agenten sichten (Transparenz-Anzeigen, keine Duplikate).

Abschluss: klarer Bericht — was läuft, wo hakt die Qualität, konkrete Vorschläge.
Deploy immer via `docker compose up -d --build scraper radar`. Nichts ohne Rückfrage committen/deployen.

## ENV-Knöpfe (in .env.server, alle mit Defaults)
`RADAR_YT_SUCHE=apify` · `RADAR_YT_APIFY_{MAX_RESULTS=10,MAX_SHORTS,DATEFILTER=today,BATCH=10}` ·
`RADAR_TIKTOK_SUCHE=1` · `RADAR_TIKTOK_APIFY_MAX=8` · `RADAR_IG_HASHTAG_SUCHE=1` · `RADAR_IG_HASHTAG_MAX=10` ·
`RADAR_ANALYSE_MAX_NEU=25`
