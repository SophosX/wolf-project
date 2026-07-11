# -*- coding: utf-8 -*-
"""
worker.py — Minuten-Worker fuer die Auftrags-Queue (nur Supabase-Modus).

Die App legt Auftraege in der Tabelle `auftraege` an ("Jetzt suchen" = typ lauf,
Onboarding-Import = typ onboarding, ...). Dieser Worker wird minuetlich vom
Cron gestartet (flock-geschuetzt), claimt offene Auftraege atomar
(Compare-and-Swap ueber status=offen) und arbeitet sie ab.

Im Lokal-Modus macht er nichts — dort gilt weiter die .lauf_anfrage-Flag-Datei.
"""

import os
import subprocess
import sys

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

import speicher

MAX_AUFTRAEGE_PRO_TICK = 3


def _run(cmd):
    """Subprozess mit durchgereichtem Output; Rueckgabe True bei Exit 0."""
    print("[worker] starte: %s" % " ".join(cmd))
    ergebnis = subprocess.run(cmd, cwd=SCRAPER_DIR)
    return ergebnis.returncode == 0


def bearbeite(auftrag):
    typ = auftrag.get("typ")
    user_id = auftrag.get("user_id")
    if typ == "lauf":
        # "Jetzt suchen": frische Akquise (Cooldown haelt die Kosten klein —
        # kuerzlich gescrapte Queries werden uebersprungen), dann Kuration
        # fuer den anfragenden Nutzer.
        ok = _run([sys.executable, "-u", "lauf.py", "--nur", "youtube,tiktok"])
        if user_id:
            ok = _run([sys.executable, "-u", "kuration.py", "--user", str(user_id)]) and ok
        return ok
    if typ == "kuration":
        if not user_id:
            return False
        return _run([sys.executable, "-u", "kuration.py", "--user", str(user_id)])
    if typ == "onboarding":
        if not user_id:
            return False
        return _run([sys.executable, "-u", "onboarding_agent.py", "--user", str(user_id)])
    if typ == "lerner":
        cmd = [sys.executable, "-u", "profil_lerner.py"]
        if user_id:
            cmd += ["--user", str(user_id)]
        return _run(cmd)
    print("[worker] Unbekannter Auftrags-Typ: %s" % typ)
    return False


def main():
    if speicher.daten_modus() != "supabase":
        return 0
    auftraege = speicher.hole_offene_auftraege(limit=MAX_AUFTRAEGE_PRO_TICK)
    if not auftraege:
        return 0
    for auftrag in auftraege:
        if not speicher.claim_auftrag(auftrag["id"]):
            continue  # ein anderer Worker war schneller
        print("[worker] Auftrag %s (typ=%s, user=%s)"
              % (auftrag["id"], auftrag.get("typ"), auftrag.get("user_id")))
        try:
            ok = bearbeite(auftrag)
            speicher.schliesse_auftrag(auftrag["id"], ok=ok,
                                       fehler_text=None if ok else "Teil-Schritt fehlgeschlagen")
        except Exception as e:
            print("[worker] FEHLER bei Auftrag %s: %s" % (auftrag["id"], e))
            speicher.schliesse_auftrag(auftrag["id"], ok=False, fehler_text=str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
