# -*- coding: utf-8 -*-
"""
Wolf Radar — Instagram-Agent (gallery-dl, BEST EFFORT)

Watchlist-Profile: gallery-dl --write-metadata --range 1-15 in einen
Temp-Ordner. Ausgewertet werden NUR die JSON-Metadaten (Caption, Likes,
Datum, URL) — Mediendateien werden sofort geloescht.

Haertung gegen Instagrams Logout-Blockaden (Login-Wall, Rate-Limits):
- Optionaler Session-Cookie: ENV IG_SESSIONID -> temporaere Netscape-
  Cookie-Datei fuer gallery-dl (--cookies). Ohne ENV: wie bisher ohne Login.
  Wie man den Cookie aus dem Browser holt: siehe README, Abschnitt
  "Instagram-Session-Cookie (optional)".
- Exponentielles Backoff zwischen Profilen (min. 20s + Jitter, verdoppelt
  sich nach Fehlschlaegen).
- Beim ERSTEN 401/429 wird der restliche IG-Lauf abgebrochen
  ("IG rate-limited — Rest uebersprungen") statt das Limit zu verschaerfen.
- Handle-Cache daten/ig_handle_status.json: fehlgeschlagene Handles werden
  nur 1x/Woche erneut versucht.

Jeder Ausfall wird sauber geloggt, der Agent wirft NIE eine Exception
nach oben — ein Instagram-Ausfall darf den Lauf nicht stoppen.
"""

import glob
import json
import os
import random
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone

POSTS_PRO_PROFIL = 15
PROFIL_TIMEOUT = 180
BACKOFF_BASIS_S = 20      # Mindestabstand zwischen zwei Profil-Scans
BACKOFF_MAX_S = 300       # Obergrenze fuer exponentielles Backoff
JITTER_MAX_S = 10         # zufaelliger Aufschlag gegen Muster-Erkennung
FEHLER_RETRY_TAGE = 7     # fehlgeschlagene Handles nur 1x/Woche erneut

# Handle-Cache liegt neben den anderen Lokal-Modus-Dateien in <repo>/daten/
SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
DATEN_DIR = os.path.join(os.path.dirname(SCRAPER_DIR), "daten")
HANDLE_STATUS_DATEI = os.path.join(DATEN_DIR, "ig_handle_status.json")

# Marker in gallery-dl-Ausgaben, die auf ein Rate-Limit/Auth-Problem deuten
_RATE_LIMIT_MARKER = ("401 unauthorized", "'401", "http 401", "429",
                      "rate limit", "wait a few minutes")


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


