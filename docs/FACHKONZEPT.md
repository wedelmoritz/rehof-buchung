# Fachkonzept – Re:Hof Quartier-Buchung

Dieses Dokument ist die **einzige Quelle der fachlichen Regeln** (Geschäfts-/
Domänenlogik) des Buchungssystems: *was* gilt und *warum* – aus Sicht der
Genossenschaft, nicht aus Sicht der Technik. Konkrete Zahlen (Tagebudget, Karma-
Schritt, Aufbewahrungsfristen, Steuersätze …) stehen **hier** und werden in den
ADRs nicht wiederholt, sondern referenziert.

**Abgrenzung zu den ADRs:** Die [Architecture Decision Records](adr/README.md)
beschreiben **technische** Entscheidungen (Frameworks, Muster, Code-Struktur) und
ihre Abwägungen. Wo eine technische Entscheidung eine fachliche Regel umsetzt,
verweist die ADR auf den passenden Abschnitt hier (`Fachkonzept § …`). Die
Umsetzung im Code ist in [`CLAUDE.md`](../CLAUDE.md) kartiert.

> Hinweis: Dieses Dokument beschreibt Regeln, **keine** Rechtsberatung. Steuer-
> und Rechtsthemen (USt, Kassenrecht, DSGVO, Pflichttexte) sind vor dem Go-Live
> mit Steuerberatung bzw. Rechtsberatung zu klären (siehe § 13, § 15).

Inhalt:

1. [Mitglieder, Anteile & Tagebudget](#1-mitglieder-anteile--tagebudget)
2. [Quartiere & Äquivalenzklassen](#2-quartiere--äquivalenzklassen)
3. [Buchungsperiode & Lebenszyklus](#3-buchungsperiode--lebenszyklus)
4. [Saison & Buchungsregeln](#4-saison--buchungsregeln)
5. [Losverfahren](#5-losverfahren)
6. [Karma (Ausgleichsfaktor)](#6-karma-ausgleichsfaktor)
7. [Losungs-Workflow (Review)](#7-losungs-workflow-review)
8. [Wunschliste](#8-wunschliste)
9. [Buchung: Spontanbuchung & Buchungsfluss](#9-buchung-spontanbuchung--buchungsfluss)
10. [Buchung ändern, Warteliste & Wechselwunsch](#10-buchung-ändern-warteliste--wechselwunsch)
11. [Tage-Übertragung](#11-tage-übertragung)
12. [Externe Gäste](#12-externe-gäste)
13. [Rechnungen, Zahlung & Steuer](#13-rechnungen-zahlung--steuer)
14. [Rollen & Rechte](#14-rollen--rechte)
15. [Recht & Datenschutz](#15-recht--datenschutz)
16. [Benachrichtigungen](#16-benachrichtigungen)

---

## 1. Mitglieder, Anteile & Tagebudget

- **Anteil (Membership)** = eine Vielleben-eG-Nummer mit einem **Jahres-Tagebudget**.
  Art `kind`: **Voll** oder **Teil**.
- **Mitglied (Member)** = das Buchungs-Subjekt genau eines Benutzerkontos
  (Anzeigename, Rechnungsdaten, Karma). **Ohne Mitglieds-Profil kann niemand
  buchen.**
- **Anteils-Zuordnung (Share)** verbindet Nutzer ↔ Anteil mit einem **festen
  Tage-Anteil**. Ein Nutzer kann an **mehreren** Anteilen hängen; sein Budget ist
  dann die **Summe** der Anteile (ganze Tage). Mehrere Nutzer können sich einen
  Anteil teilen (**Tandem/Teil**).

**Tagebudget (Kontingent):**

- **50 Tage pro Kalenderjahr** je Mitglied (Standard; am Anteil hinterlegt).
- Davon höchstens **25 Tage über die Wunschliste** (Losung); der Rest läuft über
  die normale/spontane Buchung.
- **Kein Übertrag ins Folgejahr** – das Kontingent gilt je Kalenderjahr frisch.
- Tage sind **an andere Mitglieder übertragbar** (§ 11).

---

## 2. Quartiere & Äquivalenzklassen

- **Quartier** = eine buchbare Unterkunft. Merkmal **`accessible`**
  (barrierearm/-frei) für die Eignungsfilterung nach Personenzahl/Barrierefreiheit.
- **Quartier-Saison** (optional, jährlich wiederkehrend): außerhalb der Saison ist
  ein Quartier **nicht buchbar**. Leer = ganzjährig.
- **Äquivalenzklasse** = eine Gruppe **gleichwertiger** Quartiere. Die Losung darf
  innerhalb einer Klasse auf ein gleichwertiges Quartier **ausweichen**, bevor ein
  Wunsch als Verlust zählt. Welche Quartiere gleichwertig sind, ist eine
  **fachliche Datenentscheidung** (im Backend pflegbar), keine Programmlogik.
- **Saisonale Übernachtungspreise** (für externe Gäste, § 12) über eine jährlich
  wiederkehrende Preisstaffel; sonst gilt der Basispreis pro Nacht.

---

## 3. Buchungsperiode & Lebenszyklus

- **Pro Buchungsjahr genau EINE Periode** (das Zieljahr ist eindeutig).
- Eine Periode vereint **Jahres-Losung** und **buchbaren Zeitraum**, gesteuert über
  ihren **Status**:

  `draft` (Entwurf) → `wishes_open` (Wünsche offen) → `lottery_ready` (zur Auslosung
  freigegeben) → `lottery_review` (Losung gelaufen, **unbestätigt**) → `lottery_done`
  (bestätigt/veröffentlicht) → `free_booking` (freie Bebuchbarkeit) → `ended`
  (beendet). `suspended` (unterbrochen) sperrt vorläufig.

- **Termine** der Periode: Wunsch-Fenster (offen/Schluss), Losungs-Zeitpunkt,
  buchbar ab/bis. Der Status wird normalerweise **aus den Terminen abgeleitet** und
  vom Hintergrund-Scheduler **nur vorwärts** geschaltet (nie zurück, nie automatisch
  aus `lottery_review` heraus – siehe § 7).
- Die **normale Buchung** ist nur im Status `free_booking` möglich.
- Die **Losung ist bewusst NICHT durch den buchbaren Zeitraum begrenzt**: sie vergibt
  das Folgejahr im Voraus, bevor dessen Zeitraum auf `free_booking` steht.

---

## 4. Saison & Buchungsregeln

**Saison-Regeln** (jährlich wiederkehrend, Monat/Tag ohne Jahr) – je Zeitraum
optional:

- **Mindestnächte** (`min_nights`): kürzere Aufenthalte sind nicht buchbar.
- **Parallel-Limit** (`max_parallel_units`): wie viele Wohneinheiten eine Partei
  gleichzeitig belegen darf.
- **Aufenthaltsdeckel** (`max_stay_nights`): Obergrenze der Einheiten-Nächte.

**Wo die Regeln greifen:**

- **Mindestnächte** (+ Einzel-Aufenthaltsdeckel): bei der normalen Buchung, beim
  **Eintragen/Einreichen der Wunschliste** und bei **externen Buchungen**.
- **Parallel-Limit** und **Aufenthaltsdeckel über mehrere Buchungen**: bei der
  normalen Buchung **und in der Losung** (ein gedeckelter Wunsch wird dort
  **übersprungen** – kein Verlust, kein Karma; siehe § 5).

**Schulferien** (jährlich wiederkehrend): werden im Kalender angezeigt **und**
setzen – wenn mit Regelfeldern versehen – im Zeitraum dieselben Regeln durch wie
eine Saison-Regel. Leere Regelfelder = nur Anzeige.

**Freischaltungs-Semantik (Schnittmenge, „UND"):** Ein Zeitraum ist nur dann
buchbar, wenn **sowohl** das globale Zeitraum-Fenster der Periode **als auch** die
Quartier-Saison ihn freigeben. Beide Bedingungen müssen erfüllt sein.

**Externen-Mindestaufenthalt:** Default **identisch zu intern** (inkl. Saison);
optional im Backend auf einen abweichenden festen Wert umstellbar (§ 12).

---

## 5. Losverfahren

Ziel: eine **faire**, **strategiesichere** Vergabe der umkämpften Wunsch-Slots.

- **Gewichtete Zufallsreihenfolge im Runden-Prinzip** (Random Serial Dictatorship,
  RSD): In jeder Runde wird je Partei **höchstens ein** Wunsch erfüllt; die
  Reihenfolge der Parteien wird je Runde **gewichtet zufällig** gezogen (Gewicht =
  Karma, § 6).
- **Reproduzierbar** über einen Seed; die Ziehung ist damit nachvollziehbar/auditbar.
- **Ausweichen** auf gleichwertige Quartiere derselben Äquivalenzklasse (§ 2), bevor
  ein Wunsch als Verlust zählt.
- **Nur eingereichte Wünsche** nehmen teil (§ 8).
- **Strategiesicherheit:** Es darf sich **nicht lohnen**, Wünsche taktisch zu
  ordnen oder zu verstecken. Diese Eigenschaft ist deterministisch getestet und
  muss erhalten bleiben.

**Skip-Regeln (wahren die Strategiesicherheit):**

- Ein Wunsch, der das **Budget** (§ 1) oder einen **Deckel/das Parallel-Limit** (§ 4)
  verletzen würde, wird **übersprungen** – das zählt **nicht** als Verlust und gibt
  **kein** Karma (wie ein Budget-Übersprung).
- Ein Skip übergeht die Partei **nicht**: in **derselben** Runde wird sofort der
  nächste Wunsch derselben Partei geprüft.

**Fairness-Nachweis:** Dass gleich gestellte Mitglieder statistisch dieselbe Chance
haben („equal treatment of equals") und dass das Karma nachweisbar wirkt, wird per
Monte-Carlo-Simulation belegt (Chi-Quadrat-Anpassungstest + Wilson-Konfidenz-
Intervall). Der Nachweis ist für Mitglieder einsehbar.

---

## 6. Karma (Ausgleichsfaktor)

Karma gleicht Pech über die Jahre aus, ohne die Strategiesicherheit zu brechen:

- **+0,1 pro echtem Verlust** (ein umkämpfter Wunsch, der nicht erfüllt wurde).
- **Deckel 1,5** (mehr Gewicht ist nicht möglich).
- **Reset auf 1,0** beim Gewinn eines **umkämpften** Slots.
- Ein **Budget-/Deckel-Skip** (§ 5) ist **kein** Verlust und verändert das Karma
  **nicht**.

Das Karma fließt als **Gewicht** in die Reihenfolge-Ziehung der Losung ein (§ 5).
Vor jedem bestätigungspflichtigen Lauf wird der Karma-Stand gesichert, damit eine
unbestätigte Losung vollständig zurückgenommen werden kann (§ 7).

---

## 7. Losungs-Workflow (Review)

Eine Losung wird **nicht** sofort veröffentlicht, sondern durchläuft einen
**Bestätigungs-Workflow**:

1. **Lauf** → Status `lottery_review`. Die Zuteilungen sind **vorläufig**: sie
   blockieren zwar die Verfügbarkeit, sind aber für Mitglieder **unsichtbar**; es
   werden **keine** Benachrichtigungen zugestellt (nur vorbereitet).
2. **Bestätigen** → veröffentlicht: Zuteilungen werden sichtbar,
   Benachrichtigungen/Mails gehen raus, Status `lottery_done`. **Danach kein Undo.**
3. **Zurücknehmen** (nur solange unbestätigt) → löscht die vorläufigen Zuteilungen,
   stellt das Karma aus dem Sicherungsstand wieder her, Status zurück auf
   `lottery_ready`.

Der Hintergrund-Scheduler schaltet **nie automatisch** aus `lottery_review` heraus –
die Freigabe ist immer eine bewusste Handlung der Verwaltung/Admin. Ein erneuter
Lauf rollt einen vorhandenen unbestätigten Lauf zuerst zurück (kein Karma-Aufsummieren).

---

## 8. Wunschliste

- Mitglieder tragen Wünsche fürs Folgejahr ein und **priorisieren** sie.
- Ein Wunsch hat den Zustand **Entwurf** oder **eingereicht**. **Nur eingereichte
  Wünsche** (`submitted=True`) nehmen am Losverfahren teil (§ 5).
- Wünsche bleiben bewusst **änderbar**, solange das Wunsch-Fenster offen ist.
- Höchstens **25 Tage** des Jahresbudgets laufen über die Wunschliste (§ 1).
- **Mindestnächte** werden bereits beim Eintragen/Einreichen geprüft (§ 4).

---

## 9. Buchung: Spontanbuchung & Buchungsfluss

- Die **normale/spontane Buchung** ist im Status `free_booking` der Periode möglich
  (§ 3) und prüft Budget (§ 1), Freischaltung (§ 4) und Regeln (§ 4).
- **Zweistufiger Fluss:** Erst **Verfügbarkeit/Auswahl** (Ampel-Kalender, Quartiere
  nach Personenzahl/Barrierefreiheit, Mindestnächte-Hinweis), dann ein
  **Bestätigungsschritt** – erst dieser legt die Buchung verbindlich an. So sieht
  man Fehler/Verstöße, **bevor** etwas verbindlich wird.
- Optional kann beim Buchen eine **Endreinigung** mitgebucht werden (als
  Hofladen-Position, § 13).
- Bei Belegung kann man sich auf die **Warteliste** setzen (§ 10).

---

## 10. Buchung ändern, Warteliste & Wechselwunsch

**Buchung ändern** (deckt Zeitraum, Unterkunft-Wechsel und Personenzahl ab):

- **Verlängern**: spontan, solange die zusätzlichen Nächte frei, freigeschaltet und
  im Budget sind.
- **Verkürzen**: nur wenn der **Mindestaufenthalt gewahrt** bleibt **und** die frei
  werdenden Nächte **≥ 7 Tage** in der Zukunft liegen.
- **Unterkunft-Wechsel**: spontan möglich (nur in ein freies Quartier); meldet das
  alte Quartier ebenso als „spontan frei". Die 7-Tage-Frist gilt nur fürs reine
  Verkürzen im selben Quartier.

**Spontan frei → Benachrichtigung:** Wird ein Zeitraum frei (Storno/Verkürzen/
Wechsel), bekommt die **Warteliste** für genau diesen Zeitraum eine Nachricht;
zusätzlich gibt es eine **Rundmeldung an alle** (In-App + E-Mail).

**Wechselwunsch:** Ein Mitglied kann ein anderes um einen **Quartiertausch** bitten –
auch bei nur **überlappenden** Zeiträumen (mit Hinweis). Die/der Empfänger:in stimmt
zu oder lehnt ab.

---

## 11. Tage-Übertragung

- Ein Mitglied kann **Tage aus seinem Jahreskontingent** an ein anderes Mitglied
  abgeben.
- **Nur innerhalb desselben Kalenderjahres** (kein Übertrag ins Folgejahr).
- Der Übertrag ist **verbindlich**; auf welcher (privatrechtlichen) Basis er erfolgt
  – Schenkung, Bezahlung, Tausch – regeln die Beteiligten **selbst**. Die
  Genossenschaft/App vermittelt **keine** Gegenleistung.

---

## 12. Externe Gäste

Gäste ohne Mitgliedschaft können Quartiere buchen und bezahlen:

- **Öffentlich, ohne Login**; Zugriff auf die eigene Buchung über einen
  **Magic-Link** (Token).
- **Regeln** (im Backend konfigurierbar): z. B. Anreise nur **Mo–Do**,
  **Mindestaufenthalt** (Default = intern inkl. Saison, optional eigener fester
  Wert), **Vorlauf**.
- **Preise**: Basispreis pro Nacht bzw. **saisonale** Preisstaffel (§ 2);
  zzgl. Reinigung und USt (§ 13).
- **Anzahlung** (`deposit_percent`) und **Storno-Staffel** (kostenfrei bis X Tage /
  Teil-Erstattung mit Prozentsatz bis Y Tage / danach keine), **Säumniszuschlag**.
- Externe Buchungen **blockieren die Verfügbarkeit** wie interne und erscheinen im
  internen Kalender neutral als „extern".
- Abrechnung über die **gleiche Rechnung** wie für Mitglieder (§ 13); Online-Bezahlung
  möglich.

---

## 13. Rechnungen, Zahlung & Steuer

**Rechnung** (gilt für **Mitglieder** [Hofladen] **und** Gäste [externe Buchung]):

- Nummernkreis je Monat, Status-Lebenszyklus offen → bezahlt-gemeldet →
  bestätigt/archiviert, mit §14-Pflichtangaben und Steuer-Aufschlüsselung.
- **Monatlich** (Sammelrechnung) **oder sofort** abrechenbar.
- **Offene Posten**: Fälligkeit + Überfälligkeit, **Zahlungserinnerung** (idempotent).

**Umsatzsteuer** (im Backend umschaltbar):

- **Regelbesteuerung**: pro Artikel – **Beherbergung 7 %**, **Zusatzleistungen 19 %**.
- **Kleinunternehmer (§ 19 UStG)**: Rechnung **ohne** MwSt-Ausweis + Hinweis.
- Die USt-Behandlung wird **je Rechnung gesnapshotet** (bleibt stabil, auch wenn sich
  der Status später ändert).

**Kassen-/Steuerrecht:** Abrechnung bewusst **ohne TSE** – es gibt **keine**
Vor-Ort-Barzahlung, daher keine Kassenfunktion nach KassenSichV/§146a AO. (USt-Status
und Kassenfrage vor Go-Live mit Steuerberatung klären – keine Rechtsberatung.)

**Zahlung:**

- **Online-Bezahlung** (Mollie) für Hofladen **und** Gäste auf Rechnungs-Ebene;
  ohne API-Key ein eingebauter Test-/Sandbox-Modus. **Online bezahlt ⇒ Rechnung
  sofort bestätigt/archiviert** (kein Kontoabgleich nötig).
- **Kontoabgleich**: Kontoauszug importieren; **eindeutige** Treffer (Rechnungsnummer
  + exakter Betrag) werden automatisch verbucht, nicht eindeutige bleiben zur
  manuellen Zuordnung offen.
- **Anzahlung** (heute informativ) und automatische **Storno-Erstattung** (heute
  manuell) sind als Ausbaustufe vorgesehen.

---

## 14. Rollen & Rechte

- **Mitglied** – bucht, pflegt sein Profil, sieht eigene Buchungen/Rechnungen.
- **Verwaltung** (Gruppe „Verwaltung") – nur das operative **Dashboard**
  (`/verwaltung/`): Buchungen/Losung **lesend**, Reinigungs-/Buchungslisten,
  Rechnungen mahnen, Kontoabgleich, Hofladen-Katalog pflegen. **Kein** Backend.
- **Admin** (Superuser) – volles **Backend** (`/admin/`): Stammdaten, Buchungen
  ändern, **Losung starten/bestätigen/zurücknehmen**.
- **Gast** (extern) – ohne Konto, Zugriff nur auf die eigene Buchung per Magic-Link.

Eine Person erhält die Verwaltungs-Rolle, indem sie der Gruppe „Verwaltung"
zugeordnet wird. Admin = Django-Superuser.

**Konto-Anlage:** Vom Backend oder per Beds24-Import angelegte Benutzer **vergeben
ihr Passwort selbst** über einen Einladungs-Link per E-Mail – Admins setzen kein
Passwort. Die E-Mail-Adresse ist dafür Pflicht (und zugleich der Login).

---

## 15. Recht & Datenschutz

**Pflichttexte** (im Backend konfigurierbar, öffentlich verlinkt):
**Impressum** (Pflicht, § 5 DDG), **Datenschutzerklärung** (DSGVO), **AGB**.

**Datensparsamkeit & Aufbewahrung (DSGVO):** Abgelaufene Daten werden täglich
automatisch gelöscht/pseudonymisiert. Fristen (per Einstellung überschreibbar):

| Daten | Frist | Aktion |
|---|---|---|
| Versendete E-Mails (Outbox, inkl. Anhang) | **90 Tage** | löschen |
| Benachrichtigungen | **180 Tage** | löschen |
| Bank-Transaktion – Rohdaten | **90 Tage** | leeren |
| Beds24-Import | **180 Tage** | löschen |
| Bank-Import | **365 Tage** | löschen |
| Erledigte Wechsel-/Wartelisten-Einträge | **180 Tage** | löschen |
| Wünsche beendeter Perioden | **2 Jahre** | löschen |

**Aufbewahrungspflicht:** **Rechnungen & Zahlungen bleiben 10 Jahre** unangetastet
(§ 147 AO / § 14b UStG).

**Recht auf Löschung (Art. 17 DSGVO):** Eine Mitglieds-**Anonymisierung** leert
Profil-PII und Freitexte und deaktiviert das Login; die gesetzlich aufzubewahrenden
Rechnungs-Snapshots bleiben erhalten.

---

## 16. Benachrichtigungen

Mitglieder werden über relevante Ereignisse informiert – **In-App** (immer), per
**E-Mail** (Opt-out je Mitglied) und optional als **Web-Push** (Opt-in je Gerät):

- **Konto angelegt** – Einladung, das **Passwort selbst zu setzen** (neue Konten
  aus Backend/Import; Admins vergeben kein Passwort, § 14),
- **Losergebnis** (nach Bestätigung der Losung, § 7),
- **Wartelisten-Platz frei** / **spontan frei** (§ 10),
- **Rechnung erstellt**, **Zahlungseingang bestätigt** (§ 13),
- **Konto-Freischaltung** (Mitglieds-Profil zugeordnet).

E-Mails laufen entkoppelt über eine Warteschlange (gut für Massenmails); Web-Push ist
nur aktiv, wenn die Server-Schlüssel gesetzt sind.
