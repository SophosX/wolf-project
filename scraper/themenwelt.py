# -*- coding: utf-8 -*-
"""
themenwelt.py — DB-getriebene Themenwelt (Multi-Tenant-Ersatz fuer das
mythen_katalog-Hardcoding).

Zwei Welten, EIN Interface:
  Lokal-Modus   : Christian-Betrieb wie bisher — Queries/Themen aus
                  mythen_katalog.py, Watchlist aus watchlist.json.
  Supabase-Modus: Scrape-Plan aus den Dedupe-Views scrape_queries_aktiv /
                  scrape_watchlist_aktiv (Queries ALLER aktiven Nutzer,
                  dedupliziert — Kosten skalieren mit Queries, nicht Nutzern),
                  mit Cooldown ueber scrape_status. Nutzerprofile fuer die
                  Kuration aus radar_profile/themen/watchlist_personen.
"""

import logging
import os
import sys

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import speicher

logger = logging.getLogger("wolf_radar.themenwelt")

# Ein deduplizierter Query wird fruehestens nach N Stunden erneut gescrapt.
QUERY_COOLDOWN_STUNDEN = int(os.environ.get("RADAR_QUERY_COOLDOWN_H", "8") or "8")


# ---------------------------------------------------------------------------
# Scrape-Plan (Akquise): welche Queries/Hashtags/Profile werden gescrapt?
# ---------------------------------------------------------------------------

def _lokaler_scrape_plan():
    """Christian-Betrieb: Queries aus mythen_katalog, Watchlist aus Datei."""
    import json
    import mythen_katalog
    watchlist = []
    try:
        with open(os.path.join(SCRAPER_DIR, "watchlist.json"), encoding="utf-8") as f:
            watchlist = json.load(f).get("eintraege", [])
    except (OSError, ValueError) as e:
        logger.warning("watchlist.json nicht lesbar: %s", e)
    return {
        "youtube": list(getattr(mythen_katalog, "SUCHQUERIES", [])),
        "tiktok": list(getattr(mythen_katalog, "SOCIAL_SUCHQUERIES", [])),
        "instagram_hashtags": list(getattr(mythen_katalog, "SOCIAL_HASHTAGS", [])),
        "watchlist": watchlist,
    }


def _cooldown_filter(plattform, queries):
    """Queries entfernen, die innerhalb des Cooldowns schon gescrapt wurden."""
    if not queries:
        return []
    import datetime
    zeilen = speicher._supabase_get("scrape_status", {
        "select": "query_norm,zuletzt", "plattform": "eq." + plattform,
    }) or []
    grenze = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=QUERY_COOLDOWN_STUNDEN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kuerzlich = {z["query_norm"] for z in zeilen
                 if z.get("zuletzt") and z["zuletzt"] > grenze}
    frisch = [q for q in queries if q.strip().lower() not in kuerzlich]
    if len(frisch) < len(queries):
        logger.info("Cooldown %s: %d/%d Queries uebersprungen (<%dh).",
                    plattform, len(queries) - len(frisch), len(queries),
                    QUERY_COOLDOWN_STUNDEN)
    return frisch


