# Wolf Radar — Handoff / Stand & Betrieb

**Stand: 2026-07-11 ~20:00 UTC — MULTI-TENANT-CUTOVER DURCHGEFÜHRT.**
Branch `feat/multi-tenant` ist deployed; Datenhaltung läuft auf lokal gehostetem
Supabase. Der komplette Plan/Verlauf steht in den Commit-Messages (Phasen 0-6).

Domain: https://radar.suessstoffmafia.de (DREI s). Server srv738783.
Container: `wolf-project-scraper-1` (supercronic), `wolf-project-radar-1` (Next.js).

## Architektur (seit Cutover)

- **Supabase lokal** unter `/opt/supabase` (Postgres 15 + pgvector, GoTrue,
  PostgREST, Nginx-Gateway). Host: `http://127.0.0.1:8010`; Container erreichen es
  als `http://supabase-gateway` (externes Docker-Netz `supabase-net`, siehe
  `docker-compose.override.yml`). Secrets: `/opt/supabase/.env` (0600).
- **Geteilter Video-Pool + per-User-Kuration:** `lauf.py` läuft im Supabase-Modus
  als AKQUISE (Scrape-Plan = deduplizierte Queries ALLER Nutzer aus der View
  `scrape_queries_aktiv`, 8h-Cooldown via `scrape_status`; nur Stufe A/B →
  neutraler Claim in `videos`). `kuration.py` verteilt danach pro Nutzer
  (Matching → Top-K nach Plan → Verdict gegen SEINE Positionen → `video_zuordnung`).
- **Auftrags-Queue** `auftraege` ersetzt die `.lauf_anfrage`-Flag-Datei
  ("Jetzt suchen", Onboarding, Kuration, Lerner); `worker.py` pollt minütlich.
- **Lebendes Trigger-Profil:** `radar_profile.reaktions_ausloeser` wird beim
  Onboarding aus den eigenen Videos geseedet und von `profil_lerner.py`
  (Cron 03:00) anhand des Feedbacks fortgeschrieben (Zerfall, Belege).
- **Tenant #1 (Christian/Betreiber):** business@sustinerin.de,
  UUID `c98df88b-...` = `RADAR_STANDARD_USER` in `.env.server` — der offene
  Betrieb ohne Login löst weiter auf diesen Tenant auf.
- **Signup invite-only:** `RADAR_INVITE_CODES` in `.env.server`
  (Code auch in `/root/.wolf-radar-invite`). Onboarding: /signup → /onboarding
  (Kanal-Import via `onboarding_agent.py`) → Review → fertig.

## Betrieb / Kurzreferenz

- Deploy: `cd /opt/wolf-project && docker compose up -d --build radar scraper`
- Supabase-Stack: `cd /opt/supabase && docker compose up -d`
  (nach `restart auth/rest` auch `restart gateway` — Nginx cached Container-IPs!)
- SQL direkt: `docker exec -e PGPASSWORD=<pw> supabase-db-1 psql -h localhost -U supabase_admin -d postgres`
- REST debuggen: Keys aus `/opt/supabase/.env`, `curl -H "apikey: $SERVICE_ROLE_KEY" -H "Authorization: Bearer $SERVICE_ROLE_KEY" http://127.0.0.1:8010/rest/v1/<tabelle>`
- Kuration manuell: `docker exec wolf-project-scraper-1 sh -c 'cd /app/scraper && python3 -u kuration.py --user <uuid>'`
- Kosten-Notbremse: `RADAR_APIFY_MAX_CALLS_TAG` (Default 150 Actor-Calls/Tag).
- Rollback: `.env.server`-Supabase-Block raus (`DATEN_MODUS=lokal`) + rebuild;
  JSON-Snapshot: `/root/wolf-daten-snapshot-2026-07-11.tgz`. Runbook: `deploy/CUTOVER.md`.

## Bewusste Verhaltensänderungen

1. **Keine Auto-Skripte** mehr für Inbox-Funde — Skripte on demand (Button),
   spart Gemini-Kosten pro Nutzer.
2. Rezepte-Agent schreibt interimsweise auf den Standard-Tenant
   (echte per-User-Schleife steht aus).
3. `nachanalyse`/`neubewertung` sind reine Lokal-Modus-Werkzeuge (v2: Verdicts
   leben per-User in `video_zuordnung`).

## Offen

- Rezepte-Agent per-User (Pro-Gate); Plan-Gates hart durchsetzen (Skripte/Woche);
  Signup öffnen = `RADAR_INVITE_CODES` entfernen; zweiter Test-Creator anderer
  Nische komplett durchs Onboarding (E2E); Backup-Cron für Supabase-DB
  (pg_dump analog /opt/matrix-Muster) — **WICHTIG, aktuell kein DB-Backup!**
