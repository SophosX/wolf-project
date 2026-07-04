# -*- coding: utf-8 -*-
"""
Wolf Radar — Persistenz (Kontrakt-konform)

DATEN_MODUS=lokal    -> JSON-Dateien in <repo>/daten/ (atomar geschrieben)
DATEN_MODUS=supabase -> Upsert via Supabase-REST (plain requests, Service-Key)

Merge-Semantik (beide Modi identisch):
- Neue Videos werden komplett eingefuegt.
- Bestehende Videos (gleiche id): NUR Metriken aktualisieren
  (views/likes/kommentare, plus transkript/caption falls vorher leer).
  status / feedback / skripte / claim / score werden NIE ueberschrieben.
"""

import json
import os
import tempfile
from datetime import datetime, timezone

try:
    import requests
except ImportError:  # requests fehlt nur in kaputten Umgebungen
    requests = None

# Pfade: scraper/ liegt im Repo-Root, daten/ daneben
SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRAPER_DIR)
DATEN_DIR = os.path.join(REPO_DIR, "daten")

VIDEOS_DATEI = os.path.join(DATEN_DIR, "videos.json")
AGENT_RUNS_DATEI = os.path.join(DATEN_DIR, "agent_runs.json")
EINSTELLUNGEN_DATEI = os.path.join(DATEN_DIR, "einstellungen.json")

# Felder, die bei bestehenden Videos aktualisiert werden duerfen (Metriken)
METRIK_FELDER = ("views", "likes", "kommentare")
# Felder, die nur nachgetragen werden, wenn sie vorher leer waren
NACHTRAG_FELDER = ("transkript", "caption", "kanal_follower", "dauer_s", "thumbnail_url")


def daten_modus():
    """'supabase' nur wenn explizit gesetzt UND SUPABASE_URL vorhanden, sonst 'lokal'."""
    modus = os.environ.get("DATEN_MODUS", "").strip().lower()
    if modus == "supabase" and os.environ.get("SUPABASE_URL"):
        return "supabase"
    return "lokal"


def jetzt_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Lokal-Modus: atomare JSON-Dateien
# ---------------------------------------------------------------------------

def _lade_json(pfad, fallback):
    if not os.path.exists(pfad):
        return fallback
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print("[speicher] WARNUNG: %s nicht lesbar (%s) — starte mit leerem Bestand" % (pfad, e))
        return fallback


def _schreibe_json_atomar(pfad, daten):
    """Atomar schreiben: erst Temp-Datei im selben Ordner, dann os.replace."""
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    fd, tmp_pfad = tempfile.mkstemp(dir=os.path.dirname(pfad), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=1)
        os.replace(tmp_pfad, pfad)
    except BaseException:
        if os.path.exists(tmp_pfad):
            os.remove(tmp_pfad)
        raise


def lade_videos():
    """Bestand laden. Lokal: aus videos.json. Supabase: alle Zeilen (id-Sicht reicht meist)."""
    if daten_modus() == "supabase":
        return _supabase_lade_videos()
    return _lade_json(VIDEOS_DATEI, [])


def lade_ohne_transkript(status_liste=("inbox", "strittig", "angenommen", "gespeichert")):
    """Videos ohne Transkript (fuer den Transkriptions-Backfill) vollstaendig laden.
    Default: nur Videos, mit denen Chris arbeitet (kein Archiv-Ballast)."""
    if daten_modus() == "supabase":
        zeilen = _supabase_get("videos", {
            "select": "*",
            "transkript": "is.null",
            "status": "in.(%s)" % ",".join(status_liste),
        })
        return zeilen or []
    return [v for v in _lade_json(VIDEOS_DATEI, [])
            if not v.get("transkript") and v.get("status") in status_liste]


def lade_unanalysierte():
    """Videos ohne Analyse (claim=null, status=inbox) vollstaendig laden — fuer --nachanalyse."""
    if daten_modus() == "supabase":
        zeilen = _supabase_get("videos", {"select": "*", "claim": "is.null", "status": "eq.inbox"})
        return zeilen or []
    return [v for v in _lade_json(VIDEOS_DATEI, [])
            if not v.get("claim") and v.get("status") == "inbox"]


# Analyse-Ergebnisse duerfen NUR geschrieben werden, solange der Nutzer noch
# keine Entscheidung getroffen hat (status noch inbox/strittig/archiv).
ANALYSE_FELDER = ("claim", "score", "scores", "skripte", "status")
ANALYSE_SCHREIBBAR = ("inbox", "strittig", "archiv")


