"""Rollenbasierte Verwaltung – **eine** Quelle der Wahrheit (ADR 0100).

Zweischichtiges RBAC mit Django-Bordmitteln:

* **Atome = Permissions** (auf dem `managed=False`-Modell `VerwaltungAccess`,
  siehe `models.py`) – hier lebt Least Privilege.
* **Rollen = Gruppen** (`ROLES`), die Permissions bündeln; **additive Supersets**
  (`ROLE_SUPERSETS`, „…-Erweitert" erbt die Basis-Rechte). Mehrere Rollen je
  Nutzer → Vereinigung (Django nativ).
* **Capability-Registry** (`CAPABILITIES`) beschreibt jede Verwaltungs-Seite genau
  einmal (Label/Icon/URL/benötigtes Recht/Bereich) – **Nav, View-Guards und Tests
  leiten sich daraus ab** (kein Drift).

Durchsetzung serverseitig über `requires_capability`/`requires` (fail-closed →
403). Das Seeding der Gruppen ist idempotent (`manage.py sync_roles`).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

APP = "booking"

# --- Rechte-Atome (Codenamen ohne App-Präfix; müssen zu models.VerwaltungAccess passen) -
P_BUCHUNGEN = "access_buchungen"
P_BOOK_FOR_MEMBER = "book_for_member"
P_EXPORT_WISHES = "export_wishes"
P_ADD_WISH_FOR_MEMBER = "add_wish_for_member"
P_MITGLIEDER = "access_mitglieder"
P_QUARTIERE = "access_quartiere"
P_RECHNUNGEN = "access_rechnungen"
P_HOFLADEN = "access_hofladen"
P_BROADCAST = "send_broadcast"

ALL_PERMS = (
    P_BUCHUNGEN, P_BOOK_FOR_MEMBER, P_EXPORT_WISHES, P_ADD_WISH_FOR_MEMBER,
    P_MITGLIEDER, P_QUARTIERE, P_RECHNUNGEN, P_HOFLADEN, P_BROADCAST,
)

# --- Rollen (Gruppen) → Basis-Rechte; Supersets erben zusätzlich --------------
ROLES: dict[str, set[str]] = {
    "Hofladen-Verwaltung": {P_HOFLADEN, P_BROADCAST},
    "Buchungs-Verwaltung": {P_BUCHUNGEN, P_EXPORT_WISHES, P_BROADCAST},
    "Buchungs-Verwaltung-Erweitert": {P_BOOK_FOR_MEMBER, P_ADD_WISH_FOR_MEMBER},
    "Mitglieder-Verwaltung": {P_MITGLIEDER, P_BROADCAST},
    "Quartiers-Verwaltung": {P_QUARTIERE, P_BROADCAST},
    "Rechnungs-Verwaltung": {P_RECHNUNGEN, P_BROADCAST},
}
# „…-Erweitert" ist ein additiver Superset seiner Basis-Rolle.
ROLE_SUPERSETS: dict[str, str] = {
    "Buchungs-Verwaltung-Erweitert": "Buchungs-Verwaltung",
}
# Legacy-Rolle „Verwaltung" (ADR 0014/0087) → auf die nativen **Basis**-Rollen
# abbilden, die den heutigen Zugriff **exakt erhalten** (niemand verliert etwas).
# Bewusst OHNE „…-Erweitert" (BL-Buchungen) und OHNE Quartiers-Verwaltung
# (Quartier-Bearbeitung) – das wären NEUE Rechte (Least Privilege, kein stilles
# Eskalieren). Diese vier decken alle bisher erreichbaren Dashboard-Seiten ab.
LEGACY_ROLE = "Verwaltung"
LEGACY_MAPS_TO = [
    "Hofladen-Verwaltung", "Buchungs-Verwaltung",
    "Mitglieder-Verwaltung", "Rechnungs-Verwaltung",
]


def effective_role_perms(role: str) -> set[str]:
    """Rechte einer Rolle inkl. geerbter Superset-Rechte (transitiv)."""
    perms = set(ROLES.get(role, set()))
    base = ROLE_SUPERSETS.get(role)
    if base:
        perms |= effective_role_perms(base)
    return perms


# Rechte, die die Legacy-Rolle „Verwaltung" **implizit** trägt – exakt die Summe
# ihrer Ziel-Basis-Rollen (`LEGACY_MAPS_TO`). So behalten bestehende „Verwaltung"-
# Konten ihren Zugriff auch dann, wenn `sync_roles` beim Deploy noch NICHT lief
# (kein Zugriffsverlust) – und bekommen dennoch **keine** neuen Schreib-/Quartier-
# Rechte (Least Privilege).
LEGACY_PERMS: set[str] = {
    p for role in LEGACY_MAPS_TO for p in effective_role_perms(role)
}


# --- Capability-Registry: je Verwaltungs-Seite EIN Eintrag --------------------
# perm: Codename (str), Tupel = „eines davon genügt", None = „irgendeine Rolle".
@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    icon: str
    url_name: str
    perm: str | tuple[str, ...] | None
    section: str


CAPABILITIES: list[Capability] = [
    Capability("dashboard",   "Verwaltung",       "ic-admin",     "dashboard",          None,          "Übersicht"),
    Capability("buchungen",   "Buchungen",        "ic-mybookings","verw_buchungen",     P_BUCHUNGEN,   "Buchung"),
    Capability("wuensche",    "Wünsche & Losung", "ic-wish",      "verw_wuensche",      P_EXPORT_WISHES, "Buchung"),
    Capability("reinigung",   "Reinigung",        "ic-clean",     "verw_reinigung",     P_BUCHUNGEN,   "Buchung"),
    Capability("sperrzeiten", "Sperrzeiten",      "ic-lock",      "verw_sperrzeiten",   (P_BUCHUNGEN, P_QUARTIERE), "Buchung"),
    Capability("rechnungen",  "Rechnungen",       "ic-invoices",  "verw_rechnungen",    P_RECHNUNGEN,  "Finanzen"),
    Capability("konto",       "Kontoabgleich",    "ic-bank",      "verw_konto",         P_RECHNUNGEN,  "Finanzen"),
    Capability("auslastung",  "Auslastung",       "ic-community", "verw_auslastung",    None,          "Übersicht"),
    Capability("mitglieder",  "Mitglieder",       "ic-profile",   "verw_mitglieder",    P_MITGLIEDER,  "Mitglieder"),
    Capability("rundnachricht","Rundnachricht",   "ic-mail",      "verw_rundnachricht", P_BROADCAST,   "Übersicht"),
    Capability("produkte",    "Hofladen-Katalog", "ic-shop",      "dashboard_products", P_HOFLADEN,    "Hofladen"),
]
CAPABILITY_BY_KEY = {c.key: c for c in CAPABILITIES}


# --- Prüf-Helfer --------------------------------------------------------------
def _full(codename: str) -> str:
    return f"{APP}.{codename}"


def _is_legacy(user) -> bool:
    """Ob `user` in der Legacy-Rolle „Verwaltung" ist – **einmal je Request/Instanz
    gecacht** (die Nav prüft 10 Capabilities × mehrere Call-Sites; ohne Cache wäre das
    ein Query pro Capability, N+1)."""
    cached = getattr(user, "_rehof_legacy", None)
    if cached is None:
        cached = user.groups.filter(name=LEGACY_ROLE).exists()
        try:
            user._rehof_legacy = cached
        except (AttributeError, TypeError):  # z. B. AnonymousUser
            pass
    return cached


def is_any_verwaltung(user) -> bool:
    """Bereichs-Gate: Superuser, wer irgendeine native Verwaltungs-Capability hat,
    oder (Übergang) Mitglied der Legacy-Rolle „Verwaltung"."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if any(user.has_perm(_full(p)) for p in ALL_PERMS):
        return True
    return _is_legacy(user)


