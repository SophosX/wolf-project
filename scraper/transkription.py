# -*- coding: utf-8 -*-
"""
Wolf Radar — Audio-Transkription für alle Plattformen (TikTok, Instagram, YouTube-Fallback)

Warum: Ohne Transkript urteilt die Analyse nur über Titel/Caption — bei TikTok/Reels
steht die eigentliche Falschaussage aber im GESPROCHENEN Wort. Dieses Modul holt
das Audio und transkribiert es mit Gemini (Audio-Input), damit die Datenbank für
Analyse und Faktencheck laufend mit Volltext-Material wächst.

Beschaffungswege je Plattform:
  - tiktok    : yt-dlp lädt das Video/Audio (bewährt, kein Login)
  - instagram : direkte CDN-URL aus dem Apify-Item (kandidat["apify_video_url"]);
                Fallback yt-dlp auf die Post-URL (klappt ohne Login nur manchmal)
  - youtube   : NUR Fallback, wenn es keine Auto-Untertitel gab (die bleiben
                erster Weg — billiger und schneller als Audio)

Transkription: ffmpeg wandelt in kleines Mono-MP3 (16 kHz), Gemini bekommt es
inline (Base64). Kein neues Package nötig — urllib + subprocess reichen.

Öffentliche Schnittstelle:
  transkribiere_kandidaten(kandidaten, fehler, max_videos=None) -> int
    Mutiert kandidaten in-place (setzt "transkript"), sammelt Fehler in fehler.
"""

import base64
import glob
import json
import logging
import os
import random
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from analyse import lade_gemini_key

logger = logging.getLogger("wolf_radar.transkription")

GEMINI_MODELL_TRANSKRIPT = os.environ.get("RADAR_MODELL_TRANSKRIPT", "gemini-2.5-flash")
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              + GEMINI_MODELL_TRANSKRIPT + ":generateContent")

# Budgets pro Lauf (ENV-konfigurierbar): Audio-Transkription kostet vor allem ZEIT
# (Download + ffmpeg + API ≈ 20-40 s pro Video), Tokens sind billig (~32/Sekunde Audio).
MAX_AUDIO_PRO_LAUF = int(os.environ.get("RADAR_AUDIO_MAX", "12"))
MIN_VIEWS_KURZVIDEO = int(os.environ.get("RADAR_AUDIO_MIN_VIEWS", "2000"))   # TikTok/IG
MIN_VIEWS_YOUTUBE = int(os.environ.get("RADAR_AUDIO_MIN_VIEWS_YT", "10000")) # YT-Fallback
MAX_DAUER_S = int(os.environ.get("RADAR_AUDIO_MAX_DAUER_S", "1200"))  # >20 min: skip
MAX_MP3_BYTES = 25 * 1024 * 1024   # weit unter dem 100-MB-Inline-Limit der API
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024
TRANSKRIPT_MAX_ZEICHEN = 8000      # wie youtube_agent
DOWNLOAD_TIMEOUT_S = 120
FFMPEG_TIMEOUT_S = 120
GEMINI_TIMEOUT_S = 180
SLEEP_ZWISCHEN_VIDEOS_S = 3        # rate-schonend (TikTok blockt aggressive Clients)

_KEINE_SPRACHE = "KEINE_SPRACHE"


# ---------------------------------------------------------------------------
# Schritt 1: Audio beschaffen (yt-dlp oder direkte CDN-URL) -> kleines MP3
# ---------------------------------------------------------------------------

def _zu_mono_mp3(quelle_pfad, ziel_pfad, fehler, kontext):
    """ffmpeg: beliebige Video-/Audiodatei -> Mono-MP3 16 kHz 40 kbit/s (klein & sprachtauglich)."""
    cmd = ["ffmpeg", "-y", "-i", quelle_pfad, "-vn", "-ac", "1", "-ar", "16000",
           "-b:a", "40k", "-f", "mp3", ziel_pfad]
    try:
        ergebnis = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        fehler.append("transkription %s: ffmpeg-Timeout" % kontext)
        return False
    except FileNotFoundError:
        fehler.append("transkription: ffmpeg nicht installiert")
        return False
    if ergebnis.returncode != 0 or not os.path.exists(ziel_pfad):
        meldung = (ergebnis.stderr or "").strip().splitlines()
        fehler.append("transkription %s: ffmpeg: %s" % (kontext, meldung[-1][:160] if meldung else "Fehler"))
        return False
    return True


