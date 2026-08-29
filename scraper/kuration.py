# -*- coding: utf-8 -*-
"""
kuration.py — Per-User-Kuration aus dem geteilten Video-Pool (Multi-Tenant).

Der Akquise-Lauf (lauf.py) fuellt den mandantenneutralen Pool (Tabelle videos,
inkl. Stufe-A/B-Claim). Dieser Lauf ordnet jedem aktiven Nutzer die Videos zu,
die zu SEINEM Profil passen:

  1. Deterministisches Matching (kein LLM): Keywords der Nutzer-Themen ×
     kerngewicht × Reichweite × Watchlist-Bonus × themen_boost.
  2. Nur die Top-K (Plan-Cap) durchlaufen die teure Stufe C/C+/D
     (Verdict gegen die POSITIONEN DES NUTZERS, O-Ton via match_narrativ,
     Websuche-Ergebnis wird am Pool-Video gecacht).
  3. Ergebnis -> video_zuordnung (bestehende Zuordnungen werden nie
     ueberschrieben) + agent_runs(typ='kuration', user_id).

CLI:
    python3 kuration.py --alle            # alle aktiven Nutzer (Cron)
    python3 kuration.py --user <uuid>     # ein Nutzer (z.B. nach "Jetzt suchen")
    python3 kuration.py --alle --nur-pro  # nur Pro-Nutzer (4h-Slots)
"""

import argparse
import datetime
import json
import math
import os
import sys
import time

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import analyse
import plan_limits
import speicher
import themenwelt

# Wie weit zurueck der Pool je Kurationslauf betrachtet wird. Frueher: nur seit
# dem letzten Lauf des Nutzers — dadurch fielen Kandidaten, die das Relevanz-
# Gate knapp verfehlten oder hinter dem Plan-Cap warteten ("Rest naechster
# Lauf"), fuer immer durchs Raster. Jetzt IMMER ein festes Fenster: bereits
# zugeordnete Videos werden dedupliziert (kein doppelter LLM-Call), die
# Bewertungen pro Lauf bleiben durch kuration_max_neu gedeckelt.
POOL_FENSTER_TAGE = int(os.environ.get("RADAR_KURATION_FENSTER_TAGE",
                                       os.environ.get("RADAR_KURATION_ERSTLAUF_TAGE", "14")))
POOL_FENSTER_TAGE_ERSTLAUF = POOL_FENSTER_TAGE


# Ziel-Fuellstand der Inbox: darunter wird ein zweiter Bewertungs-Batch erlaubt
# (max. 2x Plan-Cap) und bei 0 ein automatischer Suchlauf angefordert.
INBOX_MIN = int(os.environ.get("RADAR_INBOX_MIN", "3") or "3")
NACHSCHUB_STUNDEN = float(os.environ.get("RADAR_NACHSCHUB_H", "8") or "8")


def _auto_nachschub(uid):
    """Leere Inbox nach der Kuration: Auftrag typ=lauf fuer den Nutzer anlegen
    (worker -> lauf.py --user -> kuration). Gate: aktive Queries vorhanden,
    kein offener Lauf-Auftrag, letzter Auto-Nachschub > NACHSCHUB_STUNDEN her."""
    if speicher.daten_modus() != "supabase":
        return False
    queries = speicher._supabase_get("suchqueries", {
        "select": "id", "user_id": "eq." + str(uid), "aktiv": "is.true", "limit": "1"}) or []
    if not queries:
        return False
    offen = speicher._supabase_get("auftraege", {
        "select": "id", "user_id": "eq." + str(uid), "typ": "eq.lauf",
        "status": "in.(offen,laeuft)", "limit": "1"}) or []
    if offen:
        return False
    zeilen = speicher._supabase_get("einstellungen", {
        "select": "value", "user_id": "eq." + str(uid), "key": "eq.nachschub_auto"}) or []
    letzte = ((zeilen[0].get("value") if zeilen else None) or {}).get("zeit") or ""
    grenze = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=NACHSCHUB_STUNDEN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if letzte and letzte > grenze:
        return False
    jetzt = speicher.jetzt_iso()
    ok = speicher._supabase_post("auftraege", [{"user_id": str(uid), "typ": "lauf"}])
    if ok:
        speicher._supabase_post("einstellungen", [{
            "user_id": str(uid), "key": "nachschub_auto",
            "value": {"zeit": jetzt}, "aktualisiert_am": jetzt,
        }], prefer="return=minimal,resolution=merge-duplicates")
        print("[kuration] %s: Inbox leer -> automatischer Suchlauf angefordert" % uid)
    return bool(ok)


