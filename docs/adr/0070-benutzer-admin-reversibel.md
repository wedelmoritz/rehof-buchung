# 0070 – Benutzer-/Mitglieder-Verwaltung: beidseitig editierbar + reversibel

## Status

Accepted (2026-06-29)

> Verfeinert ADR 0056/0068/0069 (Onboarding, Auto-Anteil, Identitäts-Modell).
> Mit dem Nutzer abgestimmt (Optionen 1a + 2a + Härtung der starken Aktionen).

## Kontext

Selbsttest der Benutzer-/Mitglieder-Verwaltung im Backend ergab konkrete Reibung:

- Der **Mitglieds-Anteil** eines Mitglieds ließ sich **nur von der Anteil-Seite**
  bearbeiten – von der Mitglied-Seite gar nicht (`MemberAdmin` war ausgeblendet und
  ohne Anteil-Liste; das Benutzer-Formular zeigte den Anteil **nur als Anzeige**).
- Auf der **Anteil-Seite** war das per-Zeile-„Löschen?" (Mitglied aus dem Anteil
  entfernen) optisch kaum vom großen roten **„LÖSCHEN"** (= *ganzer Anteil*) zu
  unterscheiden – Verwechslungsgefahr, ganzer Anteil weg.
- Starke Aktionen (Anteil/Mitglied löschen, Tage ändern) hatten **keine doppelte
  Bestätigung** und waren **nicht rückgängig** zu machen: die Historie war nur das
  read-only Django-`LogEntry` (kein „Zurückspringen").

## Entscheidung

**1a) Mitglied beidseitig editierbar.** `MemberAdmin` wird **sichtbar** und bekommt
eine **member-seitige `Share`-Inline**: Anteil wählen/wechseln, Tage-Anteil ändern,
ein Mitglied über „Löschen?" aus EINEM Anteil entfernen (entfernt nur die Zuordnung).
Das Benutzer-Formular verlinkt dorthin („Anteile bearbeiten / Tandem aufteilen →").
`MemberAdmin` erlaubt **kein Anlegen** (läuft über Benutzer/Onboarding) und **kein
hartes Löschen** (würde Buchungen mitlöschen – dafür „Mitglied anonymisieren").

**2a) Reversibilität über django-reversion.** Die Identitäts-Modelle **Benutzer,
Mitglied, Mitglieds-Anteil, Tage-Anteil** werden versioniert. Im Backend gibt es
damit **„GESCHICHTE" → diese Version wiederherstellen** (Revert) und – wo Löschen
erlaubt ist (Anteil/Benutzer) – **„Gelöschtes wiederherstellen"** (Recover). Der
**follow-Graph** ist bewusst gesetzt: ein Benutzer-Stand umfasst sein Mitglied und
dessen Tage-Anteile; ein Anteil-Stand seine Tage-Anteile – ein Revert stellt also
auch die zugehörigen Tage-Anteile wieder her. Registrierung **genau einmal** je
Modell (explizit in `booking/admin.py`), die Admin-Klassen erben `VersionAdmin`.
Begrenzt auf die Identitäts-Daten (nicht Buchungen/Rechnungen). pip-audit/CI laufen
mit; die reversion-Admin-Seiten sind **CSP-konform** (kein Inline-JS, nonce-Skripte).

**3) Starke Aktionen gehärtet.**
- Inline-„Löschen?" klar beschriftet („entfernt NUR die Zuordnung zu DIESEM Anteil –
  Anteil & Mitglied bleiben").
- **Doppelte Bestätigung** (CSP-konform, delegiert in `base_site.html`): vor dem
  großen „LÖSCHEN" eine zusätzliche Rückfrage **plus** Djangos Lösch-Seite; beim
  Speichern mit gesetztem „Löschen?"-Häkchen eine Rückfrage. Beide Hinweise nennen
  den Rückweg („rückgängig über GESCHICHTE").

## Betrachtete Alternativen

- **Member weiter ausblenden, nur Anteil-Seite verbessern (1b):** verworfen –
  beidseitig editierbar ist nachvollziehbarer und symmetrisch.
- **Reversibilität als Eigenbau (Soft-Delete/Undo):** verworfen – deckt nur
  Löschungen, nicht Feld-/Tage-Änderungen; mehr Wartung als eine etablierte Lib.
- **Nur Doppel-Bestätigung ohne echtes Zurückspringen:** verworfen – der Wunsch war
  explizit „zurückspringen können".

## Konsequenzen

**Positiv** – Mitglied↔Anteil ist von **beiden** Seiten bearbeitbar; Entfernen vs.
Ganz-Löschen ist klar getrennt und doppelt bestätigt; starke Fehlgriffe sind über
die Historie **wiederherstellbar** (inkl. Tage-Anteile). **Betrieb** – django-reversion
ist neue Abhängigkeit (Tabellen via `migrate`; **einmalig** nach dem Deploy
`manage.py createinitialrevisions` ausführen, damit BESTAND einen Ausgangs-Stand
hat). **Grenzen** – versioniert sind bewusst nur die Identitäts-Daten; Buchungen/
Rechnungen nicht. Reines hartes Löschen von Mitgliedern bleibt gesperrt
(Anonymisieren statt Löschen, DSGVO/Buchungs-Schutz).
