# -*- coding: utf-8 -*-
"""
onboarding_agent.py — Kanal-Import fuer neue Nutzer (Multi-Tenant Phase 4).

Baut aus den EIGENEN Videos eines neuen Creators automatisch sein Radar-Profil —
dasselbe, was fuer Christian einst manuell aus ~1500 Videos destilliert wurde:

  1. Kanal-Videos einsammeln (YouTube Data API: Uploads + Top-Views;
     TikTok via Apify-Profil-Scrape). Plan-Cap: Free 25 / Pro 200 Videos.
  2. Transkripte holen (bestehende Infrastruktur).
  3. Gemini Map-Reduce ueber die Transkripte ->
       positionen        (belegte Kern-Positionen mit Kurzbeleg)
       stilguide         (Ton, Satzbau, Catchphrases, No-Gos — Markdown)
       reaktions_ausloeser (wogegen argumentiert die Person = Trigger-Seed)
       themen            (+ Keywords + Kerngewicht)
       suchqueries       (claim-formulierte Suchanfragen, 2-3 je Thema)
       watchlist_personen (erwaehnte Gegner, folgt=false bis Review)
  4. Embeddings der besten Passagen -> narrativ_chunks (768, per-User-RAG).
  5. profiles.onboarding_status: import_laeuft -> review.

Aufruf (via worker.py aus der auftraege-Queue): python3 onboarding_agent.py --user <uuid>
"""

import argparse
import json
import os
import re
import sys
import time

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import analyse
import plan_limits
import speicher

MAP_BATCH = 6              # Transkripte pro Map-Aufruf
MAX_TRANSKRIPT_ZEICHEN = 5000
MAX_CHUNKS_PRO_VIDEO = 3


def _fortschritt(user_id, text):
    """Live-Fortschritt fuer den Wizard: payload des laufenden Onboarding-
    Auftrags aktualisieren (die App pollt /api/onboarding)."""
    try:
        speicher._supabase_patch("auftraege", {
            "user_id": "eq." + str(user_id), "typ": "eq.onboarding",
            "status": "eq.laeuft",
        }, {"payload": {"schritt": text, "zeit": speicher.jetzt_iso()}})
    except Exception:
        pass
    print("[onboarding] %s" % text)


# ---------------------------------------------------------------------------
# Schritt 1: Kanal-Videos einsammeln
# ---------------------------------------------------------------------------

