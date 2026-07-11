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

# Wie weit zurueck der Pool betrachtet wird, wenn der Nutzer noch keinen
# Kurationslauf hatte (Onboarding: erste Inbox soll nicht leer sein).
POOL_FENSTER_TAGE_ERSTLAUF = int(os.environ.get("RADAR_KURATION_ERSTLAUF_TAGE", "14"))


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
    limits = plan_limits.limits(plan)
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
        seit = _letzter_kurationslauf(uid) or _iso_vor_tagen(POOL_FENSTER_TAGE_ERSTLAUF)
        pool = speicher.lade_pool_neu(seit)
    bereits = speicher.zugeordnete_video_ids(uid)
    kandidaten = [v for v in pool if v.get("id") and v["id"] not in bereits]

    # --- Deterministisches Matching ----------------------------------------
    gematcht = []
    for v in kandidaten:
        text = " ".join(filter(None, [v.get("titel"), v.get("caption"),
                                      (v.get("claim") or {}).get("aussage"),
                                      v.get("transkript")]))
        slugs = themenwelt.finde_themen_fuer(text, themen)
        auf_watchlist = _watchlist_treffer(v, watchlist)
        if not slugs and not auf_watchlist:
            continue
        slug = slugs[0] if slugs else sorted(themen, key=lambda s: -themen[s]["kerngewicht"])[0]
        gematcht.append((_match_score(v, slug, themen, gelernt, auf_watchlist), slug, v))
    gematcht.sort(key=lambda t: -t[0])

    cap = limit or limits["kuration_max_neu"]
    auswahl = gematcht[:cap]
    print("[kuration] %s (%s): Pool=%d, neu=%d, gematcht=%d, bewertet werden=%d"
          % (uid, plan, len(pool), len(kandidaten), len(gematcht), len(auswahl)))

    # --- Stufe C/C+/D gegen das Nutzer-Profil -------------------------------
    positions_text = (analyse.positionen_als_text(profil.get("positionen"))
                      or None)  # None -> analyse nutzt themenlandkarte-Fallback
    wissensbasis = themenwelt.wissensbasis_aus_profil(profil, watchlist)
    narrativ_fn = themenwelt.narrativ_fn_fuer(uid)

    zuordnungen, geflaggt = [], 0
    for _, slug, video in auswahl:
        # Kopie: bewerte_kandidat/_markiere_verworfen mutieren das Dict, der
        # Pool-Ausschnitt wird aber fuer ALLE Nutzer wiederverwendet.
        video = dict(video)
        aussage = ((video.get("claim") or {}).get("aussage") or "").strip()
        if not aussage:
            continue
        webcheck_cache = video.get("webcheck") or None
        try:
            ergebnis = analyse.bewerte_kandidat(
                video, aussage, slug, gelernt, themen,
                positions_text or analyse.lade_positions_tabelle(),
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
            claim = video.get("claim") or {}
            zuordnungen.append({
                "video_id": video["id"], "status": "archiv", "thema_slug": slug,
                "verdict": {"verdict": claim.get("verdict") or "korrekt",
                            "begruendung": claim.get("begruendung") or ""},
                "begruendung": claim.get("begruendung") or "",
            })
            continue

        geflaggt += 1
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

    gespeichert = speicher.speichere_zuordnungen(uid, zuordnungen)
    protokoll = {
        "user_id": str(uid), "typ": "kuration", "quelle": "kuration",
        "gefunden": len(kandidaten), "neu": gespeichert,
        "analysiert": len(auswahl), "geflaggt": geflaggt,
        "fehler": fehler, "dauer_s": int(time.time() - start),
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

    # Pool EINMAL fuer den aeltesten Bedarf laden und fuer alle wiederverwenden
    aelteste = None
    for n in nutzer:
        seit = _letzter_kurationslauf(n["id"]) or _iso_vor_tagen(POOL_FENSTER_TAGE_ERSTLAUF)
        aelteste = seit if (aelteste is None or seit < aelteste) else aelteste
    pool = speicher.lade_pool_neu(aelteste or _iso_vor_tagen(POOL_FENSTER_TAGE_ERSTLAUF))
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
