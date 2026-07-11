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
-- Phase 1 (Tenant-Datenmodell) wird hier ergänzt: user_id auf
-- videos/agent_runs/einstellungen/rezepte, radar_profile, themen,
-- suchqueries, watchlist_personen, narrativ_chunks
-- ----------------------------------------------------------------------------