def _iso_vor_tagen(tage):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=tage)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _letzter_kurationslauf(user_id):
    """Zeit des letzten Kurationslaufs des Nutzers (agent_runs) oder None."""
    zeilen = speicher._supabase_get("agent_runs", {
        "select": "zeit", "user_id": "eq." + str(user_id), "typ": "eq.kuration",
        "order": "zeit.desc", "limit": "1",
    }) or []
    return zeilen[0]["zeit"] if zeilen else None


def _watchlist_treffer(video, watchlist_personen):
    """True, wenn der Absender des Videos auf der Watchlist des Nutzers steht."""
    kanal = ((video.get("kanal") or "") + " " + (video.get("kanal_id") or "")).lower()
    if not kanal.strip():
        return False
    for w in watchlist_personen or []:
        namen = []
        kern = (w.get("name") or "").split("(")[0].strip().lower()
        if kern:
            namen.append(kern)
        if w.get("handle"):
            namen.append(str(w["handle"]).lower().lstrip("@"))
        if any(n and n in kanal for n in namen):
            return True
    return False


def _cosine(a, b):
    skalar = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return skalar / (na * nb) if na and nb else 0.0


def _match_score(video, thema_slug, themen, gelernt, auf_watchlist):
    """Deterministischer Vorab-Score fuers Ranking der Kandidaten (kein LLM)."""
    kerngewicht = themen.get(thema_slug, {}).get("kerngewicht", 0.7)
    views = float(video.get("views") or 0) or float(video.get("likes") or 0) * 12.0
    reichweite = math.log10(views + 10.0)
    boost = float(((gelernt or {}).get("themen_boost") or {}).get(thema_slug, 0.0) or 0.0)
    score = kerngewicht * reichweite * (1.0 + 0.3 * max(-1.0, min(1.0, boost)))
    if auf_watchlist:
        score *= 1.5
    return score


