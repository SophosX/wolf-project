# Wolf Radar — Deployment-Runbook

> Voraussetzungen vom User: (1) `gh auth login` erledigt, (2) Vercel-Token, (3) Supabase Project-URL + service_role + anon.

## 1. GitHub (Code + Cron)

```bash
cd 05_webapp/wolf-radar
gh repo create wolf-radar --private --source . --push
# Secrets für den Scraper-Cron:
gh secret set YT_API_KEY --body "$YT_API_KEY"
gh secret set GEMINI_API_KEY --body "$GEMINI_API_KEY"
gh secret set SUPABASE_URL --body "https://<projekt>.supabase.co"
gh secret set SUPABASE_SERVICE_KEY --body "<service_role>"
# optional: gh secret set IG_SESSIONID --body "<cookie>"
gh workflow enable radar-cron.yml
gh workflow run radar-cron.yml   # erster manueller Lauf
```

## 2. Supabase (Datenbank)

1. SQL-Editor → Inhalt von `supabase_schema.sql` ausführen
2. Bestehende lokale Funde migrieren:
   ```bash
   export SUPABASE_URL=... SUPABASE_SERVICE_KEY=... DATEN_MODUS=supabase
   python3 scraper/migriere_lokal_zu_supabase.py   # schreibt daten/*.json in die Tabellen
   ```

## 3. Vercel (App)

```bash
npm i -g vercel
VERCEL_TOKEN=<token> vercel link --yes
VERCEL_TOKEN=<token> vercel env add SUPABASE_URL production        # Project-URL
VERCEL_TOKEN=<token> vercel env add SUPABASE_SERVICE_KEY production
VERCEL_TOKEN=<token> vercel env add GEMINI_API_KEY production
VERCEL_TOKEN=<token> vercel env add RADAR_ZUGANGSCODE production   # z.B. "wolfradar2026"
VERCEL_TOKEN=<token> vercel env add DATEN_MODUS production         # "supabase"
VERCEL_TOKEN=<token> vercel --prod
```

## 4. Abnahme-Checks nach Deploy

- [ ] `https://<app>.vercel.app/login` lädt, Zugangscode funktioniert
- [ ] Inbox zeigt migrierte Funde
- [ ] Annehmen → Skript-Paket sichtbar; Feedback persistiert (Supabase Table Editor prüfen)
- [ ] /api/faktencheck live (Gemini erreichbar von Vercel)
- [ ] GitHub Action manuell getriggert → neue agent_runs-Zeile + ggf. neue Videos in Supabase
- [ ] Mobile-Check auf echtem Handy
- [ ] Zugangsdaten (URL + Code) in 06_abgabe/ABGABE_CHECKLISTE.md eintragen

## Hinweise

- Scraper laufen NICHT auf Vercel (yt-dlp braucht echte Runtime) — sie laufen im GitHub-Actions-Cron und schreiben direkt in Supabase. Die App liest nur.
- YouTube-Quota: 8 Suchqueries/Lauf × 6 Läufe/Tag ≈ 9.600 Einheiten — knapp unterm 10k-Limit. Bei Quota-Fehlern RADAR_QUERIES_PRO_LAUF=6 setzen.
