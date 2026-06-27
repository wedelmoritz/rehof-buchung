# 0050 – Service-Layer als Paket: `services.py` in fachliche Submodule aufteilen

## Status

Accepted (2026-06-27)

## Kontext

Der Service-Layer (ADR 0002) ist die einzige Brücke zwischen Django-Modellen und
der reinen Logik – und damit der Ort, an dem über die Zeit **die gesamte
Geschäftslogik** zusammenläuft: Losung, Buchung, Warteliste, Wünsche, Kalender,
externe Gäste, Dashboard-Auswertungen, Beds24-Migration, DSGVO-Aufräumen,
Benachrichtigungen. `booking/services.py` war zuletzt **~2250 Zeilen** mit rund
**90 Funktionen**. Das ist für eine einzelne Datei zu groß: Orientierung,
Review-Diffs und das Finden der „richtigen Stelle" (zentrales Prinzip in
CLAUDE.md) leiden. Eine fachliche Aufteilung war fällig – **ohne** das bewährte
Schichtenmodell oder die Aufrufschnittstelle anzutasten.

## Entscheidung

`booking/services.py` wird zu einem **Paket** `booking/services/` mit fachlichen
Submodulen. Das Verhalten und die öffentliche Schnittstelle bleiben **exakt
gleich**: `booking/services/__init__.py` re-exportiert alle Namen, sodass
`from booking import services as svc` und sämtliche `svc.*`-Aufrufe (sowie
`from booking.services import …`) **unverändert** funktionieren – inklusive der
extern genutzten Hilfsnamen mit Unterstrich (`_annotate_cleaning`,
`_in_season_range`).

**Submodule (in topologischer Schichtung – Pfeil = „importiert von"):**

| Modul | Inhalt | hängt ab von |
|---|---|---|
| `dates` | Monats-/Wochentags-Konstanten, Monatsgrenzen, Schulferien | – |
| `notify` | In-App-Notifications, Outbox-Mails, Web-Push, URL-Helfer | – |
| `slots` | Verfügbarkeit/Freiheit, Saison-Regeln, Mindestnächte, Freischaltung, Lücken/Splitting | – |
| `beds24_ops` | Beds24-CSV-Staging, Mitglied anlegen, Übernahme als Buchungen | – |
| `retention` | DSGVO-Aufbewahrung/Löschung, Anonymisierung | – |
| `calendars` | Kalender-Aufbau (Buchen/Wunsch/Community/Belegung/Extern), Tagesdetail | `dates`, `slots` |
| `lottery_ops` | Losung durchführen/bestätigen/zurücknehmen, Notices, Fairness | `slots`, `notify` |
| `wishes` | Wunschliste eintragen/umsortieren/einreichen | `slots` |
| `booking_ops` | Spontanbuchung, Warteliste, Storno/Ändern, Wechselwunsch, Tage-Übertragung | `slots`, `notify` |
| `dashboard` | Statistik, Reinigungs-/Buchungslisten, Exporte/Texte, Monats-Mail | `dates`, `notify` |
| `external_ops` | Externe Gäste: Angebot/Verfügbarkeit, Buchung/Storno, Magic-Link | `slots`, `notify`, `booking_ops` |

Die Abhängigkeiten bilden einen **azyklischen Graphen** (DAG): fünf Submodule sind
abhängigkeitsfrei (Blätter), die übrigen hängen nur an tieferen Schichten. Die
**einzige** Kante zwischen zwei „Operations"-Modulen ist `external_ops →
booking_ops` (eine externe Stornierung meldet einen frei gewordenen Zeitraum über
`notify_waitlist_if_free` an die Warteliste). Damit gibt es **keine zirkulären
Importe**; Submodule importieren ihre Helfer direkt aus dem jeweils tieferen Modul
(`from .slots import …`), nicht über das Paket.

**Mechanik der Aufteilung:** Der Schnitt erfolgte **mechanisch** (AST-gestützt) –
jede Top-Level-Definition wurde unverändert in ihr Zielmodul verschoben, die nötigen
Importe je Modul aus der tatsächlichen Verwendung abgeleitet. So ist garantiert,
dass **kein Code geändert** wurde, nur umsortiert. Beide Test-Suiten (68 reine +
212 Integration) sind das Sicherheitsnetz und bleiben grün; es gibt **keine
Migration** (keine Modelländerung).

## Betrachtete Alternativen

- **Eine große `services.py` belassen:** verworfen – die Größe behindert genau das
  „gezielt an der richtigen Stelle ändern", das CLAUDE.md vorgibt.
- **Aufteilung nach technischen Kriterien (z.B. „queries" / „mutations"):**
  verworfen – die fachliche Gliederung (Losung, Buchung, Wünsche, extern …) deckt
  sich mit der Art, wie an der Codebasis gearbeitet wird, und mit der Backend-
  Sektionierung (ADR 0049).
- **Voll-Hexagonal (Ports/Adapter, Repositories):** verworfen für diesen Schritt –
  zu invasiv; das Drei-Schichten-Modell (ADR 0002) bleibt bewusst bestehen. Diese
  Aufteilung ist eine reine **Datei-Organisation** innerhalb der bestehenden
  Service-Schicht.
- **Submodule mit Namen wie `lottery`/`external`/`availability`:** verworfen, weil
  sie mit den **reinen** Modulen `booking/lottery.py`, `booking/external.py`,
  `booking/availability.py` kollidieren würden. Daher `lottery_ops`, `external_ops`,
  `beds24_ops` bzw. `slots` (statt `availability`).

## Konsequenzen

**Positiv**
- Deutlich bessere Orientierung: ~150–500 Zeilen je fachlichem Modul statt 2250 in
  einer Datei; Review-Diffs landen im passenden Modul.
- Die Aufrufseite ändert sich **nicht** – kein Risiko für Views/Tests/Commands,
  keine Migration.
- Der azyklische Schichtenschnitt macht die Abhängigkeiten explizit und sichtbar.

**Negativ / Grenzen**
- Mehr Dateien; eine neue Service-Funktion muss bewusst im richtigen Submodul
  landen (sonst wächst fälschlich ein „Sammelmodul").
- Das `__init__` re-exportiert per `import *` – neue Namen sind automatisch dabei,
  aber die Aggregation ist etwas „magisch" (bewusst, um die Schnittstelle stabil
  und wartungsarm zu halten).
- Querschnitts-Helfer (z.B. `notify_waitlist_if_free`) wohnen in *einem* Modul
  (`booking_ops`); andere Module importieren sie dort – die Heimat ist eine
  Konvention, kein harter Schnitt.
