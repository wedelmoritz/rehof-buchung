# Buchungs- und Losverfahren für die Ferienwohnungen

**Spezifikation – Stand: Entwurf zur Abstimmung in der Genossenschaft**

Dieses Dokument beschreibt, wie die Buchung der 12 Ferienwohnungen funktionieren soll. Es ist so geschrieben, dass es zwei Zwecke erfüllt: Es kann der Genossenschaft zur Entscheidung vorgelegt werden, und es dient anschließend als präziser Bauplan für die Software.

Stellen, an denen die Genossenschaft eine bewusste Wahl treffen muss, sind so markiert:

> **▶ Entscheidung der Genossenschaft:** …

---

## 1. Grundprinzip

Das Jahr teilt sich in zwei Buchungswege:

1. **Die Jahres-Losung** – einmal jährlich für die begehrten Zeiträume des Folgejahres. Alle melden gleichzeitig ihre Wünsche an; Konflikte werden fair ausgelost.
2. **Die Spontanbuchung** – ganzjährig für alle Termine, die nach der Losung noch frei sind. Hier gilt: zuerst kommt, zuerst bucht.

Dazu kommen drei unterstützende Bausteine: das **Tage-Konto** (wie viele Nächte habe ich, kann ich übertragen), die **Dienste & Waren** (Endreinigung, Sauna …) und die **externe Buchung** (Gäste ohne Mitgliedschaft).

Die Leitidee bei allem: **Das Verfahren muss verständlich, nachvollziehbar und manipulationssicher sein.** Lieber etwas einfacher, dafür von allen durchschaut, als perfekt-kompliziert und niemandem erklärbar. Vertrauen ist hier wichtiger als mathematische Eleganz.

---

## 2. Begriffe

| Begriff | Bedeutung |
|---|---|
| **Wunsch** | Eine gewünschte Buchung: eine (oder mehrere gleichwertige) Wohnung(en) + ein Zeitraum (von–bis). |
| **Konflikt** | Mehr Wünsche zielen auf dieselbe Wohnung im selben Zeitraum, als erfüllbar sind. |
| **Äquivalenzklasse** | Eine Gruppe von Wohnungen, die als gleichwertig gelten und gegeneinander getauscht werden dürfen. |
| **Ausgleichsfaktor** | Persönlicher Wert, der die Gewinnchance in der Losung leicht erhöht. Startet bei 1,0. |
| **Tage-Konto** | Persönliches Kontingent an Nächten pro Jahr. |
| **Clique** | Mehrere Mitglieder, die gemeinsam gewinnen oder verlieren wollen. |

---

## 3. Teil A – Die Jahres-Losung

### 3.1 Ablauf in vier Schritten

1. **Anmeldefenster** (z. B. 3 Wochen im Herbst): Alle Mitglieder tragen ihre Wünsche fürs Folgejahr ein. Reihenfolge der Eingabe spielt **keine** Rolle.
2. **Auflösung der Konflikte** durch das Losverfahren (siehe 3.2).
3. **Ergebnis & Einspruchsfrist**: Jeder sieht sein Ergebnis und die nachvollziehbare Ziehung. Eine kurze Frist erlaubt das Melden offensichtlicher Fehler.
4. **Bestätigung**: Die Buchungen werden fest. Was nicht verlost wurde, fällt in die Spontanbuchung.

> **▶ Entscheidung der Genossenschaft:** Wie viele Wünsche darf jedes Mitglied pro Losung abgeben? (Empfehlung: 2–3 priorisierte Wünsche, damit jeder eine realistische Chance auf *einen* Treffer hat, statt dass wenige alles abräumen.)

### 3.2 Das Losverfahren im Detail

Das Verfahren heißt fachlich **gewichtete Zufallsreihenfolge im Runden-Prinzip** (Round-Robin). Erst die einfache Idee, dann die genauen Regeln.