def _cookie_datei_erstellen():
    """
    ENV IG_SESSIONID -> temporaere Netscape-Cookie-Datei fuer gallery-dl.
    Rueckgabe: Pfad zur Datei oder None (dann laeuft alles ohne Login wie bisher).
    Aufrufer muss die Datei nach dem Lauf loeschen (enthaelt das Session-Secret!).
    """
    sessionid = (os.environ.get("IG_SESSIONID") or "").strip()
    if not sessionid:
        return None
    ablauf = int(time.time()) + 365 * 24 * 3600
    inhalt = (
        "# Netscape HTTP Cookie File\n"
        "# Wolf Radar: temporaer aus ENV IG_SESSIONID erzeugt, wird nach dem Lauf geloescht\n"
        ".instagram.com\tTRUE\t/\tTRUE\t%d\tsessionid\t%s\n" % (ablauf, sessionid)
    )
    fd, pfad = tempfile.mkstemp(prefix="radar_ig_cookies_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(inhalt)
    except OSError:
        try:
            os.remove(pfad)
        except OSError:
            pass
        return None
    return pfad


def _lade_handle_status():
    """daten/ig_handle_status.json laden: {handle: {status, zeit, grund}}."""
    try:
        with open(HANDLE_STATUS_DATEI, "r", encoding="utf-8") as f:
            daten = json.load(f)
        return daten if isinstance(daten, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _speichere_handle_status(status):
    """Handle-Cache atomar schreiben (Best effort, nie werfen)."""
    try:
        os.makedirs(DATEN_DIR, exist_ok=True)
        fd, tmp_pfad = tempfile.mkstemp(dir=DATEN_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(status, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp_pfad, HANDLE_STATUS_DATEI)
        finally:
            if os.path.exists(tmp_pfad):
                try:
                    os.remove(tmp_pfad)
                except OSError:
                    pass
    except OSError as e:
        print("[instagram] WARNUNG: Handle-Status nicht speicherbar: %s" % e)


def _soll_ueberspringen(eintrag):
    """True, wenn der Handle vor < FEHLER_RETRY_TAGE fehlgeschlagen ist."""
    if not eintrag or eintrag.get("status") != "fehler":
        return False
    try:
        zeit = datetime.strptime(str(eintrag.get("zeit") or ""),
                                 "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    alter_tage = (datetime.now(timezone.utc) - zeit).total_seconds() / 86400.0
    return 0 <= alter_tage < FEHLER_RETRY_TAGE


def _ist_rate_limit(text):
    text = (text or "").lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKER)


def _backoff_schlafen(fehlschlaege_in_folge):
    """Exponentielles Backoff zwischen Profilen: min. 20s + Jitter."""
    basis = min(BACKOFF_BASIS_S * (2 ** fehlschlaege_in_folge), BACKOFF_MAX_S)
    dauer = basis + random.uniform(0, JITTER_MAX_S)
    print("[instagram] Backoff: %.0fs Pause vor dem naechsten Profil" % dauer)
    time.sleep(dauer)


def profil_scannen(handle, fehler, cookie_datei=None):
    """
    Ein Instagram-Profil scannen.
    Rueckgabe: (Liste roher Kandidaten, rate_limited: bool).
    rate_limited=True signalisiert dem Aufrufer, den IG-Lauf abzubrechen.
    """
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
        ]
        if cookie_datei:
            cmd += ["--cookies", cookie_datei]
        cmd.append(url)
        try:
            ergebnis = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=PROFIL_TIMEOUT)
        except subprocess.TimeoutExpired:
            fehler.append("instagram @%s: Timeout (%ds)" % (handle, PROFIL_TIMEOUT))
            return [], False
        except FileNotFoundError:
            fehler.append("instagram: gallery-dl nicht installiert")
            return [], False

        json_dateien = glob.glob(os.path.join(tmp, "**", "*.json"), recursive=True)

        if not json_dateien:
            ausgabe = ((ergebnis.stderr or "") + "\n" + (ergebnis.stdout or "")).strip()
            if _ist_rate_limit(ausgabe):
                fehler.append("instagram @%s: HTTP 401/429 (Rate-Limit erkannt)" % handle)
                return [], True
            meldung = ausgabe.splitlines()
            kurz = meldung[-1][:200] if meldung else "keine Metadaten (Login-Wall oder Handle falsch?)"
            fehler.append("instagram @%s: %s" % (handle, kurz))
            return [], False

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
        return list(kandidaten.values()), False
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
    if handles and shutil.which("gallery-dl") is None:
        fehler.append("instagram: gallery-dl nicht installiert")
        return {"kandidaten": kandidaten, "fehler": fehler}

    status = _lade_handle_status()
    cookie_datei = _cookie_datei_erstellen()
    print("[instagram] Session-Cookie: %s"
          % ("aktiv (ENV IG_SESSIONID)" if cookie_datei else "keiner (Best effort ohne Login)"))

    fehlschlaege_in_folge = 0
    erster_scan = True
    try:
        for handle in handles:
            eintrag = status.get(handle)
            if _soll_ueberspringen(eintrag):
                print("[instagram] @%s uebersprungen (Fehlschlag am %s, Retry erst nach %d Tagen)"
                      % (handle, eintrag.get("zeit"), FEHLER_RETRY_TAGE))
                continue
            if not erster_scan:
                _backoff_schlafen(fehlschlaege_in_folge)
            erster_scan = False

            fehler_vorher = len(fehler)
            try:
                neue, rate_limited = profil_scannen(handle, fehler, cookie_datei)
            except Exception as e:
                fehler.append("instagram @%s: Abbruch: %s" % (handle, e))
                neue, rate_limited = [], False

            if rate_limited:
                # 401/429 ist ein GLOBALES Limit, kein Handle-Problem:
                # Handle-Status unangetastet lassen, restliche Profile auslassen.
                fehler.append("IG rate-limited — Rest uebersprungen")
                print("[instagram] FEHLER: IG rate-limited — Rest uebersprungen "
                      "(%d Profile nicht gescannt)"
                      % (len(handles) - handles.index(handle) - 1))
                break

            if neue:
                kandidaten.extend(neue)
                status[handle] = {"status": "ok", "zeit": _jetzt_iso(), "grund": None}
                fehlschlaege_in_folge = 0
            else:
                grund = "; ".join(fehler[fehler_vorher:]) or "keine Metadaten"
                status[handle] = {"status": "fehler", "zeit": _jetzt_iso(),
                                  "grund": grund[:200]}
                fehlschlaege_in_folge += 1
    finally:
        if cookie_datei:
            try:
                os.remove(cookie_datei)
            except OSError:
                pass
        _speichere_handle_status(status)

    return {"kandidaten": kandidaten, "fehler": fehler}
