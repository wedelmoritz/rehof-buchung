# 0110 – Korrektheit: Storno-Rechnung entwerten + Doppelbuchungs-Zeilensperre

## Status

Accepted (2026-07-20) · härtet [ADR 0013](0013-buchungskorrektheit-zeilensperre.md)
(Zeilensperre), [ADR 0023](0023-externe-gaeste-magic-link.md) (externe Gäste),
[ADR 0016](0016-hofladen-eigene-app-generalisierte-invoice.md) (Rechnung) · verweist auf
[ADR 0038](0038-zahlungsanbindung-anzahlung-storno-erstattung.md) (Erstattung/Storno-Gebühr,
Roadmap). **Umgesetzt (2026-07)** – Ergebnis des vollständigen Bug-Reviews.

## Kontext

Zwei verifizierte Korrektheits-Funde des Voll-App-Reviews:

1. **Externe Stornierung ließ die Rechnung offen.** `cancel_external_booking` setzte nur
   die `ExternalBooking` auf `CANCELLED`, rührte die verknüpfte `Invoice` aber nicht an.
   Eine noch **unbezahlte** (OPEN) Rechnung blieb offen → `overdue_invoices` nahm sie auf
   und der Mahnlauf mahnte den Gast über den **vollen** Betrag, obwohl die Buchung
   storniert war.
2. **Doppelbuchung möglich.** Der Doppelbuchungs-Schutz beruht auf der Quartier-
   Zeilensperre (`select_for_update`, ADR 0013); die nahmen aber nur `book_spontaneous`/
   `book_for_member`. `adjust_allocation` und `create_external_booking` prüften
   `quarter_is_free` **ohne** Sperre → parallele Requests konnten beide „frei" sehen und
   überlappend schreiben.

## Entscheidung

**1) Storno entwertet die unbezahlte Rechnung.** `Invoice` bekommt den Status `cancelled`.
`cancel_external_booking` (jetzt `@transaction.atomic`) setzt eine verknüpfte Rechnung mit
Status `OPEN` auf `cancelled` – sie fällt damit aus `open_invoices`/`overdue_invoices` und
dem Mahnlauf. Bereits **bezahlte/bestätigte** Rechnungen bleiben unangetastet (Erstattung
ist manuell, ADR 0038). Der Beleg bleibt erhalten (Aufbewahrung §147 AO). Eine etwaige
**Storno-Gebühr** (`preview["kept"]`) wird separat gestellt (ADR 0038, Roadmap).

**2) Zeilensperre in beiden Schreibpfaden.** `adjust_allocation` und
`create_external_booking` nehmen vor der Frei-Prüfung
`Quarter.objects.select_for_update().filter(pk=…)` – identisch zu `book_spontaneous`
(unter SQLite ein No-Op, unter PostgreSQL serialisiert es Buchungen desselben Quartiers).

## Architektur / Sicherheit / Performanz

- Kleine, gezielte Diffs; keine Verhaltensänderung für legitime Abläufe.
- Migration `shop/0020_alter_invoice_status` (neuer Status-Wert, additiv).
- Regressionstests `booking/tests_correctness.py`: Storno entwertet OPEN-Rechnung
  (nicht mehr überfällig) / lässt CONFIRMED unangetastet; belegtes Quartier bei
  adjust/extern abgelehnt. **Grenze:** der echte Nebenläufigkeits-Beweis der Sperre
  gehört zu den Zeilensperren-/Lasttests (ADR 0051), nicht in die Unit-Suite.

## Konsequenzen

**Positiv** – kein Falsch-Mahnen stornierter Buchungen; die Doppelbuchungs-Invariante
gilt jetzt in **allen** Buchungs-Schreibpfaden, nicht nur der Spontanbuchung.

**Negativ / Grenzen** – die anteilige **Storno-Gebühr** wird noch nicht automatisch neu
fakturiert (ADR 0038); die Storno-Entwertung waiviert bei freier Stornierung korrekt den
vollen Betrag, bei kostenpflichtiger Stornierung bleibt die Gebühr ein manueller/Roadmap-
Schritt.
