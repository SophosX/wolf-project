# -*- coding: utf-8 -*-
"""
Wolf Radar — Apify-Anbindung für Instagram (und optional TikTok als Fallback).

Warum Apify (User-Entscheidung): Instagram drosselt anonymes Scraping nach wenigen
Profilen (HTTP 401). Apifys gewartete Scraper laufen zuverlässig und legal auf
öffentliche Profile. Kosten: ~1-3 $/1000 Posts, bei 5 Watchlist-Profilen × 6 Läufen/Tag
grob 5-10 $/Monat.

Aktivierung: ENV APIFY_TOKEN setzen — lauf.py nutzt dann automatisch diesen Agenten
für Instagram statt gallery-dl. Ohne Token: gallery-dl-Best-Effort wie bisher.
"""
import json
import os
import time
import urllib.parse
import urllib.request

APIFY_BASIS = "https://api.apify.com/v2"
IG_ACTOR = os.environ.get("APIFY_IG_ACTOR", "apify~instagram-scraper")
TIMEOUT_S = 300


def token():
    return os.environ.get("APIFY_TOKEN") or None


def verfuegbar():
    return token() is not None


def _run_sync(actor, eingabe):
    """Actor synchron ausführen, Dataset-Items zurückgeben."""
    url = (APIFY_BASIS + "/acts/" + actor + "/run-sync-get-dataset-items?token="
           + urllib.parse.quote(token()) + "&timeout=" + str(TIMEOUT_S))
    anfrage = urllib.request.Request(
        url,
        data=json.dumps(eingabe).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S + 30) as r:
        return json.load(r)


def _iso(zeit):
    return zeit if zeit else None


def sammle_instagram(watchlist, limit_pro_profil=15):
    """
    Watchlist-Instagram-Profile über den Apify-Instagram-Scraper einsammeln.
    Rückgabe wie die anderen Agenten: {"kandidaten": [...], "fehler": [...]}
    Kandidaten im Kontrakt-Format (plattform=instagram, quelle=watchlist).
    """
    kandidaten, fehler = [], []
    # watchlist kann Liste (lauf.py) oder {"eintraege": [...]} (Rohdatei) sein
    eintraege = watchlist if isinstance(watchlist, list) else watchlist.get("eintraege", [])
    profile = [e for e in eintraege if e.get("instagram")]
    if not profile:
        return {"kandidaten": [], "fehler": []}

    urls = ["https://www.instagram.com/%s/" % e["instagram"] for e in profile]
    handle_zu_name = {e["instagram"].lower(): e["name"] for e in profile}
    try:
        items = _run_sync(IG_ACTOR, {
            "directUrls": urls,
            "resultsType": "posts",
            "resultsLimit": limit_pro_profil,
            "addParentData": True,
        })
    except Exception as e:
        fehler.append("apify instagram: Lauf fehlgeschlagen: %s" % e)
        return {"kandidaten": [], "fehler": fehler}

    for it in items or []:
        try:
            if it.get("error"):
                fehler.append("apify instagram @%s: %s" % (it.get("username", "?"), it["error"]))
                continue
            kurz = it.get("shortCode") or it.get("shortcode")
            if not kurz:
                continue
            handle = (it.get("ownerUsername") or "").lower()
            caption = it.get("caption") or ""
            kandidaten.append({
                "id": "instagram:%s" % kurz,
                "plattform": "instagram",
                "video_id": kurz,
                "url": it.get("url") or ("https://www.instagram.com/p/%s/" % kurz),
                "titel": caption.split("\n")[0][:120] if caption else "(ohne Caption)",
                "kanal": handle_zu_name.get(handle, it.get("ownerFullName") or handle),
                "kanal_id": "@" + handle if handle else None,
                "kanal_follower": (it.get("owner") or {}).get("followersCount"),
                "veroeffentlicht": _iso(it.get("timestamp")),
                "views": it.get("videoPlayCount") or it.get("videoViewCount") or 0,
                "likes": it.get("likesCount") or 0,
                "kommentare": it.get("commentsCount") or 0,
                "dauer_s": int(it["videoDuration"]) if it.get("videoDuration") else None,
                "thumbnail_url": it.get("displayUrl"),
                "caption": caption[:3000],
                "transkript": None,
                "quelle": "watchlist",
                "status": "inbox",
                "score": 0,
                "scores": {},
                "claim": None,
                "skripte": [],
                "feedback": [],
            })
        except Exception as e:
            fehler.append("apify instagram item: %s" % e)
        time.sleep(0)  # kein Rate-Limit nötig — Apify liefert gesammelt

    return {"kandidaten": kandidaten, "fehler": fehler}
