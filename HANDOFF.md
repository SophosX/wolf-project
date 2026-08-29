# Wolf Radar — Handoff / Stand & Betrieb

**Stand: 2026-08-29 — QA-Session „kaum Videos für neuen Account“ (siehe Session-Log unten).**
Branch `feat/multi-tenant`, deployed. Vorheriger Stand (2026-07-11 Cutover) darunter unverändert.

## Session 2026-08-29 — QA „neuer Account findet kaum Videos“ (Peter, free, Medizin/Psychologie/Klima/Beauty)

**Ursachen (verifiziert):**
1. **Pool war nicht mandantenneutral (Kernfehler):** `lauf.py` rief `analyse.extrahiere_claims()`
   ohne Themen/Nische → Fallback auf Christians `mythen_katalog` + Nische „Ernährung…“. Jedes
   Nicht-Ernährungs-Video wurde in Stufe A/B „aussortiert“ (aussage=null) und konnte NIE in
   eine fremde Inbox. DB-Beleg: `claim->>'thema'` war zu 100 % ein Christian-Slug.
2. **Kuration:** aussortierte Videos zählten als Kandidaten, belegten per Keyword die Top-K und
   wurden dann still übersprungen („bewertet werden=10, 0 zugeordnet in 1 s“).
3. **Relevanz-Gate** maß nur gegen das Keyword-Thema (0.66) → 39/42 passende Kandidaten verworfen.
4. **Kurations-Fenster „seit letztem Lauf“** → Warteschlange/knapp Gescheiterte kamen nie wieder dran.
5. **Free-Cap** (6 Themen/12 Queries) first-come → 4. Bereich (Klima) still komplett weg.
6. **Suchbreite:** YT `dateFilter=today`+5 Results, TikTok 5 Results+90 T → winzige Ausbeute;
   `scrape_status.treffer_gesamt` wurde nie geschrieben (keine Ertragsdaten).
7. **„Jetzt suchen“** eines Nutzers lief ohne seine Queries (24h-Cooldown/Rotation).
8. Katalog-Query „Krankheit XY …“ war wörtlich „XY“.

**Fixes (Commits e7c7030 … 19bf08f):**
- Stufe A/B neutral: Kategorien = `interessen_katalog`-Bereiche (+`sonstiges`), Nische = alle
  Bereiche + Nutzer-Nischen (`themenwelt.pool_kategorien/pool_nische_text`,
  `analyse._system_stufe_ab_neutral`, `extrahiere_claims(neutral=True)`); `videos.kategorie`
  kommt jetzt aus dem LLM-Bereich. `scraper/backfill_neutral.py` hat 56/77 aussortierte Videos
  der letzten 14 Tage nachextrahiert.
- Kuration: nur Kandidaten mit Aussage; Gate gegen ALLE Themen (ähnlichstes wird zugeordnet);
  Schwellen: eigene Bereiche 0.60 (`RADAR_MATCH_MIN_AEHNLICHKEIT_EIGEN`), sonst 0.66, fachfremd
  0.68; festes Fenster `RADAR_KURATION_FENSTER_TAGE=14`; Diagnose in `agent_runs.detail`.
- Ertrag je Suchbegriff: `scrape_status.letzte_treffer/leer_folge/fenster` (Migration in
  `supabase_schema_v2.sql`, auf dem Server ausgeführt). Adaptive Breite `themenwelt.fenster_fuer`:
  neue Query → month/breit; 1× leer → month; ≥2× leer → year/breit. YT-Basis `week` (Kosten
  identisch, maxResults deckelt). TikTok/IG „breit“ = 15 Results + 365 Tage (2. Actor-Call).
- `lauf.py --user <uuid>` (Worker gibt es durch): Queries des Anfragenden ohne Rotation/Cooldown
  (min. `RADAR_BEVORZUGT_MIN_H=1`). Cooldown-Leerlauf scrapt nicht mehr den Seed-Katalog.