def user_can(user, perm) -> bool:
    """Prüft eine Capability-Anforderung: None = irgendeine Rolle; Tupel = eines
    davon genügt; str = genau dieses Recht. Superuser darf immer."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if perm is None:
        return is_any_verwaltung(user)
    perms = (perm,) if isinstance(perm, str) else tuple(perm)
    if any(user.has_perm(_full(p)) for p in perms):
        return True
    # Übergang: Legacy-Rolle „Verwaltung" deckt ihre Basis-Rechte auch ohne
    # gelaufenes `sync_roles` ab (kein stilles Eskalieren über LEGACY_PERMS hinaus).
    if any(p in LEGACY_PERMS for p in perms):
        return _is_legacy(user)
    return False


def allowed_capabilities(user) -> list[Capability]:
    """Die für `user` sichtbaren Capabilities – Grundlage der gefilterten Nav."""
    return [c for c in CAPABILITIES if user_can(user, c.perm)]


def requires_capability(key: str):
    """View-Decorator: erzwingt die zur Capability `key` gehörende Anforderung
    (fail-closed → 403, kein Redirect/Info-Leak)."""
    cap = CAPABILITY_BY_KEY[key]

    def deco(view):
        @login_required
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            if not user_can(request.user, cap.perm):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return _wrapped
    return deco


def requires(perm):
    """Wie `requires_capability`, aber direkt für ein Recht (Codename/Tupel/None) –
    für Aktionen ohne eigene Seite (z. B. `book_for_member`)."""
    def deco(view):
        @login_required
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            if not user_can(request.user, perm):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return _wrapped
    return deco
