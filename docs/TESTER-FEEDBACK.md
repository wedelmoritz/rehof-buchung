# Tester-Feedback – Vorlage

Diese Vorlage als **geteiltes Tabellenblatt** (Google Sheets / Excel / Nextcloud)
anlegen und den Link an die Tester:innen geben. Eine Zeile pro Rückmeldung.
So können wir Bugs und Wünsche **gemeinsam, sortierbar und ohne Doppelungen**
abarbeiten.

## Spalten

| Spalte | Inhalt | Beispiel |
|---|---|---|
| **Nr.** | fortlaufend (automatisch) | 17 |
| **Datum** | wann gemeldet | 2026-06-27 |
| **Tester:in** | Name/Kürzel | A. Muster |
| **Rolle** | Mitglied · Verwaltung · Admin · Gast (extern) | Mitglied |
| **Kategorie** | siehe unten | Bug |
| **Bereich** | Seite/Funktion | Buchen · Kalender |
| **Gerät/Browser** | nur bei Bugs nötig | iPhone, Safari |
| **Titel** | ein knapper Satz | Häkchen verrutscht auf dem Handy |
| **Beschreibung / Schritte** | was passiert ist bzw. der Wunsch; bei Bugs: Schritte zum Nachstellen | 1) Buchen öffnen 2) … |
| **Erwartet vs. tatsächlich** | nur bei Bugs | Erwartet: links · Tatsächlich: rechts |
| **Priorität (Tester)** | blockierend · stört · kosmetisch · nice-to-have | stört |
| **Screenshot** | Link (optional) | … |
| **Status** | *von uns gepflegt:* offen · in Arbeit · erledigt · zurückgestellt · abgelehnt | offen |

## Kategorien

- **Bug** – etwas funktioniert nicht / falsch / Fehlermeldung.
- **Feature-Wunsch** – neue Funktion oder Erweiterung.
- **UX/Verständlichkeit** – funktioniert, ist aber unklar, umständlich oder missverständlich.
- **Inhalt/Daten** – falsche Texte, Preise, Quartiersangaben, Tippfehler.
- **Lob/Positiv** – was gut funktioniert (hilft uns beim Priorisieren).

## Priorität (Selbsteinschätzung der Tester:innen)

- **blockierend** – man kommt nicht weiter / Kernfunktion kaputt.
- **stört** – nervt spürbar, es gibt aber einen Umweg.
- **kosmetisch** – Darstellung/Feinschliff.
- **nice-to-have** – wäre schön, kein Druck.

## Import-Header (zum Einfügen in Sheets/Excel)

```
Nr.;Datum;Tester:in;Rolle;Kategorie;Bereich;Gerät/Browser;Titel;Beschreibung/Schritte;Erwartet vs. tatsächlich;Priorität (Tester);Screenshot;Status
```

> Tipp: „Kategorie“, „Priorität“ und „Status“ als **Dropdown** (Datenüberprüfung)
> anlegen – das hält die Tabelle sauber und filterbar.
