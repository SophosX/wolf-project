#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Einmalige Migration: lokale daten/*.json -> Supabase.
Nutzung: SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python3 migriere_lokal_zu_supabase.py"""
import json
import os
import sys

os.environ["DATEN_MODUS"] = "supabase"
import speicher  # noqa: E402

DATEN = speicher.DATEN_DIR


def lade(name):
    pfad = os.path.join(DATEN, name)
    if not os.path.exists(pfad):
        return []
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def main():
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY fehlen")

    videos = lade("videos.json")
    if videos:
        neu, aktualisiert = speicher.speichere_videos(videos)
        # Analyse-Felder nachziehen (speichere_videos schreibt bei Bestehenden nur Metriken)
        analysierte = [v for v in videos if v.get("claim")]
        n = speicher.aktualisiere_analyse(analysierte)
        print("videos: %d neu, %d aktualisiert, %d Analyse-Felder gesetzt" % (neu, aktualisiert, n))

    for run in lade("agent_runs.json"):
        speicher.speichere_agent_run(run)
    print("agent_runs migriert: %d" % len(lade("agent_runs.json")))

    einst = lade("einstellungen.json")
    if isinstance(einst, dict) and einst.get("gelernt"):
        speicher._supabase_post("einstellungen", [{"key": "gelernt", "value": einst["gelernt"]}],
                                prefer="resolution=merge-duplicates")
        print("einstellungen migriert")

    print("FERTIG — Supabase Table Editor gegenpruefen.")


if __name__ == "__main__":
    main()
