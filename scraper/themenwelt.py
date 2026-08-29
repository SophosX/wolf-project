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


# "Jetzt suchen" eines Nutzers: seine Queries umgehen den normalen Cooldown,
# aber nicht oefter als alle N Stunden (Spam-/Kostenschutz).
BEVORZUGT_MIN_STUNDEN = float(os.environ.get("RADAR_BEVORZUGT_MIN_H", "1") or "1")

# YouTube-Zeitfenster (streamers~youtube-scraper dateFilter). Die Kosten sind
# pay-per-result und durch maxResults gedeckelt — ein weiteres Fenster kostet
# also NICHT mehr, es liefert nur eher volle Trefferlisten.
YT_FENSTER_BASIS = os.environ.get("RADAR_YT_APIFY_DATEFILTER", "week").strip() or "week"
YT_FENSTER_STUFEN = ["week", "month", "year"]


def lade_status_map():
    """scrape_status komplett als {(plattform, query_norm): zeile}."""
    zeilen = speicher._supabase_get("scrape_status", {"select": "*"}) or []
    return {(z.get("plattform"), z.get("query_norm")): z for z in zeilen}


def query_norm(q):
    return (q or "").strip().lstrip("#").lower()


def fenster_fuer(plattform, status_zeile):
    """Adaptive Suchbreite je Query aus der Ertragshistorie:
    - nie gescrapt (Neu-Nutzer/neue Query): direkt breit -> erste Funde SOFORT
    - zuletzt Treffer: Basis-Fenster (guenstig, frisch)
    - 1x leer: eine Stufe breiter, >=2x leer: maximal breit
    YouTube: today/week/month/year; TikTok/Instagram: normal|breit."""
    nie = not status_zeile or not status_zeile.get("zuletzt")
    leer = int((status_zeile or {}).get("leer_folge") or 0)
    if plattform == "youtube":
        if nie or leer >= 2:
            return "year" if leer >= 2 else "month"
        if leer == 1:
            try:
                i = YT_FENSTER_STUFEN.index(YT_FENSTER_BASIS)
            except ValueError:
                i = 0
            return YT_FENSTER_STUFEN[min(i + 1, len(YT_FENSTER_STUFEN) - 1)]
        return YT_FENSTER_BASIS
    return "breit" if (nie or leer >= 1) else "normal"


