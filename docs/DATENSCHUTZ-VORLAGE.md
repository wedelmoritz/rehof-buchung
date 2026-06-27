# Datenschutzerklärung – einfache Vorlage & Checkliste

> **Keine Rechtsberatung.** Diese Vorlage ist ein **Startpunkt**, der die in dieser
> App tatsächlich anfallenden Verarbeitungen abdeckt. Die Genossenschaft muss sie
> prüfen, anpassen und verantworten – im Zweifel anwaltlich prüfen lassen.

## So gehst du vor

1. Den Vorlagetext unten kopieren.
2. Im Backend unter **„Rechtliche & Zahlungs-Einstellungen“** ins Feld
   **„Datenschutzerklärung“** einfügen (früher „Hofladen-Einstellungen“).
3. Alle **[Platzhalter in eckigen Klammern]** durch eure Angaben ersetzen.
4. Speichern → die Seite ist unter **/datenschutz/** erreichbar und im Seiten-Fuß
   verlinkt.

## Checkliste – diese Punkte sind individuell

| Punkt | Was zu tun ist |
|---|---|
| **Verantwortlicher** | Name der eG, Anschrift, Vorstand, Kontakt-E-Mail (steht meist schon in den Einstellungen). |
| **Hosting** | Wer betreibt den Server? (Standard hier: Hetzner, Deutschland.) Auftragsverarbeitungs-Vertrag (AVV) abschließen. |
| **Zahlungsdienstleister** | Nur relevant, wenn Online-Bezahlung aktiv ist (Mollie). Sonst diesen Absatz streichen. |
| **E-Mail-Versand** | Über welchen Anbieter laufen die Benachrichtigungs-Mails? (SMTP-Dienst nennen oder „kein externer Versand“.) |
| **Speicherdauer** | Steuerlich relevante Daten (Rechnungen) i. d. R. **10 Jahre**; sonstige Daten löschen, wenn nicht mehr nötig. |
| **Aufsichtsbehörde** | Zuständige Landes-Datenschutzbehörde nennen (nach Sitz der eG). |
| **Datenschutzbeauftragte:r** | Nur falls bestellt (oft nicht verpflichtend bei kleinen eG) – sonst Absatz streichen. |
| **Cookies/Tracking** | Diese App setzt nur **technisch notwendige** Session-/CSRF-Cookies, **kein** Tracking/Analyse. Falls ihr nichts ergänzt, passt der Vorlage-Absatz. |

## Vorlage (zum Kopieren)

```
Datenschutzerklärung

1. Verantwortlicher
[Name der Genossenschaft eG], [Straße Nr.], [PLZ Ort]
Vertreten durch den Vorstand: [Namen]
E-Mail: [kontakt@…]

2. Welche Daten wir verarbeiten und wozu
Wir verarbeiten personenbezogene Daten, soweit das für den Betrieb der
Mitglieder- und Buchungsplattform erforderlich ist:
- Mitglieder: Name, Anschrift, E-Mail, ggf. IBAN, Mitgliedsnummer, Buchungen,
  Wünsche und Hofladen-Einkäufe.
- Externe Gäste: Name, Anschrift, E-Mail und Buchungsdaten.
- Abrechnung: Rechnungsdaten (Pflichtangaben nach §14 UStG).
- Technisch: Server-Protokolle (IP-Adresse, Zeitpunkt) zur Sicherheit und
  Fehlersuche; Session-/CSRF-Cookies für die Anmeldung (technisch notwendig).

Rechtsgrundlagen sind die Erfüllung des Mitglieds-/Nutzungsverhältnisses bzw. des
Beherbergungsvertrags (Art. 6 Abs. 1 lit. b DSGVO), die Erfüllung rechtlicher
Pflichten – insbesondere steuer-/handelsrechtlicher Aufbewahrung – (Art. 6 Abs. 1
lit. c DSGVO) sowie unser berechtigtes Interesse an einem sicheren Betrieb
(Art. 6 Abs. 1 lit. f DSGVO).

3. Empfänger / Auftragsverarbeiter
- Hosting: [Anbieter, z. B. Hetzner Online GmbH, Deutschland].
- Zahlungsabwicklung (nur bei Online-Bezahlung): [Mollie B.V., Niederlande].
- E-Mail-Versand: [Anbieter / „Versand über unseren Server“].
Mit diesen Dienstleistern bestehen, soweit erforderlich, Verträge zur
Auftragsverarbeitung (Art. 28 DSGVO).

4. Speicherdauer
Wir speichern Daten nur so lange, wie es für die genannten Zwecke nötig ist.
Rechnungs- und steuerrelevante Unterlagen bewahren wir entsprechend den
gesetzlichen Fristen auf (in der Regel zehn Jahre).

5. Cookies
Es werden ausschließlich technisch notwendige Cookies (Anmeldung, Sicherheit)
gesetzt. Es findet kein Tracking und keine Reichweitenanalyse statt.

6. Deine Rechte
Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der
Verarbeitung, Datenübertragbarkeit und Widerspruch. Außerdem kannst du dich bei
einer Datenschutz-Aufsichtsbehörde beschweren; zuständig ist
[zuständige Landesbehörde].

7. Kontakt in Datenschutzfragen
[kontakt@…]

Stand: [Monat Jahr]
```

## Hinweise für AGB & Impressum

- **Impressum** wird im selben Backend-Bereich aus den Stammdaten erzeugt
  (Name, Anschrift, Vorstand, Register, Steuernummer/USt-IdNr., Kontakt) – nur die
  Felder ausfüllen.
- **AGB** sind nicht zwingend, bei Beherbergung/Storno aber empfohlen. Die
  Stornofristen stehen bereits in den Externe-Gäste-Einstellungen; die AGB können
  darauf verweisen.