def lade_scrape_plan():
    """Der Akquise-Plan dieses Laufs: {youtube: [...], tiktok: [...],
    instagram_hashtags: [...], watchlist: [eintraege]}."""
    if speicher.daten_modus() != "supabase":
        return _lokaler_scrape_plan()

    import datetime
    import plan_limits

    plan = {"youtube": [], "tiktok": [], "instagram_hashtags": [], "watchlist": []}

    # Per-User-Query-Cap mit Tages-Rotation: jeder Nutzer traegt maximal
    # limits['queries_pro_lauf'] Queries zum Lauf bei (Admin-Override moeglich).
    # Rotation ueber den Tag im Jahr, damit ueber die Zeit ALLE Queries drankommen.
    profile = speicher._supabase_get("profiles", {
        "select": "id,plan,limits",
        "onboarding_status": "eq.fertig",
        "geloescht_am": "is.null",
    }) or []
    limits_je_user = {p_["id"]: plan_limits.limits(p_.get("plan"), p_.get("limits"))
                      for p_ in profile}
    zeilen = speicher._supabase_get("suchqueries", {
        "select": "user_id,plattform,query",
        "aktiv": "is.true", "order": "id.asc",
    }) or []
    je_user = {}
    for z in zeilen:
        uid = z.get("user_id")
        if uid not in limits_je_user:
            continue  # Nutzer nicht fertig/geloescht
        je_user.setdefault(uid, []).append(z)
    tag = datetime.datetime.now(datetime.timezone.utc).timetuple().tm_yday
    gesehen = set()
    for uid, qs in je_user.items():
        cap = int(limits_je_user[uid].get("queries_pro_lauf") or 12)
        if len(qs) > cap:
            start = (tag * cap) % len(qs)
            qs = (qs + qs)[start:start + cap]
            logger.info("Query-Rotation %s: %d von %d Queries in diesem Lauf.",
                        uid, cap, len(je_user[uid]))
        for z in qs:
            p = z.get("plattform")
            norm = (p, z.get("query", "").strip().lower())
            if not norm[1] or norm in gesehen:
                continue
            gesehen.add(norm)
            if p == "instagram":
                plan["instagram_hashtags"].append(z.get("query", "").lstrip("#"))
            elif p in plan:
                plan[p].append(z.get("query", ""))

    for p in ("youtube", "tiktok"):
        plan[p] = _cooldown_filter(p, [q for q in plan[p] if q])
    plan["instagram_hashtags"] = _cooldown_filter(
        "instagram", [h for h in plan["instagram_hashtags"] if h])

    # Watchlist-Profile (dedupliziert ueber alle Nutzer) im Format der
    # bisherigen watchlist.json-Eintraege {name, youtube, tiktok, instagram}.
    wl_zeilen = speicher._supabase_get("scrape_watchlist_aktiv", {"select": "*"}) or []
    nach_name = {}
    for z in wl_zeilen:
        name = z.get("name") or z.get("handle") or "?"
        eintrag = nach_name.setdefault(name, {"name": name, "youtube": None,
                                              "tiktok": None, "instagram": None})
        if z.get("plattform") in ("youtube", "tiktok", "instagram") and z.get("handle"):
            eintrag[z["plattform"]] = z["handle"]
    plan["watchlist"] = list(nach_name.values())

    logger.info("Scrape-Plan (Supabase): yt=%d tiktok=%d ig-hashtags=%d watchlist=%d",
                len(plan["youtube"]), len(plan["tiktok"]),
                len(plan["instagram_hashtags"]), len(plan["watchlist"]))

    # Leerer Plan (noch keine aktiven Nutzer/Queries in der DB) -> Lokal-Plan
    # als Seed, damit der Akquise-Lauf nach dem Cutover nicht leerlaeuft.
    if not any((plan["youtube"], plan["tiktok"], plan["instagram_hashtags"])):
        logger.warning("Scrape-Plan aus DB leer — nutze mythen_katalog als Seed.")
        lokal = _lokaler_scrape_plan()
        lokal["watchlist"] = plan["watchlist"] or lokal["watchlist"]
        return lokal
    return plan


def markiere_gescrapte(plattform, queries):
    """Nach dem Scrapen: scrape_status upserten (Cooldown-Grundlage)."""
    if speicher.daten_modus() != "supabase" or not queries:
        return
    zeilen = [{"plattform": plattform, "query_norm": q.strip().lower(),
               "zuletzt": speicher.jetzt_iso()} for q in queries if q.strip()]
    speicher._supabase_post("scrape_status", zeilen,
                            prefer="return=minimal,resolution=merge-duplicates")


# ---------------------------------------------------------------------------
# Nutzerprofile (Kuration): Themen, Positionen, Wissensbasis pro Nutzer
# ---------------------------------------------------------------------------

def themen_dict(zeilen):
    """themen-Tabellenzeilen -> {slug: {name, kerngewicht, keywords}} (analyse-Format)."""
    themen = {}
    for z in zeilen or []:
        slug = z.get("slug")
        if not slug:
            continue
        themen[slug] = {
            "name": z.get("name") or slug,
            "kerngewicht": float(z.get("kerngewicht") or 0.7),
            "keywords": [k.lower() for k in (z.get("keywords") or []) if k],
        }
    return themen


