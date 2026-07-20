# 0104 – Buchung nach der Losung vervollständigen (+ 4-Wochen-Erinnerung)

## Status

Proposed (2026-07-20) · nutzt [ADR 0003](0003-losverfahren-weighted-rsd.md) (Losverfahren),
[ADR 0008](0008-losung-review-workflow.md) (Review-/Bestätigungs-Workflow),
[ADR 0081](0081-endreinigung-freigabe-workflow.md) (Endreinigung als bestätigungs-
pflichtige Leistung), [ADR 0089](0089-benachrichtigungs-framework.md) (Benachrichtigungs-
Framework). **Umgesetzt (2026-07).**

## Kontext

Ein Wunsch trägt nur **Quartier + Zeitraum + Priorität**. Wird er in der Losung erfüllt,
entsteht eine `Allocation` – aber **ohne** die Angaben, die eine Spontan-/Externbuchung
schon beim Buchen erfasst: **Personenzahl** (Default 1), **Begleitung**, **Besonderheiten**
(Hund/Beistellbett/Kinder) und die optionale **Endreinigung**. Diese Details braucht das
Team zur Vorbereitung – heute fehlen sie bei Los-Buchungen ganz.

Ziel: Nach der Bestätigung der Losung soll das Mitglied die gewonnene Buchung **nachträglich
vervollständigen**, mit einem klaren Hinweis. Passiert das nicht rechtzeitig, erinnert die
App **vier Wochen vor der Anreise** (In-App + E-Mail).

## Entscheidung

**Los-Zuteilungen als „Details nachzutragen" markieren.** `run_period_lottery` setzt
`Allocation.details_pending=True` (nur Quelle `lottery`; Spontan/Extern/Import sind schon
vollständig → `False`). Das Flag überlebt die Bestätigung und steuert die UI.

**Nachtragen in „Meine Buchungen".** Zu jeder offenen Los-Buchung erscheint eine dezent
hervorgehobene Karte **„Bitte diese Buchung vervollständigen"** mit einem Formular:
**Personen · Begleitung · Besonderheiten** und – wie beim Buchen – die opt-in
**Dienstleistungen** (`Product.book_with_stay`, u. a. die bestätigungspflichtige
Endreinigung nach [ADR 0081](0081-endreinigung-freigabe-workflow.md)). Absenden setzt die
Felder und räumt `details_pending` ab. Der **Zeitraum/das Quartier** wird hier **nicht**
geändert – dafür bleibt „Buchung ändern".

**4-Wochen-Erinnerung.** Ein geplanter Scheduler-Schritt erinnert **einmal je Buchung**,
sobald die Anreise ≤ `lead_days` (Default **28**) entfernt ist und `details_pending` noch
gilt. Idempotenz über `Allocation.details_reminded_on`. Das läuft über das
Benachrichtigungs-Framework ([ADR 0089](0089-benachrichtigungs-framework.md)) als
**member-audience, scheduled**-Ereignis `booking_details_reminder` (In-App-`Notification`
+ E-Mail über den Opt-in) – an/aus, Empfänger und Vorlauf im Backend
(`NotificationSetting`) einstellbar wie jede andere Benachrichtigung.

## Architektur / Sicherheit / Performanz

- **Service-Layer (keine Shop-Kopplung in der Kernfunktion):**
  `booking_ops.complete_lottery_details(member, allocation_id, *, persons, companions,
  special_requests)` – lädt **nur die eigene**, noch offene Los-Buchung
  (`member.allocations.get(source="lottery", details_pending=True)`), prüft den
  **Personen-Rahmen** (`1..max_occupancy`), säubert Freitext mit
  `validation.strip_controls` (Längenlimit 255) und räumt das Flag ab
  (`@transaction.atomic`, gezielte `update_fields`). Die **Endreinigung/Dienstleistungen**
  laufen – wie in `book_confirm` – über `shop.services.request_service`/`purchase_service`
  in der View (Service bleibt frei von Shop-Imports).
- **Scheduler:** `dashboard.send_booking_details_reminders(today)` in
  `run_scheduled_notifications` registriert; ein indizierter Query
  (`source, details_pending, provisional, start`), pro Treffer eine Benachrichtigung.
  Nur **bestätigte** Buchungen (`provisional=False`) werden erinnert.
- **Security:** Ownership-Check im Service (Fremdzugriff unmöglich, nicht nur in der View);
  Eingaben strikt begrenzt/gesäubert; keine neue Freitext-Ausgabe ohne Auto-Escaping
  (Template rendert `companions`/`special_requests` escaped); Formular CSP-treu (kein
  Inline-Handler); der 255er-Cap deckelt Missbrauch. Die Benachrichtigungs-Vorlage nutzt
  den bestehenden `safe_substitute`-Katalog (kein SSTI).

## Datenmodell

- `Allocation.details_pending` (Boolean, Default `False`) – True nur bei Los-Buchungen.
- `Allocation.details_reminded_on` (Date, null) – Idempotenz-Marke der Erinnerung.
- Katalog-Ereignis `booking_details_reminder` (audience `member`, kind `scheduled`,
  Default `daily`/`lead_days=28`).
- Migration `0075_allocation_details_pending_and_more`.

## Betrachtete Alternativen

- **Details schon im Wunsch erfassen:** verworfen – für die Losung sind Personen/
  Besonderheiten **irrelevant** (ändern die Zuteilung nicht) und der `Wish` bliebe unnötig
  breit; die Angaben gehören zur konkreten Buchung, nicht zum Wunsch.
- **Vervollständigen erzwingen (Buchung sonst ungültig):** verworfen – die Zuteilung steht;
  ein weicher, erinnerter Hinweis ist angemessen (Default `persons=1` bleibt gültig).
- **Erinnerung als eigener Cron statt Framework:** verworfen – das Benachrichtigungs-
  Framework ([ADR 0089](0089-benachrichtigungs-framework.md)) bietet an/aus, Empfänger,
  Vorlauf und Idempotenz-Muster bereits.

## Konsequenzen

**Positiv** – das Team bekommt die Vorbereitungs-Angaben auch für Los-Buchungen; klarer
Handlungs-Hinweis + Sicherheitsnetz (4 Wochen vorher); nutzt bestehende Bausteine
(Endreinigungs-Flow, Benachrichtigungs-Framework); minimaler Modell-Zuwachs.

**Negativ / Grenzen** – zusätzlicher Schritt für das Mitglied (bewusst weich gehalten);
bleibt das Nachtragen aus, gilt weiter `persons=1`/leere Besonderheiten (dokumentierte
Grenze, keine harte Sperre).