def youtube_kanal_videos(handle, max_videos, fehler):
    """Uploads (neueste) + Top-Views eines Kanals via Data API.
    ~2/3 Top-Views, ~1/3 Neueste (der Stil von heute + die Hits von immer)."""
    import youtube_agent
    antwort = youtube_agent._api_get("channels", {
        "part": "id,contentDetails,statistics",
        "forHandle": handle.lstrip("@"),
    }, fehler)
    items = (antwort or {}).get("items") or []
    if not items:
        fehler.append("onboarding: YouTube-Kanal @%s nicht gefunden" % handle)
        return []
    kanal = items[0]
    kanal_id = kanal["id"]
    uploads_playlist = kanal["contentDetails"]["relatedPlaylists"]["uploads"]
    follower = int((kanal.get("statistics") or {}).get("subscriberCount") or 0)

    video_ids = []
    # Neueste ueber die Uploads-Playlist (1 Einheit / 50)
    seite = None
    while len(video_ids) < max_videos:
        params = {"part": "contentDetails", "playlistId": uploads_playlist, "maxResults": 50}
        if seite:
            params["pageToken"] = seite
        antwort = youtube_agent._api_get("playlistItems", params, fehler)
        if not antwort:
            break
        for it in antwort.get("items") or []:
            vid = it.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        seite = antwort.get("nextPageToken")
        if not seite:
            break
    neueste = video_ids[: max(1, max_videos // 3)]

    # Top-Views via search.list (100 Einheiten — einmalig pro Onboarding ok)
    top = []
    antwort = youtube_agent._api_get("search", {
        "part": "id", "channelId": kanal_id, "type": "video",
        "order": "viewCount", "maxResults": 50,
    }, fehler)
    for it in (antwort or {}).get("items") or []:
        vid = (it.get("id") or {}).get("videoId")
        if vid:
            top.append(vid)
    top = top[: max(1, max_videos - len(neueste))]

    alle_ids = list(dict.fromkeys(top + neueste))[:max_videos]
    if not alle_ids:
        return []

    kandidaten = []
    for i in range(0, len(alle_ids), 50):
        batch = alle_ids[i:i + 50]
        antwort = youtube_agent._api_get("videos", {
            "part": "snippet,statistics,contentDetails", "id": ",".join(batch),
        }, fehler)
        for it in (antwort or {}).get("items") or []:
            sn = it.get("snippet") or {}
            st = it.get("statistics") or {}
            kandidaten.append({
                "id": "youtube:" + it["id"],
                "plattform": "youtube",
                "video_id": it["id"],
                "url": "https://www.youtube.com/watch?v=" + it["id"],
                "titel": sn.get("title") or "",
                "kanal": sn.get("channelTitle") or handle,
                "kanal_id": kanal_id,
                "kanal_follower": follower,
                "veroeffentlicht": sn.get("publishedAt"),
                "views": int(st.get("viewCount") or 0),
                "likes": int(st.get("likeCount") or 0),
                "caption": (sn.get("description") or "")[:1500],
                "transkript": None,
            })
    return kandidaten


def tiktok_kanal_videos(handle, max_videos, fehler):
    try:
        import apify_agent
        if not apify_agent.verfuegbar():
            return []
        kandidaten = []
        apify_agent._sammle_profile([handle], {handle.lower(): handle},
                                    max_videos, "watchlist", kandidaten, fehler)
        return kandidaten[:max_videos]
    except Exception as e:
        fehler.append("onboarding tiktok @%s: %s" % (handle, e))
        return []


# ---------------------------------------------------------------------------
# Schritt 3: Gemini Map-Reduce
# ---------------------------------------------------------------------------

_SCHEMA_MAP = {
    "type": "OBJECT",
    "properties": {
        "positionen": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "thema": {"type": "STRING"}, "position": {"type": "STRING"},
            "kurzbeleg": {"type": "STRING"}}, "required": ["thema", "position"]}},
        "stil_merkmale": {"type": "ARRAY", "items": {"type": "STRING"}},
        "catchphrases": {"type": "ARRAY", "items": {"type": "STRING"}},
        "trigger": {"type": "ARRAY", "items": {"type": "STRING"},
                    "description": "Wogegen argumentiert die Person erkennbar emotional?"},
        "gegner": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name": {"type": "STRING"}, "plattform": {"type": "STRING"},
            "handle": {"type": "STRING"}}, "required": ["name"]}},
        "themen": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name": {"type": "STRING"},
            "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
            "zentralitaet": {"type": "NUMBER"}}, "required": ["name", "keywords"]}},
    },
    "required": ["positionen", "stil_merkmale", "trigger", "themen"],
}

_SYSTEM_MAP = """Du analysierst Transkripte aus den EIGENEN Videos eines Creators, um sein
Debunk-Radar-Profil zu bauen. Extrahiere NUR, was die Transkripte wirklich hergeben:
- positionen: fachliche Kern-Positionen, die die Person VERTRITT (mit Kurzbeleg = Video-Zitat/Paraphrase)
- stil_merkmale: WIE die Person spricht (Ton, Satzbau, Anrede, Humor, Eskalation)
- catchphrases: woertliche Signature-Phrasen (nur wenn wiederholt/typisch)
- trigger: wogegen die Person erkennbar und wiederholt argumentiert (Falschbehauptungen,
  Akteure, Narrative — als kurze deutsche Saetze, z.B. 'Angstmache vor X ohne Studienlage')
- gegner: konkrete Personen/Kanaele, gegen die die Person argumentiert (nur explizit genannte)
- themen: die inhaltlichen Kernthemen mit 4-8 deutschen Suchbegriff-Keywords und
  zentralitaet 0-1 (wie zentral fuers Profil)."""

_SCHEMA_REDUCE = {
    "type": "OBJECT",
    "properties": {
        "nische": {"type": "STRING"},
        "stilguide_md": {"type": "STRING",
                         "description": "Markdown-Stilguide (Ton, Anrede, Satzbau, Signature-Phrasen, No-Gos)"},
        "kern_botschaft": {"type": "STRING"},
        "positionen": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "thema": {"type": "STRING"}, "position": {"type": "STRING"},
            "kurzbeleg": {"type": "STRING"}}, "required": ["thema", "position"]}},
        "trigger": {"type": "ARRAY", "items": {"type": "STRING"}},
        "themen": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "slug": {"type": "STRING"}, "name": {"type": "STRING"},
            "kerngewicht": {"type": "NUMBER"},
            "keywords": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "required": ["slug", "name", "kerngewicht", "keywords"]}},
        "suchqueries": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "plattform": {"type": "STRING", "enum": ["youtube", "tiktok", "instagram"]},
            "query": {"type": "STRING"}, "thema_slug": {"type": "STRING"}},
            "required": ["plattform", "query"]}},
    },
    "required": ["nische", "stilguide_md", "positionen", "trigger", "themen", "suchqueries"],
}