def _hat_audio_stream(pfad):
    """ffprobe: enthält die Datei mindestens einen Audio-Stream?
    (TikTok liefert teils video-only-Varianten, die als 'aac' gelabelt sind.)"""
    try:
        ergebnis = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", pfad],
            capture_output=True, text=True, timeout=30)
        return "audio" in (ergebnis.stdout or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return True  # im Zweifel konvertieren lassen — ffmpeg meldet es sonst


def _audio_via_ytdlp(url, tmp, fehler, kontext, plattform=None):
    """Video-URL -> MP3-Pfad via yt-dlp (TikTok, YouTube, notfalls Instagram).
    TikTok: das 'download'-Format zuerst (garantiert mit Tonspur gemuxt —
    Wasserzeichen egal, gebraucht wird nur das Audio); manche als 'aac'
    gelistete CDN-Varianten sind in Wahrheit video-only."""
    formate = ["download", "ba/b"] if plattform == "tiktok" else ["ba/b"]
    letzte_meldung = None
    for versuch, format_wahl in enumerate(formate, 1):
        for alt in glob.glob(os.path.join(tmp, "roh.*")):
            os.remove(alt)
        cmd = [
            "yt-dlp", "--no-warnings", "--quiet", "--no-playlist",
            "-f", format_wahl,
            "--max-filesize", str(MAX_DOWNLOAD_BYTES),
            "-o", os.path.join(tmp, "roh.%(ext)s"),
            url,
        ]
        try:
            ergebnis = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=DOWNLOAD_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            fehler.append("transkription %s: yt-dlp-Timeout (%ds)" % (kontext, DOWNLOAD_TIMEOUT_S))
            return None
        except FileNotFoundError:
            fehler.append("transkription: yt-dlp nicht installiert")
            return None
        roh_dateien = [p for p in glob.glob(os.path.join(tmp, "roh.*"))
                       if not p.endswith(".part")]
        if ergebnis.returncode != 0 or not roh_dateien:
            meldung = (ergebnis.stderr or "").strip().splitlines()
            letzte_meldung = meldung[-1][:160] if meldung else "kein Download"
            continue
        if not _hat_audio_stream(roh_dateien[0]):
            letzte_meldung = "Format ohne Audio-Stream (%s)" % format_wahl
            continue
        mp3 = os.path.join(tmp, "audio.mp3")
        if _zu_mono_mp3(roh_dateien[0], mp3, fehler, kontext):
            return mp3
        return None
    fehler.append("transkription %s: yt-dlp: %s" % (kontext, letzte_meldung))
    return None


def _audio_von_direkter_url(video_url, tmp, fehler, kontext):
    """Direkte CDN-URL (Apify-Instagram-Item) -> MP3-Pfad. Kein Login nötig,
    die URL ist nur kurz gültig — deshalb wird sie im selben Lauf verbraucht."""
    roh = os.path.join(tmp, "roh.mp4")
    anfrage = urllib.request.Request(video_url, headers={
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    })
    try:
        with urllib.request.urlopen(anfrage, timeout=DOWNLOAD_TIMEOUT_S) as antwort, \
                open(roh, "wb") as ziel:
            gelesen = 0
            while True:
                block = antwort.read(1 << 20)
                if not block:
                    break
                gelesen += len(block)
                if gelesen > MAX_DOWNLOAD_BYTES:
                    fehler.append("transkription %s: Video > %d MB — übersprungen"
                                  % (kontext, MAX_DOWNLOAD_BYTES // (1 << 20)))
                    return None
                ziel.write(block)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        fehler.append("transkription %s: CDN-Download: %s" % (kontext, str(e)[:160]))
        return None
    if not _hat_audio_stream(roh):
        # Foto-Post/kaputter Download — kein Audio ist kein Pipeline-Fehler
        logger.info("Transkription %s: CDN-Datei ohne Audio-Stream — übersprungen.", kontext)
        return None
    mp3 = os.path.join(tmp, "audio.mp3")
    if not _zu_mono_mp3(roh, mp3, fehler, kontext):
        return None
    return mp3


# ---------------------------------------------------------------------------
# Schritt 2: Gemini-Transkription (Audio inline als Base64)
# ---------------------------------------------------------------------------

_TRANSKRIPT_PROMPT = (
    "Transkribiere die gesprochene Sprache in dieser Audiodatei wörtlich und vollständig "
    "in der Originalsprache (erwartet: Deutsch). Gib NUR den reinen Transkript-Text zurück — "
    "keine Zeitstempel, keine Sprecher-Labels, keine Anführungszeichen, keine Kommentare, "
    "keine Übersetzung. Musik oder Geräusche ignorierst du. "
    "Wenn gar keine Sprache vorkommt, antworte exakt mit: " + _KEINE_SPRACHE
)


def _gemini_transkribiere(mp3_pfad, fehler, kontext, max_versuche=3):
    """MP3 -> Transkript-Text via Gemini. None bei Fehlern (transparent gesammelt)."""
    try:
        groesse = os.path.getsize(mp3_pfad)
        if groesse > MAX_MP3_BYTES:
            fehler.append("transkription %s: MP3 %.1f MB > Limit — übersprungen"
                          % (kontext, groesse / 1048576.0))
            return None
        with open(mp3_pfad, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        fehler.append("transkription %s: MP3 nicht lesbar: %s" % (kontext, e))
        return None

    koerper = json.dumps({
        "contents": [{"role": "user", "parts": [
            {"text": _TRANSKRIPT_PROMPT},
            {"inline_data": {"mime_type": "audio/mp3", "data": audio_b64}},
        ]}],
        "generationConfig": {"temperature": 0.0},
    }).encode("utf-8")

    letzter_fehler = None
    for versuch in range(1, max_versuche + 1):
        anfrage = urllib.request.Request(
            GEMINI_URL, data=koerper, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": lade_gemini_key()},
        )
        try:
            with urllib.request.urlopen(anfrage, timeout=GEMINI_TIMEOUT_S) as antwort:
                daten = json.loads(antwort.read().decode("utf-8"))
            teile = ((daten.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            text = "".join(t.get("text", "") for t in teile).strip()
            if not text or text.upper().startswith(_KEINE_SPRACHE):
                return None  # stumm/Musik — kein Fehler
            return text[:TRANSKRIPT_MAX_ZEICHEN]
        except urllib.error.HTTPError as e:
            rumpf = ""
            try:
                rumpf = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            letzter_fehler = "HTTP %s: %s" % (e.code, rumpf)
            if e.code in (429, 500, 502, 503, 504) and versuch < max_versuche:
                time.sleep(2.0 * (2 ** (versuch - 1)) + random.uniform(0, 1))
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            letzter_fehler = "Netzwerk: %s" % e
            if versuch < max_versuche:
                time.sleep(2.0 * (2 ** (versuch - 1)))
                continue
            break
    fehler.append("transkription %s: Gemini: %s" % (kontext, letzter_fehler))
    return None


# ---------------------------------------------------------------------------
# Öffentlich: Kandidaten transkribieren (alle Plattformen)
# ---------------------------------------------------------------------------

def _audio_beschaffen(kandidat, tmp, fehler, kontext):
    """Plattformgerechter Beschaffungsweg; gibt MP3-Pfad oder None zurück."""
    plattform = kandidat.get("plattform")
    if plattform == "instagram":
        cdn_url = kandidat.get("apify_video_url")
        if cdn_url:
            mp3 = _audio_von_direkter_url(cdn_url, tmp, fehler, kontext)
            if mp3:
                return mp3
        # Fallback ohne CDN-URL: yt-dlp direkt auf den Post (klappt anonym nur manchmal)
        return _audio_via_ytdlp(kandidat.get("url"), tmp, fehler, kontext, plattform)
    return _audio_via_ytdlp(kandidat.get("url"), tmp, fehler, kontext, plattform)


def _ist_transkriptions_kandidat(k, min_views_kurz, min_views_yt):
    if k.get("transkript"):
        return False
    if not k.get("url"):
        return False
    views = k.get("views") or 0
    if k.get("plattform") == "instagram":
        if not views:
            views = (k.get("likes") or 0) * 12  # Reichweiten-Proxy wie im Vorfilter
        # Reine Foto-/Carousel-Posts ohne Video haben kein Audio: nur versuchen,
        # wenn es ein Video-Indiz gibt (frische CDN-URL oder bekannte Dauer).
        if not k.get("apify_video_url") and not k.get("dauer_s"):
            return False
    mindest = min_views_yt if k.get("plattform") == "youtube" else min_views_kurz
    if views < mindest:
        return False
    dauer = k.get("dauer_s")
    if dauer and float(dauer) > MAX_DAUER_S:
        return False
    return True


def transkribiere_kandidaten(kandidaten, fehler, max_videos=None,
                             min_views_kurz=None, min_views_yt=None):
    """
    Für Kandidaten ohne Transkript (alle Plattformen) Audio holen und transkribieren.
    Mutiert die Dicts in-place ("transkript"). Rückgabe: Anzahl erfolgreicher Transkripte.
    Reihenfolge: größte Reichweite zuerst; Budget MAX_AUDIO_PRO_LAUF.
    """
    if max_videos is None:
        max_videos = MAX_AUDIO_PRO_LAUF
    if min_views_kurz is None:
        min_views_kurz = MIN_VIEWS_KURZVIDEO
    if min_views_yt is None:
        min_views_yt = MIN_VIEWS_YOUTUBE
    ziel = [k for k in kandidaten
            if _ist_transkriptions_kandidat(k, min_views_kurz, min_views_yt)]
    ziel.sort(key=lambda k: -(k.get("views") or 0))
    ziel = ziel[:max_videos]
    if not ziel:
        return 0

    erfolgreich = 0
    for kandidat in ziel:
        kontext = "%s(%s)" % (kandidat.get("id", "?"), kandidat.get("plattform", "?"))
        tmp = tempfile.mkdtemp(prefix="radar_audio_")
        try:
            mp3 = _audio_beschaffen(kandidat, tmp, fehler, kontext)
            if mp3:
                text = _gemini_transkribiere(mp3, fehler, kontext)
                if text:
                    kandidat["transkript"] = text
                    erfolgreich += 1
                    logger.info("Transkript %s: %d Zeichen (Audio).", kandidat.get("id"), len(text))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        time.sleep(SLEEP_ZWISCHEN_VIDEOS_S)

    print("[transkription] %d/%d Audio-Transkripte erfolgreich (%s)"
          % (erfolgreich, len(ziel),
             ", ".join(sorted(set(k.get("plattform", "?") for k in ziel)))))
    return erfolgreich