def finde_themen_fuer(text, themen):
    """Wie mythen_katalog.finde_themen, aber gegen die Themen EINES Nutzers.
    Rueckgabe: Slugs, sortiert nach Kerngewicht (wichtigstes zuerst)."""
    if not text or not themen:
        return []
    text_klein = text.lower()
    treffer = []
    for slug, thema in themen.items():
        for kw in thema.get("keywords") or []:
            if kw in text_klein:
                treffer.append(slug)
                break
    treffer.sort(key=lambda s: -themen[s]["kerngewicht"])
    return treffer


def keywords_union():
    """Union der Keywords ALLER aktiven Nutzer-Themen — der billige
    Akquise-Vorfilter (welche Videos ueberhaupt Stufe A/B sehen).
    None im Lokal-Modus (dort filtert mythen_katalog.finde_themen)."""
    if speicher.daten_modus() != "supabase":
        return None
    zeilen = speicher._supabase_get("themen", {
        "select": "keywords", "aktiv": "is.true",
    }) or []
    union = set()
    for z in zeilen:
        for kw in z.get("keywords") or []:
            if kw and len(kw) >= 3:
                union.add(kw.lower())
    if not union:
        # Noch keine Nutzer-Themen in der DB -> mythen_katalog als Seed
        import mythen_katalog
        for t in getattr(mythen_katalog, "THEMEN", {}).values():
            union.update(k.lower() for k in t.get("keywords", []))
    logger.info("Keyword-Union: %d Keywords.", len(union))
    return union


def wissensbasis_aus_profil(profil, watchlist_personen):
    """Per-User-Aequivalent der wissensbasis.json fuer analyse._wissensbasis_boni:
    interessen_profil aus radar_profile, personen aus watchlist_personen."""
    personen = []
    for w in watchlist_personen or []:
        personen.append({
            "name": w.get("name") or "",
            "handles": {w.get("plattform") or "": w.get("handle") or ""},
            "prioritaet": int(w.get("prioritaet") or 3),
        })
    return {
        "interessen_profil": (profil or {}).get("interessen_profil") or {},
        "personen": personen,
    }


def lade_nutzer():
    """Aktive Nutzer inkl. allem, was die Kuration braucht.
    Lokal-Modus: EIN Pseudo-Nutzer 'lokal' (Christian-Dateien als Fallbacks
    in analyse.py — profil bleibt leer)."""
    if speicher.daten_modus() != "supabase":
        import mythen_katalog
        themen = {slug: {"name": t.get("name", slug),
                         "kerngewicht": float(t.get("kerngewicht", 0.7)),
                         "keywords": [k.lower() for k in t.get("keywords", [])]}
                  for slug, t in getattr(mythen_katalog, "THEMEN", {}).items()}
        gelernt = (speicher.lade_einstellungen() or {}).get("gelernt", {})
        return [{"id": "lokal", "plan": "pro", "profil": {}, "themen": themen,
                 "gelernt": gelernt, "watchlist_personen": []}]

    nutzer = []
    for n in speicher.lade_nutzer_aktiv():
        uid = n["id"]
        n["themen"] = themen_dict(n.get("themen"))
        n["gelernt"] = (speicher.lade_einstellungen(uid) or {}).get("gelernt", {})
        n["watchlist_personen"] = speicher.lade_watchlist_personen(uid)
        nutzer.append(n)
    logger.info("Aktive Nutzer geladen: %d", len(nutzer))
    return nutzer


def narrativ_fn_fuer(user_id):
    """Per-User-O-Ton-Retriever: Query-Embedding (768) + match_narrativ-RPC.
    None im Lokal-Modus (dort nutzt analyse.py den Datei-Index)."""
    if speicher.daten_modus() != "supabase":
        return None

    def _retriever(aussage):
        try:
            import narrativ
            vektor = narrativ.embed_text(aussage, dim=768, task="RETRIEVAL_QUERY")
            if not vektor:
                return ""
            chunks = speicher._supabase_rpc("match_narrativ", {
                "p_user": str(user_id), "p_embedding": vektor, "p_k": 2,
            }) or []
            passagen = [c.get("text", "")[:550] for c in chunks if c.get("text")]
            if not passagen:
                return ""
            return ("EIGENE AUSSAGEN DES CREATORS ZUM THEMA (O-Ton aus seinen Videos):\n"
                    + "\n".join("- »%s«" % p for p in passagen))
        except Exception as e:
            logger.debug("Per-User-Narrativ fehlgeschlagen (%s): %s", user_id, e)
            return ""

    return _retriever
