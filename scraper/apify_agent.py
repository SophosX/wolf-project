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
import re
import time
import urllib.parse
import urllib.request


def _jetzt_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

APIFY_BASIS = "https://api.apify.com/v2"
IG_ACTOR = os.environ.get("APIFY_IG_ACTOR", "apify~instagram-scraper")
# YouTube-Transkripte: liefert die Untertitel-Spur, mit Whisper-KI-Fallback fuer
# caption-lose Videos. Umgeht YouTubes Bot-Sperre gegen die Server-IP (an der
# yt-dlp scheitert), da Apify ueber eigene Infrastruktur/Proxies laedt.
YT_ACTOR = os.environ.get("APIFY_YT_ACTOR", "codepoetry~youtube-transcript-ai-scraper")
# YouTube-SUCHE via Apify (ersetzt die quota-limitierte YouTube Data API):
# Apifys offizieller, gewarteter Scraper — kein Tageslimit, pay-per-result
# (~5 $/1000 Videos). Sortiert nach Datum, gefiltert auf frische Uploads, damit
# der Radar wirklich alle paar Stunden NEUE Videos findet.
YT_SUCHE_ACTOR = os.environ.get("APIFY_YT_SUCHE_ACTOR", "streamers~youtube-scraper")
# Kosten-/Umfang-Knöpfe: maxResults (normale Videos) + maxResultsShorts (Shorts)
# je Suchbegriff, Datumsfilter (hour/today/week/month/year).
# Default today = frisch & kostengünstig (die 4h-Läufe decken den Tag ab);
# week = maximal umfangreich, aber ~5× Kosten (re-scrapt die Wochen-Backlog je Lauf).
YT_SUCHE_MAX_RESULTS = int(os.environ.get("RADAR_YT_APIFY_MAX_RESULTS", "10"))
YT_SUCHE_MAX_SHORTS = int(os.environ.get("RADAR_YT_APIFY_MAX_SHORTS",
                                         str(YT_SUCHE_MAX_RESULTS)))
YT_SUCHE_DATEFILTER = os.environ.get("RADAR_YT_APIFY_DATEFILTER", "today").strip() or "today"
# TikTok-Keyword-Suche (Apify clockworks) + Instagram-Hashtag-Suche — geben
# TikTok/IG dieselbe breite Abdeckung wie die YouTube-Suche (nicht nur Watchlist).
TIKTOK_SUCHE_ACTOR = os.environ.get("APIFY_TIKTOK_ACTOR", "clockworks~tiktok-scraper")
TIKTOK_SUCHE_MAX = int(os.environ.get("RADAR_TIKTOK_APIFY_MAX", "8"))      # Videos je Suchbegriff
IG_HASHTAG_MAX = int(os.environ.get("RADAR_IG_HASHTAG_MAX", "10"))        # Posts je Hashtag
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


