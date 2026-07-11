-- Wolf Radar — Supabase-Schema v2 (Multi-Tenant-Umbau)
-- ============================================================================
-- Dieses Skript wird PHASENWEISE erweitert. Jede Phase ist idempotent und
-- kann gefahrlos mehrfach im SQL-Editor des Supabase-Projekts ausgeführt werden.
--
--   Phase 0 (dieses Skript): Auth-Fundament — profiles-Tabelle, Trigger für
--            neue Nutzer, RLS-Policies. Noch KEINE Tenant-Spalten auf den
--            bestehenden Tabellen.
--   Phase 1 (folgt): Tenant-Datenmodell — user_id auf videos/agent_runs/
--            einstellungen/rezepte, neue Tabellen radar_profile, themen,
--            suchqueries, watchlist_personen, narrativ_chunks.
--   Phase 2 (folgt): Embeddings/RAG auf Basis von pgvector (narrativ_chunks).
-- ============================================================================

-- pgvector jetzt schon aktivieren — wird ab Phase 2 für narrativ_chunks gebraucht.
create extension if not exists vector;

-- ----------------------------------------------------------------------------
-- Phase 0: Auth-Fundament
-- ----------------------------------------------------------------------------

-- Ein Profil pro Auth-Nutzer. Wird automatisch vom Trigger unten angelegt,
-- sobald sich jemand registriert (Zeile in auth.users entsteht).
create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  anzeige_name text,
  handle text unique,                 -- nullable, für spätere Kanal-Zuordnung
  rolle text not null default 'creator' check (rolle in ('creator','admin')),
  plan text not null default 'free' check (plan in ('free','pro')),
  onboarding_status text not null default 'offen'
    check (onboarding_status in ('offen','import_laeuft','review','fertig')),
  zeitzone text not null default 'Europe/Berlin',
  erstellt_am timestamptz not null default now()
);

-- Trigger-Funktion: legt bei jedem neuen Auth-Nutzer die profiles-Zeile an.
-- security definer + fester search_path, damit der Insert trotz RLS greift
-- und kein Schema-Hijacking möglich ist.
create or replace function handle_neuer_nutzer()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into profiles (id, email, anzeige_name)
  values (new.id, new.email, new.raw_user_meta_data->>'anzeige_name');
  return new;
end;
$$;

-- Trigger idempotent neu anlegen.
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_neuer_nutzer();

-- RLS: Nutzer sieht und ändert nur die EIGENE Profil-Zeile.
-- Kein insert/delete für normale Nutzer — Anlegen macht der Trigger,
-- Löschen/Verwalten der Admin über den Service-Key (umgeht RLS).
alter table profiles enable row level security;

drop policy if exists "profiles_eigene_lesen" on profiles;
create policy "profiles_eigene_lesen" on profiles
  for select
  using (auth.uid() = id);

drop policy if exists "profiles_eigene_aendern" on profiles;
create policy "profiles_eigene_aendern" on profiles
  for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- ----------------------------------------------------------------------------
-- Phase 1: Tenant-Datenmodell
--
-- Kernidee (Owner-Entscheidung): geteilter Video-POOL + per-User-ZUORDNUNG.
--   videos          → mandantenneutral, 1 Zeile pro Video (Dedupe plattform+video_id),
--                     inkl. Transkript, neutraler Claim-Extraktion und gecachtem Webcheck.
--   video_zuordnung → alles Nutzerspezifische (Status, Score, Verdict, Skripte, Feedback).
-- ACHTUNG: ersetzt das flache v1-Schema (supabase_schema.sql). Auf einem Projekt
-- mit v1-Tabellen zuerst migrieren (scraper/migriere_tenant_christian.py), dann
-- die v1-Tabellen droppen — dieses Skript legt nur an, es droppt nichts.
-- ----------------------------------------------------------------------------

-- profiles um Plan-/Lösch-Verwaltung erweitern (idempotent).
alter table profiles add column if not exists plan_bis timestamptz;
alter table profiles add column if not exists geloescht_am timestamptz;

-- === Video-Pool (mandantenneutral) ========================================
create table if not exists videos (
  id text primary key,                       -- "youtube:abc123"
  plattform text not null check (plattform in ('youtube','tiktok','instagram')),
  video_id text not null,
  url text not null,
  titel text,
  kanal text,
  kanal_id text,
  kanal_follower bigint,
  veroeffentlicht timestamptz,
  views bigint default 0,
  likes bigint default 0,
  kommentare bigint default 0,
  dauer_s int,
  thumbnail_url text,
  caption text,
  transkript text,
  sprache text default 'de',
  quelle text check (quelle in ('claim_suche','watchlist','discovery')),
  quelle_query text,
  gefunden_am timestamptz default now(),
  -- Neutrale Stufe-A/B-Extraktion (aussage, kategorie, konfidenz, schadenspotential):
  claim jsonb,
  -- Geteilter Websuche-Faktencheck, einmal gerechnet, für alle Nutzer gecacht:
  webcheck jsonb,
  aktualisiert_am timestamptz default now(),
  unique (plattform, video_id)
);
create index if not exists videos_gefunden_am on videos (gefunden_am desc);