def aktualisiere_analyse(videos):
    """Nachtraegliche Analyse-Ergebnisse in bestehende Videos schreiben.
    Rueckgabe: Anzahl aktualisierter Videos."""
    if daten_modus() == "supabase":
        n = 0
        for v in videos:
            felder = {f: v.get(f) for f in ANALYSE_FELDER if v.get(f) is not None}
            if not felder:
                continue
            # Status-Guard serverseitig: nur patchen, wenn status noch schreibbar ist
            if requests is None:
                break
            url = _supabase_url("videos") + ("?id=eq.%s&status=in.(%s)"
                                             % (v["id"], ",".join(ANALYSE_SCHREIBBAR)))
            r = requests.patch(url, headers=_supabase_headers(), json=felder, timeout=30)
            if r.status_code < 400:
                n += 1
            else:
                print("[speicher] Nachanalyse-PATCH %s fehlgeschlagen: %s" % (v["id"], r.status_code))
        return n

    bestand = _lade_json(VIDEOS_DATEI, [])
    index = {v.get("id"): v for v in bestand}
    n = 0
    for v in videos:
        ziel = index.get(v.get("id"))
        if not ziel or ziel.get("status") not in ANALYSE_SCHREIBBAR:
            continue
        geaendert = False
        for f in ANALYSE_FELDER:
            if v.get(f) is not None:
                ziel[f] = v[f]
                geaendert = True
        if geaendert:
            n += 1
    _schreibe_json_atomar(VIDEOS_DATEI, bestand)
    return n


def lade_einstellungen():
    fallback = {"gelernt": {"themen_boost": {}, "notizen": []}, "zuletzt_gelernt": None}
    if daten_modus() == "supabase":
        zeilen = _supabase_get("einstellungen", {"select": "key,value"})
        if zeilen is None:
            return fallback
        for zeile in zeilen:
            if zeile.get("key") == "gelernt":
                return {"gelernt": zeile.get("value") or fallback["gelernt"],
                        "zuletzt_gelernt": None}
        return fallback
    return _lade_json(EINSTELLUNGEN_DATEI, fallback)


def _merge_video(bestehend, neu):
    """Metriken des bestehenden Videos aktualisieren, Rest unangetastet lassen."""
    geaendert = False
    for feld in METRIK_FELDER:
        wert = neu.get(feld)
        if wert is not None and wert != bestehend.get(feld):
            bestehend[feld] = wert
            geaendert = True
    for feld in NACHTRAG_FELDER:
        if not bestehend.get(feld) and neu.get(feld):
            bestehend[feld] = neu[feld]
            geaendert = True
    return geaendert


def speichere_videos(kandidaten):
    """
    Kandidaten in den Bestand mergen.
    Rueckgabe: (anzahl_neu, anzahl_aktualisiert)
    """
    if daten_modus() == "supabase":
        return _supabase_speichere_videos(kandidaten)

    bestand = _lade_json(VIDEOS_DATEI, [])
    index = {}
    for v in bestand:
        index[v.get("id")] = v

    neu, aktualisiert = 0, 0
    for kand in kandidaten:
        vid = kand.get("id")
        if not vid:
            continue
        if vid in index:
            if _merge_video(index[vid], kand):
                aktualisiert += 1
        else:
            bestand.append(kand)
            index[vid] = kand
            neu += 1

    _schreibe_json_atomar(VIDEOS_DATEI, bestand)
    return neu, aktualisiert


def speichere_agent_run(protokoll):
    """Ein agent_run-Protokoll anhaengen: {zeit, quelle, gefunden, neu, analysiert, geflaggt, fehler, dauer_s}"""
    protokoll.setdefault("zeit", jetzt_iso())
    if daten_modus() == "supabase":
        ok = _supabase_post("agent_runs", [
            {k: protokoll.get(k) for k in
             ("zeit", "quelle", "gefunden", "neu", "analysiert", "geflaggt", "fehler", "dauer_s")}
        ])
        if not ok:
            print("[speicher] WARNUNG: agent_run konnte nicht nach Supabase geschrieben werden")
        return
    runs = _lade_json(AGENT_RUNS_DATEI, [])
    runs.append(protokoll)
    # Nur die letzten 500 Laeufe behalten, Datei klein halten
    _schreibe_json_atomar(AGENT_RUNS_DATEI, runs[-500:])


