// Zentrale Typen — spiegeln exakt das Datenmodell aus KONTRAKT.md

export type Plattform = "youtube" | "tiktok" | "instagram";

export type Status =
  | "inbox"
  | "angenommen"
  | "abgelehnt"
  | "gespeichert"
  | "strittig"
  | "archiv";

export type Verdict = "klar_falsch" | "strittig" | "korrekt";

export interface Claim {
  aussage: string; // wörtliches Zitat der Falschaussage
  verdict: Verdict;
  konfidenz: number; // 0..1
  begruendung: string; // Ein Satz, warum falsch
  thema: string; // Slug aus mythen_katalog.THEMEN
}

export interface Quelle {
  titel: string;
  url: string;
}

export interface Skript {
  variante: number; // 1..3
  hook_typ: string; // z.B. o_ton_konter | frage_hook | empoerungs_hook
  inhalt_md: string;
  quellen: Quelle[];
}

export interface FeedbackEintrag {
  aktion: string; // angenommen | abgelehnt | gespeichert | kommentar
  kommentar?: string;
  zeit: string; // ISO
}

export interface Video {
  id: string; // "youtube:abc123"
  plattform: Plattform;
  video_id: string;
  url: string;
  titel: string;
  kanal: string;
  kanal_id: string;
  kanal_follower: number | null;
  veroeffentlicht: string; // ISO
  views: number;
  likes: number;
  kommentare: number;
  dauer_s: number | null;
  thumbnail_url: string | null;
  caption: string;
  transkript: string | null;
  gefunden_am: string; // ISO
  quelle: "claim_suche" | "watchlist" | "discovery";
  status: Status;
  score: number; // 0-100
  scores: { reichweite: number; relevanz: number; tauglichkeit: number };
  // null = Scraper hat das Video gesammelt, aber die Analyse lief noch nicht
  claim: Claim | null;
  skripte: Skript[];
  feedback: FeedbackEintrag[];
}

export interface AgentRun {
  zeit: string;
  quelle: string;
  gefunden: number;
  neu: number;
  analysiert: number;
  geflaggt: number;
  fehler: string[];
  dauer_s: number;
}

export interface Einstellungen {
  gelernt: {
    themen_boost: Record<string, number>; // slug → -1..1
    notizen: string[];
  };
  zuletzt_gelernt: string | null;
}

export interface VideoFilter {
  status?: Status | Status[];
  plattform?: Plattform;
  thema?: string;
  zeitraumTage?: number; // veroeffentlicht innerhalb der letzten N Tage
}

export interface WatchlistEintrag {
  name: string;
  youtube: string | null;
  tiktok: string | null;
  instagram: string | null;
  notiz?: string;
}

// Anzeige-Namen der Themen-Slugs (UI-Chips, Filter)
export const THEMEN_LABELS: Record<string, string> = {
  honig: "Honig",
  datteln: "Datteln",
  fruehstueck: "Frühstück",
  suessstoffe: "Süßstoffe",
  kohlenhydrate_abends: "KH abends",
  detox: "Detox",
  protein: "Protein",
  abnehmen: "Abnehmen",
  zucker: "Zucker",
  supplements: "Supplements",
  verarbeitete_lebensmittel: "Verarbeitetes",
  saftkur: "Saftkur",
};

export function themaLabel(slug: string): string {
  return THEMEN_LABELS[slug] || slug.replace(/_/g, " ");
}

export const HOOK_LABELS: Record<string, string> = {
  o_ton_konter: "O-Ton-Konter",
  frage_hook: "Frage-Hook",
  empoerungs_hook: "Empörungs-Hook",
  cold_open: "Cold Open",
  nutzenversprechen: "Nutzenversprechen",
};

export function hookLabel(slug: string): string {
  return HOOK_LABELS[slug] || slug.replace(/_/g, " ");
}