-- === Per-User-Sicht auf den Pool ==========================================
create table if not exists video_zuordnung (
  user_id uuid not null references profiles(id) on delete cascade,
  video_id text not null references videos(id) on delete cascade,
  status text not null default 'inbox' check (status in
    ('inbox','angenommen','abgelehnt','gespeichert','strittig','archiv')),
  thema_slug text,                           -- Thema DES Nutzers (aus seiner themen-Tabelle)
  score int default 0,
  scores jsonb default '{}'::jsonb,
  verdict jsonb,                             -- Urteil ggü. den Positionen DIESES Nutzers
  begruendung text,                          -- "Warum für dich relevant"
  skripte jsonb default '[]'::jsonb,
  feedback jsonb default '[]'::jsonb,
  dublette_von text,
  zugeordnet_am timestamptz default now(),
  aktualisiert_am timestamptz,
  primary key (user_id, video_id)
);
create index if not exists vz_user_status_score
  on video_zuordnung (user_id, status, score desc);

-- === Persona / Wissensbasis pro Nutzer ====================================
create table if not exists radar_profile (
  user_id uuid primary key references profiles(id) on delete cascade,
  nische text,
  sprache text not null default 'de',
  marke text,                                -- App-Titel: "«marke» Radar"
  quelle_kanaele jsonb default '[]'::jsonb,  -- [{plattform, handle, kanal_id}]
  stilguide text,                            -- Markdown (ersetzt chris_stilguide.md)
  positionen jsonb default '[]'::jsonb,      -- [{thema, position, kurzbeleg}]
  -- Lebende Trigger-Liste ("Was dich erfahrungsgemäß triggert"):
  -- [{trigger, staerke 0-1, quelle onboarding|interview|feedback,
  --   belege [video_ids], aktualisiert_am}]
  reaktions_ausloeser jsonb default '[]'::jsonb,
  interessen_profil jsonb default '{}'::jsonb,
  playbook text,
  aktualisiert_am timestamptz not null default now()
);

create table if not exists themen (
  user_id uuid not null references profiles(id) on delete cascade,
  slug text not null,
  name text not null,
  kerngewicht real not null default 0.7 check (kerngewicht between 0 and 1),
  keywords text[] not null default '{}',
  aktiv boolean not null default true,
  quelle text not null default 'onboarding'
    check (quelle in ('onboarding','manuell','lerner')),
  primary key (user_id, slug)
);

create table if not exists suchqueries (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  thema_slug text,
  plattform text not null check (plattform in ('youtube','tiktok','instagram')),
  query text not null,
  aktiv boolean not null default true,
  quelle text not null default 'onboarding'
    check (quelle in ('onboarding','manuell','lerner')),
  erstellt_am timestamptz not null default now(),
  unique (user_id, plattform, query)
);

-- Dedupe-Sicht für den Scraper: Kosten skalieren mit distinct Queries,
-- nicht mit Nutzern. Nur fertige (aktive) Nutzer speisen den Scrape-Plan.
create or replace view scrape_queries_aktiv as
  select s.plattform,
         lower(trim(s.query)) as query_norm,
         min(s.query)         as query,
         count(distinct s.user_id) as nutzer_anzahl
  from suchqueries s
  join profiles p on p.id = s.user_id
  where s.aktiv
    and p.onboarding_status = 'fertig'
    and p.geloescht_am is null
  group by 1, 2;

-- Rotation/Cooldown pro dedupliziertem Query (Scraper schreibt nach jedem Scrape).
create table if not exists scrape_status (
  plattform text not null,
  query_norm text not null,
  zuletzt timestamptz,
  treffer_gesamt int default 0,
  fehler_folge int default 0,
  primary key (plattform, query_norm)
);

create table if not exists watchlist_personen (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  name text not null,
  plattform text,
  handle text,
  kanal_id text,
  prioritaet int default 3,
  folgt boolean not null default true,
  notizen text,
  interessen text[] default '{}',
  reaktionen jsonb default '[]'::jsonb,      -- Historie eigener Reaktionen auf diese Person
  quelle text not null default 'manuell'
    check (quelle in ('onboarding','manuell','lerner')),
  unique (user_id, plattform, handle)
);

-- Watchlist-Scrapes ebenfalls dedupliziert über alle Nutzer.
create or replace view scrape_watchlist_aktiv as
  select w.plattform,
         w.handle,
         min(w.name) as name,
         count(distinct w.user_id) as nutzer_anzahl
  from watchlist_personen w
  join profiles p on p.id = w.user_id
  where w.folgt
    and p.onboarding_status = 'fertig'
    and p.geloescht_am is null
  group by 1, 2;

