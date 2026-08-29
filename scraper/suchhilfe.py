# -*- coding: utf-8 -*-
"""
suchhilfe.py — Tote Suchbegriffe automatisch durch breitere Varianten ersetzen.

Ein Begriff gilt als "tot", wenn er TOT_AB Laeufe in Folge nichts fand — und
zwar NACHDEM die adaptive Suchbreite (themenwelt.fenster_fuer) ihn schon auf
das weiteste Fenster gestellt hat. Dann schlaegt kein Nachjustieren mehr an;
der Begriff selbst passt nicht zur Plattform (zu lang, zu speziell, falsche
Wortwahl). Statt den Nutzer stumm ohne Funde zu lassen:

  1. Gemini formuliert EINE breitere, plattformtypische Variante
     (YouTube: kurze Claim-Formulierung; TikTok: 2-4 Suchwoerter;
     Instagram: EIN Hashtag-Wort).
  2. Fuer jeden Besitzer: alter Begriff aktiv=false, Variante als neue
     Suchanfrage (quelle='lerner', aktiv=true, gleiches thema_slug).
  3. Hinweis in einstellungen.such_hinweise -> Inbox-Diagnose zeigt
     "„alt“ → „neu“" (Transparenz).

Wird am Ende jedes Akquise-Laufs aufgerufen (lauf.py, Supabase-Modus).
"""

import datetime
import os
import sys

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import speicher

TOT_AB = int(os.environ.get("RADAR_QUERY_TOT_AB", "3") or "3")
MAX_PRO_LAUF = int(os.environ.get("RADAR_QUERY_ERSATZ_MAX", "6") or "6")

_SCHEMA = {
    "type": "OBJECT",
    "properties": {"variante": {"type": "STRING"}},
    "required": ["variante"],
}

_SYSTEM = """Du hilfst einem Debunk-Radar, Suchbegriffe zu retten, die auf einer
Social-Media-Plattform mehrfach NICHTS gefunden haben. Formuliere GENAU EINE
breitere, plattformtypische Variante — dieselbe Falschbehauptung/dasselbe
Thema, aber so, wie Leute dort wirklich suchen und Creator wirklich titeln:
- youtube: kurze, klickstarke Formulierung (3-7 Woerter), keine Fantasie-Platzhalter
- tiktok: 2-4 kleingeschriebene Suchwoerter ohne Satzbau
- instagram: EIN einzelnes Hashtag-Wort ohne '#', ohne Leerzeichen
Deutsch. Keine Erklaerung, nur das Feld 'variante'."""


def _variante(plattform, query, thema_name=None):
    import analyse
    prompt = ("Plattform: %s\nBisheriger Begriff (fand nichts): %s\n%s"
              % (plattform, query, ("Thema: %s\n" % thema_name) if thema_name else ""))
    daten = analyse.gemini_json(prompt, system=_SYSTEM, schema=_SCHEMA, temperatur=0.5)
    v = (daten.get("variante") or "").strip().strip('"„“')
    if plattform == "instagram":
        v = v.lstrip("#").split()[0] if v else ""
    return v[:120]


def ersetze_tote_queries(max_pro_lauf=None):
    """Rueckgabe: Anzahl ersetzter Suchanfragen (ueber alle Nutzer)."""
    if speicher.daten_modus() != "supabase":
        return 0
    max_pro_lauf = max_pro_lauf or MAX_PRO_LAUF
    tote = speicher._supabase_get("scrape_status", {
        "select": "plattform,query_norm,leer_folge",
        "leer_folge": "gte.%d" % TOT_AB,
        "order": "leer_folge.desc",
    }) or []
    if not tote:
        return 0
    aktive = speicher._supabase_get("suchqueries", {
        "select": "id,user_id,plattform,query,thema_slug", "aktiv": "is.true",
    }) or []
    nach_key = {}
    for q in aktive:
        key = (q.get("plattform"), (q.get("query") or "").strip().lstrip("#").lower())
        nach_key.setdefault(key, []).append(q)

    ersetzt = 0
    for t in tote:
        if ersetzt >= max_pro_lauf:
            break
        key = (t.get("plattform"), t.get("query_norm"))
        besitzer = nach_key.get(key) or []
        if not besitzer:
            continue
        try:
            neu = _variante(key[0], besitzer[0]["query"], besitzer[0].get("thema_slug"))
        except Exception as e:
            print("[suchhilfe] Variante fehlgeschlagen fuer %s: %s" % (key, e))
            continue
        if not neu or neu.lower() == key[1]:
            continue
        jetzt = speicher.jetzt_iso()
        for q in besitzer:
            uid = q["user_id"]
            # Dublette beim Nutzer? Dann nur den alten Begriff schlafen legen.
            ok = speicher._supabase_post("suchqueries", [{
                "user_id": uid, "plattform": key[0], "query": neu,
                "thema_slug": q.get("thema_slug"), "aktiv": True, "quelle": "lerner",
            }], prefer="return=minimal,resolution=ignore-duplicates")
            speicher._supabase_patch("suchqueries", {"id": "eq.%s" % q["id"]}, {"aktiv": False})
            if ok:
                _hinweis(uid, {"alt": q["query"], "neu": neu, "plattform": key[0], "zeit": jetzt})
            print("[suchhilfe] %s: „%s“ (%dx leer) -> „%s“ [%s]"
                  % (uid, q["query"], int(t.get("leer_folge") or 0), neu, key[0]))
        # Zaehler zuruecksetzen, damit derselbe tote Begriff nicht jeden Lauf neu ersetzt wird
        speicher._supabase_post("scrape_status", [{
            "plattform": key[0], "query_norm": key[1], "leer_folge": 0,
        }], prefer="return=minimal,resolution=merge-duplicates")
        ersetzt += 1
    return ersetzt


def _hinweis(user_id, eintrag, maximal=20):
    zeilen = speicher._supabase_get("einstellungen", {
        "select": "value", "user_id": "eq." + str(user_id), "key": "eq.such_hinweise"}) or []
    liste = (zeilen[0].get("value") if zeilen else None) or []
    if not isinstance(liste, list):
        liste = []
    liste = (liste + [eintrag])[-maximal:]
    speicher._supabase_post("einstellungen", [{
        "user_id": str(user_id), "key": "such_hinweise", "value": liste,
        "aktualisiert_am": speicher.jetzt_iso(),
    }], prefer="return=minimal,resolution=merge-duplicates")


if __name__ == "__main__":
    print("[suchhilfe] ersetzt: %d" % ersetze_tote_queries())
