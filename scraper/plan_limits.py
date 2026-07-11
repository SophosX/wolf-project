"""Free/Pro-Limits — Spiegel von lib/plan.ts (dort ist die Referenz).

Wird von kuration.py, onboarding_agent.py und rezepte_agent.py gelesen,
um Kosten pro Nutzer hart zu deckeln. Bei Änderungen BEIDE Dateien anfassen.
"""

PLAN_LIMITS = {
    "free": {
        "import_videos": 25,       # Videos beim Kanal-Import im Onboarding
        "themen": 6,               # max. aktive Themen im Profil
        "suchqueries": 12,         # max. aktive Suchqueries
        "watchlist": 5,            # max. Personen auf der Beobachtungsliste
        "kuration_pro_tag": 1,     # Kurationslaeufe pro Tag
        "kuration_max_neu": 10,    # max. NEUE Inbox-Zuordnungen pro Lauf
        "queries_pro_lauf": 12,    # wie viele aktive Queries je Akquise-Lauf (Rotation)
        "skripte_pro_woche": 3,
        "rezepte": False,
        "webcheck": False,
    },
    "pro": {
        "import_videos": 200,
        "themen": 25,
        "suchqueries": 50,
        "watchlist": 25,
        "kuration_pro_tag": 6,     # alle 4 h
        "kuration_max_neu": 25,
        "queries_pro_lauf": 40,    # Apify-Kosten-Deckel auch fuer Pro
        "skripte_pro_woche": None,  # None = unbegrenzt
        "rezepte": True,
        "webcheck": True,
    },
}


def limits(plan: str | None, overrides: dict | None = None) -> dict:
    """Effektive Limits: Plan-Defaults + Admin-Overrides (profiles.limits).
    Unbekannter Plan faellt auf free zurueck; nur bekannte Keys werden gemerged."""
    basis = dict(PLAN_LIMITS.get(plan or "free", PLAN_LIMITS["free"]))
    for k, v in (overrides or {}).items():
        if k not in basis or v is None:
            continue
        if isinstance(basis[k], bool):
            basis[k] = bool(v)
        elif basis[k] is None or isinstance(basis[k], int):
            try:
                basis[k] = int(v)
            except (TypeError, ValueError):
                pass
    return basis