-- === RAG über die EIGENEN Videos des Nutzers (Phase 2 nutzt embedding) ====
create table if not exists narrativ_chunks (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  video_id text,
  titel text,
  text text not null,
  ist_reaktion boolean default false,
  embedding vector(768),                     -- gemini-embedding-001, outputDimensionality=768
  erstellt_am timestamptz not null default now()
);
create index if not exists nc_user on narrativ_chunks (user_id);
create index if not exists nc_embedding on narrativ_chunks
  using hnsw (embedding vector_cosine_ops);

create or replace function match_narrativ(
  p_user uuid, p_embedding vector(768), p_k int default 4
) returns setof narrativ_chunks
language sql stable
set search_path = public
as $$
  select * from narrativ_chunks
  where user_id = p_user and embedding is not null
  order by embedding <=> p_embedding
  limit p_k
$$;

-- === Bestehende Konzepte mandantenfähig ===================================
-- Key-Value-Einstellungen pro Nutzer (Keys: gelernt, watchlist-Altlast,
-- extra_queries, rezept_extra_queries, rezepte_aktiv, ...).
create table if not exists einstellungen (
  user_id uuid not null references profiles(id) on delete cascade,
  key text not null,
  value jsonb,
  aktualisiert_am timestamptz not null default now(),
  primary key (user_id, key)
);

create table if not exists rezepte (
  id text primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  plattform text default 'youtube',
  video_id text,
  url text,
  titel text,
  kanal text,
  views bigint default 0,
  likes bigint default 0,
  kommentare bigint default 0,
  veroeffentlicht timestamptz,
  thumbnail_url text,
  dauer_s int,
  kategorie text,
  zutaten_kurz jsonb default '[]'::jsonb,
  score int default 0,
  fit_score int default 0,
  haken text,                                -- ehem. chris_haken: "was DU kritisieren würdest"
  begruendung text,
  status text not null default 'vorschlag'
    check (status in ('vorschlag','gemerkt','verworfen')),
  feedback jsonb default '[]'::jsonb,
  gefunden_am timestamptz default now()
);
create index if not exists rezepte_user_status on rezepte (user_id, status, score desc);

create table if not exists agent_runs (
  id bigint generated always as identity primary key,
  user_id uuid references profiles(id) on delete cascade,  -- null = globaler Akquise-Lauf
  typ text not null default 'akquise'
    check (typ in ('akquise','kuration','onboarding','lerner','rezepte')),
  zeit timestamptz not null default now(),
  quelle text,
  gefunden int default 0,
  neu int default 0,
  analysiert int default 0,
  geflaggt int default 0,
  fehler jsonb default '[]'::jsonb,          -- Liste von Fehler-Strings (Kontrakt)
  dauer_s int default 0,
  such_protokoll jsonb default '[]'::jsonb,  -- Pro-Query-Aufschlüsselung (UI-Transparenz)
  detail jsonb default '{}'::jsonb           -- z.B. Token-/Kosten-Zähler
);
create index if not exists agent_runs_zeit on agent_runs (zeit desc);
create index if not exists agent_runs_user on agent_runs (user_id, zeit desc);

-- Auftrags-Queue: ersetzt die .lauf_anfrage-Flag-Datei im Supabase-Modus.
-- Ein Minuten-Worker im Scraper-Container claimt offene Aufträge.
create table if not exists auftraege (
  id bigint generated always as identity primary key,
  user_id uuid references profiles(id) on delete cascade,
  typ text not null check (typ in ('lauf','onboarding','kuration','lerner')),
  status text not null default 'offen'
    check (status in ('offen','laeuft','fertig','fehler')),
  payload jsonb default '{}'::jsonb,
  fehler_text text,
  erstellt_am timestamptz not null default now(),
  gestartet_am timestamptz,
  beendet_am timestamptz
);
create index if not exists auftraege_offen on auftraege (status, erstellt_am)
  where status = 'offen';

-- === RLS: deny-all auf allen Datentabellen =================================
-- Zugriff ausschließlich server-seitig über den Service-Key (App + Scraper).
-- Client-seitiges supabase-js wird NUR für Auth benutzt. Policies bewusst
-- keine — RLS enabled ohne Policy == niemand außer Service-Rolle.
alter table videos             enable row level security;
alter table video_zuordnung    enable row level security;
alter table radar_profile      enable row level security;
alter table themen             enable row level security;
alter table suchqueries        enable row level security;
alter table scrape_status      enable row level security;
alter table watchlist_personen enable row level security;
alter table narrativ_chunks    enable row level security;
alter table einstellungen      enable row level security;
alter table rezepte            enable row level security;
alter table agent_runs         enable row level security;
alter table auftraege          enable row level security;

-- ----------------------------------------------------------------------------
-- Phase 2 (Embeddings/RAG-Befüllung) nutzt narrativ_chunks.embedding +
-- match_narrativ() — Schema dafür ist oben bereits vollständig angelegt.
-- ----------------------------------------------------------------------------
