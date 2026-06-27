# 0014 – Rollentrennung Admin (Superuser) vs. Verwaltung (Gruppe)

## Status

Accepted (2026-06-26)

> **Fachlicher Bezug:** Die zugrundeliegenden fachlichen Regeln stehen im
> [Fachkonzept § 14 – Rollen & Rechte](../FACHKONZEPT.md#14-rollen--rechte).
> Diese ADR hält die *technische* Entscheidung und ihre Abwägungen fest; die
> Regelwerte werden dort gepflegt, nicht hier.

## Kontext

Es gibt zwei unterschiedliche Betriebsaufgaben: (1) **Stammdaten/Backend** (Mitglieder
anlegen, Buchungen ändern, Losungen starten) und (2) **operatives Tagesgeschäft**
(Reinigungsliste, anstehende Buchungen, Rechnungen einsehen, Hofladen-Katalog pflegen).
Beides am einzelnen Django-Flag `is_staff` aufzuhängen wäre zu grob: Wer das Dashboard
sehen soll, bekäme nicht automatisch Backend-Rechte – und umgekehrt.

## Entscheidung

Zwei **getrennte Rollen** statt eines `is_staff`-Flags, definiert in
`booking/permissions.py` – die fachliche Rollendefinition (Admin = Superuser,
Verwaltung = Gruppe „Verwaltung“) steht in Fachkonzept § 14:

- **Admin** → `is_admin` (Django-Superuser): volles Backend `/admin/`.
- **Verwaltung** → `is_verwaltung` (Gruppe „Verwaltung“ ODER Admin, Konstante
  `VERWALTUNG_GROUP`): nur das Dashboard `/verwaltung/`, **kein** Backend.

`is_verwaltung` ist bewusst **nicht** an `is_staff` gekoppelt (Kommentar in
`permissions.py:22-31`). Die Gruppe legt Migration `booking/0027_verwaltung_group`
an; `ensure_verwaltung_group` ist idempotent. `booking/context_processors.py:roles`
stellt `is_admin`/`is_verwaltung` allen Templates bereit (Nav-Punkte „Verwaltung“ vs.
„Backend“). Zuordnung = ein Häkchen (User in die Gruppe „Verwaltung“).

## Betrachtete Alternativen

- **Nur `is_staff`:** vermischt Backend-Zugang und Dashboard-Zugang; keine saubere
  „lesend, aber kein Backend“-Rolle.
- **Feingranulare Django-Permissions je Aktion:** mächtig, aber für ein kleines Team
  unnötig komplex zu pflegen.

## Konsequenzen

**Positiv**
- Klare, einfache Zuordnung (ein Gruppen-Häkchen) ohne Einzelrechte.
- Verwaltung kann operativ arbeiten, ohne Stammdaten/Buchungen ändern zu können.

**Negativ**
- Zwei Begriffe (Admin/Verwaltung) müssen im Team verstanden sein.
- Sonderfälle (z. B. Beds24-Import nur für Admin) müssen je View zusätzlich geprüft
  werden (`booking/views.py:beds24_import` → `is_admin`).
