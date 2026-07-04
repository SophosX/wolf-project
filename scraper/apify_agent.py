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
import datetime
import json
import os
import time
import urllib.parse
import urllib.request


def _jetzt_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

APIFY_BASIS = "https://api.apify.com/v2"
IG_ACTOR = os.environ.get("APIFY_IG_ACTOR", "apify~instagram-scraper")
TIMEOUT_S = 300

# Discovery: kuratierte grosse DE-Profile jenseits der Watchlist (verifizierte Handles)
DISCOVERY_DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "discovery_instagram.json")
DISCOVERY_LIMIT_PRO_PROFIL = int(os.environ.get("RADAR_IG_DISCOVERY_LIMIT", "8"))


def _lade_discovery():
    """Discovery-Profile laden; abschaltbar per RADAR_IG_DISCOVERY=0."""
    if (os.environ.get("RADAR_IG_DISCOVERY", "1").strip() or "1") == "0":
        return []
    try:
        with open(DISCOVERY_DATEI, encoding="utf-8") as f:
            return json.load(f).get("profile", [])
    except (OSError, ValueError):
        return []


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


def _item_zu_kandidat(it, handle_zu_name, quelle):
    """Apify-Post-Item -> Kandidaten-Dict im Kontrakt-Format (None wenn unbrauchbar)."""
    kurz = it.get("shortCode") or it.get("shortcode")
    if not kurz:
        return None
    handle = (it.get("ownerUsername") or "").lower()
    caption = it.get("caption") or ""
    return {
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
        # transient (wird vor dem Speichern entfernt): kurzlebige CDN-URL
        # des Reels — Beschaffungsweg für die Audio-Transkription
        "apify_video_url": _video_url_aus_item(it),
        "gefunden_am": _jetzt_iso(),
        "quelle": quelle,
        "status": "inbox",
        "score": 0,
        "scores": {},
        "claim": None,
        "skripte": [],
        "feedback": [],
    }


def _sammle_profile(profil_handles, handle_zu_name, limit, quelle, kandidaten, fehler,
                    abdeckungs_check=True):
    """Einen Satz IG-Profile über den Apify-Actor einsammeln (ein Actor-Lauf)."""
    if not profil_handles:
        return
    urls = ["https://www.instagram.com/%s/" % h for h in profil_handles]
    try:
        items = _run_sync(IG_ACTOR, {
            "directUrls": urls,
            "resultsType": "posts",
            "resultsLimit": limit,
            "addParentData": True,
        })
    except Exception as e:
        fehler.append("apify instagram (%s): Lauf fehlgeschlagen: %s" % (quelle, e))
        return

    gesehene_handles = set()
    for it in items or []:
        try:
            if it.get("error"):
                # Fehler-Items tragen kein username-Feld — Profil aus der URL ableiten
                quelle_url = it.get("url") or it.get("inputUrl") or ""
                wer = it.get("username") or quelle_url.rstrip("/").split("/")[-1] or "?"
                fehler.append("apify instagram @%s: %s" % (wer, it["error"]))
                continue
            kandidat = _item_zu_kandidat(it, handle_zu_name, quelle)
            if kandidat is None:
                continue
            handle = (it.get("ownerUsername") or "").lower()
            if handle:
                gesehene_handles.add(handle)
            kandidaten.append(kandidat)
        except Exception as e:
            fehler.append("apify instagram item: %s" % e)

    if abdeckungs_check:
        # Angefragte Profile, die weder Posts noch Fehler-Item lieferten
        for handle in profil_handles:
            h = handle.lower()
            if h not in gesehene_handles and not any(("@%s" % h) in f for f in fehler):
                fehler.append("apify instagram @%s (%s): 0 Posts geliefert — Handle pruefen"
                              % (h, handle_zu_name.get(h, "?")))


def sammle_instagram(watchlist, limit_pro_profil=15):
    """
    Instagram über den Apify-Scraper einsammeln:
    (a) Watchlist-Profile (voll, mit Abdeckungs-Check),
    (b) Discovery-Profile aus discovery_instagram.json (kleineres Limit).
    Rückgabe wie die anderen Agenten: {"kandidaten": [...], "fehler": [...]}
    """
    kandidaten, fehler = [], []
    # watchlist kann Liste (lauf.py) oder {"eintraege": [...]} (Rohdatei) sein
    eintraege = watchlist if isinstance(watchlist, list) else watchlist.get("eintraege", [])
    profile = [e for e in eintraege if e.get("instagram")]
    handle_zu_name = {e["instagram"].lower(): e["name"] for e in profile}

    _sammle_profile([e["instagram"] for e in profile], handle_zu_name,
                    limit_pro_profil, "watchlist", kandidaten, fehler)

    discovery = _lade_discovery()
    if discovery:
        watchlist_handles = set(handle_zu_name)
        disco = [p for p in discovery
                 if p.get("handle") and p["handle"].lower() not in watchlist_handles]
        for p in disco:
            handle_zu_name.setdefault(p["handle"].lower(), p.get("name", p["handle"]))
        _sammle_profile([p["handle"] for p in disco], handle_zu_name,
                        DISCOVERY_LIMIT_PRO_PROFIL, "discovery", kandidaten, fehler)
        print("[apify] Discovery: %d Profile angefragt, gesamt %d Kandidaten"
              % (len(disco), len(kandidaten)))

    return {"kandidaten": kandidaten, "fehler": fehler}


def _video_url_aus_item(it):
    """videoUrl eines Apify-Items — bei Sidecar-Posts (Carousel) aus dem ersten
    Video-Kind. None, wenn der Post schlicht kein Video ist (reines Foto)."""
    if it.get("videoUrl"):
        return it["videoUrl"]
    for kind in it.get("childPosts") or []:
        if kind.get("videoUrl"):
            return kind["videoUrl"]
    return None


def hole_video_urls(post_urls, fehler):
    """
    Für bestehende Instagram-Posts frische CDN-Video-URLs nachladen (Backfill der
    Audio-Transkription: die beim Fund gelieferte URL ist längst abgelaufen).
    Rückgabe: {shortcode: videoUrl} — Posts ohne Video fehlen bewusst.
    """
    if not post_urls or not verfuegbar():
        return {}
    urls = {}
    for versuch in (1, 2):  # Apify liefert nach Kaltstart vereinzelt leer — einmal wiederholen
        try:
            items = _run_sync(IG_ACTOR, {
                "directUrls": list(post_urls),
                "resultsType": "posts",
                "resultsLimit": 1,
            })
        except Exception as e:
            if versuch == 2:
                fehler.append("apify instagram video-urls: %s" % e)
            continue
        for it in items or []:
            kurz = it.get("shortCode") or it.get("shortcode")
            url = _video_url_aus_item(it)
            if kurz and url:
                urls[kurz] = url
        if urls or items:
            break
        time.sleep(5)
    return urls