_SYSTEM_REDUCE = """Du fasst Teil-Analysen aus den Videos EINES Creators zu seinem
Debunk-Radar-Profil zusammen. Das Radar sucht spaeter FREMDE Videos mit Falschinformationen
aus seiner Nische, die er richtigstellen wuerde.

Liefere:
- nische: EIN praegnanter deutscher Ausdruck (z.B. 'Ernaehrung, Abnehmen und Fitness')
- stilguide_md: kompakter Markdown-Stilguide (## Ton, ## Anrede & Satzbau,
  ## Signature-Phrasen, ## No-Gos) — konkret genug, dass ein Ghostwriter danach schreiben kann
- kern_botschaft: die EINE Kernformel/Botschaft der Person (kurz)
- positionen: dedupliziert, die 8-20 wichtigsten belegten Positionen
- trigger: 5-12 kurze Saetze, was die Person erfahrungsgemaess triggert (dedupliziert,
  konkret, keine Dopplungen mit den Positionen)
- themen: 5-15 Themen, slug = kebab_case/snake_case, kerngewicht 0-1 (1 = absolutes
  Kernthema), keywords = 4-10 deutsche Substring-Suchbegriffe (klein, praegnant)
- suchqueries: 2-3 CLAIM-formulierte deutsche Suchanfragen je Kernthema — so, wie die
  FALSCHBEHAUPTUNG klingt (z.B. 'Honig gesuender als Zucker'), fuer youtube laenger,
  fuer tiktok kuerzer; instagram = einzelne Hashtag-Woerter ohne #."""


def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()
               .replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))
    return s.strip("_")[:40] or "thema"