def kuratiere_nutzer(nutzer, pool=None, limit=None):
    """Kuration fuer EINEN Nutzer. Rueckgabe: Protokoll-Dict (agent_run-Form)."""
    uid = nutzer["id"]
    plan = nutzer.get("plan") or "free"
    limits = plan_limits.limits(plan, nutzer.get("limits"))
    themen = nutzer.get("themen") or {}
    gelernt = nutzer.get("gelernt") or {}
    profil = nutzer.get("profil") or {}
    watchlist = nutzer.get("watchlist_personen") or []
    start = time.time()
    fehler = []

    if not themen:
        print("[kuration] %s: keine Themen im Profil — uebersprungen" % uid)
        return None

    # --- Pool-Ausschnitt laden ---------------------------------------------
    if pool is None:
        pool = speicher.lade_pool_neu(_iso_vor_tagen(POOL_FENSTER_TAGE))
    bereits = speicher.zugeordnete_video_ids(uid)
    # NUR Videos mit extrahierter Kernaussage sind Kandidaten. Aussortierte
    # (claim.aussage=null) belegten sonst per Keyword-Treffer die Top-K-Plaetze
    # und wurden dann still uebersprungen -> "bewertet werden=10, 0 zugeordnet".
    ohne_aussage = 0
    kandidaten = []
    for v in pool:
        if not v.get("id") or v["id"] in bereits:
            continue
        if not ((v.get("claim") or {}).get("aussage") or "").strip():
            ohne_aussage += 1
            continue
        kandidaten.append(v)
    diagnose = {"pool": len(pool), "kandidaten": len(kandidaten),
                "ohne_aussage": ohne_aussage, "themen": len(themen)}

    # --- Deterministisches Matching ----------------------------------------
    gematcht = []
    gematcht_ids = set()
    for v in kandidaten:
        # BEWUSST ohne Transkript: generische Keywords ("motivation", "freiheit")
        # matchen sonst in jedem langen Transkript — Titel/Caption/Kernaussage
        # tragen die eigentliche Themen-Information.
        text = " ".join(filter(None, [v.get("titel"), v.get("caption"),
                                      (v.get("claim") or {}).get("aussage")]))
        slugs = themenwelt.finde_themen_fuer(text, themen)
        auf_watchlist = _watchlist_treffer(v, watchlist)
        if not slugs and not auf_watchlist:
            continue
        slug = slugs[0] if slugs else sorted(themen, key=lambda s: -themen[s]["kerngewicht"])[0]
        gematcht.append((_match_score(v, slug, themen, gelernt, auf_watchlist), slug, v))
        gematcht_ids.add(v.get("id"))

    # --- Semantisches Matching (Pool-Vernetzung) -----------------------------
    # Aehnlichkeit zwischen Nutzer-Themen und Claim-Embeddings des GESAMTEN
    # Pools — findet auch Funde ohne Keyword-Treffer (z.B. von den Suchen
    # ANDERER Nutzer). Schwelle konservativ, Kosten: 0 LLM-Calls (Embeddings
    # sind gecacht bzw. einmalig pro Thema).
    # Kalibriert 2026-07-11 auf gemini-embedding-001@768 (hohe Baseline ~0.58):
    # eigene Nischen-Claims erreichen 0.67-0.74, fachfremde max ~0.66.
    SEMANTIK_SCHWELLE = float(os.environ.get("RADAR_SEMANTIK_SCHWELLE", "0.66"))
    pool_nach_id = {v.get("id"): v for v in kandidaten}
    semantisch = 0
    seit_iso = min((v.get("gefunden_am") or "9999" for v in pool), default=None)
    if pool_nach_id and seit_iso:
        for slug, thema in themen.items():
            emb = speicher.hole_thema_embedding(uid, slug, thema)
            if not emb:
                continue
            treffer = speicher._supabase_rpc("match_pool", {
                "p_embedding": emb, "p_seit": seit_iso, "p_k": 10}) or []
            for t in treffer:
                vid = t.get("id")
                if (vid not in pool_nach_id or vid in gematcht_ids
                        or float(t.get("aehnlichkeit") or 0) < SEMANTIK_SCHWELLE):
                    continue
                v = pool_nach_id[vid]
                score = (_match_score(v, slug, themen, gelernt, False)
                         * float(t["aehnlichkeit"]))
                gematcht.append((score, slug, v))
                gematcht_ids.add(vid)
                semantisch += 1
    diagnose["keyword"] = len(gematcht) - semantisch
    diagnose["semantisch"] = semantisch
    if semantisch:
        print("[kuration] %s: +%d semantische Kandidaten (Pool-Vernetzung)"
              % (uid, semantisch))

    # --- Relevanz-Gate: Keyword-Treffer sind nur ein VORSCHLAG — bestehen
    # muss jeder Kandidat die semantische Naehe zwischen SEINEM Thema und der
    # Kernaussage des Videos. Fachfremde Kategorie => hoehere Huerde.
    MIN_AEHNLICHKEIT = float(os.environ.get("RADAR_MATCH_MIN_AEHNLICHKEIT", "0.66"))
    FREMD_AEHNLICHKEIT = 0.68
    # Video liegt laut neutraler Stufe A/B (LLM) in einem Interessen-Bereich des
    # Nutzers: das ist bereits ein starkes Relevanz-Signal, das Embedding muss
    # nur noch grobe Ausreisser abfangen. Gemessen 2026-08-29 (Starter-Profil
    # Medizin/Psychologie/Beauty): passende Bereichs-Claims liegen bei
    # 0.60-0.71, fachfremde (Finanzen/Krypto) ebenfalls bis 0.62 — die trennt
    # aber schon die Kategorie. Mit 0.66 wurden 39/42 Kandidaten verworfen.
    EIGEN_AEHNLICHKEIT = float(os.environ.get("RADAR_MATCH_MIN_AEHNLICHKEIT_EIGEN", "0.60"))
    labels = set((profil.get("interessen_profil") or {}).get("interessen_labels") or [])
    # Embeddings ALLER Nutzer-Themen (gecacht in themen.embedding): Der Keyword-
    # Treffer ist nur ein Hinweis, welches Thema gemeint sein KOENNTE — gemessen
    # wird gegen das aehnlichste Thema, und das wird dann auch zugeordnet.
    # (Vorher: nur gegen das Keyword-Thema -> "trauma"/"erfolg" im Titel band
    # einen Medizin-Claim an Pop-Psychologie und liess ihn am Gate scheitern.)
    thema_embs = {}
    for slug_, thema_ in themen.items():
        thema_embs[slug_] = speicher.hole_thema_embedding(uid, slug_, thema_)
    gate_verworfen = 0
    gefiltert = []
    for eintrag in gematcht:
        score_alt, slug, v = eintrag
        emb_v = v.get("claim_embedding")
        if isinstance(emb_v, str):
            try:
                emb_v = json.loads(emb_v)
            except ValueError:
                emb_v = None
        if not emb_v:
            gefiltert.append(eintrag)  # Uebergangsfall: kein Embedding -> durchlassen
            continue
        sims = [(_cosine(e, emb_v), s) for s, e in thema_embs.items() if e]
        if not sims:
            gefiltert.append(eintrag)
            continue
        sim, bester_slug = max(sims, key=lambda t: t[0])
        if bester_slug != slug and not _watchlist_treffer(v, watchlist):
            slug = bester_slug
            eintrag = (_match_score(v, slug, themen, gelernt, False), slug, v)
        grenze = MIN_AEHNLICHKEIT
        # Hat der Nutzer Interessen-Labels, gilt fuer alles AUSSERHALB davon die
        # hoehere Huerde — auch fuer UNkategorisierte Videos (kategorie=None ist
        # meist fachfremder Watchlist-/Lifestyle-Content, kein Freifahrtschein).
        # INNERHALB seiner Bereiche reicht die niedrigere Huerde.
        if labels and (v.get("kategorie") not in labels):
            grenze = max(grenze, FREMD_AEHNLICHKEIT)
        elif labels:
            grenze = min(grenze, EIGEN_AEHNLICHKEIT)
        if sim < grenze:
            gate_verworfen += 1
            continue
        gefiltert.append(eintrag)
    gematcht = gefiltert
    diagnose["gate_verworfen"] = gate_verworfen
    if gate_verworfen:
        print("[kuration] %s: relevanz_gate=%d Kandidaten verworfen (zu themenfern)"
              % (uid, gate_verworfen))

    gematcht.sort(key=lambda t: -t[0])

    cap = limit or limits["kuration_max_neu"]
    auswahl = gematcht[:cap]
    print("[kuration] %s (%s): Pool=%d, neu=%d, gematcht=%d, bewertet werden=%d (+Nachschlag bei Inbox<%d)"
          % (uid, plan, len(pool), len(kandidaten), len(gematcht), len(auswahl), INBOX_MIN))

    # --- Stufe C/C+/D gegen das Nutzer-Profil -------------------------------
    positions_text = themenwelt.massstab_text(uid, profil, themen)
    wissensbasis = themenwelt.wissensbasis_aus_profil(profil, watchlist)
    narrativ_fn = themenwelt.narrativ_fn_fuer(uid)

    # Nachschub-Garantie: Ist die Inbox des Nutzers duenn (< INBOX_MIN), darf
    # ein zweiter Batch bewertet werden (max. 2x Plan-Cap) — der Creator soll
    # nach einem Lauf MATERIAL haben, nicht nur eine Warteschlange.
    inbox_vorher = len(speicher.lade_zuordnungen(uid, ["inbox"], select="video_id"))
    inbox_neu = 0
    zuordnungen, geflaggt, korrekt, bewertet = [], 0, 0, 0
    for _, slug, video in gematcht:
        if bewertet >= cap and (inbox_vorher + inbox_neu >= INBOX_MIN or bewertet >= cap * 2):
            break
        # Kopie: bewerte_kandidat/_markiere_verworfen mutieren das Dict, der
        # Pool-Ausschnitt wird aber fuer ALLE Nutzer wiederverwendet.
        video = dict(video)
        aussage = ((video.get("claim") or {}).get("aussage") or "").strip()
        if not aussage:
            continue
        bewertet += 1
        webcheck_cache = video.get("webcheck") or None
        try:
            ergebnis = analyse.bewerte_kandidat(
                video, aussage, slug, gelernt, themen, positions_text,
                wissensbasis=wissensbasis, narrativ_fn=narrativ_fn,
                webcheck_cache=webcheck_cache)
        except Exception as e:
            fehler.append("%s: %s" % (video.get("id"), e))
            continue

        # Frisches Websuche-Ergebnis am Pool-Video cachen (fuer alle Nutzer)
        roh = (ergebnis or video).get("_webcheck_roh")
        if roh:
            speicher.speichere_webcheck(video["id"], roh)

        if ergebnis is None:
            # 'korrekt' — als archiv-Zuordnung festhalten (Dedupe: nie wieder bewerten)
            korrekt += 1
            claim = video.get("claim") or {}
            zuordnungen.append({
                "video_id": video["id"], "status": "archiv", "thema_slug": slug,
                "verdict": {"verdict": claim.get("verdict") or "korrekt",
                            "begruendung": claim.get("begruendung") or ""},
                "begruendung": claim.get("begruendung") or "",
            })
            continue

        geflaggt += 1
        if ergebnis["status"] == "inbox":
            inbox_neu += 1
        claim = ergebnis["claim"]
        zuordnungen.append({
            "video_id": video["id"],
            "status": ergebnis["status"],
            "thema_slug": slug,
            "score": ergebnis["score"],
            "scores": ergebnis["scores"],
            "verdict": {"verdict": claim["verdict"], "konfidenz": claim["konfidenz"],
                        "begruendung": claim["begruendung"],
                        "websuche": claim.get("websuche"),
                        "quellen": claim.get("quellen") or []},
            "begruendung": claim["begruendung"],
        })
    auswahl = gematcht[:bewertet]

    gespeichert = speicher.speichere_zuordnungen(uid, zuordnungen)
    inbox_gesamt = inbox_vorher + inbox_neu
    diagnose.update({"bewertet": bewertet, "korrekt": korrekt,
                     "geflaggt": geflaggt, "inbox_neu": inbox_neu,
                     "inbox_gesamt": inbox_gesamt, "gematcht": len(gematcht),
                     "nachschlag": max(0, bewertet - cap),
                     "warteschlange": max(0, len(gematcht) - bewertet)})
    # Inbox trotz allem leer? -> automatisch einen Suchlauf fuer diesen Nutzer
    # anfordern (seine Queries ohne Cooldown, ertragslose breiter) — hoechstens
    # alle NACHSCHUB_STUNDEN, damit Apify-Kosten gedeckelt bleiben.
    if inbox_gesamt == 0:
        try:
            if _auto_nachschub(uid):
                diagnose["auto_nachschub"] = 1
        except Exception as e:
            print("[kuration] WARNUNG: Auto-Nachschub fehlgeschlagen: %s" % e)
    protokoll = {
        "user_id": str(uid), "typ": "kuration", "quelle": "kuration",
        "gefunden": len(kandidaten), "neu": gespeichert,
        "analysiert": len(auswahl), "geflaggt": geflaggt,
        "fehler": fehler, "dauer_s": int(time.time() - start),
        # Diagnose fuers UI ("warum ist meine Inbox leer?")
        "detail": diagnose,
    }
    speicher.speichere_agent_run(protokoll)
    print("[kuration] %s: %d zugeordnet (%d geflaggt), %d Fehler, %ds"
          % (uid, gespeichert, geflaggt, len(fehler), protokoll["dauer_s"]))
    return protokoll


