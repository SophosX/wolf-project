#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migriere_tenant_christian.py — Christian wird Tenant #1 (Cutover Phase 3).

Migriert den kompletten Single-Tenant-Bestand in das v2-Multi-Tenant-Schema:
  1. Auth-Nutzer anlegen (GoTrue-Admin-API) -> profiles (admin, pro, fertig, Marke "Wolf")
  2. radar_profile   <- wissen/ (stilguide, playbook, wissensbasis: interessen_profil
                        + reaktions_ausloeser als lebende Trigger-Liste)
  3. themen          <- mythen_katalog.THEMEN
  4. suchqueries     <- SUCHQUERIES (youtube) + SOCIAL_SUCHQUERIES (tiktok)
                        + SOCIAL_HASHTAGS (instagram)
  5. watchlist_personen <- watchlist.json + wissensbasis.personen (Reaktions-Historie)
  6. narrativ_chunks <- wissen/narrativ_index.json (re-embedded auf 768, Index ist 512)
  7. videos (POOL) + video_zuordnung <- daten/videos.json
  8. einstellungen/vorschlaege/rezepte/agent_runs <- daten/*.json

Idempotent: alles laeuft ueber Upserts (merge-duplicates) bzw. ignore-duplicates.
Am Ende druckt das Skript einen Zaehl-Report Quelle vs. Ziel.

Nutzung (auf dem Server, daten/ = Docker-Volume):
  SUPABASE_URL=... SUPABASE_SERVICE_KEY=... GEMINI_API_KEY=... \\
  python3 migriere_tenant_christian.py --email chris@... --passwort '...' \\
      [--daten-dir /var/lib/docker/volumes/wolf-project_daten/_data] [--ohne-narrativ]
"""

import argparse
import json
import os
import sys
import time

SCRAPER_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRAPER_DIR not in sys.path:
    sys.path.insert(0, SCRAPER_DIR)

os.environ["DATEN_MODUS"] = "supabase"

import requests

import speicher  # noqa: E402

WISSEN = os.path.join(SCRAPER_DIR, "wissen")


def lade_json(pfad, fallback):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return fallback


def lade_text(pfad):
    try:
        with open(pfad, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _admin_headers():
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return {"apikey": key, "Authorization": "Bearer " + key,
            "Content-Type": "application/json"}


def _auth_url(pfad):
    return os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1" + pfad


def nutzer_anlegen(email, passwort):
    """Auth-Nutzer anlegen (oder bestehenden per E-Mail finden). Rueckgabe: uuid."""
    r = requests.post(_auth_url("/admin/users"), headers=_admin_headers(), json={
        "email": email, "password": passwort, "email_confirm": True,
        "user_metadata": {"anzeige_name": "Christian Wolf"},
    }, timeout=30)
    if r.status_code < 400:
        uid = r.json().get("id")
        print("[migration] Auth-Nutzer angelegt: %s" % uid)
        return uid
    # existiert vermutlich schon -> suchen
    print("[migration] Anlegen: %s %s — suche bestehenden Nutzer" % (r.status_code, r.text[:120]))
    seite = 1
    while seite <= 10:
        r = requests.get(_auth_url("/admin/users?page=%d&per_page=100" % seite),
                         headers=_admin_headers(), timeout=30)
        r.raise_for_status()
        nutzer = r.json().get("users") or []
        for n in nutzer:
            if (n.get("email") or "").lower() == email.lower():
                print("[migration] Bestehender Auth-Nutzer: %s" % n["id"])
                return n["id"]
        if len(nutzer) < 100:
            break
        seite += 1
    raise RuntimeError("Auth-Nutzer konnte weder angelegt noch gefunden werden.")


def upsert(tabelle, zeilen, konflikt=None):
    if not zeilen:
        return 0
    prefer = "return=minimal,resolution=merge-duplicates"
    url = speicher._supabase_url(tabelle)
    if konflikt:
        url += "?on_conflict=" + konflikt
    headers = dict(speicher._supabase_headers())
    headers["Prefer"] = prefer
    # PostgREST-Bulk: alle Zeilen eines Batches muessen dieselben Keys haben
    alle_keys = set()
    for z in zeilen:
        alle_keys.update(z.keys())
    zeilen = [{k: z.get(k) for k in alle_keys} for z in zeilen]
    ok = 0
    for i in range(0, len(zeilen), 200):
        batch = zeilen[i:i + 200]
        r = requests.post(url, headers=headers, data=json.dumps(batch), timeout=60)
        if r.status_code >= 400:
            print("[migration] Upsert %s fehlgeschlagen: %s %s"
                  % (tabelle, r.status_code, r.text[:300]))
        else:
            ok += len(batch)
    return ok


def zaehle(tabelle, user_id=None):
    headers = dict(speicher._supabase_headers())
    headers["Prefer"] = "count=exact"
    params = {"select": "count"}
    if user_id:
        params["user_id"] = "eq." + user_id
    r = requests.get(speicher._supabase_url(tabelle), headers=headers,
                     params=params, timeout=30)
    try:
        return int(r.headers.get("Content-Range", "/0").split("/")[-1])
    except ValueError:
        return -1


ZUORDNUNG_FELDER = ("status", "score", "scores", "skripte", "feedback", "dublette_von")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--passwort", required=True)
    parser.add_argument("--daten-dir", default=None,
                        help="Pfad zum daten/-Ordner (Default: <repo>/daten)")
    parser.add_argument("--ohne-narrativ", action="store_true",
                        help="narrativ_chunks nicht migrieren (spart 290 Embed-Calls)")
    args = parser.parse_args()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY fehlen")
    daten_dir = args.daten_dir or speicher.DATEN_DIR

    # --- 1) Auth + profiles --------------------------------------------------
    uid = nutzer_anlegen(args.email, args.passwort)
    # Trigger hat die profiles-Zeile angelegt; jetzt haerten
    speicher._supabase_patch("profiles", {"id": "eq." + uid}, {
        "rolle": "admin", "plan": "pro", "onboarding_status": "fertig",
        "anzeige_name": "Christian Wolf", "handle": "wolf",
    })
    print("[migration] profiles: admin/pro/fertig gesetzt")

    # --- 2) radar_profile <- wissen/ ------------------------------------------
    wb = lade_json(os.path.join(WISSEN, "wissensbasis.json"), {})
    jetzt = speicher.jetzt_iso()
    ausloeser = [{"trigger": t, "staerke": 0.8, "quelle": "onboarding",
                  "belege": [], "aktualisiert_am": jetzt}
                 for t in (wb.get("reaktions_ausloeser") or [])]
    speicher.speichere_profil(uid, {
        "nische": "Ernährung, Abnehmen, Fitness oder Gesundheit",
        "sprache": "de",
        "marke": "Wolf",
        "quelle_kanaele": [{"plattform": "youtube", "handle": "christianwolf"}],
        "stilguide": lade_text(os.path.join(WISSEN, "chris_stilguide.md")),
        "playbook": lade_text(os.path.join(WISSEN, "reaktions_playbook.md")),
        # positionen bewusst leer: kuration faellt auf themenlandkarte.md zurueck
        # (Repo-Datei bleibt Christians Positions-Quelle der Wahrheit)
        "positionen": [],
        "reaktions_ausloeser": ausloeser,
        "interessen_profil": wb.get("interessen_profil") or {},
    })
    print("[migration] radar_profile: stilguide/playbook/%d Trigger/interessen" % len(ausloeser))

    # --- 3+4) themen + suchqueries <- mythen_katalog --------------------------
    import mythen_katalog
    themen_zeilen = [{"user_id": uid, "slug": slug, "name": t.get("name", slug),
                      "kerngewicht": float(t.get("kerngewicht", 0.7)),
                      "keywords": t.get("keywords", []), "aktiv": True,
                      "quelle": "onboarding"}
                     for slug, t in mythen_katalog.THEMEN.items()]
    n_themen = upsert("themen", themen_zeilen)

    queries = ([{"user_id": uid, "plattform": "youtube", "query": q,
                 "aktiv": True, "quelle": "onboarding"}
                for q in mythen_katalog.SUCHQUERIES]
               + [{"user_id": uid, "plattform": "tiktok", "query": q,
                   "aktiv": True, "quelle": "onboarding"}
                  for q in mythen_katalog.SOCIAL_SUCHQUERIES]
               + [{"user_id": uid, "plattform": "instagram", "query": h,
                   "aktiv": True, "quelle": "onboarding"}
                  for h in mythen_katalog.SOCIAL_HASHTAGS])
    n_queries = upsert("suchqueries", queries, konflikt="user_id,plattform,query")
    print("[migration] themen=%d suchqueries=%d" % (n_themen, n_queries))

    # --- 5) watchlist_personen ------------------------------------------------
    wl = lade_json(os.path.join(SCRAPER_DIR, "watchlist.json"), {}).get("eintraege", [])
    personen_zeilen = []
    gesehen = set()
    for e in wl:
        for plattform in ("youtube", "tiktok", "instagram"):
            handle = e.get(plattform)
            if not handle:
                continue
            schluessel = (plattform, handle.lower())
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            personen_zeilen.append({
                "user_id": uid, "name": e.get("name") or handle,
                "plattform": plattform, "handle": handle, "folgt": True,
                "notizen": e.get("notiz"), "quelle": "onboarding",
            })
    # Reaktions-Historie aus der Wissensbasis (folgt=False, reine Historie)
    for p in wb.get("personen") or []:
        handles = p.get("handles") or {}
        plattform = next((pl for pl in ("youtube", "tiktok", "instagram")
                          if handles.get(pl)), None)
        handle = handles.get(plattform) if plattform else None
        schluessel = (plattform or "", (handle or p.get("name", "")).lower())
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        personen_zeilen.append({
            "user_id": uid, "name": p.get("name") or "?",
            "plattform": plattform, "handle": handle, "folgt": False,
            "prioritaet": int(p.get("prioritaet") or 3),
            "interessen": p.get("themen") or [],
            "reaktionen": p.get("reaktionen") or [],
            "quelle": "onboarding",
        })
    n_personen = upsert("watchlist_personen", personen_zeilen,
                        konflikt="user_id,plattform,handle")
    print("[migration] watchlist_personen=%d" % n_personen)

    # --- 6) narrativ_chunks (Re-Embedding 512 -> 768) --------------------------
    n_chunks = 0
    if not args.ohne_narrativ:
        import narrativ
        index = lade_json(os.path.join(WISSEN, "narrativ_index.json"), {})
        chunks = index.get("chunks") or []
        vorhandene = zaehle("narrativ_chunks", uid)
        if vorhandene >= len(chunks) and chunks:
            print("[migration] narrativ_chunks: %d schon vorhanden — uebersprungen" % vorhandene)
        else:
            zeilen = []
            for i, c in enumerate(chunks):
                try:
                    vektor = narrativ.embed_text(c.get("text", ""), dim=768,
                                                 task="RETRIEVAL_DOCUMENT")
                except Exception as e:
                    print("[migration] Embed %d/%d fehlgeschlagen: %s" % (i + 1, len(chunks), e))
                    continue
                zeilen.append({"user_id": uid, "video_id": c.get("video_id"),
                               "titel": c.get("quelle"), "text": c.get("text", ""),
                               "ist_reaktion": bool(c.get("reaktion")),
                               "embedding": vektor})
                if (i + 1) % 50 == 0:
                    print("[migration] narrativ: %d/%d embedded" % (i + 1, len(chunks)))
                time.sleep(0.15)
            n_chunks = upsert("narrativ_chunks", zeilen)
        print("[migration] narrativ_chunks=%d (Quelle: %d)" % (n_chunks, len(chunks)))

    # --- 7) videos (POOL) + video_zuordnung <- daten/videos.json ---------------
    videos = lade_json(os.path.join(daten_dir, "videos.json"), [])
    pool_zeilen = [speicher._nur_pool_felder(v) for v in videos if v.get("id")]
    upsert("videos", pool_zeilen)
    zuordnungen = []
    for v in videos:
        if not v.get("id"):
            continue
        claim = v.get("claim") or {}
        zuordnungen.append({
            "user_id": uid, "video_id": v["id"],
            "status": v.get("status") or "inbox",
            "thema_slug": claim.get("thema"),
            "score": v.get("score") or 0,
            "scores": v.get("scores") or {},
            "verdict": ({"verdict": claim.get("verdict"),
                         "konfidenz": claim.get("konfidenz"),
                         "begruendung": claim.get("begruendung"),
                         "websuche": claim.get("websuche"),
                         "quellen": claim.get("quellen") or []} if claim else None),
            "begruendung": claim.get("begruendung"),
            "skripte": v.get("skripte") or [],
            "feedback": v.get("feedback") or [],
            "dublette_von": v.get("dublette_von"),
        })
    n_zuordnungen = upsert("video_zuordnung", zuordnungen, konflikt="user_id,video_id")
    print("[migration] videos=%d zuordnungen=%d" % (len(pool_zeilen), n_zuordnungen))

    # --- 8) einstellungen / vorschlaege / rezepte / agent_runs -----------------
    einst = lade_json(os.path.join(daten_dir, "einstellungen.json"), None)
    einst_zeilen = []
    if einst:
        einst_zeilen.append({"user_id": uid, "key": "einstellungen", "value": einst})
    vorschlaege = lade_json(os.path.join(daten_dir, "vorschlaege.json"), {})
    for key in ("vorschlaege", "extra_queries", "rezept_vorschlaege", "rezept_extra_queries"):
        if vorschlaege.get(key):
            einst_zeilen.append({"user_id": uid, "key": key, "value": vorschlaege[key]})
    n_einst = upsert("einstellungen", einst_zeilen, konflikt="user_id,key")

    REZEPT_FELDER = ("id", "plattform", "video_id", "url", "titel", "kanal",
                     "views", "likes", "kommentare", "veroeffentlicht",
                     "thumbnail_url", "dauer_s", "kategorie", "zutaten_kurz",
                     "score", "fit_score", "begruendung", "status", "feedback",
                     "gefunden_am")
    rezepte = lade_json(os.path.join(daten_dir, "rezepte.json"), [])
    rezept_zeilen = []
    for r in rezepte:
        zeile = {k: r.get(k) for k in REZEPT_FELDER if k in r}
        zeile["user_id"] = uid
        zeile["haken"] = r.get("chris_haken") or r.get("haken") or ""
        rezept_zeilen.append(zeile)
    n_rezepte = upsert("rezepte", rezept_zeilen)

    runs = lade_json(os.path.join(daten_dir, "agent_runs.json"), [])
    for r in runs[-200:]:
        r = dict(r)
        r.setdefault("typ", "akquise")
        speicher.speichere_agent_run(r)
    print("[migration] einstellungen=%d rezepte=%d agent_runs=%d"
          % (n_einst, n_rezepte, len(runs[-200:])))

    # --- Zaehl-Report ----------------------------------------------------------
    print("\n===== ZAEHL-REPORT (Quelle -> Supabase) =====")
    print("videos:           %6d -> %d" % (len(videos), zaehle("videos")))
    print("video_zuordnung:  %6d -> %d" % (len(zuordnungen), zaehle("video_zuordnung", uid)))
    print("themen:           %6d -> %d" % (len(themen_zeilen), zaehle("themen", uid)))
    print("suchqueries:      %6d -> %d" % (len(queries), zaehle("suchqueries", uid)))
    print("watchlist:        %6d -> %d" % (len(personen_zeilen), zaehle("watchlist_personen", uid)))
    print("rezepte:          %6d -> %d" % (len(rezept_zeilen), zaehle("rezepte", uid)))
    print("narrativ_chunks:  %6s -> %d" % ("-" if args.ohne_narrativ else "s.o.",
                                           zaehle("narrativ_chunks", uid)))
    print("\nChristian-UUID (fuer .env.server RADAR_STANDARD_USER): %s" % uid)
    print("FERTIG — im Supabase Table Editor gegenpruefen.")


if __name__ == "__main__":
    main()