def _run_sync(actor, eingabe, timeout=None):
    """Actor synchron ausführen, Dataset-Items zurückgeben."""
    t = int(timeout or TIMEOUT_S)
    url = (APIFY_BASIS + "/acts/" + actor + "/run-sync-get-dataset-items?token="
           + urllib.parse.quote(token()) + "&timeout=" + str(t))
    anfrage = urllib.request.Request(
        url,
        data=json.dumps(eingabe).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(anfrage, timeout=t + 30) as r:
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
    """Einen Satz IG-Profile über den Apify-Actor einsammeln.
    Profile ohne Ergebnis werden EINMAL wiederholt — der Actor liefert nach
    Kaltstarts vereinzelt transient leere Antworten (no_items)."""
    if not profil_handles:
        return

    def _abrufen(handles):
        return _run_sync(IG_ACTOR, {
            "directUrls": ["https://www.instagram.com/%s/" % h for h in handles],
            "resultsType": "posts",
            "resultsLimit": limit,
            "addParentData": True,
        })

    gesehene_handles = set()
    harte_fehler = set()  # Profile mit echtem Fehler-Item (not_found etc.) — kein Retry

    def _verarbeiten(items, fehler_sammeln):
        for it in items or []:
            try:
                if it.get("error"):
                    quelle_url = it.get("url") or it.get("inputUrl") or ""
                    wer = (it.get("username") or quelle_url.rstrip("/").split("/")[-1] or "?").lower()
                    harte_fehler.add(wer)
                    if fehler_sammeln:
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

    try:
        _verarbeiten(_abrufen(profil_handles), fehler_sammeln=False)
    except Exception as e:
        fehler.append("apify instagram (%s): Lauf fehlgeschlagen: %s" % (quelle, e))
        return

    # Ein Retry NUR für still-leere Profile (transientes no_items)
    fehlend = [h for h in profil_handles
               if h.lower() not in gesehene_handles and h.lower() not in harte_fehler]
    if fehlend:
        time.sleep(5)
        try:
            _verarbeiten(_abrufen(fehlend), fehler_sammeln=True)
        except Exception as e:
            fehler.append("apify instagram (%s) Retry: %s" % (quelle, e))

    if abdeckungs_check:
        # Angefragte Profile, die auch nach dem Retry nichts lieferten
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
    such_protokoll = []
    # watchlist kann Liste (lauf.py) oder {"eintraege": [...]} (Rohdatei) sein
    eintraege = watchlist if isinstance(watchlist, list) else watchlist.get("eintraege", [])
    profile = [e for e in eintraege if e.get("instagram")]
    handle_zu_name = {e["instagram"].lower(): e["name"] for e in profile}

    # (0) Breite Hashtag-Suche via Apify (analog YouTube/TikTok): Funde beliebiger Creators
    if (os.environ.get("RADAR_IG_HASHTAG_SUCHE", "1").strip() or "1") != "0":
        try:
            from mythen_katalog import SOCIAL_HASHTAGS
            hkand, such_protokoll = sammle_instagram_hashtags(SOCIAL_HASHTAGS, fehler)
            kandidaten.extend(hkand)
        except Exception as e:
            fehler.append("apify instagram-hashtags: %s" % e)

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

    return {"kandidaten": kandidaten, "fehler": fehler, "such_protokoll": such_protokoll}


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


# Miss-Liste: Videos, die Apify (auch mit KI) NICHT transkribieren konnte
# (Musik-only/Shorts/entfernt). Nach RADAR_YT_MISS_MAX Fehlversuchen nicht mehr
# anfragen -> verhindert wiederkehrende KI-Kosten im taeglichen Backfill.
_YT_MISS_DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "daten", ".yt_apify_misses.json")
YT_MISS_MAX = int(os.environ.get("RADAR_YT_MISS_MAX", "2"))


def _lade_misses():
    try:
        with open(_YT_MISS_DATEI, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _speichere_misses(misses):
    try:
        os.makedirs(os.path.dirname(_YT_MISS_DATEI), exist_ok=True)
        with open(_YT_MISS_DATEI, "w", encoding="utf-8") as f:
            json.dump(misses, f)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# YouTube-SUCHE via Apify — ersetzt youtube_agent.claim_suche (Data-API-Quota)
# ---------------------------------------------------------------------------

_YT_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/watch/)([A-Za-z0-9_-]{11})")
_YT_KANAL_RE = re.compile(r"/channel/(UC[A-Za-z0-9_-]{20,})")
_REL_RE = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year|"
                     r"sekunde|minute|stunde|tag|woche|monat|jahr)", re.I)
_REL_TAGE = {"second": 0, "sekunde": 0, "minute": 0, "hour": 0, "stunde": 0,
             "day": 1, "tag": 1, "week": 7, "woche": 7, "month": 30, "monat": 30,
             "year": 365, "jahr": 365}