def map_reduce(kandidaten, fehler, fokus_text="", user_id=None):
    """Gemini-Map ueber Transkript-Batches, dann Reduce zum Profil.
    fokus_text: Freitext-Wunsch des Nutzers aus dem Wizard ("Worauf willst du
    reagieren?") — fliesst als Leitplanke in den Reduce-Prompt ein."""
    mit_material = [k for k in kandidaten if (k.get("transkript") or k.get("caption"))]
    teil_analysen = []
    for i in range(0, len(mit_material), MAP_BATCH):
        batch = mit_material[i:i + MAP_BATCH]
        bloecke = []
        for k in batch:
            bloecke.append("=== VIDEO: %s (%s Views) ===\nTITEL: %s\nTEXT: %s" % (
                k.get("titel"), k.get("views"),
                k.get("titel"),
                (k.get("transkript") or k.get("caption") or "")[:MAX_TRANSKRIPT_ZEICHEN]))
        try:
            daten = analyse.gemini_json("\n\n".join(bloecke), system=_SYSTEM_MAP,
                                        schema=_SCHEMA_MAP, temperatur=0.2)
            teil_analysen.append(daten)
            if user_id:
                _fortschritt(user_id, "Deine Inhalte werden analysiert (%d/%d) …"
                             % (i // MAP_BATCH + 1,
                                (len(mit_material) + MAP_BATCH - 1) // MAP_BATCH))
        except Exception as e:
            fehler.append("map batch %d: %s" % (i // MAP_BATCH + 1, e))
        time.sleep(analyse.PAUSE_ZWISCHEN_CALLS_S)
    if not teil_analysen:
        return None

    if user_id:
        _fortschritt(user_id, "Fast fertig — dein Profil wird destilliert "
                     "(Positionen, Ton, Trigger, Suchplan) …")
    prompt_teile = ["TEIL-ANALYSEN:\n"
                    + json.dumps(teil_analysen, ensure_ascii=False)[:60000]]
    if fokus_text:
        prompt_teile.append("FOKUS-WUNSCH DES CREATORS (Leitplanke fuer Themen/"
                            "Queries/Trigger — hoeher gewichten, was dazu passt):\n"
                            + fokus_text[:600])
    try:
        profil = analyse.gemini_json(
            "\n\n".join(prompt_teile),
            system=_SYSTEM_REDUCE, schema=_SCHEMA_REDUCE, temperatur=0.2,
            modell=analyse.GEMINI_MODELL_QUALITAET)
    except Exception as e:
        fehler.append("reduce: %s" % e)
        return None
    # Gegner aus den Map-Laeufen aggregieren (Reduce-Schema haelt sie nicht)
    gegner = {}
    for t in teil_analysen:
        for g in t.get("gegner") or []:
            name = (g.get("name") or "").strip()
            if name and name.lower() not in gegner:
                gegner[name.lower()] = g
    profil["gegner"] = list(gegner.values())[:15]
    return profil


# ---------------------------------------------------------------------------
# Schritt 4: narrativ_chunks
# ---------------------------------------------------------------------------

def baue_narrativ_chunks(user_id, kandidaten, fehler, max_chunks=150):
    import narrativ
    zeilen = []
    for k in kandidaten:
        text = (k.get("transkript") or "").strip()
        if not text:
            continue
        # grobe Absatz-Chunks ~450 Zeichen
        stuecke = [text[i:i + 450] for i in range(0, len(text), 450)][:MAX_CHUNKS_PRO_VIDEO]
        for stueck in stuecke:
            if len(zeilen) >= max_chunks:
                break
            try:
                vektor = narrativ.embed_text(stueck, dim=768, task="RETRIEVAL_DOCUMENT")
            except Exception as e:
                fehler.append("embed: %s" % e)
                continue
            zeilen.append({"user_id": str(user_id), "video_id": k.get("id"),
                           "titel": k.get("titel"), "text": stueck,
                           "ist_reaktion": False, "embedding": vektor})
            time.sleep(0.1)
    if zeilen:
        speicher._supabase_post("narrativ_chunks", zeilen,
                                prefer="return=minimal")
    return len(zeilen)


# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Wolf Radar — Onboarding-Kanal-Import")
    parser.add_argument("--user", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if speicher.daten_modus() != "supabase":
        print("[onboarding] Nur im Supabase-Modus.")
        return 1
    uid = args.user
    start = time.time()
    fehler = []

    profile_zeilen = speicher._supabase_get("profiles", {"select": "plan", "id": "eq." + uid}) or []
    plan = (profile_zeilen[0].get("plan") if profile_zeilen else None) or "free"
    limit = args.limit or plan_limits.limits(plan)["import_videos"]
    profil = speicher.lade_profil(uid)
    kanaele = profil.get("quelle_kanaele") or []
    if not kanaele:
        print("[onboarding] Keine quelle_kanaele im Profil — Abbruch.")
        speicher._supabase_patch("profiles", {"id": "eq." + uid},
                                 {"onboarding_status": "offen"})
        return 1

    speicher._supabase_patch("profiles", {"id": "eq." + uid},
                             {"onboarding_status": "import_laeuft"})
    print("[onboarding] %s (%s): Import von %d Kanal/Kanaelen, Limit %d Videos"
          % (uid, plan, len(kanaele), limit))
    _fortschritt(uid, "Deine Kanaele werden gelesen — wir sammeln deine Videos ein …")

    # --- 1) Videos einsammeln ------------------------------------------------
    kandidaten = []
    for kanal in kanaele:
        plattform = (kanal.get("plattform") or "youtube").lower()
        handle = kanal.get("handle") or ""
        rest = max(0, limit - len(kandidaten))
        if rest == 0:
            break
        if plattform == "youtube":
            kandidaten += youtube_kanal_videos(handle, rest, fehler)
        elif plattform == "tiktok":
            kandidaten += tiktok_kanal_videos(handle, rest, fehler)
        else:
            fehler.append("onboarding: Plattform %s (noch) nicht unterstuetzt" % plattform)
    _fortschritt(uid, "%d Videos gefunden — jetzt holen wir die Transkripte …"
                 % len(kandidaten))

    # --- 2) Transkripte -------------------------------------------------------
    yt = [k for k in kandidaten if k.get("plattform") == "youtube"]
    if yt:
        try:
            import youtube_agent
            youtube_agent.hole_transkripte(yt, fehler, min_views=0, max_videos=len(yt))
        except Exception as e:
            fehler.append("transkripte: %s" % e)
    try:
        import transkription
        transkription.transkribiere_kandidaten(
            [k for k in kandidaten if not k.get("transkript")], fehler,
            max_videos=20, min_views_kurz=0, min_views_yt=0)
    except Exception as e:
        fehler.append("transkription: %s" % e)
    mit_transkript = sum(1 for k in kandidaten if k.get("transkript"))
    _fortschritt(uid, "%d von %d Transkripten liegen vor — die KI liest jetzt, "
                 "wie du sprichst und wofuer du stehst …" % (mit_transkript, len(kandidaten)))

    # --- 3) Map-Reduce ---------------------------------------------------------
    fokus_text = ((profil.get("interessen_profil") or {}).get("fokus_text") or "").strip()
    ergebnis = map_reduce(kandidaten, fehler, fokus_text=fokus_text, user_id=uid)
    if not ergebnis:
        print("[onboarding] Map-Reduce lieferte nichts — Status zurueck auf offen.")
        speicher._supabase_patch("profiles", {"id": "eq." + uid},
                                 {"onboarding_status": "offen"})
        speicher.speichere_agent_run({"user_id": uid, "typ": "onboarding",
                                      "quelle": "onboarding", "gefunden": len(kandidaten),
                                      "fehler": fehler,
                                      "dauer_s": int(time.time() - start)})
        return 1

    jetzt = speicher.jetzt_iso()
    speicher.speichere_profil(uid, {
        "nische": ergebnis.get("nische"),
        "stilguide": ergebnis.get("stilguide_md"),
        "positionen": ergebnis.get("positionen") or [],
        "reaktions_ausloeser": [
            {"trigger": t, "staerke": 0.7, "quelle": "onboarding",
             "belege": [], "aktualisiert_am": jetzt}
            for t in (ergebnis.get("trigger") or [])],
        "quelle_kanaele": kanaele,
    })

    themen_zeilen = []
    for t in (ergebnis.get("themen") or [])[:plan_limits.limits(plan)["themen"]]:
        themen_zeilen.append({
            "user_id": uid, "slug": _slugify(t.get("slug") or t.get("name")),
            "name": t.get("name") or "?",
            "kerngewicht": max(0.0, min(1.0, float(t.get("kerngewicht") or 0.7))),
            "keywords": [k.lower() for k in (t.get("keywords") or []) if k][:10],
            "aktiv": True, "quelle": "onboarding",
        })
    speicher._supabase_post("themen", themen_zeilen,
                            prefer="return=minimal,resolution=merge-duplicates")

    query_zeilen = []
    for q in (ergebnis.get("suchqueries") or [])[:plan_limits.limits(plan)["suchqueries"]]:
        if not q.get("query"):
            continue
        query_zeilen.append({
            "user_id": uid, "plattform": q.get("plattform") or "youtube",
            "query": q["query"].strip(),
            "thema_slug": _slugify(q.get("thema_slug") or "") or None,
            "aktiv": True, "quelle": "onboarding",
        })
    if query_zeilen:
        speicher._supabase_post("suchqueries", query_zeilen,
                                prefer="return=minimal,resolution=ignore-duplicates")

    personen_zeilen = []
    for g in ergebnis.get("gegner") or []:
        personen_zeilen.append({
            "user_id": uid, "name": g.get("name") or "?",
            "plattform": (g.get("plattform") or None),
            "handle": (g.get("handle") or None),
            "folgt": False, "quelle": "onboarding",
        })
    if personen_zeilen:
        speicher._supabase_post("watchlist_personen", personen_zeilen,
                                prefer="return=minimal,resolution=ignore-duplicates")

    # --- 4) narrativ_chunks ----------------------------------------------------
    _fortschritt(uid, "Dein Sprach-Gedaechtnis wird aufgebaut (damit Skripte "
                 "spaeter nach DIR klingen) …")
    n_chunks = baue_narrativ_chunks(uid, kandidaten, fehler)

    # --- 5) Review-Status -------------------------------------------------------
    speicher._supabase_patch("profiles", {"id": "eq." + uid},
                             {"onboarding_status": "review"})
    speicher.speichere_agent_run({
        "user_id": uid, "typ": "onboarding", "quelle": "onboarding",
        "gefunden": len(kandidaten), "analysiert": mit_transkript,
        "neu": len(themen_zeilen), "geflaggt": len(query_zeilen),
        "fehler": fehler, "dauer_s": int(time.time() - start),
        "detail": {"chunks": n_chunks, "personen": len(personen_zeilen)},
    })
    print("[onboarding] FERTIG (review): %d Themen, %d Queries, %d Personen, %d Chunks, %d Fehler"
          % (len(themen_zeilen), len(query_zeilen), len(personen_zeilen), n_chunks, len(fehler)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
