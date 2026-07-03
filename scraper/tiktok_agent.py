# -*- coding: utf-8 -*-
"""
Wolf Radar — TikTok-Agent (yt-dlp, kein Login)

a) Watchlist-Profile: yt-dlp --flat-playlist --dump-single-json auf
   https://www.tiktok.com/@handle -> neueste ~30 Eintraege mit
   view_count/like_count/timestamp direkt aus den Playlist-Entries.
   Handle-Verifikation: 404/Fehler landet sichtbar in der fehler-Liste.

b) Fuer Kandidaten mit > 50.000 Views: Einzelvideo-Details nachladen
   (yt-dlp -J) fuer vollstaendigen Titel/Beschreibung.

Rate-schonend: sleep zwischen allen yt-dlp-Aufrufen.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone

MAX_EINTRAEGE_PRO_PROFIL = 30
DETAIL_MIN_VIEWS = 50000
DETAIL_MAX_VIDEOS = int(os.environ.get("RADAR_TIKTOK_DETAILS_MAX", "10"))
SLEEP_ZWISCHEN_CALLS = 3   # Sekunden — TikTok blockt aggressive Clients
PROFIL_TIMEOUT = 120
DETAIL_TIMEOUT = 60


def _jetzt_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_zu_iso(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError, OverflowError):
        return None


def _yt_dlp_json(args, timeout, fehler, kontext):
    """yt-dlp ausfuehren und stdout als JSON parsen; None bei Fehlern."""
    cmd = ["yt-dlp", "--no-warnings", "--quiet"] + args
    try:
        ergebnis = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        fehler.append("tiktok %s: Timeout (%ds)" % (kontext, timeout))
        return None
    except FileNotFoundError:
        fehler.append("tiktok: yt-dlp nicht installiert")
        return None
    if ergebnis.returncode != 0 or not ergebnis.stdout.strip():
        meldung = (ergebnis.stderr or "").strip().splitlines()
        fehler.append("tiktok %s: %s" % (kontext, meldung[-1][:200] if meldung else "yt-dlp Fehler ohne Meldung"))
        return None
    try:
        return json.loads(ergebnis.stdout)
    except json.JSONDecodeError as e:
        fehler.append("tiktok %s: JSON nicht lesbar (%s)" % (kontext, e))
        return None


def _erste_zeile(text):
    if not text:
        return None
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if zeile:
            return zeile[:200]
    return None


def _roh_kandidat(entry, handle, profil_name, follower):
    """Playlist-Entry -> rohes video-Dict nach Kontrakt."""
    video_id = str(entry.get("id") or "")
    if not video_id:
        return None
    caption = entry.get("description") or entry.get("title") or ""
    url = entry.get("url") or entry.get("webpage_url") or (
        "https://www.tiktok.com/@%s/video/%s" % (handle, video_id))
    return {
        "id": "tiktok:" + video_id,
        "plattform": "tiktok",
        "video_id": video_id,
        "url": url,
        "titel": _erste_zeile(caption) or ("TikTok von @" + handle),
        "kanal": profil_name or entry.get("uploader") or handle,
        "kanal_id": "@" + handle,
        "kanal_follower": follower,
        "veroeffentlicht": _ts_zu_iso(entry.get("timestamp")),
        "views": int(entry.get("view_count") or 0),
        "likes": int(entry["like_count"]) if entry.get("like_count") is not None else None,
        "kommentare": int(entry["comment_count"]) if entry.get("comment_count") is not None else None,
        "dauer_s": int(entry["duration"]) if entry.get("duration") else None,
        "thumbnail_url": entry.get("thumbnail") or None,
        "caption": caption,
        "transkript": None,
        "gefunden_am": _jetzt_iso(),
        "quelle": "watchlist",
        "status": "inbox",
        "score": 0,
        "scores": {},
        "claim": None,
        "skripte": [],
        "feedback": [],
    }


def profil_scannen(handle, fehler):
    """
    (a) Ein Watchlist-Profil scannen. Rueckgabe: Liste roher Kandidaten.
    Existiert das Profil nicht (404 o.ae.), landet das in der fehler-Liste.
    """
    url = "https://www.tiktok.com/@" + handle
    daten = _yt_dlp_json(
        ["--flat-playlist", "--dump-single-json",
         "--playlist-end", str(MAX_EINTRAEGE_PRO_PROFIL), url],
        PROFIL_TIMEOUT, fehler, "profil @" + handle)
    if daten is None:
        return []

    entries = daten.get("entries") or []
    if not entries:
        fehler.append("tiktok profil @%s: 0 Eintraege (Profil leer, privat oder Handle falsch?)" % handle)
        return []

    profil_name = daten.get("uploader") or daten.get("channel") or daten.get("title")
    follower = daten.get("channel_follower_count")
    if follower is not None:
        follower = int(follower)

    kandidaten = []
    for entry in entries[:MAX_EINTRAEGE_PRO_PROFIL]:
        kand = _roh_kandidat(entry, handle, profil_name, follower)
        if kand:
            kandidaten.append(kand)
    print("[tiktok] @%s verifiziert: %d Videos, Follower: %s"
          % (handle, len(kandidaten), follower if follower is not None else "unbekannt"))
    return kandidaten


def details_nachladen(kandidaten, fehler, min_views=DETAIL_MIN_VIEWS,
                      max_videos=DETAIL_MAX_VIDEOS):
    """
    (b) Fuer TikTok-Kandidaten mit > min_views Views Einzelvideo-Details
    (-J) nachladen: vollstaendige Beschreibung, praezisere Zahlen.
    Mutiert kandidaten in-place. Rueckgabe: Anzahl nachgeladener Videos.
    """
    ziel = [k for k in kandidaten
            if k.get("plattform") == "tiktok" and (k.get("views") or 0) > min_views]
    ziel.sort(key=lambda k: -(k.get("views") or 0))
    ziel = ziel[:max_videos]

    nachgeladen = 0
    for kand in ziel:
        time.sleep(SLEEP_ZWISCHEN_CALLS)
        daten = _yt_dlp_json(["-J", kand["url"]], DETAIL_TIMEOUT, fehler,
                             "detail " + kand["id"])
        if not daten:
            continue
        beschreibung = daten.get("description") or daten.get("title") or ""
        if beschreibung:
            kand["caption"] = beschreibung
            kand["titel"] = _erste_zeile(beschreibung) or kand["titel"]
        for quelle_feld, ziel_feld in (
                ("view_count", "views"), ("like_count", "likes"),
                ("comment_count", "kommentare"), ("duration", "dauer_s")):
            if daten.get(quelle_feld) is not None:
                kand[ziel_feld] = int(daten[quelle_feld])
        if daten.get("timestamp"):
            kand["veroeffentlicht"] = _ts_zu_iso(daten["timestamp"])
        if daten.get("thumbnail"):
            kand["thumbnail_url"] = daten["thumbnail"]
        if daten.get("channel_follower_count") is not None:
            kand["kanal_follower"] = int(daten["channel_follower_count"])
        nachgeladen += 1
    if ziel:
        print("[tiktok] Details nachgeladen: %d/%d (views > %d)"
              % (nachgeladen, len(ziel), min_views))
    return nachgeladen


def sammle(watchlist_eintraege):
    """
    Haupteinstieg fuer lauf.py: alle Watchlist-Profile mit TikTok-Handle.
    Rueckgabe: {"kandidaten": [...], "fehler": [...]}
    """
    fehler = []
    kandidaten = []
    handles = [(e.get("tiktok"), e.get("name")) for e in watchlist_eintraege if e.get("tiktok")]
    for i, (handle, name) in enumerate(handles):
        if i > 0:
            time.sleep(SLEEP_ZWISCHEN_CALLS)
        try:
            kandidaten.extend(profil_scannen(handle, fehler))
        except Exception as e:
            fehler.append("tiktok profil @%s: Abbruch: %s" % (handle, e))

    try:
        details_nachladen(kandidaten, fehler)
    except Exception as e:
        fehler.append("tiktok details: Abbruch: %s" % e)

    return {"kandidaten": kandidaten, "fehler": fehler}