def _yt_video_id(url):
    if not url:
        return None
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def _yt_kanal_id(kanal_url):
    if not kanal_url:
        return None
    m = _YT_KANAL_RE.search(kanal_url)
    if m:
        return m.group(1)
    # Handle-URL (…/@handle) — Handle als Ersatz, reicht für die Anzeige
    teil = kanal_url.rstrip("/").split("/")[-1]
    return teil or None


def _apify_datum_zu_iso(wert):
    """Apify liefert 'date' mal ISO ('2026-07-05'), mal relativ ('2 days ago').
    Beides zu einem ISO-Zeitstempel machen; None wenn unparsebar (Velocity fällt
    dann sauber auf den 14-Tage-Default zurück)."""
    if not wert:
        return None
    s = str(wert).strip()
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass
    m = _REL_RE.search(s)
    if m:
        tage = int(m.group(1)) * _REL_TAGE.get(m.group(2).lower(), 0)
        dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=tage)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _dauer_mmss_zu_sekunden(wert):
    """'29:54' oder '1:02:03' -> Sekunden. None wenn leer/Live."""
    if not wert:
        return None
    if isinstance(wert, (int, float)):
        return int(wert)
    teile = str(wert).strip().split(":")
    if not all(t.isdigit() for t in teile) or not teile:
        return None
    sek = 0
    for t in teile:
        sek = sek * 60 + int(t)
    return sek


def _ganzzahl(wert):
    """Views/Likes können Zahl, '1.2M'-String oder None sein -> int oder None."""
    if wert is None:
        return None
    if isinstance(wert, (int, float)):
        return int(wert)
    s = str(wert).strip().replace(",", "").replace(".", "")
    return int(s) if s.isdigit() else None


def _yt_such_item_zu_kandidat(it, quelle_query):
    """Apify-Such-Item -> Kandidaten-Dict im Kontrakt-Format (None wenn unbrauchbar).
    Feldnamen defensiv gemappt (Actor-Varianten)."""
    vid = it.get("id") or _yt_video_id(it.get("url"))
    if not vid or len(str(vid)) != 11:
        return None
    views = _ganzzahl(it.get("viewCount") if it.get("viewCount") is not None
                      else it.get("viewsCount"))
    # channelId ist die kanonische UC-ID (fuer Watchlist-Abgleich); sonst aus der
    # channelUrl (/channel/UC… oder @handle) ableiten.
    kanal_id = it.get("channelId") or _yt_kanal_id(it.get("channelUrl"))
    return {
        "id": "youtube:" + vid,
        "plattform": "youtube",
        "video_id": vid,
        "url": it.get("url") or ("https://www.youtube.com/watch?v=%s" % vid),
        "titel": it.get("title") or it.get("titel"),
        "kanal": it.get("channelName") or it.get("channelTitle") or it.get("channelUsername"),
        "kanal_id": kanal_id,
        "kanal_follower": _ganzzahl(it.get("numberOfSubscribers")),
        "veroeffentlicht": _apify_datum_zu_iso(
            it.get("date") or it.get("uploadDate") or it.get("publishedTime")),
        "views": views or 0,
        "likes": _ganzzahl(it.get("likes")),
        "kommentare": _ganzzahl(it.get("commentsCount")),
        "dauer_s": _dauer_mmss_zu_sekunden(it.get("duration")),
        "thumbnail_url": it.get("thumbnailUrl") or it.get("thumbnail"),
        "caption": (it.get("text") or it.get("description") or "")[:3000],
        "transkript": None,
        "gefunden_am": _jetzt_iso(),
        "quelle": "claim_suche",
        "quelle_query": quelle_query,   # welcher Suchbegriff das Video zutage förderte
        "status": "inbox",
        "score": 0,
        "scores": {},
        "claim": None,
        "skripte": [],
        "feedback": [],
    }