- `scraper/suchhilfe.py`: Begriffe mit ≥3 leeren Läufen (trotz weitestem Fenster) werden per
  Gemini durch eine plattformtypische breitere Variante ersetzt (alt aktiv=false, neu quelle=lerner),
  Hinweis in `einstellungen.such_hinweise`; läuft am Ende jedes Akquise-Laufs.
- UI: `/api/suchstatus` (GET Diagnose, POST `{aktion:"breiter"}`), `components/InboxDiagnose.tsx`
  (Inbox <3 Karten: welche Begriffe fanden was, was die Prüfung ergab, Empfehlung
  warten/breiter/spezifizieren, Buttons „Jetzt breiter suchen“/„Suchbegriffe anpassen“/„Interessen
  erweitern“, Hinweis auf strittige Funde). `/einstellungen` zeigt Ertrag je Query. Onboarding
  legt Starter-Pack reihum über Bereiche an und meldet Plan-Cap-Verluste im Review.

**Zweite Runde (User: „nur strittige Zuordnungen ist dumm“):** Peter hatte nach der ersten Runde
11 strittig / 0 inbox. Ursache: Stufe C bewertete gegen **Christians Positionstabelle** (Fallback
für Nutzer ohne eigene Positionen) und durfte nur dort Gedecktes flaggen → Medizin-Claims
„außerhalb des Kernbereichs“ = strittig (0.9). Fix (fd2530a):
- `themenwelt.massstab_text()`: Maßstab je Nutzer = Positionen (falls vorhanden) + Nische +
  Trigger-Liste + Themen; Standard-Tenant behält seine `themenlandkarte.md`.
- Neues Verdict **`irrefuehrend`** (nicht widerlegt, aber als Botschaft irreführend: unbelegte
  Heils-/Rendite-Versprechen, Ferndiagnosen, absolute Ansprüche) → **inbox ab Konfidenz 0.75**
  wie `klar_falsch`. Sicherheitsnetze (Debunk, Kurzvideo ohne Transkript) gelten weiter.
- Nachschub-Garantie in `kuration.py`: zweiter Bewertungs-Batch bis 2× Plan-Cap, solange die
  Inbox < `RADAR_INBOX_MIN` (3); bleibt sie leer → automatischer Suchlauf (`auftraege` typ=lauf
  für den Nutzer, max. alle `RADAR_NACHSCHUB_H`=8 h, Marker `einstellungen.nachschub_auto`).
- UI: „Warum irreführend:“ auf der Karte; `KONTRAKT.md` ergänzt.

**Review-Runde (3 Prüf-Agenten, Commit c354274):** `lauf.py --user` scrapt nur die Queries des
Nutzers (Kosten!), Worker läuft unter `/tmp/radar.lock` und setzt `RADAR_AUFTRAG_ID`, `irrefuehrend`
durchläuft die Websuche (nuanciert/unklar demotet nicht), `suchhilfe` mit `on_conflict`, Ertrag nur
für wirklich gesuchte Begriffe, breite Suche auf `RADAR_MAX_ALTER_TAGE` gedeckelt, Kuration:
`match_pool` im 14-Tage-Fenster, Watchlist umgeht das Gate, Fehler → `archiv`, Nachschlag nur
innerhalb `kuration_pro_tag`. App: `scrape_status` nur für eigene Norms, „Breiter suchen“ fasst nur
ertragslose eigene Begriffe an und überschreibt `zuletzt` nicht, Empfehlungslogik gehärtet,
Onboarding-Upserts prüfen Fehler. Gemeinsame Normalisierung `lib/suchnorm.ts` ↔
`themenwelt.query_norm`.

**Ergebnis nach Reset + Neu-Kuration (17:50 UTC):** Peter **7 inbox** (klar_falsch/irrefuehrend
mit Websuche-Belegen, z. B. „OPs in 9 von 10 Fällen überflüssig“, Impf-Verschwörung) + 3 archiv;
Finanztest 2 inbox, Labeltest 1 inbox.