**Die einfache Idee:** Wir würfeln eine zufällige Reihenfolge aller Parteien aus. Dann wird **rundenweise** zugeteilt – wie beim Mannschaftswählen: In der ersten Runde bekommt jede Partei nur ihren **Erstwunsch**, in der zweiten Runde ihren Zweitwunsch, usw. So häuft niemand alle Sahnestücke auf einmal an. Der Ausgleichsfaktor sorgt dafür, dass Verlierer der Vorjahre etwas weiter vorne in der Reihenfolge landen.

**Warum Runden und nicht „jede Partei nimmt am Stück alles"?** Gäbe man jeder Partei nacheinander *alle* ihre Wünsche, würde die Partei auf Losplatz 1 sich die beiden begehrtesten Termine des Jahres (z. B. Pfingsten **und** Himmelfahrt) gemeinsam schnappen. Im Runden-Prinzip bekommt sie in Runde 1 nur **einen** davon; der zweite bleibt für die anderen im Spiel. Das verteilt die wenigen Premium-Termine deutlich gleichmäßiger – genau das, was bei den langen Wochenenden mit vielen Kollisionen zählt.

**Die genauen Regeln:**

1. **Reihenfolge auslosen.** Jede Partei erhält einen zufälligen Platz in der Warteschlange. Der Ausgleichsfaktor wirkt wie zusätzliche Lose: Wer den Faktor 1,1 hat, hat etwas höhere Chancen auf einen vorderen Platz als jemand mit 1,0. *(Technisch sauber und reproduzierbar über einen festen Zufalls-Startwert, damit die Ziehung im Nachhinein überprüfbar ist.)*
2. **Runde für Runde zuteilen.** In jeder Runde geht das System die Warteschlange einmal von vorn nach hinten durch. Jede Partei bekommt **einen** Wunsch zugeteilt – den höchstpriorisierten ihrer Liste, der noch vollständig frei ist.
3. **Ausweichen vor Verlieren.** Ist die konkret gewünschte Wohnung schon vergeben, aber eine **gleichwertige** (gleiche Äquivalenzklasse) noch frei, bekommt die Partei diese – statt leer auszugehen. Erst wenn in der ganzen Klasse nichts mehr frei ist, gilt der Wunsch als **verloren**.
4. **Kontingent beachten.** Eine Partei wird in den Runden so lange berücksichtigt, bis ihre **25 Wunsch-Nächte** aufgebraucht oder alle ihre Wünsche bearbeitet sind. Danach wird sie übersprungen. (Hintergrund: 50 Nächte/Jahr pro Partei, davon max. die Hälfte über die Wunschliste – Rest siehe Teil C.)
5. **Ausgleich gutschreiben.** Nur wer einen Zeitraum *wirklich wollte* und **gar keine** gleichwertige Wohnung bekommen hat, erhält für die **nächste** Losung einen erhöhten Ausgleichsfaktor (siehe 3.3).

Die Runden laufen, bis keine Partei mehr einen erfüllbaren Wunsch innerhalb ihres Kontingents hat. Was übrig bleibt, fällt in die Spontanbuchung.

### 3.2.1 Die wichtigste Eigenschaft: Tricksen lohnt sich nicht

Dies ist der zentrale Grund, warum das Verfahren glaubwürdig ist – und gehört in jede Erklärung gegenüber den Mitgliedern. Fachlich heißt die Eigenschaft **Strategiesicherheit**: Die **ehrliche** Angabe der wahren Wünsche ist für jede Partei *immer mindestens so gut* wie jeder Trick – egal, was die anderen tun. Niemand muss Wahrscheinlichkeiten ausrechnen oder Mitbewerber einschätzen. Jeder schreibt einfach auf, was er wirklich will, und das ist garantiert die optimale Strategie.

Der Grund ist eine einzige Struktureigenschaft:

> **Deine Wunschliste bestimmt nur, *was* du nimmst, wenn du an der Reihe bist – nicht, *wann* du dran bist, und nicht, was die *anderen* bekommen.**