# Suchbegriffe pro Actor-Lauf. Der Actor taggt jedes Item mit `input` (=Query),
# daher ein Lauf für viele Begriffe (effizient) statt einer pro Begriff. In Batches,
# damit ein einzelner run-sync nicht ins Timeout läuft.
YT_SUCHE_BATCH = int(os.environ.get("RADAR_YT_APIFY_BATCH", "10"))
YT_SUCHE_TIMEOUT_S = int(os.environ.get("RADAR_YT_APIFY_TIMEOUT_S", "540"))


def sammle_youtube_suche(queries, fehler):
    """
    YouTube-Claim-Suche über den Apify-Scraper (kein Data-API-Quota-Limit mehr →
    ALLE Begriffe pro Lauf). Der Actor liefert jedes Item mit `input` (Suchbegriff),
    daher ein Lauf pro Batch statt pro Begriff. Ergebnisse werden je Begriff
    protokolliert (Transparenz-Anforderung: "was hat jede Suche ergeben").

    Rückgabe: (kandidaten, protokoll)
      protokoll: [{"query": q, "gefunden": n, "fehler": bool}] je Suchbegriff,
                 in der Reihenfolge der Eingabe.
    """
    kandidaten = []
    queries = [q for q in queries if q]
    # Protokoll vorbelegen, damit JEDER Begriff auftaucht (auch 0-Treffer/Fehler)
    protokoll = {q: {"query": q, "gefunden": 0, "fehler": False} for q in queries}
    if not verfuegbar():
        fehler.append("apify youtube-suche: kein APIFY_TOKEN gesetzt")
        return kandidaten, list(protokoll.values())

    def _query_zu_kand(it):
        # `input` ist der Suchbegriff, dem dieses Item entstammt
        return it.get("input")

    for i in range(0, len(queries), YT_SUCHE_BATCH):
        batch = queries[i:i + YT_SUCHE_BATCH]
        eingabe = {
            "searchQueries": batch,
            "maxResults": YT_SUCHE_MAX_RESULTS,
            "maxResultsShorts": YT_SUCHE_MAX_SHORTS,
            "sortingOrder": "date",       # neueste zuerst
            "dateFilter": YT_SUCHE_DATEFILTER,
        }
        try:
            items = _run_sync(YT_SUCHE_ACTOR, eingabe, timeout=YT_SUCHE_TIMEOUT_S)
        except Exception as e:
            fehler.append("apify youtube-suche (Batch %d: %s): %s"
                          % (i // YT_SUCHE_BATCH + 1, ", ".join(batch), e))
            for q in batch:
                protokoll[q]["fehler"] = True
            continue
        for it in items or []:
            q = _query_zu_kand(it)
            eintrag = protokoll.get(q)
            if it.get("error"):          # z. B. NO_VIDEOS für diesen Begriff
                continue
            try:
                kand = _yt_such_item_zu_kandidat(it, q)
            except Exception as e:
                fehler.append("apify youtube-such-item: %s" % e)
                continue
            if kand is None:
                continue
            kandidaten.append(kand)
            if eintrag is not None:
                eintrag["gefunden"] += 1

    print("[apify] YouTube-Suche: %d Begriffe in %d Batch(es), %d Roh-Treffer"
          % (len(queries), (len(queries) + YT_SUCHE_BATCH - 1) // max(1, YT_SUCHE_BATCH),
             len(kandidaten)))
    return kandidaten, list(protokoll.values())


# ---------------------------------------------------------------------------
# TikTok-KEYWORD-Suche via Apify (clockworks) — nicht mehr nur Watchlist-Profile
# ---------------------------------------------------------------------------

def _tiktok_such_item_zu_kandidat(it):
    """clockworks-TikTok-Item -> Kandidaten-Dict im Kontrakt-Format."""
    vid = str(it.get("id") or "")
    if not vid:
        return None
    autor = it.get("authorMeta") or {}
    vmeta = it.get("videoMeta") or {}
    text = it.get("text") or ""
    handle = autor.get("name")
    return {
        "id": "tiktok:" + vid,
        "plattform": "tiktok",
        "video_id": vid,
        "url": it.get("webVideoUrl") or (
            "https://www.tiktok.com/@%s/video/%s" % (handle or "", vid)),
        "titel": (text.split("\n")[0][:120] if text else None) or ("TikTok von @%s" % (handle or "?")),
        "kanal": autor.get("nickName") or handle,
        "kanal_id": ("@" + handle) if handle else None,
        "kanal_follower": _ganzzahl(autor.get("fans")),
        "veroeffentlicht": _apify_datum_zu_iso(it.get("createTimeISO")),
        "views": _ganzzahl(it.get("playCount")) or 0,
        "likes": _ganzzahl(it.get("diggCount")),
        "kommentare": _ganzzahl(it.get("commentCount")),
        "dauer_s": _ganzzahl(vmeta.get("duration")),
        "thumbnail_url": vmeta.get("coverUrl") or vmeta.get("originalCoverUrl"),
        "caption": text[:3000],
        "transkript": None,
        "gefunden_am": _jetzt_iso(),
        "quelle": "claim_suche",
        "quelle_query": it.get("searchQuery"),
        "status": "inbox",
        "score": 0,
        "scores": {},
        "claim": None,
        "skripte": [],
        "feedback": [],
    }


def sammle_tiktok_suche(queries, fehler):
    """
    TikTok-Keyword-Suche über den Apify-Actor (clockworks). Findet Ernährungs-
    Falschinfos von BELIEBIGEN Creators, nicht nur den Watchlist-Profilen.
    Rückgabe: (kandidaten, protokoll[{query, gefunden, fehler}]).
    """
    kandidaten = []
    queries = [q for q in queries if q]
    protokoll = {q: {"query": q, "gefunden": 0, "fehler": False} for q in queries}
    if not verfuegbar() or not queries:
        if not verfuegbar():
            fehler.append("apify tiktok-suche: kein APIFY_TOKEN")
        return kandidaten, list(protokoll.values())

    # Ein Lauf für alle Begriffe; jedes Item trägt searchQuery = Herkunfts-Begriff.
    eingabe = {
        "searchQueries": queries,
        "resultsPerPage": TIKTOK_SUCHE_MAX,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
        "shouldDownloadSubtitles": False,
        "proxyCountryCode": "DE",
    }
    try:
        items = _run_sync(TIKTOK_SUCHE_ACTOR, eingabe, timeout=540)
    except Exception as e:
        fehler.append("apify tiktok-suche: %s" % e)
        for q in queries:
            protokoll[q]["fehler"] = True
        return kandidaten, list(protokoll.values())

    for it in items or []:
        try:
            kand = _tiktok_such_item_zu_kandidat(it)
        except Exception as e:
            fehler.append("apify tiktok-such-item: %s" % e)
            continue
        if kand is None:
            continue
        kandidaten.append(kand)
        eintrag = protokoll.get(it.get("searchQuery"))
        if eintrag is not None:
            eintrag["gefunden"] += 1
    print("[apify] TikTok-Suche: %d Begriffe, %d Roh-Treffer"
          % (len(queries), len(kandidaten)))
    return kandidaten, list(protokoll.values())


def sammle_instagram_hashtags(hashtags, fehler):
    """
    Instagram-HASHTAG-Suche über den bestehenden IG-Actor (Tag-Seiten-URLs).
    Ergänzt die Profil-basierte Suche um Funde beliebiger Creators.
    Rückgabe: (kandidaten, protokoll[{query, gefunden, fehler}]).
    """
    kandidaten = []
    tags = [h.lstrip("#") for h in (hashtags or []) if h]
    protokoll = {t: {"query": "#" + t, "gefunden": 0, "fehler": False} for t in tags}
    if not verfuegbar() or not tags:
        return kandidaten, list(protokoll.values())

    for tag in tags:
        try:
            items = _run_sync(IG_ACTOR, {
                "directUrls": ["https://www.instagram.com/explore/tags/%s/" % tag],
                "resultsType": "posts",
                "resultsLimit": IG_HASHTAG_MAX,
                "addParentData": True,
            })
        except Exception as e:
            fehler.append("apify instagram-hashtag #%s: %s" % (tag, e))
            protokoll[tag]["fehler"] = True
            continue
        for it in items or []:
            if it.get("error"):
                continue
            kand = _item_zu_kandidat(it, {}, "claim_suche")
            if kand is None:
                continue
            kand["quelle_query"] = "#" + tag
            kandidaten.append(kand)
            protokoll[tag]["gefunden"] += 1
    print("[apify] Instagram-Hashtags: %d Tags, %d Roh-Treffer"
          % (len(tags), len(kandidaten)))
    return kandidaten, list(protokoll.values())


def hole_youtube_transkripte(video_ids, fehler, sprache="de", max_zeichen=8000):
    """
    Transkripte fuer YouTube-Videos ueber Apify holen — EIN Call fuer ALLE IDs.
    Der Actor liefert YouTubes Untertitel-Spur; fehlen Captions, greift sein
    KI-Fallback (Whisper). Umgeht die Bot-Sperre, an der yt-dlp von der Server-IP
    scheitert ("Sign in to confirm you're not a bot").
    Rueckgabe: {video_id: transkript_text}. Leeres Dict, wenn kein Token/Fehler.

    Kosten-Guards per ENV:
      RADAR_YT_AI_FALLBACK=0   -> KI-Fallback aus (nur Captions, ~0,0005 $/Video)
      RADAR_YT_AI_MINUTEN      -> harte Obergrenze KI-Minuten pro Lauf (Default 60)
      RADAR_YT_AI_SKIP_MIN     -> KI fuer Videos laenger als N Min ueberspringen (Default 60)
      RADAR_YT_MISS_MAX        -> nach N Fehlversuchen Video nicht mehr anfragen (Default 2)
    """
    alle = [v for v in dict.fromkeys(video_ids or []) if v]  # dedupe, Reihenfolge erhalten
    if not alle or not verfuegbar():
        return {}
    # Dauer-Nieten aussparen (spart wiederkehrende KI-Kosten im Backfill)
    misses = _lade_misses()
    ids = [v for v in alle if int(misses.get(v, 0)) < YT_MISS_MAX]
    if not ids:
        return {}
    ai_an = (os.environ.get("RADAR_YT_AI_FALLBACK", "1").strip() or "1") != "0"
    eingabe = {
        "startUrls": [{"url": "https://www.youtube.com/watch?v=%s" % v} for v in ids],
        "languages": [sprache],
        "enableAiFallback": ai_an,
        "forceWhisperLanguage": sprache,
        "outputFormats": ["text"],
        "subType": "both",
        "maxResults": len(ids),
        "maxAiMinutes": int(os.environ.get("RADAR_YT_AI_MINUTEN", "60")),
        "skipAiFallbackIfLongerThan": int(os.environ.get("RADAR_YT_AI_SKIP_MIN", "60")),
    }
    try:
        items = _run_sync(YT_ACTOR, eingabe)
    except Exception as e:
        fehler.append("apify youtube transkripte: %s" % e)
        return {}
    ergebnis = {}
    for it in items or []:
        try:
            md = it.get("metadata") or {}
            vid = md.get("id") or it.get("video_id") or it.get("id")
            txt = (it.get("transcript_text") or it.get("transcript_llm") or "").strip()
            if vid and txt:
                ergebnis[vid] = txt[:max_zeichen]
        except Exception as e:
            fehler.append("apify youtube transkript item: %s" % e)
    # Miss-Zaehler pflegen: Treffer loeschen, Nieten hochzaehlen
    geaendert = False
    for v in ids:
        if v in ergebnis:
            if misses.pop(v, None) is not None:
                geaendert = True
        else:
            misses[v] = int(misses.get(v, 0)) + 1
            geaendert = True
    if geaendert:
        _speichere_misses(misses)
    return ergebnis
