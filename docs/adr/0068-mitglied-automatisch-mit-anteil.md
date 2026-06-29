# 0068 – „Mitglied" und „Mitglieds-Anteil": getrennt, aber automatisch verknüpft

## Status

Accepted (2026-06-29)

> Verfeinert ADR 0056 (geführtes Onboarding). Beantwortet die Frage „Warum sind
> Mitglied und Mitglieds-Anteil getrennt?" und vereinfacht die Zuordnung.

## Kontext

Beim Anlegen eines Mitglieds über das Benutzer-Formular entstand bisher **nur** das
Mitglieds-Profil (`Member`), **kein** Mitglieds-Anteil (`Membership`/`Share`). Die
Person konnte danach noch **nicht buchen** (kein Tage-Budget), und die Verknüpfung
musste in einem **zweiten** Schritt am „Mitglieds-Anteil" hergestellt werden. Das
war verwirrend – der Eindruck: „Mitglied und Anteil müssten doch automatisch
zusammenhängen."

**Sollte man `Member` und `Membership` also zu EINEM Modell verschmelzen?** Nein –
die Trennung hat einen echten fachlichen Grund:

- **`Member`** = die buchende **Person** (ein Login): Anzeigename, Karma, Rechnungs-
  daten, Terminal-PIN. Pro Konto genau eine.
- **`Membership` (Mitglieds-Anteil)** = ein **Genossenschafts-Anteil** (eine
  Vielleben-eG-Nummer) mit Jahres-Tagebudget (50). Das ist eine **wirtschaftlich/
  rechtliche Einheit**, unabhängig davon, wer sich einloggt.
- Verbunden über **`Share`** (fester Tage-Anteil) als **n:m**:
  - **Ein Anteil → mehrere Personen** = **Tandem** (z. B. 25 + 25 Tage),
  - **Eine Person → mehrere Anteile** (Budgets summieren sich).

Analogie: Anteil = **Genossenschafts-Konto**, Person = **Kontoinhaber**. Ein Konto
kann mehrere Inhaber haben (Tandem), eine Person mehrere Konten – darum trennt man
„Person" und „Konto" und verbindet sie über eine Zuordnung. Eine Verschmelzung
würde das **Tandem**-Modell unmöglich machen (auf dem u. a. ADR 0066 –
Buchungsregeln je vollem Anteil – aufbaut).

## Entscheidung

**Trennung beibehalten, aber die Verknüpfung automatisch und sichtbar machen** –
für den Normalfall (Voll-Mitglied = eine Person, ein voller Anteil) ohne Extra-
Schritt:

1. **Auto-Voll-Anteil** (`services.ensure_personal_membership`, idempotent): Wird im
   Benutzer-Formular ein **buchendes** Mitglieds-Profil gespeichert, das noch
   **keinen** Anteil hat, legt `UserAdmin.save_related` **automatisch einen vollen
   Mitglieds-Anteil (50/25)** an und ordnet die Person voll zu. Sie kann sofort
   buchen. Übersprungen wird, wer schon einen Anteil hat (auch als Tandem-Partner)
   oder ein **Hofladen-Gast** (`is_external`) ist. Die **eG-Nummer** trägt die
   Verwaltung später nach.
2. **Sichtbar zueinander:** Das Benutzer-Formular zeigt im Mitglieds-Profil eine
   **„Mitglieds-Anteil(e)"-Übersicht** (Anteil + Tage-Anteil + Link, Tandem-Hinweis,
   Gesamtbudget). Umgekehrt zeigt der „Mitglieds-Anteil" wie bisher seine Nutzer
   (`ShareInline`). So stehen Mitglied und Anteil auf **beiden** Seiten beieinander.
3. **Tandem bleibt bewusst:** Ein geteilter Anteil entsteht, indem man am Anteil
   weitere Nutzer mit ihrem Tage-Anteil ergänzt (oder im geführten Onboarding einen
   **bestehenden** Anteil wählt) – nicht automatisch.

Das **geführte Onboarding** (ADR 0056) bleibt für neue Konten der komfortable Weg
(es ordnet Profil **und** Anteil in einem Schritt zu und erlaubt die Tandem-Wahl);
der Auto-Voll-Anteil ist das Sicherheitsnetz für den direkten Benutzer-Formular-Weg.

## Betrachtete Alternativen

- **`Member` und `Membership` verschmelzen:** verworfen – würde Tandems (mehrere
  Personen je Anteil) und Mehrfach-Anteile unmöglich machen und ADR 0066 untergraben.
- **Anteil weiter manuell in zweitem Schritt:** der Status quo, der genau die
  Verwirrung erzeugt hat – verworfen.
- **Anteilig fürs Anlagejahr (wie die Onboarding-Vorgabe):** für den automatischen,
  unsichtbaren Weg bewusst NICHT – „voller Anteil = 50 Tage" ist als Vorgabe
  verständlicher; unterjährig kann die Verwaltung den Tage-Anteil anpassen.

## Konsequenzen

**Positiv** – „Mitglied anlegen" macht die Person sofort buchbar; Mitglied und
Anteil sind im Backend immer miteinander verknüpft und beidseitig sichtbar; die
Trennung bleibt nur dort sichtbar, wo sie gebraucht wird (Tandem/Mehrfach-Anteil).
**Grenzen** – legt man jemanden direkt übers Benutzer-Formular an, der eigentlich
einem **bestehenden** Tandem-Anteil beitreten soll, entsteht zunächst ein eigener
Voll-Anteil (die Meldung weist auf das Aufteilen hin); für diesen Fall ist das
geführte Onboarding der bessere Weg. Auto-Anteile haben anfangs **keine eG-Nummer**
(nachzutragen).