Wann eine Partei dran ist, entscheidet allein das Los (plus der Ausgleichsfaktor aus den Vorjahren). Das ist von der Wunschliste **vollständig entkoppelt**. Man spielt also nie gegen die *Angaben* der anderen, sondern nur gegen den *Zufall* – und gegen den Zufall kann man nicht taktieren. Die beiden naheliegenden Tricks laufen deshalb ins Leere:

- **„Ich nenne zuerst einen unrealistischen Premium-Slot."** Bringt nichts: Ist er weg, rückt einfach der nächste Wunsch nach. Schlimmstenfalls bekommt man den Premium-Slot doch zugeteilt, obwohl man ihn kaum wollte, und verbraucht damit Kontingent für den eigentlichen Lieblingstermin. Unehrlichkeit kann hier nur *schaden*.
- **„Ich verschweige meinen wahren Erstwunsch und nenne etwas ‚Aussichtsreicheres'."** Sinnlos: Ob man den Lieblingstermin bekommt, hängt nur davon ab, ob er frei ist, wenn man dran ist – nicht von seiner Position auf der Liste. Setzt man ihn künstlich nach hinten, bekommt man eher einen *schlechteren* Termin und verliert den guten an jemand anderen.

In manchen anderen Verteilungsverfahren kann man durch geschicktes Lügen *anderen* etwas wegnehmen, weil die eigene Angabe deren Zuteilung mitverschiebt. Hier ist das ausgeschlossen. **Es gibt schlicht nichts zu tricksen – und genau das kann man allen ehrlich sagen.**

**Die weiteren guten Eigenschaften:**

- **Keine Verschwendung.** Es bleibt keine Wohnung frei, die jemand gewollt hätte, während eine andere Partei leer ausgeht.
- **Nachvollziehbar.** Die Ziehung lässt sich Schritt für Schritt zeigen und im Nachhinein überprüfen.

### 3.3 Der Ausgleichsfaktor (das „Karma")

Deine Idee, Verlierer beim nächsten Mal besserzustellen, ist goldrichtig – Fairness entsteht nicht in der einzelnen Losung, sondern **über die Jahre**. Damit der Faktor fair bleibt und nicht kippt, braucht er drei Regeln:

1. **Erhöhung bei echtem Verlust.** Wer einen gewünschten Zeitraum *komplett* nicht bekommt (auch keine gleichwertige Wohnung), dessen Faktor steigt um einen festen Schritt, z. B. **+0,1**, für die nächste Losung.
2. **Deckelung.** Der Faktor steigt **höchstens bis zu einer Obergrenze** (z. B. 1,5). Das verhindert, dass jemand nach mehreren Jahren einen praktisch *garantierten* Sieg ansammelt und dann den begehrtesten Slot blockiert.
3. **Rücksetzung bei Gewinn.** Gewinnt ein Mitglied einen **umkämpften** Slot (einen, um den wirklich gelost wurde), wird sein Faktor auf 1,0 zurückgesetzt. Ein Gewinn bei einem Termin, den *niemand sonst* wollte, setzt den Faktor **nicht** zurück – sonst würde man fürs bloße Buchen bestraft.

> **▶ Entscheidung der Genossenschaft (drei Stellschrauben):**
> - **Schrittweite** des Bonus pro verlorenem Jahr? (Empfehlung: +0,1 – spürbar, aber sanft.)
> - **Obergrenze** des Faktors? (Empfehlung: 1,5.)
> - **Rücksetzung** bei Gewinn: vollständig auf 1,0, oder nur teilweise reduzieren? (Empfehlung: vollständig – einfacher und gerechter.)

### 3.4 Äquivalenzklassen – welche Wohnungen sind „gleichwertig"?

Die Ausweich-Logik steht und fällt damit, welche der 12 Wohnungen als austauschbar gelten. **Das ist keine technische, sondern eine Wert-Entscheidung** – und erfahrungsgemäß die, über die am meisten diskutiert wird. Beispiel einer möglichen Einteilung:

| Klasse | Wohnungen | Merkmal |
|---|---|---|
| A | Whg 1, 2, 3 | 4 Personen, vergleichbare Lage |
| B | Whg 4, 5 | 2 Personen, mit Balkon |
| C | Whg 6–12 | … |

> **▶ Entscheidung der Genossenschaft:** Welche Wohnungen bilden welche Äquivalenzklasse? Zählt z. B. Seeblick als Unterschied? Diese Tabelle sollte **vor** der ersten Losung gemeinsam festgelegt und akzeptiert sein.

### 3.5 Gemeinsame Buchungen (Cliquen)

Falls mehrere Mitglieder gemeinsam eine Wohnung oder denselben Zeitraum buchen wollen, übernehmen wir das bewährte Fusion-Prinzip: **Eine Clique zählt als ein einziger Eintrag in der Warteschlange.** Sie gewinnt oder verliert geschlossen. So verzerrt Gruppenbildung die Chancen nicht.

> **▶ Entscheidung der Genossenschaft:** Brauchen wir Cliquen überhaupt? Falls ja: maximale Gruppengröße?

---

## 4. Teil B – Spontanbuchung

Alles, was nach der Losung frei ist, kann ganzjährig spontan gebucht werden.

1. Der Kalender zeigt **freie Lücken** – sowohl gesamt als auch pro Wohnung.
2. Buchung nach dem Prinzip **zuerst kommt, zuerst bucht**.
3. Jede Buchung wird vom **Tage-Konto** (Teil C) abgezogen.
4. Stornierte Zeiträume werden automatisch wieder als freie Lücke angezeigt.

Hier ist **kein** Losverfahren nötig – das ist erprobte Standardtechnik und der unkomplizierte Teil.

