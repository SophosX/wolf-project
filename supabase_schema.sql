-- Wolf Radar — Supabase-Schema (im SQL-Editor des Projekts ausführen)
create table if not exists videos (
  id text primary key,                -- "youtube:abc123"
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
  gefunden_am timestamptz default now(),
  quelle text check (quelle in ('claim_suche','watchlist','discovery')),
  status text default 'inbox' check (status in ('inbox','angenommen','abgelehnt','gespeichert','strittig','archiv')),
  score int default 0,
  scores jsonb default '{}'::jsonb,
  claim jsonb,
  skripte jsonb default '[]'::jsonb,
  feedback jsonb default '[]'::jsonb
);
create index if not exists videos_status_score on videos (status, score desc);
create index if not exists videos_plattform on videos (plattform);

create table if not exists agent_runs (
  id bigint generated always as identity primary key,
  zeit timestamptz default now(),
  quelle text,
  gefunden int default 0,
  neu int default 0,
  analysiert int default 0,
  geflaggt int default 0,
  fehler jsonb default '[]'::jsonb,
  dauer_s int
);

create table if not exists einstellungen (
  key text primary key,
  value jsonb
);
-- Genutzte Keys: 'gelernt' (Feedback-Lernen), 'watchlist' (gefolgte Personen aus dem
-- Personen-Dashboard — Quelle der Wahrheit im Supabase-Modus, Datei ist nur Seed)

create table if not exists rezepte (
  id text primary key,
  url text not null,
  titel text,
  kanal text,
  views bigint default 0,
  likes bigint default 0,
  kommentare bigint default 0,
  veroeffentlicht timestamptz,
  thumbnail_url text,
  dauer_s int,
  fit_score int default 0,
  kategorie text,
  begruendung text,
  zutaten_kurz jsonb default '[]'::jsonb,
  chris_haken text,
  score int default 0,
  status text default 'vorschlag' check (status in ('vorschlag','gemerkt','verworfen')),
  feedback jsonb default '[]'::jsonb,
  gefunden_am timestamptz default now()
);
create index if not exists rezepte_status_score on rezepte (status, score desc);
alter table rezepte enable row level security;

-- RLS: Service-Key (Server) hat vollen Zugriff; anon bekommt nichts (App läuft serverseitig).
alter table videos enable row level security;
alter table agent_runs enable row level security;
alter table einstellungen enable row level security;