def lade_scrape_plan(bevorzugt_user=None):
    """Der Akquise-Plan dieses Laufs: {youtube: [...], tiktok: [...],
    instagram_hashtags: [...], watchlist: [eintraege],
    fenster: {plattform: {query: fenster}}}.
    bevorzugt_user: dessen Queries laufen OHNE Rotations-Cap und ohne den
    24h-Cooldown ("Jetzt suchen" eines Nutzers muss SEINE Suche ausloesen)."""
    if speicher.daten_modus() != "supabase":
        plan = _lokaler_scrape_plan()
        plan["fenster"] = {}
        return plan

    import datetime
    import plan_limits

    plan = {"youtube": [], "tiktok": [], "instagram_hashtags": [], "watchlist": [],
            "fenster": {"youtube": {}, "tiktok": {}, "instagram": {}}}
    status_map = lade_status_map()
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    cooldown_grenze = (jetzt - datetime.timedelta(hours=QUERY_COOLDOWN_STUNDEN)
                       ).strftime("%Y-%m-%dT%H:%M:%SZ")
    bevorzugt_grenze = (jetzt - datetime.timedelta(hours=BEVORZUGT_MIN_STUNDEN)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    bevorzugt_user = str(bevorzugt_user) if bevorzugt_user else None

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
    uebersprungen = 0
    # Bevorzugter Nutzer zuerst, damit seine Queries den Dedupe "gewinnen"
    reihenfolge = sorted(je_user.keys(), key=lambda u: 0 if u == bevorzugt_user else 1)
    for uid in reihenfolge:
        qs = je_user[uid]
        ist_bevorzugt = (uid == bevorzugt_user)
        cap = int(limits_je_user[uid].get("queries_pro_lauf") or 12)
        if len(qs) > cap and not ist_bevorzugt:
            start = (tag * cap) % len(qs)
            qs = (qs + qs)[start:start + cap]
            logger.info("Query-Rotation %s: %d von %d Queries in diesem Lauf.",
                        uid, cap, len(je_user[uid]))
        for z in qs:
            p = z.get("plattform")
            norm = (p, query_norm(z.get("query")))
            if not norm[1] or norm in gesehen or p not in ("youtube", "tiktok", "instagram"):
                continue
            zeile = status_map.get(norm)
            zuletzt = (zeile or {}).get("zuletzt") or ""
            grenze = bevorzugt_grenze if ist_bevorzugt else cooldown_grenze
            if zuletzt and zuletzt > grenze:
                uebersprungen += 1
                continue
            gesehen.add(norm)
            text = z.get("query", "").strip()
            fenster = fenster_fuer(p, zeile)
            if p == "instagram":
                plan["instagram_hashtags"].append(text.lstrip("#"))
                plan["fenster"]["instagram"][text.lstrip("#")] = fenster
            else:
                plan[p].append(text)
                plan["fenster"][p][text] = fenster
    if uebersprungen:
        logger.info("Cooldown: %d Queries uebersprungen (<%dh%s).", uebersprungen,
                    QUERY_COOLDOWN_STUNDEN,
                    ", bevorzugt <%gh" % BEVORZUGT_MIN_STUNDEN if bevorzugt_user else "")

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
    # Leerer Plan: Entweder sind alle Queries im Cooldown (normal, dann NICHT
    # den Seed-Katalog scrapen — das kostete frueher jedes Mal Geld) oder es
    # gibt noch gar keine Nutzer-Queries (dann Seed).
    if not any((plan["youtube"], plan["tiktok"], plan["instagram_hashtags"])):
        if not zeilen:
            logger.warning("Scrape-Plan aus DB leer — nutze mythen_katalog als Seed.")
            lokal = _lokaler_scrape_plan()
            lokal["watchlist"] = plan["watchlist"] or lokal["watchlist"]
            lokal["fenster"] = {}
            return lokal
        logger.info("Scrape-Plan: alle Queries im Cooldown — nur Watchlist in diesem Lauf.")
    return plan


def markiere_gescrapte(plattform, queries, protokoll=None, fenster=None):
    """Nach dem Scrapen: scrape_status upserten — Cooldown-Grundlage UND
    Ertragsstatistik (letzte_treffer, leer_folge, fenster) fuer die adaptive
    Suchbreite und die Nutzer-Rueckmeldung ("Begriff X fand 3x nichts")."""
    if speicher.daten_modus() != "supabase" or not queries:
        return
    treffer = {}
    for p in protokoll or []:
        treffer[query_norm(p.get("query"))] = int(p.get("gefunden") or 0)
    fehler = {query_norm(p.get("query")) for p in (protokoll or []) if p.get("fehler")}
    alt = {}
    try:
        zeilen = speicher._supabase_get("scrape_status", {
            "select": "query_norm,treffer_gesamt,leer_folge,fehler_folge",
            "plattform": "eq." + plattform}) or []
        alt = {z["query_norm"]: z for z in zeilen}
    except Exception as e:
        logger.debug("scrape_status nicht lesbar: %s", e)
    jetzt = speicher.jetzt_iso()
    upserts = []
    for q in queries:
        norm = query_norm(q)
        if not norm:
            continue
        a = alt.get(norm) or {}
        n = treffer.get(norm, 0)
        zeile = {"plattform": plattform, "query_norm": norm, "zuletzt": jetzt,
                 "letzte_treffer": n,
                 "treffer_gesamt": int(a.get("treffer_gesamt") or 0) + n,
                 "fehler_folge": (int(a.get("fehler_folge") or 0) + 1) if norm in fehler else 0,
                 "fenster": (fenster or {}).get(q) or (fenster or {}).get(norm)}
        if norm in fehler:
            # Gestoerter Lauf ist kein Urteil ueber den Begriff
            zeile["leer_folge"] = int(a.get("leer_folge") or 0)
        else:
            zeile["leer_folge"] = 0 if n > 0 else int(a.get("leer_folge") or 0) + 1
        upserts.append(zeile)
    if upserts:
        speicher._supabase_post("scrape_status", upserts,
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


# ---------------------------------------------------------------------------
# Pool-Vernetzung: neutrale Kategorie + Claim-Embedding am geteilten Pool.
# Jeder Fund — egal wessen Suche ihn fand — wird so fuer ALLE Nutzer
# auffindbar (Kategorie-Filter + semantische Aehnlichkeit).
# ---------------------------------------------------------------------------

_KATALOG_CACHE = None


def _interessen_katalog():
    global _KATALOG_CACHE
    if _KATALOG_CACHE is None:
        import json
        try:
            with open(os.path.join(SCRAPER_DIR, "interessen_katalog.json"),
                      encoding="utf-8") as f:
                _KATALOG_CACHE = json.load(f).get("bereiche", [])
        except (OSError, ValueError) as e:
            logger.warning("interessen_katalog.json nicht lesbar: %s", e)
            _KATALOG_CACHE = []
    return _KATALOG_CACHE


def pool_kategorien():
    """Neutrale Bereichs-Slugs des interessen_katalog + 'sonstiges' — die
    erlaubte Themen-Liste der Stufe A/B im AKQUISE-Modus (geteilter Pool).
    Damit ist der Pool mandantenneutral: ein Psychologie- oder Finanz-Video
    wird NICHT mehr als 'kein Ernaehrungsthema' aussortiert."""
    slugs = [b.get("slug") for b in _interessen_katalog() if b.get("slug")]
    return slugs + ["sonstiges"]


def pool_nische_text(max_nutzer_nischen=10):
    """Nischen-Beschreibung fuer die neutrale Stufe A/B: alle Katalog-Bereiche
    plus die individuellen Nischen der aktiven Nutzer (radar_profile.nische)."""
    labels = [b.get("label") for b in _interessen_katalog() if b.get("label")]
    extra = []
    if speicher.daten_modus() == "supabase":
        try:
            zeilen = speicher._supabase_get("radar_profile", {"select": "nische"}) or []
            gesehen = set(l.lower() for l in labels)
            for z in zeilen:
                n = (z.get("nische") or "").strip()
                if n and n.lower() not in gesehen and len(n) <= 120:
                    gesehen.add(n.lower())
                    extra.append(n)
                if len(extra) >= max_nutzer_nischen:
                    break
        except Exception as e:
            logger.debug("Nutzer-Nischen nicht ladbar: %s", e)
    teile = labels + extra
    return ("Creator-Nischen, in denen Falschinformationen richtiggestellt werden: "
            + "; ".join(teile)) if teile else None


def kategorisiere(text):
    """Neutraler Bereichs-Slug (interessen_katalog) mit den meisten
    Keyword-Treffern im Text; None ohne Treffer. Deterministisch, kein LLM."""
    if not text:
        return None
    text_klein = text.lower()
    beste, beste_treffer = None, 0
    for bereich in _interessen_katalog():
        treffer = 0
        for thema in bereich.get("themen", []):
            treffer += sum(1 for kw in thema.get("keywords", []) if kw in text_klein)
        if treffer > beste_treffer:
            beste, beste_treffer = bereich["slug"], treffer
    return beste


def vernetze_pool_kandidaten(kandidaten):
    """Nach der Claim-Extraktion (Akquise): kategorie + claim_embedding an
    neue Pool-Videos haengen. Fail-safe — Fehler kosten nur die Vernetzung."""
    if speicher.daten_modus() != "supabase":
        return
    import time as _time
    try:
        import narrativ
    except ImportError:
        return
    n = 0
    for k in kandidaten or []:
        aussage = ((k.get("claim") or {}).get("aussage") or "").strip()
        if not aussage:
            continue
        # Bereich bevorzugt aus der neutralen Stufe A/B (LLM), sonst Keywords
        thema = ((k.get("claim") or {}).get("thema") or "").strip()
        if thema and thema != "sonstiges" and thema in pool_kategorien():
            k["kategorie"] = thema
        else:
            k["kategorie"] = kategorisiere(" ".join(filter(None, [
                k.get("titel"), aussage, k.get("caption")])))
        try:
            k["claim_embedding"] = narrativ.embed_text(
                aussage, dim=768, task="RETRIEVAL_DOCUMENT") or None
            n += 1
            _time.sleep(0.1)
        except Exception as e:
            logger.debug("Claim-Embedding %s fehlgeschlagen: %s", k.get("id"), e)
    if n:
        logger.info("Pool-Vernetzung: %d Claims embedded/kategorisiert.", n)


def backfill_pool_vernetzung(limit=500):
    """Einmalig: Bestand ohne kategorie/claim_embedding nachvernetzen."""
    zeilen = speicher._supabase_get("videos", {
        "select": "id,titel,caption,claim",
        "claim": "not.is.null", "claim_embedding": "is.null",
        "limit": str(limit),
    }) or []
    print("[vernetzung] Backfill: %d Videos" % len(zeilen))
    import narrativ
    import time as _time
    n = 0
    for v in zeilen:
        aussage = ((v.get("claim") or {}).get("aussage") or "").strip()
        if not aussage:
            continue
        felder = {"kategorie": kategorisiere(" ".join(filter(None, [
            v.get("titel"), aussage, v.get("caption")])))}
        try:
            felder["claim_embedding"] = narrativ.embed_text(
                aussage, dim=768, task="RETRIEVAL_DOCUMENT") or None
        except Exception as e:
            print("[vernetzung] embed %s: %s" % (v["id"], e))
        speicher._supabase_patch("videos", {"id": "eq." + v["id"]}, felder)
        n += 1
        if n % 50 == 0:
            print("[vernetzung] %d/%d" % (n, len(zeilen)))
        _time.sleep(0.1)
    print("[vernetzung] Backfill fertig: %d" % n)
    return n


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