def main():
    parser = argparse.ArgumentParser(description="Wolf Radar — Per-User-Kuration")
    parser.add_argument("--user", help="Nur diesen Nutzer kuratieren (UUID)")
    parser.add_argument("--alle", action="store_true", help="Alle aktiven Nutzer")
    parser.add_argument("--nur-pro", action="store_true",
                        help="Nur Pro-Nutzer (fuer die 4h-Slots; Free laeuft 1x taeglich)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max. Bewertungen pro Nutzer (ueberschreibt Plan-Cap)")
    args = parser.parse_args()

    if speicher.daten_modus() != "supabase":
        print("[kuration] Nur im Supabase-Modus sinnvoll (Lokal-Modus nutzt lauf.py voll).")
        return 0

    nutzer = themenwelt.lade_nutzer()
    if args.user:
        nutzer = [n for n in nutzer if str(n["id"]) == args.user]
        if not nutzer:
            # "Jetzt suchen" darf auch Nutzer im Onboarding-Review bedienen
            profil = speicher.lade_profil(args.user)
            if profil:
                nutzer = [{"id": args.user, "plan": "free",
                           "profil": profil,
                           "themen": themenwelt.themen_dict(speicher.lade_themen(args.user)),
                           "gelernt": (speicher.lade_einstellungen(args.user) or {}).get("gelernt", {}),
                           "watchlist_personen": speicher.lade_watchlist_personen(args.user)}]
        if not nutzer:
            print("[kuration] Nutzer %s nicht gefunden/aktiv." % args.user)
            return 1
    elif args.nur_pro:
        nutzer = [n for n in nutzer if (n.get("plan") or "free") == "pro"]
    elif not args.alle:
        parser.error("--user <uuid> oder --alle angeben")

    # Pool EINMAL laden (festes Fenster) und fuer alle Nutzer wiederverwenden
    aelteste = _iso_vor_tagen(POOL_FENSTER_TAGE)
    pool = speicher.lade_pool_neu(aelteste)
    print("[kuration] %d Nutzer, Pool-Fenster seit %s: %d Videos"
          % (len(nutzer), aelteste, len(pool)))

    for n in nutzer:
        try:
            kuratiere_nutzer(n, pool=pool, limit=args.limit)
        except Exception as e:
            print("[kuration] FEHLER bei Nutzer %s: %s" % (n.get("id"), e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
