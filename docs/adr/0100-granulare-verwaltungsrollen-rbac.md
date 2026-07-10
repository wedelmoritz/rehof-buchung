# 0100 – Granulare Verwaltungsrollen (RBAC) im einheitlichen Frontend

## Status

Proposed (2026-07-10) · verfeinert [ADR 0014](0014-rollentrennung-admin-verwaltung.md)
(grobe Rollentrennung) · baut auf [ADR 0049](0049-admin-fachliche-sektionen.md),
[ADR 0055](0055-backend-navigator-pjax.md), [ADR 0056](0056-onboarding-pendinguser.md),
[ADR 0085](0085-verwaltung-unterseiten.md), [ADR 0087](0087-rollen-mitgliedsstatus.md),
[ADR 0094](0094-bl-buchungen-audit-notify.md) auf. **Noch nicht umgesetzt.**

## Kontext

Heute gibt es zwei Verwaltungs-Ebenen mit einer **groben** Grenze:

- **Verwaltung** (`/verwaltung/`, native App-Optik): alles-oder-nichts über
  `is_verwaltung` (Gruppe „Verwaltung" **oder** Superuser). Jede `verw_*`-View prüft
  denselben `_staff_required()`-Guard (`booking/views.py`). Ein Konto, das **nur** die
  Kasse oder **nur** die Reinigung bedienen soll, ist nicht darstellbar.
- **Backend** (`/admin/`, Django-Admin, reskinnt): **Superuser only**.

Im Produktivbetrieb fehlt (a) **Least Privilege** – einzelne Funktionen je Person
freischaltbar – und (b) eine **native Mitglieder-/Benutzerverwaltung** (Freischalten,
Anteile zuordnen), die heute nur im Backend existiert. Ein **Voll-Rebuild** des
Django-Admin wird bewusst verworfen (er liefert Reversion-Historie, Validierung,
Inlines, CRUD „geschenkt"); der Admin bleibt das **Superuser-Sicherheitsnetz** für
seltene, gefährliche, irreversible Operationen.

Best-Practice-Recherche (Django Admin Theme Roundup 2025; Django-RBAC-Guides):
Django-Admin **themen statt neu bauen**; RBAC über **Groups + Permissions** (Least
Privilege in den Permissions, Ergonomie in den Gruppen); Enforcement **serverseitig**
an der View; ABAC/ReBAC hier nicht nötig.

## Entscheidung

### 1. Trennlinie Verwaltung ↔ Backend (neu definiert)

Nicht mehr „darf ändern ja/nein", sondern:

> **Alltäglich & reversibel → native, rollen-gegatete Verwaltung.**
> **Selten, gefährlich, irreversibel → Superuser-Backend.**

**Bleibt bewusst Superuser/Backend:** Losung *durchführen* **und** *bestätigen*
(sehr selten, `confirm_lottery` irreversibel) · Buchungsregeln/Saison/Perioden ·
tiefe Mitglieds-/Anteils-/PII-Änderungen · Löschen/Anonymisieren · Reversion-Revert ·
Config-Singletons (`ShopConfig`/`OpsConfig`/`NotificationSetting`/`TerminalConfig`,
inkl. Terminal-Token/Roster) · Beds24-Import · Logs.

**Carve-out Losverfahren-Domäne (ADR 0101):** Zwei **alltägliche, reversible**
Wunsch-Operationen sind **nativ** (nicht Superuser), obwohl die Losung sonst dem
Superuser vorbehalten bleibt: **stellvertretend einen Wunsch nachtragen**
(`add_wish_for_member`, für Vergessene) und der **Wunsch-Export** der Verwaltung
(`export_wishes`). Beide ändern nur Wunsch-Daten (kein Ziehen/Bestätigen, keine
Regeln); ersteres auditiert wie `book_for_member`. Sie fallen damit klar auf die
Seite „alltäglich & reversibel → native Verwaltung".

### 2. Zweischichtiges RBAC (Django-nativ)

- **Atome = Permissions** je (Ressource × Aktion) – hier lebt Least Privilege.
- **Rollen = Groups**, die Permissions bündeln; **additive Supersets** („…-Erweitert"
  enthält Basis-Perms **+** Delta). Mehrere Rollen je Nutzer → **Vereinigung** (Django
  nativ, kein Deny).
- **Nutzer** sind Mitglieder (`Member`) **und/oder** in Verwaltungsrollen (orthogonal,
  wie heute die „Verwaltung"-Gruppe).

**Rollenkatalog (native Rollen):**

| Rolle (Group) | Permissions | Superset von |
|---|---|---|
| Hofladen-Verwaltung | `access_hofladen`, `send_broadcast` | – |
| Buchungs-Verwaltung | `access_buchungen`, `export_wishes`, `send_broadcast` | – |
| Buchungs-Verwaltung-Erweitert | + `book_for_member`, `add_wish_for_member` | Buchungs-Verwaltung |
| Mitglieder-Verwaltung | `access_mitglieder`, `send_broadcast` | – |
| Quartiers-Verwaltung | `access_quartiere`, `send_broadcast` | – |
| Rechnungs-Verwaltung | `access_rechnungen`, `send_broadcast` | – |

- **`access_buchungen`** deckt: Buchungen sehen + interne Notiz, Reinigung,
  **Endreinigung-Freigabe**, **Sperrzeiten**, Auslastung (read), Plan-PDF, Tagesdetail.
- **`access_quartiere`** deckt: Quartiere/Preise/Saison **+ Sperrzeiten** (Sperrzeiten
  gehören damit Buchungs- **∪** Quartiers-Verwaltung).
- **`book_for_member`** = BL-Buchungen anlegen/ändern/stornieren (auditiert, s. §4).
- **`export_wishes`** = Wunsch-Export der Verwaltung (vor/nach der Entzerrungsphase,
  ADR 0101); bei **Buchungs-Verwaltung**, da Nachfrage-/Buchungsanalyse.
- **`add_wish_for_member`** = Wunsch stellvertretend für Vergessene nachtragen
  (auditiert, ADR 0101); bei **Buchungs-Verwaltung-Erweitert** (wie `book_for_member`).
- **`send_broadcast`** (Rundnachricht) + Auslastung(read) sind **Querschnitt** → in
  jeder nativen Rolle enthalten.
- **Mitglieder-Verwaltung ist bewusst „shallow"**: Freischalten (Onboarding), Anteil an
  bestehenden Anteil zuordnen, passiv/aktiv, Kontaktliste. **Tiefe** Änderungen
  (PII, Anteile/Tandems anlegen/umbauen) bleiben Superuser (kein „…-Erweitert" nativ).
- **Nicht als native Rolle gebaut (später nachrüstbar):** Mitglieder-Verwaltung-Erweitert,
  Buchungsregel-Verwaltung.

**„App-Administration" = Superuser-Flag**, keine Gruppe.

### 3. Capability-Registry als Single Source of Truth

Zugriffs-Permissions, die zu keinem einzelnen Modell gehören, leben auf **einem
permissions-only Proxy** (Standard-Django-Pattern, **keine** DB-Tabelle):

```python
# booking/authz.py  (Umsetzungs-Skizze)
class VerwaltungAccess(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("access_buchungen",   "Verwaltung: Buchungen/Reinigung/Sperrzeiten"),
            ("book_for_member",    "Verwaltung: Buchungen für Mitglieder"),
            ("export_wishes",      "Verwaltung: Wunsch-Export (Entzerrungsphase)"),
            ("add_wish_for_member","Verwaltung: Wunsch für Mitglied nachtragen"),
            ("access_mitglieder",  "Verwaltung: Mitglieder freischalten/zuordnen"),
            ("access_quartiere",   "Verwaltung: Quartiere/Sperrzeiten"),
            ("access_rechnungen",  "Verwaltung: Rechnungen/Kontoabgleich"),
            ("access_hofladen",    "Verwaltung: Hofladen-Katalog"),
            ("send_broadcast",     "Verwaltung: Rundnachricht senden"),
        ]
```

Eine **Registry** beschreibt jede Verwaltungs-Funktion **genau einmal**; Nav,
View-Guards und Tests leiten sich daraus ab (DRY, kein Drift):

```python
@dataclass(frozen=True)
class Capability:
    key: str; label: str; icon: str; url_name: str; perm: str; section: str

CAPABILITIES: list[Capability] = [ ... ]           # buchungen, reinigung, sperrzeiten, …
ROLES: dict[str, set[str]] = { ... }               # Group-Name -> Perm-Codenames (additiv)
```

`ROLES` ist die Quelle fürs **idempotente** Seeding (`manage.py sync_roles`): legt die
Groups an, ordnet die Permissions zu, **vereinigt Supersets** (…-Erweitert erbt Basis).
Re-runnable, reproduzierbar über alle Umgebungen (kein manuelles Klicken).

### 4. Durchsetzung (Security-first, fail-closed)

```python
def requires(perm):                                # ersetzt _staff_required
    def deco(view):
        @login_required
        @wraps(view)
        def _w(request, *a, **k):
            if not request.user.has_perm(perm):
                raise PermissionDenied              # 403, kein Redirect (kein Info-Leak)
            return view(request, *a, **k)
        return _w
    return deco
```

- **Immer serverseitig** an der View; Nav-Ausblenden ist nur Komfort, **nie** Schutz.
- **Defense in depth:** die heikelste Mutation `book_for_member` prüft die Capability
  **zusätzlich im Service** (`services.create_admin_allocation(..., actor=user)` verifiziert
  `actor.has_perm`), nicht nur in der View.
- **Audit:** BL-Buchungen laufen weiter über `Allocation.created_by`/`by_management`
  (ADR 0094) **und** werden nativ in `reversion.create_revision(user=…)` gewickelt →
  gleiche Historie wie im Admin. **Rundnachricht** bekommt einen eigenen Audit-Eintrag
  (wer, wann, Ziel-Rolle, Empfängerzahl).
- **CSP/CSRF/Rate-Limit** wie im Bestand: `nonce`, keine Inline-Handler
  (`data-confirm`-Doppelbestätigung für destruktive Aktionen), Mutationen nur per POST,
  `django-ratelimit` auf Onboarding/BL-Buchung/Broadcast/Mitgliedersuche.
- **`PermissionDenied` (403)** statt Redirect mit Query (kein PII-Leak).

### 5. UI/UX (einheitlich, kein neuer Look)

- **Token-/Komponenten-System** aus App + Dashboard unverändert (ADR 0054/0065).
- **Rollengefilterte Navigation:** Sidenav-Unterpunkte + Mobil-Sheet werden
  **datengetrieben aus der Registry** gerendert und nach `has_perm` gefiltert – jeder
  sieht nur, was er darf (tote Links vermieden, #48-Prinzip). Aggregat-Gate
  `is_any_verwaltung(user)` blendet den Bereich ein/aus.
- **Mitglieder-Verwaltung (neu, aufgabenorientiert):** Onboarding-Warteschlange als
  Karten mit 2-Klick-Aktionen (Freischalten via `member_search`-Typeahead/
  `ensure_personal_membership` · „Nur Hofladen" · „Deaktivieren"), Mitgliederliste mit
  Status-Chips (aktiv/passiv) + Detailkarte (Anteil zuordnen/entfernen *shallow*).
  Tiefe Änderungen zeigen einen dezenten **„Im Backend bearbeiten"-Deeplink** (nur
  Superuser) – ehrliche, klare Grenze. Live per `data-ajax`, Toasts, Empty-States,
  WCAG-AA, Mobil-first.

### 6. Performanz

Django cached `user.get_all_permissions()` **pro Request** → nach erstem Zugriff O(1);
Gruppen-Join = **eine** Query/Request. Registry ist eine **statische** Python-Struktur
(0 DB). Nav filtert in-memory (kein N+1). Neue Seiten **wiederverwenden Services**
(kein neuer Hot-Path). Kein zusätzlicher Cache nötig.

### 7. Datenmodell, Migration, Rückwärtskompatibilität

- **Keine Schemaänderung** außer dem `managed=False`-Proxy (erzeugt nur Permission-Rows).
- **Seeding** via `sync_roles` (idempotentes Kommando) statt hart kodierter Datenmigration.
- **Bestehende Gruppe „Verwaltung"** wird beim ersten `sync_roles` auf **alle nativen
  Rollen** gemappt → **niemand verliert Zugriff**.
- `is_verwaltung` bleibt als **Aggregat** („in irgendeiner Verwaltungsrolle") fürs
  Bereichs-Gate; feine Checks laufen über `has_perm`.

## Umsetzungsplan (Phasen)

| Phase | Inhalt | Dateien (Richtung) | Aufwand |
|---|---|---|---|
| **1 – RBAC-Fundament** | Proxy-Perms + Registry + `requires` + `sync_roles`; `verw_*`-Guards umstellen; datengetriebene, gefilterte Nav; Rollen-Matrix-Tests | `booking/authz.py` (neu), `booking/permissions.py`, `booking/views.py`, `booking/management/commands/sync_roles.py` (neu), `booking/templates/booking/base.html`, `booking/tests_roles_status.py` | mittel |
| **2 – Mitglieder-Verwaltung nativ (shallow)** | Onboarding-Queue, Mitgliederliste/Detail, Anteil-Zuordnung (reuse `onboard_*`/`ensure_personal_membership`/`apply_member_status`) | `booking/views.py`, `booking/templates/booking/verw_mitglieder*.html`, `booking/urls.py` | mittel |
| **3 – BL-Buchungen nativ (auditiert)** | Buchung für Mitglied anlegen/ändern/stornieren nativ, `reversion`-Wrap + `created_by` | `booking/services/booking_ops.py`, `booking/views.py`, Templates | mittel |
| **4 – Feinschliff** | Icons ins Sprite, Empty-States, Deeplinks, optional Admin-Theme | Templates, `static` | klein |

**Bewusst nicht Teil dieser ADR (bleibt Superuser):** Losung, Buchungsregeln, tiefe
Mitglieds-/Anteils-Edits, Löschen/Anonymisieren, Config, Terminal-Token.

## Betrachtete Alternativen

- **Voll-Rebuild des Django-Admin** – verworfen: hoher Aufwand/Risiko, verliert
  Reversion/Validierung/Inlines/History „geschenkt"; schlechtes Aufwand-Nutzen-Verhältnis
  für eine kleine Genossenschaft.
- **Nur Custom-Permissions ohne Rollen** – maximale Granularität, aber mühsame Vergabe
  je Person; verworfen zugunsten **Rollen als Bündel** (Least Privilege bleibt in den
  Atomen erhalten).
- **Nur grobe Rollen ohne Permissions** (Status quo verfeinert) – zu unflexibel,
  verfehlt Least Privilege.
- **Fremd-Framework (django-guardian/ABAC/ReBAC)** – Overkill; Django-Bordmittel
  reichen (keine objekt-/beziehungsabhängigen Regeln nötig).
- **Django-Admin per Model-Permissions für Verwaltung öffnen** (`is_staff`+Perms) –
  bleibt als *Fallback* für seltene Backend-Aufgaben möglich, aber Admin-Optik statt
  einheitlicher App-UX; daher nicht der Haupt-Weg.

## Konsequenzen

**Positiv** – Least Privilege je Funktion; überschneidende Rollen per Union; einheitliche,
moderne App-UX auch für Verwaltungsaufgaben; native Mitglieder-Freischaltung schließt die
wichtigste Produktiv-Lücke; Nav/Guards/Tests aus **einer** Registry (kein Drift);
Audit/Reversion auch für native Deep-Edits; keine Schemaänderung, kein Fremd-Framework,
Django-nativ und performant.

**Negativ / Grenzen** – mehr Rollen = mehr Konfigurations-Sorgfalt (durch `sync_roles`
+ Matrix-Tests abgefedert); native Deep-Edits erfordern **bewusstes** Audit-Wiring (sonst
Historie-Lücke); die Grenze „native vs. Backend" muss gepflegt werden, wenn neue
Funktionen dazukommen (Registry ist der eine Ort dafür); „shallow" bei der
Mitglieder-Verwaltung bedeutet, dass tiefe Anteils-/Tandem-Umbauten vorerst im Backend
bleiben (bewusst, spätere native „…-Erweitert"-Rolle möglich).
