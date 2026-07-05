# 0094 – Buchungen durch die Verwaltung im Namen von Mitgliedern (Audit + Benachrichtigung)

## Status

Accepted (2026-07-05) · adressiert Feedback #50 · konkretisiert ADR 0087 (Punkt 9)

## Kontext

Die Betriebsleitung legt im Tagesgeschäft Buchungen **für** Mitglieder an (telefonische
Anfrage, Sonderfall) – heute im Backend (`AllocationAdmin`). Zwei Lücken: (1) das
betroffene Mitglied **erfährt es nicht** und findet plötzlich eine Buchung vor; (2) es
ist **nicht nachvollziehbar**, wer eine Buchung angelegt/geändert hat.

## Entscheidung

**Audit-Feld + Benachrichtigung am Backend-Hook**, ohne einen neuen Buchungs-Flow:

- **`Allocation.created_by`** (FK auf `auth.User`, `SET_NULL`, read-only im Admin):
  wer die Buchung im Backend angelegt/zuletzt geändert hat. Leer, wenn das Mitglied
  selbst über die App gebucht hat. Property `Allocation.by_management` = „von einem
  anderen Konto als dem Mitglied angelegt“.
- **`AllocationAdmin.save_model`** setzt `created_by = request.user` und ruft
  `services.notify_member_of_staff_booking(alloc, "new"|"change")` – In-App-
  `Notification` + E-Mail (Opt-in) ans Mitglied. Nur bei **echter** Feldänderung
  (`form.changed_data`) und **nicht** für `lottery`/`external` (die tragen ihre eigene
  Benachrichtigung). `delete_model`/`delete_queryset` melden `"cancel"` vor dem Löschen.
- **Hinweis in „Meine Buchungen“**: Buchungen mit `by_management` tragen die Marke
  „von der Verwaltung angelegt“ (Transparenz fürs Mitglied).

Bewusst **kein** eigener BL-Buchungs-Screen im Frontend (Feedback #50 „ohne
Ansichtswechsel“): das Backend bleibt der eine Ort für stellvertretende Buchungen; die
Domänenregeln (`Allocation.clean`, keine Doppelbuchung, ADR 0045) greifen dort ohnehin.

## Konsequenzen

**Positiv** – Mitglieder werden über stellvertretende Buchungen/Änderungen/Stornos
informiert; jede Backend-Buchung ist ihrem Urheber zuordenbar; kein neuer, doppelt zu
pflegender Buchungs-Flow.

**Grenzen** – `created_by` wird nur im Backend gesetzt (App-Buchungen bleiben leer, was
gewollt ist: „leer = selbst gebucht“). Ein echtes Änderungs-Journal (mehrere Einträge)
gibt es nicht; für Benutzer/Mitglied/Anteil deckt das `django-reversion` ab.
