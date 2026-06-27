# 0039 – Eingabe-Validierung der Benutzereingaben und XSS-/Injektions-Härtung

## Status

Accepted (2026-06-27)

## Kontext

Mehrere Seiten nehmen freie Benutzereingaben entgegen: **Registrierung** (Name),
**Profil** (Name, Straße, PLZ, Ort, IBAN, Mitgliedsnummer), **externe Gäste-Buchung**
(Name, E-Mail, Adresse) sowie Freitext (Begleitung, Wechselwunsch-Nachricht,
Übertrags-Notiz, Hofladen-Katalog der Verwaltung). Diese Daten landen nicht nur in
HTML-Seiten, sondern auch in **Rechnungs-PDFs**, **E-Mails** und **CSV-/xlsx-Exporten**.

Zwei Anforderungen: (1) **Plausibilität** – Namen bestehen aus Buchstaben, PLZ aus
genau 5 Ziffern, IBAN korrekte Länge **und** Prüfsumme usw. (2) **Sicherheit** –
keine gespeicherten Cross-Site-Scripting-Nutzlasten und keine CSV-/Formel-Injektion.

## Entscheidung

**Reine, Django-freie Validierungslogik** in `booking/validation.py` (passt zur
Schicht-Trennung aus ADR 0002, isoliert getestet in `tests/test_validation.py`),
plus dünne Anbindung in Formularen/Service-Layer und Härtung der Exporte.

- **Plausibilitäts-Prüfer** (`*_error(...) -> str | None`):
  `name_error` (nur Buchstaben inkl. Umlaute/Akzente + ` - ' .`),
  `plz_error` (genau 5 Ziffern, deutsche Adressen),
  `city_error` (Buchstaben + `- . ' ( ) /`, z. B. „Frankfurt (Oder)"),
  `street_error` (inkl. Hausnummer), `email_error`,
  `iban_error` (Format + **länderspezifische Länge** + **Mod-97-Prüfsumme**,
  ISO 13616). `strip_controls` säubert Freitext.
- **Anbindung:** `RegistrationForm.clean_name`, `ProfileForm.clean_*`
  (`forms.py`); `services.create_external_booking` prüft die Gastdaten und gibt
  bei Verstoß einen Fehlertext zurück (die Eingabeseite zeigt ihn an). Freitext
  (Begleitung/Nachricht/Notiz, Katalog-Namen) wird über `strip_controls` von
  Steuerzeichen befreit und längenbegrenzt.
- **XSS-Posture:** Django-Templates escapen alle Ausgaben automatisch; das einzige
  `|safe` steht auf einem **entwicklerdefinierten** `help_text` (kein
  Nutzer-Input). Zusätzlich weisen die Prüfer Markup (`<`/`>`) und Steuerzeichen in
  Namen/Orten/Adressen ab (Defense-in-Depth für PDF/E-Mail/Export).
- **CSV-/Formel-Injektion:** `exports.py` stellt Textzellen, die mit `= + - @ \t \r`
  beginnen, ein `'` voran (`_safe_cell`), damit Excel/Calc sie nicht als Formel
  ausführt – für CSV **und** xlsx.

## Betrachtete Alternativen

- **Nur auf Djangos Auto-Escaping vertrauen:** schützt die HTML-Ausgabe, aber nicht
  PDF/E-Mail/Export; liefert auch keine fachliche Plausibilität.
- **Validierung direkt in den Formularen (ohne reines Modul):** nicht ohne Django
  testbar und im Service-Layer (externe Buchung) nicht wiederverwendbar.
- **Strikte „nur A–Z"-Namen:** würde echte Namen (Umlaute, Akzente, Bindestrich,
  Apostroph) abweisen – verworfen zugunsten Unicode-Buchstaben + üblicher Satzzeichen.
- **Internationale PLZ/Adressen sofort:** zurückgestellt (siehe Konsequenzen).

## Konsequenzen

**Positiv**
- Einheitliche, isoliert getestete Prüfungen über Web-Formulare **und** Service-Layer.
- IBAN wird echt geprüft (Länge + Mod-97), nicht nur „sieht aus wie".
- Geringeres Risiko bei Export/PDF/E-Mail (Markup-/Steuerzeichen-Abwehr,
  Formel-Injektion entschärft).

**Negativ / Grenzen**
- **Annahme deutsche Adressen:** PLZ = 5 Ziffern, IBAN-Längen primär für DACH/EU.
  Für internationale Gäste bräuchte es ein Land-Feld (`Guest.country` existiert,
  wird im Formular noch nicht abgefragt) und länderabhängige Regeln – bewusst offen.
- Sehr seltene Namensformen (z. B. mit Ziffern) werden abgewiesen; im Zweifel
  pflegt die Verwaltung den Datensatz.
