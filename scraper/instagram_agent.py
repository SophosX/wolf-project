# -*- coding: utf-8 -*-
"""
Wolf Radar — Instagram-Agent (gallery-dl ohne Login, BEST EFFORT)

Watchlist-Profile: gallery-dl --write-metadata --range 1-15 in einen
Temp-Ordner. Ausgewertet werden NUR die JSON-Metadaten (Caption, Likes,
Datum, URL) — Mediendateien werden sofort geloescht.

Instagram blockt Logout-Zugriffe gern (Login-Wall, Rate-Limits):
Jeder Ausfall wird sauber geloggt, der Agent wirft NIE eine Exception
nach oben — ein Instagram-Ausfall darf den Lauf nicht stoppen.
"""

import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone

POSTS_PRO_PROFIL = 15
PROFIL_TIMEOUT = 180
SLEEP_ZWISCHEN_PROFILEN = 5


def _jetzt_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _datum_zu_iso(wert):
    """gallery-dl liefert 'date' als 'YYYY-MM-DD HH:MM:SS' oder Unix-Timestamp."""
    if not wert:
        return None
    if isinstance(wert, (int, float)):
        try:
            return datetime.fromtimestamp(int(wert), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OSError, OverflowError):
            return None
    text = str(wert).strip().replace(" ", "T")
    if text and not text.endswith("Z") and "+" not in text:
        text += "Z"
    return text


def _erste_zeile(text):
    if not text:
        return None
    for zeile in text.splitlines():
        zeile = zeile.strip()
        if zeile:
            return zeile[:200]
    return None


def _meta_zu_kandidat(meta, handle):
    """Ein gallery-dl-Metadaten-JSON -> rohes video-Dict nach Kontrakt."""
    # Post-Kurzcode: 'post_shortcode' identifiziert den POST (Karussell-Bilder
    # haben je ein eigenes 'shortcode' -> wuerde Duplikate erzeugen)
    shortcode = meta.get("post_shortcode") or meta.get("shortcode")
    if not shortcode:
        return None
    caption = meta.get("description") or meta.get("caption") or ""
    likes = meta.get("likes")
    if likes is None:
        likes = meta.get("like_count")
    url = meta.get("post_url") or ("https://www.instagram.com/p/%s/" % shortcode)
    kanal = meta.get("fullname") or meta.get("username") or handle
    views = meta.get("video_view_count") or meta.get("view_count") or 0
    return {
        "id": "instagram:" + shortcode,
        "plattform": "instagram",
        "video_id": shortcode,
        "url": url,
        "titel": _erste_zeile(caption) or ("Instagram-Post von @" + handle),
        "kanal": kanal,
        "kanal_id": "@" + (meta.get("username") or handle),
        "kanal_follower": meta.get("followers") or None,
        "veroeffentlicht": _datum_zu_iso(meta.get("date")),
        "views": int(views or 0),
        "likes": int(likes) if likes is not None else None,
        "kommentare": int(meta["comments"]) if meta.get("comments") is not None else None,
        "dauer_s": int(meta["video_duration"]) if meta.get("video_duration") else None,
        "thumbnail_url": meta.get("display_url") or None,
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
    """Ein Instagram-Profil scannen. Rueckgabe: Liste roher Kandidaten."""
    tmp = tempfile.mkdtemp(prefix="radar_ig_")
    try:
        url = "https://www.instagram.com/" + handle + "/"
        cmd = [
            "gallery-dl",
            "--write-metadata",
            "--no-download",              # nur Metadaten, keine Medien
            "--range", "1-%d" % POSTS_PRO_PROFIL,
            "--directory", tmp,
            "--quiet",
            url,
        ]
        try:
            ergebnis = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=PROFIL_TIMEOUT)
        except subprocess.TimeoutExpired:
            fehler.append("instagram @%s: Timeout (%ds)" % (handle, PROFIL_TIMEOUT))
            return []
        except FileNotFoundError:
            fehler.append("instagram: gallery-dl nicht installiert")
            return []

        json_dateien = glob.glob(os.path.join(tmp, "**", "*.json"), recursive=True)

        if not json_dateien:
            meldung = (ergebnis.stderr or ergebnis.stdout or "").strip().splitlines()
            kurz = meldung[-1][:200] if meldung else "keine Metadaten (Login-Wall oder Handle falsch?)"
            fehler.append("instagram @%s: %s" % (handle, kurz))
            return []

        # Mehrere JSONs pro Post moeglich (Karussell) -> per shortcode dedupen
        kandidaten = {}
        for pfad in sorted(json_dateien):
            try:
                with open(pfad, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                fehler.append("instagram @%s: Metadaten %s nicht lesbar (%s)"
                              % (handle, os.path.basename(pfad), e))
                continue
            kand = _meta_zu_kandidat(meta, handle)
            if kand and kand["id"] not in kandidaten:
                kandidaten[kand["id"]] = kand

        print("[instagram] @%s: %d Posts aus %d Metadaten-Dateien"
              % (handle, len(kandidaten), len(json_dateien)))
        return list(kandidaten.values())
    finally:
        # Temp-Ordner inkl. eventuell doch geladener Mediendateien loeschen
        shutil.rmtree(tmp, ignore_errors=True)


def sammle(watchlist_eintraege):
    """
    Haupteinstieg fuer lauf.py: alle Watchlist-Profile mit Instagram-Handle.
    Best effort: Fehler werden gesammelt, nie geworfen.
    Rueckgabe: {"kandidaten": [...], "fehler": [...]}
    """
    fehler = []
    kandidaten = []
    handles = [e.get("instagram") for e in watchlist_eintraege if e.get("instagram")]
    for i, handle in enumerate(handles):
        if i > 0:
            time.sleep(SLEEP_ZWISCHEN_PROFILEN)
        try:
            kandidaten.extend(profil_scannen(handle, fehler))
        except Exception as e:
            fehler.append("instagram @%s: Abbruch: %s" % (handle, e))
    return {"kandidaten": kandidaten, "fehler": fehler}
