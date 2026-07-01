# 0078 – Tester-Feedback: konfigurierbare Grenzen, sanfte Hinweise, UX-Feinschliff

## Status

Accepted (2026-07-01)

> Setzt die im Test (Rückmeldungen „Judith", Zeilen #2–#26) offen gebliebenen
> Punkte um, die bewusst zur Delegations-/Klärungsentscheidung standen. Ergänzt die
> Buchungsrichtlinien (ADR 0075/0076) und den Tausch (ADR 0077).

## Kontext

Aus dem Testdurchlauf blieben sieben Punkte, die nicht eindeutig „Bug" oder
„fertig" waren, sondern eine **fachliche Entscheidung** verlangten. Für jeden gab es
die Optionen **a) so lassen · b) umsetzen · c) konfigurierbar**. Der Vorstand/die
Delegation hat je Punkt entschieden; diese ADR hält die Entscheidungen und ihre
technische Umsetzung fest.

Leitplanken für alle Punkte: **das Losverfahren bleibt unangetastet** (Strategie-
sicherheit, ADR 0062/0073), **Regeln werden server-seitig erzwungen** (Frontend-
Hinweise sind nur Komfort), und wo eine Grenze politisch ist, wird sie
**konfigurierbar** statt fest verdrahtet.

## Entscheidung

### #5 – Obergrenze für Wünsche je Periode: **konfigurierbar (Default aus)**

Neues Feld `BookingPolicy.max_wishes_per_period` (PositiveInteger, Default **0 =
unbegrenzt**). `services.add_wish` prüft die Grenze server-seitig beim Eintragen; bei
0 ändert sich nichts. Bewusst per Default aus, damit **Rückfall-Wünsche** (mehr
Wünsche als Budget, ADR 0073) möglich bleiben – die Grenze ist nur für den Fall
gedacht, dass die Delegation eine Begrenzung beschließt. Sichtbar in „Meine Wünsche"
(„X von höchstens Y") und auf der Hilfeseite (`booking_policy_summary`).

### #2b – Überlappende Wünsche fürs selbe Quartier: **erlaubt + sanfter Hinweis**

Bleibt bewusst **zulässig** (das Losverfahren berücksichtigt in einem überlappenden
Zeitraum ohnehin nur einen davon). Nur **exakte** Doppel-Wünsche werden abgelehnt
(ADR/Feedback #2a). Neu: je Wunsch ein **informativer Hinweis**, wenn er sich mit
einem anderen eigenen Wunsch fürs **selbe Quartier** überlappt – rein aus den bereits
geladenen Wünschen berechnet (0 zusätzliche Abfragen), keine Sperre.

### #8 – Tausch-Anfragen abschaltbar: **Opt-out je Mitglied (Default an)**

Neues Feld `Member.accept_swap_requests` (Bool, Default **True**). Wer es abschaltet,
erscheint für andere **nicht** als Tausch-Partner (server-seitig in
`create_swap_request` erzwungen, zusätzlich im UI gefiltert). Umschaltbar im Profil
(„Benachrichtigungen"/Einstellungen). Der informative Bereich „Wer ist zur gleichen
Zeit da?" bleibt unberührt (rein Anzeige).

### #16b – Kurze freie Lücken beim Buchen sichtbar machen: **umsetzen**

Unter dem Buchungs-Kalender listet ein **anklickbarer** Abschnitt die nächsten
**kurzen freien Lücken** (exakt zwischen zwei Belegungen, beidseitig geschlossen) je
Quartier – ideal für Lückenfüllung (ADR 0075). Aus der ohnehin geladenen Belegung
berechnet (wenige Abfragen). Klick übernimmt Zeitraum + Quartier in die Auswahl.

### #17 – „Passende freie Unterkunft"-Sperre barrierefrei: **umsetzen**

Die Kopplung „Personenzahl außerhalb des Rahmens nur, wenn nichts Passendes frei ist"
(`has_fitting_free_quarter`, ADR 0076) berücksichtigt jetzt den Bedarf
**barrierefrei** (`need_accessible`): Wer eine barrierefreie Unterkunft braucht, wird
nicht auf eine freie, aber **nicht** barrierefreie Unterkunft verwiesen. Der Bedarf
wird durch `book_spontaneous`/`book_confirm`/`free_quarters_for` durchgereicht.

### #24 – Desktop-Navigation nach links: **umsetzen**

Die vertikale Navigationsleiste steht auf dem Desktop jetzt **links** statt rechts
(gewohnte Lese-/Bedienrichtung). Reine CSS-/Layout-Änderung in `base.html`; die
mobile Tab-Leiste unten bleibt unverändert.

### #26 – Selbst-Meldung „Habe ich überwiesen" abschaltbar: **konfigurierbar (Default an)**

Neues Feld `ShopConfig.allow_self_report_paid` (Bool, Default **True**). Ist es aus,
entfällt der „Habe ich überwiesen"-Knopf auf der Rechnung (UI **und** server-seitige
Aktion `mark_paid`) – dann zählt allein der **Kontoabgleich** bzw. die
**Online-Zahlung**. Für Betriebe, die die reine Selbst-Meldung nicht wollen.

## Betrachtete Alternativen

- **#5 fest begrenzen:** verworfen – Rückfall-Wünsche sind ein bewusstes Feature;
  eine Grenze ist eine politische Entscheidung, daher konfigurierbar.
- **#2b überlappende Wünsche verbieten:** verworfen – schränkt legitime Strategie ein
  und ist fürs Losverfahren irrelevant; ein Hinweis genügt.
- **#8 Tausch global abschalten:** verworfen zugunsten einer feineren
  **Opt-out-je-Mitglied**-Lösung.
- **#26 Selbst-Meldung ersatzlos entfernen:** verworfen – viele Betriebe nutzen sie;
  daher konfigurierbar statt hart entfernt.

## Konsequenzen

**Positiv** – politische Grenzen (#5, #26) sind konfigurierbar statt verdrahtet;
sicherheitsrelevante Regeln (#8, #17) werden **server-seitig** erzwungen, nicht nur im
UI; sanfte Hinweise (#2b, #16b) verbessern die Bedienung ohne das Losverfahren zu
berühren; alle Neuerungen sind effizient (Wiederverwendung geladener Belegung, keine
N+1). Migrationen für die drei neuen Felder (`BookingPolicy`, `Member`, `ShopConfig`).

**Grenzen** – die neuen Grenzwerte sind bewusst per Default **neutral** (unbegrenzt /
Tausch an / Selbst-Meldung an), damit sich das Verhalten ohne aktive Entscheidung
nicht ändert.
