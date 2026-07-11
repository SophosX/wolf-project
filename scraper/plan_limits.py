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
        "skripte_pro_woche": None,  # None = unbegrenzt
        "rezepte": True,
        "webcheck": True,
    },
}


def limits(plan: str | None) -> dict:
    """Limits fuer einen Plan; unbekannt/None faellt auf free zurueck."""
    return PLAN_LIMITS.get(plan or "free", PLAN_LIMITS["free"])