> **▶ Entscheidung der Genossenschaft:** Gibt es eine Mindest-/Höchstdauer pro Spontanbuchung? Eine Vorausbuchungsgrenze (z. B. „maximal 3 Monate im Voraus")?

---

## 5. Teil C – Tage-Konto & Übertragung

Jedes Mitglied hat ein jährliches Kontingent an Nächten. **Bereits beschlossen:** 50 Nächte pro Jahr, davon **maximal 25 über die Jahres-Wunschliste** buchbar; die übrigen Nächte stehen für die Spontanbuchung zur Verfügung.

1. **Guthaben:** 50 Nächte pro Jahr und Partei.
2. **Wunschlisten-Grenze:** höchstens 25 dieser Nächte werden in der Jahres-Losung vergeben.
3. **Abbuchung:** Jede Buchung (Losung *und* Spontan) zieht Nächte ab.
4. **Anzeige:** Jedes Mitglied sieht jederzeit sein Restguthaben.
5. **Übertragung an andere:** Ein Mitglied kann Nächte an ein anderes abgeben.
6. **Übertrag ins Folgejahr** („Banking"): nicht genutzte Nächte verfallen – oder werden begrenzt mitgenommen.

> **▶ Entscheidung der Genossenschaft:**
> - Wie viele Nächte pro Mitglied und Jahr?
> - Übertragung an andere Mitglieder: erlaubt, und falls ja, mit Obergrenze?
> - Verfallen Restnächte am Jahresende, oder dürfen einige ins Folgejahr?

---

## 6. Teil D – Dienste & Waren

Endreinigung, Saunanutzung und Ähnliches werden über dasselbe System gebucht – sie hängen einfach an einer Wohnungsbuchung.

- Dienste/Waren kosten in der Regel **Geld**, nicht Nächte (z. B. Endreinigungspauschale).
- Manche können verpflichtend sein (Endreinigung bei jeder Buchung), andere optional (Sauna).

> **▶ Entscheidung der Genossenschaft:** Welche Dienste gibt es, was kosten sie, und welche sind Pflicht? Wie wird abgerechnet (sofort, Sammelrechnung)?

---

## 7. Teil E – Externe Buchung (sicherheitskritisch)

„Von extern buchen" bedeutet: Personen **ohne** vollwertige Mitgliedschaft greifen aufs System zu. **Das ist der wichtigste Sicherheitspunkt der ganzen App** und braucht klare Regeln.

Vorgeschlagenes Vorgehen:

1. Externe buchen **nur freie Lücken** – sie nehmen **nie** an der Losung teil.
2. Zugang über **zeitlich begrenzte, persönliche Einladungs-/Buchungslinks** oder Gastkonten mit **minimalen Rechten** (nur das Nötigste sehen und tun).
3. Optional: Eine externe Buchung muss von einem Mitglied **„gesponsert"** / freigegeben werden.

> **▶ Entscheidung der Genossenschaft:**
> - Wer darf extern buchen – jeder, oder nur auf Einladung eines Mitglieds?
> - Werden externe Nächte einem Mitglieds-Konto angerechnet?

---

## 8. Datenschutz & Sicherheit (Querschnitt)

Diese Punkte gelten für die gesamte App und sind für die Genossenschaft als Zusage wichtig:

- **Deutsche Server-Infrastruktur** (Hetzner), volle Datenhoheit.
- **Etablierter Login** mit Mehr-Faktor-Schutz – nicht selbst gebaut, sondern über bewährte Komponenten (geringeres Risiko von Sicherheitslücken).
- **Verschlüsselung** der Verbindungen und der gespeicherten Daten.
- **Automatische, verschlüsselte Backups.**
- **Protokollierung** aller Buchungen und jeder Losziehung (für Nachvollziehbarkeit).
- **Datensparsamkeit:** nur erheben, was gebraucht wird; klares Löschkonzept.

---

## 9. Zusammenfassung der Entscheidungspunkte

Diese Liste kann die Genossenschaft direkt als Beschluss-Checkliste nutzen:

| # | Thema | Zu entscheiden | Empfehlung |
|---|---|---|---|
| 1 | Losung | Anzahl Wünsche pro Mitglied | 2–3 priorisiert |
| 2 | Ausgleichsfaktor | Schrittweite pro verlorenem Jahr | +0,1 |
| 3 | Ausgleichsfaktor | Obergrenze | 1,5 |
| 4 | Ausgleichsfaktor | Rücksetzung bei Gewinn | vollständig auf 1,0 |
| 5 | Äquivalenz | Einteilung der 12 Wohnungen in Klassen | gemeinsam festlegen |
| 6 | Cliquen | Nötig? Max. Größe? | optional |
| 7 | Spontan | Min./Max.-Dauer, Vorausbuchungsgrenze | offen |
| 8 | Tage-Konto | Nächte pro Mitglied/Jahr | **beschlossen: 50, davon 25 per Wunschliste** |
| 9 | Tage-Konto | Übertragung an andere erlaubt? | mit Obergrenze |
| 10 | Tage-Konto | Übertrag ins Folgejahr? | begrenzt |
| 11 | Dienste | Welche, Preise, Pflicht? | offen |
| 12 | Extern | Wer darf, mit/ohne Sponsoring? | nur auf Einladung |

---

## 10. Was daraus für die Software folgt

Sobald die Entscheidungen 1–12 getroffen sind, ist das Verfahren **eindeutig** – und damit programmierbar. Der Kern (Teil A, die Losung) ist abgeschlossene, regelbasierte Logik und lässt sich mit einer **Test-Suite** absichern: Hunderte simulierte Szenarien (viele Mitglieder, viele Pfingst-Kollisionen, Grenzfälle) belegen, dass die Verteilung tatsächlich fair und reproduzierbar ist. Genau dieser Nachweis ist das überzeugendste Argument gegenüber der Genossenschaft.

Die Teile B–E (Spontanbuchung, Tage-Konto, Dienste, externe Buchung) sind erprobte Standard-Bausteine, die auf demselben Datenmodell aufsetzen.
