# 0066 – Buchungsregeln auf den vollen Mitglieds-Anteil (Tandem-Bündelung)

## Status

Accepted (2026-06-28)

> Verfeinert ADR 0009 (Saison-Regeln in Buchung & Losung). Betrifft das Verhältnis
> **Benutzer ↔ Mitglieds-Anteil ↔ Tandem**.

## Kontext

Die Datenmodell-Kette ist `User` (Login) → `Member` (Buchungs-Subjekt, 1:1) →
`Share` (fester Tage-Anteil) → `Membership` (= **Mitglieds-Anteil**, Default
50 Tage/Jahr). Ein **Tandem** sind mehrere Nutzer, die sich **einen** Anteil teilen
(typisch 25+25 Tage); ein Nutzer kann mehreren Anteilen angehören (Mehrfach-Tandem),
seine Budgets summieren sich.

Korrekt umgesetzt waren bereits:
- **Struktur** und **Tage-Budget**: je Nutzer = Summe seiner `Share`-Anteile
  (Tandem-Partner haben getrennte, feste Budgets).
- **Losung je Benutzer**: eine Los-Partei = **ein** `Member` (nicht der ganze Anteil,
  nicht das Tandem) – so soll es sein (strategiesicher, je Konto eine Reihenfolge).

**Lücke:** Die Saison-Regeln **Parallel-Limit** (`max_parallel_units`, gleichzeitige
Wohneinheiten) und **Aufenthaltsdeckel** (`max_stay_nights`, Einheiten-Nächte) wurden
**je Benutzer** geprüft (`member.allocations`), nicht **je vollem Mitglieds-Anteil**.
Folge: Ein Tandem (2 Nutzer auf 1 Anteil) bekam diese Grenzen **doppelt** – jeder
Nutzer schöpfte sie eigenständig aus. Die fachliche Vorgabe ist aber: die
**Buchungsregeln gelten auf den vollen Anteil**.

Erschwernis: Eine `Allocation` trug **nur** `member`, keinen Bezug zum konkreten
`Membership`. Bei einem Mehrfach-Tandem ist daher nicht eindeutig, welchem Anteil eine
Buchung „gehört" – ohne Attribution lässt sich die Grenze nicht exakt zuordnen.

## Entscheidung

**Exakte Zurechnung Buchung/Wunsch → Mitglieds-Anteil.** `Allocation` und `Wish`
bekommen je einen optionalen FK **`membership`**. Damit zählen Parallel-Limit und
Aufenthaltsdeckel über den **vollen Anteil inkl. aller Tandem-Partner** – exakt auch
im Mehrfach-Tandem-Fall.

1. **Zurechnung (`Member.membership_for`)**: bei genau **einem** Anteil automatisch
   dieser; bei **mehreren** der explizit gewählte, sonst deterministisch der größte
   (Tage-Anteil, dann id). Ohne Anteil (externer Gast) bleibt es leer.
2. **Buchung** (`book_spontaneous` → `check_booking_rules(member, …, membership)`):
   die schon vorhandenen Belegungen kommen aus `Allocation.objects.filter(membership=…)`
   – also über **alle** Nutzer dieses Anteils, nicht nur den einzelnen.
3. **Losung** (rein, `lottery.run_lottery`): die Saison-Regeln über mehrere Buchungen
   werden je **`rule_group`** gebündelt statt je Partei. Die Gruppe ist der Anteil:
   Tandem-Partner (verschiedene Parteien, gleicher Anteil) teilen sich die Grenzen,
   das **Budget** (Wunsch-Tage) bleibt **je Partei** getrennt. Ohne `rule_group` fällt
   die Gruppe auf die Partei zurück → das alte Verhalten (Regression-sicher, alle
   bisherigen Tests grün). Der Los-Gewinn wird über den Quell-Wunsch dem Anteil
   zugeschrieben; `verify_lottery` baut dieselbe `rule_group` → Reproduzierbarkeit
   (Commit-Reveal, ADR 0062) bleibt erhalten.
4. **UI** nur bei Mehrfach-Tandem: ein schlanker **Anteil-Auswähler** auf der
   Buchungs-Bestätigung und je Wunsch in der Wunschliste (erscheint erst ab **zwei**
   Anteilen – der Normalfall „ein Anteil" bleibt unverändert und ohne Mehrklick).
5. **Bestandsdaten** (Daten-Migration): vorhandene Buchungen/Wünsche werden dem Anteil
   zugerechnet – **nur**, wenn der Nutzer **eindeutig** einem Anteil angehört (der
   übliche Tandem-Fall: beide Partner sind je in genau einem Anteil → beide werden
   zugeordnet → die Bündelung greift). Mehrdeutige Altfälle bleiben leer.

## Betrachtete Alternativen

- **Bündelung über `tandem_partners` ohne FK** (Vereinigung aller Partner): einfacher,
  aber im Mehrfach-Tandem **unscharf** (vermischt fremde Anteile) – verworfen
  zugunsten exakter Zurechnung.
- **Status quo (je Benutzer)**: widerspricht der fachlichen Vorgabe (Tandem bekäme die
  Grenzen doppelt) – verworfen.
- **Losung je Anteil statt je Benutzer**: würde die Strategiesicherheit/Reihenfolge je
  Konto aufgeben – bewusst **nicht** geändert (Losung bleibt je Benutzer).

## Konsequenzen

**Positiv** – Parallel-Limit und Aufenthaltsdeckel wirken fachlich korrekt auf den
vollen Anteil (auch über Tandem-Partner und in der Losung); die Zurechnung ist exakt
und im Backend sichtbar (Spalte/Filter). Der Normalfall (ein Anteil) braucht **keine**
zusätzliche Eingabe. **Grenzen** – die Bündelung im Los-Algorithmus betrachtet wie
bisher nur die **laufeigenen** Zuteilungen (vorbestehende Buchungen desselben Anteils
fließen dort nicht ein – dokumentierte Grenze, ADR 0009). Mehrdeutige **Alt**-Buchungen
eines Mehrfach-Tandems bleiben ohne Anteil (neue tragen ihn immer). Das Tage-**Budget**
bleibt bewusst **je Nutzer/Anteil** getrennt (kein gemeinsamer Topf – dafür gibt es den
Solidaritäts-Pool, ADR 0064).
