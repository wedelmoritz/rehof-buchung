"""Katalog der Benachrichtigungs-Vorlagen (ADR 0087/0089).

**Text als Code, Betrieb im Backend:** Die Vorlagen (Betreff/Text/Formatierung)
leben hier – versioniert, testbar, **ohne** Template-Engine auf gespeicherten
Strings (kein SSTI). Variablen werden ausschließlich über
`string.Template.safe_substitute` gegen die je Ereignis erlaubten Namen ersetzt.
Die **Betriebs-Parameter** (an/aus, Empfänger, Frequenz, PDF-Anhang, Vorlauf) stehen
dagegen im Backend (`NotificationSetting`).

Ein Ereignis ist rein Daten:
* ``audience``  – ``ops`` (Verwaltung), ``cleaning`` (Reinigungsteam), ``member``
  (an ein Mitglied) oder ``broadcast`` (Rundnachricht, Empfänger kommt vom Aufruf).
* ``kind``      – ``event`` (sofort, bei einem Ereignis) oder ``scheduled``
  (regelmäßig über den Scheduler).
* ``subject`` / ``body`` – Vorlagen mit ``$variable``-Platzhaltern.
* ``vars``      – erlaubte Platzhalter (reine Doku/Prüfung).
* ``pdf``       – optionaler PDF-Anhang-Typ (``plan`` etc.), sonst ``None``.
* ``defaults``  – Vorbelegung der `NotificationSetting` (Frequenz/Tag/Vorlauf …).
"""
from __future__ import annotations

from string import Template

# --------------------------------------------------------------------------- #
# Ereignis-Katalog. Neue Benachrichtigung = neuer Eintrag hier (+ ein dispatch-
# Aufruf an der passenden Stelle). Das Backend legt die Einstellung lazy an.
# --------------------------------------------------------------------------- #
EVENTS: dict[str, dict] = {
    # --- Verwaltung: geplante Übersichten (B3) ------------------------------ #
    "bookings_overview": {
        "audience": "ops", "kind": "scheduled", "pdf": "plan",
        "subject": "Re:Hof – Buchungsübersicht $month",
        "body": ("Buchungsübersicht $month (An-/Abreisen inkl. Endreinigungen):\n\n"
                 "$body\n"),
        "vars": ["month", "body"],
        "label": "Buchungsübersicht (regelmäßig, mit Plan-PDF)",
        "defaults": {"frequency": "weekly", "weekday": 0, "attach_pdf": True},
    },
    "occupancy_overview": {
        "audience": "ops", "kind": "scheduled", "pdf": None,
        "subject": "Re:Hof – Auslastung $month",
        "body": ("Auslastung je Unterkunft ($month) mit Ziel-Ampel:\n\n$body\n"),
        "vars": ["month", "body"],
        "label": "Auslastungs-Übersicht (regelmäßig, mit Ampel)",
        "defaults": {"frequency": "monthly", "day_of_month": 1},
    },
    "overdue_overview": {
        "audience": "ops", "kind": "scheduled", "pdf": None,
        "subject": "Re:Hof – Überfällige Rechnungen",
        "body": ("Aktuell überfällige Rechnungen:\n\n$body\n"),
        "vars": ["body"],
        "label": "Übersicht überfällige Rechnungen (regelmäßig)",
        "defaults": {"frequency": "weekly", "weekday": 0},
    },
    "lottery_reminder": {
        "audience": "ops", "kind": "scheduled", "pdf": None,
        "subject": "Re:Hof – Losverfahren steht an ($period)",
        "body": ("Das Losverfahren für $period steht in $lead_days Tagen an "
                 "(Ziehung am $draw). Bitte prüfen, ob alles vorbereitet ist.\n"),
        "vars": ["period", "lead_days", "draw"],
        "label": "Erinnerung: Losverfahren steht an",
        "defaults": {"frequency": "event", "lead_days": 7},
    },
    "member_status_upcoming": {
        "audience": "ops", "kind": "scheduled", "pdf": None,
        "subject": "Re:Hof – Mitglieds-Statuswechsel stehen bevor",
        "body": ("Bei folgenden Konten greift in den nächsten $lead_days Tagen ein "
                 "Statuswechsel (passiv/ausgeschieden):\n\n$list\n"),
        "vars": ["lead_days", "list"],
        "label": "Vorwarnung: Passivierung/Ausscheiden steht bevor",
        "defaults": {"frequency": "daily", "lead_days": 14},
    },
    # --- Verwaltung: Ereignis sofort (B3 nähe-abhängig) --------------------- #
    "booking_activity_urgent": {
        "audience": "ops", "kind": "event", "pdf": None,
        "subject": "Re:Hof – ⚠️ Kurzfristig: $what",
        "body": ("Kurzfristige Buchungs-Änderung (Anreise in Kürze):\n\n$what\n"
                 "$detail\n"),
        "vars": ["what", "detail"],
        "label": "Sofort-Meldung bei kurzfristiger Buchung/Storno",
        "defaults": {"frequency": "immediate"},
    },
    # --- Mitglied: geplant (ADR 0104) --------------------------------------- #
    "booking_details_reminder": {
        "audience": "member", "kind": "scheduled", "pdf": None,
        "subject": "Re:Hof – Bitte Buchung vervollständigen ($quarter)",
        "body": ("Deine Buchung aus der Losung steht: $quarter, $start–$end.\n\n"
                 "Bitte trage jetzt noch die Details nach – Personenzahl, Begleitung, "
                 "Besonderheiten (z. B. Hund, Beistellbett) und ob du eine "
                 "Endreinigung möchtest:\n$url\n\n"
                 "Die Anreise ist in $lead_days Tagen.\n"),
        "vars": ["quarter", "start", "end", "url", "lead_days"],
        "label": "Erinnerung an Mitglied: Los-Buchung vervollständigen",
        "defaults": {"frequency": "daily", "lead_days": 28},
    },
    # --- Rundnachricht (B4) ------------------------------------------------- #
    "announcement": {
        "audience": "broadcast", "kind": "event", "pdf": None,
        "subject": "Re:Hof: $subject",
        "body": "$body\n",
        "vars": ["subject", "body"],
        "label": "Rundnachricht an eine Rolle (manuell)",
        "defaults": {"frequency": "immediate"},
    },
}


def render(event_key: str, context: dict) -> tuple[str, str]:
    """Rendert (Betreff, Text) eines Ereignisses **sicher** (safe_substitute gegen
    die Vorlage – kein Code, fehlende Variablen bleiben stehen)."""
    ev = EVENTS[event_key]
    ctx = {k: ("" if v is None else str(v)) for k, v in (context or {}).items()}
    subject = Template(ev["subject"]).safe_substitute(ctx)
    body = Template(ev["body"]).safe_substitute(ctx)
    return subject, body
