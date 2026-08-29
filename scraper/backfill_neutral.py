# -*- coding: utf-8 -*-
"""
backfill_neutral.py — Einmal-Werkzeug nach dem Neutral-Fix der Stufe A/B.

Der geteilte Pool hatte bis 2026-08-29 JEDES Video ausserhalb von Christians
Ernaehrungs-Katalog "aussortiert" (claim.aussage=null). Dieses Skript zieht
aussortierte Pool-Videos der letzten N Tage noch einmal durch die
mandantenneutrale Stufe A/B und schreibt claim/kategorie/claim_embedding
zurueck — danach koennen Kurationslaeufe sie den passenden Nutzern zuordnen.

CLI:
    python3 backfill_neutral.py [--tage 14] [--limit 200] [--dry-run]
"""

import argparse
import datetime
import os
import sys

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import analyse
import speicher
import themenwelt


def main():
    parser = argparse.ArgumentParser(description="Aussortierte Pool-Videos neutral neu extrahieren")
    parser.add_argument("--tage", type=int, default=14)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true", help="nur analysieren, nichts schreiben")
    args = parser.parse_args()

    if speicher.daten_modus() != "supabase":
        print("[backfill] nur im Supabase-Modus sinnvoll")
        return 0

    seit = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=args.tage)).strftime("%Y-%m-%dT%H:%M:%SZ")
    zeilen = speicher._supabase_get("videos", {
        "select": "id,plattform,titel,kanal,views,caption,transkript,claim,gefunden_am,quelle",
        "gefunden_am": "gte." + seit,
        "claim->>verdict": "eq.aussortiert",
        "claim->>neutral_geprueft": "is.null",
        "order": "views.desc",
        "limit": str(args.limit),
    }) or []
    print("[backfill] %d aussortierte Videos seit %s" % (len(zeilen), seit))
    if not zeilen:
        return 0

    kategorien = themenwelt.pool_kategorien()
    nische = themenwelt.pool_nische_text()
    alte_claims = {z["id"]: dict(z.get("claim") or {}) for z in zeilen}
    mit_claim = analyse.extrahiere_claims(zeilen, themen_slugs=kategorien,
                                          nische=nische, neutral=True)
    print("[backfill] neutral extrahiert: %d/%d haben jetzt eine Aussage"
          % (len(mit_claim), len(zeilen)))
    for v in mit_claim:
        print("  + %-28s [%s] %s" % (v["id"], (v.get("claim") or {}).get("thema"),
                                     ((v.get("claim") or {}).get("aussage") or "")[:110]))
    if args.dry_run:
        return 0

    themenwelt.vernetze_pool_kandidaten(mit_claim)
    n = 0
    for v in mit_claim:
        # aktualisiert_am: die Kuration betrachtet auch spaeter extrahierte Claims
        felder = {"claim": v.get("claim"), "kategorie": v.get("kategorie"),
                  "aktualisiert_am": speicher.jetzt_iso()}
        if v.get("claim_embedding"):
            felder["claim_embedding"] = v["claim_embedding"]
        if speicher._supabase_patch_video(v["id"], felder):
            n += 1
    # Weiterhin aussortierte: Begruendung aktualisieren (jetzt neutral geprueft),
    # damit sie nicht bei jedem Backfill erneut Kosten verursachen.
    m = 0
    neu_ids = {v["id"] for v in mit_claim}
    for z in zeilen:
        if z["id"] in neu_ids:
            continue
        claim = z.get("claim") or {}
        if claim.get("verdict") == "aussortiert" and claim != alte_claims.get(z["id"]):
            claim = dict(claim)
            claim["neutral_geprueft"] = True
            if speicher._supabase_patch_video(z["id"], {"claim": claim}):
                m += 1
    print("[backfill] geschrieben: %d mit Aussage, %d weiterhin aussortiert markiert" % (n, m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
