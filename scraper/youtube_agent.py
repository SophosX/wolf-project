# -*- coding: utf-8 -*-
"""
Wolf Radar — YouTube-Agent (Data API v3)

a) Claim-Suche: rotierende deutsche Suchqueries aus mythen_katalog.SUCHQUERIES
   (search.list mit relevanceLanguage=de, regionCode=DE, publishedAfter=60 Tage,
    je Query einmal order=viewCount und einmal order=relevance, maxResults=10)
   -> videos.list fuer Statistiken -> rohe Kandidaten-Dicts nach Kontrakt.
   QUOTA: search.list kostet 100 Einheiten -> hartes Budget MAX_SEARCH_CALLS,
   Queries rotieren pro Lauf (4h-Slot), dedupe frueh.

b) Watchlist: channels.list -> Uploads-Playlist -> playlistItems (1 Einheit,
   guenstig) der letzten 30 Tage.

c) Transkript-Versuch: deutsche Auto-Untertitel via yt-dlp
   (--write-auto-subs --skip-download) fuer Kandidaten mit views > 10000,
   VTT zu Fliesstext bereinigt (Rolling-Caption-Dedupe), max 8000 Zeichen.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone

import requests

from mythen_katalog import SUCHQUERIES

API_BASIS = "https://www.googleapis.com/youtube/v3"

# Quota-Budget: search.list = 100 Einheiten. 16 Calls/Lauf * 6 Laeufe/Tag
# = 9600 Einheiten < 10000 Tageslimit (videos/channels/playlistItems ~ 1).
MAX_SEARCH_CALLS = int(os.environ.get("RADAR_MAX_SEARCH_CALLS", "50"))
QUERIES_PRO_LAUF = int(os.environ.get("RADAR_QUERIES_PRO_LAUF", "8"))

CLAIM_SUCHE_TAGE = 60      # publishedAfter fuer die Claim-Suche
WATCHLIST_TAGE = 30        # Zeitfenster fuer Watchlist-Uploads
TRANSKRIPT_MIN_VIEWS = 10000
TRANSKRIPT_MAX_ZEICHEN = 8000
TRANSKRIPT_MAX_VIDEOS = int(os.environ.get("RADAR_TRANSKRIPT_MAX", "15"))


def _api_key():
    key = os.environ.get("YT_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YT_API_KEY fehlt in der Umgebung")
    return key


def _api_get(endpoint, params, fehler):
    """GET gegen die Data API; Fehler werden gesammelt statt geworfen."""
    params = dict(params)
    params["key"] = _api_key()
    try:
        r = requests.get(API_BASIS + "/" + endpoint, params=params, timeout=30)
        if r.status_code >= 400:
            kurz = r.text[:300].replace("\n", " ")
            fehler.append("youtube %s: HTTP %s %s" % (endpoint, r.status_code, kurz))
            return None
        return r.json()
    except requests.RequestException as e:
        fehler.append("youtube %s: %s" % (endpoint, e))
        return None


def _iso_vor_tagen(tage):
    t = datetime.now(timezone.utc) - timedelta(days=tage)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _jetzt_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dauer_zu_sekunden(iso_dauer):
    """ISO-8601-Dauer (PT1H2M3S) -> Sekunden."""
    if not iso_dauer:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_dauer)
    if not m:
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _bestes_thumbnail(thumbs):
    if not thumbs:
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbs and thumbs[key].get("url"):
            return thumbs[key]["url"]
    return None


def _roh_kandidat(video_id, snippet, statistik, content, quelle, follower=None):
    """Rohes video-Dict nach Kontrakt (ohne claim/score-Analyse)."""
    return {
        "id": "youtube:" + video_id,
        "plattform": "youtube",
        "video_id": video_id,
        "url": "https://www.youtube.com/watch?v=" + video_id,
        "titel": snippet.get("title"),
        "kanal": snippet.get("channelTitle"),
        "kanal_id": snippet.get("channelId"),
        "kanal_follower": follower,
        "veroeffentlicht": snippet.get("publishedAt"),
        "views": int(statistik.get("viewCount", 0) or 0),
        "likes": int(statistik["likeCount"]) if statistik.get("likeCount") else None,
        "kommentare": int(statistik["commentCount"]) if statistik.get("commentCount") else None,
        "dauer_s": _dauer_zu_sekunden(content.get("duration")) if content else None,
        "thumbnail_url": _bestes_thumbnail(snippet.get("thumbnails")),
        "caption": snippet.get("description") or "",
        "transkript": None,
        "gefunden_am": _jetzt_iso(),
        "quelle": quelle,
        "status": "inbox",
        "score": 0,
        "scores": {},
        "claim": None,
        "skripte": [],
        "feedback": [],
    }


def _videos_details(video_ids, fehler):
    """videos.list in 50er-Batches: snippet + statistics + contentDetails."""
    details = {}
    ids = [v for v in video_ids if v]
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        antwort = _api_get("videos", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
            "maxResults": 50,
        }, fehler)
        if not antwort:
            continue
        for item in antwort.get("items", []):
            details[item["id"]] = item
    return details


def _kanal_follower(kanal_ids, fehler):
    """channels.list in 50er-Batches -> {kanal_id: abonnenten oder None}."""
    follower = {}
    ids = sorted(set(k for k in kanal_ids if k))
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        antwort = _api_get("channels", {
            "part": "statistics",
            "id": ",".join(batch),
            "maxResults": 50,
        }, fehler)
        if not antwort:
            continue
        for item in antwort.get("items", []):
            stats = item.get("statistics", {})
            if stats.get("hiddenSubscriberCount"):
                follower[item["id"]] = None
            else:
                follower[item["id"]] = int(stats.get("subscriberCount", 0) or 0)
    return follower


def _query_rotation(alle_queries, pro_lauf):
    """
    Deterministische Rotation: pro 4h-Slot ein anderes Fenster ueber die
    Query-Liste, damit ueber den Tag alle Queries drankommen, ohne das
    Quota-Budget eines Einzellaufs zu sprengen.
    """
    if pro_lauf >= len(alle_queries):
        return list(alle_queries)
    slot = int(time.time() // (4 * 3600))
    start = (slot * pro_lauf) % len(alle_queries)
    doppelt = alle_queries + alle_queries
    return doppelt[start:start + pro_lauf]


def claim_suche(fehler, queries=None):
    """
    (a) Claim-Suche ueber SUCHQUERIES.
    Rueckgabe: Liste roher Kandidaten (quelle='claim_suche').
    """
    if queries is None:
        queries = _query_rotation(SUCHQUERIES, QUERIES_PRO_LAUF)

    published_after = _iso_vor_tagen(CLAIM_SUCHE_TAGE)
    such_calls = 0
    gefundene_ids = []      # Reihenfolge behalten
    schon_gesehen = set()   # dedupe frueh, spart videos.list-Volumen

    for query in queries:
        for order in ("viewCount", "relevance"):
            if such_calls >= MAX_SEARCH_CALLS:
                fehler.append("youtube claim_suche: Such-Budget (%d) erschoepft, restliche Queries uebersprungen" % MAX_SEARCH_CALLS)
                break
            antwort = _api_get("search", {
                "part": "snippet",
                "q": query,
                "type": "video",
                "relevanceLanguage": "de",
                "regionCode": "DE",
                "publishedAfter": published_after,
                "order": order,
                "maxResults": 10,
            }, fehler)
            such_calls += 1
            if not antwort:
                continue
            for item in antwort.get("items", []):
                vid = (item.get("id") or {}).get("videoId")
                if vid and vid not in schon_gesehen:
                    schon_gesehen.add(vid)
                    gefundene_ids.append(vid)
        if such_calls >= MAX_SEARCH_CALLS:
            break

    print("[youtube] Claim-Suche: %d Queries, %d search-Calls, %d eindeutige Video-IDs"
          % (len(queries), such_calls, len(gefundene_ids)))

    details = _videos_details(gefundene_ids, fehler)
    follower = _kanal_follower(
        [d.get("snippet", {}).get("channelId") for d in details.values()], fehler)

    kandidaten = []
    for vid in gefundene_ids:
        item = details.get(vid)
        if not item:
            continue
        snippet = item.get("snippet", {})
        kandidaten.append(_roh_kandidat(
            vid, snippet, item.get("statistics", {}), item.get("contentDetails", {}),
            quelle="claim_suche",
            follower=follower.get(snippet.get("channelId")),
        ))
    return kandidaten


def watchlist_uploads(watchlist_eintraege, fehler):
    """
    (b) Watchlist: fuer jeden Eintrag mit YouTube-Kanal-ID die Uploads-Playlist
    der letzten 30 Tage (channels.list + playlistItems.list, je 1 Quota-Einheit).
    Rueckgabe: Liste roher Kandidaten (quelle='watchlist').
    """
    kanal_roh = [e["youtube"] for e in watchlist_eintraege if e.get("youtube")]
    if not kanal_roh:
        return []

    # Watchlist-Eintraege koennen Kanal-IDs (UC...) ODER Handles sein
    # (Vorschlags-/Folgen-Funktion speichert Handles) -> Handles aufloesen
    kanal_ids = []
    for eintrag in kanal_roh:
        if eintrag.startswith("UC") and len(eintrag) >= 20:
            kanal_ids.append(eintrag)
            continue
        antwort = _api_get("channels", {
            "part": "id", "forHandle": eintrag.lstrip("@"),
        }, fehler)
        items = (antwort or {}).get("items") or []
        if items:
            kanal_ids.append(items[0]["id"])
        else:
            fehler.append("youtube watchlist: Handle %r nicht aufloesbar" % eintrag)

    # Uploads-Playlists + Abonnenten in einem Rutsch
    kanal_info = {}
    antwort = _api_get("channels", {
        "part": "contentDetails,statistics,snippet",
        "id": ",".join(kanal_ids),
        "maxResults": 50,
    }, fehler)
    if antwort:
        for item in antwort.get("items", []):
            uploads = (item.get("contentDetails", {})
                       .get("relatedPlaylists", {}).get("uploads"))
            stats = item.get("statistics", {})
            kanal_info[item["id"]] = {
                "uploads": uploads,
                "follower": None if stats.get("hiddenSubscriberCount")
                            else int(stats.get("subscriberCount", 0) or 0),
            }
    # Handle-Verifikation: Kanal-IDs, die die API nicht kennt, sichtbar loggen
    for kid in kanal_ids:
        if kid not in kanal_info:
            fehler.append("youtube watchlist: Kanal %s nicht gefunden (ID pruefen!)" % kid)

    grenze = datetime.now(timezone.utc) - timedelta(days=WATCHLIST_TAGE)
    video_ids = []
    video_follower = {}

    for kid, info in kanal_info.items():
        if not info["uploads"]:
            fehler.append("youtube watchlist: Kanal %s hat keine Uploads-Playlist" % kid)
            continue
        antwort = _api_get("playlistItems", {
            "part": "contentDetails",
            "playlistId": info["uploads"],
            "maxResults": 50,
        }, fehler)
        if not antwort:
            continue
        for item in antwort.get("items", []):
            cd = item.get("contentDetails", {})
            vid = cd.get("videoId")
            veroeff = cd.get("videoPublishedAt")
            if not vid or not veroeff:
                continue
            try:
                zeit = datetime.strptime(veroeff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if zeit >= grenze:
                video_ids.append(vid)
                video_follower[vid] = info["follower"]

    print("[youtube] Watchlist: %d Kanaele verifiziert, %d Uploads der letzten %d Tage"
          % (len(kanal_info), len(video_ids), WATCHLIST_TAGE))

    details = _videos_details(video_ids, fehler)
    kandidaten = []
    for vid in video_ids:
        item = details.get(vid)
        if not item:
            continue
        kandidaten.append(_roh_kandidat(
            vid, item.get("snippet", {}), item.get("statistics", {}),
            item.get("contentDetails", {}),
            quelle="watchlist",
            follower=video_follower.get(vid),
        ))
    return kandidaten


# ---------------------------------------------------------------------------
# (c) Transkripte via yt-dlp Auto-Untertitel
# ---------------------------------------------------------------------------

_VTT_TAG = re.compile(r"<[^>]+>")
_VTT_ZEIT = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s+-->")

# Sentinel: Untertitel-Abruf scheiterte am IP-Rate-Limit (kein inhaltlicher Fehler)
_RATE_LIMIT = "__RATE_LIMIT_429__"


def _vtt_zu_text(vtt_inhalt, max_zeichen=TRANSKRIPT_MAX_ZEICHEN):
    """
    VTT -> Fliesstext. YouTube-Auto-Untertitel wiederholen Zeilen rollierend
    (jede Cue enthaelt die vorherige Zeile nochmal) -> Rolling-Dedupe:
    eine Zeile wird nur uebernommen, wenn sie nicht der letzten entspricht.
    """
    zeilen = []
    letzte = None
    for roh in vtt_inhalt.splitlines():
        zeile = _VTT_TAG.sub("", roh).strip()
        if (not zeile or zeile.startswith("WEBVTT") or zeile.startswith("Kind:")
                or zeile.startswith("Language:") or zeile.startswith("NOTE")
                or _VTT_ZEIT.match(zeile) or "-->" in zeile):
            continue
        if zeile == letzte:
            continue
        # Rolling-Caption: neue Zeile beginnt oft mit dem Ende der letzten
        if letzte and zeile.startswith(letzte):
            zeile_neu = zeile[len(letzte):].strip()
            if zeile_neu:
                zeilen.append(zeile_neu)
                letzte = zeile
            continue
        zeilen.append(zeile)
        letzte = zeile
    text = " ".join(zeilen)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_zeichen] if text else None


def _transkript_fuer_video(video_id, fehler):
    """Deutsche Auto-Untertitel eines Videos laden; None wenn keine da sind."""
    tmp = tempfile.mkdtemp(prefix="radar_yt_subs_")
    try:
        cmd = [
            "yt-dlp",
            "--write-auto-subs", "--write-subs",
            # NUR Original-Deutsch — "de.*" zog auch Auto-Übersetzungen (de-ar, de-sq …)
            # und vervielfachte die Requests gegen den 429-limitierten Endpunkt
            "--sub-langs", "de,de-orig",
            "--sub-format", "vtt",
            "--skip-download",
            "--no-warnings", "--quiet",
            "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
            "https://www.youtube.com/watch?v=" + video_id,
        ]
        ergebnis = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if ergebnis.returncode != 0:
            meldung = (ergebnis.stderr or "").strip().splitlines()
            letzte = meldung[-1] if meldung else "yt-dlp Fehler"
            if "429" in letzte:
                # Erwartetes IP-Rate-Limit: KEIN Panel-Fehler — der Aufrufer erkennt
                # es am Marker, setzt den Cooldown und der Audio-Fallback uebernimmt.
                print("[youtube] Untertitel %s: HTTP 429 (Rate-Limit)" % video_id)
                return _RATE_LIMIT
            fehler.append("youtube transkript %s: %s" % (video_id, letzte))
            return None
        vtts = glob.glob(os.path.join(tmp, "*.vtt"))
        if not vtts:
            return None  # kein deutscher Untertitel vorhanden — kein Fehler
        with open(vtts[0], "r", encoding="utf-8") as f:
            return _vtt_zu_text(f.read())
    except subprocess.TimeoutExpired:
        fehler.append("youtube transkript %s: Timeout (90s)" % video_id)
        return None
    except Exception as e:
        fehler.append("youtube transkript %s: %s" % (video_id, e))
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Nach einem 429 des Untertitel-Endpunkts pausieren ALLE Untertitel-Versuche
# fuer eine Weile (IP-basiertes Rate-Limit — sofortiges Weiterhaemmern verlaengert
# nur die Sperre). Der Audio-Fallback der Transkription deckt die Zeit ab.
_SUBS_COOLDOWN_DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "daten", ".yt_subs_429_cooldown")
SUBS_COOLDOWN_S = int(os.environ.get("RADAR_SUBS_COOLDOWN_S", "1800"))


def _subs_cooldown_aktiv():
    try:
        alter = time.time() - os.path.getmtime(_SUBS_COOLDOWN_DATEI)
        return alter < SUBS_COOLDOWN_S
    except OSError:
        return False


def _subs_cooldown_setzen():
    try:
        os.makedirs(os.path.dirname(_SUBS_COOLDOWN_DATEI), exist_ok=True)
        with open(_SUBS_COOLDOWN_DATEI, "w") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


def hole_transkripte(kandidaten, fehler, min_views=TRANSKRIPT_MIN_VIEWS,
                     max_videos=TRANSKRIPT_MAX_VIDEOS):
    """
    (c) Fuer YouTube-Kandidaten mit views > min_views deutsche Auto-Untertitel
    versuchen (Top max_videos nach Views). Mutiert kandidaten in-place.
    Rueckgabe: Anzahl erfolgreicher Transkripte.
    """
    ziel = [k for k in kandidaten
            if k.get("plattform") == "youtube"
            and not k.get("transkript")
            and (k.get("views") or 0) > min_views]
    ziel.sort(key=lambda k: -(k.get("views") or 0))
    ziel = ziel[:max_videos]

    if ziel and _subs_cooldown_aktiv():
        print("[youtube] Untertitel-Endpunkt im 429-Cooldown — %d Kandidaten gehen "
              "direkt in den Audio-Fallback" % len(ziel))
        for offen in ziel:
            offen["transkript_429"] = True
        return 0

    erfolgreich = 0
    for kand in ziel:
        text = _transkript_fuer_video(kand["video_id"], fehler)
        if text == _RATE_LIMIT:
            # YouTube drosselt den Untertitel-Endpunkt IP-basiert (HTTP 429):
            # sofort aufhoeren + Cooldown setzen statt weiterzuhaemmern. KEIN
            # Panel-Fehler — der Audio-Fallback der Transkription uebernimmt,
            # und 'aussortiert' ohne Material wird ohnehin vertagt (lauf.py).
            for offen in ziel[ziel.index(kand):]:
                if not offen.get("transkript"):
                    offen["transkript_429"] = True
            _subs_cooldown_setzen()
            print("[youtube] Transkripte: 429 — restliche %d gehen in den Audio-Fallback, "
                  "Untertitel pausieren %d min"
                  % (len(ziel) - ziel.index(kand), SUBS_COOLDOWN_S // 60))
            break
        if text:
            kand["transkript"] = text
            erfolgreich += 1
        time.sleep(2)  # rate-schonend
    print("[youtube] Transkripte: %d/%d erfolgreich (views > %d)"
          % (erfolgreich, len(ziel), min_views))
    return erfolgreich


def sammle(watchlist_eintraege, extra_queries=None):
    """
    Haupteinstieg fuer lauf.py.
    extra_queries: Zusatz-Queries aus Chris' Vorschlaegen — laufen IMMER mit und
    verdraengen Rotations-Slots (Quota bleibt konstant: QUERIES_PRO_LAUF gesamt).
    Rueckgabe: {"kandidaten": [...], "fehler": [...]}
    (Transkripte werden separat NACH dem Vorfilter geholt: hole_transkripte)
    """
    fehler = []
    kandidaten = []
    try:
        queries = None
        if extra_queries:
            extras = [q for q in extra_queries if q][:4]
            rotation = _query_rotation(SUCHQUERIES, max(1, QUERIES_PRO_LAUF - len(extras)))
            queries = extras + [q for q in rotation if q not in extras]
            print("[youtube] Vorschlags-Queries aktiv: %s" % ", ".join(extras))
        kandidaten.extend(claim_suche(fehler, queries=queries))
    except Exception as e:
        fehler.append("youtube claim_suche: Abbruch: %s" % e)
    try:
        kandidaten.extend(watchlist_uploads(watchlist_eintraege, fehler))
    except Exception as e:
        fehler.append("youtube watchlist: Abbruch: %s" % e)

    # Dedupe innerhalb des Laufs (Claim-Suche vs. Watchlist), Watchlist gewinnt
    nach_id = {}
    for k in kandidaten:
        vorhanden = nach_id.get(k["id"])
        if vorhanden is None or k["quelle"] == "watchlist":
            if vorhanden is not None and vorhanden["quelle"] == "watchlist":
                continue
            nach_id[k["id"]] = k
    return {"kandidaten": list(nach_id.values()), "fehler": fehler}
