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

import contextlib
import json
import os
import tempfile
import time
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


_VIDEOS_LOCK = os.path.join(DATEN_DIR, ".videos.lock")


@contextlib.contextmanager
def _videos_schreib_lock():
    """Exklusiver Datei-Lock um Read-Modify-Write von videos.json — gleiche
    Semantik wie lib/daten.ts (mitLock): App (Node) und Scraper teilen sich im
    Server-Betrieb dasselbe daten-Volume; ohne Lock kann ein Feedback der App
    verloren gehen, das zwischen Python-Read und -Write faellt.
    Nach Timeout laeuft der Schreiber trotzdem weiter (atomare Writes verhindern
    Korruption) — verwaiste Locks (>10 s) werden geraeumt."""
    erworben = False
    for _ in range(25):
        try:
            fd = os.open(_VIDEOS_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            erworben = True
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(_VIDEOS_LOCK) > 10:
                    os.remove(_VIDEOS_LOCK)
                    continue
            except OSError:
                pass
            time.sleep(0.12)
    try:
        yield
    finally:
        if erworben:
            try:
                os.remove(_VIDEOS_LOCK)
            except OSError:
                pass


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
        # v2-Pool: keine status-Spalte — Backfill nimmt die juengsten ohne Transkript
        zeilen = _supabase_get("videos", {
            "select": "*",
            "transkript": "is.null",
            "order": "gefunden_am.desc",
            "limit": "200",
        })
        return zeilen or []
    return [v for v in _lade_json(VIDEOS_DATEI, [])
            if not v.get("transkript") and v.get("status") in status_liste]


VORSCHLAEGE_DATEI = os.path.join(DATEN_DIR, "vorschlaege.json")


def lade_extra_queries(maximal=4):
    """Aktive Zusatz-Suchqueries aus Chris' Vorschlaegen (App schreibt sie mit Ablaufdatum).
    Lokal: daten/vorschlaege.json; Supabase: einstellungen-Key 'extra_queries'."""
    eintraege = []
    if daten_modus() == "supabase":
        zeilen = _supabase_get("einstellungen", {"select": "value", "key": "eq.extra_queries"})
        if zeilen and isinstance(zeilen[0].get("value"), list):
            eintraege = zeilen[0]["value"]
    else:
        eintraege = (_lade_json(VORSCHLAEGE_DATEI, {}) or {}).get("extra_queries", [])
    jetzt = jetzt_iso()
    aktiv = [e.get("query", "").strip() for e in eintraege
             if e.get("query") and str(e.get("bis", "")) > jetzt]
    return aktiv[:maximal]


def lade_rezept_extra_queries(maximal=4):
    """Aktive Zusatz-Suchqueries fuer den REZEPTE-Radar aus Chris' Vorschlaegen
    (gleicher Mechanismus wie lade_extra_queries, eigener Schluessel)."""
    eintraege = []
    if daten_modus() == "supabase":
        zeilen = _supabase_get("einstellungen", {"select": "value", "key": "eq.rezept_extra_queries"})
        if zeilen and isinstance(zeilen[0].get("value"), list):
            eintraege = zeilen[0]["value"]
    else:
        eintraege = (_lade_json(VORSCHLAEGE_DATEI, {}) or {}).get("rezept_extra_queries", [])
    jetzt = jetzt_iso()
    aktiv = [e.get("query", "").strip() for e in eintraege
             if e.get("query") and str(e.get("bis", "")) > jetzt]
    return aktiv[:maximal]


def lade_fuer_neubewertung():
    """Videos fuer die Bestands-Neubewertung: analysiert (claim vorhanden), aber noch
    ohne Websuche-Verifikation (claim.websuche fehlt = alte Pipeline), und nur solche,
    die der Nutzer noch nicht entschieden hat (status inbox/strittig/archiv)."""
    if daten_modus() == "supabase":
        # v2: Verdicts leben per-User in video_zuordnung — Neubewertung ist ein
        # Lokal-Modus-Werkzeug (per-User-Aequivalent waere ein Kurations-Neulauf).
        print("[speicher] lade_fuer_neubewertung: im Supabase-Modus nicht verfuegbar (v2).")
        return []
    return [v for v in _lade_json(VIDEOS_DATEI, [])
            if v.get("claim") and not v["claim"].get("websuche")
            and v.get("status") in ANALYSE_SCHREIBBAR]


def lade_unanalysierte():
    """Videos ohne Analyse (claim=null, status=inbox) vollstaendig laden — fuer --nachanalyse."""
    if daten_modus() == "supabase":
        # v2: Pool-Videos ohne Claim (Stufe A/B beim naechsten Akquise-Lauf faellig)
        zeilen = _supabase_get("videos", {"select": "*", "claim": "is.null",
                                          "order": "gefunden_am.desc", "limit": "200"})
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

    with _videos_schreib_lock():
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


def lade_einstellungen(user_id=None):
    """Einstellungen des Nutzers. Lokal: einstellungen.json (user_id ignoriert).
    Supabase (v2): einstellungen-Tabelle mit PK (user_id, key) — die App
    speichert das komplette Objekt unter key 'einstellungen'."""
    fallback = {"gelernt": {"themen_boost": {}, "notizen": []}, "zuletzt_gelernt": None}
    if daten_modus() == "supabase":
        params = {"select": "key,value", "key": "eq.einstellungen"}
        if user_id:
            params["user_id"] = "eq." + str(user_id)
        zeilen = _supabase_get("einstellungen", params)
        if zeilen:
            wert = zeilen[0].get("value") or {}
            return {"gelernt": wert.get("gelernt") or fallback["gelernt"],
                    "zuletzt_gelernt": wert.get("zuletzt_gelernt")}
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

    with _videos_schreib_lock():
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


def _normalisiere_aussage(text):
    """Aussage fuer Aehnlichkeitsvergleich vereinheitlichen (klein, ohne
    Satzzeichen/Mehrfach-Leerzeichen)."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\wäöüß ]", " ", (text or "").lower())).strip()


def markiere_dubletten(schwelle=0.85):
    """
    Fast-Dubletten zusammenfassen: Wenn DERSELBE Kanal mehrere geflaggte Videos
    (Status inbox/strittig) mit sehr aehnlicher Kernaussage hat, bleibt nur das
    reichweitenstaerkste in der Inbox — die anderen wandern nach 'archiv' mit
    Verweis 'dublette_von'. So sieht Christian nicht zweimal denselben Claim
    desselben Creators. Vergleich nur INNERHALB eines Kanals (verschiedene
    Creators mit gleichem Mythos bleiben getrennte, legitime Funde).
    Rueckgabe: Anzahl als Dublette archivierter Videos.
    """
    from difflib import SequenceMatcher

    if daten_modus() == "supabase":
        return 0  # (Supabase-Modus hier nicht aktiv)

    with _videos_schreib_lock():
        bestand = _lade_json(VIDEOS_DATEI, [])
        kandidaten = [v for v in bestand if v.get("status") in ("inbox", "strittig")
                      and (v.get("claim") or {}).get("aussage")]
        # nach Kanal gruppieren (kanal_id bevorzugt, sonst Name)
        nach_kanal = {}
        for v in kandidaten:
            schluessel = v.get("kanal_id") or v.get("kanal") or "?"
            nach_kanal.setdefault(schluessel, []).append(v)

        archiviert = 0
        for gruppe in nach_kanal.values():
            if len(gruppe) < 2:
                continue
            # staerkstes zuerst -> wird immer Behalter eines Clusters
            gruppe.sort(key=lambda v: (v.get("views") or 0), reverse=True)
            behalten = []  # (behalter, normalisierte_aussage)
            for v in gruppe:
                norm = _normalisiere_aussage((v["claim"] or {}).get("aussage"))
                treffer = None
                for behalter, b_norm in behalten:
                    if SequenceMatcher(None, norm, b_norm).ratio() >= schwelle:
                        treffer = behalter
                        break
                if treffer is None:
                    behalten.append((v, norm))
                else:
                    v["status"] = "archiv"
                    v["dublette_von"] = treffer.get("id")
                    archiviert += 1

        if archiviert:
            _schreibe_json_atomar(VIDEOS_DATEI, bestand)
    return archiviert


def speichere_agent_run(protokoll):
    """Ein agent_run-Protokoll anhaengen: {zeit, quelle, gefunden, neu, analysiert,
    geflaggt, fehler, dauer_s} — optional user_id (null = globaler Akquise-Lauf),
    typ (akquise|kuration|onboarding|lerner|rezepte) und detail (Token-/Kostenzaehler)."""
    protokoll.setdefault("zeit", jetzt_iso())
    if daten_modus() == "supabase":
        ok = _supabase_post("agent_runs", [
            {k: protokoll.get(k) for k in
             ("zeit", "quelle", "gefunden", "neu", "analysiert", "geflaggt",
              "fehler", "dauer_s", "such_protokoll", "user_id", "typ", "detail")
             if protokoll.get(k) is not None
             or k not in ("user_id", "typ", "detail", "such_protokoll")}
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
            # v2-Pool: KEINE status-Spalte (die lebt in video_zuordnung)
            "select": "id,views,likes,kommentare,transkript,caption,kanal_follower,dauer_s,thumbnail_url",
            "limit": "1000",
            "offset": str(seite * 1000),
        })
        if zeilen is None:
            return alle
        alle.extend(zeilen)
        if len(zeilen) < 1000:
            return alle
        seite += 1


# Spalten der v2-POOL-Tabelle `videos` (mandantenneutral). Alles Nutzer-
# spezifische (status/score/scores/skripte/feedback/dublette_von) lebt in
# video_zuordnung und wird beim Pool-Insert verworfen.
POOL_FELDER = (
    "id", "plattform", "video_id", "url", "titel", "kanal", "kanal_id",
    "kanal_follower", "veroeffentlicht", "views", "likes", "kommentare",
    "dauer_s", "thumbnail_url", "caption", "transkript", "sprache",
    "quelle", "quelle_query", "gefunden_am", "claim", "webcheck",
    "kategorie", "claim_embedding",
)


def _nur_pool_felder(kandidat):
    # ALLE Pool-Spalten ausgeben (fehlende als None): PostgREST-Bulk-Inserts
    # verlangen identische Schluessel in allen Zeilen eines Batches (PGRST102).
    zeile = {k: kandidat.get(k) for k in POOL_FELDER}
    if not zeile.get("gefunden_am"):
        zeile["gefunden_am"] = jetzt_iso()
    return zeile


def _supabase_speichere_videos(kandidaten):
    """
    Merge-Semantik wie lokal: bestehende ids -> nur Metriken per PATCH,
    neue ids -> komplett per POST einfuegen (v2: nur POOL-Spalten).
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
    neue_zeilen = [_nur_pool_felder(z) for z in neue_zeilen]
    for i in range(0, len(neue_zeilen), 200):
        batch = neue_zeilen[i:i + 200]
        if _supabase_post("videos", batch,
                          prefer="return=minimal,resolution=ignore-duplicates"):
            neu += len(batch)
    return neu, aktualisiert


# ---------------------------------------------------------------------------
# Multi-Tenant (Phase 1): Profile, Video-Zuordnungen, Auftrags-Queue.
# Nur im Supabase-Modus aktiv — der Lokal-Modus bleibt Single-User ("lokal").
# ---------------------------------------------------------------------------

def _supabase_patch(tabelle, params, felder):
    """Generisches PATCH auf eine Tabelle (params = PostgREST-Filter)."""
    if requests is None or not felder:
        return False
    try:
        r = requests.patch(_supabase_url(tabelle), headers=_supabase_headers(),
                           params=params, data=json.dumps(felder), timeout=30)
        if r.status_code >= 400:
            print("[speicher] Supabase PATCH %s fehlgeschlagen: %s %s"
                  % (tabelle, r.status_code, r.text[:200]))
            return False
        return True
    except Exception as e:
        print("[speicher] Supabase PATCH %s Fehler: %s" % (tabelle, e))
        return False


def _supabase_rpc(funktion, argumente):
    """PostgREST-RPC (z.B. match_narrativ). Rueckgabe: JSON oder None."""
    if requests is None:
        return None
    try:
        url = os.environ.get("SUPABASE_URL", "").rstrip("/") + "/rest/v1/rpc/" + funktion
        r = requests.post(url, headers=_supabase_headers(),
                          data=json.dumps(argumente), timeout=30)
        if r.status_code >= 400:
            print("[speicher] Supabase RPC %s fehlgeschlagen: %s %s"
                  % (funktion, r.status_code, r.text[:200]))
            return None
        return r.json()
    except Exception as e:
        print("[speicher] Supabase RPC %s Fehler: %s" % (funktion, e))
        return None


def lade_nutzer_aktiv():
    """Alle aktiven Nutzer (Onboarding fertig, nicht geloescht) mit Profil,
    Themen und Plan — die Iterationsbasis fuer Kurations-/Lerner-Laeufe.
    Rueckgabe: Liste von {id, plan, profil, themen} (leer im Lokal-Modus)."""
    if daten_modus() != "supabase":
        return []
    profile = _supabase_get("profiles", {
        "select": "id,plan,limits,onboarding_status,geloescht_am",
        "onboarding_status": "eq.fertig",
        "geloescht_am": "is.null",
    }) or []
    nutzer = []
    for p in profile:
        nutzer.append({
            "id": p["id"],
            "plan": p.get("plan") or "free",
            "limits": p.get("limits") or {},
            "profil": lade_profil(p["id"]),
            "themen": lade_themen(p["id"]),
        })
    return nutzer


def lade_profil(user_id):
    """radar_profile-Zeile des Nutzers (Positionen, Stilguide, Trigger, ...)."""
    zeilen = _supabase_get("radar_profile", {"select": "*", "user_id": "eq." + str(user_id)})
    return (zeilen or [{}])[0] if zeilen else {}


def speichere_profil(user_id, felder):
    """radar_profile upserten (z.B. Onboarding-Ergebnis, Lerner-Update)."""
    felder = dict(felder)
    felder["user_id"] = str(user_id)
    felder["aktualisiert_am"] = jetzt_iso()
    return _supabase_post("radar_profile", [felder],
                          prefer="return=minimal,resolution=merge-duplicates")


def lade_themen(user_id, nur_aktive=True):
    params = {"select": "*", "user_id": "eq." + str(user_id)}
    if nur_aktive:
        params["aktiv"] = "is.true"
    return _supabase_get("themen", params) or []


def lade_watchlist_personen(user_id, nur_gefolgte=True):
    params = {"select": "*", "user_id": "eq." + str(user_id)}
    if nur_gefolgte:
        params["folgt"] = "is.true"
    return _supabase_get("watchlist_personen", params) or []


def lade_zuordnungen(user_id, status_liste=None, select="*"):
    """video_zuordnung-Zeilen des Nutzers (optional nach Status gefiltert)."""
    params = {"select": select, "user_id": "eq." + str(user_id)}
    if status_liste:
        params["status"] = "in.(%s)" % ",".join(status_liste)
    return _supabase_get("video_zuordnung", params) or []


def speichere_zuordnungen(user_id, zeilen):
    """Neue Inbox-Zuordnungen anlegen (Kurationslauf). Bestehende Zuordnungen
    werden NICHT ueberschrieben (ignore-duplicates) — Nutzer-Entscheidungen
    (status/feedback) bleiben unantastbar. Rueckgabe: Anzahl versucht."""
    if not zeilen:
        return 0
    for z in zeilen:
        z["user_id"] = str(user_id)
        z.setdefault("zugeordnet_am", jetzt_iso())
    # PostgREST-Bulk verlangt identische Keys in allen Zeilen (PGRST102):
    # archiv-Zeilen (ohne score/scores) und geflaggte (mit) auf die
    # Key-Union normalisieren, fehlende Werte als None.
    alle_keys = set()
    for z in zeilen:
        alle_keys.update(z.keys())
    zeilen = [{k: z.get(k) for k in alle_keys} for z in zeilen]
    ok = _supabase_post("video_zuordnung", zeilen,
                        prefer="return=minimal,resolution=ignore-duplicates")
    return len(zeilen) if ok else 0


def zugeordnete_video_ids(user_id):
    """IDs aller Videos, die dem Nutzer schon zugeordnet sind (Dedupe der Kuration)."""
    zeilen = lade_zuordnungen(user_id, select="video_id")
    return {z.get("video_id") for z in zeilen if z.get("video_id")}


def lade_pool_neu(seit_iso, mit_claim=True):
    """Pool-Videos fuer die Kuration: seit `seit_iso` gefunden, mit extrahiertem
    Claim (Stufe A/B gelaufen). Paginierend, komplette Zeilen."""
    alle, seite = [], 0
    # gefunden_am ODER aktualisiert_am im Fenster: Claims, die erst spaeter
    # (Backfill/Nachanalyse) extrahiert wurden, sollen nicht durchs Raster fallen.
    params_basis = {"select": "*",
                    "or": "(gefunden_am.gte.%s,aktualisiert_am.gte.%s)" % (seit_iso, seit_iso),
                    "order": "gefunden_am.desc"}
    if mit_claim:
        params_basis["claim"] = "not.is.null"
    while True:
        params = dict(params_basis)
        params["limit"] = "1000"
        params["offset"] = str(seite * 1000)
        zeilen = _supabase_get("videos", params)
        if zeilen is None:
            return alle
        alle.extend(zeilen)
        if len(zeilen) < 1000:
            return alle
        seite += 1


def hole_thema_embedding(user_id, slug, thema):
    """Embedding eines Nutzer-Themas — gecacht in themen.embedding, sonst
    einmalig berechnet (Name + Keywords) und zurueckgeschrieben."""
    zeilen = _supabase_get("themen", {
        "select": "embedding", "user_id": "eq." + str(user_id), "slug": "eq." + slug,
    }) or []
    roh = zeilen[0].get("embedding") if zeilen else None
    if roh:
        # pgvector kommt als String "[0.1,...]" ueber REST
        if isinstance(roh, str):
            try:
                roh = json.loads(roh)
            except ValueError:
                roh = None
        if roh:
            return roh
    try:
        import narrativ
        text = "%s: %s" % (thema.get("name") or slug,
                           ", ".join(thema.get("keywords") or []))
        vektor = narrativ.embed_text(text, dim=768, task="RETRIEVAL_QUERY")
    except Exception as e:
        print("[speicher] Thema-Embedding %s fehlgeschlagen: %s" % (slug, e))
        return None
    if vektor:
        _supabase_patch("themen", {"user_id": "eq." + str(user_id), "slug": "eq." + slug},
                        {"embedding": vektor})
    return vektor or None


def speichere_webcheck(video_id, webcheck):
    """Websuche-Ergebnis am Pool-Video cachen — nachfolgende Nutzer sparen den Call."""
    return _supabase_patch("videos", {"id": "eq." + str(video_id)},
                           {"webcheck": webcheck, "aktualisiert_am": jetzt_iso()})


# --- Auftrags-Queue (ersetzt .lauf_anfrage im Supabase-Modus) ---------------

def hole_offene_auftraege(typ=None, limit=5):
    """Offene Auftraege, aelteste zuerst. typ optional (lauf|onboarding|kuration|lerner)."""
    if daten_modus() != "supabase":
        return []
    params = {"select": "*", "status": "eq.offen",
              "order": "erstellt_am.asc", "limit": str(limit)}
    if typ:
        params["typ"] = "eq." + typ
    return _supabase_get("auftraege", params) or []


def claim_auftrag(auftrag_id):
    """Auftrag atomar claimen: offen -> laeuft. False, wenn ihn schon jemand hat
    (der status=eq.offen-Filter macht das PATCH zum Compare-and-Swap)."""
    return _supabase_patch("auftraege",
                           {"id": "eq." + str(auftrag_id), "status": "eq.offen"},
                           {"status": "laeuft", "gestartet_am": jetzt_iso()})


def schliesse_auftrag(auftrag_id, ok=True, fehler_text=None):
    felder = {"status": "fertig" if ok else "fehler", "beendet_am": jetzt_iso()}
    if fehler_text:
        felder["fehler_text"] = str(fehler_text)[:500]
    return _supabase_patch("auftraege", {"id": "eq." + str(auftrag_id)}, felder)


if __name__ == "__main__":
    print("Modus:", daten_modus())
    print("Bestand:", len(lade_videos()), "Videos")