**Betriebsregeln neu:** `_supabase_speichere_videos` patcht claim/kategorie/embedding NICHT für
bestehende Zeilen — nach Prompt-/Kategorie-Änderungen ist `backfill_neutral.py` Pflicht.
Peters/Test-Zuordnungen ohne Feedback dürfen bei Logik-Änderungen zurückgesetzt werden
(`delete … where feedback='[]'`), damit die Kuration neu bewertet.

**Offen / beobachten:**
- Apify-Kosten nach den breiteren Fenstern 2–3 Tage beobachten (`GET api.apify.com/v2/users/me/limits`),
  Ziel <1 $/Tag; Stellschrauben `RADAR_YT_APIFY_BREIT_RESULTS`, `RADAR_TIKTOK_APIFY_BREIT_MAX`.
- Erste automatische Query-Ersetzungen (suchhilfe) stichprobenartig prüfen (Log `[suchhilfe]`).
- Ob „strittig“ für Neu-Nutzer sichtbar genug ist (Inbox bleibt leer, solange nichts ≥0.75).

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

## Session 2026-07-11 spaet (nach Cutover) — Kurzlog

1. **Admin-Dashboard** (/admin, nur echte Admin-Session): Nutzerliste mit
   Aktivitaet, Plan-Wechsel, per-User-Limit-Overrides (profiles.limits),
   Invite-Codes + Invite-ANFRAGEN (Landing-Formular -> ntfy-Push -> Einladen
   mit mailto-Entwurf). Christian gedrosselt (kuration 10, queries/Lauf 30).
2. **Gefuehrtes Onboarding**: Interessen-Chips (interessen_katalog.json,
   12 Bereiche mit Starter-Packs) -> sofortige Themen/Queries/Trigger;
   Kanal optional; Fokus-Freitext als Reduce-Leitplanke; Live-Fortschritt
   (auftraege.payload); Abschluss stoesst vollen Lauf an (~30 min erste Funde).
3. **Landing /start** (Hero, 3 Schritte, Mock-Karte, Login, Invite-Anfrage);
   offener Betrieb beendet — Christian via Magic-Link (/root/.wolf-radar-magiclink).
4. **Pool-Vernetzung**: videos.kategorie + claim_embedding(768) + HNSW;
   RPCs match_pool/aehnliche_videos; Kuration matcht Keyword + semantisch.
5. **Multi-Nischen-Fixes nach Finanz-Testnutzer** (finanztest@/labeltest@):
   - Keyword-Matching ohne Transkript + semantisches Relevanz-Gate
     (EMPIRISCH kalibriert: Basis 0.66, fachfremd/unkategorisiert 0.68 —
     gemini-embedding-Baseline ist ~0.58, geratene Schwellen wirkungslos!).
   - Keyword-Vorfilter gilt nicht mehr fuer Claim-Suche-Treffer (Query=Signal).
   - Rezepte = Feature-Flag (einstellungen.rezepte_aktiv), Tab adaptiv.
   - Beobachtungsliste user-scoped (lib/watchlist.ts las Christians Datei!),
     PersonHinzufuegen-Formular, Lerner schlaegt Kanaele mit >=2 Annahmen vor.
   - Such-Protokoll (/api/agenten) pro Nutzer gefiltert (Privacy!).
   Verifiziert: Kuration finanztest vs 253er-Ernaehrungs-Pool ->
   relevanz_gate=49, 0 Zuordnungen, 0 LLM-Kosten.

## Offen

- Rezepte-Agent echte per-User-Schleife (aktuell Standard-Tenant-Bruecke).
- Signup oeffnen = `RADAR_INVITE_CODES` entfernen (User-Entscheidung).
- Testnutzer finanztest@/labeltest@ behalten oder loeschen (User fragen).
- PR feat/multi-tenant -> main, wenn stabil.
- Erledigt seit letztem Stand: Plan-Gates (Skripte/Woche 403), E2E-Test
  Finanz-Creator komplett, DB-Backup-Cron 02:30 (/opt/supabase/backup.sh),
  DSGVO-Loeschkaskade verifiziert.