def stelle_einstellungen_sicher():
    """Lokal: einstellungen.json anlegen, falls fehlend (App erwartet die Datei)."""
    if daten_modus() == "supabase":
        return
    if not os.path.exists(EINSTELLUNGEN_DATEI):
        _schreibe_json_atomar(EINSTELLUNGEN_DATEI, {
            "gelernt": {"themen_boost": {}, "notizen": []},
            "zuletzt_gelernt": None,
        })


# ---------------------------------------------------------------------------
# Supabase-Modus: plain REST mit Service-Key (kein supabase-py)
# ---------------------------------------------------------------------------

def _supabase_headers():
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    }


def _supabase_url(tabelle):
    basis = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return basis + "/rest/v1/" + tabelle


def _supabase_get(tabelle, params):
    if requests is None:
        return None
    try:
        r = requests.get(_supabase_url(tabelle), headers=_supabase_headers(),
                         params=params, timeout=30)
        if r.status_code >= 400:
            print("[speicher] Supabase GET %s fehlgeschlagen: %s %s" % (tabelle, r.status_code, r.text[:200]))
            return None
        return r.json()
    except Exception as e:
        print("[speicher] Supabase GET %s Fehler: %s" % (tabelle, e))
        return None


def _supabase_post(tabelle, zeilen, prefer="return=minimal"):
    if requests is None or not zeilen:
        return bool(zeilen) is False
    try:
        headers = dict(_supabase_headers())
        headers["Prefer"] = prefer
        r = requests.post(_supabase_url(tabelle), headers=headers,
                          data=json.dumps(zeilen), timeout=60)
        if r.status_code >= 400:
            print("[speicher] Supabase POST %s fehlgeschlagen: %s %s" % (tabelle, r.status_code, r.text[:200]))
            return False
        return True
    except Exception as e:
        print("[speicher] Supabase POST %s Fehler: %s" % (tabelle, e))
        return False


def _supabase_patch_video(video_id, felder):
    if requests is None or not felder:
        return False
    try:
        r = requests.patch(_supabase_url("videos"), headers=_supabase_headers(),
                           params={"id": "eq." + video_id},
                           data=json.dumps(felder), timeout=30)
        if r.status_code >= 400:
            print("[speicher] Supabase PATCH %s fehlgeschlagen: %s %s" % (video_id, r.status_code, r.text[:200]))
            return False
        return True
    except Exception as e:
        print("[speicher] Supabase PATCH %s Fehler: %s" % (video_id, e))
        return False


def _supabase_lade_videos():
    """Bestand aus Supabase (nur Felder, die die Pipeline braucht: dedupe + merge)."""
    alle = []
    seite = 0
    while True:
        zeilen = _supabase_get("videos", {
            "select": "id,views,likes,kommentare,transkript,caption,kanal_follower,dauer_s,thumbnail_url,status",
            "limit": "1000",
            "offset": str(seite * 1000),
        })
        if zeilen is None:
            return alle
        alle.extend(zeilen)
        if len(zeilen) < 1000:
            return alle
        seite += 1


def _supabase_speichere_videos(kandidaten):
    """
    Merge-Semantik wie lokal: bestehende ids -> nur Metriken per PATCH,
    neue ids -> komplett per POST einfuegen.
    """
    bestand = _supabase_lade_videos()
    vorhandene = {}
    for zeile in bestand:
        vorhandene[zeile.get("id")] = zeile

    neue_zeilen = []
    neu, aktualisiert = 0, 0
    for kand in kandidaten:
        vid = kand.get("id")
        if not vid:
            continue
        if vid in vorhandene:
            update = {}
            alt = vorhandene[vid]
            for feld in METRIK_FELDER:
                wert = kand.get(feld)
                if wert is not None and wert != alt.get(feld):
                    update[feld] = wert
            for feld in NACHTRAG_FELDER:
                if not alt.get(feld) and kand.get(feld):
                    update[feld] = kand[feld]
            if update and _supabase_patch_video(vid, update):
                aktualisiert += 1
        else:
            neue_zeilen.append(kand)

    # Neue Zeilen in Batches einfuegen; ignore-duplicates schuetzt vor Rennen
    # mit parallelen Laeufen (on conflict id: nichts ueberschreiben).
    for i in range(0, len(neue_zeilen), 200):
        batch = neue_zeilen[i:i + 200]
        if _supabase_post("videos", batch,
                          prefer="return=minimal,resolution=ignore-duplicates"):
            neu += len(batch)
    return neu, aktualisiert


if __name__ == "__main__":
    print("Modus:", daten_modus())
    print("Bestand:", len(lade_videos()), "Videos")
