# -*- coding: utf-8 -*-
"""
Wolf Radar — Live-Status des Scrapers fuer die App (/agenten).

Schreibt daten/agent_status.json ATOMAR (temp + rename), waehrend ein Lauf
laeuft: aktuelle Phase, ein Schritt-Protokoll im "Thinking"-Stil und laufende
Zaehler. Die App pollt die Datei und zeigt Christian live, was der Radar tut.

Bewusst fehlertolerant: Status ist Komfort, nie Pflicht — jede Exception wird
geschluckt, damit ein Status-Problem NIEMALS einen Lauf abbricht.
"""
import json
import os
import tempfile

import speicher

STATUS_DATEI = os.path.join(speicher.DATEN_DIR, "agent_status.json")
MAX_SCHRITTE = 60  # Ringpuffer: alte Schritte fallen raus

_status = None


def _schreiben():
    """Atomar schreiben: temp-Datei im selben Verzeichnis, dann rename."""
    if _status is None:
        return
    try:
        os.makedirs(speicher.DATEN_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".agent_status_", suffix=".tmp",
                                   dir=speicher.DATEN_DIR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_status, f, ensure_ascii=False)
        os.replace(tmp, STATUS_DATEI)
    except Exception:
        pass  # Status ist Komfort — nie den Lauf gefaehrden


def start(modus, quellen=None):
    """Neuen Lauf beginnen. modus: 'lauf' | 'transkription' | 'nachanalyse' | 'neubewertung'"""
    global _status
    try:
        _status = {
            "aktiv": True,
            "modus": modus,
            "quellen": quellen or [],
            "gestartet": speicher.jetzt_iso(),
            "beendet": None,
            "phase": "Radar startet …",
            "schritte": [],
            "zaehler": {"gefunden": 0, "neu": 0, "analysiert": 0, "geflaggt": 0},
            "ergebnis": None,
        }
        _schreiben()
    except Exception:
        pass


def phase(text):
    """Neue Arbeitsphase — erscheint als Ueberschrift UND als Schritt."""
    global _status
    try:
        if _status is None:
            return
        _status["phase"] = text
        schritt(text, typ="phase")
    except Exception:
        pass


def schritt(text, typ="info"):
    """Einen Schritt ins Live-Protokoll haengen (typ: 'phase'|'info'|'erfolg')."""
    global _status
    try:
        if _status is None:
            return
        _status["schritte"].append(
            {"zeit": speicher.jetzt_iso(), "text": text, "typ": typ})
        _status["schritte"] = _status["schritte"][-MAX_SCHRITTE:]
        _schreiben()
    except Exception:
        pass


def zaehler(**kw):
    """Laufende Zaehler erhoehen/setzen (gefunden, neu, analysiert, geflaggt)."""
    global _status
    try:
        if _status is None:
            return
        for k, v in kw.items():
            _status["zaehler"][k] = _status["zaehler"].get(k, 0) + int(v)
        _schreiben()
    except Exception:
        pass


def ende(ergebnis_text=None):
    """Lauf abschliessen; ergebnis_text ist die Christian-taugliche Kurzbilanz."""
    global _status
    try:
        if _status is None:
            return
        _status["aktiv"] = False
        _status["beendet"] = speicher.jetzt_iso()
        _status["phase"] = "Fertig"
        if ergebnis_text:
            _status["ergebnis"] = ergebnis_text
            schritt(ergebnis_text, typ="erfolg")
        else:
            _schreiben()
        _status = None
    except Exception:
        pass
